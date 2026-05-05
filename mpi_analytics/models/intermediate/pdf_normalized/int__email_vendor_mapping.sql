{{ config(
    materialized='view',
    schema='intermediate'
) }}

WITH matched_patterns AS (
    SELECT
        eq.id AS email_queue_id,
        eq.subject,
        s.supplier_name,
        s.is_subject_resolved,
        ROW_NUMBER() OVER (
            PARTITION BY eq.id
            ORDER BY LENGTH(sep.sender_pattern) DESC, sep.sender_pattern
        ) AS rn
    FROM {{ ref('stg__email_download_queue') }} eq
    LEFT JOIN {{ source('public', 'supplier_email_patterns') }} sep
        ON LOWER(eq.sender) LIKE '%' || LOWER(sep.sender_pattern)
        AND sep.is_active = true
    LEFT JOIN {{ source('public', 'suppliers') }} s
        ON s.id = sep.supplier_id
)

SELECT
    mp.email_queue_id,
    CASE
        WHEN mp.supplier_name IS NOT NULL AND NOT mp.is_subject_resolved
            THEN mp.supplier_name
        WHEN mp.is_subject_resolved
            THEN CASE
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%WWPS%' THEN 'World Wide Plumbing'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%BMW%' THEN 'BMW Plumbing Supplies'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%FLOWMARK%' THEN 'Flow Mark Plumbing Supply'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%SUPREME%' THEN 'Supreme Plumbing Supply'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%YS%' OR UPPER(TRIM(mp.subject)) ILIKE '%Y&S%' THEN 'Y & S Plumbing Supply'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%PYRAMID%' THEN 'Pyramid Plumbing'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%PARK%' THEN 'Park Plumbing Supply'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%AF SUPPLY%' THEN 'AF Supply'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%BRUCE%' THEN 'Bruce Supply Corp.'
                WHEN UPPER(TRIM(mp.subject)) ILIKE '%PLUMBING EXCHANGE%' THEN 'Plumbing Exchange'
                ELSE NULL
            END
        ELSE NULL
    END AS email_derived_vendor
FROM matched_patterns mp
WHERE mp.rn = 1
