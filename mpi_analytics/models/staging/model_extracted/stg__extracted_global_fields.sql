/*
Staging Model: Extracted Global Fields

Parses global/header fields from raw_data JSONB in raw.model_extracted_data.
One row per extraction attempt.

Data lineage:
  raw.model_extracted_data → THIS MODEL → int__extracted_data_combined

Key features:
- Incremental processing based on extracted_at timestamp
- Multi-format date parsing (YYYY-MM-DD, MM/DD/YYYY, MM/DD/YY)
- Line item count for validation
- Validation metadata from raw_data
- Filters out records where parent pdf_extraction_queue has been soft-deleted
- Post-hook removes stale records when parent is soft-deleted after initial load

Note: This model is part of the new normalized extraction pipeline.
The old pipeline uses stg__model_extracted_data which reads from public.model_extracted_data.
*/

{{
  config(
    materialized='incremental',
    unique_key='extraction_invoice_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    schema='staging',
    post_hook=[
      "DELETE FROM {{ this }} WHERE extraction_id NOT IN (
        SELECT extraction_id FROM (
          SELECT extraction_id, ROW_NUMBER() OVER (PARTITION BY s3_file_key ORDER BY extracted_at DESC) AS rn
          FROM {{ this }}
        ) ranked WHERE rn = 1
      )",
      "DELETE FROM {{ this }} stg
       USING {{ source('raw', 'pdf_extraction_queue') }} peq
       WHERE stg.pdf_extraction_queue_id = peq.id
         AND peq.deleted_at IS NOT NULL",
      "DELETE FROM {{ this }} stg
       USING {{ source('raw', 'model_extracted_data') }} med
       WHERE stg.extraction_id = med.id
         AND med.deleted_at IS NOT NULL"
    ]
  )
}}

-- First time the system extracted each file with an extraction that passes
-- the minimum validation threshold applied downstream in the intermediate
-- layer (see int__extracted_data_combined_compat and int__model_extracted_data).
--
-- Includes soft-deleted rows so a later cleanup or re-extraction never resets
-- the anchor, but excludes rows that would have been filtered out as failed
-- extractions, so "date_added" reflects the first time a valid extraction
-- existed rather than the first time the system tried.
WITH first_seen AS (
    SELECT
        s3_file_key,
        MIN(extracted_at) AS first_extracted_at
    FROM {{ source('raw', 'model_extracted_data') }}
    WHERE status = 'model_approved'
       OR validation_score > {{ var('min_validation_score') }}
    GROUP BY s3_file_key
),

source AS (
    SELECT
        med.id,
        med.s3_file_key,
        med.pdf_extraction_queue_id,
        med.email_queue_id,
        peq.user_upload_id,
        med.model_name,
        med.prompt_hash,
        med.status,
        med.validation_score,
        med.confidence_score,
        med.raw_data,
        med.extracted_at,
        fs.first_extracted_at,
        med.deleted_at,
        med.deletion_reason,
        -- Keep only the most recent extraction per file to prevent stale data
        ROW_NUMBER() OVER (
            PARTITION BY med.s3_file_key
            ORDER BY med.extracted_at DESC
        ) AS extraction_rank
    FROM {{ source('raw', 'model_extracted_data') }} med
    -- Join to check parent pdf_extraction_queue soft-delete status
    -- Also used to read user_upload_id (which only exists on this table)
    LEFT JOIN {{ source('raw', 'pdf_extraction_queue') }} peq
        ON med.pdf_extraction_queue_id = peq.id
    LEFT JOIN first_seen fs
        ON fs.s3_file_key = med.s3_file_key
    WHERE med.deleted_at IS NULL
      -- Exclude records where parent pdf_extraction_queue has been soft-deleted
      AND (peq.deleted_at IS NULL OR peq.id IS NULL)
    {% if is_incremental() %}
      AND med.extracted_at >= (SELECT COALESCE(MAX(extracted_at), '1900-01-01'::timestamp) FROM {{ this }})
    {% endif %}
),

-- Filter to only the latest extraction per file
latest_extractions AS (
    SELECT * FROM source WHERE extraction_rank = 1
),

{{ unnest_invoices('latest_extractions', filter_non_invoices=true) }}

SELECT
    -- Identifiers
    ABS(HASHTEXTEXTENDED(id::text || '-' || invoice_index::text, 0)) AS extraction_invoice_id,
    id AS extraction_id,
    invoice_index,
    s3_file_key,
    s3_file_key AS filename,  -- Alias for compatibility with existing models
    pdf_extraction_queue_id,
    email_queue_id,
    user_upload_id,
    -- Extraction metadata
    model_name,
    prompt_hash,
    status,
    validation_score,
    confidence_score,
    extracted_at,
    -- date_added semantics: "first time the system extracted this file"
    -- (earliest extracted_at per s3_file_key). Stable across re-extractions
    -- and soft-delete cleanups, so downstream timelines show a fixed anchor
    -- rather than drifting forward on every reprocess.
    first_extracted_at AS date_added,
    deleted_at,

    -- Parse global fields from JSONB
    TRIM(invoice_obj->>'ref_no') AS ref_no,

    -- Multi-format date parsing
    CASE
        -- ISO format: YYYY-MM-DD
        WHEN invoice_obj->>'date' ~ '^\d{4}-\d{2}-\d{2}$'
        THEN (invoice_obj->>'date')::date
        -- US format with 4-digit year: MM/DD/YYYY
        WHEN invoice_obj->>'date' ~ '^\d{1,2}/\d{1,2}/\d{4}$'
        THEN TO_DATE(invoice_obj->>'date', 'MM/DD/YYYY')
        -- US format with 2-digit year: MM/DD/YY
        WHEN invoice_obj->>'date' ~ '^\d{1,2}/\d{1,2}/\d{2}$'
        THEN TO_DATE(invoice_obj->>'date', 'MM/DD/YY')
        ELSE NULL
    END AS date,

    TRIM(invoice_obj->>'vendor') AS vendor,
    TRIM(invoice_obj->>'buyer') AS buyer,
    TRIM(COALESCE(invoice_obj->>'po_no', invoice_obj->>'po_number')) AS po_number,
    TRIM(invoice_obj->>'customer_job') AS customer_job,
    TRIM(invoice_obj->>'bill') AS bill,

    -- Financial totals (stored as text, will be cast later)
    COALESCE(NULLIF(TRIM(invoice_obj->>'tax'), ''), '0') AS tax,
    TRIM(invoice_obj->>'sub_total') AS sub_total,
    COALESCE(NULLIF(TRIM(invoice_obj->>'freight'), ''), '0') AS freight,

    -- Line item count for validation
    COALESCE(jsonb_array_length(invoice_obj->'line_items'), 0) AS line_item_count,

    -- Misc charges array (pass through for unnesting in int__extracted_data_combined)
    invoice_obj->'misc_charges' AS misc_charges_raw,

    -- Validation metadata from raw_data
    (invoice_obj->>'_validation_passed')::boolean AS validation_passed,
    invoice_obj->'_header_details' AS header_validation_details,
    invoice_obj->'_line_items_details' AS line_items_validation_details

FROM invoices_unnested
