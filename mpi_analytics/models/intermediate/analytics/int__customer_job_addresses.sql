/*
Customer Job Address Extraction

This model uses Python-parsed address data from the usaddress library,
with SQL regex fallback for addresses not yet parsed by Python.

Data lineage:
  stg__parsed_customer_job_addresses (Python) → THIS MODEL
  stg__invoice_items (fallback)             ↗
                                           ↘ int__invoice_items_with_normalized_fields (can join)

To refresh Python-parsed addresses:
  python scripts/parse_customer_job_addresses.py
*/

{{ config(
    materialized='view',
    schema='intermediate'
) }}

-- Source 1: Python-parsed addresses (preferred)
WITH python_parsed AS (
    SELECT
        customer_job,
        prefix_removed AS prefix_text,
        extracted_address,
        address_number AS street_number,
        -- Build street name with suffix
        TRIM(CONCAT_WS(' ',
            street_name_pre_directional,
            street_name,
            street_name_post_type,
            street_name_post_directional
        )) AS street_name_with_suffix,
        place_name AS city,
        state_name AS state,
        zip_code,
        NULL::text AS cross_street_info,  -- usaddress doesn't extract this
        confidence AS extraction_confidence,
        needs_manual_review
    FROM {{ ref('stg__parsed_customer_job_addresses') }}
),

-- Source 2: All distinct customer_jobs from invoice items
all_customer_jobs AS (
    SELECT DISTINCT customer_job
    FROM {{ ref('int__model_extracted_data') }}
    WHERE customer_job IS NOT NULL
      AND TRIM(customer_job) != ''
),

-- Source 3: SQL regex fallback for unparsed addresses
-- (This will be empty once all addresses are Python-parsed)
sql_fallback AS (
    SELECT
        a.customer_job,

        -- Find position where street number starts
        (REGEXP_MATCH(
            a.customer_job,
            '(\d+(-\d+)?)\s+[A-Za-z]'
        ))[1] AS street_number_match,

        POSITION(
            (REGEXP_MATCH(a.customer_job, '(\d+(-\d+)?)\s+[A-Za-z]'))[1]
            IN a.customer_job
        ) AS address_start_pos

    FROM all_customer_jobs a
    LEFT JOIN python_parsed p ON a.customer_job = p.customer_job
    WHERE p.customer_job IS NULL  -- Only process unparsed addresses
),

-- Build fallback extracted addresses
sql_extracted AS (
    SELECT
        customer_job,

        -- Prefix text (everything before street number)
        CASE
            WHEN address_start_pos > 1
            THEN TRIM(SUBSTRING(customer_job, 1, address_start_pos - 1))
            ELSE NULL
        END AS prefix_text,

        -- Extracted address (from street number onwards)
        CASE
            WHEN street_number_match IS NOT NULL
            THEN TRIM(SUBSTRING(customer_job, address_start_pos))
            ELSE customer_job
        END AS extracted_address_raw,

        street_number_match AS street_number

    FROM sql_fallback
    WHERE street_number_match IS NOT NULL OR customer_job IS NOT NULL
),

-- Deduplicate SQL fallback addresses
sql_deduplicated AS (
    SELECT
        customer_job,
        prefix_text,
        street_number,
        -- Check for duplicate street number
        CASE
            WHEN street_number IS NOT NULL
                 AND POSITION(street_number IN SUBSTRING(extracted_address_raw, 2)) > 0
            THEN TRIM(SUBSTRING(
                extracted_address_raw,
                POSITION(street_number IN SUBSTRING(extracted_address_raw, 2)) + 1
            ))
            ELSE extracted_address_raw
        END AS extracted_address
    FROM sql_extracted
),

-- Parse SQL fallback addresses (basic regex)
sql_parsed AS (
    SELECT
        customer_job,
        prefix_text,
        extracted_address,
        (REGEXP_MATCH(extracted_address, '^(\d+(-\d+)?)'))[1] AS street_number,

        -- Street name (simplified regex)
        TRIM(
            (REGEXP_MATCH(
                extracted_address,
                '^\d+(-\d+)?\s+(.+?)\s+(?:Brooklyn|Jamaica|Bronx|Queens|Manhattan|Flushing|Astoria)',
                'i'
            ))[2]
        ) AS street_name_with_suffix,

        -- City
        COALESCE(
            (REGEXP_MATCH(
                extracted_address,
                '\s(Jamaica|Brooklyn|Bronx|Queens|Manhattan|Staten Island|Flushing|Astoria|Forest Hills)',
                'i'
            ))[1],
            (REGEXP_MATCH(extracted_address, '([A-Za-z]+)\s*,?\s*(?:Ny|NY)', 'i'))[1]
        ) AS city,

        -- State
        CASE
            WHEN extracted_address ~* '\s(?:Ny|NY|N\.?Y\.?)' THEN 'NY'
            WHEN extracted_address ~* '\s(?:Nj|NJ|N\.?J\.?)' THEN 'NJ'
            WHEN extracted_address ~* '\s(?:Ct|CT)' THEN 'CT'
            ELSE NULL
        END AS state,

        -- ZIP
        (REGEXP_MATCH(extracted_address, '(\d{5}(?:-\d{4})?)(?:\s|$)', 'i'))[1] AS zip_code,

        NULL::text AS cross_street_info,

        -- Confidence
        CASE
            WHEN (REGEXP_MATCH(extracted_address, '^(\d+(-\d+)?)'))[1] IS NOT NULL
                 AND extracted_address ~* '\s(?:Ny|NY)'
            THEN 'medium'  -- SQL fallback is less reliable
            WHEN (REGEXP_MATCH(extracted_address, '^(\d+(-\d+)?)'))[1] IS NOT NULL
            THEN 'low'
            ELSE 'low'
        END AS extraction_confidence,

        TRUE AS needs_manual_review  -- SQL fallback always needs review

    FROM sql_deduplicated
),

-- Combine Python-parsed and SQL fallback
combined AS (
    -- Python-parsed addresses (preferred)
    SELECT
        customer_job,
        prefix_text,
        extracted_address,
        street_number,
        street_name_with_suffix,
        city,
        state,
        zip_code,
        cross_street_info,
        extraction_confidence,
        needs_manual_review,
        'python' AS parse_source
    FROM python_parsed

    UNION ALL

    -- SQL fallback for unparsed addresses
    SELECT
        customer_job,
        prefix_text,
        extracted_address,
        street_number,
        street_name_with_suffix,
        city,
        state,
        zip_code,
        cross_street_info,
        extraction_confidence,
        needs_manual_review,
        'sql_fallback' AS parse_source
    FROM sql_parsed
)

SELECT
    customer_job,
    prefix_text,

    -- Apply normalize_address to ensure consistent formatting (title case, abbreviations, typo fixes)
    {{ normalize_address('extracted_address') }} AS extracted_address,

    street_number,
    {{ normalize_address('street_name_with_suffix') }} AS street_name_with_suffix,
    INITCAP(city) AS city,
    UPPER(state) AS state,
    zip_code,
    cross_street_info,

    -- Reconstructed clean address (normalized) - only when we have a street number
    {{ normalize_address(
        "CASE WHEN street_number IS NOT NULL THEN
            NULLIF(TRIM(CONCAT_WS(' ',
                street_number,
                street_name_with_suffix,
                city,
                state,
                zip_code
            )), '')
        ELSE NULL END"
    ) }} AS clean_address,

    extraction_confidence,
    needs_manual_review,
    parse_source

FROM combined
