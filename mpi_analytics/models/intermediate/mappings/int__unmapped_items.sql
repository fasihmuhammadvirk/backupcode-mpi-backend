/*
Intermediate Unmapped Items
Items with no mapping for audit purposes
*/

{{ config(
    materialized='table',
    schema='intermediate',
    indexes=[
        {'columns': ['item', 'vendor']}
    ],
    post_hook=[
        "ANALYZE {{ this }}"
    ]
) }}

WITH mapped_items AS (
    SELECT * FROM {{ ref('int__invoice_items_mapped') }}
),

invoice_voided AS (
    SELECT * FROM {{ source('public', 'invoice_voided') }}
),

unmapped_only AS (
    SELECT
        m.invoice_items_id,
        m.item,
        m.description,
        m.vendor,
        m.buyer,
        m.date,
        m.date_added,
        m.qty,
        m.cost,
        m.amount,
        m.filename,
        m.ref_no,
        m.po_number,
        m.customer_job,
        m.invoice_id,
        m.original_mpi_item,
        m.original_mpi_description,
        m.original_sheet_name,
        m.mapping_type,
        m.mapped_at
    FROM mapped_items m
    LEFT JOIN invoice_voided iv
        ON m.ref_no = iv.ref_no
       AND m.date   = iv.date
       AND m.vendor = iv.vendor
    WHERE m.mapping_type IN ('no_match', 'possible_match')
      AND iv.ref_no IS NULL
)

SELECT * FROM unmapped_only
