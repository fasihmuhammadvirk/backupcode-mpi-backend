/*
Mart Invoice Items
Final table consumed by the application
Replaces the current invoice_items table for reads
*/

{{ config(
    materialized='incremental',
    unique_key='id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    indexes=[
        {'columns': ['id'], 'unique': True},
        {'columns': ['item']},
        {'columns': ['vendor']},
        {'columns': ['mapping_type']},
        {'columns': ['date']},
        {'columns': ['_dbt_updated_at']}
    ],
    post_hook=[
        "{% if not is_incremental() %}ANALYZE {{ this }}{% endif %}",
        "{% if is_incremental() %}DELETE FROM {{ this }} t WHERE NOT EXISTS (SELECT 1 FROM {{ ref('int__invoice_items_with_rerated_pricing') }} n WHERE n.invoice_items_id = t.id){% endif %}",
        "{% if is_incremental() %}DELETE FROM {{ this }} t WHERE EXISTS (SELECT 1 FROM {{ ref('int__invoice_items_with_rerated_pricing') }} n WHERE n.invoice_items_id = t.id AND n.invoice_voided_at IS NOT NULL){% endif %}"
    ]
) }}

WITH normalized_items AS (
    -- Source: rerated intermediate so QuickBooks export and Mapping pages
    -- reflect Y & S BOX→EACH corrected cost/qty (issue #899).
    SELECT * FROM {{ ref('int__invoice_items_with_rerated_pricing') }}
    -- Incremental: only pick up rows updated since last run (cascades via _dbt_updated_at)
    {% if is_incremental() %}
    WHERE _dbt_updated_at > (SELECT COALESCE(MAX(_dbt_updated_at), '1900-01-01'::timestamp) FROM {{ this }})
    {% endif %}
)

SELECT
    -- Primary key
    invoice_items_id AS id,

    -- File and invoice tracking
    filename,
    invoice_id,
    ref_no,
    po_number,

    -- Original item data (preserved)
    item,
    description,

    -- Resolved mapping values (use these for analysis)
    resolved_sheet_name AS sheet_name,
    resolved_mpi_item AS mpi_item,
    resolved_mpi_description AS mpi_description,

    -- Supplier info
    matched_supplier AS supplier,
    matched_supplier_id AS supplier_id,
    vendor,

    -- Financial data. Raw `qty` / `cost` are passed through unchanged. The
    -- Y & S BOX→EACH rerated values are exposed alongside via `rerated_cost`,
    -- `rerated_qty`, `is_price_rerated` so consumers can opt in.
    -- Total spend (`amount`) is preserved by rerating construction.
    qty,
    cost,
    amount,
    rerated_cost,
    rerated_qty,
    is_price_rerated,

    -- Job and customer tracking
    customer_job,
    buyer,

    -- Date fields
    date,
    date_added,

    -- Account assignment (now from intermediate layer)
    assigned_account AS account,

    -- Status
    is_active,

    -- Audit columns
    mapping_type,
    mapping_source,
    mapped_at,

    -- Original values (for reference)
    original_mpi_item,
    original_mpi_description,
    original_sheet_name,

    CURRENT_TIMESTAMP AS _dbt_updated_at

FROM normalized_items
WHERE (is_active = TRUE OR is_active IS NULL)
  AND invoice_voided_at IS NULL
