#!/usr/bin/env python3
"""Unit tests for email-vendor request schema validation."""

import pytest
from pydantic import ValidationError

from mpi_backend.database.schemas.EmailVendor import (
    SupplierPatternCreate,
    SupplierPatternUpdate,
)


def test_supplier_pattern_create_rejects_blank_sender_pattern():
    """Blank sender_pattern should fail before controller/database logic."""
    with pytest.raises(ValidationError):
        SupplierPatternCreate(sender_pattern="   ", is_active=True)


def test_supplier_pattern_create_rejects_too_long_sender_pattern():
    """sender_pattern >255 chars should fail at schema validation."""
    with pytest.raises(ValidationError):
        SupplierPatternCreate(sender_pattern=("a" * 256), is_active=True)


def test_supplier_pattern_create_strips_whitespace():
    """Input should be trimmed once so dedupe checks stay consistent."""
    schema = SupplierPatternCreate(sender_pattern="  @example.com  ", is_active=True)
    assert schema.sender_pattern == "@example.com"


def test_supplier_pattern_update_rejects_blank_sender_pattern():
    """PATCH payload should reject blank sender_pattern when provided."""
    with pytest.raises(ValidationError):
        SupplierPatternUpdate(sender_pattern="   ")

