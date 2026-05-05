/*
Intermediate Model: Extracted Data Combined - Compatibility Layer

This model adapts the new normalized extraction pipeline output (int__extracted_data_combined)
to match the schema expected by int__model_extracted_data, enabling downstream models
to work with either pipeline without changes.

Data lineage:
  stg__extracted_global_fields + stg__extracted_line_items
  → int__extracted_data_combined
  → int__extracted_data_items_cleaned (item-level patchfixes)
  → THIS MODEL (compatibility layer)
  → int__extracted_data_switched (when data_source='model_extracted_data')
  → int__invoice_items_mapped
  → downstream...

Key features:
- Maps new pipeline columns to old pipeline column names
- Applies email-derived vendor logic (same as int__model_extracted_data)
- Applies vendor suffix to items (same as int__model_extracted_data)
- Adds missing columns with NULL or default values
- Applies same filtering logic as old pipeline (validation, active status, etc.)
- Numeric casting and consistency checks

Note: This is a compatibility layer for Phase 5 pipeline switching.
The old pipeline remains the default for backwards compatibility.
*/

{{
  config(
    materialized='view',
    schema='intermediate'
  )
}}

WITH combined_data AS (
    SELECT * FROM {{ ref('int__extracted_data_items_cleaned') }}
),

-- Join with email queue and vendor mapping (same as int__model_extracted_data)
with_email_vendor AS (
    SELECT
        cd.*,
        -- Replace unreliable vendor with email-derived vendor
        evm.email_derived_vendor,
        -- Supplier name from user upload (NULL for email-sourced PDFs)
        uup.supplier_name AS upload_supplier_name,
        -- item_cleaned comes from upstream (already has leading digit stripped AND first word extracted for Flow Mark/Supreme)
        cd.item_cleaned,
        -- Apply vendor suffix - use COALESCE so NULL email_derived_vendor falls back to user-provided supplier name (never OCR fallback)
        {{ add_vendor_suffix('cd.item_cleaned', "COALESCE(evm.email_derived_vendor, uup.supplier_name, 'Unknown vendor')") }} AS item_with_suffix,
        eq.email_date as email_date
    FROM combined_data cd
    LEFT JOIN {{ ref('int__email_vendor_mapping') }} evm
        ON cd.email_queue_id::uuid = evm.email_queue_id
    LEFT JOIN {{ ref('stg__email_download_queue') }} eq
        ON cd.email_queue_id::uuid = eq.id
    LEFT JOIN {{ source('raw', 'user_uploaded_pdfs') }} uup
        ON cd.user_upload_id::uuid = uup.id
    -- Filter for downloaded emails or non-email records
    WHERE (eq.status = 'DOWNLOADED' OR eq.status IS NULL)
    -- Only keep records where the validation passed (model_approved)
    AND (
        cd.status = 'model_approved'
        -- OR the validation_score exceeds the minimum threshold
        OR cd.validation_score > {{ var('min_validation_score') }}
    )
    -- Only keep records where the item is not empty
    AND (cd.item != '' AND cd.item IS NOT NULL)
    -- Filter out descriptions that start with "invoice" (case-insensitive)
    AND NOT (cd.description IS NOT NULL AND UPPER(TRIM(cd.description)) LIKE 'INVOICE%')
    -- Filter out date-like descriptions (MM/DD/YY or MM/DD/YYYY pattern at start)
    AND NOT (cd.description IS NOT NULL AND TRIM(cd.description) ~ '^\d{1,2}/\d{1,2}/\d{2,4}(\s|$)')
    -- Filter out question mark descriptions
    AND NOT (cd.description IS NOT NULL AND TRIM(cd.description) = '?')
    -- TEMPORARY: Filter out Y & S Plumbing Supply invoices on or before 04/22/2018
    -- Reason: LLM fails to extract item and description properly for these older invoices
    -- COALESCE handles NULL propagation: when email_derived_vendor or date is NULL,
    -- NOT(NULL) evaluates to NULL which would incorrectly exclude the row
    AND NOT COALESCE(
        UPPER(TRIM(evm.email_derived_vendor)) = 'Y & S PLUMBING SUPPLY'
        AND cd.date <= '2018-04-22',
        FALSE
    )
),

-- Filename-level ref_no validation: Filter out entire filenames where ANY record has empty ref_no
-- Business rule: If ANY invoice line item in a PDF file has missing ref_no, reject the ENTIRE PDF file
filename_ref_no_validation AS (
    SELECT
        *,
        -- Apply persistent patch fix early so deduplication can rely on the normalized reference number
        regexp_replace(ref_no, '^1-', 'I-') AS patched_ref_no,

        -- Window function to check if ANY record in the filename has empty ref_no
        CASE WHEN MAX(
            CASE
                WHEN ref_no IS NULL
                     OR TRIM(ref_no) = ''
                     OR TRIM(ref_no) ~ '^[\s]*$'  -- whitespace-only pattern
                THEN 1
                ELSE 0
            END
        ) OVER (PARTITION BY filename) = 1
        THEN FALSE
        ELSE TRUE
        END AS filename_has_valid_ref_no
    FROM with_email_vendor
),

