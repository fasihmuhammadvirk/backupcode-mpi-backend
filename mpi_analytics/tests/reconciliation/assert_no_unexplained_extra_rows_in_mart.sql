{{ config(tags=['reconciliation']) }}

/*
Test: No Unexplained Extra Rows in Mart
Description: Starts from mart__invoice_items, LEFT JOINs back to staging line items.
             Rows in the mart that have no corresponding staging line item are categorized
             as known synthetic records (tax, freight, misc charges) or unexplained.
             Fails only on truly unexplained extra rows.

Expected Result: 0 rows (test passes)
Failure Condition: Mart rows that cannot be traced back to any staging line item
                   and are not a known synthetic record type.

Known synthetic categories (not failures):
  - synthetic_tax: tax line added from global fields
  - synthetic_freight: freight line added from global fields
  - synthetic_misc: misc charge from global fields misc_charges_raw JSONB

Why mart rows can exist without a staging source:
  int__extracted_data_combined creates synthetic records by UNION ALL'ing
  tax, freight, and misc charge rows onto the real line items from
  stg__extracted_line_items. These synthetic rows get deterministic IDs
  (HASHTEXTEXTENDED) that won't match any staging line_item_id, so they
  appear as "extra" in this reconciliation.

  We identify them by recomputing the same deterministic hash from
  stg__extracted_global_fields, matching the exact ID generation logic
  in int__extracted_data_combined. This avoids heuristic-based matching
  (e.g. checking description text) which could mask real issues.
*/

/*
  Defined in: int__extracted_data_combined (tax_records CTE).
  Tax IDs are: ABS(HASHTEXTEXTENDED(extraction_invoice_id || '-tax', 0))
*/
WITH synthetic_tax_ids AS (
    SELECT ABS(HASHTEXTEXTENDED(extraction_invoice_id::text || '-tax', 0)) AS synthetic_id
    FROM {{ ref('stg__extracted_global_fields') }}
),

/*
  Defined in: int__extracted_data_combined (freight_records CTE).
  Freight IDs are: ABS(HASHTEXTEXTENDED(extraction_invoice_id || '-freight', 0))
*/
synthetic_freight_ids AS (
    SELECT ABS(HASHTEXTEXTENDED(extraction_invoice_id::text || '-freight', 0)) AS synthetic_id
    FROM {{ ref('stg__extracted_global_fields') }}
),

/*
  Defined in: int__extracted_data_combined (misc_charges_records CTE).
  Misc IDs are: ABS(HASHTEXTEXTENDED(extraction_invoice_id || '-misc-' || ordinality, 0))
  One ID per entry in the misc_charges_raw JSONB array.
*/
synthetic_misc_ids AS (
    SELECT ABS(HASHTEXTEXTENDED(g.extraction_invoice_id::text || '-misc-' || mc_order::text, 0)) AS synthetic_id
    FROM {{ ref('stg__extracted_global_fields') }} g,
    LATERAL jsonb_array_elements(g.misc_charges_raw) WITH ORDINALITY AS mc(charge, mc_order)
    WHERE g.misc_charges_raw IS NOT NULL AND jsonb_array_length(g.misc_charges_raw) > 0
),

mart_rows AS (
    SELECT
        mart.invoice_items_id,
        mart.item,
        mart.description,
        mart.vendor,
        mart.ref_no,
        mart.date,
        mart.amount
    FROM {{ ref('mart__invoice_items') }} mart
),

/*
  Join mart back to staging by invoice_items_id = line_item_id.
  Rows where staging_id IS NULL have no staging source.
*/
with_staging AS (
    SELECT
        m.*,
        li.line_item_id AS staging_id
    FROM mart_rows m
    LEFT JOIN {{ ref('stg__extracted_line_items') }} li
        ON m.invoice_items_id = li.line_item_id
),

unmatched AS (
    SELECT
        w.*,
        CASE
            WHEN w.invoice_items_id IN (SELECT synthetic_id FROM synthetic_tax_ids)
                THEN 'synthetic_tax'
            WHEN w.invoice_items_id IN (SELECT synthetic_id FROM synthetic_freight_ids)
                THEN 'synthetic_freight'
            WHEN w.invoice_items_id IN (SELECT synthetic_id FROM synthetic_misc_ids)
                THEN 'synthetic_misc'
            ELSE 'UNEXPLAINED'
        END AS extra_reason
    FROM with_staging w
    WHERE w.staging_id IS NULL
)

SELECT
    invoice_items_id,
    item,
    description,
    vendor,
    ref_no,
    date,
    amount,
    extra_reason
FROM unmatched
WHERE extra_reason = 'UNEXPLAINED'
