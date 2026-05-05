/*
Invoice Items with Rerated Pricing

Adds Y & S (BOX vs EACH UOM mismatch) price rerating on top of the normalized
intermediate. Downstream marts that need rerated cost/qty (Data Review, Price
Changes, QuickBooks, Mapping, Purchase Order, Supplier Comparison) should source
from this model instead of `int__invoice_items_with_normalized_fields`.

What this model adds vs upstream:
  - previous_cost, previous_qty, previous_date  (LAG by item+vendor, date ASC)
  - is_price_rerated                            (TRUE when threshold tripped for Y&S)
  - rerated_cost, rerated_qty                   (corrected EACH-equivalent values)
  - original_current_price, original_current_qty (= cost / qty, kept for clarity)

The detection and correction rules are kept in lock-step with the equivalent
CTEs in `mart__price_increases.sql`. Voided rows and rows with non-positive
cost are excluded from the LAG window (matching `mart__price_increases`) so
they neither receive a `previous_cost` nor anchor one for later rows.

Detection rule:
  vendor = 'Y & S Plumbing Supply'
  AND previous_cost IS NOT NULL AND previous_cost > 0
  AND ((cost - previous_cost) / previous_cost * 100) > price_increase_threshold

Correction rule (preserves total spend cost*qty):
  ratio          = ROUND(cost / previous_cost)
  rerated_cost   = ROUND((cost / NULLIF(ratio, 0))::numeric, 2)
  rerated_qty    = qty  * NULLIF(ratio, 0)

The raw `cost` and `qty` columns are preserved unchanged so consumers can choose
which value to expose. Columns are additive.

Materialization:
  Full-refresh table. The LAG window requires the complete history per
  (item, vendor) pair, so we rebuild from scratch each run (mirrors the strategy
  used by `mart__price_increases`). Cost is amortized across all downstream marts.

Lineage:
  int__invoice_items_mapped
    → int__invoice_items_with_normalized_fields
      → THIS MODEL
        → mart__invoice_items, mart__invoice_items_map,
          mart__item_price_comparison, mart__mapping_audit,
          mart__address_sheet_aggregates
*/

{% set price_increase_threshold = var('price_increase_threshold') %}

{{ config(
    materialized='table',
    schema='intermediate',
    tags=['intermediate', 'pricing', 'rerating'],
    indexes=[
        {'columns': ['invoice_items_id'], 'unique': True},
        {'columns': ['item', 'vendor']},
        {'columns': ['is_active']},
        {'columns': ['_dbt_updated_at']},
        {'columns': ['is_overridden']},
        {'columns': ['invoice_voided_at']},
        {'columns': ['is_price_rerated']}
    ],
    post_hook=[
        "ANALYZE {{ this }}"
    ]
) }}

WITH normalized AS (
    SELECT * FROM {{ ref('int__invoice_items_with_normalized_fields') }}
),

-- Look up the previous valid purchase per (item, vendor). Voided rows and rows
-- with non-positive cost are excluded so they don't pollute the comparison
-- window. This mirrors `item_price_data → price_comparison` in
-- `mart__price_increases.sql`. The ORDER BY is intentionally only on `date`
-- (no `invoice_items_id` tiebreaker) so this model produces the *same*
-- previous_cost / previous_qty / rerating decisions as `mart__price_increases`
-- for rows on the same date. Adding a deterministic tiebreaker here would
-- silently diverge the two implementations on tied dates (~47k rows in prod),
-- which defeats the goal of issue #899.
valid_purchase_history AS (
    SELECT
        invoice_items_id,
        LAG(cost) OVER (
            PARTITION BY item, vendor
            ORDER BY "date" ASC
        ) AS previous_cost,
        LAG(qty) OVER (
            PARTITION BY item, vendor
            ORDER BY "date" ASC
        ) AS previous_qty,
        LAG("date") OVER (
            PARTITION BY item, vendor
            ORDER BY "date" ASC
        ) AS previous_date
    FROM normalized
    WHERE cost IS NOT NULL
      AND cost > 0
      AND invoice_voided_at IS NULL
),

-- Stitch previous-purchase context back onto every row (including voided /
-- zero-cost ones, which receive NULL previous_*) and flag rerating candidates.
flagged AS (
    SELECT
        n.*,
        vp.previous_cost,
        vp.previous_qty,
        vp.previous_date,
        CASE
            WHEN n.vendor = 'Y & S Plumbing Supply'
                AND vp.previous_cost IS NOT NULL
                AND vp.previous_cost > 0
                AND n.cost IS NOT NULL
                AND n.cost > 0
                AND ((n.cost - vp.previous_cost) / vp.previous_cost * 100) > {{ price_increase_threshold }}
            THEN TRUE
            ELSE FALSE
        END AS is_price_rerated
    FROM normalized n
    LEFT JOIN valid_purchase_history vp
        ON n.invoice_items_id = vp.invoice_items_id
),

-- Apply the rerating correction. NULLIF guards against a ratio that rounds to
-- 0 (would only happen if cost ≤ 0.5 × previous_cost, i.e. not actually a
-- rerating candidate, but kept defensively).
rerated AS (
    SELECT
        f.*,

        -- Aliases that match mart__price_increases' renamed columns (PR #906).
        -- Always equal to raw cost/qty; provided so the FE doesn't have to know
        -- which intermediate it sourced the row from.
        f.cost AS original_current_price,
        f.qty  AS original_current_qty,

        ROUND(
            (CASE
                WHEN f.is_price_rerated THEN
                    f.cost / NULLIF(ROUND(f.cost / f.previous_cost), 0)
                ELSE f.cost
            END)::numeric,
            2
        ) AS rerated_cost,

        CASE
            WHEN f.is_price_rerated THEN
                f.qty * NULLIF(ROUND(f.cost / f.previous_cost), 0)
            ELSE f.qty
        END AS rerated_qty

    FROM flagged f
)

SELECT * FROM rerated
