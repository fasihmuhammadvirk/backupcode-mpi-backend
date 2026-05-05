/*
Intermediate Invoice Items with Resolved Mappings

Maps invoice line items to MPI items through priority-based matching:
1. Permanent mappings - supplier_item → mpi_code + mpi_description
2. Temporary mappings - supplier_item → sheet_name only → generates UIDI-{Job Equipment/Job Materials Purchased}
3. Possible match - for unmatched items, suggests matches found by:
   a. Removing trailing suffix (-B, -Y pattern) from item code
   b. Case-insensitive matching
4. No match - item not found in any mapping → 'No Match'

Pipeline Switching:
  - Default: Uses old pipeline (int__model_extracted_data)
  - New pipeline: Run with --vars '{"data_source": "model_extracted_data"}'
    to use the new normalized pipeline (int__extracted_data_combined_compat)

Incremental Strategy:
  - MERGE on invoice_items_id (deterministic hash of extraction_id + invoice_index + line_order)
  - Detects: new invoices (date_added), mapping changes (extraction_timestamp vs _dbt_updated_at)
  - Post-hook DELETE handles re-extractions: when an invoice is re-extracted, it gets a new
    extraction_id → new invoice_items_id. The staging layer deletes old extraction rows, so the
    source view no longer contains the old IDs. The post-hook DELETE removes these orphaned rows
    from this table to prevent duplicate line items.

*/

{{ config(
    materialized='incremental',
    unique_key='invoice_items_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    schema='intermediate',
    indexes=[
        {'columns': ['invoice_items_id'], 'unique': True},
        {'columns': ['item']},
        {'columns': ['mapping_type']},
        {'columns': ['date_added']},
        {'columns': ['_dbt_updated_at']}
    ],
    post_hook=[
        "{% if not is_incremental() %}ANALYZE {{ this }}{% endif %}",
        "{% if is_incremental() %}DELETE FROM {{ this }} t WHERE NOT EXISTS (SELECT 1 FROM {{ ref('int__extracted_data_switched') }} s WHERE s.invoice_items_id = t.invoice_items_id){% endif %}"
    ]
) }}

