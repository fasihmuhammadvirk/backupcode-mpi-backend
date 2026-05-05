# ADR-0011: User Override Layer for Mart-Derived Data

## Status

ACCEPTED

## Date

2026-02-27

## Supersedes

ADR-0004's mart-only read rule, for the specific case of user corrections to mart-derived data. The mart-only rule continues to apply for all pipeline/analytical reads.

## Context

Issue [#169](https://github.com/Mpi-plumbing/mpi-backend/issues/169) identified that users need to correct values in mart-derived records (e.g. wrong sheet name, wrong item mapping, wrong amount).
Mart tables are written by dbt, not the API, so users cannot correct data via a direct table write.

The agreed design is a "Persistent Override Source + Bounded API Join" pattern:
- Users write corrections to a dedicated `public.user_overrides` table
- dbt picks up those overrides on each run and COALESCEs them into the mart
- The API JOIN covers the freshness window between a user write and the next dbt run

## Scope Boundary

This pattern applies ONLY when both are true:

1. The data originated from the dbt extraction pipeline (lives in `analytics.mart__*`)
2. A user wants to correct a value in that mart-derived record

## Decision

### Override Table

`public.user_overrides` -- one row per mart record, keyed by `record_id` (the invoice item ID).

| Column | Purpose |
|--------|---------|
| `record_id` | Primary key -- references the mart record being overridden |
| `overrides` | JSONB containing only the fields the user has changed (e.g. sheet name, amount) |
| `overridden_by` | UUID of the user who made the change |
| `overridden_at` | Timestamp of the override |
| `is_deleted` / `deleted_at` | Soft-delete columns per ADR-0007 |

- Lives in `public` schema (application data, not pipeline data)
- App-managed; dbt reads from it
- ADR-0007 (soft deletes) applies: overrides are reverted via soft delete, not hard-deleted

### Write Path

Controller --> DAO --> UPSERT into `public.user_overrides`.
Before any UPSERT, the controller/DAO MUST enforce record-level authorization (tenant/account ownership + user permission) for the target record ID.

The DAO performs an upsert keyed on record ID:

- **New override:** inserts a row with the override JSONB, user ID, and timestamp
- **Existing override:** merges the new JSONB keys into the existing override (untouched fields are preserved), updates the user ID and timestamp, and clears any soft-delete flag
- **Null override values are disallowed at the API layer.** To revert a single field, remove its key from the JSONB. To revert all overrides for a record, soft-delete the row.
- If a key is absent from the overrides JSONB, the original mart value is used automatically (no special handling needed)
- User context (e.g.: `overridden_by`) is passed as a direct parameter, not via database session variables

### dbt Injection Point

The injection point is the `int__invoice_items_with_normalized_fields` view, so changes propagate to all downstream marts automatically.

- A CTE joins non-deleted rows from `public.user_overrides` to the invoice items
- For each overrideable field, COALESCE picks the override value if present, otherwise keeps the original
- An overridden flag is true when an override row exists for that record
- After a dbt run, mart tables contain the override value baked in -- no API-level join needed post-run

### API-Level Join for Freshness

The DAO LEFT JOINs the mart with `public.user_overrides` to cover the window between a user writing an override and the next dbt run. Per ADR-0002, this join lives in SQL, not Python.

- DAO reads/writes involving overrides MUST enforce record-level authorization and tenant scoping
- The query selects all mart columns plus COALESCE'd override values for each overrideable field
- Only non-deleted override rows are joined
- An `is_overridden` flag indicates whether the record has active overrides
- This is correct in both states: pre-dbt-run (override comes from the join) and post-dbt-run (mart already has the override baked in, so COALESCE returns the mart value)
- This is the only place this join lives outside dbt

### Audit Log Table

`public.user_override_logs` -- append-only, one row per save event.

| Column | Purpose |
|--------|---------|
| `record_id` | Which mart record was affected |
| `old_values` | JSONB snapshot of overrides before the change |
| `new_values` | JSONB snapshot of overrides after the change |
| `action_type` | One of: upsert, field_revert, record_revert |
| `overridden_by` | UUID of the user who triggered the change |
| `saved_at` | Timestamp of the event |

- Populated by an AFTER INSERT OR UPDATE trigger on `public.user_overrides`. The trigger writes the before/after JSONB snapshot automatically on every write, no controller-level log calls needed.
- Admin endpoint reads from `public.user_override_logs` (not from `user_overrides`).
- ADR-0007 (soft deletes) does NOT apply to `public.user_override_logs`. The log table is append-only and must not be soft-deleted.


### ADR-0007 Compatibility

Soft deletes apply to `public.user_overrides`. One row per mart record (`record_id TEXT PRIMARY KEY`).

| Operation | Mechanism |
|-----------|-----------|
| Revert all overrides for a record | `is_deleted = TRUE`, `deleted_at = NOW()` |
| Revert a single field | `overrides = overrides - 'field_name'` (soft-delete the row if `overrides` becomes `'{}'`) |
| Fresh override on previously soft-deleted record | Re-UPSERT sets `is_deleted = FALSE`, `deleted_at = NULL` |

## Consequences

### Positive

- Business tables are never touched by user edits
- dbt remains the single transformation pipeline; overrides are folded in at a defined injection point
- The API join is idempotent: correct before and after a dbt run
- Full audit history via append-only `user_override_logs`
- Single-field reverts without losing other overrides
- JSONB `||` merge means multiple users can override different fields on the same record without clobbering

### Negative

- Freshness join adds a LEFT JOIN to mart queries that support overrides
- dbt intermediate model must explicitly list every overrideable field with COALESCE
- Two tables to maintain (`user_overrides` + `user_override_logs`)

## Cross-References

| ADR | Relationship |
|-----|-------------|
| ADR-0003 | DAO layer: all writes and reads go through DAO functions |
| ADR-0001 | dbt: override source is declared in dbt sources; COALESCE injected into intermediate model |
| ADR-0004 | Superseded in part: mart-only read rule relaxed for freshness join on override-enabled endpoints |
| ADR-0007 | Soft deletes apply to `public.user_overrides`; do NOT apply to `public.user_override_logs` |
| ADR-0002 | SQL aggregation: the freshness LEFT JOIN and COALESCE must be in the DAO SQL, not Python |

## Compliance

- User corrections to mart-derived data MUST write to `public.user_overrides` via DAO, never directly to mart tables
- The API DAO MUST include the freshness JOIN on `public.user_overrides` for all reads of mart-derived data that support user overrides
- dbt intermediate models MUST COALESCE override values for all overrideable fields
- Do NOT use this pattern for non-mart CRUD; use regular `public` schema tables
- Is this a user correction of mart-derived data? --> write to public.user_overrides via DAO, COALESCE in dbt and API JOIN (ADR-0011)

## Notes
