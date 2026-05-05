-- int__item_classifications.sql
--
-- Intermediate model to handle normalization of item classifications.
-- This ensures that sheet names are consistently formatted for joins in downstream marts.

{{ config(
    materialized='table',
    schema='intermediate',
    tags=['inventory', 'classification', 'intermediate']
) }}

WITH source AS (
    SELECT * FROM {{ ref('stg__item_classification') }}
),

normalized AS (
    SELECT
        id,
        -- Apply standard normalization (removes parentheses, periods, etc.)
        {{ normalize_sheet_name('sheet_name') }} AS sheet_name,
        category
    FROM source
),

deduplicated AS (
    -- Ensure exactly one row per sheet_name to prevent join fan-out in marts.
    SELECT DISTINCT ON (sheet_name)
        id,
        sheet_name,
        category
    FROM normalized
    ORDER BY sheet_name, id
)

SELECT * FROM deduplicated
