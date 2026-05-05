/*
Mart Invoice Items used to compare the item price for different filters
Used for purchase order analysis
*/

{{
    config(
        materialized='table',
        tags=['mart', 'purchase_order', 'pricing'],
        indexes=[
            {'columns': ['invoice_items_id'], 'unique': True},
            {'columns': ['item_code']},
            {'columns': ['item_mpi_code']},
            {'columns': ['supplier_name']},
            {'columns': ['supplier_id']},
            {'columns': ['purchase_date']},
            {'columns': ['item_mpi_code', 'supplier_name']},
            {'columns': ['item_code', 'supplier_name']}
        ],
        post_hook=[
            "ANALYZE {{ this }}"
        ]
    )
}}

-- Source: rerated intermediate so Purchase Order and Supplier Comparison rank
-- items by their UOM-corrected per-unit rerated_cost (issue #899). Without rerating,
-- a Y & S BOX-priced row would appear as a much higher rerated_cost than its true
-- EACH-equivalent price and skew the "cheapest" ranking.
WITH prioritized_line_items AS (
    SELECT
        invoice_items_id,
        filename,
        item AS item_code,
        description AS item_description,
        rerated_cost AS item_cost,
        rerated_qty  AS item_quantity,
        is_price_rerated,
        original_current_price,
        original_current_qty,
        date AS purchase_date,
        matched_supplier AS supplier_name,
        matched_supplier_id AS supplier_id,
        resolved_mpi_item AS item_mpi_code,
        resolved_mpi_description AS item_mpi_description,
        ref_no,
        ROW_NUMBER() OVER (
            PARTITION BY item, matched_supplier
            ORDER BY rerated_cost ASC, date DESC
        ) AS rank_by_item_code,
        ROW_NUMBER() OVER (
            PARTITION BY resolved_mpi_item, matched_supplier
            ORDER BY rerated_cost ASC, date DESC
        ) AS rank_by_item_mpi_code,
        ROW_NUMBER() OVER (
            PARTITION BY item, resolved_mpi_item, matched_supplier
            ORDER BY rerated_cost ASC, date DESC
        ) AS cheapest_rank_by_item_and_mpi_code,
        ROW_NUMBER() OVER (
            PARTITION BY item, matched_supplier
            ORDER BY date DESC, rerated_cost ASC
        ) AS latest_rank_by_item_code,
        ROW_NUMBER() OVER (
            PARTITION BY resolved_mpi_item, matched_supplier
            ORDER BY date DESC, rerated_cost ASC
        ) AS latest_rank_by_mpi_item_code,
        ROW_NUMBER() OVER (
            PARTITION BY item, resolved_mpi_item, matched_supplier
            ORDER BY date DESC, rerated_cost ASC
        ) AS latest_rank_by_item_and_mpi_code
    FROM {{ ref('int__invoice_items_with_rerated_pricing') }}
    WHERE item IS NOT NULL AND TRIM(item) <> ''
        AND cost IS NOT NULL
        AND matched_supplier_id IS NOT NULL
        AND invoice_voided_at IS NULL
)

SELECT
    *
FROM prioritized_line_items