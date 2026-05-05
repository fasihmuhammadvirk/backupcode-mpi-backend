/* See stg__invoice_items.yml for documentation */
{{ config(
  materialized='view',
  schema='staging'
) }}

SELECT
  -- IDs and Keys
  id::numeric AS invoice_items_id,
  invoice_id::text AS invoice_id,

  -- Item Information
  {{ strip_newlines("item::text") }} AS item,
  TRIM(mpi_item::text) AS mpi_item,
  {{ strip_newlines("description::text") }} AS description,
  TRIM(mpi_description::text) AS mpi_description,

  -- Supplier and Customer Information
  TRIM(vendor::text) AS vendor,
  TRIM(customer_job::text) AS customer_job,
  TRIM(buyer::text) AS buyer,

  -- Financials
  -- TODO: We should use int and convert to cents to prevent floating point errors
  TRIM(cost::text) AS cost,
  TRIM(qty::text) AS qty,
  TRIM(amount::text) AS amount,

  -- Accounting and Classification
  TRIM(class_::text) AS class_, -- not sure what this is
  TRIM(account::text) AS account,

  -- References and Metadata
  TRIM(ref_no::text) AS ref_no,
  TRIM(po_number::text) AS po_number,
  TRIM(sheet_name::text) AS sheet_name,
  TRIM(export_status::text) AS export_status,
  is_active::boolean AS is_active,
  filename::text AS filename,
  bill::text AS bill,
  memo::text AS memo,

  -- Dates
  date::date AS date,
  date_added::date AS date_added

FROM {{ source('public', 'invoice_items') }}
