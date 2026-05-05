#!/usr/bin/env python3
"""
Tests for role-based filtering of invoice items.

These tests verify that users with different roles see appropriately filtered data.
Standard users should NOT see accounting fields like 'account', while admin and
bookkeeping users should see all fields.
"""
import pytest

from uuid import uuid4

from fastapi_pagination import paginate, Params

from mpi_backend.utils.auth.schema_selector import get_invoice_item_schema
from mpi_backend.database.schemas.InvoiceItems import InvoiceItemFull, InvoiceItemStandard
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.roles import UserRole


def _make_filter_payload(filters=None, comparison_filters=None):
    """Helper to create filter request payload"""
    if filters is None:
        filters = {}
    if comparison_filters is None:
        comparison_filters = []
    return {
        "filters": filters,
        "comparison_filters": comparison_filters,
    }


def _create_mock_invoice_item_with_account():
    """Create a mock invoice item that includes the account field"""
    # Create a simple object with attributes
    class MockInvoiceItem:
        def __init__(self):
            self.id = 1
            self.item = 'ABC123'
            self.description = 'Test Item'
            self.cost = '10.50'
            self.vendor = 'Test Vendor'
            self.account = 'M'  # This is the sensitive field
            self.customer_job = 'Job Site A'
            # Add all required fields from InvoiceItemBase
            self.filename = None
            self.sheet_name = None
            self.mpi_item = None
            self.mpi_description = None
            self.qty = 1
            self.amount = '10.50'
            self.date = None
            self.ref_no = None
            self.po_number = None
            self.bill = None
            self.class_ = None
            self.export_status = None
            self.memo = None
            self.buyer = None
            self.date_added = None
            self.invoice_id = None
            self.is_active = True
            self.percentage_increase = None

    return MockInvoiceItem()

@pytest.mark.parametrize("role", list(UserRole))
def test_filter_endpoint_role_based_access(client, override_get_current_user, role, realistic_mock_invoice_controller):
    """
    Test that /filter endpoint respects role-based field filtering for different roles.

    GIVEN an authenticated user with a specific role
    WHEN the '/filter' endpoint is called
    THEN the response should correctly include or exclude the 'account' field based on the user's role.
    AND Admin and Bookkeeping users should see the 'account' field
    AND Standard users should not see the 'account' field.
    """

    user = User(id=uuid4(), username=f"{role}_user", role=role, company_id=1, is_active=True)

    with override_get_current_user(user):
        payload = _make_filter_payload()
        res = client.post("/filter", json=payload)

        assert res.status_code == 200
        body = res.json()

        assert "items" in body
        assert len(body["items"]) == 3, "Realistic mock should return 3 items"

        account_in_response = "account" in body["items"][0]
        if role in [UserRole.ADMIN.value, UserRole.BOOKKEEPING.value]:
            assert account_in_response, f"{role} users should see 'account' field"
            assert body["items"][0]["account"] == "1000-Materials"
        else:
            assert not account_in_response, f"{role} users should NOT see 'account' field"

@pytest.mark.parametrize("role", list(UserRole))
def test_filter_by_column_paginated(client, override_get_current_user, role, realistic_mock_invoice_controller):
    """
    Make sure standard user cannot access account column when requesting by column.

    GIVEN an authenticated user with a specific role
    WHEN a request is made to '/filter/by-column-paginated' for the 'account' column
    THEN the endpoint should return a 200 OK for Admin and Bookkeeping users
    AND the endpoint should return a 403 Forbidden for all other users.
    """
    user = User(id=uuid4(), username=f"{role}_user", role=role, company_id=1, is_active=True)

    with override_get_current_user(user):
        payload = {
            "comparison_filters": [
                {"column": "date", "operator": "gte", "value": "2000-01-01"},
                {"column": "date", "operator": "lte", "value": "2025-08-15"}
            ],
            "page": 1,
            "limit": 20
        }
        res = client.post("/filter/by-column-paginated?column_name=account", json=payload)

        if user.role in [UserRole.ADMIN.value, UserRole.BOOKKEEPING.value]:
            assert res.status_code == 200
            assert res.json()["data"] == [], "Realistic mock has no 'account' column data"
        else:
            assert res.status_code == 403


