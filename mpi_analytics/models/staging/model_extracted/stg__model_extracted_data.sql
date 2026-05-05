/*
See stg__model_extracted_data.yml for documentation.

Note: Excludes records where parent pdf_extraction_queue has been soft-deleted.
*/
{{ config(
  materialized='view',
  schema='staging'
) }}

SELECT
  -- IDs and Keys
  med.id::numeric AS invoice_items_id,
  med.pdf_extraction_queue_id::text AS invoice_id,

  -- Item Information - preserve raw item value
  -- Flow Mark splitting is handled in intermediate layer where vendor is available
  {{ strip_newlines("med.item::text") }} AS item,
  NULL::text AS mpi_item,  -- Not available in model_extracted_data
  {{ strip_newlines("med.description::text") }} AS description,
  NULL::text AS mpi_description,  -- Not available in model_extracted_data

  -- Supplier and Customer Information
  TRIM(med.vendor::text) AS vendor,
  TRIM(med.customer_job::text) AS customer_job,
  TRIM(med.buyer::text) AS buyer,

  -- Financials
  TRIM(med.qty::text) AS qty,
  TRIM(med.cost::text) AS cost,
  TRIM(med.amount::text) AS amount,
  TRIM(med.tax::text) AS tax,

  -- Accounting and Classification
  NULL::text AS class_,  -- Not available in model_extracted_data
  NULL::text AS account,  -- Not available in model_extracted_data

  -- References and Metadata
  TRIM(med.ref_no::text) AS ref_no,
  TRIM(med.po_number::text) AS po_number,
  NULL::text AS sheet_name,  -- Not available in model_extracted_data
  NULL::text AS export_status,  -- Not available in model_extracted_data
  TRUE::boolean AS is_active,  -- Always true for model_extracted_data
  med.s3_file_key::text AS filename,
  med.bill::text AS bill,
  NULL::text AS memo,  -- Not available in model_extracted_data

  -- Dates
  med.date::date AS date,
  med.extracted_at::date AS date_added,

  -- Model tracking and quality metrics
  med.model_name::text AS model_name,
  med.status::text AS status,
  med.validation_score::numeric AS validation_score,
  med.confidence_score::numeric AS confidence_score,

  -- Keep email_queue_id for downstream transformations
  med.email_queue_id::text AS email_queue_id

FROM {{ source('public', 'model_extracted_data') }} med
-- Join to check parent pdf_extraction_queue soft-delete status
LEFT JOIN {{ source('raw', 'pdf_extraction_queue') }} peq
    ON med.pdf_extraction_queue_id = peq.id
-- Filter out records extracted before January 15, 2026 at 1:00 AM
-- Reason: we created and deployed a prompt that produce good results on that timestamp
WHERE med.extracted_at >= '2026-01-15 01:00:00'
AND med.deleted_at IS NULL
-- Exclude records where parent pdf_extraction_queue has been soft-deleted
AND (peq.deleted_at IS NULL OR peq.id IS NULL)
-- We are commentings this out because we only have gemini models in productions
-- but we should have a specific list of which models are approved for production
-- WHERE model_name in ('gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-2.5-pro')
