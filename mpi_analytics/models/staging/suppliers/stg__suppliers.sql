/*
Staged Suppliers

Source of truth for vendor/supplier names used in fuzzy matching.
Data from public.suppliers table containing 13 known suppliers.

Data lineage:
  public.suppliers → THIS MODEL → int__vendors (fuzzy matching)
*/

{{ config(
    materialized='view',
    schema='staging'
) }}

SELECT
    id AS supplier_id,
    supplier_name,
    suffix
FROM {{ source('public', 'suppliers') }}
