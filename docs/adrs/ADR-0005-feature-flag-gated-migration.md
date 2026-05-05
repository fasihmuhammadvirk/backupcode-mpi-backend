# ADR-0005: Feature Flag-Gated Migration Strategy

## Status

ACCEPTED (Active)

## Date

2025-12-01

## Context

Migrating from the legacy ORM-based query path to the new DAO/mart-based path (ADRs 0003, 0004) cannot happen as a big-bang switch. The system processes production invoices daily, and any query regression would affect bookkeeping accuracy and QuickBooks exports.

The team needs a way to:
- Test new query paths in production with real data
- Roll back instantly if a new path produces incorrect results
- Gradually expand the user base as confidence grows
- Compare results between old and new paths

## Decision

Use a **three-mode feature flag system** to control the migration at the per-user and per-endpoint level.

### Three Phases of Rollout

**Phase 1: Production Safe (default)**
- `USE_DAO_WITH_FALLBACK = False` - uses the new DAO architecture with the existing code as fallback
- `USE_DAO_ONLY = False` - use the new DAO architecture without fallback

**Phase 2: DAO Testing (per-user)**
- Feature flag (e.g.: `use_dao_with_fallback`) enabled for specific users
- DAO executes first; if it fails or returns unexpected results, falls back to ORM
- Failures logged with warning mode for analysis
- User sees correct data regardless (ORM catches DAO failures)

**Phase 3: DAO Only (per-user, then global)**
- Feature flag `use_dao_only` enabled
- DAO is required; failure returns HTTP 500
- Only enabled after Phase 2 proves DAO correctness
- Eventually becomes the default (module-level flag flipped)

### Controller Implementation Pattern

When a controller method supports the DAO path:

1. Check the feature flag for the current user
2. If enabled, attempt the DAO call first
3. If the DAO call succeeds, return its result
4. If it fails, log a warning and fall back to the legacy ORM path
5. If the flag is disabled, use the legacy ORM path directly

### Feature Flag Source

Feature flags are stored in the database and exposed via:
- `GET /feature-flags` API endpoint
- `FeatureFlagContext` on the frontend
- `is_enabled(flag_name, user)` utility function on the backend

## Consequences

### Positive
- Zero-downtime migration with instant rollback capability
- Production validation with real data before full switch
- Per-user granularity allows testing with internal users first
- Failure logging during Phase 2 identifies edge cases before they affect all users
- Feature flags also serve non-migration purposes (hiding incomplete frontend features)

### Negative
- Two code paths must be maintained during migration (increases complexity)
- Feature flag checks add a small overhead per request
- Risk of "flag debt" -- flags that are never cleaned up after migration completes

### Cleanup Rule
Once a DAO path has been in Phase 3 (DAO Only) globally for 30 days with no DAO-path regressions (for example:
zero migration-related incidents and no rollback requests), the legacy ORM code and the feature flag check should be removed.

## Compliance
- All legacy-to-new migrations MUST use the three-phase feature flag pattern
- No big-bang switches of query paths in production

## Notes
