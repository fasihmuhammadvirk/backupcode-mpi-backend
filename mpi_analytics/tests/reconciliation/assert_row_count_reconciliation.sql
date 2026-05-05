{{ config(tags=['reconciliation']) }}

/*
Test: Row Count Reconciliation
Description: Compares staging row count to mart row count, breaking down the difference
             into staging rows that matched the mart, mart rows not in staging (synthetic),
             and any unexplained difference. Fails if the numbers don't balance.

Expected Result: 0 rows (test passes)
Failure Condition: mart_rows - staging_rows_in_mart - mart_synthetic_rows != 0,
                   meaning there are rows in the mart that can't be accounted for by
                   either staging line items or known synthetic records.

Why the counts differ:
  - Staging has MORE rows than mart because business filters in the pipeline
    (validation, dedup, item cleaning, etc.) drop rows before the mart.
  - Mart has EXTRA rows not in staging because int__extracted_data_combined
    synthesizes tax, freight, and misc charge records from invoice-level totals.
  - The equation: mart = staging_matched + synthetic. If it doesn't balance,
    something is creating or losing rows unexpectedly.
*/

/*
  Total staging rows: join line items to global fields (same join used by the
  pipeline in int__extracted_data_combined) to count only rows that have
  a valid global fields parent.
*/
WITH staging_count AS (
    SELECT COUNT(*) AS cnt
    FROM {{ ref('stg__extracted_line_items') }} li
    INNER JOIN {{ ref('stg__extracted_global_fields') }} g
        ON li.extraction_invoice_id = g.extraction_invoice_id
),

mart_count AS (
    SELECT COUNT(*) AS cnt
    FROM {{ ref('mart__invoice_items') }}
),

/*
  Staging rows that made it to the mart (matched by line_item_id = invoice_items_id).
  These survived all business filters and appear in the final table.
*/
staging_in_mart AS (
    SELECT COUNT(*) AS cnt
    FROM {{ ref('stg__extracted_line_items') }} li
    INNER JOIN {{ ref('mart__invoice_items') }} mart
        ON li.line_item_id = mart.invoice_items_id
),

/*
  Mart rows with no staging source — these are the synthetic records
  (tax, freight, misc) created by int__extracted_data_combined.
*/
mart_not_in_staging AS (
    SELECT COUNT(*) AS cnt
    FROM {{ ref('mart__invoice_items') }} mart
    LEFT JOIN {{ ref('stg__extracted_line_items') }} li
        ON mart.invoice_items_id = li.line_item_id
    WHERE li.line_item_id IS NULL
)

SELECT
    s.cnt AS staging_rows,
    m.cnt AS mart_rows,
    sim.cnt AS staging_rows_in_mart,
    mns.cnt AS mart_rows_not_in_staging,
    s.cnt - sim.cnt AS staging_rows_filtered_out,
    m.cnt - sim.cnt - mns.cnt AS unexplained_diff
FROM staging_count s, mart_count m, staging_in_mart sim, mart_not_in_staging mns
WHERE m.cnt - sim.cnt - mns.cnt != 0
