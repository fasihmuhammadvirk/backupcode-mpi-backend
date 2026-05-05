/*
Staging Google Sheet Mappings
Clean and standardize raw Google Sheet mapping data
Derived business logic fields are in int__google_sheet_mappings

See stg__google_sheet_mappings.yml for documentation
*/

{{ config(
  materialized='view',
  schema='staging'
) }}

WITH raw_data AS (
    SELECT *
    FROM {{ source('raw', 'raw_google_sheet_mappings') }}
),

cleaned AS (
    SELECT
        -- Primary key
        id,

        -- Sheet identification (cleaned)
        TRIM(sheet_title) AS sheet_title,
        TRIM(google_sheet_name) AS google_sheet_name,
        TRIM(sheet_id) AS sheet_id,

        -- MPI mapping data (cleaned)
        TRIM(mpi_code) AS mpi_code,
        TRIM(description) AS mpi_description,

        -- Supplier info (cleaned)
        TRIM(supplier) AS supplier,
        supplier_id,

        -- Supplier item codes (cleaned) - KEY FOR JOINING
        TRIM(supplier_item_ids) AS supplier_item_id,
        -- TODO: Not sure if we need this from the google sheet?
        -- TRIM(original_supplier_item_id) AS original_supplier_item_id,

        -- Debugging metadata (preserved as-is)
        row_number,
        column_index,

        -- Classification (from source)
        TRIM(mapping_type) AS mapping_type,
        TRIM(validation_status) AS validation_status,

        -- Timestamps
        extraction_timestamp,
        {{ current_timestamp() }} AS loaded_at

    FROM raw_data
    -- Filter out obviously invalid rows
    WHERE mapping_type IS NOT NULL
      AND mapping_type != ''
      -- TODO: if we filter out 'invalid' mapping_types we need a table to verify (same as the mpi_code below)
      --AND mapping_type != 'invalid'  -- Exclude invalid mappings from staging
      -- Filter out invalid mpi_code values (prices, numbers, header values)
      -- Exclude header values but keep null mpi_codes since that means that it's a temporary mapping
      -- TODO: Add a validation to write to a table when mpi_code is IN the list below so we can verify
      -- that we're not excluding actual items
      AND (
        mpi_code IS NULL
        OR TRIM(mpi_code) NOT IN ('Item Code', 'DESCRIPTION', 'MPI Code', 'Description')
      )
)

SELECT * FROM cleaned
