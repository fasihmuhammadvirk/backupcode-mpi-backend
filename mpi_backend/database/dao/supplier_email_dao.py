"""
Data Access Object for supplier email pattern queries.

Stateless functions for CRUD on supplier_email_patterns and supplier
email-related lookups, separating data access from controller business logic.
"""

import uuid
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.models.SupplierEmailPattern import SupplierEmailPattern


def get_all_suppliers_with_patterns(db: Session) -> List[Supplier]:
    """All suppliers with their email patterns eagerly loaded."""
    return (
        db.query(Supplier)
        .options(joinedload(Supplier.email_patterns))
        .order_by(Supplier.id)
        .all()
    )


def get_supplier_by_id(db: Session, supplier_id: int) -> Optional[Supplier]:
    return (
        db.query(Supplier)
        .options(joinedload(Supplier.email_patterns))
        .filter(Supplier.id == supplier_id)
        .first()
    )


def find_supplier_by_name(db: Session, name: str, exclude_id: Optional[int] = None) -> Optional[Supplier]:
    q = db.query(Supplier).filter(
        Supplier.supplier_name == name,
        Supplier.is_subject_resolved.is_(False),
    )
    if exclude_id is not None:
        q = q.filter(Supplier.id != exclude_id)
    return q.first()


def find_subject_resolved_supplier(db: Session, exclude_id: Optional[int] = None) -> Optional[Supplier]:
    q = db.query(Supplier).filter(Supplier.is_subject_resolved.is_(True))
    if exclude_id is not None:
        q = q.filter(Supplier.id != exclude_id)
    return q.first()


def create_supplier(db: Session, supplier_name: Optional[str], is_subject_resolved: bool) -> Supplier:
    s = Supplier(
        supplier_name=supplier_name,
        is_subject_resolved=is_subject_resolved,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def delete_supplier(db: Session, supplier: Supplier) -> bool:
    """Delete supplier; raises ValueError if other rows still reference this supplier."""
    try:
        db.delete(supplier)
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        raise ValueError(
            "Cannot delete vendor because it is referenced by existing records"
        ) from None


def get_pattern_by_id(db: Session, pattern_id: uuid.UUID) -> Optional[SupplierEmailPattern]:
    return (
        db.query(SupplierEmailPattern)
        .filter(SupplierEmailPattern.id == pattern_id)
        .first()
    )


def find_pattern_by_sender(
    db: Session, sender_pattern: str, exclude_id: Optional[uuid.UUID] = None
) -> Optional[SupplierEmailPattern]:
    q = db.query(SupplierEmailPattern).filter(
        SupplierEmailPattern.sender_pattern == sender_pattern
    )
    if exclude_id is not None:
        q = q.filter(SupplierEmailPattern.id != exclude_id)
    return q.first()


def create_pattern(
    db: Session, supplier_id: int, sender_pattern: str, is_active: bool
) -> SupplierEmailPattern:
    p = SupplierEmailPattern(
        supplier_id=supplier_id,
        sender_pattern=sender_pattern,
        is_active=is_active,
    )
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("sender_pattern already in use") from None
    db.refresh(p)
    return p


def update_pattern_fields(db: Session, pattern: SupplierEmailPattern) -> SupplierEmailPattern:
    """Commit current state of pattern to the database."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("sender_pattern already in use") from None
    db.refresh(pattern)
    return pattern


def update_supplier_fields(db: Session, supplier: Supplier) -> Supplier:
    """Commit current state of supplier to the database."""
    db.commit()
    db.refresh(supplier)
    return supplier


def delete_pattern(db: Session, pattern: SupplierEmailPattern) -> bool:
    db.delete(pattern)
    db.commit()
    return True
