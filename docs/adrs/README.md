# Architecture Decision Records (ADRs)

An Architecture Decision Record captures a single architectural decision along with its context and consequences.
ADRs are short, focused documents that explain **why** a decision was made, not just what was decided.
They serve as a persistent log so that future contributors (and future-you) can understand the reasoning behind the system's design without having to reverse-engineer it from code.
ADRs should be thought of as immutable, once accepted they must be kept and only update the status when required but everything else should stay the exact same.

## Goal

- Record decisions at the point they are made, while context is fresh
- Provide a searchable history of architectural choices
- Make trade-offs explicit so they can be revisited when circumstances change
- Give new contributors a fast path to understanding the system

## Statuses

| Status     | Meaning |
|------------|---------|
| PROPOSED   | Under discussion; not yet approved |
| ACCEPTED   | Approved and in effect. May include a qualifier: |
|            | -- **(Implemented)** -- fully rolled out |
|            | -- **(In Progress)** -- adoption is underway |
|            | -- **(Active)** -- ongoing concern (e.g. a migration strategy) |
| DEPRECATED | No longer the recommended approach; kept for historical context |
| SUPERSEDED | Replaced by a newer ADR (link to replacement in the Status or Supersedes section) |

## Minimum Structure

Every ADR must contain at least the following sections:

```markdown
# ADR-NNNN: Title

## Status
ACCEPTED | PROPOSED | DEPRECATED | SUPERSEDED

## Date
YYYY-MM-DD

## Context
What situation or problem is forcing this decision?

## Decision
What is the architectural decision and how does it work?

## Consequences
What are the overall trade-offs?

### Positive
### Negative

## Compliance
What are the concrete rules that code reviewers can check against?

## Notes
```

### Optional Sections

These appear in some ADRs when relevant:

- **Supersedes** -- which ADR (and which specific rule) this one overrides
- **Scope Boundary** -- when the decision applies only under specific conditions
- **Cross-References** -- table of related ADRs and their relationship

## File Naming

```text
ADR-NNNN-short-title.md
```

Numbers are sequential starting from 0001.

## Index

| ADR | Title | Date | Status |
|-----|-------|------|--------|
| [0001](ADR-0001-dbt-as-transformation-layer.md) | dbt as Transformation Layer | 2025-11-01 | ACCEPTED (Implemented) |
| [0002](ADR-0002-sql-level-aggregation.md) | SQL-Level Aggregation | 2025-11-15 | ACCEPTED (In Progress) |
| [0003](ADR-0003-dao-layer-separation.md) | DAO Layer Separation | 2025-12-01 | ACCEPTED (In Progress -- Gradual Rollout) |
| [0004](ADR-0004-mart-tables-as-source-of-truth.md) | Mart Tables as Source of Truth | 2025-12-01 | ACCEPTED (In Progress -- Migration) |
| [0005](ADR-0005-feature-flag-gated-migration.md) | Feature Flag-Gated Migration | 2025-12-01 | ACCEPTED (Active) |
| [0006](ADR-0006-normalized-extraction-architecture.md) | Normalized Extraction Architecture | 2025-12-15 | ACCEPTED (Implemented) |
| [0007](ADR-0007-soft-deletes.md) | Soft Deletes | 2025-12-20 | ACCEPTED (Implemented) |
| [0008](ADR-0008-prompt-engineering-framework.md) | Prompt Engineering Framework | 2026-01-01 | ACCEPTED (Implemented) |
| [0009](ADR-0009-declarative-classification-rules.md) | Declarative Classification Rules | 2026-01-15 | ACCEPTED (Implemented) |
| [0010](ADR-0010-email-derived-vendor.md) | Email-Derived Vendor | 2026-01-20 | ACCEPTED (Implemented) |
| [0011](ADR-0011-user-override-layer.md) | User Override Layer | 2026-02-27 | ACCEPTED |
| [0012](ADR-0012-three-layer-api-architecture.md) | Three-Layer API Architecture (Route / Controller / DAO) | 2026-04-15 | ACCEPTED (In Progress -- Gradual Rollout) |
| [0013](ADR-0013-schema-level-request-validation.md) | Schema-Level Request Validation | 2026-04-15 | ACCEPTED (In Progress -- Gradual Rollout) |
| [0014](ADR-0014-alembic-managed-migrations.md) | Alembic-Managed Database Migrations | 2026-04-15 | ACCEPTED |
