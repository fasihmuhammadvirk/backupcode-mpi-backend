/*
Invoice Items with Normalized Fields

Adds normalization and account assignment logic on top of mapped invoice items.
This is the final intermediate layer before mart models.

Data lineage:
  stg__invoice_items → int__invoice_items → int__invoice_items_mapped → THIS MODEL → marts

Incremental Strategy:
  - MERGE on invoice_items_id, cascading from int__invoice_items_mapped via _dbt_updated_at
  - Detects: upstream changes (mapped model), user override additions/updates/removals
  - Post-hook DELETE handles re-extractions: removes rows whose invoice_items_id no longer
    exists in the upstream mapped table (orphaned by re-extraction ID changes)

*/

{{ config(
    materialized='incremental',
    unique_key='invoice_items_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    schema='intermediate',
    indexes=[
        {'columns': ['invoice_items_id'], 'unique': True},
        {'columns': ['item', 'vendor']},
        {'columns': ['is_active']},
        {'columns': ['_dbt_updated_at']},
        {'columns': ['is_overridden']},
        {'columns': ['invoice_voided_at']}
    ],
    post_hook=[
        "{% if not is_incremental() %}ANALYZE {{ this }}{% endif %}",
        "{% if is_incremental() %}DELETE FROM {{ this }} t WHERE NOT EXISTS (SELECT 1 FROM {{ ref('int__invoice_items_mapped') }} m WHERE m.invoice_items_id = t.invoice_items_id){% endif %}"
    ]
) }}

WITH mapped_items AS (
    SELECT * FROM {{ ref('int__invoice_items_mapped') }}
),

buyers_normalized AS (
    SELECT * FROM {{ ref('int__buyers') }}
),

vendors_normalized AS (
    SELECT * FROM {{ ref('int__vendors') }}
),

user_overrides AS (
    SELECT * FROM {{ ref('int__user_overrides') }}
),

invoice_voided AS (
    SELECT * FROM {{ source('public', 'invoice_voided') }}
),

{% if is_incremental() %}
-- Anchor the incremental watermark once so every change detector compares against
-- the same cut-off for this run.
last_run AS (
    SELECT COALESCE(MAX(_dbt_updated_at), '1900-01-01'::timestamp) AS max_ts
    FROM {{ this }}
),

changed_from_mapped AS (
    -- Why: upstream mapped rows changed (new extraction/mapping updates).
    -- Filter: only ids newer than this model's latest _dbt_updated_at.
    SELECT m.invoice_items_id
    FROM mapped_items m
    CROSS JOIN last_run lr
    WHERE m._dbt_updated_at > lr.max_ts
),

changed_from_override_upserts AS (
    -- Why: user created or edited overrides after last run.
    -- Filter:
    --   1) overridden_at > max_ts (recent override activity)
    --   2) numeric record_id only (safe bigint cast)
    --   3) id must exist in mapped_items (skip orphan/non-mapped override rows)
    SELECT m.invoice_items_id
    FROM user_overrides ov
    JOIN mapped_items m
        ON m.invoice_items_id::text = ov.record_id
    CROSS JOIN last_run lr
    WHERE ov.overridden_at > lr.max_ts
      AND ov.record_id ~ '^[0-9]+$'
),

previously_overridden AS (
    -- Snapshot of ids this model currently marks as overridden.
    SELECT t.invoice_items_id
    FROM {{ this }} t
    WHERE t.is_overridden = TRUE
),

currently_overridden AS (
    -- Snapshot of ids currently present in active override records.
    SELECT m.invoice_items_id
    FROM user_overrides ov
    JOIN mapped_items m
        ON m.invoice_items_id::text = ov.record_id
    WHERE ov.record_id ~ '^[0-9]+$'
),

changed_from_override_removals AS (
    -- Why: override was removed/reverted since last run.
    -- Filter: ids that were overridden before but are no longer in current overrides.
    SELECT p.invoice_items_id
    FROM previously_overridden p
    LEFT JOIN currently_overridden c
        ON p.invoice_items_id = c.invoice_items_id
    WHERE c.invoice_items_id IS NULL
),

changed_from_void_state AS (
    -- Why: void status changed and must be re-materialized.
    -- Branch A: newly voided now (exists in invoice_voided now, but target row was not voided).
    -- Branch B: restored now (target row was voided, but no longer matches invoice_voided join).
    SELECT m.invoice_items_id
    FROM mapped_items m
    JOIN invoice_voided iv
        ON m.ref_no = iv.ref_no
       AND m.date   = iv.date
       AND m.vendor = iv.vendor
    WHERE NOT EXISTS (
        SELECT 1
        FROM {{ this }} t
        WHERE t.invoice_items_id = m.invoice_items_id
          AND t.invoice_voided_at IS NOT NULL
    )

    UNION

    SELECT t.invoice_items_id
    FROM {{ this }} t
    WHERE t.invoice_voided_at IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM mapped_items m
          JOIN invoice_voided iv
              ON m.ref_no = iv.ref_no
             AND m.date   = iv.date
             AND m.vendor = iv.vendor
          WHERE m.invoice_items_id = t.invoice_items_id
      )
),

