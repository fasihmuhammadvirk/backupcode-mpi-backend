/*
Intermediate model for vendor normalization using two-tier fuzzy matching.

Two-Tier Matching Strategy:
  TIER 1: Fuzzy match against vendor_variants_map() variants (0.6 threshold)
          Maps abbreviated/alternate names to canonical suppliers
  TIER 2: Direct fuzzy match against public.suppliers (0.7 threshold)
          Catches typos and minor variations

Example: "YS Plumbing LLC" → matches "YS Plumbing" variant → "Y & S Plumbing Supply"

Data lineage:
  int__invoice_items_mapped (vendor) + stg__suppliers + vendor_variants_map()
  → THIS MODEL → int__invoice_items_with_normalized_fields
*/

{{ config(
    materialized='view',
    schema='intermediate'
) }}

{# Flatten vendor variants map into (canonical, variant) rows #}
{%- set vendor_map = vendor_variants_map() -%}

WITH distinct_vendors AS (
    -- Get all distinct vendor values from mapped invoice items
    SELECT DISTINCT vendor
    FROM {{ ref('int__invoice_items_mapped') }}
    WHERE is_active = true
      AND vendor IS NOT NULL
      AND TRIM(vendor) != ''
),

suppliers AS (
    SELECT * FROM {{ ref('stg__suppliers') }}
),

-- Flatten the vendor variants map into rows
vendor_variants AS (
    {% for canonical, variants in vendor_map.items() %}
    {% for variant in variants %}
    SELECT '{{ canonical }}' AS canonical_supplier, '{{ variant }}' AS variant_key
    {% if not loop.last %}UNION ALL{% endif %}
    {% endfor %}
    {% if not loop.last %}UNION ALL{% endif %}
    {% endfor %}
),

-- TIER 1: Fuzzy match against variant keys (lower threshold since variants are explicit)
variant_matches AS (
    SELECT
        dv.vendor,
        vv.canonical_supplier,
        vv.variant_key AS matched_variant,
        SIMILARITY(LOWER(dv.vendor), LOWER(vv.variant_key)) AS variant_similarity,
        ROW_NUMBER() OVER (
            PARTITION BY dv.vendor
            ORDER BY SIMILARITY(LOWER(dv.vendor), LOWER(vv.variant_key)) DESC
        ) AS variant_rank
    FROM distinct_vendors dv
    CROSS JOIN vendor_variants vv
    WHERE SIMILARITY(LOWER(dv.vendor), LOWER(vv.variant_key)) >= 0.6
),

-- TIER 2: Direct fuzzy match against suppliers (higher threshold for precision)
supplier_matches AS (
    SELECT
        dv.vendor,
        s.supplier_id,
        s.supplier_name,
        SIMILARITY(LOWER(dv.vendor), LOWER(s.supplier_name)) AS similarity_score,
        ROW_NUMBER() OVER (
            PARTITION BY dv.vendor
            ORDER BY SIMILARITY(LOWER(dv.vendor), LOWER(s.supplier_name)) DESC
        ) AS match_rank
    FROM distinct_vendors dv
    CROSS JOIN suppliers s
    WHERE SIMILARITY(LOWER(dv.vendor), LOWER(s.supplier_name)) >= 0.7
)

SELECT
    dv.vendor,
    -- Priority: variant match > direct supplier match > original value
    COALESCE(
        vm.canonical_supplier,
        sm.supplier_name,
        dv.vendor
    ) AS vendor_normalized,
    -- Matched supplier info (for downstream use)
    COALESCE(vm.canonical_supplier, sm.supplier_name) AS matched_supplier_fuzzy,
    s.supplier_id AS matched_supplier_id_fuzzy,
    -- Match metadata
    CASE
        WHEN vm.canonical_supplier IS NOT NULL THEN vm.variant_similarity
        ELSE sm.similarity_score
    END AS similarity_score,
    CASE
        WHEN vm.canonical_supplier IS NOT NULL THEN 'variant'
        WHEN sm.supplier_name IS NOT NULL THEN 'direct'
        ELSE NULL
    END AS match_type,
    vm.matched_variant
FROM distinct_vendors dv
LEFT JOIN variant_matches vm
    ON dv.vendor = vm.vendor
    AND vm.variant_rank = 1
LEFT JOIN supplier_matches sm
    ON dv.vendor = sm.vendor
    AND sm.match_rank = 1
    AND vm.canonical_supplier IS NULL  -- Only use direct match if no variant match
LEFT JOIN suppliers s
    ON COALESCE(vm.canonical_supplier, sm.supplier_name) = s.supplier_name
