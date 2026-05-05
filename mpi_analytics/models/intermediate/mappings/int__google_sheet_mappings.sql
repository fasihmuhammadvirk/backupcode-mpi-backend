/*
Intermediate Google Sheet Mappings
Adds derived business logic fields to the staged Google Sheet data
*/

{{ config(
    materialized='view',
    schema='intermediate'
) }}

WITH staged_mappings AS (
    SELECT * FROM {{ ref('stg__google_sheet_mappings') }}
    -- Exclude this sheet because it's not stuff that we want to map against
    -- it is documentation for MPI
    WHERE {{ should_include_sheet('google_sheet_name') }}
)

SELECT
    -- Pass through all staged columns
    id,
    sheet_title,
    google_sheet_name,
    sheet_id,
    mpi_code,
    mpi_description,
    supplier,
    supplier_id,
    supplier_item_id,
    -- original_supplier_item_id, -- same as supplier_item_id, query:
    --
    -- select count(1)
    -- from raw.raw_google_sheet_mappings 
    -- where supplier_item_ids <> original_supplier_item_id
    --
    -- Returns 0
    row_number,
    column_index,
    CASE
        WHEN (mpi_code IS NULL OR TRIM(mpi_code) = '' AND supplier_item_id IS NOT NULL ) THEN 'temporary'
        WHEN UPPER(mpi_code) LIKE 'UIDI%' THEN 'unmapped'
        WHEN UPPER(mpi_code) LIKE 'NO MATCH%' THEN 'unmapped'
        WHEN UPPER(mpi_code) LIKE 'TEMP%' THEN 'unmapped'
        WHEN (mpi_code IS NOT NULL AND supplier_id IS NOT NULL) THEN 'permanent'
        ELSE 'unknown' -- there should be 0 unknown. We should only have permanent or temporary
    END AS mapping_type,
    -- validation_status,
    extraction_timestamp,
    loaded_at,

    -- Derived: Is this a temporary mapping?
    -- Temporary mappings have empty MPI Codes, UIDI, No Match, Temp (Not clear where the UIDI is brought in)
    -- CASE
    --     -- Removing the google sheet because there were two mpi_items : WAT-0386419, 0386419 that were marked as
    --     -- temporary but they are not
    --     -- WHEN mapping_type = 'temporary' THEN TRUE
    --     WHEN mpi_code IS NULL OR mpi_code = '' THEN TRUE
    --     WHEN UPPER(mpi_code) LIKE 'UIDI%' THEN TRUE
    --     WHEN UPPER(mpi_code) LIKE 'NO MATCH%' THEN TRUE
    --     WHEN UPPER(mpi_code) LIKE 'TEMP%' THEN TRUE
    --     ELSE FALSE
    -- END AS is_temporary_mapping,

    -- Derived: Is this valid for joining to invoice_items?
    -- Must have a non-empty supplier_item_id
    -- TODO: double check that having a supplier_item_id makes this valid for join
    --   when we have new items it will not be assigned under any supplier. For example:
    --
    -- 	Original Item	Original Description	Total Qty	Unit Cost	Total Amount
	--  QCS5P-W	5       PIECE QUICK COUPL	            11	$10.00	        $110.00
    -- Has no supplier id but is still valid to map. Is it?
    -- TODO: Is this even needed?
    CASE
        WHEN supplier_item_id IS NULL THEN FALSE
        WHEN TRIM(supplier_item_id) = '' THEN FALSE
        ELSE TRUE
    END AS is_valid_for_join

FROM staged_mappings
