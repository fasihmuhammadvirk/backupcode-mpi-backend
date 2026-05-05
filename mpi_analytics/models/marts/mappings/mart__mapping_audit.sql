/*
Mart Mapping Audit
Audit trail of all mappings applied to invoice items
*/

{{ config(
    materialized='table',
) }}

WITH mapped_items AS (
    -- Source: rerated intermediate so this mart can join cleanly with the
    -- rest of the rerated-pricing lineage (issue #899). Aggregates here
    -- continue to use raw `qty` / `cost` so audit numbers don't shift.
    SELECT * FROM {{ ref('int__invoice_items_with_rerated_pricing') }}
),

audit_summary AS (
    SELECT
        -- Item identification
        item,
        description,
        vendor,

        -- Mapping resolution
        resolved_mpi_item AS mpi_item,
        resolved_mpi_description AS mpi_description,
        resolved_sheet_name AS sheet_name,
        mapping_type,
        mapping_source,

        -- Aggregated metrics (using safe_cast to handle commas in numeric strings)
        COUNT(*) AS total_occurrences,
        SUM(COALESCE(qty, 0)) AS total_quantity,
        SUM(COALESCE(amount, 0)) AS total_amount,
        AVG(cost) AS avg_cost,
        MIN(date) AS first_seen,
        MAX(date) AS last_seen,
        MAX(mapped_at) AS last_mapped_at,

        -- Sample invoice for reference (cast to text since invoice_id may be UUID)
        MIN(invoice_id::text) AS sample_invoice_id,
        MIN(filename) AS sample_filename

    FROM mapped_items
    WHERE invoice_voided_at IS NULL
    GROUP BY
        item,
        description,
        vendor,
        resolved_mpi_item,
        resolved_mpi_description,
        resolved_sheet_name,
        mapping_type,
        mapping_source
)

SELECT
    -- Generate a unique audit ID
    {{ dbt_utils.generate_surrogate_key(['item', 'vendor', 'mpi_item']) }} AS audit_id,

    -- Item and mapping info
    item,
    description,
    vendor,
    mpi_item,
    mpi_description,
    sheet_name,
    mapping_type,
    mapping_source,

    -- Metrics
    total_occurrences,
    total_quantity,
    total_amount,
    avg_cost,
    first_seen,
    last_seen,
    last_mapped_at,

    -- Sample reference
    sample_invoice_id,
    sample_filename,

    -- Audit timestamp
    CURRENT_TIMESTAMP AS audit_generated_at

FROM audit_summary
