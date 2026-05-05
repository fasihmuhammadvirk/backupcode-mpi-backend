-- Staging model for Python-parsed customer job addresses
-- Source: parsed_customer_job_addresses table populated by scripts/parse_customer_job_addresses.py
--
-- This model reads address data that has been parsed using the usaddress Python library,
-- which provides more accurate address parsing than pure SQL regex patterns.

{{ config(
    materialized='view',
    schema='staging'
) }}

SELECT
    customer_job,

    -- Parsed address components
    address_number,
    street_name_pre_directional,
    street_name,
    street_name_post_type,
    street_name_post_directional,
    occupancy_type,
    occupancy_identifier,
    place_name,
    state_name,
    zip_code,

    -- Cleaned addresses
    extracted_address,
    clean_street_address,

    -- Metadata
    parse_type,
    confidence,
    needs_manual_review,
    prefix_removed,

    -- Timestamps
    created_at,
    updated_at

FROM {{ source('public', 'parsed_customer_job_addresses') }}
