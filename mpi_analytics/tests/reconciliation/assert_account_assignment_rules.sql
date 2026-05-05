{{ config(tags=['reconciliation']) }}

/*
Test: Account Assignment Rules
Description: Validates the assigned_account column in mart__invoice_items against
             the documented business rules. Recomputes expected assigned_account from
             the mart's own columns (mpi_item, sheet_name, account) which already
             reflect override-merged effective values.

Expected Result: 0 rows (test passes)
Failure Condition: Rows where the mart's assigned_account disagrees with the
                   expected value computed from the business rules below.

Defined in: int__invoice_items_with_normalized_fields (assigned_account CASE statement).
We recompute the same logic here against the mart's columns (which already have user
overrides applied) so we can verify the mart stored the correct result. If someone
changes the CASE logic in the intermediate SQL, this test will catch the drift.

Account assignment rules (priority order):
  1. Preserve explicit 'A'
  2. mpi_item = 'UIDI - Job Materials Purchased' -> 'M'
  3. mpi_item = 'UIDI - Job Equipment' -> 'E'
  4. sheet_name LIKE '%job materials%' -> 'M'
  5. sheet_name LIKE '%job equipment%' -> 'E'
  6. Fallback to existing account if non-empty
  7. Else NULL

We compare against mpi_item and sheet_name from the mart (not staging) because the
mart columns reflect the full pipeline: mapping resolution, user overrides, and
normalization. The account assignment rules operate on these effective values.
*/

WITH mart_with_expected AS (
    SELECT
        invoice_items_id,
        mpi_item,
        sheet_name,
        account,
        assigned_account AS actual_assigned,
        CASE
            WHEN UPPER(account) = 'A' THEN 'A'
            WHEN mpi_item = 'UIDI - Job Materials Purchased' THEN 'M'
            WHEN mpi_item = 'UIDI - Job Equipment' THEN 'E'
            WHEN LOWER(sheet_name) LIKE '%job materials%' THEN 'M'
            WHEN LOWER(sheet_name) LIKE '%job equipment%' THEN 'E'
            WHEN account IS NOT NULL AND account != '' THEN account
            ELSE NULL
        END AS expected_assigned
    FROM {{ ref('mart__invoice_items') }}
)

SELECT
    invoice_items_id,
    mpi_item,
    sheet_name,
    account,
    actual_assigned,
    expected_assigned
FROM mart_with_expected
WHERE COALESCE(actual_assigned, '__NULL__') != COALESCE(expected_assigned, '__NULL__')
