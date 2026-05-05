/*
Staging Model: Extracted Line Items

Explodes line_items array from raw_data JSONB in raw.model_extracted_data.
One row per line item.

Data lineage:
  raw.model_extracted_data → THIS MODEL → int__extracted_data_combined

Key features:
- Uses jsonb_array_elements WITH ORDINALITY to get line_order
- Generates deterministic surrogate key from (extraction_id, invoice_index, line_order)
- Incremental processing based on extracted_at timestamp
- Filters out records where parent pdf_extraction_queue has been soft-deleted
- Post-hook removes stale records when parent is soft-deleted after initial load

Note: This model is part of the new normalized extraction pipeline.
The old pipeline uses stg__model_extracted_data which reads from public.model_extracted_data.
*/

{{
  config(
    materialized='incremental',
    unique_key='line_item_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    schema='staging',
    post_hook=[
      "DELETE FROM {{ this }} WHERE extraction_id NOT IN (
        SELECT extraction_id FROM (
          SELECT extraction_id, ROW_NUMBER() OVER (PARTITION BY s3_file_key ORDER BY extracted_at DESC) AS rn
          FROM (SELECT DISTINCT extraction_id, s3_file_key, extracted_at FROM {{ this }}) dist
        ) ranked WHERE rn = 1
      )",
      "DELETE FROM {{ this }} stg
       USING {{ source('raw', 'model_extracted_data') }} med,
             {{ source('raw', 'pdf_extraction_queue') }} peq
       WHERE stg.extraction_id = med.id
         AND med.pdf_extraction_queue_id = peq.id
         AND peq.deleted_at IS NOT NULL",
      "DELETE FROM {{ this }} stg
       USING {{ source('raw', 'model_extracted_data') }} med
       WHERE stg.extraction_id = med.id
         AND med.deleted_at IS NOT NULL"
    ]
  )
}}

WITH source AS (
    SELECT
        med.id AS extraction_id,
        med.s3_file_key,
        med.model_name,
        med.extracted_at,
        med.raw_data,
        -- Keep only the most recent extraction per file to prevent stale data
        ROW_NUMBER() OVER (
            PARTITION BY med.s3_file_key
            ORDER BY med.extracted_at DESC
        ) AS extraction_rank
    FROM {{ source('raw', 'model_extracted_data') }} med
    -- Join to check parent pdf_extraction_queue soft-delete status
    LEFT JOIN {{ source('raw', 'pdf_extraction_queue') }} peq
        ON med.pdf_extraction_queue_id = peq.id
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

{{ unnest_invoices('latest_extractions', filter_line_items=true, filter_non_invoices=true) }},

exploded AS (
    SELECT
        s.extraction_id,
        s.s3_file_key,
        s.model_name,
        s.extracted_at,
        s.invoice_index,
        li.line_item,
        li.line_order::int AS line_order
    FROM invoices_unnested s,
    LATERAL jsonb_array_elements(s.invoice_obj->'line_items') WITH ORDINALITY AS li(line_item, line_order)
)

SELECT
    -- Deterministic integer ID from extraction_id (UUID) + line_order
    -- Uses ABS(HASHTEXTEXTENDED()) for 64-bit entropy to avoid collisions on unique index
    ABS(HASHTEXTEXTENDED(extraction_id::text || '-' || invoice_index::text || '-' || line_order::text, 0)) AS line_item_id,

    -- Foreign key to global fields
    ABS(HASHTEXTEXTENDED(extraction_id::text || '-' || invoice_index::text, 0)) AS extraction_invoice_id,
    extraction_id,
    invoice_index,
    s3_file_key,
    s3_file_key AS filename,  -- Alias for compatibility
    model_name,
    extracted_at,
    line_order,

    -- Parse line item fields
    {{ strip_newlines("line_item->>'item'") }} AS item,
    -- item_code uses full item value (no split)
    {{ strip_newlines("line_item->>'item'") }} AS item_code,
    {{ strip_newlines("line_item->>'description'") }} AS description,
    TRIM(line_item->>'qty') AS qty,
    TRIM(line_item->>'cost') AS cost,
    TRIM(line_item->>'amount') AS amount,

    -- Keep raw line item for debugging
    line_item AS raw_line_item

FROM exploded
