/*
Intermediate Permanent Mappings
Valid permanent mappings from Google Sheets - used for primary mapping joins
*/

{{ config(
    materialized='table',
    schema='intermediate',
    post_hook=[
        "CREATE INDEX IF NOT EXISTS idx_perm_map_supplier_item_trim ON {{ this }} (TRIM(supplier_item))",
        "CREATE INDEX IF NOT EXISTS idx_perm_map_supplier_item_upper_trim ON {{ this }} (UPPER(TRIM(supplier_item)))",
        "ANALYZE {{ this }}"
    ]
) }}

WITH google_sheet_mappings AS (
    SELECT * FROM {{ ref('int__google_sheet_mappings') }}
),

permanent_only AS (
    SELECT
        id,
        sheet_title,
        google_sheet_name,
        sheet_id,
        mpi_code,
        mpi_description,
        supplier,
        supplier_id,
        supplier_item_id,
        -- original_supplier_item_id,
        row_number,
        column_index,
        mapping_type,
        extraction_timestamp,
        loaded_at,
        is_valid_for_join
    FROM google_sheet_mappings
    WHERE mapping_type = 'permanent'
      AND is_valid_for_join = TRUE
)

SELECT
    id,
    sheet_title AS sheet_name,
    mpi_code,
    mpi_description,
    supplier_item_id AS supplier_item,
    supplier,
    supplier_id,
    sheet_id,

    -- For debugging: track source and metadata
    google_sheet_name,
    -- original_supplier_item_id,
    row_number,
    column_index,

    -- Source tracking
    google_sheet_name || ' row: ' || row_number || ' col:' || column_index  AS mapping_source,
    extraction_timestamp,
    loaded_at,
    CURRENT_TIMESTAMP AS transformed_at

FROM permanent_only
