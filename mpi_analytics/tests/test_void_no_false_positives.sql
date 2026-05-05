/*
Test: No False Positive Voids
Description: Rows in the intermediate model should only have invoice_voided_at set
             if there is a matching row in public.invoice_voided. This catches cases
             where a restore (un-void) wasn't detected by incremental condition #4,
             leaving stale invoice_voided_at values.

Expected Result: 0 rows (test passes)
Failure Condition: Rows returned indicate items marked as voided in the intermediate
                   model that have no corresponding record in the invoice_voided source.
*/

WITH voided_source AS (
    SELECT DISTINCT ref_no, date, vendor
    FROM {{ source('public', 'invoice_voided') }}
)

SELECT
    n.invoice_items_id,
    n.ref_no,
    n.date,
    n.vendor,
    n.invoice_voided_at
FROM {{ ref('int__invoice_items_with_normalized_fields') }} n
LEFT JOIN voided_source v
    ON n.ref_no = v.ref_no
   AND n.date   = v.date
   AND n.vendor = v.vendor
WHERE n.invoice_voided_at IS NOT NULL
  AND v.ref_no IS NULL
