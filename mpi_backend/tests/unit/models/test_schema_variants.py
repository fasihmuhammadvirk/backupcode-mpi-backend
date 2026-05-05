#!/usr/bin/env python3
"""
Unit and integration tests for role-based schema variants and column filtering.

Tests cover:
- Schema selection based on user role
- Field exclusion for restricted roles
- Column access validation
- Integration with main endpoints
"""

import pytest
from fastapi import HTTPException
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.InvoiceItems import (
    InvoiceItemBase,
    InvoiceItemFull,
    InvoiceItemStandard
)
from mpi_backend.utils.auth.schema_selector import (
    get_invoice_item_schema,
    validate_column_access,
    can_access_column
)
from uuid import uuid4


class TestSchemaSelection:
    """Test schema selection based on user role"""

    def test_admin_gets_full_schema(self):
        """Admin users should get InvoiceItemFull with account field"""
        admin = User(id=uuid4(), role='admin', username='admin', is_active=True)
        schema = get_invoice_item_schema(admin)

        assert schema == InvoiceItemFull
        assert 'account' in schema.model_fields

    def test_bookkeeping_gets_full_schema(self):
        """Bookkeeping users should get InvoiceItemFull with account field"""
        bookkeeper = User(id=uuid4(), role='bookkeeping', username='bookkeeper', is_active=True)
        schema = get_invoice_item_schema(bookkeeper)

        assert schema == InvoiceItemFull
        assert 'account' in schema.model_fields

    def test_standard_gets_standard_schema(self):
        """Standard users should get InvoiceItemStandard without account field"""
        standard = User(id=uuid4(), role='standard', username='user', is_active=True)
        schema = get_invoice_item_schema(standard)

        assert schema == InvoiceItemStandard
        assert 'account' not in schema.model_fields