-- Source invoice items
-- Uses switching model to support both old and new extraction pipelines
-- Note: mpi_item, mpi_description, sheet_name from PDF extraction are untrustworthy
-- They are kept as original_* columns for audit/comparison only
WITH invoice_items AS (
    SELECT
        invoice_items_id,
        filename,
        item,           -- Join key (supplier's item code from invoice)
        description,    -- Invoice description (used as fallback)
        vendor,
        date,
        ref_no,
        po_number,
        customer_job,
        buyer,
        date_added,
        invoice_id,
        class_,
        account,
        export_status,
        bill,
        memo,
        amount,
        cost,
        qty,
        is_active,
        -- Original values from PDF extraction (untrustworthy - for audit only)
        mpi_item AS original_mpi_item,
        mpi_description AS original_mpi_description,
        sheet_name AS original_sheet_name,
        line_order
    FROM {{ ref('int__extracted_data_switched') }}
    {% if is_incremental() %}
    WHERE
        -- 1. New invoice data: pick up rows added since last run (1-hour buffer for late arrivals)
        date_added > (SELECT COALESCE(MAX(date_added), '1900-01-01'::timestamp) - interval '1 hour' FROM {{ this }})
        -- 2. Permanent mapping changed: re-process items whose mapping was updated in Google Sheets
        OR invoice_items_id IN (
            SELECT t.invoice_items_id
            FROM {{ this }} t
            INNER JOIN {{ ref('int__permanent_mappings') }} pm
                ON TRIM(t.item) = TRIM(pm.supplier_item)
            WHERE pm.extraction_timestamp > t._dbt_updated_at
        )
        -- 3. Temporary mapping changed: same logic for temporary (sheet-only) mappings
        OR invoice_items_id IN (
            SELECT t.invoice_items_id
            FROM {{ this }} t
            INNER JOIN {{ ref('int__temporary_mappings') }} tm
                ON TRIM(t.item) = TRIM(tm.original_item)
            WHERE tm.extraction_timestamp > t._dbt_updated_at
        )
    {% endif %}
),

permanent_mappings AS (
    SELECT * FROM {{ ref('int__permanent_mappings') }}
),

temporary_mappings AS (
    SELECT * FROM {{ ref('int__temporary_mappings') }}
),

-- Step 1: Try permanent mapping (exact match on trimmed item codes)
with_permanent AS (
    SELECT
        i.*,
        p.mpi_code,
        p.mpi_description,
        p.sheet_name,
        p.supplier,
        p.supplier_id,
        p.mapping_source,
        p.extraction_timestamp AS perm_extraction_ts,
        CASE WHEN p.mpi_code IS NOT NULL THEN 'permanent' END AS match_type
    FROM invoice_items i
    LEFT JOIN permanent_mappings p
        ON LOWER(TRIM(i.item)) = LOWER(TRIM(p.supplier_item))
),

-- Step 2: Try temporary mapping if no permanent match found
with_fallback AS (
    SELECT
        wp.*,
        t.sheet_name AS temp_sheet_name,
        t.original_description AS temp_description,
        t.mapping_source AS temp_mapping_source,
        t.extraction_timestamp AS temp_extraction_ts,
        CASE
            WHEN wp.match_type = 'permanent' THEN 'permanent'
            WHEN t.original_item IS NOT NULL THEN 'temporary'
            ELSE 'no_match'
        END AS final_match_type
    FROM with_permanent wp
    LEFT JOIN temporary_mappings t
        ON TRIM(wp.item) = TRIM(t.original_item)
        AND wp.match_type IS NULL  -- Only attempt temp match if no permanent found
),

-- Step 3.a: Find possible matches via suffix removal (-B, -Y pattern)
suffix_possible AS (
    SELECT DISTINCT ON (wf.invoice_items_id)
        wf.invoice_items_id,
        COALESCE(p.sheet_name, t.sheet_name) AS suffix_sheet_name,
        p.mpi_code AS suffix_possible_code
    FROM with_fallback wf
    LEFT JOIN permanent_mappings p
        ON TRIM(REGEXP_REPLACE(wf.item, '-[A-Za-z]$', '')) = TRIM(p.supplier_item)
    LEFT JOIN temporary_mappings t
        ON TRIM(REGEXP_REPLACE(wf.item, '-[A-Za-z]$', '')) = TRIM(t.original_item)
        AND p.mpi_code IS NULL
    WHERE wf.final_match_type = 'no_match'
      AND wf.item ~ '-[A-Za-z]$'
      AND (p.mpi_code IS NOT NULL OR t.sheet_name IS NOT NULL)
    ORDER BY wf.invoice_items_id, p.mpi_code NULLS LAST
),

-- Step 3.b: Find possible matches via case-insensitive matching
case_possible AS (
    SELECT DISTINCT ON (wf.invoice_items_id)
        wf.invoice_items_id,
        COALESCE(p.sheet_name, t.sheet_name) AS case_sheet_name,
        p.mpi_code AS case_possible_code
    FROM with_fallback wf
    LEFT JOIN permanent_mappings p
        ON UPPER(TRIM(wf.item)) = UPPER(TRIM(p.supplier_item))
        AND TRIM(wf.item) != TRIM(p.supplier_item)
    LEFT JOIN temporary_mappings t
        ON UPPER(TRIM(wf.item)) = UPPER(TRIM(t.original_item))
        AND TRIM(wf.item) != TRIM(t.original_item)
        AND p.mpi_code IS NULL
    WHERE wf.final_match_type = 'no_match'
      AND (p.mpi_code IS NOT NULL OR t.sheet_name IS NOT NULL)
    ORDER BY wf.invoice_items_id, p.mpi_code NULLS LAST
),

-- Step 4: Deduplicate to ensure one row per invoice item
-- (handles cases where multiple mappings match the same item)
with_dedup AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY invoice_items_id
            ORDER BY
                -- Priority: permanent > temporary > no_match
                CASE final_match_type
                    WHEN 'permanent' THEN 1
                    WHEN 'temporary' THEN 2
                    ELSE 3
                END,
                -- Within same match type, prefer earlier mapping (deterministic)
                mpi_code NULLS LAST,
                temp_sheet_name NULLS LAST
        ) AS rn
    FROM with_fallback
),

