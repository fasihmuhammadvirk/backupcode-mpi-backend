/* See: int__extracted_data_combined.yml for documentation */

{{
  config(
    materialized='view',
    schema='intermediate'
  )
}}

WITH globals AS (
    SELECT * FROM {{ ref('stg__extracted_global_fields') }}
),

line_items AS (
    SELECT * FROM {{ ref('stg__extracted_line_items') }}
),

-- Line items with global fields joined
line_items_with_globals AS (
    SELECT
        li.line_item_id AS invoice_items_id,
        li.extraction_id,
        g.s3_file_key,
        g.filename,
        g.pdf_extraction_queue_id,
        g.email_queue_id,
        g.user_upload_id,

        -- Global fields
        g.ref_no,
        g.date,
        g.vendor,
        g.buyer,
        g.po_number,
        g.customer_job,
        g.bill,

        -- Line item fields (use item_code which has Flow Mark split applied)
        -- Fee/surcharge rows have no product code: item, qty, and cost
        -- are all empty. Promote description to item so downstream
        -- add_vendor_suffix appends the vendor code and the row becomes
        -- matchable (e.g., "Gas Surcharge" --> "Gas Surcharge-XX").
        CASE
            WHEN UPPER(TRIM(g.vendor)) = 'PLUMBING EXCHANGE'
                 AND (li.item_code IS NULL OR TRIM(li.item_code) = '')
                 AND li.description IS NOT NULL AND TRIM(li.description) != ''
            THEN TRIM(li.description)
            WHEN (li.item_code IS NULL OR TRIM(li.item_code) = '')
                 AND (li.qty IS NULL OR TRIM(li.qty) = '')
                 AND (li.cost IS NULL OR TRIM(li.cost) = '')
                 AND li.description IS NOT NULL AND TRIM(li.description) != ''
                 AND li.amount IS NOT NULL AND TRIM(li.amount) != ''
            THEN TRIM(li.description)
            ELSE li.item_code
        END AS item,
        li.description,
        li.qty,
        li.cost,
        CASE
            WHEN g.ref_no ILIKE 'cr-%' THEN
                CASE
                    WHEN li.amount IS NULL THEN NULL
                    ELSE '-' || regexp_replace(li.amount, '^-', '')
                END
            ELSE li.amount
        END AS amount,
        li.line_order,

        -- Metadata
        g.model_name,
        g.status,
        g.validation_score,
        g.confidence_score,
        g.extracted_at,
        g.date_added,

        -- Global totals (for reference, not used in line items)
        g.tax AS global_tax,
        g.sub_total,
        g.freight,

        -- Line item count (for reference)
        g.line_item_count,

        'line_item' AS record_type

    FROM line_items li
    INNER JOIN globals g ON li.extraction_invoice_id = g.extraction_invoice_id
),

-- Tax as separate records (one per extraction with non-zero tax)
tax_records AS (
    SELECT
        -- Deterministic integer ID for tax record using extraction_id + 'tax' string
        -- Uses ABS(HASHTEXTEXTENDED()) for 64-bit entropy to avoid collisions on unique index
        ABS(HASHTEXTEXTENDED(extraction_invoice_id::text || '-tax', 0)) AS invoice_items_id,
        extraction_id,
        s3_file_key,
        filename,
        pdf_extraction_queue_id,
        email_queue_id,
        user_upload_id,

        -- Global fields
        ref_no,
        date,
        vendor,
        buyer,
        po_number,
        customer_job,
        bill,

        -- Tax as line item
        '10 Materials' AS item,
        'Tax' AS description,
        NULL::text AS qty,
        NULL::text AS cost,
        CASE
            WHEN ref_no ILIKE 'cr-%' THEN
                CASE
                    WHEN tax IS NULL THEN NULL
                    ELSE '-' || regexp_replace(tax, '^-', '')
                END
            ELSE tax
        END AS amount,
        line_item_count + 1 AS line_order,  -- After all line items

        -- Metadata
        model_name,
        status,
        validation_score,
        confidence_score,
        extracted_at,
        date_added,

        -- Global totals
        tax AS global_tax,
        sub_total,
        freight,

        -- Line item count
        line_item_count,

        'tax' AS record_type

    FROM globals
),

