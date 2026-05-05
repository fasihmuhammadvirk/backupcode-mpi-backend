-- mart__quickbooks_preview.sql
--
-- Pre-computed QuickBooks export preview rows for both 'all' and 'unprocessed' filters.
--
-- Refactored to:
--   1. Aggregate items in two modes: 'all' (entire invoice) and 'unprocessed' (unexported items).
--   2. Store the result as a single row per invoice_id.
--   3. Enable partial-invoice exports by pre-calculating the remaining subtotal/tax.
--
-- Each output row represents one unique invoice.
--
-- Tax rate is defined in dbt_project.yml vars

{{
    config(
        materialized='table',
        tags=['quickbooks', 'export', 'reporting'],
        indexes=[
            {'columns': ['date']},
            {'columns': ['invoice_id']},
            {'columns': ['ref_no', 'vendor', 'date']}
        ],
        post_hook=[
            "ANALYZE {{ this }}"
        ]
    )
}}

-- ============================================================
-- STEP 1: Base — filter raw mart items
-- ============================================================
WITH base AS (
    SELECT
        invoice_items_id                            AS id,
        invoice_id,
        ref_no,
        vendor,
        "date",
        customer_job,
        amount,
        date_added,
        sheet_name,
        class_,
        COALESCE(NULLIF(TRIM(assigned_account), ''), NULLIF(TRIM(account), ''))
                                                    AS raw_account,
        mpi_item,
        item,
        description,
        memo,
        filename
    FROM {{ ref('mart__invoice_items') }}
    WHERE
        COALESCE(sheet_name, '') != '(TAX)'
        AND COALESCE(mpi_item, '') != ''
        AND item IS NOT NULL
        AND TRIM(item) != ''
        AND TRIM(item) != '.'
        AND LOWER(COALESCE(memo, ''))        NOT LIKE '%tax%'
        AND LOWER(COALESCE(item, ''))        NOT LIKE '%tax%'
        AND LOWER(COALESCE(description, '')) NOT LIKE '%tax%'
),

-- ============================================================
-- STEP 2: Join with Export Status
--   We join at the item level to support partial exports.
-- ============================================================
items_with_status AS (
    SELECT 
        b.*,
        EXISTS (
            SELECT 1 
            FROM {{ ref('stg__quickbooks_items') }} qbi
            WHERE qbi.invoice_items_id = b.id
        ) AS is_exported
    FROM base b
),

-- ============================================================
-- STEP 3: Branch into 'all' and 'unprocessed' modes
-- ============================================================
group_setup AS (
    -- Mode: ALL (Every valid item)
    SELECT *, 'all' as filter_mode FROM items_with_status
    
    UNION ALL
    
    -- Mode: UNPROCESSED (Only items not yet exported)
    SELECT *, 'unprocessed' as filter_mode FROM items_with_status 
    WHERE is_exported = FALSE
),

-- ============================================================
-- STEP 4: Resolve accounts + Deduplication
-- ============================================================
item_classifications AS (
    SELECT sheet_name, category
    FROM {{ ref('int__item_classifications') }}
),

with_account AS (
    SELECT
        gs.*,
        CASE
            WHEN UPPER(TRIM(gs.raw_account)) = 'M'
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
            WHEN UPPER(TRIM(gs.raw_account)) = 'E'
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Equipment'
            WHEN UPPER(TRIM(gs.raw_account)) = 'A'
                THEN 'UnInvoiced JIP:Subcontractors Expense:Labor & Material:Additional Material'
            WHEN gs.raw_account LIKE '%:%'
                THEN gs.raw_account
            WHEN ic.category = 'M'
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
            WHEN ic.category = 'E'
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Equipment'
            WHEN ic.category = 'A'
                THEN 'UnInvoiced JIP:Subcontractors Expense:Labor & Material:Additional Material'
            WHEN gs.mpi_item = 'UIDI-Job Materials Purchased'
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
            WHEN gs.mpi_item = 'UIDI-Job Equipment'
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Equipment'
            WHEN gs.mpi_item IN ('UIDI-Sprinkler specialty item', 'UIDI-Drainage Material')
                THEN 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
            WHEN gs.raw_account = '' THEN 'UNMAPPED'
            ELSE 'UNMAPPED'
        END AS account_full_path,
        LOWER(COALESCE(gs.class_, '')) LIKE 'finishing%' AS is_finishings
    FROM group_setup gs
    LEFT JOIN item_classifications ic ON ic.sheet_name = gs.sheet_name
),

