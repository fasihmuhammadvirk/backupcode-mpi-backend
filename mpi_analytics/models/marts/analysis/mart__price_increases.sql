-- Mart model for price increase analysis per invoice item.
-- Calculates percentage price increase by comparing each purchase with the previous purchase chronologically.
-- Supplier-specific: Compares prices within the same supplier only.
-- See mart__price_increases.yml for detailed documentation.

{% set price_increase_threshold = var('price_increase_threshold') %}

{{
    config(
        materialized='table',
        tags=['analysis', 'pricing', 'reporting'],
        indexes=[
            {'columns': ['invoice_items_id'], 'unique': True},
            {'columns': ['item']},
            {'columns': ['vendor']},
            {'columns': ['item', 'vendor']},
            {'columns': ['purchase_date']}
        ],
        post_hook=[
            "ANALYZE {{ this }}"
        ]
    )
}}

{#
  Price Increase Analysis Model:

  Purpose:
  - Tracks price changes for items over time, supplier-specific
  - Each row represents an invoice item purchase with its price comparison
  - Enables quick identification of price increases/decreases

  Key Features:
  - Supplier-specific comparison (same item from different suppliers tracked separately)
  - Chronological comparison (each purchase compared to immediately preceding purchase)
  - Handles edge cases (first purchase, missing prices, zero prices)
  - Price Rerating: For specific vendors (e.g., Y & S Plumbing Supply), large price hikes ( > price_increase_threshold)
    are treated as UOM mismatches (BOX vs EACH) and rerated for accurate comparison.

  Indexes:
  1. invoice_items_id (unique) - Primary key linking to mart__invoice_items
  2. item - Item code filtering
  3. vendor - Supplier filtering
  4. (item, vendor) - Composite for supplier-specific item queries
  5. purchase_date - Temporal analysis

  Business Rules:
  - Only compares items with valid cost > 0 (zero-cost items excluded)
  - Comparison is per-supplier (same item from different suppliers tracked independently)
  - First purchase for item-vendor pair has NULL previous_price
  - Zero previous prices result in NULL percentage_increase to avoid division errors
  - Price Rerating: If percentage increase > price_increase_threshold for "Y & S Plumbing Supply",
    the current price is rerated: current_price = current_price / ROUND(current_price / previous_price)
  - Must maintain 1-to-1 parity with InvoiceItems.calculate_price_increase() controller method
#}

WITH item_price_data AS (
    -- Source: Get all active invoice items with valid pricing information
    -- WHY: We need clean, filtered data with only items that have valid costs
    SELECT
        invoice_items_id,
        item,
        vendor,
        "date",  -- Quoted because date is a reserved keyword in PostgreSQL
        cost AS COST,
        qty
    FROM {{ ref('int__invoice_items_with_normalized_fields') }}
    WHERE cost IS NOT NULL
        AND cost > 0
        AND invoice_voided_at IS NULL
),

price_comparison AS (
    -- Calculate price changes using window functions for efficient chronological comparison
    -- WHY: LAG function allows us to compare each purchase with the immediately preceding one
    --      within the same item-vendor partition
    SELECT
        ipd.invoice_items_id,
        ipd.item,
        ipd.vendor,
        ipd."date",
        ipd.cost AS current_price,
        ipd.qty AS current_qty,

        -- Get previous price and date for the same item from the same vendor
        LAG(ipd.cost) OVER (
            PARTITION BY ipd.item, ipd.vendor
            ORDER BY ipd."date" ASC
        ) AS previous_price,

        LAG(ipd."date") OVER (
            PARTITION BY ipd.item, ipd.vendor
            ORDER BY ipd."date" ASC
        ) AS previous_date,

        LAG(ipd.qty) OVER (
            PARTITION BY ipd.item, ipd.vendor
            ORDER BY ipd."date" ASC
        ) AS previous_qty
    FROM item_price_data ipd
),

price_rerating AS (
    -- Identify suspected UOM mismatches for specific vendors
    -- WHY: Some vendors switch between BOX and EACH pricing, causing massive percentage hikes (>250%).
    --      We flag these for rerating to ensure meaningful price comparisons.
    SELECT
        pc.*,
        CASE
            WHEN pc.vendor = 'Y & S Plumbing Supply'
                AND pc.previous_price IS NOT NULL
                AND pc.previous_price > 0
                AND ((pc.current_price - pc.previous_price) / pc.previous_price * 100) > {{ price_increase_threshold }}
            THEN TRUE
            ELSE FALSE
        END AS is_price_rerated
    FROM price_comparison pc
),

final_price_data AS (
    -- Apply price and qty rerating if the mismatch flag is set
    -- WHY: If rerated, we divide the current price by the rounded price ratio to get the 'EACH' price.
    --      Simultaneously, we multiply the quantity by the same ratio to keep the total amount consistent.
    --      We round the final price to 2 decimal places for consistency.
    SELECT
        pr.*,
        ROUND(
            (CASE
                WHEN pr.is_price_rerated THEN
                    pr.current_price / NULLIF(ROUND(pr.current_price / pr.previous_price), 0)
                ELSE pr.current_price
            END)::numeric,
            2
        ) AS final_current_price,
        CASE
            WHEN pr.is_price_rerated THEN
                pr.current_qty * NULLIF(ROUND(pr.current_price / pr.previous_price), 0)
            ELSE pr.current_qty
        END AS final_current_qty
    FROM price_rerating pr
),

price_increase_calc AS (
    -- Calculate percentage increase with proper handling of edge cases
    -- WHY: Need to handle NULL and zero previous prices to avoid division errors.
    --      Calculations are based on the final (possibly rerated) current price.
    SELECT
        fpd.invoice_items_id,
        fpd.item,
        fpd.vendor,
        fpd."date" AS purchase_date,
        fpd.final_current_price AS current_price,
        fpd.final_current_qty AS current_qty,
        fpd.previous_price,
        fpd.previous_date,
        fpd.previous_qty,
        fpd.is_price_rerated,
        fpd.current_price AS original_current_price, -- Original price before rerating
        fpd.current_qty AS original_current_qty, -- Original qty before rerating

        -- Calculate percentage increase
        CASE
            WHEN fpd.previous_price IS NULL THEN NULL  -- First purchase, no comparison
            WHEN fpd.previous_price = 0 THEN NULL      -- Avoid division by zero
            ELSE ROUND(
                ((fpd.final_current_price - fpd.previous_price) / fpd.previous_price * 100)::numeric,
                1
            )
        END AS percentage_increase,

        -- Calculate absolute price change
        CASE
            WHEN fpd.previous_price IS NULL THEN NULL
            ELSE ROUND((fpd.final_current_price - fpd.previous_price)::numeric, 2)
        END AS price_change,

        -- Flag for whether this item has price history
        CASE
            WHEN fpd.previous_price IS NOT NULL THEN TRUE
            ELSE FALSE
        END AS has_previous_price

    FROM final_price_data fpd
)

SELECT
    invoice_items_id,
    item,
    vendor,
    purchase_date,
    current_price,
    current_qty,
    previous_price,
    previous_date,
    previous_qty,
    percentage_increase,
    price_change,
    has_previous_price,
    is_price_rerated,
    original_current_price,
    original_current_qty,

    -- Add formatted percentage string for easy display (matching original method output)
    CASE
        WHEN percentage_increase IS NOT NULL THEN
            CAST(percentage_increase AS TEXT) || '%'
        ELSE 'N/A'
    END AS percentage_increase_formatted

FROM price_increase_calc
