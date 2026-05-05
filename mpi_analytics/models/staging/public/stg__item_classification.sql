WITH source AS (
    SELECT * FROM {{ source('public', 'item_classification') }}
),

renamed AS (
    SELECT 
        id,
        item AS sheet_name,
        category
    FROM source
)

SELECT * FROM renamed
