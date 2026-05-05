# ADR-0004: Mart Tables as the analytic API's Source of Truth

## Status

ACCEPTED (In Progress -- Migration) | Partially superseded by ADR-0011 for user override data

## Date

2025-12-01

## Context

The API historically read from the `public.invoice_items` table directly. This table:

- Contains raw, un-normalized data requiring Python-side cleaning on every request
- Lacks pre-computed columns for efficient filtering and searching
- Has grown to rows without query-optimized indexes
- Forces every API endpoint to independently apply the same normalization logic
- Makes it almost impossible to change the data model without breaking all consumers

Meanwhile, dbt (ADR-0001) now produces `analytics.mart__invoice_items` -- a denormalized, pre-normalized, indexed table optimized for the exact queries the API needs.

## Decision

**Mart tables are the analytics API's source of truth.** All new DAO functions (ADR-0003) read from `mart__*` tables in the `analytics` schema, not from `public.invoice_items`.

### Table Deprecation Path

| Table | Status | Replacement |
|-------|--------|-------------|
| `public.invoice_items` | DEPRECATED | `analytics.mart__invoice_items` |
| `public.model_extracted_data` | DEPRECATED | `raw.model_extracted_data` + dbt staging |
| `public.invoice_items` (writes) | Still active | Writes go to `public`, dbt transforms to `analytics` |

### Mart Table Properties

- **Read-only from API perspective**: Only dbt writes to mart tables
- **Pre-computed normalized columns**: `item_normalized`, `description_normalized`
- **Indexed for API queries**: Composite indexes on filter columns
- **Denormalized**: Joins pre-computed (supplier name, mapping status, etc.)
- **Incremental**: dbt updates only changed/new rows

### Write Path vs Read Path

- **Write path:** Extraction writes to `raw.model_extracted_data`, dbt transforms it into `analytics.mart__invoice_items`
- **Read path:** API requests go through the DAO, which reads from `analytics.mart__invoice_items`
- The write path and read path are intentionally separated
- The API never writes to mart tables
- The API never reads from raw tables (except for admin/debug endpoints)

## Consequences

### Positive
- API queries are 10-100x faster (pre-normalized, pre-indexed)
- No Python-side normalization needed at query time
- Data consistency guaranteed by dbt (single transformation pipeline)
- Schema changes to raw tables don't break the API (dbt absorbs the change)
- DAO functions are simpler (no normalization logic needed)

### Negative
- Data freshness lag: mart data is as fresh as the last dbt run (up to 30 min)
- Write operations still target `public` schema (dual-write concern during transition)
- Must maintain backward compatibility during migration (feature flags, ADR-0005)

### Risk Mitigation
- dbt run frequency can be increased for near-real-time freshness

## Compliance
- New DAO functions MUST read from `analytics.mart__*` tables
- Reading from `public.invoice_items` is legacy and should not appear in new code.

## Notes
