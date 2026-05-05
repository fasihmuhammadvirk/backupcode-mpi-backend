"""
Business logic for email-based supplier configuration.

Manages suppliers that participate in email scanning and their sender patterns.
Delegates raw DB access to ``database.dao.supplier_email_dao``.

When ``is_subject_resolved`` is True on a supplier, the email sender pattern
(e.g. ``invoicefwdmpi@gmail.com``) is a forwarding inbox. The actual supplier
is resolved from the email **subject** keywords (e.g. "BMW", "WWPS") by the dbt
model ``int__email_vendor_mapping.sql`` rather than the sender domain.
"""

import logging
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from mpi_backend.database.dao import supplier_email_dao as dao
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.models.SupplierEmailPattern import SupplierEmailPattern

logger = logging.getLogger(__name__)


class EmailVendorController:
    """
    CRUD for suppliers participating in email scanning and their sender patterns.

    Maps to ``public.suppliers`` (with ``is_subject_resolved``) and
    ``public.supplier_email_patterns``.  Callers (FastAPI routes) translate
    ``ValueError`` / ``LookupError`` to HTTP responses.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_all_suppliers(self) -> List[Supplier]:
        """Suppliers used for email resolution (see DAO: patterns or subject-resolved)."""
        try:
            return dao.get_all_suppliers_with_patterns(self.db)
        except Exception as e:
            logger.error(f"Error fetching suppliers: {e}")
            raise

    def get_supplier_by_id(self, supplier_id: int) -> Optional[Supplier]:
        """Get a single supplier by ID."""
        try:
            return dao.get_supplier_by_id(self.db, supplier_id)
        except Exception as e:
            logger.error(f"Error fetching supplier {supplier_id}: {e}")
            raise

    def create_supplier(
        self, name: Optional[str], is_subject_resolved: bool
    ) -> Supplier:
        """Create a new supplier for email scanning."""
        try:
            if is_subject_resolved:
                if dao.find_subject_resolved_supplier(self.db):
                    raise ValueError("A subject-resolved supplier already exists")
                return dao.create_supplier(self.db, None, True)
            else:
                if not name or not name.strip():
                    raise ValueError(
                        "name is required unless is_subject_resolved is true"
                    )
                nm = name.strip()
                if dao.find_supplier_by_name(self.db, nm):
                    raise ValueError(f"Supplier with name '{nm}' already exists")
                return dao.create_supplier(self.db, nm, False)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error creating supplier: {e}")
            raise

    def update_supplier(self, supplier_id: int, updates: dict) -> Supplier:
        """
        Partially update a supplier.

        ``updates`` is a dict of fields present in the request body.
        Only keys that exist in the dict are applied.
        """
        try:
            s = dao.get_supplier_by_id(self.db, supplier_id)
            if not s:
                raise LookupError("Supplier not found")

            if "is_subject_resolved" in updates:
                val = updates["is_subject_resolved"]
                if not isinstance(val, bool):
                    raise ValueError("is_subject_resolved must be a boolean")
                next_is_subject_resolved = val
            else:
                next_is_subject_resolved = s.is_subject_resolved

            if "name" in updates:
                raw = updates["name"]
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    next_name = None
                else:
                    next_name = raw.strip()
            else:
                next_name = s.supplier_name

            if next_is_subject_resolved:
                next_name = None
                if dao.find_subject_resolved_supplier(self.db, exclude_id=supplier_id):
                    raise ValueError("A subject-resolved supplier already exists")
            else:
                if not next_name:
                    raise ValueError(
                        "name is required unless is_subject_resolved is true"
                    )
                if dao.find_supplier_by_name(self.db, next_name, exclude_id=supplier_id):
                    raise ValueError(
                        f"Supplier with name '{next_name}' already exists"
                    )

            s.supplier_name = next_name
            s.is_subject_resolved = next_is_subject_resolved
            return dao.update_supplier_fields(self.db, s)
        except (ValueError, LookupError):
            raise
        except Exception as e:
            logger.error(f"Error updating supplier {supplier_id}: {e}")
            raise

    def delete_supplier(self, supplier_id: int) -> bool:
        """Delete a supplier and its patterns. ValueError if delete is blocked by referencing rows."""
        try:
            s = dao.get_supplier_by_id(self.db, supplier_id)
            if not s:
                raise LookupError("Supplier not found")
            return dao.delete_supplier(self.db, s)
        except (LookupError, ValueError):
            raise
        except Exception as e:
            logger.error(f"Error deleting supplier {supplier_id}: {e}")
            raise

    def add_pattern(
        self, supplier_id: int, sender_pattern: str, is_active: bool = True
    ) -> SupplierEmailPattern:
        """Add a sender pattern to a supplier. Caller (schema) handles strip/lowercase."""
        try:
            s = dao.get_supplier_by_id(self.db, supplier_id)
            if not s:
                raise LookupError("Supplier not found")
            if dao.find_pattern_by_sender(self.db, sender_pattern):
                raise ValueError("sender_pattern already in use")
            return dao.create_pattern(self.db, supplier_id, sender_pattern, is_active)
        except (ValueError, LookupError):
            raise
        except Exception as e:
            logger.error(f"Error adding pattern to supplier {supplier_id}: {e}")
            raise

    def update_pattern(self, pattern_id: uuid.UUID, updates: dict) -> SupplierEmailPattern:
        """Partially update a sender pattern using a dict of changed fields."""
        try:
            p = dao.get_pattern_by_id(self.db, pattern_id)
            if not p:
                raise LookupError("Pattern not found")
            if "sender_pattern" in updates:
                sp = updates["sender_pattern"]
                if dao.find_pattern_by_sender(self.db, sp, exclude_id=pattern_id):
                    raise ValueError("sender_pattern already in use")
                p.sender_pattern = sp
            if "is_active" in updates:
                val = updates["is_active"]
                if not isinstance(val, bool):
                    raise ValueError("is_active must be a boolean")
                p.is_active = val
            return dao.update_pattern_fields(self.db, p)
        except (ValueError, LookupError):
            raise
        except Exception as e:
            logger.error(f"Error updating pattern {pattern_id}: {e}")
            raise

    def delete_pattern(self, pattern_id: uuid.UUID) -> bool:
        """Delete a sender pattern."""
        try:
            p = dao.get_pattern_by_id(self.db, pattern_id)
            if not p:
                raise LookupError("Pattern not found")
            return dao.delete_pattern(self.db, p)
        except LookupError:
            raise
        except Exception as e:
            logger.error(f"Error deleting pattern {pattern_id}: {e}")
            raise
