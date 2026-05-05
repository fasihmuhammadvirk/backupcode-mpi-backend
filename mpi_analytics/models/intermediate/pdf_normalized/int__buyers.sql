/* Intermediate model for buyer normalization and explicit mapping */

{{ config(
  materialized='view',
  schema='intermediate'
) }}

-- Source the buyer universe from the same switching layer the rest of the
-- pipeline uses (int__extracted_data_switched), instead of the old-pipeline-only
-- int__model_extracted_data. Otherwise distinct buyers that exist only in the
-- new normalized pipeline (int__extracted_data_combined_compat) are missing
-- here, the LEFT JOIN in int__invoice_items_with_normalized_fields fails for
-- those rows, buyer_normalized_canonical comes back NULL, and the mart's
-- `buyer` column (aliased from buyer_normalized_canonical) shows blank in the
-- data review page even though the raw extraction had the buyer value. (#870)
WITH distinct_buyers AS (
    SELECT DISTINCT
        buyer
    FROM {{ ref('int__extracted_data_switched') }}
    WHERE is_active = true
      AND buyer IS NOT NULL
      AND TRIM(buyer) != ''
),

buyer_counts AS (
    -- Count occurrences so auto-canonicalization prefers the most common "full" buyer value.
    SELECT
        buyer,
        COUNT(*)::bigint AS buyer_count
    FROM {{ ref('int__extracted_data_switched') }}
    WHERE is_active = true
      AND buyer IS NOT NULL
      AND TRIM(buyer) != ''
    GROUP BY buyer
),

normalized_buyers AS (
    -- Step 1: Normalize buyer into "Alpha Numeric" (Title Case alpha; digits grouped)
    -- Inline normalization logic (no function dependency)
    SELECT
        buyer AS original_buyer,
        CASE
            WHEN buyer IS NULL OR TRIM(buyer) = '' THEN buyer
            ELSE
                -- Remove all non-alphanumeric, then extract alpha and numeric parts
                CASE
                    WHEN REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g') != ''
                         AND REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g') != ''
                    THEN
                        -- Format as "Alpha Numeric" with Title Case
                        INITCAP(REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g')) || ' ' ||
                        REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g')
                    WHEN REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g') != ''
                    THEN
                        INITCAP(REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g'))
                    WHEN REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g') != ''
                    THEN
                        REGEXP_REPLACE(REGEXP_REPLACE(buyer, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g')
                    ELSE ''
                END
        END AS buyer_normalized_base
    FROM distinct_buyers
),

normalized_buyers_enriched AS (
    SELECT
        nb.original_buyer,
        nb.buyer_normalized_base,
        REGEXP_REPLACE(COALESCE(nb.buyer_normalized_base, ''), '[^A-Za-z]', '', 'g') AS alpha_part,
        REGEXP_REPLACE(COALESCE(nb.buyer_normalized_base, ''), '[^0-9]', '', 'g') AS numeric_part,
        COALESCE(bc.buyer_count, 0)::bigint AS buyer_count
    FROM normalized_buyers nb
    LEFT JOIN buyer_counts bc
        ON bc.buyer = nb.original_buyer
),

buyer_typo_overrides_raw AS (
    {#-
      Flatten `buyer_typo_map()` into (canonical_raw, variant_raw) rows.
      This provides explicit, deterministic mappings for buyer name normalization.
    -#}
    {% set m = buyer_typo_map() %}
    {% set ns = namespace(rows=[]) %}
    {% for canonical, variants in m.items() %}
        {% for variant in variants %}
            {% set c_escaped = canonical | replace("'", "''") %}
            {% set v_escaped = variant | replace("'", "''") %}
            {% set row_str = "('" ~ c_escaped ~ "'::text, '" ~ v_escaped ~ "'::text)" %}
            {% set ns.rows = ns.rows + [row_str] %}
        {% endfor %}
    {% endfor %}
    {% if ns.rows | length == 0 %}
    SELECT NULL::text AS canonical_raw, NULL::text AS variant_raw WHERE FALSE
    {% else %}
    SELECT
        t.canonical_raw,
        t.variant_raw
    FROM (
        VALUES {{ ns.rows | join(', ') }}
    ) AS t(canonical_raw, variant_raw)
    {% endif %}
),

buyer_typo_overrides_norm AS (
    -- Normalize variants for matching, but KEEP canonical in display form (with spaces)
    -- This allows: "Mordchaideutch" -> "Mordchai Deutch" (display), even though the
    -- normalized key becomes "Mordchaideutch".
    --
    -- Also dedupe on variant_norm in case multiple raw variants collapse to the same norm.
    SELECT
        variant_norm,
        (ARRAY_AGG(canonical_display ORDER BY LENGTH(canonical_display) DESC))[1] AS canonical_display
    FROM buyer_typo_overrides_raw
    CROSS JOIN LATERAL (
        SELECT
            -- Inline normalization logic for variant_raw (no function dependency)
            CASE
                WHEN variant_raw IS NULL OR TRIM(variant_raw) = '' THEN variant_raw
                ELSE
                    CASE
                        WHEN REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g') != ''
                             AND REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g') != ''
                        THEN
                            INITCAP(REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g')) || ' ' ||
                            REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g')
                        WHEN REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g') != ''
                        THEN
                            INITCAP(REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^A-Za-z]', '', 'g'))
                        WHEN REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g') != ''
                        THEN
                            REGEXP_REPLACE(REGEXP_REPLACE(variant_raw, '[^A-Za-z0-9]', '', 'g'), '[^0-9]', '', 'g')
                        ELSE ''
                    END
            END AS variant_norm,
            TRIM(REGEXP_REPLACE(canonical_raw, '[[:space:]]+', ' ', 'g')) AS canonical_display
    ) x
    WHERE variant_raw IS NOT NULL AND TRIM(variant_raw) != ''
    GROUP BY variant_norm
),

mapped_buyers AS (
    -- Apply mapping AFTER normalization:
    -- 1) compute buyer_normalized_base
    -- 2) lookup mapping in buyer_typo_map.sql
    -- 3) if found -> mapped canonical
    -- 4) else auto-canonicalize truncated numeric suffixes (same alpha, digits are prefix of a longer digits value)
    -- 5) else -> buyer_normalized_base
    SELECT
        nb.original_buyer,
        nb.buyer_normalized_base,
        COALESCE(
            bo.canonical_display,
            ac.auto_canonical_base,
            nb.buyer_normalized_base
        ) AS buyer_normalized_canonical
    FROM normalized_buyers_enriched nb
    LEFT JOIN buyer_typo_overrides_norm bo
        ON bo.variant_norm = nb.buyer_normalized_base
    LEFT JOIN LATERAL (
        SELECT
            nb2.buyer_normalized_base AS auto_canonical_base
        FROM normalized_buyers_enriched nb2
        WHERE bo.canonical_display IS NULL  -- Only auto-canonicalize if no explicit mapping exists
          AND nb.alpha_part != ''
          AND nb.numeric_part != ''
          AND LENGTH(nb.numeric_part) >= 4  -- Only for buyers with at least 4 digits
          AND nb2.alpha_part = nb.alpha_part  -- Same name part
          AND nb2.numeric_part != ''
          AND nb2.numeric_part LIKE nb.numeric_part || '%'  -- nb's digits are a prefix of nb2's digits
          AND LENGTH(nb2.numeric_part) > LENGTH(nb.numeric_part)  -- nb2 has more digits (longer phone number)
        ORDER BY
            nb2.buyer_count DESC,  -- Prefer most common
            LENGTH(nb2.numeric_part) DESC,  -- Prefer longest phone number
            nb2.buyer_normalized_base
        LIMIT 1
    ) ac ON (bo.canonical_display IS NULL)  -- Only execute LATERAL join when no explicit mapping exists
)

SELECT
    original_buyer AS buyer,
    buyer_normalized_base,
    buyer_normalized_canonical
FROM mapped_buyers

