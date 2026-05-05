/*
  snp__google_sheet_mappings
  ──────────────────────────────────────────────────────────────────────────────
  DBT Snapshot — Slowly Changing Dimension (Type 2) for Google Sheet mappings.

  Purpose:
    Automatically tracks the full history of mapping_type and mpi_code changes
    for every supplier item in raw.raw_google_sheet_mappings.

  Usage:
    Reference in dbt models:  {{ ref('snp__google_sheet_mappings') }}
    Powers mart__item_mapping_timeline.
*/

{% snapshot snp__google_sheet_mappings %}

{{
    config(
        target_schema = 'snapshots',
        unique_key    = 'sheet_supplier_unique_key',
        strategy      = 'check',
        check_cols    = ['mapping_type', 'mpi_code'],
        invalidate_hard_deletes = True
    )
}}

WITH processed AS (
    SELECT
        coalesce(lower(trim(sheet_title)), '') as sheet_title_clean,
        coalesce(lower(trim(supplier_item_ids)), '') as supplier_item_ids_clean,
        -- Generated hash based key based on sheet_title and supplier_item_ids
        {{ dbt_utils.generate_surrogate_key(["coalesce(lower(trim(sheet_title)), '')","coalesce(lower(trim(supplier_item_ids)), '')"]) }} as sheet_supplier_unique_key,

        sheet_title,
        google_sheet_name,
        sheet_id,

        -- MPI mapping data
        mpi_code,
        description             AS mpi_description,

        -- Supplier info
        supplier,
        supplier_id,

        -- Supplier item code (the key field for all joins)
        supplier_item_ids,

        -- Classification — the two columns dbt watches for changes
        mapping_type,
        validation_status,

        -- Debugging metadata
        row_number,
        column_index,

        -- Source timestamps (preserved for auditability)
        extraction_timestamp,
        loaded_at,
        CASE WHEN mapping_type='permanent' THEN 2
             WHEN mapping_type='temporary' THEN 1 ELSE 0 END AS priority

    FROM {{ source('raw', 'raw_google_sheet_mappings') }}

    -- Only snapshot rows that are usable for history tracking
    WHERE supplier_item_ids IS NOT NULL
      AND TRIM(supplier_item_ids) != ''
      AND mapping_type IS NOT NULL
      AND mapping_type != ''
),

prioritized AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY sheet_supplier_unique_key
            ORDER BY priority DESC
        ) AS rn
    FROM processed
)

SELECT
    sheet_title_clean,
    supplier_item_ids_clean,
    sheet_supplier_unique_key,

    sheet_title,
    google_sheet_name,
    sheet_id,

    -- MPI mapping data
    mpi_code,
    mpi_description,

    -- Supplier info
    supplier,
    supplier_id,

    -- Supplier item code (the key field for all joins)
    supplier_item_ids,

    -- Classification — the two columns dbt watches for changes
    mapping_type,
    validation_status,

    -- Debugging metadata
    row_number,
    column_index,

    -- Source timestamps (preserved for auditability)
    extraction_timestamp,
    loaded_at
FROM prioritized
WHERE rn = 1

{% endsnapshot %}