changed_invoice_items AS (
    -- Final incremental workset. UNION de-duplicates ids touched by multiple change signals.
    SELECT invoice_items_id FROM changed_from_mapped
    UNION
    SELECT invoice_items_id FROM changed_from_override_upserts
    UNION
    SELECT invoice_items_id FROM changed_from_override_removals
    UNION
    SELECT invoice_items_id FROM changed_from_void_state
),
{% endif %}

-- Compute effective field values by merging user overrides on top of mart values.
-- All downstream expressions MUST reference effective_* columns so that overrides
-- propagate consistently to assigned_account, corrected_amount, and normalized search
-- columns.  Numeric casts are guarded by a regex check to prevent cast failures when
-- a user submits a non-numeric string.
effective_values AS (
    SELECT
        m.*,
        COALESCE(ov.mpi_item,        m.resolved_mpi_item)        AS effective_mpi_item,
        COALESCE(ov.mpi_description, m.resolved_mpi_description) AS effective_mpi_description,
        COALESCE(ov.sheet_name,      m.resolved_sheet_name)      AS effective_sheet_name,
        COALESCE(ov.account,         m.account)                  AS effective_account,
        COALESCE(ov.memo,            m.memo)                     AS effective_memo,
        COALESCE(ov.description,     m.description)              AS effective_description,
        COALESCE(ov.qty,             m.qty)                      AS effective_qty,
        COALESCE(ov.customer_job,    m.customer_job)             AS effective_customer_job,
        COALESCE(ov.date,            m.date)                     AS effective_date,
        COALESCE(ov.vendor,          m.vendor)                   AS effective_vendor,
        COALESCE(ov.po_number,       m.po_number)                AS effective_po_number,
        COALESCE(ov.buyer,           m.buyer)                    AS effective_buyer,
        COALESCE(ov.class_,          m.class_)                   AS effective_class_,
        COALESCE(ov.cost,            m.cost)                     AS effective_cost,
        COALESCE(ov.amount,          m.amount)                   AS effective_amount,
        CASE WHEN ov.record_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_overridden,
        ov.customer_job IS NOT NULL AS is_customer_job_overridden,
        ov.overridden_by,
        ov.overridden_at,
        iv.invoice_voided_at,
        normalize_address_fn(COALESCE(ov.customer_job, m.customer_job)) AS _addr_pre_normalized
    FROM mapped_items m
    {% if is_incremental() %}
    -- On incremental runs, only process ids identified by changed_invoice_items.
    -- This avoids scanning/normalizing the full mapped table on every run.
    INNER JOIN changed_invoice_items ci
        ON ci.invoice_items_id = m.invoice_items_id
    {% endif %}
    LEFT JOIN user_overrides ov
        ON m.invoice_items_id::text = ov.record_id
    LEFT JOIN invoice_voided iv
        ON m.ref_no = iv.ref_no
       AND m.date   = iv.date
       AND m.vendor = iv.vendor
),

