# ADR-0014: Alembic-Managed Database Migrations

## Status

ACCEPTED (Active)

## Date

2026-04-15

## Context

Without a formal migration workflow, schema changes were applied inconsistently:
- Some changes were applied manually to production without a corresponding script.
- Rollbacks required manual SQL, often undocumented.
- New developer environments diverged from production over time.
- There was no audit trail of when schema changes were applied or by whom.

## Decision

All `mpi_backend` database schema changes are managed exclusively through Alembic migration scripts.

### Scope

A new Alembic migration file is **mandatory** for:
- Creating or dropping tables.
- Adding, renaming, or removing columns.
- Changing column types or nullability constraints.
- Adding or dropping indexes.
- Adding or dropping foreign key or unique constraints.

### Workflow

1. Update the SQLAlchemy model in `mpi_backend/database/models/`.
2. Generate a migration script:
   ```bash
   uv run alembic revision --autogenerate -m "short_description_of_change"
   ```
3. Review the generated script. Autogenerate is a starting point, not a final script -- verify it captures the intent correctly and does not include unintended changes.
4. Apply the migration to the target environment:
   ```bash
   uv run alembic upgrade head
   ```

### Review Checklist for Generated Scripts

Before committing a generated migration, verify:
- [ ] The `upgrade()` function performs only the intended change.
- [ ] The `downgrade()` function correctly reverses the upgrade.
- [ ] No unrelated tables or columns appear in the diff (common with autogenerate).
- [ ] Data migrations (if any) are handled explicitly -- autogenerate does not produce data migrations.
- [ ] Indexes on new columns are included if the column will be queried.

### Data Migrations

Schema-only migrations (DDL) are generated via `--autogenerate`. Data migrations (DML -- backfilling values, transforming existing rows) must be written manually inside the migration script, executed after the DDL step within the same migration.

### One-Off Schema Changes

No schema change may be applied to any environment by running raw SQL manually. All changes go through a migration file that is committed to version control before being applied.

## Consequences

### Positive
- Schema history is version-controlled alongside application code.
- Environments (local, staging, production) can be brought to the same schema state with a single command.
- Rollback is scripted and repeatable.
- PR reviews catch schema changes before they reach production.

### Negative
- Autogenerate occasionally produces incorrect or incomplete scripts, requiring manual correction.
- Generating migrations requires the local database to be running and at the previous migration state.

### Risks
- Autogenerate compares the live database to the current ORM models. If the live database already contains manual changes, the generated script may be incorrect. Keep environments clean.

## Compliance

- All schema changes MUST have a corresponding Alembic migration committed before the change is applied to any environment.
- Raw SQL DDL applied outside of Alembic is prohibited.
- Generated migration scripts MUST be reviewed before merging -- autogenerate output is not trusted blindly.

## Related ADRs

- ADR-0007: Soft Deletes (migration pattern for soft-delete columns)

## Notes
- If two pull requests (PRs) both generate a migration off the same head, our process for when the second one merges is:
  1. Rebase/merge and update the latter migrations' `down_version` to the right head
