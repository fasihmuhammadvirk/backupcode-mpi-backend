# ADR-0006: Normalized Extraction Architecture

## Status

ACCEPTED (Implemented)

## Date

2025-12-15

## Context

The original `public.model_extracted_data` table stored one row per line item with duplicated global fields (invoice date, vendor, reference number, etc.) on every row. This caused:

- 50%+ storage redundancy (global fields repeated per line item)
- Inconsistent global fields across rows of the same extraction (race conditions during writes)
- No way to A/B test extraction models (one table, one schema, no versioning)
- Incremental dbt runs couldn't work correctly (no clear extraction boundary)
- No distinction between "raw extraction output" and "cleaned/parsed data"

## Decision

Introduce a **normalized extraction architecture** using the `raw` schema:

### Table: `raw.model_extracted_data`

- One row per extraction attempt
- Stores the complete AI model response in a `raw_data` column

### dbt Parsing Pipeline

The raw JSONB is parsed through a series of dbt models:

1. **Staging** -- two models split the JSONB into global fields (one row per extraction: date, vendor, ref number, totals) and line items (one row per item: item, qty, cost, amount)
2. **Intermediate** -- combines line items with their global fields and tax rows, then applies quality filters and deduplication
3. **Mart** -- produces the final `mart__invoice_items` table, ready for API consumption

### Multi-Invoice PDF Support

A single PDF may contain multiple invoices. The extraction pipeline handles this by:
- Using a `multi_invoice` prompt that returns an array of invoice objects
- Each invoice object in the JSONB contains its own global fields and line items
- dbt staging models handle the array explosion


## Consequences

### Positive
- Extraction output is immutable (raw JSONB, never modified after write)
- A/B testing possible: two extractions of the same PDF stored as separate rows
- dbt handles all parsing -- no Python code touches raw data after extraction
- 50% storage reduction from eliminating row-level global field duplication
- Soft deletes preserve extraction history for audit and debugging
- Validation scores enable quality filtering at the dbt layer

### Negative
- JSONB queries in dbt are more complex than flat column access
- Migration from `public.model_extracted_data` requires backfill
- Two extraction tables exist during transition (legacy `public` + new `raw`)

## Compliance

- New extraction code MUST write to `raw.model_extracted_data` with JSONB `raw_data`
- Direct writes to `public.model_extracted_data` are legacy and being removed

## Notes