-- Step 5: Resolve final values based on match priority
final AS (
    SELECT
        -- Identifiers
        wd.invoice_items_id,
        wd.filename,
        wd.item,
        wd.description,

        -- Resolved MPI values (priority: permanent > temporary > no_match)
        CASE wd.final_match_type
            WHEN 'permanent' THEN wd.mpi_code
            WHEN 'temporary' THEN {{ resolve_temp_mpi_item('wd.temp_sheet_name') }}
            ELSE
                CASE
                    WHEN sp.suffix_possible_code IS NOT NULL AND cp.case_possible_code IS NOT NULL
                         AND sp.suffix_possible_code != cp.case_possible_code
                    THEN 'Possible match: ' || sp.suffix_possible_code || ', ' || cp.case_possible_code
                    WHEN sp.suffix_possible_code IS NOT NULL
                    THEN 'Possible match: ' || sp.suffix_possible_code
                    WHEN cp.case_possible_code IS NOT NULL
                    THEN cp.case_possible_code
                    ELSE 'No Match'
                END
        END AS resolved_mpi_item,

        CASE wd.final_match_type
            WHEN 'permanent' THEN wd.mpi_description
            WHEN 'temporary' THEN COALESCE(wd.temp_description, wd.description)
            ELSE 'No Match'
        END AS resolved_mpi_description,

        CASE wd.final_match_type
            WHEN 'permanent' THEN wd.sheet_name
            WHEN 'temporary' THEN wd.temp_sheet_name
            ELSE COALESCE(sp.suffix_sheet_name, cp.case_sheet_name)
        END AS resolved_sheet_name,

        -- Financial data
        wd.qty,
        wd.cost,
        wd.amount,

        -- Invoice metadata
        wd.date,
        wd.ref_no,
        wd.po_number,
        wd.customer_job,
        wd.vendor,
        wd.buyer,
        wd.date_added,
        wd.invoice_id,

        -- Supplier info (from permanent mapping only)
        wd.supplier AS matched_supplier,
        wd.supplier_id AS matched_supplier_id,

        -- Status and additional fields
        wd.is_active,
        wd.class_,
        wd.account,
        wd.bill,
        wd.export_status,
        wd.memo,
        wd.line_order,

        -- Audit columns
        CASE
            WHEN wd.final_match_type = 'no_match'
                 AND (sp.suffix_possible_code IS NOT NULL OR cp.case_possible_code IS NOT NULL)
            THEN 'possible_match'
            ELSE wd.final_match_type
        END AS mapping_type,
        CASE
            WHEN wd.final_match_type = 'permanent' THEN wd.mapping_source
            WHEN wd.final_match_type = 'temporary' THEN wd.temp_mapping_source
            WHEN sp.suffix_possible_code IS NOT NULL OR cp.case_possible_code IS NOT NULL
            THEN 'possible_match'
            ELSE 'unmapped'
        END AS mapping_source,
        CURRENT_TIMESTAMP AS mapped_at,

        CASE wd.final_match_type
            WHEN 'permanent' THEN wd.perm_extraction_ts
            WHEN 'temporary' THEN wd.temp_extraction_ts
            ELSE NULL
        END AS _mapping_extraction_ts,
        CURRENT_TIMESTAMP AS _dbt_updated_at,

        -- Original values from PDF extraction (untrustworthy - for audit/comparison)
        wd.original_mpi_item,
        wd.original_mpi_description,
        wd.original_sheet_name

    FROM with_dedup wd
    LEFT JOIN suffix_possible sp ON wd.invoice_items_id = sp.invoice_items_id
    LEFT JOIN case_possible cp ON wd.invoice_items_id = cp.invoice_items_id
    WHERE wd.rn = 1
)

SELECT * FROM final
