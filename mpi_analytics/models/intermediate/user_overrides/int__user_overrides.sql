/*
Intermediate User Overrides

Unpacks the JSONB `overrides` column from staging into individual typed columns.
Text fields are extracted as TEXT (NULL when the key is absent from the JSONB).
Numeric and date fields are validated and cast to their target types, falling
back to NULL on invalid input.

Downstream consumers can use simple column references (e.g., ov.mpi_item)
and NULL checks (e.g., ov.amount IS NOT NULL) instead of JSONB operators.

Data lineage:
  stg__user_overrides --> THIS MODEL --> int__invoice_items_with_normalized_fields
*/

{{ config(
    materialized='view',
    schema='intermediate'
) }}

{% set text_columns = [
    'sheet_name',
    'mpi_item',
    'mpi_description',
    'account',
    'class_',
    'memo',
    'description',
    'customer_job',
    'vendor',
    'po_number',
    'buyer'
] %}

WITH source AS (
    SELECT * FROM {{ ref('stg__user_overrides') }}
)

SELECT
    record_id,

    -- Text fields: extract from JSONB as text (NULL when key absent)
    {% for col in text_columns %}
    overrides->>'{{ col }}' AS {{ col }},
    {% endfor %}

    -- Numeric fields: regex-guarded cast to numeric, NULL on invalid input
    CASE
        WHEN overrides ? 'amount'
             AND (overrides->>'amount') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN (overrides->>'amount')::numeric
        ELSE NULL
    END AS amount,

    CASE
        WHEN overrides ? 'cost'
             AND (overrides->>'cost') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN (overrides->>'cost')::numeric
        ELSE NULL
    END AS cost,

    CASE
        WHEN overrides ? 'qty'
             AND (overrides->>'qty') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN (overrides->>'qty')::numeric
        ELSE NULL
    END AS qty,

    -- Date field: format-validated cast to DATE, NULL on invalid input
    CASE
        WHEN overrides ? 'date'
             AND (overrides->>'date') ~ '^\d{2}-\d{2}-\d{4}$'
             AND TO_CHAR(TO_DATE(overrides->>'date', 'MM-DD-YYYY'), 'MM-DD-YYYY') = (overrides->>'date')
            THEN TO_DATE(overrides->>'date', 'MM-DD-YYYY')
        ELSE NULL
    END AS date,

    -- Metadata
    overridden_by,
    overridden_at

FROM source
