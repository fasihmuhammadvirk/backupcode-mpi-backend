WITH source AS (
    SELECT * FROM {{ source('public', 'quickbooks_items') }}
)

SELECT
    invoice_items_id,
    invoice_id,
    exported_at
FROM source
