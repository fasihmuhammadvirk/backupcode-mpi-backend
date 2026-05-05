# ADR-0001: dbt as the Data Transformation Layer

## Status

ACCEPTED (Implemented)

## Date

2025-11-01 (initial dbt project setup)

## Context

Data transformations such as deduplication, normalization, aggregation, cleaning were implemented in Python within controllers and route handlers. This caused:

- Transformation logic scattered across 37+ controller methods
- Python-side aggregation pulling full datasets into memory before filtering
- No versioning or lineage tracking for data transformations
- Duplicate string normalization logic (50+ occurrences)
- Inconsistent cleaning rules applied differently across endpoints
- No way to test transformations independently of the API

## Decision

Adopt **dbt (data build tool)** as the single transformation layer between raw extracted data and the API-facing tables.
Almost all data cleaning, normalization, deduplication, and aggregation happens in SQL via dbt models.

### dbt Layer Architecture

Data flows through three layers, each building on the previous:

1. **Staging (`stg__*`)** -- parses, type-casts, and normalizes raw extraction output
2. **Intermediate (`int__*`)** -- cleans, deduplicates, combines, and enriches staged data
3. **Marts (`mart__*`)** -- produces API-ready, denormalized, indexed tables

### Model Naming Convention
- Staging models: `stg__<model_name>`
- Intermediate models: `int__<model_name>`
- Dimension models: `dim__<model_name>`
- Fact models: `fct__<model_name>`
- Mart models: `mart__<model_name>`

### Key dbt Features Used

- **Incremental models**: Staging models use incremental merge, not full refresh
- **Post-hooks**: Staging models run post-hooks after each incremental merge
- **Pre-computed normalized columns**: `item_normalized`, `description_normalized` via `REGEXP_REPLACE`
- **Materialized views**: Expensive aggregation views materialized for performance

### What Stays in Python

- PDF extraction (AI model calls)
- S3 file operations
- Email download and attachment parsing
- API request/response handling
- Authentication and authorization

### What Moves to dbt

- String normalization and cleaning
- Deduplication logic
- Aggregation queries
- Date parsing and formatting
- Price history calculations
- Supplier report generation

## Consequences

### Positive
- Single source of truth for all data transformations
- Transformations are version-controlled, testable, and documented
- dbt lineage graph shows data flow from raw to mart
- Incremental runs are fast (process only new/changed data)
- SQL-native developers can contribute without Python knowledge
- Pre-computed columns eliminate repeated normalization at query time

### Negative
- Adds infrastructure dependency (dbt must run on schedule)
- Data freshness depends on dbt run frequency (currently every 20 minutes)
- Team must learn dbt SQL patterns and Jinja templating
- Two query languages in the stack (Python SQLAlchemy + dbt SQL)


## Compliance

- New data transformation logic MUST be implemented as a dbt model, not as Python code in controllers
- Controllers read from mart tables via DAOs
- Simple aggregations are acceptable to exist directly in DAOs

## Notes
