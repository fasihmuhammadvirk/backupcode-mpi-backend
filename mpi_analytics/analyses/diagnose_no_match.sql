/*
Diagnostic: Investigate why items are not matching

Run with: dbt compile -s diagnose_no_match && psql -f target/compiled/mpi_analytics/analyses/diagnose_no_match.sql
Or copy the compiled SQL and run directly
*/

-- 1. Sample of no_match items
WITH no_match_items AS (
    SELECT
        item,
        description,
        vendor,
        COUNT(*) as occurrences
    FROM {{ ref('int__invoice_items_mapped') }}
    WHERE mapping_type = 'no_match'
    GROUP BY item, description, vendor
    ORDER BY occurrences DESC
    LIMIT 20
),

-- 2. Check if these items exist in permanent mappings (case-insensitive)
permanent_check AS (
    SELECT
        nm.item AS invoice_item,
        nm.vendor,
        nm.occurrences,
        pm.supplier_item AS permanent_supplier_item,
        pm.mpi_code,
        pm.supplier
    FROM no_match_items nm
    LEFT JOIN {{ ref('int__permanent_mappings') }} pm
        ON LOWER(TRIM(nm.item)) = LOWER(TRIM(pm.supplier_item))
),

-- 3. Check if these items exist in temporary mappings (case-insensitive)
temporary_check AS (
    SELECT
        nm.item AS invoice_item,
        nm.vendor,
        nm.occurrences,
        tm.original_item AS temp_original_item,
        tm.sheet_name
    FROM no_match_items nm
    LEFT JOIN {{ ref('int__temporary_mappings') }} tm
        ON LOWER(TRIM(nm.item)) = LOWER(TRIM(tm.original_item))
)

-- Final diagnostic output
SELECT
    '=== NO MATCH ITEMS ANALYSIS ===' AS section,
    NULL AS invoice_item,
    NULL AS vendor,
    NULL AS occurrences,
    NULL AS found_in_permanent,
    NULL AS found_in_temporary,
    NULL AS permanent_mpi_code,
    NULL AS temp_sheet_name

UNION ALL

SELECT
    'Sample no_match items' AS section,
    pc.invoice_item,
    pc.vendor,
    pc.occurrences,
    CASE WHEN pc.permanent_supplier_item IS NOT NULL THEN 'YES (case-insensitive)' ELSE 'NO' END AS found_in_permanent,
    CASE WHEN tc.temp_original_item IS NOT NULL THEN 'YES (case-insensitive)' ELSE 'NO' END AS found_in_temporary,
    pc.mpi_code AS permanent_mpi_code,
    tc.sheet_name AS temp_sheet_name
FROM permanent_check pc
LEFT JOIN temporary_check tc ON pc.invoice_item = tc.invoice_item
ORDER BY section, occurrences DESC NULLS LAST
