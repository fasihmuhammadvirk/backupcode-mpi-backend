/*
Intermediate Model: Item Cleaning Layer

Centralizes all item-level transformations and patchfixes.
Each cleaning rule is documented and applied in sequence.

Data lineage:
  int__extracted_data_combined
  → THIS MODEL (item cleaning)
  → int__extracted_data_combined_compat (vendor join + suffix)
*/

{{ config(materialized='view', schema='intermediate') }}

WITH source AS (
    SELECT * FROM {{ ref('int__extracted_data_combined') }}
),

/*
=============================================================================
ITEM CLEANING RULES
Each rule is applied sequentially. Add new rules as CTEs below.
=============================================================================
*/

-- Rule 1: Strip leading single digit prefix (ALL vendors)
-- Examples: "1 2402302" → "2402302", "1 28L" → "28L"
-- Pattern: digit + whitespace + rest → keep rest
-- See: https://github.com/Mpi-plumbing/mpi-backend/issues/463
-- Plumbing exchange doesn't have item codes so we use the description and some descriptions could start with
-- a leading integer
rule_1_strip_leading_digit AS (
    SELECT
        *,
        CASE
            WHEN TRIM(item) ~ '^\d\s+.+'
                AND UPPER(TRIM(vendor)) != 'PLUMBING EXCHANGE'
            THEN (regexp_match(TRIM(item), '^\d\s+(.+)$'))[1]
            ELSE TRIM(item)
        END AS item_after_rule_1
    FROM source
),

-- Rule 2: Take first word (Flow Mark & Supreme only)
-- Uses OCR vendor field (reliable for these two vendors)
-- Examples: "GA300WTG 29136" → "GA300WTG", "LPLE102M3 LE102M3" → "LPLE102M3"
-- See: https://github.com/Mpi-plumbing/mpi-backend/issues/462
rule_2_first_word AS (
    SELECT
        *,
        CASE
            WHEN UPPER(TRIM(vendor)) IN ('FLOW MARK PLUMBING SUPPLY', 'SUPREME PLUMBING SUPPLY')
            THEN COALESCE((regexp_match(item_after_rule_1, '^([^[:space:]]+)'))[1], item_after_rule_1)
            ELSE item_after_rule_1
        END AS item_after_rule_2
    FROM rule_1_strip_leading_digit
),

-- Rule 3: Exclude non-product items (ALL vendors)
-- These are line items that should never be mapped (discounts, headers, etc.)
-- See: https://github.com/Mpi-plumbing/mpi-backend/issues/473
rule_3_exclude_non_products AS (
    SELECT *
    FROM rule_2_first_word
    WHERE (
        UPPER(TRIM(item_after_rule_2)) NOT IN (
            'CUSTOMER DISCOUNT',
            'HEADER'
        )
        OR record_type = 'misc_charge'
    )
),

-- Final output: pass through all columns, add cleaned item
final AS (
    SELECT
        -- Pass through all original columns (from int__extracted_data_combined)
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
        item,  -- keep original
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
        record_type,
        -- Add cleaned item column
        item_after_rule_2 AS item_cleaned
    FROM rule_3_exclude_non_products
    -- Exclude legacy item codes per user request
    WHERE item NOT IN ('SP*00001075', 'SP*00001076')
)

SELECT * FROM final
