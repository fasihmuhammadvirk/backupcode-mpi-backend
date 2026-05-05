/*
Mart Unmapped Report
Items that need manual review - use this to identify what needs to be added to Google Sheet
*/

{{ config(
    materialized='table',
) }}

WITH unmapped_items AS (
    SELECT * FROM {{ ref('int__unmapped_items') }}
),

unmapped_summary AS (
    SELECT
        item,
        description,
        vendor,
        COUNT(*) AS occurrence_count,
        SUM(COALESCE(qty, 0)) AS total_quantity,
        SUM(COALESCE(amount, 0)) AS total_amount,
        AVG(cost) AS avg_cost,
        MIN(date) AS first_seen,
        MAX(date) AS last_seen,
        MAX(date_added) AS last_added,

        -- Sample references for investigation
        ARRAY(SELECT DISTINCT filename FROM {{ ref('int__unmapped_items') }} u2
              WHERE u2.item = unmapped_items.item
              AND u2.vendor = unmapped_items.vendor
              ORDER BY filename LIMIT 3) AS sample_filenames,
        ARRAY(SELECT DISTINCT invoice_id FROM {{ ref('int__unmapped_items') }} u2
              WHERE u2.item = unmapped_items.item
              AND u2.vendor = unmapped_items.vendor
              ORDER BY invoice_id LIMIT 3) AS sample_invoice_ids,
        ARRAY(SELECT DISTINCT ref_no FROM {{ ref('int__unmapped_items') }} u2
              WHERE u2.item = unmapped_items.item
              AND u2.vendor = unmapped_items.vendor
              ORDER BY ref_no LIMIT 3) AS sample_ref_nos,

        -- Count of unique buyers/jobs
        COUNT(DISTINCT buyer) AS unique_buyers,
        COUNT(DISTINCT customer_job) AS unique_jobs

    FROM unmapped_items
    GROUP BY
        item,
        description,
        vendor
)

SELECT
    -- Generate a unique report ID
    {{ dbt_utils.generate_surrogate_key(['item', 'vendor']) }} AS report_id,

    -- Item info
    item,
    description,
    vendor,

    -- Priority metrics (for triage)
    occurrence_count,
    total_amount,
    total_quantity,
    avg_cost,

    -- Date info (helps identify stale vs recent)
    first_seen,
    last_seen,
    last_added,
    CURRENT_DATE - last_seen::DATE AS days_since_last_seen,

    -- Investigation aids
    unique_buyers,
    unique_jobs,
    sample_filenames,
    sample_invoice_ids,

    -- Priority score (higher = more important to map)
    -- Based on: frequency, recency, and total amount
    (
        occurrence_count * 10 +
        CASE WHEN CURRENT_DATE - last_seen::DATE < 30 THEN 50 ELSE 0 END +
        LEAST(total_amount / 1000, 100)
    )::INTEGER AS priority_score,

    -- Report generation timestamp
    CURRENT_TIMESTAMP AS report_generated_at

FROM unmapped_summary