-- Deduplication logic (per mode)
latest_invoice_ids AS (
    SELECT DISTINCT ON (filter_mode, ref_no, vendor, "date")
        filter_mode,
        invoice_id
    FROM with_account
    ORDER BY filter_mode, ref_no, vendor, "date", date_added DESC NULLS LAST
),

deduped AS (
    SELECT wa.*
    FROM with_account wa
    JOIN latest_invoice_ids l 
        ON wa.invoice_id = l.invoice_id 
        AND wa.filter_mode = l.filter_mode
),

-- ============================================================
-- STEP 5: Aggregation + Tax Calculation
-- ============================================================
grouped AS (
    SELECT
        filter_mode,
        invoice_id,
        ref_no,
        vendor,
        "date",
        MIN(customer_job)                           AS customer_job,
        MAX(date_added)                             AS date_added,
        CASE 
            WHEN is_finishings THEN 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
            ELSE account_full_path 
        END                                         AS resolved_account,
        MIN(COALESCE(class_, ''))                   AS class_,
        BOOL_OR(is_finishings)                      AS is_finishings,
        MIN(filename)                               AS filename,
        
        SUM(amount)                                 AS group_pretax_amount,
        SUM(amount) * {{ var('quickbooks_tax_multiplier') }} AS group_total_with_tax,
        
        JSONB_AGG(id::text ORDER BY id)                 AS raw_item_ids,
        JSONB_AGG(
            JSONB_BUILD_OBJECT(
                'id', id::text,  -- Cast to TEXT to prevent JSON float precision loss
                'invoice_id', invoice_id, 'item', item,
                'mpi_item', mpi_item,
                'description', description, 'amount', amount,
                'account', account_full_path, 'class_', class_,
                'ref_no', ref_no, 'vendor', vendor, 'date', "date",
                'customer_job', customer_job, 'date_added', date_added,
                'memo', memo
            )
            ORDER BY id
        )                                           AS raw_items
    FROM deduped
    GROUP BY
        filter_mode, invoice_id, ref_no, vendor, "date",
        is_finishings,
        CASE
            WHEN NOT is_finishings THEN COALESCE(class_, '')
            ELSE NULL
        END,
        CASE 
            WHEN is_finishings THEN 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
            ELSE account_full_path 
        END
),

-- ============================================================
-- STEP 6: Rounding Correction + Totals (Partitioned by mode)
-- ============================================================
invoice_totals AS (
    SELECT
        filter_mode,
        invoice_id,
        SUM(group_pretax_amount) AS invoice_pretax_total,
        ROUND((SUM(group_pretax_amount) * {{ var('quickbooks_tax_multiplier') }})::NUMERIC, 2) AS invoice_total,
        COUNT(*) AS split_count
    FROM grouped
    GROUP BY filter_mode, invoice_id
),

with_totals AS (
    SELECT
        g.*,
        t.invoice_pretax_total,
        t.invoice_total,
        t.split_count,
        ROW_NUMBER() OVER (
            PARTITION BY g.filter_mode, g.invoice_id
            ORDER BY 
                CASE WHEN g.is_finishings THEN 0 ELSE 1 END,
                CASE WHEN g.resolved_account = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased' THEN 0 ELSE 1 END,
                g.resolved_account
        ) AS split_row_num
    FROM grouped g
    JOIN invoice_totals t ON g.invoice_id = t.invoice_id AND g.filter_mode = t.filter_mode
),

with_running_sum AS (
    SELECT
        *,
        COALESCE(
            SUM(ROUND(group_total_with_tax::NUMERIC, 2))
                OVER (
                    PARTITION BY filter_mode, invoice_id
                    ORDER BY split_row_num
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ),
            0
        ) AS prior_splits_sum
    FROM with_totals
),

