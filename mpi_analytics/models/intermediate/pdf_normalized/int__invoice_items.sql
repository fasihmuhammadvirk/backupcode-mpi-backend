/*
Invoice Items - Cleanup and Preparation

Cleans raw invoice data and prepares it for mapping joins.
Handles: safe numeric casting, item suffix normalization, basic data cleanup.

Data lineage:
  stg__invoice_items → THIS MODEL → int__invoice_items_mapped → int__invoice_items_with_normalized_fields → marts

Note: Normalization fields (fuzzy search, buyer/address normalization, account assignment)
have been moved to int__invoice_items_with_normalized_fields for cleaner separation of concerns.
*/

{{ config(
    materialized='view',
    schema='intermediate'
) }}

WITH invoice_items_staged AS (
    SELECT *
    FROM {{ ref('stg__invoice_items') }}
    -- Only keep active invoices
    WHERE (is_active = true OR is_active IS NULL)
),

transformed AS (
    SELECT
        invoice_items_id,
        filename,
        item,
        description,
        vendor,
        date,
        ref_no,
        po_number,
        customer_job,
        buyer,
        date_added,
        invoice_id,
        is_active,
        mpi_item,
        mpi_description,
        sheet_name,
        class_,
        account,
        export_status,
        bill,
        memo,

        -- Safe numeric casting
        {{ safe_cast('amount', 'NUMERIC(18, 2)') }} AS amount_numeric,
        {{ safe_cast('cost', 'NUMERIC(18, 2)') }} AS cost_numeric,
        {{ safe_cast('qty', 'NUMERIC(18, 2)') }} AS qty_numeric,

        -- Keep raw values for audit
        amount AS amount_raw,
        cost AS cost_raw,
        qty AS qty_raw,

        -- Item with vendor suffix for mapping joins
        -- "10 Materials" and "11 Equipment" items need vendor suffixes for proper mapping
        CASE
            WHEN item IN ('10 Materials', '11 Equipment') THEN
                item || CASE
                    WHEN UPPER(vendor) LIKE '%WORLD WIDE%' OR UPPER(vendor) LIKE '%WWPS%' THEN '-W'
                    WHEN UPPER(vendor) LIKE '%BMW%' THEN '-B'
                    WHEN UPPER(vendor) LIKE '%Y & S%' OR UPPER(vendor) LIKE '%Y&S%' THEN '-Y'
                    WHEN UPPER(vendor) LIKE '%FLOW%' THEN '-F'
                    WHEN UPPER(vendor) LIKE '%SUPREME%' THEN '-S'
                    WHEN UPPER(vendor) LIKE '%PARK%' OR UPPER(vendor) LIKE '%PYRAMID%' THEN '-P'
                    WHEN UPPER(vendor) LIKE '%GOTHAM%' THEN '-G'
                    ELSE ''
                END
            -- TODO: Adding this temporary fix to these two org items because it is faster than tracking down
            -- the code from the extraction. We're also moving away from the existing extractors towards new
            -- models which will provide the raw data
            WHEN item IN ('715S62464-B', '715S41664-B') THEN
                item || '-B'
            ELSE item
        END AS item_with_suffix

    FROM invoice_items_staged
)

SELECT
    invoice_items_id,
    filename,
    item_with_suffix AS item,  -- Use suffixed version for mapping joins
    description,
    vendor,
    date,
    ref_no,
    po_number,
    customer_job,
    buyer,
    date_added,
    invoice_id,
    is_active,
    mpi_item,
    mpi_description,
    sheet_name,
    class_,
    account,
    export_status,
    bill,
    memo,

    -- Clean numeric columns
    amount_numeric AS amount,
    cost_numeric AS cost,
    qty_numeric AS qty,

    -- Raw values for audit
    amount_raw,
    cost_raw,
    qty_raw

FROM transformed
