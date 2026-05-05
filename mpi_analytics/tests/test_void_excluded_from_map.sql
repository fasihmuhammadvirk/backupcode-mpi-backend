/*
Test: Voided Invoices Excluded from Invoice Items Map
Description: mart__invoice_items_map should never contain rows for voided invoices.
             The SELECT filters with WHERE invoice_voided_at IS NULL, and the
             post-hook DELETE removes any that slip through during incremental runs.

Expected Result: 0 rows (test passes)
Failure Condition: Rows returned indicate voided invoices leaked into the map table,
                   meaning either the WHERE filter or the post-hook DELETE failed.
*/

SELECT
    map.id AS map_id,
    map.ref_no,
    map.vendor,
    map.date,
    n.invoice_voided_at
FROM {{ ref('mart__invoice_items_map') }} map
INNER JOIN {{ ref('int__invoice_items_with_normalized_fields') }} n
    ON map.id = n.invoice_items_id
WHERE n.invoice_voided_at IS NOT NULL
