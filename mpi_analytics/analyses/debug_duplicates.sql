-- Analysis: Debug duplicate patterns in int__model_extracted_data
-- This analysis helps us understand what's causing the any duplicates

WITH duplicate_groups AS (
    SELECT
        vendor,
        ref_no,
        date,
        item,
        COUNT(*) as duplicate_count
    FROM {{ ref('int__model_extracted_data') }}
    GROUP BY vendor, ref_no, date, item
    HAVING COUNT(*) > 1
),

detailed_duplicates AS (
    SELECT
        d.vendor,
        d.ref_no,
        d.date,
        d.item,
        g.duplicate_count,
        d.invoice_items_id,
        d.date_added,
        d.invoice_id,
        d.description,
        d.amount_raw,
        d.cost_raw,
        d.qty_raw,
        -- Add ranking to see window function behavior
        ROW_NUMBER() OVER (
            PARTITION BY d.vendor, d.ref_no, d.date, d.item
            ORDER BY d.date_added DESC NULLS LAST, d.invoice_items_id DESC
        ) as manual_rank
    FROM duplicate_groups g
    JOIN {{ ref('int__model_extracted_data') }} d
        ON g.vendor = d.vendor
        AND g.ref_no = d.ref_no
        AND g.date = d.date
        AND g.item = d.item
)

SELECT
    vendor,
    ref_no,
    date,
    item,
    duplicate_count,
    invoice_items_id,
    date_added,
    description,
    amount_raw,
    manual_rank,
    -- Show if these should have been deduped
    CASE WHEN manual_rank = 1 THEN 'SHOULD_KEEP' ELSE 'SHOULD_REMOVE' END as expected_action
FROM detailed_duplicates
ORDER BY duplicate_count DESC, ref_no, manual_rank
LIMIT 30
