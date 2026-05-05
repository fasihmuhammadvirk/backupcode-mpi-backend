# ADR-0003: DAO Layer Separation from Controllers

## Status

ACCEPTED (In Progress -- Gradual Rollout)

## Date

2025-12-01 (initial DAO introduction) -- ongoing

## Context

The backend's `InvoiceItemController` grew to 4,895 lines with 102 methods (62 public, 40 private), 47 of which contain direct database access.
Business logic, input validation, query construction, and data access are tangled together in controller methods, making them untestable in isolation and difficult to optimize.

Key pain points observed in production:
- 12+ duplicate query patterns across methods
- 50+ scattered string normalization calls
- 267-line duplicate detection algorithm with 6+ embedded queries
- N+1 query risk in loops (e.g., lines 2010-2020 of InvoiceItems.py)
- Inability to swap query strategies (ORM vs raw SQL vs mart) without touching business logic

## Decision

Introduce a DAO (Data Access Object) layer between controllers and the ORM/database. DAOs:

1. **May be functions or classes** -- the choice depends on complexity. Simple query sets use plain functions;
    related query groups that share configuration or caching may use classes.
2. **Always receive `db: Session` as a parameter** -- DAOs never create or manage their own sessions.
    The session is owned by the request lifecycle (FastAPI's `Depends(get_db)`).
3. Return **dataclass objects** (not Pydantic models, not ORM objects). This keeps the DAO layer independent of both the API schema and the ORM layer.
4. Are organized by **mart table or domain concern**, not by controller method.
5. Use **raw SQL with CTEs** for performance-critical queries, ORM for simple CRUD.

### Controller Role After DAO Adoption

Controllers become **gatekeepers** responsible for:
- Business logic
- Input sanitization
- Feature flag checks (which query strategy to use)
- Error response formatting
- Resource monitoring (timing, memory)

Controllers do NOT construct queries or touch `db.query()` directly in new code.

## Consequences

### Positive
- DAO functions/classes are independently testable with a test database session
- Query optimization (switching from ORM to raw SQL) happens in one place
- Controllers shrink as query logic moves to DAOs
- Feature-flag rollout is possible (see ADR-0005)
- Clear ownership: DAO owns query correctness, controller owns business rules

### Negative
- Two code paths exist during migration (DAO and legacy ORM in same controller)
- Dataclass return types add a mapping step between DAO and Pydantic response schemas
- New contributors must understand which pattern to use (answer: always DAO for new code)

### Risks
- Migration is incremental; some methods will remain un-migrated for months
- DAO classes must be careful not to re-introduce the "god class" anti-pattern. Keep each DAO focused on a single domain concern


## Compliance
- New database access code MUST go through a DAO function or class
- The `db: Session` parameter is always passed in so DAOs never create their own sessions
- Direct `db.query()` in controllers is legacy and should not be extended.

## Notes
