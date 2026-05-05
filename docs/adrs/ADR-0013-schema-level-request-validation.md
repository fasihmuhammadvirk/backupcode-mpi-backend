# ADR-0013: Schema-Level Request Validation

## Status

ACCEPTED (Active)

## Date

2026-04-15

## Context

Request validation was implemented inconsistently across the codebase:
- Some routes validated inputs with inline `if` checks before calling controllers.
- Some controllers re-validated the same inputs after receiving them.
- Cross-field validation (e.g., "either field A or field B must be provided") was duplicated or omitted.
- Validation errors raised in routes returned different shapes than domain errors from controllers.

Pydantic -- already used for response models -- provides purpose-built tools for this that were not being utilised consistently.

## Decision

All request validation logic lives in Pydantic request schemas, not in route handlers or controllers.

### Simple Field Validation

Single-field constraints (type, min/max length, regex format) are expressed as Pydantic field annotations:

```python
class CreateInvoiceRequest(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0)
```

### Cross-Field and Complex Validation

Multi-field rules and business-level input constraints use `@model_validator`:

```python
class POBulkImportRequest(BaseModel):
    item_mpi_codes: Optional[List[str]] = None
    item_codes: Optional[List[str]] = None

    @model_validator(mode='after')
    def validate_item_codes(self):
        if not self.item_mpi_codes and not self.item_codes:
            raise ValueError("Either item_mpi_codes or item_codes must be provided")
        return self
```

Raise `ValueError` directly. Pydantic catches `ValueError` from validators and wraps it into a `ValidationError`, which FastAPI serialises as a `422 Unprocessable Entity`.
The error message is preserved in the response. Do not raise HTTP exceptions from inside a schema validator since that couples input validation to the HTTP layer.

### What Stays in Controllers

Controllers validate **business state**: conditions that require querying the database or checking runtime context (e.g., "does this invoice belong to the requesting tenant?"). This is distinct from input shape validation and cannot be done in a schema.

### What Stays in Routes

Nothing. Routes trust that a successfully instantiated request schema is valid and pass it directly to the controller.

## Consequences

### Positive
- Validation errors are automatically serialised and returned by FastAPI before the controller is ever called.
- Business logic in controllers is not cluttered with input shape checks.
- Schemas are self-documenting -- the OpenAPI spec reflects real constraints.
- Schemas are independently testable without standing up a route or controller.

### Negative
- The boundary between input shape validation and domain logic can be blurry. Teams must exercise judgement about what belongs in a schema validator vs. a controller (e.g. a missing-field check belongs in the schema; a check that requires a DB query belongs in the controller).

### Risks
- `@model_validator` runs before the controller; validators that perform DB lookups would bypass the controller's session management. Schema validators MUST NOT access the database.

## Compliance

- Multi-field input constraints MUST be expressed as `@model_validator` methods in the request schema.
- Route handlers MUST NOT contain `if` statements that validate request fields.
- Controllers MUST NOT re-validate input shape; they may validate business state.
- Schema validators MUST NOT perform database queries.

## Related ADRs

- ADR-0012: Three-Layer API Architecture (establishes which layer owns which concern)

## Notes