-- Freight as separate records (one per extraction, show Freight even if missing or 0)
freight_records AS (
    SELECT
        -- Deterministic integer ID for freight record using extraction_id + 'freight' string
        -- Uses ABS(HASHTEXTEXTENDED()) for 64-bit entropy to avoid collisions on unique index
        ABS(HASHTEXTEXTENDED(extraction_invoice_id::text || '-freight', 0)) AS invoice_items_id,
        extraction_id,
        s3_file_key,
        filename,
        pdf_extraction_queue_id,
        email_queue_id,
        user_upload_id,

        -- Global fields
        ref_no,
        date,
        vendor,
        buyer,
        po_number,
        customer_job,
        bill,

        -- Freight as line item
        'FREIGHT' AS item,
        'Freight' AS description,
        NULL::text AS qty,
        NULL::text AS cost,
        freight AS amount,
        line_item_count + 2 AS line_order,  -- After tax

        -- Metadata
        model_name,
        status,
        validation_score,
        confidence_score,
        extracted_at,
        date_added,

        -- Global totals
        tax AS global_tax,
        sub_total,
        freight,

        -- Line item count
        line_item_count,

        'freight' AS record_type

    FROM globals
),

-- Misc charges as separate records (one per misc charge entry, e.g. RETURN FEE, RESTOCK FEE)
misc_charges_records AS (
    SELECT
        -- Deterministic integer ID for each misc charge using extraction_id + 'misc' + ordinal
        ABS(HASHTEXTEXTENDED(extraction_invoice_id::text || '-misc-' || mc_order::text, 0)) AS invoice_items_id,
        extraction_id,
        s3_file_key,
        filename,
        pdf_extraction_queue_id,
        email_queue_id,
        user_upload_id,

        -- Global fields
        ref_no,
        date,
        vendor,
        buyer,
        po_number,
        customer_job,
        bill,

        -- Misc charge as line item
        UPPER(TRIM(mc.charge->>'label')) AS item,
        TRIM(mc.charge->>'label') AS description,
        NULL::text AS qty,
        NULL::text AS cost,
        TRIM(mc.charge->>'amount') AS amount,
        line_item_count + 2 + mc_order::int AS line_order,  -- After freight (line_item_count + 2)

        -- Metadata
        model_name,
        status,
        validation_score,
        confidence_score,
        extracted_at,
        date_added,

        -- Global totals
        tax AS global_tax,
        sub_total,
        freight,

        -- Line item count
        line_item_count,

        'misc_charge' AS record_type

    FROM globals,
    LATERAL jsonb_array_elements(misc_charges_raw) WITH ORDINALITY AS mc(charge, mc_order)
)

SELECT
    invoice_items_id,
    extraction_id,
    s3_file_key,
    filename,
    pdf_extraction_queue_id,
    email_queue_id,
    user_upload_id,
    ref_no,
    date,
    vendor,
    buyer,
    po_number,
    customer_job,
    bill,
    item,
    description,
    qty,
    cost,
    amount,
    line_order,
    model_name,
    status,
    validation_score,
    confidence_score,
    extracted_at,
    date_added,
    global_tax,
    sub_total,
    freight,
    line_item_count,
    record_type
FROM line_items_with_globals

UNION ALL

SELECT
    invoice_items_id,
    extraction_id,
    s3_file_key,
    filename,
    pdf_extraction_queue_id,
    email_queue_id,
    user_upload_id,
    ref_no,
    date,
    vendor,
    buyer,
    po_number,
    customer_job,
    bill,
    item,
    description,
    qty,
    cost,
    amount,
    line_order,
    model_name,
    status,
    validation_score,
    confidence_score,
    extracted_at,
    date_added,
    global_tax,
    sub_total,
    freight,
    line_item_count,
    record_type
FROM tax_records

UNION ALL

SELECT
    invoice_items_id,
    extraction_id,
    s3_file_key,
    filename,
    pdf_extraction_queue_id,
    email_queue_id,
    user_upload_id,
    ref_no,
    date,
    vendor,
    buyer,
    po_number,
    customer_job,
    bill,
    item,
    description,
    qty,
    cost,
    amount,
    line_order,
    model_name,
    status,
    validation_score,
    confidence_score,
    extracted_at,
    date_added,
    global_tax,
    sub_total,
    freight,
    line_item_count,
    record_type
FROM freight_records

UNION ALL

SELECT
    invoice_items_id,
    extraction_id,
    s3_file_key,
    filename,
    pdf_extraction_queue_id,
    email_queue_id,
    user_upload_id,
    ref_no,
    date,
    vendor,
    buyer,
    po_number,
    customer_job,
    bill,
    item,
    description,
    qty,
    cost,
    amount,
    line_order,
    model_name,
    status,
    validation_score,
    confidence_score,
    extracted_at,
    date_added,
    global_tax,
    sub_total,
    freight,
    line_item_count,
    record_type
FROM misc_charges_records
