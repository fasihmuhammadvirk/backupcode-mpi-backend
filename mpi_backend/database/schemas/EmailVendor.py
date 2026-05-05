from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator
from typing_extensions import Annotated

from mpi_backend.database.models.Suppliers import Supplier


class SupplierPatternResponse(BaseModel):
    """One sender_pattern row exposed to the API."""

    id: UUID
    sender_pattern: str
    is_active: bool

    class Config:
        from_attributes = True


class SupplierEmailResponse(BaseModel):
    """Supplier with nested email patterns for list/detail responses."""

    id: int
    name: Optional[str] = None
    is_subject_resolved: bool
    patterns: List[SupplierPatternResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


def supplier_to_response(s: Supplier) -> SupplierEmailResponse:
    """Map a Supplier ORM row (with loaded email_patterns) to API response."""
    return SupplierEmailResponse(
        id=s.id,
        name=s.supplier_name,
        is_subject_resolved=bool(s.is_subject_resolved),
        patterns=[
            SupplierPatternResponse(
                id=p.id,
                sender_pattern=p.sender_pattern,
                is_active=bool(p.is_active),
            )
            for p in (s.email_patterns or [])
        ],
    )


class SupplierEmailCreate(BaseModel):
    """Create a supplier for email scanning."""

    name: Optional[str] = None
    is_subject_resolved: bool = False


class SupplierEmailUpdate(BaseModel):
    """Partial update; only fields present in the JSON body are applied."""

    name: Optional[str] = None
    is_subject_resolved: Optional[bool] = None


class SupplierPatternCreate(BaseModel):
    """Attach a sender pattern; sender_pattern is trimmed, lowercased, non-empty, max 255 chars (matches DB)."""

    sender_pattern: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    is_active: bool = True

    @field_validator("sender_pattern", mode="after")
    @classmethod
    def lowercase_pattern(cls, v: str) -> str:
        return v.lower()


class SupplierPatternUpdate(BaseModel):
    """Partial update; optional fields use same sender_pattern rules as create when provided."""

    sender_pattern: Optional[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    ] = None
    is_active: Optional[bool] = None

    @field_validator("sender_pattern", mode="after")
    @classmethod
    def lowercase_pattern(cls, v: Optional[str]) -> Optional[str]:
        return v.lower() if v is not None else v
