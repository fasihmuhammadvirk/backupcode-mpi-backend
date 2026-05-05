/*
Test: Void State Consistency Between Intermediate and Mart
Description: The invoice_voided_at value in mart__invoice_items must match
             the intermediate model. If they diverge, the mart's incremental
             _dbt_updated_at cascade failed to pick up the void state change.

Expected Result: 0 rows (test passes)
Failure Condition: Rows returned indicate mart__invoice_items has stale void state
                   that didn't cascade from the intermediate model.
*/

SELECT
    m.invoice_items_id,
    m.invoice_voided_at AS mart_voided_at,
    n.invoice_voided_at AS intermediate_voided_at
FROM {{ ref('mart__invoice_items') }} m
INNER JOIN {{ ref('int__invoice_items_with_normalized_fields') }} n
    ON m.invoice_items_id = n.invoice_items_id
WHERE (m.invoice_voided_at IS NULL AND n.invoice_voided_at IS NOT NULL)
   OR (m.invoice_voided_at IS NOT NULL AND n.invoice_voided_at IS NULL)