with_rounding AS (
    SELECT
        *,
        CASE
            WHEN split_row_num = split_count THEN invoice_total - prior_splits_sum
            ELSE ROUND(group_total_with_tax::NUMERIC, 2)
        END AS final_group_total
    FROM with_running_sum
),

-- ============================================================
-- STEP 7: Format as QuickBooksPreviewItem JSON
-- ============================================================
final_items_raw AS (
    -- Split Rows
    SELECT
        filter_mode, invoice_id, ref_no, vendor, "date", customer_job, date_added, filename,
        JSONB_BUILD_OBJECT(
            'id', (raw_item_ids->>0), -- First item ID as string
            'items', raw_items,
            'invoice_id', invoice_id,
            'date', TO_CHAR("date", 'MM/DD/YYYY'),
            'ref', ref_no,
            'vendor', vendor,
            'account', resolved_account,
            'customer_job', customer_job,
            'class', COALESCE(class_, ''),
            'tax', ROUND((final_group_total / {{ var('quickbooks_tax_multiplier') }} * {{ var('quickbooks_tax_rate') }})::NUMERIC, 2),
            'amount', final_group_total,
            'memo', '',
            'is_total_row', FALSE,
            'filename', filename,
            'raw_item_ids', raw_item_ids
        ) AS item_json,
        is_finishings,
        resolved_account
    FROM with_rounding

    UNION ALL

    -- Total Rows (Generated once per unique mode+invoice)
    SELECT
        filter_mode, invoice_id, ref_no, vendor, "date", customer_job, date_added, filename,
        JSONB_BUILD_OBJECT(
            'id', NULL,
            'items', '[]'::jsonb,
            'invoice_id', invoice_id,
            'date', TO_CHAR("date", 'MM/DD/YYYY'),
            'ref', ref_no,
            'vendor', vendor,
            'account', 
                -- Prefer material account for total row
                FIRST_VALUE(resolved_account) OVER (
                    PARTITION BY filter_mode, invoice_id
                    ORDER BY 
                        CASE WHEN resolved_account = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased' THEN 0 ELSE 1 END,
                        resolved_account
                ),
            'customer_job', customer_job,
            'class', '',
            'tax', ROUND((invoice_total / {{ var('quickbooks_tax_multiplier') }} * {{ var('quickbooks_tax_rate') }})::NUMERIC, 2),
            'amount', invoice_total,
            'memo', '',
            'is_total_row', TRUE,
            'filename', filename,
            'raw_item_ids', NULL
        ) AS item_json,
        FALSE as is_finishings,
        'TOTAL' as resolved_account
    FROM with_rounding
    WHERE split_row_num = 1 -- Only one total row per invoice
),

-- ============================================================
-- STEP 8: Pivot into final columns
-- ============================================================
final_agg AS (
    SELECT
        invoice_id,
        MIN(ref_no) as ref_no,
        MIN(vendor) as vendor,
        MIN("date") as "date",
        MIN(customer_job) as customer_job,
        MAX(date_added) as date_added,
        MIN(filename) as filename,
        JSONB_AGG(item_json ORDER BY (item_json->>'is_total_row')::boolean ASC, (item_json->>'account') ASC) FILTER (WHERE filter_mode = 'all')          AS all_data_json,
        JSONB_AGG(item_json ORDER BY (item_json->>'is_total_row')::boolean ASC, (item_json->>'account') ASC) FILTER (WHERE filter_mode = 'unprocessed')  AS unprocessed_data_json
    FROM final_items_raw
    GROUP BY invoice_id
)

SELECT
    {{ dbt_utils.generate_surrogate_key(['invoice_id', 'ref_no', 'vendor']) }} AS id,
    invoice_id,
    ref_no,
    vendor,
    "date",
    customer_job,
    date_added,
    filename,
    COALESCE(all_data_json, '[]'::jsonb)          AS all_data_json,
    COALESCE(unprocessed_data_json, '[]'::jsonb)  AS unprocessed_data_json,
    NOW()                                         AS computed_at
FROM final_agg
