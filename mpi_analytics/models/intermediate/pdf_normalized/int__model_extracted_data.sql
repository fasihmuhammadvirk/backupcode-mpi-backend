/*
Model Extracted Data - Cleanup and Preparation

Cleans AI-extracted invoice data and prepares it for mapping joins.
Handles: safe numeric casting, item suffix normalization, basic data cleanup.

Data lineage:
  stg__model_extracted_data → THIS MODEL → int__invoice_items_mapped → int__invoice_items_with_normalized_fields → marts

Note: This model mirrors the structure of int__invoice_items to maintain consistency
in the data pipeline and enable seamless switching between data sources.

Note: This is the OLD pipeline. The new pipeline uses raw.model_extracted_data with
int__extracted_data_combined which handles tax records from JSONB.
*/

{{ config(
    materialized='view',
    schema='intermediate'
) }}

WITH model_extracted_staged AS (
    SELECT
        stage.*,
        evm.email_derived_vendor,
        -- Clean item: Flow Mark items need whitespace-split (e.g., "GA300WTG 29136" or "GA300WTG\n29136" -> "GA300WTG")
        -- Uses POSIX regex to extract first non-whitespace sequence (handles spaces, newlines, tabs)
        -- Other vendors keep item as-is
        CASE
            WHEN UPPER(TRIM(evm.email_derived_vendor)) = 'FLOW MARK PLUMBING SUPPLY'
            THEN (regexp_match(TRIM(stage.item), '^([^[:space:]]+)'))[1]
            ELSE TRIM(stage.item)
        END AS item_cleaned,
        -- Apply vendor suffix using email-derived vendor BEFORE deduplication
        -- Use cleaned item (with Flow Mark split applied)
        {{ add_vendor_suffix(
            "CASE WHEN UPPER(TRIM(evm.email_derived_vendor)) = 'FLOW MARK PLUMBING SUPPLY' THEN (regexp_match(TRIM(stage.item), '^([^[:space:]]+)'))[1] ELSE TRIM(stage.item) END",
            'evm.email_derived_vendor'
        ) }} AS item_with_suffix
    FROM {{ ref('stg__model_extracted_data') }} stage
    LEFT JOIN {{ ref('int__email_vendor_mapping') }} evm
        ON stage.email_queue_id::uuid = evm.email_queue_id
    LEFT JOIN {{ ref('stg__email_download_queue') }} eq
        ON stage.email_queue_id::uuid = eq.id
    -- Only keep active records
    WHERE (stage.is_active = true OR stage.is_active IS NULL)
    -- Filter for downloaded emails or non-email records
    AND (eq.status = 'DOWNLOADED' OR eq.status IS NULL)
    -- Only keep records where the validation passed (model_approved)
    AND (
        stage.status = 'model_approved'
        -- OR the validation_score exceeds the minimum threshold
        OR stage.validation_score > {{ var('min_validation_score') }}
    )
    -- Only keep records where the org item is not empty
    AND (stage.item != '' AND stage.item IS NOT NULL)
    -- Filter out descriptions that start with "invoice" (case-insensitive)
    AND NOT (stage.description IS NOT NULL AND UPPER(TRIM(stage.description)) LIKE 'INVOICE%')
    -- Filter out date-like descriptions (MM/DD/YY or MM/DD/YYYY pattern at start)
    AND NOT (stage.description IS NOT NULL AND TRIM(stage.description) ~ '^\d{1,2}/\d{1,2}/\d{2,4}(\s|$)')
    -- Filter out question mark descriptions
    AND NOT (stage.description IS NOT NULL AND TRIM(stage.description) = '?')
    -- TEMPORARY: Filter out Y & S Plumbing Supply invoices on or before 04/22/2018
    -- Reason: LLM fails to extract item and description properly for these older invoices
    AND NOT (
        UPPER(TRIM(evm.email_derived_vendor)) = 'Y & S PLUMBING SUPPLY'
        AND stage.date <= '2018-04-22'
    )
),

-- Filename-level ref_no validation: Filter out entire filenames where ANY record has empty ref_no
-- Business rule: If ANY invoice line item in a PDF file has missing ref_no, reject the ENTIRE PDF file
filename_ref_no_validation AS (
    SELECT
        *,
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
    FROM model_extracted_staged
),

-- Deduplicate to latest extraction per logical invoice record
-- Incorporates lessons from previous invoice uniqueness issues:
-- - Different suppliers can use same invoice number
-- - Same supplier can reuse invoice numbers on different dates
-- - Multiple items per invoice are legitimate
-- Supports append-only reprocessing where failed extractions are retried.
latest_only AS (
    SELECT *
    FROM (
        SELECT
            *,
            ROW_NUMBER() OVER (
                -- Partition by business-logical invoice identity with SUFFIXED item:
                -- Email-derived Supplier + Invoice Number + Invoice Date + Item (with vendor suffix)
                -- This ensures deduplication works correctly on the final item codes with reliable vendor data
                -- NOTE: Old pipeline cannot preserve duplicate item codes on same invoice
                -- because line_order is not available. Use new pipeline (default) instead.
                PARTITION BY email_derived_vendor, ref_no, date, item_with_suffix
                -- Order by most recent extraction with multiple tie-breakers for deterministic results
                ORDER BY
                    date_added DESC NULLS LAST,  -- Most recent extraction first
                    validation_score DESC NULLS LAST,  -- Higher quality extraction first
                    status DESC NULLS LAST,  -- Prefer 'model_approved' over score-based approval
                    invoice_items_id DESC  -- Final deterministic tie-breaker
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
        date,
        -- patch fix: The model is picking up ref numbers wrong
        regexp_replace(ref_no, '^1-', 'I-') AS ref_no,
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
    -- Use suffixed version for mapping joins, Tax records get '10 Materials' with vendor suffix
    CASE
        WHEN description = 'Tax' THEN {{ add_vendor_suffix("'10 Materials'", 'email_derived_vendor') }}
        ELSE item_with_suffix
    END AS item,
    description,
    email_derived_vendor AS vendor,  -- Use reliable email-derived vendor
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
    -- Tax records have no cost (set to 0), other records use computed cost
    CASE WHEN description = 'Tax' THEN 0.00 ELSE cost_numeric END AS cost,
    qty_numeric AS qty,

    -- Raw values for audit
    amount_raw,
    cost_raw,
    qty_raw,

    -- Mathematical consistency and cents conversion
    is_amount_consistent,
    amount_cents,
    cost_cents

FROM transformed
