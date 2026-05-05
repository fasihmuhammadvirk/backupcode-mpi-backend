{{ config(tags=['reconciliation']) }}

/*
Test: Amount Reconciliation (Per-Row)
Description: For each staging row that matched to the mart (same invoice_items_id),
             compares the numeric amount at the row level. Excludes rows with known
             legitimate transformations:
             - Credit memo sign flips (CR- ref_no prefix)
             - User overrides that changed the amount
             - Non-parseable staging amounts (text that isn't a valid number)

             Returns individual rows where the staging and mart amounts differ by
             more than $0.01, indicating a data transformation issue.

Expected Result: 0 rows (test passes)
Failure Condition: Any matched row where the staging numeric amount differs
                   from the mart amount by more than $0.01.
*/

WITH matched AS (
    SELECT
        li.line_item_id,
        li.amount AS staging_amount_text,
        mart.amount AS mart_amount,
        mart.ref_no,
        mart.item,
        mart.vendor,
        mart.date
    FROM {{ ref('stg__extracted_line_items') }} li
    INNER JOIN {{ ref('mart__invoice_items') }} mart
        ON li.line_item_id = mart.invoice_items_id
    WHERE
        /*
          Defined in: int__extracted_data_combined and int__invoice_items_with_normalized_fields.
          Credit memos (ref_no starting with 'CR-') have their amount sign flipped to negative
          in the pipeline. The staging text has the original positive value, so these will
          always differ. Exclude from comparison.
        */
        mart.ref_no NOT LIKE 'CR-%'

        /*
          Defined in: int__invoice_items_with_normalized_fields (effective_values CTE).
          User overrides are stored in public.user_overrides as JSONB. When a user changes
          an amount via the app, the mart reflects the override but staging still has the
          original extraction value. Exclude these since the difference is intentional.
        */
        AND NOT EXISTS (
            SELECT 1 FROM {{ ref('int__user_overrides') }} uo
            WHERE uo.record_id = li.line_item_id::text
              AND uo.amount IS NOT NULL
        )

        /*
          Staging amounts are raw text from PDF extraction. Some aren't valid numbers
          (empty, malformed, or contain non-numeric characters). These can't be
          meaningfully compared, so we only check rows with parseable amounts.
        */
        AND li.amount ~ '^-?[0-9]+(\.[0-9]+)?$'
)

SELECT
    line_item_id,
    staging_amount_text,
    staging_amount_text::numeric AS staging_amount,
    mart_amount,
    ABS(staging_amount_text::numeric - COALESCE(mart_amount, 0)) AS abs_diff,
    ref_no,
    item,
    vendor,
    date
FROM matched
WHERE ABS(staging_amount_text::numeric - COALESCE(mart_amount, 0)) > 0.01