with_normalization AS (
    SELECT
        -- Pass through all columns from mapped_items
        e.invoice_items_id,
        e.filename,
        e.item,
        e.effective_description     AS description,
        e.effective_mpi_item        AS resolved_mpi_item,
        e.effective_mpi_description AS resolved_mpi_description,
        e.effective_sheet_name      AS resolved_sheet_name,
        e.effective_qty             AS qty,
        e.effective_cost            AS cost,
        e.effective_amount          AS amount,
        e.effective_date            AS date,
        e.ref_no,
        e.effective_po_number       AS po_number,
        e.effective_customer_job    AS customer_job,
        -- Vendor: use canonical supplier name if matched, otherwise original
        COALESCE(vn.matched_supplier_fuzzy, e.effective_vendor) AS vendor,
        e.vendor AS vendor_raw,
        e.effective_buyer           AS buyer,
        e.date_added,
        e.invoice_id,
        e.matched_supplier,
        e.matched_supplier_id,
        e.is_active,
        e.mapping_type,
        e.mapping_source,
        e.mapped_at,
        e.original_mpi_item,
        e.original_mpi_description,
        e.original_sheet_name,
        e.effective_account AS account,
        e.is_overridden,
        e.is_customer_job_overridden,
        e.overridden_by,
        e.overridden_at,

        -- Address normalization (pre-computed in effective_values to avoid 17× function re-evaluation)
        {{ normalize_address('e.effective_customer_job', precomputed_column='e._addr_pre_normalized') }} AS customer_job_normalized,
        e.customer_job AS original_customer_job,

        -- Sheet name normalization (using effective_sheet_name)
        {{ normalize_sheet_name('e.effective_sheet_name') }} AS sheet_name_normalized,

        -- Buyer normalization (from join)
        e.buyer AS original_buyer,
        bn.buyer_normalized_base,
        bn.buyer_normalized_canonical,

        -- Vendor normalization metadata (from fuzzy matching join)
        vn.matched_supplier_id_fuzzy AS vendor_supplier_id,
        vn.similarity_score AS vendor_match_score,

        -- Account assignment (uses effective values so overrides propagate)
        CASE
            -- 1. Preserve explicit 'A'
            WHEN UPPER(e.effective_account) = 'A' THEN 'A'
            -- 2. UIDI-specific mapping using effective mpi_item
            WHEN e.effective_mpi_item = 'UIDI - Job Materials Purchased' THEN 'M'
            WHEN e.effective_mpi_item = 'UIDI - Job Equipment' THEN 'E'
            -- 3. Fallback to sheet_name patterns
            WHEN LOWER(e.effective_sheet_name) LIKE '%job materials%' THEN 'M'
            WHEN LOWER(e.effective_sheet_name) LIKE '%job equipment%' THEN 'E'
            -- 4. Fallback to original account if it exists
            WHEN e.effective_account IS NOT NULL AND e.effective_account != '' THEN e.effective_account
            -- 5. Default to NULL if no rule applies
            ELSE NULL
        END AS assigned_account,

        -- Corrected amount (for credit memos, uses effective amount)
        CASE
            WHEN e.ref_no LIKE 'CR-%' THEN -ABS(e.effective_amount)
            ELSE e.effective_amount
        END AS corrected_amount,

        -- Reference number normalized (for dedup)
        CASE
            WHEN REGEXP_LIKE(e.ref_no, '^[A-Za-z]+-0+[0-9]+$')
                THEN SPLIT_PART(e.ref_no, '-', 1) || '-' || LTRIM(SPLIT_PART(e.ref_no, '-', 2), '0')
            WHEN REGEXP_LIKE(e.ref_no, '^0+[0-9]+[A-Za-z]+$')
                THEN LTRIM(e.ref_no, '0')
            WHEN REGEXP_LIKE(e.ref_no, '^[A-Za-z]+0+[0-9]+$')
                THEN REGEXP_REPLACE(e.ref_no, '([A-Za-z])0+', '\1')
            WHEN REGEXP_LIKE(e.ref_no, '^[0-9]+$')
                THEN LTRIM(e.ref_no, '0')
            ELSE e.ref_no
        END AS ref_no_normalized,

        -- Void state (from public.invoice_voided)
        e.invoice_voided_at,

        -- Keep additional fields for reference
        e.effective_class_  AS class_,
        e.bill,
        e.export_status,
        e.effective_memo AS memo,
        e.line_order,

        -- ============================================================================
        -- NORMALIZED COLUMNS FOR FUZZY SEARCH
        -- Pre-computed to eliminate expensive runtime REGEXP_REPLACE() calls
        -- ============================================================================

        -- Item columns (using effective values where appropriate)
        REGEXP_REPLACE(LOWER(SUBSTRING(e.item, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS item_normalized,
        REGEXP_REPLACE(LOWER(SUBSTRING(COALESCE(e.effective_mpi_item, e.item), 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS mpi_item_normalized,

        -- Description columns
        REGEXP_REPLACE(LOWER(SUBSTRING(e.effective_description, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS description_normalized,
        REGEXP_REPLACE(LOWER(SUBSTRING(COALESCE(e.effective_mpi_description, e.effective_description), 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS mpi_description_normalized,

        -- Vendor (pre-computed for fuzzy text search)
        REGEXP_REPLACE(LOWER(SUBSTRING(e.effective_vendor, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS vendor_search_normalized,

        -- Buyer (uses normalized buyer from joined buyers model for fuzzy search)
        REGEXP_REPLACE(LOWER(SUBSTRING(bn.buyer_normalized_base, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS buyer_normalized,

        -- Sheet name fuzzy (uses effective_sheet_name)
        REGEXP_REPLACE(
            LOWER(
                SUBSTRING(
                    {{ normalize_sheet_name('e.effective_sheet_name') }},
                    1, 1000
                )
            ),
            '[-_\s\(\)]+', ' ', 'g'
        ) AS sheet_name_normalized_fuzzy,

        -- Account normalized (uses effective_account)
        REGEXP_REPLACE(LOWER(SUBSTRING(e.effective_account, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS account_normalized,

        -- PO Number
        REGEXP_REPLACE(LOWER(SUBSTRING(e.effective_po_number, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS po_number_normalized,

        -- Export status
        REGEXP_REPLACE(LOWER(SUBSTRING(e.export_status, 1, 1000)), '[-_\s\(\)]+', ' ', 'g') AS export_status_normalized,

        CURRENT_TIMESTAMP AS _dbt_updated_at

    FROM effective_values e
    LEFT JOIN buyers_normalized bn
        ON e.effective_buyer = bn.buyer
    LEFT JOIN vendors_normalized vn
        ON e.effective_vendor = vn.vendor
)

SELECT * FROM with_normalization
