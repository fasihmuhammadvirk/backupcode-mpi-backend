/*
Test: Extraction Invoice ID Referential Integrity
Description: Validates that every extraction_invoice_id in stg__extracted_line_items
             has a corresponding row in stg__extracted_global_fields.
             This is an orphan check for multi-invoice PDF extraction where each PDF
             may produce multiple invoices, each identified by extraction_invoice_id
             (a deterministic hash of extraction_id + invoice_index).

Purpose: Ensure referential integrity between line items and global fields after
         multi-invoice PDF extraction. Orphan line items indicate a mismatch in
         how invoices are unnested between the two staging models.

Expected Result: 0 rows (test passes)
Failure Condition: Any rows returned indicate line items referencing an
                   extraction_invoice_id that does not exist in global fields.
*/

SELECT
    li.extraction_invoice_id,
    li.extraction_id,
    li.invoice_index,
    li.s3_file_key,
    COUNT(*) AS orphan_line_item_count
FROM {{ ref('stg__extracted_line_items') }} li
LEFT JOIN {{ ref('stg__extracted_global_fields') }} gf
    ON li.extraction_invoice_id = gf.extraction_invoice_id
WHERE gf.extraction_invoice_id IS NULL
GROUP BY
    li.extraction_invoice_id,
    li.extraction_id,
    li.invoice_index,
    li.s3_file_key
ORDER BY orphan_line_item_count DESC
