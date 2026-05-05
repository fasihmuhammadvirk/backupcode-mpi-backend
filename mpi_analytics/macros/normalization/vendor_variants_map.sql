/*
Vendor Variants Map

Maps known vendor abbreviations/variations to canonical supplier names.
Used for two-tier fuzzy matching in int__vendors.sql.

Usage:
  - Add new variants under the appropriate canonical supplier name
  - Variants are fuzzy matched (0.6 threshold) before direct supplier matching
  - Canonical names MUST match entries in public.suppliers exactly

Example: "YS Plumbing LLC" → fuzzy matches "YS Plumbing" → maps to "Y & S Plumbing Supply"
*/

{% macro vendor_variants_map() %}
    {{
        return({
            "Y & S Plumbing Supply": [
                "YS",
                "YS Plumbing",
                "YSPLUMBING",
                "Y and S Plumbing",
                "YS PLUMBING LLC",
                "YSPLUMBING LLC",
                "YS PLUMBING & HEATING",
                "YS PLUMBING & HEATING SUPPLY",
                "YS PLUMBING HEATING SUPPLY",
                "YSPLUMBING HVAC",
                "YSPLUMBING HVAC LLC",
                "YSPLUMBING.COM",
            ],
            "Certified Lumber & Home Center": [
                "Certified Lumber",
                "CERTIFIED LUMBER",
            ],
        })
    }}
{% endmacro %}
