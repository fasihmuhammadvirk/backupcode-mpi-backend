# ADR-0012: Three-Layer API Architecture (Route / Controller / DAO)

## Status

ACCEPTED (Active)

## Date

2026-04-15

## Context

As the backend grew beyond a single controller file, code responsibility boundaries became ambiguous. Route handlers began containing business logic. Controllers began constructing queries. This led to:

- Untestable business logic coupled to FastAPI request/response objects
- Query changes requiring edits in business logic files
- Duplicate validation scattered across routes and controllers
- No consistent pattern for new contributors to follow

ADR-0003 established the DAO layer in isolation. This ADR formalises the complete three-layer contract across all new code.

## Decision

All API request handling follows a strict three-layer architecture:

```text
Route Layer (api/routes/)  -->  Controller Layer (database/controllers/)  -->  DAO Layer (database/dao/)  -->  Database
```

### Layer Responsibilities

**Route Layer (`mpi_backend/api/routes/`)**
- Define API endpoints and HTTP methods via FastAPI decorators.
- Declare Pydantic request/response schemas on the endpoint signature.
- Inject dependencies via `Depends()` (database session, authenticated user).
- Delegate all work to a controller; return the controller's result directly.
- Trigger `BackgroundTasks` where needed.
- **Must not**: contain business logic, construct queries, or access `db` directly.

**Controller Layer (`mpi_backend/database/controllers/`)**
- Own all business rules and domain constraints.
- Orchestrate one or more DAO calls to fulfil a use case.
- Transform raw DAO output (`RowMapping` / dataclass) into Pydantic response models.
- Call utility functions from `mpi_backend/utils/` for cross-cutting operations.
- **Must not**: construct SQL or call `db.execute()` / `db.query()` directly.
- **Must**: be reusable -- a controller method should be callable from multiple routes without modification.

**DAO Layer (`mpi_backend/database/dao/`)**
- Construct and execute all SQL (raw `text()` or SQLAlchemy ORM).
- Accept `db: Session` as an explicit parameter; never create or own a session.
- Return `RowMapping` objects or dataclass instances -- not Pydantic models.
- Contain no business logic; filtering parameters passed in are applied mechanically.
- See ADR-0003 for DAO structural rules (function vs class, session ownership).

## Consequences

### Positive
- Each layer is independently testable (routes with mocked controllers, controllers with mocked DAOs, DAOs with a test session).
- Query changes are isolated to the DAO layer; business logic is unaffected.
- New contributors have a clear, consistent pattern to follow.
- Controllers are reusable across routers without duplication.

### Negative
- Simple endpoints require three files instead of one -- overhead for trivial cases.
- Dataclass-to-Pydantic mapping step adds a small amount of boilerplate in controllers.

### Risks
- Legacy code in `InvoiceItemController` still violates these boundaries. That code is not a reference; do not model new code on it.

## Compliance

- New API endpoints MUST delegate to a controller; routes must not touch `db` directly.
- New database access MUST go through a DAO (see ADR-0003).
- Controllers MUST NOT call `db.execute()` or `db.query()` for new code.
- Business logic MUST NOT appear in route handlers.

## Related ADRs

- ADR-0003: DAO Layer Separation (DAO structural rules)
- ADR-0004: Mart Tables as Source of Truth (what DAOs query)
- ADR-0013: Schema-Level Request Validation (where validation lives)

## Notes