@pytest.mark.parametrize("role", list(UserRole))
def test_schema_selector_returns_correct_schema(role):
    """
    Test that invoice item schema filtering works correctly for different user roles.

    These tests directly verify the core schema filtering logic that protects sensitive
    fields based on user roles.

    GIVEN a user with a specific role
    WHEN the 'get_invoice_item_schema' utility function is called with that user
    THEN the function should return the correct Pydantic schema for that role.
    AND the 'InvoiceItemFull' schema (with 'account' field) should be returned for Admin and Bookkeeping users
    AND the 'InvoiceItemStandard' schema (without 'account' field) should be returned for other users.
    """

    user = User(id=uuid4(), username=f"{role}_user", role=role, company_id=1, is_active=True)
    schema = get_invoice_item_schema(user)
    if role in [UserRole.ADMIN.value, UserRole.BOOKKEEPING.value]:
        assert schema == InvoiceItemFull, "Admin and bookkeeping users should get InvoiceItemFull schema"
        assert "account" in schema.model_fields, "Admin and bookkeeping schemas should have account field"
    else:
        assert schema == InvoiceItemStandard, "Standard users should get InvoiceItemStandard schema"
        assert "account" not in schema.model_fields, "Standard schema should not have account field"

@pytest.mark.parametrize("role", list(UserRole))
def test_schemas_filters_account_field_from_database_objects(role):
    """
    Verify that Standard schema actually filters out account field from database objects.

    GIVEN a database object that contains an 'account' field
    AND a user with a specific role
    WHEN the object is validated against the schema corresponding to the user's role
    THEN the resulting Pydantic model should include the 'account' field for Admin and Bookkeeping users
    AND the resulting Pydantic model should NOT include the 'account' field for other users.

    TODO: We're doing mocking until we can have a database for our tests.
    """

    # Simulate database object with account field
    db_item = _create_mock_invoice_item_with_account()
    assert hasattr(db_item, 'account'), "Mock DB item should have account field"

    # Apply schema validation (this is what the endpoint does)
    user = User(id=uuid4(), username=f"{role}_user", role=role, company_id=1, is_active=True)
    schema = get_invoice_item_schema(user)
    validated_item = schema.model_validate(db_item)

    # Verify account field is present (admin and bookkeeper) or filtered out (standard user)
    from mpi_backend.database.schemas.InvoiceItems import InvoiceItemFull, InvoiceItemStandard
    if role in [UserRole.ADMIN.value, UserRole.BOOKKEEPING.value]:
        assert isinstance(validated_item, InvoiceItemFull), "Item should be InvoiceItemFull for admin/bookkeeping roles"
        assert validated_item.account == 'M', "Account field should have correct value"
        assert validated_item.item == 'ABC123', "Other fields should still be present"
    else:
        assert isinstance(validated_item, InvoiceItemStandard), "Item should be InvoiceItemStandard for other roles"
        assert not hasattr(validated_item, 'account'), "Validated item should NOT have account field"
        assert validated_item.item == 'ABC123', "Other fields should still be present"
        assert validated_item.vendor == 'Test Vendor', "Other fields should still be present"


def test_pagination_works_with_filtered_schemas():
    """
    Verify that pagination works correctly with role-filtered schemas.

    This test ensures that the `fastapi-pagination` library can correctly
    paginate a list of Pydantic models that have been filtered based on
    user role.

    GIVEN a list of database items and a standard user
    WHEN the items are filtered using the standard user's schema
    AND the filtered list is paginated
    THEN the pagination results (e.g., item count, total) should be correct.
    """
    standard_user = User(id=uuid4(), username='user', role='standard', company_id=1, is_active=True)

    # Simulate database results with more items than page size
    db_items = [_create_mock_invoice_item_with_account() for _ in range(25)]

    # Apply schema filtering (as it would happen in the endpoint)
    ItemSchema = get_invoice_item_schema(standard_user)
    filtered_items = [ItemSchema.model_validate(item) for item in db_items]

    # Apply pagination
    result = paginate(filtered_items, Params(page=1, size=10))

    # Verify that pagination logic is correct
    assert len(result.items) == 10, "Should have 10 items on page 1"
    assert result.total == 25, "Should have 25 total items"
    assert result.page == 1, "Should be page 1"

    # Note: We don't re-test the filtering of the 'account' field here,
    # as that is already covered in `test_schemas_filters_account_field_from_database_objects`.
    # This test focuses on the interaction between filtering and pagination.