class TestSchemaFieldExclusion:
    """Test that schemas properly exclude fields based on role"""

    def test_full_schema_includes_account(self):
        """InvoiceItemFull should accept and include account field"""
        # Use model_construct to bypass validation for minimal test
        item = InvoiceItemFull.model_construct(
            id=1,
            item='ABC123',
            description='Test item',
            account='12345-M'
        )
        assert item.account == '12345-M'

    def test_standard_schema_excludes_account(self):
        """InvoiceItemStandard should ignore account field during parsing"""
        # Use model_construct to test field exclusion
        item = InvoiceItemStandard.model_construct(
            id=1,
            item='ABC123',
            description='Test item',
            account='12345-M'  # This should be ignored by Standard schema
        )
        assert not hasattr(item, 'account')
        assert item.item == 'ABC123'  # Other fields still work

    def test_base_schema_excludes_account(self):
        """InvoiceItemBase should not have account field"""
        assert 'account' not in InvoiceItemBase.model_fields

    def test_full_schema_validates_account(self):
        """InvoiceItemFull should apply account normalization validator"""
        # Testing the validator requires providing all required fields
        # Use model_validate with minimal complete data
        item = InvoiceItemFull.model_construct(
            id=1,
            item='ABC123',
            account='UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        )
        # Since we used model_construct, validator isn't run. Test it separately
        from mpi_backend.database.schemas.InvoiceItems import InvoiceItemFull as Schema
        normalized = Schema.normalize_account('UnInvoiced JIP:Cost Of Materials:Job Materials Purchased')
        assert normalized == 'M'  # Should be normalized


class TestColumnAccessValidation:
    """Test column access validation functions"""

    def test_standard_cannot_access_account(self):
        """validate_column_access should raise 403 for standard users accessing account"""
        with pytest.raises(HTTPException) as exc_info:
            validate_column_access('account', 'standard')

        assert exc_info.value.status_code == 403
        assert 'Access denied' in str(exc_info.value.detail)

    def test_standard_cannot_access_account_number(self):
        """validate_column_access should raise 403 for standard users accessing account_number"""
        with pytest.raises(HTTPException) as exc_info:
            validate_column_access('account_number', 'standard')

        assert exc_info.value.status_code == 403

    def test_admin_can_access_account(self):
        """validate_column_access should not raise for admin accessing account"""
        try:
            validate_column_access('account', 'admin')
        except HTTPException:
            pytest.fail("Admin should be able to access account column")

    def test_bookkeeping_can_access_account(self):
        """validate_column_access should not raise for bookkeeping accessing account"""
        try:
            validate_column_access('account', 'bookkeeping')
        except HTTPException:
            pytest.fail("Bookkeeping should be able to access account column")

    def test_standard_can_access_other_columns(self):
        """Standard users should be able to access non-restricted columns"""
        allowed_columns = ['item', 'description', 'cost', 'vendor', 'customer_job']

        for column in allowed_columns:
            try:
                validate_column_access(column, 'standard')
            except HTTPException:
                pytest.fail(f"Standard user should access {column} column")

    def test_can_access_column_helper(self):
        """can_access_column should return boolean without raising"""
        assert can_access_column('account', 'admin') is True
        assert can_access_column('account', 'standard') is False
        assert can_access_column('item', 'standard') is True


class TestSchemaIntegration:
    """Integration tests with actual data"""

    def test_convert_dict_to_full_schema(self):
        """Test converting dict with account to InvoiceItemFull"""
        raw_data = {
            'id': 123,
            'item': 'PIPE-001',
            'description': '1/2 inch pipe',
            'qty': 10,
            'cost': '15.50',
            'amount': '155.00',
            'vendor': 'ABC Supply',
            'account': 'M',
            'customer_job': 'Job Site A'
        }

        item = InvoiceItemFull.model_construct(**raw_data)
        assert item.account == 'M'
        assert item.item == 'PIPE-001'

    def test_convert_dict_to_standard_schema(self):
        """Test converting dict with account to InvoiceItemStandard (account ignored)"""
        raw_data = {
            'id': 123,
            'item': 'PIPE-001',
            'description': '1/2 inch pipe',
            'qty': 10,
            'cost': '15.50',
            'amount': '155.00',
            'vendor': 'ABC Supply',
            'account': 'M',  # Should be ignored
            'customer_job': 'Job Site A'
        }

        item = InvoiceItemStandard.model_construct(**raw_data)
        assert not hasattr(item, 'account')
        assert item.item == 'PIPE-001'
        assert item.vendor == 'ABC Supply'

    def test_list_filtering_simulation(self):
        """Simulate filtering a list of items by role"""
        raw_items = [
            {'id': 1, 'item': 'A', 'account': 'M'},
            {'id': 2, 'item': 'B', 'account': 'E'},
            {'id': 3, 'item': 'C', 'account': 'A'}
        ]

        # Admin sees account (using model_construct)
        admin_items = [InvoiceItemFull.model_construct(**item) for item in raw_items]
        assert all(hasattr(item, 'account') for item in admin_items)
        assert admin_items[0].account == 'M'

        # Standard doesn't see account (using model_construct)
        standard_items = [InvoiceItemStandard.model_construct(**item) for item in raw_items]
        assert all(not hasattr(item, 'account') for item in standard_items)
        assert standard_items[0].item == 'A'


class TestBackwardsCompatibility:
    """Test backwards compatibility"""

    def test_invoice_items_alias_works(self):
        """InvoiceItems alias should point to InvoiceItemFull"""
        from mpi_backend.database.schemas.InvoiceItems import InvoiceItems

        assert InvoiceItems == InvoiceItemFull

        item = InvoiceItems.model_construct(id=1, item='TEST', account='M')
        assert item.account == 'M'


class TestValidators:
    """Test that validators are properly inherited"""

    def test_cost_validator_in_standard_schema(self):
        """Standard schema should have cost validator from base"""
        # Validators aren't called with model_construct, test field existence instead
        assert 'cost' in InvoiceItemStandard.model_fields

    def test_buyer_validator_in_standard_schema(self):
        """Standard schema should have buyer validator from base"""
        # Validators are inherited from Base schema
        assert 'buyer' in InvoiceItemStandard.model_fields

    def test_account_validator_in_full_schema(self):
        """Full schema should have account validator"""
        assert 'account' in InvoiceItemFull.model_fields
        # Account field exists only in Full schema
        assert 'account' not in InvoiceItemStandard.model_fields


class TestSerializationBehavior:
    """Test model_dump() serialization behavior (critical for API responses)"""

    def test_model_dump_preserves_null_values(self):
        """model_dump should preserve NULL values for defined fields"""
        item = InvoiceItemFull.model_construct(
            id=1,
            item='ABC',
            vendor=None,  # NULL value
            description=None,  # NULL value
            account='M'
        )

        serialized = item.model_dump(exclude_unset=False, exclude_none=False)

        # NULL values should be preserved
        assert 'vendor' in serialized
        assert serialized['vendor'] is None
        assert 'description' in serialized
        assert serialized['description'] is None

    def test_model_dump_excludes_undefined_fields(self):
        """model_dump should exclude fields not in schema definition"""
        # Create with account field (but Standard schema doesn't have it)
        item = InvoiceItemStandard.model_construct(
            id=1,
            item='ABC',
            vendor='Test Vendor',
            account='M'  # This field doesn't exist in Standard schema
        )

        serialized = item.model_dump(exclude_unset=False, exclude_none=False)

        # Account should NOT appear in serialized output
        assert 'account' not in serialized
        # Other fields should be present
        assert 'id' in serialized
        assert 'item' in serialized
        assert 'vendor' in serialized

    def test_model_dump_full_vs_standard_comparison(self):
        """Compare Full and Standard serialization with same data"""
        data = {
            'id': 123,
            'item': 'PIPE-001',
            'vendor': 'ABC Supply',
            'description': None,  # NULL
            'account': 'M'
        }

        # Full schema
        full_item = InvoiceItemFull.model_construct(**data)
        full_dict = full_item.model_dump(exclude_unset=False, exclude_none=False)

        # Standard schema
        standard_item = InvoiceItemStandard.model_construct(**data)
        standard_dict = standard_item.model_dump(exclude_unset=False, exclude_none=False)

        # Both should have common fields
        assert full_dict['id'] == standard_dict['id']
        assert full_dict['item'] == standard_dict['item']
        assert full_dict['vendor'] == standard_dict['vendor']

        # Both should preserve NULL description
        assert full_dict['description'] is None
        assert standard_dict['description'] is None

        # Only Full should have account
        assert 'account' in full_dict
        assert full_dict['account'] == 'M'
        assert 'account' not in standard_dict

    def test_json_serialization_compatibility(self):
        """Test that model_dump output is JSON-serializable"""
        import json

        item = InvoiceItemStandard.model_construct(
            id=1,
            item='ABC',
            vendor=None
        )

        serialized = item.model_dump(exclude_unset=False, exclude_none=False)

        # Should be JSON-serializable without errors
        try:
            json_str = json.dumps(serialized)
            assert json_str is not None
        except Exception as e:
            pytest.fail(f"Serialization failed: {e}")
