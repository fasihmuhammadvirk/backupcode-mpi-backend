/*
  mart__item_mapping_timeline
  Full historical event stream of mapping status transitions for each item.

  One row per state change (e.g. no_match -> temporary -> permanent -> no_match).
  Captures:
    1. Initial 'no_match' as the earliest date_added (when the system first
       ingested the item), falling back to invoice date for legacy rows.
    2. Status changes (mapping_type) from Google Sheet snapshots.
    3. Expiration/Deletion (hard deletes) as a transition back to 'no_match'.

  Usage:
    - Powers the /unmapped-items/mapping-timeline API endpoint
    - Enables frontend to show the full lifecycle of any item
*/

{{ config(
    materialized='table',
    indexes = [
        {'columns': ['supplier_item_ids']},
        {'columns': ['supplier_item_ids','supplier_id']},
    ]
) }}

-- 1. Initial "no_match" event from invoice records.
--    recorded_at uses date_added (when the system first observed the item),
--    falling back to the invoice date for legacy rows where date_added is NULL.
--    Using invoice date alone is misleading because users can upload historical
--    invoices long after the invoice date, making an item appear "unmapped since
--    {invoice_date}" even though the system only became aware of it on date_added.
WITH invoice_first_seen AS (
    SELECT
        MAX(supplier_id) AS supplier_id,
        item AS supplier_item_ids,
        vendor AS supplier,
        sheet_name AS sheet_title,
        MIN(COALESCE(date_added, date)) AS recorded_at
    FROM {{ ref('mart__invoice_items_map') }}
    WHERE item IS NOT NULL
      AND TRIM(item) != ''
    GROUP BY item, sheet_name, vendor
),

-- 2. Cleaned snapshot history: Filter only rows where mapping_type actually changed
snapshot_changes AS (
    SELECT
        supplier_item_ids,
        supplier_id,
        supplier,
        mapping_type,
        mpi_code,
        sheet_title,
        dbt_valid_from AS recorded_at,
        dbt_valid_to,
        -- Detect status change compared to previous version of the same conceptual item
        LAG(mapping_type) OVER (
            PARTITION BY supplier_item_ids, sheet_title
            ORDER BY dbt_valid_from
        ) AS prev_mapping_type
    FROM {{ ref('snp__google_sheet_mappings') }}
),

-- 3. Transition events back to "no_match" if an item was deleted/expired from the sheet
deletion_events_pre AS (
    SELECT
        supplier_item_ids,
        supplier_id,
        supplier,
        sheet_title,
        'no_match' AS mapping_type,
        NULL       AS mpi_code,
        dbt_valid_to AS recorded_at,
        MAX(dbt_valid_to) OVER (
          PARTITION BY supplier_item_ids, sheet_title
        ) AS max_dbt_valid_to
    FROM snapshot_changes
    WHERE dbt_valid_to IS NOT NULL
),

deletion_events AS (
    SELECT
        supplier_item_ids,
        supplier_id,
        supplier,
        mapping_type,
        mpi_code,
        sheet_title,
        recorded_at
    FROM deletion_events_pre
    WHERE recorded_at = max_dbt_valid_to
      -- And ensure there isn't a newer active row (dbt_valid_to IS NULL) starting after this delete
      AND NOT EXISTS (
          SELECT 1 FROM {{ ref('snp__google_sheet_mappings') }} newer
          WHERE newer.supplier_item_ids = deletion_events_pre.supplier_item_ids
            AND newer.sheet_title = deletion_events_pre.sheet_title
            AND newer.dbt_valid_to IS NULL
      )
),

-- 4. Unified event pool
all_history_events AS (
    -- Case A: Starting no_match (from invoices)
    SELECT
        supplier_item_ids,
        supplier_id,
        supplier,
        'no_match' AS mapping_type,
        NULL       AS mpi_code,
        sheet_title,
        recorded_at,
        false AS is_delete_record
    FROM invoice_first_seen

    UNION ALL

    -- Case B: Status transitions (e.g. temp, permanent)
    SELECT
        supplier_item_ids,
        supplier_id,
        supplier,
        mapping_type,
        mpi_code,
        sheet_title,
        recorded_at,
        false AS is_delete_record
    FROM snapshot_changes
    WHERE prev_mapping_type IS NULL OR mapping_type != prev_mapping_type

    UNION ALL

    -- Case C: Hard deletions -> back to no_match
    SELECT
        supplier_item_ids,
        supplier_id,
        supplier,
        mapping_type,
        mpi_code,
        sheet_title,
        recorded_at,
        true AS is_delete_record
    FROM deletion_events
)

SELECT
    -- Stable unique ID for each EVENT (item + timestamp)
    {{ dbt_utils.generate_surrogate_key([
        'supplier_item_ids',
        'sheet_title',
        'recorded_at'
    ]) }} AS id,

    supplier_item_ids,
    supplier_id,
    supplier,
    mapping_type,
    mpi_code,
    sheet_title,
    recorded_at,
    is_delete_record,
    
    CURRENT_TIMESTAMP AS mart_refreshed_at

FROM all_history_events
WHERE {{ should_include_sheet('sheet_title') }}
ORDER BY supplier_item_ids, recorded_at ASC
