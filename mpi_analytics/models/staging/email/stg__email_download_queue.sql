/*
Staged Email Download Queue

Source of truth for email download queue data used for email-based vendor resolution.
Data from raw.email_download_queue containing email metadata including sender information.

Data lineage:
  raw.email_download_queue → THIS MODEL → int__model_extracted_data (vendor resolution)
*/

{{ config(
    materialized='view',
    schema='staging'
) }}

SELECT
    id,
    sender,
    subject,
    status,
    email_date
FROM {{ source('raw', 'email_download_queue') }}
WHERE deleted_at IS NULL
