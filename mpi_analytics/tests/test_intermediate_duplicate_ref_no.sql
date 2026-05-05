{{
  config(
    severity = 'warn',
    warn_if = '>0'
  )
}}
/*
Test: Intermediate Layer Window Function Validation
Description: Validates that the latest_only window function is working correctly.
             Only checks for true duplicates (same vendor, ref_no, date, item appearing multiple times).

Purpose: Ensure window function deduplication works as intended.
         Different suppliers using same ref_no is EXPECTED and not an error.

Expected Result: 0 rows (test passes)
Failure Condition: Any rows returned (window function failed to deduplicate properly)
*/

WITH true_duplicates AS (
    SELECT
        ref_no,
        vendor,
        date,
        item,
        COUNT(*) as occurrence_count,
        STRING_AGG(
            'ID: ' || invoice_items_id ||
            ' | Date Added: ' || COALESCE(date_added::text, 'NULL') ||
            ' | Invoice ID: ' || COALESCE(invoice_id::text, 'NULL'),
            ' || '
            ORDER BY date_added DESC, invoice_items_id DESC
        ) as duplicate_details
    FROM {{ ref('int__model_extracted_data') }}
    WHERE ref_no IS NOT NULL
    GROUP BY ref_no, vendor, date, item
    HAVING COUNT(*) > 1
)

-- Only flag true duplicates (same business key appearing multiple times)
SELECT
    ref_no,
    vendor,
    date,
    item,
    occurrence_count,
    'WINDOW_FUNCTION_FAILURE: Same (vendor, ref_no, date, item) appears ' ||
    occurrence_count || ' times. Details: ' || duplicate_details as error_message
FROM true_duplicates
ORDER BY occurrence_count DESC, ref_no