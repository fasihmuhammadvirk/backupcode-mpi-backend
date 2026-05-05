{{ config(tags=['reconciliation']) }}

/*
Test: No Missing Rows in Map Mart
Description: Verifies that mart__invoice_items_map contains all rows from
             mart__invoice_items that pass the map mart's is_active filter
             (WHERE is_active = TRUE OR is_active IS NULL).

Expected Result: 0 rows (test passes)
Failure Condition: Rows in mart__invoice_items that should appear in
                   mart__invoice_items_map based on the is_active filter,
                   but are absent.

Defined in: mart__invoice_items_map (final WHERE clause).
Both marts read from int__invoice_items_with_normalized_fields, but they differ:
  - mart__invoice_items: selects all rows (no is_active filter)
  - mart__invoice_items_map: applies WHERE is_active = TRUE OR is_active IS NULL
Rows with is_active = FALSE legitimately exist in the main mart but not the map
mart. Since the main mart doesn't carry is_active as a column, we join to the
intermediate model to check the filter. Only active/null rows are expected to
appear in both marts.
*/

SELECT
    mart.invoice_items_id,
    mart.item,
    mart.vendor,
    mart.ref_no,
    mart.date
FROM {{ ref('mart__invoice_items') }} mart
INNER JOIN {{ ref('int__invoice_items_with_normalized_fields') }} interm
    ON mart.invoice_items_id = interm.invoice_items_id
LEFT JOIN {{ ref('mart__invoice_items_map') }} map_mart
    ON mart.invoice_items_id = map_mart.id
WHERE map_mart.id IS NULL
  AND (interm.is_active = TRUE OR interm.is_active IS NULL)
