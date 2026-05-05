# ADR-0007: Soft Deletes Throughout the Pipeline

## Status

ACCEPTED (Implemented)

## Date

2025-12-20

## Context

Hard deletes were used throughout the invoice processing pipeline. When an extraction failed, a duplicate was detected, or a vendor was unsupported, the corresponding records were permanently removed. This caused:

- No audit trail for why records disappeared
- Inability to debug extraction failures after the fact
- Lost data when classification rules changed (previously "unsupported" documents couldn't be reclassified)
- No way to recover from accidental deletions
- Backfill operations couldn't identify what had already been processed

## Decision

All deletions in the invoice processing pipeline use **soft deletes**. Records are marked as deleted but remain in the database.

### Soft Delete Columns

- Every table in the pipeline includes `deleted_at` columns
- All queries MUST filter soft-deleted records by default
- Admin/debug endpoints may include soft-deleted records with an explicit parameter

### Pipeline Behavior

- Before creating a new extraction, check if a soft-deleted record exists for the same S3 file key
- Before downloading an email attachment, check the download queue's soft deletion status
- Unsupported vendor extractions are soft-deleted with a reason field

## Consequences

### Positive
- Complete audit trail for all pipeline operations
- Reclassification possible (un-delete a record after updating rules)
- Backfill operations can skip already-processed records
- Debugging production issues is straightforward (the data is still there)
- Accidental deletions are recoverable

### Negative
- Database size grows (deleted records are retained)
- Every query must include `deleted_at` filter (forgetting = data leak)
- Unique constraints must account for soft-deleted records (e.g., composite unique on `s3_file_key` + `deleted_at`)

### Mitigation
- dbt models enforce the `deleted_at` filter at the staging layer
- Periodic archival of old soft-deleted records (>90 days) to cold storage
- DAO functions include the filter by default

## Compliance
- Deletion of pipeline records MUST use soft delete (set `deleted_at=now()`)
- Hard deletes are only permitted for truly transient data (temp files, cache entries)

## Notes
