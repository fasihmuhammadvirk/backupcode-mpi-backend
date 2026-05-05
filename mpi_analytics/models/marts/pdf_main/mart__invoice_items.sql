-- Mart model for invoice items, optimized for PDF generation and reporting.
-- See mart__invoice_items.yml for detailed documentation.

{{
    config(
        materialized='incremental',
        unique_key='invoice_items_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        tags=['pdf', 'reporting', 'invoice'],
        indexes=[
            {'columns': ['invoice_items_id'], 'unique': True},
            {'columns': ['date']},
            {'columns': ['vendor']},
            {'columns': ['customer_job']},
            {'columns': ['sheet_name']},
            {'columns': ['date', 'vendor', 'customer_job']},
            {'columns': ['item']},
            {'columns': ['description']},
            {'columns': ['ref_no']},
            {'columns': ['item_normalized']},
            {'columns': ['description_normalized']},
            {'columns': ['vendor_search_normalized']},
            {'columns': ['customer_job_normalized']},
            {'columns': ['date_added', 'invoice_items_id']},
            {'columns': ['invoice_voided_at']},
            {'columns': ['_dbt_updated_at']}
        ],
        post_hook=[
            "{% if not is_incremental() %}ANALYZE {{ this }}{% endif %}",
            "{% if is_incremental() %}DELETE FROM {{ this }} t WHERE NOT EXISTS (SELECT 1 FROM {{ ref('int__invoice_items_with_rerated_pricing') }} n WHERE n.invoice_items_id = t.invoice_items_id){% endif %}",
            "ALTER TABLE {{ this }} ALTER COLUMN date SET STATISTICS 1000",
            "ALTER TABLE {{ this }} ALTER COLUMN vendor SET STATISTICS 1000",
            "ALTER TABLE {{ this }} ALTER COLUMN customer_job SET STATISTICS 1000"
        ]
    )
}}

{#
  Mart Table Optimization Strategy:

  Indexes:
  1. invoice_items_id (unique) - Primary key for fast lookups
  2. date - Date range filters (very common)
  3. vendor - Vendor filtering
  4. customer_job - Location filtering
  5. sheet_name - Category filtering
  6. (date, vendor, customer_job) - Composite index for common filter combinations
  7. item - Item code search
  8. description - Description search
  9. ref_no - Reference number search
  10. item_normalized - Fuzzy search on normalized item codes
  11. description_normalized - Fuzzy search on normalized descriptions
  12. vendor_search_normalized - Fuzzy search on normalized vendor names
  13. customer_job_normalized - Fuzzy search on normalized locations
  14. (date, invoice_items_id) - Sorting optimization for default ORDER BY date DESC, invoice_items_id DESC

  Post-hooks:
  - ANALYZE: Updates PostgreSQL statistics for better query planning (full refresh only)
  - Re-extraction cleanup DELETE: Removes orphaned rows left behind when invoices are
    re-extracted (new extraction_id → new invoice_items_id, old rows no longer in source)
  - SET STATISTICS 1000: Increases stats sampling for accurate COUNT estimates
#}

WITH invoice_items_intermediate AS (
    -- Source: Selects all transformed data from the rerated intermediate model.
    -- WHY: The rerated intermediate carries the Y & S BOX→EACH price/qty corrections
    --      so that the App's Data Review tab displays the same per-unit cost/qty
    --      that the Price Changes tab uses for its comparison. See issue #899.
    SELECT *
    FROM {{ ref('int__invoice_items_with_rerated_pricing') }}
    -- Incremental: only pick up rows updated since last run (cascades via _dbt_updated_at)
    {% if is_incremental() %}
    WHERE _dbt_updated_at > (SELECT COALESCE(MAX(_dbt_updated_at), '1900-01-01'::timestamp) FROM {{ this }})
    {% endif %}
),

-- Address extraction: structured address components from customer_job
customer_job_addresses AS (
    SELECT *
    FROM {{ ref('int__customer_job_addresses') }}
),

selected_columns AS (
    SELECT
        i.invoice_items_id,
        i.invoice_id,
        i.item,
        i.description,
        i.resolved_mpi_item AS mpi_item,
        i.resolved_mpi_description AS mpi_description,
        -- Raw values from upstream are passed through unchanged so existing
        -- consumers keep their current behavior. The Y & S BOX→EACH UOM
        -- correction is exposed alongside via `rerated_cost`, `rerated_qty`,
        -- and `is_price_rerated` so the FE can opt in (e.g. to display the
        -- corrected value with a tooltip).
        i.qty,
        i.cost,
        i.amount,
        i.ref_no,
        i.vendor,

        -- Customer job: use extracted address if available, fallback to normalized.
        -- If user manually overrode this field, respect their raw value (e.g. for casing).
        CASE 
            WHEN i.is_customer_job_overridden THEN i.customer_job
            ELSE COALESCE(addr.extracted_address, i.customer_job_normalized)
        END AS customer_job,

        -- Additional address components from extraction
        addr.street_number,
        addr.street_name_with_suffix AS street_name,
        addr.city,
        addr.state,
        addr.zip_code,
        addr.extraction_confidence AS address_confidence,

        i.buyer_normalized_canonical AS buyer,
        i.class_,
        i.account,
        i.po_number,
        i.sheet_name_normalized AS sheet_name,
        i.date,
        i.assigned_account,

        -- Additional fields for compatibility with invoice_items table
        i.filename,
        i.bill,
        i.export_status,
        i.memo,
        i.date_added,

        -- Normalized columns for fuzzy search (pre-computed REGEXP_REPLACE)
        -- Convention: all normalized columns use {column}_normalized naming
        i.item_normalized,
        i.mpi_item_normalized,
        i.description_normalized,
        i.mpi_description_normalized,
        i.vendor_search_normalized,
        i.buyer_normalized,
        i.sheet_name_normalized_fuzzy AS sheet_name_normalized,
        -- Use extracted address for normalized customer_job too, unless overridden
        REGEXP_REPLACE(
            LOWER(SUBSTRING(
                CASE 
                    WHEN i.is_customer_job_overridden THEN i.customer_job
                    ELSE COALESCE(addr.extracted_address, i.customer_job_normalized)
                END, 
                1, 1000
            )),
            '[-_\s\(\)]+', ' ', 'g'
        ) AS customer_job_normalized,
        i.ref_no_normalized,
        i.line_order,
        i.invoice_voided_at,

        -- Y & S BOX→EACH rerating (see int__invoice_items_with_rerated_pricing).
        -- Equal to cost/qty when is_price_rerated = FALSE.
        i.rerated_cost,
        i.rerated_qty,
        i.is_price_rerated,

        CURRENT_TIMESTAMP AS _dbt_updated_at
    FROM invoice_items_intermediate i
    LEFT JOIN customer_job_addresses addr
        ON i.customer_job = addr.customer_job
)

SELECT * FROM selected_columns
