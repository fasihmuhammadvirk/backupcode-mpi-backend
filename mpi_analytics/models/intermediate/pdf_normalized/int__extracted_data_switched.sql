/*
Intermediate Model: Extracted Data Switch Point

This model acts as a switch point between the old and new extraction pipelines,
allowing downstream models to work with either pipeline without modification.

Usage:
  - Default (new pipeline): dbt run --select int__invoice_items_mapped+
  - Old pipeline: dbt run --select int__invoice_items_mapped+ --vars '{"data_source": "public.model_extracted_data"}'

Data lineage (default - new pipeline):
  raw.model_extracted_data (JSONB)
  → stg__extracted_global_fields + stg__extracted_line_items
  → int__extracted_data_combined
  → int__extracted_data_combined_compat
  → THIS MODEL
  → int__invoice_items_mapped
  → downstream...

Data lineage (old pipeline with data_source='public.model_extracted_data'):
  stg__model_extracted_data
  → int__model_extracted_data
  → THIS MODEL
  → int__invoice_items_mapped
  → downstream...

Configuration:
  data_source (dbt variable):
    - 'default' (default): Use new normalized pipeline (int__extracted_data_combined_compat)
    - 'public.model_extracted_data': Use old pipeline (int__model_extracted_data)

Note: The new pipeline is now the default after validation.
Use the old pipeline flag only for backwards compatibility or debugging.
*/

{{
  config(
    materialized='view',
    schema='intermediate'
  )
}}

{% set data_source = var('data_source', 'default') %}

{% if data_source == 'public.model_extracted_data' %}
{#
  OLD PIPELINE: Uses the original extraction from public.model_extracted_data
  Use this flag for backwards compatibility or debugging
#}
SELECT
    invoice_items_id,
    filename,
    item,
    description,
    vendor,
    date,
    ref_no,
    po_number,
    customer_job,
    buyer,
    date_added,
    invoice_id,
    is_active,
    mpi_item,
    mpi_description,
    sheet_name,
    class_,
    account,
    export_status,
    bill,
    memo,
    model_name,
    status,
    validation_score,
    confidence_score,
    amount,
    cost,
    qty,
    amount_raw,
    cost_raw,
    qty_raw,
    is_amount_consistent,
    amount_cents,
    cost_cents,
    -- line_order not available in old pipeline (column removed from public.model_extracted_data)
    NULL::integer AS line_order
FROM {{ ref('int__model_extracted_data') }}

{% else %}
{#
  NEW PIPELINE (DEFAULT): Uses the new normalized extraction from raw.model_extracted_data JSONB
  The compatibility layer ensures column names match the old pipeline output
#}
SELECT
    invoice_items_id,
    filename,
    item,
    description,
    vendor,
    date,
    ref_no,
    po_number,
    customer_job,
    buyer,
    date_added,
    invoice_id,
    is_active,
    mpi_item,
    mpi_description,
    sheet_name,
    class_,
    account,
    export_status,
    bill,
    memo,
    model_name,
    status,
    validation_score,
    confidence_score,
    amount,
    cost,
    qty,
    amount_raw,
    cost_raw,
    qty_raw,
    is_amount_consistent,
    amount_cents,
    cost_cents,
    line_order
FROM {{ ref('int__extracted_data_combined_compat') }}

{% endif %}
