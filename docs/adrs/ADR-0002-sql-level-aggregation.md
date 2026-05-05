# ADR-0002: SQL-Level Aggregation over Python-Level

## Status

ACCEPTED (In Progress)

## Date

2025-11-15

## Context

Several API endpoints performed aggregation in Python:
- `get_aggregates()` pulled full filtered datasets into Python, then computed sums/counts/averages in controller code
- Monthly comparison endpoints loaded raw data and grouped in pandas
- Supplier report generation iterated over query results in Python loops

This caused:
- Full dataset transfer from database to application (memory spikes)
- O(n) Python processing on data the database could aggregate in O(log n)
- Inconsistent aggregation logic between endpoints (rounding, null handling)
- Inability to handle large datasets (memory exhaustion on 500K+ rows)

## Decision

**Push all aggregation to SQL.** DAOs use CTEs (Common Table Expressions) and window functions to compute aggregates at the database level. Python receives only the final result.

### CTE Query Pattern (Standard for DAOs)

DAO queries follow a three-step CTE (Common Table Expression) structure:

1. **Filter** -- apply all WHERE conditions (date range, supplier, status, soft-delete flag, etc.) to the mart table
2. **Aggregate** -- compute counts, sums, and averages on the filtered set, grouped by the relevant dimension
3. **Paginate** -- apply row numbering and return only the requested page

Each step is a named CTE that feeds into the next, keeping the query readable and composable.

### Pre-Computed Normalized Columns

Mart tables (ADR-0004) include pre-computed `item_normalized` and `description_normalized` columns. These store the lowercased, trimmed, and regex-cleaned version of each value so that filtering is a simple equality check rather than a function call on every row.

### What Stays in Python

- Response formatting (converting SQL results to Pydantic/dataclass)
- Excel/CSV file generation (streaming, not in-memory)
- Business rule validation before queries
- Feature flag logic

## Consequences

### Positive
- Database handles aggregation efficiently (indexes, statistics, parallel query execution)
- API memory usage stays constant regardless of dataset size
- Consistent aggregation logic (SQL is the single source)
- CTEs are composable and readable
- Pre-computed columns eliminate repeated normalization

### Negative
- Complex SQL CTEs are harder to debug than Python loops
- PostgreSQL-specific syntax limits database portability (acceptable for this project)
- Developers must be comfortable with SQL window functions and CTEs

## Compliance
- New aggregation endpoints MUST compute aggregates in SQL (via DAO CTEs)
- Python-side aggregation of database results is not permitted in new code

## Notes
