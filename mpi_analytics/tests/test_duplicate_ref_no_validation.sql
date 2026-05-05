{{
  config(
    severity = 'warn',
    warn_if = '>0'
  )
}}
/*
Test: Reference Number Business Rules Validation
Description: Validates ref_no distribution across vendors in mart__invoice_items.
             Reports suspicious patterns but allows legitimate business cases.

Purpose: Monitor ref_no usage patterns and identify potential data quality issues
         while respecting business rule that same ref_no can legitimately appear
         across different suppliers or dates.

Expected Result: 0 rows (test passes)
Failure Condition: Rows returned indicate potential data quality issues to investigate
*/

WITH ref_no_analysis AS (
    SELECT
        ref_no,
        COUNT(*) as total_occurrences,
        COUNT(DISTINCT vendor) as unique_vendors,
        COUNT(DISTINCT date) as unique_dates,
        COUNT(DISTINCT item) as unique_items,
        STRING_AGG(DISTINCT vendor, ', ') as vendors_list,
        STRING_AGG(DISTINCT date::text, ', ') as dates_list
    FROM {{ ref('mart__invoice_items') }}
    WHERE ref_no IS NOT NULL
    GROUP BY ref_no
),

suspicious_patterns AS (
    SELECT
        ref_no,
        total_occurrences,
        unique_vendors,
        unique_dates,
        unique_items,
        vendors_list,
        dates_list,
        CASE
            -- Same ref_no, same vendor, same date, but many different items (>10)
            WHEN unique_vendors = 1 AND unique_dates = 1 AND unique_items > 10
            THEN 'LARGE_INVOICE: ' || ref_no || ' has ' || unique_items || ' items from same vendor/date'

            -- Same ref_no used by >5 different vendors (unlikely but possible)
            WHEN unique_vendors > 5
            THEN 'MULTI_VENDOR_SUSPICIOUS: ' || ref_no || ' used by ' || unique_vendors || ' vendors'

            -- For debugging: cases where ref_no appears >50 times total
            WHEN total_occurrences > 50
            THEN 'HIGH_FREQUENCY: ' || ref_no || ' appears ' || total_occurrences || ' times'

            ELSE NULL
        END as warning_message
    FROM ref_no_analysis
)

SELECT
    ref_no,
    total_occurrences,
    unique_vendors,
    unique_dates,
    unique_items,
    vendors_list,
    dates_list,
    warning_message
FROM suspicious_patterns
WHERE warning_message IS NOT NULL
ORDER BY total_occurrences DESC, unique_vendors DESC