-- Deduplicate to latest extraction per logical invoice record
latest_only AS (
    SELECT *
    FROM (
        SELECT
            *,
            DENSE_RANK() OVER (
                -- Partition by business-logical invoice identity with SUFFIXED item:
                -- Email-derived Supplier + Invoice Number (Patched) + Invoice Date
                PARTITION BY COALESCE(email_derived_vendor, upload_supplier_name, vendor, email_queue_id::text, 'Unknown vendor'), patched_ref_no, date
                -- Order by most recent extraction with multiple tie-breakers for deterministic results
                ORDER BY
                    email_date DESC NULLS LAST,  -- Most recent extraction first to remove duplicates
                    validation_score DESC NULLS LAST,  -- Higher quality extraction first
                    status DESC NULLS LAST,  -- Prefer 'model_approved' over score-based approval
                    extraction_id DESC
            ) AS extraction_rank
        FROM filename_ref_no_validation
        WHERE filename_has_valid_ref_no = TRUE  -- Filter out filenames with ANY empty ref_no
    ) ranked
    WHERE extraction_rank = 1
),

transformed AS (
    SELECT
        invoice_items_id,
        filename,
        item,
        description,
        vendor,
        email_derived_vendor,  -- Include email-derived vendor for final output
        upload_supplier_name,  -- Include user-upload supplier name for final output
        date,
        -- Use early-patched ref_no
        patched_ref_no AS ref_no,
        po_number,
        customer_job,
        buyer,
        date_added,
        extraction_id AS invoice_id,  -- Map extraction_id to invoice_id for compatibility
        TRUE AS is_active,  -- Default to true for new pipeline
        NULL::text AS mpi_item,
        NULL::text AS mpi_description,
        NULL::text AS sheet_name,
        NULL::text AS class_,
        NULL::text AS account,
        NULL::text AS export_status,
        bill,
        NULL::text AS memo,
        model_name,
        status,
        validation_score,
        confidence_score,
        line_order,
        record_type,

        -- Safe numeric casting
        {{ safe_cast('amount', 'NUMERIC(18, 2)') }} AS amount_numeric,
        {{ safe_cast('cost', 'NUMERIC(18, 2)') }} AS cost_numeric,
        {{ safe_cast('qty', 'NUMERIC(18, 2)') }} AS qty_numeric,

        -- Keep raw values for audit
        amount AS amount_raw,
        cost AS cost_raw,
        qty AS qty_raw,

        -- Mathematical consistency check (tolerance of 1 cent)
        CASE
            WHEN {{ safe_cast('qty', 'NUMERIC(18, 2)') }} IS NOT NULL
                AND {{ safe_cast('cost', 'NUMERIC(18, 2)') }} IS NOT NULL
                AND {{ safe_cast('amount', 'NUMERIC(18, 2)') }} IS NOT NULL
            THEN ABS({{ safe_cast('amount', 'NUMERIC(18, 2)') }} - ({{ safe_cast('qty', 'NUMERIC(18, 2)') }} * {{ safe_cast('cost', 'NUMERIC(18, 2)') }})) < 0.01
            ELSE NULL
        END AS is_amount_consistent,

        -- Cents conversion (USD only)
        CASE
            WHEN {{ safe_cast('amount', 'NUMERIC(18, 2)') }} IS NOT NULL
            THEN ROUND({{ safe_cast('amount', 'NUMERIC(18, 2)') }} * 100)::int
        END AS amount_cents,
        CASE
            WHEN {{ safe_cast('cost', 'NUMERIC(18, 2)') }} IS NOT NULL
            THEN ROUND({{ safe_cast('cost', 'NUMERIC(18, 2)') }} * 100)::int
        END AS cost_cents,

        -- Item suffix already applied in staging step
        item_with_suffix

    FROM latest_only
)

SELECT
    invoice_items_id,
    filename,
    -- Use suffixed version for mapping joins
    -- Synthetic records (tax, freight, misc) get their item with vendor suffix
    CASE
        WHEN record_type = 'tax' THEN {{ add_vendor_suffix("'10 Materials'", "COALESCE(email_derived_vendor, upload_supplier_name, 'Unknown vendor')") }}
        WHEN record_type = 'freight' THEN {{ add_vendor_suffix("'FREIGHT'", "COALESCE(email_derived_vendor, upload_supplier_name, 'Unknown vendor')") }}
        WHEN record_type = 'misc_charge' THEN {{ add_vendor_suffix('item', "COALESCE(email_derived_vendor, upload_supplier_name, 'Unknown vendor')") }}
        ELSE item_with_suffix
    END AS item,
    description,
    -- Use best available vendor source:
    -- 1. email_derived_vendor  (email-based, most reliable)
    -- 2. upload_supplier_name  (user upload supplier, second priority)
    -- 3. 'Unknown vendor'      (fallback)
    COALESCE(email_derived_vendor, upload_supplier_name, 'Unknown vendor') AS vendor,
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

    -- Model tracking and quality metrics
    model_name,
    status,
    validation_score,
    confidence_score,

    -- Clean numeric columns
    amount_numeric AS amount,
    -- Tax/Freight records have no cost (set to 0), other records use computed cost
    CASE WHEN record_type IN ('tax', 'freight', 'misc_charge') THEN 0.00 ELSE cost_numeric END AS cost,
    qty_numeric AS qty,

    -- Raw values for audit
    amount_raw,
    cost_raw,
    qty_raw,

    -- Mathematical consistency and cents conversion
    is_amount_consistent,
    amount_cents,
    cost_cents,

    -- Line ordering for display
    line_order

FROM transformed
