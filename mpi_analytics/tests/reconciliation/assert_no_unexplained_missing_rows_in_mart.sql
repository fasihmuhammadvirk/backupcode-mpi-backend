{{ config(tags=['reconciliation']) }}

/*
Test: No Unexplained Missing Rows in Mart
Description: Starts from staging sources (stg__extracted_line_items + stg__extracted_global_fields),
             LEFT JOINs to mart__invoice_items. For rows missing from the mart, categorizes them
             by the known business filter that explains the exclusion.
             Fails only on rows that are missing for no known reason.

Expected Result: 0 rows (test passes)
Failure Condition: Staging rows that should have reached the mart but didn't.

Known exclusion categories (not failures):
  - filtered_by_validation: validation_score <= threshold AND status != 'model_approved'
  - filtered_empty_item: item is NULL or empty
  - filtered_bad_description: description starts with "INVOICE", is date-like, or is "?"
  - filtered_empty_ref_no: ref_no is NULL or blank (entire PDF rejected)
  - filtered_dedup: superseded by a newer extraction of the same logical invoice
  - filtered_email_status: email queue record not in DOWNLOADED status
  - filtered_ys_date_cutoff: Y & S Plumbing Supply before 2018-04-22
  - filtered_item_cleaning: non-product items (Header, Customer Discount) or legacy codes
*/

/*
  Line items only have item-level data (item, description, qty, cost, amount).
  Global fields (ref_no, vendor, date, status, validation_score, email_queue_id)
  live on the invoice level in stg__extracted_global_fields. We need both to
  evaluate the business filters that happen downstream.
*/
WITH staging AS (
    SELECT
        li.line_item_id AS invoice_items_id,
        li.extraction_id,
        li.extraction_invoice_id,
        li.s3_file_key AS filename,
        li.item,
        li.description,
        li.amount,
        li.extracted_at,
        g.ref_no,
        g.vendor,
        g.date,
        g.status,
        g.validation_score,
        g.email_queue_id
    FROM {{ ref('stg__extracted_line_items') }} li
    INNER JOIN {{ ref('stg__extracted_global_fields') }} g
        ON li.extraction_invoice_id = g.extraction_invoice_id
),

/*
  Every staging row should have a matching mart row via line_item_id = invoice_items_id
  (deterministic hash set in int__extracted_data_combined).
  Rows that don't match are "missing from mart" and need to be explained.
*/
missing_from_mart AS (
    SELECT stg.*
    FROM staging stg
    LEFT JOIN {{ ref('mart__invoice_items') }} mart
        ON stg.invoice_items_id = mart.invoice_items_id
    WHERE mart.invoice_items_id IS NULL
),

/* Email metadata for checking email_status and sender/subject filters. */
email_status_lookup AS (
    SELECT id, status AS email_status, sender, subject
    FROM {{ ref('stg__email_download_queue') }}
),

/*
  Defined in: int__extracted_data_combined_compat (filename_ref_no_validation CTE).
  If ANY line item in a PDF file has an empty ref_no, the ENTIRE file is rejected
  (filename_has_valid_ref_no = FALSE). We replicate this by collecting all filenames
  where any staging row has a blank ref_no.
*/
filenames_with_empty_ref_no AS (
    SELECT DISTINCT s.filename
    FROM staging s
    WHERE s.ref_no IS NULL
       OR TRIM(s.ref_no) = ''
       OR TRIM(s.ref_no) ~ '^[\s]*$'
),

/*
  Defined in: int__extracted_data_combined_compat (latest_only CTE).
  The compat layer deduplicates by DENSE_RANK over (vendor, patched_ref_no, date),
  keeping only the "best" extraction (ordered by email_date, validation_score,
  status, extraction_id). Rows from losing extractions are dropped.

  We detect dedup losers by checking: does the mart already have rows for the
  same ref_no + date from a DIFFERENT extraction? If yes, this staging row
  lost the dedup race. We use mart.invoice_id (which equals extraction_id from
  the compat layer) instead of re-joining to staging, because the staging
  post-hook may delete old extractions. The regexp_replace mirrors the
  1- → I- ref_no patch applied in the compat layer.

  Note: The compat dedup key also includes vendor, but we can't reliably match
  on vendor here because the mart stores the resolved vendor (email-derived)
  while staging has the raw OCR vendor — they differ in spelling/casing.
  The risk of a false positive (different vendor, same ref_no + date) is low
  since invoice numbers are vendor-specific.
*/
dedup_losers AS (
    SELECT DISTINCT m.invoice_items_id
    FROM missing_from_mart m
    WHERE EXISTS (
        SELECT 1
        FROM {{ ref('mart__invoice_items') }} mart
        WHERE mart.invoice_id != m.extraction_id
          AND (
              mart.ref_no = m.ref_no
              OR mart.ref_no = regexp_replace(m.ref_no, '^1-', 'I-')
          )
          AND mart.date = m.date
    )
),

