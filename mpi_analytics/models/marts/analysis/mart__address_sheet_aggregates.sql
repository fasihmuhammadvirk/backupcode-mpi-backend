-- Mart model for pre-aggregated address + sheet_name analysis data.
-- See mart__address_sheet_aggregates.yml for detailed documentation.

{{
    config(
        materialized='table',
        tags=['analysis', 'aggregates', 'reporting'],
        indexes=[
            {'columns': ['customer_job']},
            {'columns': ['sheet_name']},
            {'columns': ['customer_job', 'sheet_name'], 'unique': True}
        ]
    )
}}

WITH invoice_items_intermediate AS (
    -- Source: rerated intermediate (issue #899) so this mart sits in the same
    -- lineage as the rest of the App's marts. Aggregations here only sum
    -- `amount`, which is preserved across rerating, so totals are unchanged.
    SELECT
        cost,
        -- TODO: For amount we might want to use the "corrected_amount" instead of just amount
        amount,
        corrected_amount,

        customer_job_normalized AS customer_job,
        sheet_name_normalized AS sheet_name
    FROM {{ ref('int__invoice_items_with_rerated_pricing') }}
    WHERE is_active = TRUE
      AND invoice_voided_at IS NULL
),

-- Calculate per-address, per-sheet totals
address_sheet_totals AS (
    SELECT
        customer_job,
        sheet_name,
        SUM(amount) AS total_amount
    FROM invoice_items_intermediate
    GROUP BY customer_job, sheet_name
)

SELECT
    customer_job,
    sheet_name,
    total_amount,
    -- Calculate total amount across all sheet_names for each address
    SUM(total_amount) OVER (PARTITION BY customer_job) AS address_total
FROM address_sheet_totals
