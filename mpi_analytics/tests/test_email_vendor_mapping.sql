/*
Test: Email-Based Vendor Mapping Validation
Description: Validates vendor mapping completeness and exclusions in stg__model_extracted_data.
             Ensures vendor information is properly derived from email senders for DOWNLOADED status records.

Purpose: Monitor email-to-vendor mapping coverage and ensure excluded vendors are properly filtered out.

Expected Result: 0 rows (test passes)
Failure Condition: >10% unmapped vendors OR any excluded vendors present (Positive Tech, MPI Plumbing Corp)
*/

WITH vendor_stats AS (
    SELECT
        COUNT(*) as total_records,
        COUNT(CASE WHEN vendor IS NULL THEN 1 END) as unmapped_count,
        COUNT(CASE WHEN vendor = 'Positive Tech' OR vendor = 'MPI Plumbing Corp' THEN 1 END) as excluded_count,
        COUNT(CASE WHEN vendor IS NOT NULL THEN 1 END) as mapped_count
    FROM {{ ref('int__model_extracted_data') }}
),

detailed_analysis AS (
    SELECT
        total_records,
        unmapped_count,
        excluded_count,
        mapped_count,
        ROUND(unmapped_count * 100.0 / NULLIF(total_records, 0), 2) as unmapped_percentage,
        CASE
            WHEN unmapped_count * 100.0 / NULLIF(total_records, 0) > 10.0
            THEN 'UNMAPPED_THRESHOLD_EXCEEDED: ' || ROUND(unmapped_count * 100.0 / NULLIF(total_records, 0), 2) || '% unmapped (>10% threshold)'
            WHEN excluded_count > 0
            THEN 'EXCLUDED_VENDORS_PRESENT: ' || excluded_count || ' records with excluded vendors (Positive Tech, MPI Plumbing Corp)'
            ELSE NULL
        END as failure_reason
    FROM vendor_stats
)

-- Return results only when test should fail
SELECT
    total_records,
    mapped_count,
    unmapped_count,
    excluded_count,
    unmapped_percentage,
    failure_reason
FROM detailed_analysis
WHERE failure_reason IS NOT NULL