categorized AS (
    SELECT
        m.*,
        CASE
            /*
              Defined in: int__extracted_data_combined_compat (WHERE clause).
              Only rows with status='model_approved' OR validation_score > threshold survive.
            */
            WHEN m.status != 'model_approved'
                 AND (m.validation_score IS NULL OR m.validation_score <= {{ var('min_validation_score') }})
                THEN 'filtered_by_validation'

            /*
              Defined in: int__extracted_data_combined_compat (WHERE clause).
              Rows with empty or NULL item are excluded.
            */
            WHEN m.item IS NULL OR TRIM(m.item) = ''
                THEN 'filtered_empty_item'

            /*
              Defined in: int__extracted_data_combined_compat (WHERE clause).
              Descriptions starting with "INVOICE" are filtered out.
            */
            WHEN m.description IS NOT NULL AND UPPER(TRIM(m.description)) LIKE 'INVOICE%'
                THEN 'filtered_bad_description'

            /*
              Defined in: int__extracted_data_combined_compat (WHERE clause).
              Date-like descriptions (e.g. "01/15/2024") are filtered out.
            */
            WHEN m.description IS NOT NULL AND TRIM(m.description) ~ '^\d{1,2}/\d{1,2}/\d{2,4}(\s|$)'
                THEN 'filtered_date_description'

            /*
              Defined in: int__extracted_data_combined_compat (WHERE clause).
              Descriptions that are just "?" are filtered out.
            */
            WHEN m.description IS NOT NULL AND TRIM(m.description) = '?'
                THEN 'filtered_question_description'

            /*
              Defined in: int__extracted_data_combined_compat (filename_ref_no_validation CTE).
              If any line in the same PDF has empty ref_no, all lines in that file are rejected.
            */
            WHEN m.filename IN (SELECT filename FROM filenames_with_empty_ref_no)
                THEN 'filtered_empty_ref_no'

            /*
              Defined in: int__extracted_data_combined_compat (JOIN to email queue).
              Only emails with status='DOWNLOADED' (or no email record) pass through.
            */
            WHEN es.email_status IS NOT NULL AND es.email_status != 'DOWNLOADED'
                THEN 'filtered_email_status'

            /*
              Defined in: int__extracted_data_combined_compat (WHERE clause).
              Y & S Plumbing Supply invoices on or before 2018-04-22 are excluded because
              the LLM fails to extract item/description properly for older invoices.
              We use LIKE because staging has the OCR vendor name ('Y & S Plumbing Supplies')
              while compat uses the email-derived name ('Y & S PLUMBING SUPPLY').
            */
            WHEN UPPER(TRIM(m.vendor)) LIKE 'Y & S PLUMBING SUPPL%' AND m.date <= '2018-04-22'
                THEN 'filtered_ys_date_cutoff'

            /*
              Defined in: int__extracted_data_items_cleaned (rule_3_exclude_non_products CTE).
              Non-product line items like "Header" (contact info) and "Customer Discount"
              are excluded from the pipeline.
            */
            WHEN UPPER(TRIM(m.item)) IN ('HEADER', 'CUSTOMER DISCOUNT')
                THEN 'filtered_item_cleaning'

            /*
              Defined in: int__extracted_data_items_cleaned (final WHERE clause).
              Two specific legacy item codes are hardcoded for exclusion.
            */
            WHEN m.item IN ('SP*00001075', 'SP*00001076')
                THEN 'filtered_legacy_item'

            /*
              Defined in: int__extracted_data_combined_compat (latest_only CTE).
              This row's extraction lost the dedup race — another extraction for the same
              invoice (same ref_no + date) produced the rows that appear in the mart.
            */
            WHEN m.invoice_items_id IN (SELECT invoice_items_id FROM dedup_losers)
                THEN 'filtered_dedup'

            ELSE 'UNEXPLAINED'
        END AS exclusion_reason
    FROM missing_from_mart m
    LEFT JOIN email_status_lookup es ON m.email_queue_id = es.id
)

SELECT
    invoice_items_id,
    filename,
    item,
    description,
    ref_no,
    vendor,
    date,
    status,
    validation_score,
    exclusion_reason
FROM categorized
WHERE exclusion_reason = 'UNEXPLAINED'
