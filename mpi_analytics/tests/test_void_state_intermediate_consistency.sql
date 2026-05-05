/*
Test: Void State Consistency in Intermediate Model
Description: Every invoice in public.invoice_voided should have invoice_voided_at
             set on corresponding rows in the intermediate normalized fields model.
             If rows are returned, it means the incremental logic failed to detect
             a voided invoice and propagate the void state.

Expected Result: 0 rows (test passes)
Failure Condition: Rows returned indicate voided invoices that weren't picked up
                   by the incremental WHERE condition #4.
*/

WITH voided_source AS (
    SELECT DISTINCT ref_no, date, vendor
    FROM {{ source('public', 'invoice_voided') }}
),

intermediate_missing_void AS (
    SELECT
        n.invoice_items_id,
        n.ref_no,
        n.date,
        n.vendor,
        n.invoice_voided_at
    FROM {{ ref('int__invoice_items_with_normalized_fields') }} n
    INNER JOIN voided_source v
        ON n.ref_no = v.ref_no
       AND n.date   = v.date
       AND n.vendor = v.vendor
    WHERE n.invoice_voided_at IS NULL
)

SELECT * FROM intermediate_missing_void
