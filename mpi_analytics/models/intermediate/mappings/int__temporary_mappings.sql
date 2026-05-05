/*
Intermediate Temporary Mappings
Items awaiting full classification - have sheet_name but no valid MPI code
Only used to assign sheet_name when permanent mapping not found
*/

{{ config(
    materialized='table',
    schema='intermediate',
    post_hook=[
        "CREATE INDEX IF NOT EXISTS idx_temp_map_original_item_trim ON {{ this }} (TRIM(original_item))",
        "CREATE INDEX IF NOT EXISTS idx_temp_map_original_item_upper_trim ON {{ this }} (UPPER(TRIM(original_item)))",
        "ANALYZE {{ this }}"
    ]
) }}

WITH google_sheet_mappings AS (
    SELECT * FROM {{ ref('int__google_sheet_mappings') }}
),

temporary_only AS (
    SELECT
        id,
        sheet_title,
        google_sheet_name,
        sheet_id,
        supplier_item_id,
        -- original_supplier_item_id,
        mpi_description AS original_description,
        row_number,
        column_index,
        mapping_type,
        extraction_timestamp,
        loaded_at
    FROM google_sheet_mappings
    WHERE mapping_type = 'temporary'
      AND is_valid_for_join = TRUE
)

SELECT DISTINCT
    supplier_item_id AS original_item,
    original_description,
    sheet_title AS sheet_name,
    sheet_id,

    -- TODO: Why not the same as int__permanent_mappings?
    -- For debugging
    MIN(id) AS min_id,
    MIN(google_sheet_name) AS google_sheet_name,
    MIN(row_number) AS first_row_number,
    MIN(column_index) AS first_column_index,

    -- Source tracking
    google_sheet_name || ' row: ' || row_number || ' col:' || column_index  AS mapping_source,
    MIN(extraction_timestamp) AS extraction_timestamp,
    MIN(loaded_at) AS loaded_at,
    CURRENT_TIMESTAMP AS transformed_at

FROM temporary_only
GROUP BY
    google_sheet_name,
    row_number,
    column_index,
    supplier_item_id,
    original_description,
    sheet_title,
    sheet_id
