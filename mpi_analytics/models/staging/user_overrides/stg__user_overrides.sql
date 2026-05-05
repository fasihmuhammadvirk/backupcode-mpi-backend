/*
Staged User Overrides

Cleans the raw user_overrides source: filters soft-deleted rows and selects
columns needed downstream. The JSONB `overrides` column is passed through
raw; unpacking happens in int__user_overrides.
*/

{{ config(
    materialized='view',
    schema='staging'
) }}

SELECT
    record_id,
    overrides,
    overridden_by,
    overridden_at
FROM {{ source('public', 'user_overrides') }}
WHERE deleted_at IS NULL
