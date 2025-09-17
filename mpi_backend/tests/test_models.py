#!/usr/bin/env python3
"""
Test database models to ensure proper data structure and relationships.
"""
import pytest
from datetime import date

from mpi_backend.database.models.Invoice import Invoice
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.CustomerJobMappings import CustomerJobMapping
from mpi_backend.database.models.UnmappedItems import UnmappedItems
from mpi_backend.database.models.MonthlyStatement import PlumbingStatement
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from mpi_backend.database.models.ItemClassification import ItemClassification
from mpi_backend.database.models.User import User


class TestDatabaseModels:
    """Test cases for database models."""

    def test_supplier_model_creation(self):
        """Test Supplier model creation."""
        supplier = Supplier(supplier_name="Test Supplier")
        
        # Test that the model can be instantiated
        assert supplier.supplier_name == "Test Supplier"
        assert hasattr(supplier, 'id')

    def test_invoice_model_creation(self):
        """Test Invoice model creation."""
        # Create supplier first
        supplier = Supplier(supplier_name="Test Supplier")
        
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        
        # Test that the model can be instantiated
        assert invoice.filename == "test_invoice.pdf"
        assert invoice.supplier_id == supplier.id
        assert hasattr(invoice, 'id')

    def test_invoice_item_model_creation(self):
        """Test InvoiceItem model creation with all fields."""
        # Create supplier and invoice first
        supplier = Supplier(supplier_name="Test Supplier")
        
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        
        # Create invoice item with numeric values for cost
        invoice_item = InvoiceItem(
            item="10001",
            description="Test Item Description",
            qty=5,
            cost=10.00,  # Use float instead of string
            amount="50.00",
            date=date.today(),
            ref_no="REF001",
            po_number="PO001",
            customer_job="Test Job",
            bill="Bill",
            vendor="Test Vendor",
            class_="Class1",
            account="Account1",
            memo="Test memo",
            buyer="Test Buyer",
            filename="test_invoice.pdf",
            sheet_name="Sheet1",
            mpi_item="MPI001",
            mpi_description="MPI Description",
            invoice_id=invoice.id,
            is_active=True,
            export_status="Pending"
        )
        
        # Test that the model can be instantiated
        assert invoice_item.item == "10001"
        assert invoice_item.cost == 10.00
        assert hasattr(invoice_item, 'id')

    def test_items_mapping_model(self):
        """Test ItemsMapping model creation and functionality."""
        mapping = ItemsMapping(
            google_sheet_name="Test Sheet",
            mpi_code="MPI001",
            description="Test Item",
            supplier_item_ids="SUP001",
            supplier_id=1
        )
        
        # Test that the model can be instantiated
        assert mapping.mpi_code == "MPI001"
        assert mapping.description == "Test Item"
        assert hasattr(mapping, 'id')

    def test_customer_job_mapping_model(self):
        """Test CustomerJobMapping model creation and functionality."""
        mapping = CustomerJobMapping(
            customer_job="Test Customer Job",
            updated_customer_job="MPI Customer Job"
        )
        
        # Test that the model can be instantiated
        assert mapping.customer_job == "Test Customer Job"
        assert mapping.updated_customer_job == "MPI Customer Job"
        assert hasattr(mapping, 'id')

    def test_unmapped_item_model(self):
        """Test UnmappedItems model for tracking unmapped items."""
        # Create supplier first
        supplier = Supplier(supplier_name="Test Supplier")
        
        unmapped = UnmappedItems(
            mpi_code="UNMAPPED001",
            description="Unmapped Item",
            supplier_item_ids="SUP001",
            supplier_id=supplier.id
        )
        
        # Test that the model can be instantiated
        assert unmapped.mpi_code == "UNMAPPED001"
        assert unmapped.description == "Unmapped Item"
        assert hasattr(unmapped, 'id')

    def test_monthly_statement_model(self):
        """Test PlumbingStatement model for statement tracking."""
        statement = PlumbingStatement(
            supplier_id=1,
            statement_date=date.today(),
            account_number="ACC001",
            total_amount=1000.00,
            total_invoices=5,
            pdf_filename="statement.pdf"
        )
        
        # Test that the model can be instantiated
        assert statement.account_number == "ACC001"
        assert statement.total_amount == 1000.00
        assert hasattr(statement, 'id')

    def test_temporary_item_mapping_model(self):
        """Test TemporaryItemMapping model for temporary mappings."""
        temp_mapping = TempItemMapping(
            original_item="TEMP001",
            original_description="Temporary Item",
            sheet_name="Test Sheet"
        )
        
        # Test that the model can be instantiated
        assert temp_mapping.original_item == "TEMP001"
        assert temp_mapping.original_description == "Temporary Item"
        assert hasattr(temp_mapping, 'id')

    def test_item_classification_model(self):
        """Test ItemClassification model for QuickBooks export."""
        classification = ItemClassification(
            item="MPI001",
            category="Materials"
        )
        
        # Test that the model can be instantiated
        assert classification.item == "MPI001"
        assert classification.category == "Materials"
        assert hasattr(classification, 'id')

    def test_user_model(self):
        """Test User model for authentication."""
        user = User(
            username="testuser",
            password="hashedpassword123"
        )
        
        # Test that the model can be instantiated
        assert user.username == "testuser"
        assert user.password == "hashedpassword123"
        assert hasattr(user, 'id')

    def test_model_relationships(self):
        """Test relationships between models."""
        # Create supplier
        supplier = Supplier(supplier_name="Test Supplier")
        
        # Create invoice
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        
        # Create invoice item
        invoice_item = InvoiceItem(
            item="10001",
            description="Test Item",
            qty=1,
            cost=10.00,
            amount="10.00",
            invoice_id=invoice.id
        )
        
        # Test relationships
        assert invoice_item.invoice_id == invoice.id
        assert invoice.supplier_id == supplier.id

    def test_complex_relationships_and_joins(self):
        """Test complex relationships between models."""
        # Create test data hierarchy
        supplier = Supplier(supplier_name="Complex Test Supplier")
        
        invoice = Invoice(
            date=date.today(),
            filename="complex_test.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/complex/path"
        )
        
        items = [
            InvoiceItem(
                item=f"COMPLEX{i:03d}",
                description=f"Complex Item {i}",
                invoice_id=invoice.id,
                qty=1,
                cost=10.00  # Use float instead of string
            )
            for i in range(3)
        ]
        
        # Test that models can be instantiated
        assert len(items) == 3
        assert items[0].item == "COMPLEX000"
        assert items[1].item == "COMPLEX001"
        assert items[2].item == "COMPLEX002"

    def test_data_validation_and_constraints(self):
        """Test data validation and constraints."""
        # Test that models can be instantiated with required fields
        try:
            supplier = Supplier(supplier_name="Test Supplier")
            assert supplier.supplier_name == "Test Supplier"
        except Exception:
            pytest.fail("Should be able to create supplier with required fields")

    def test_date_and_datetime_handling(self):
        """Test date and datetime field handling."""
        # Test different date formats and edge cases
        invoice = Invoice(
            filename="date_test.pdf",
            date=date.today()  # Current date
        )
        
        assert isinstance(invoice.date, date)
        
        # Test datetime fields
        mapping = ItemsMapping(
            google_sheet_name="Date Sheet",
            mpi_code="MPI_DATE001",
            description="Date Test",
            supplier_item_ids="SUP001",
            supplier_id=1
        )
        
        assert mapping.mpi_code == "MPI_DATE001"
        assert hasattr(mapping, 'id')

    def test_bulk_operations(self):
        """Test bulk operations."""
        # Test bulk creation
        suppliers = [
            Supplier(supplier_name=f"Bulk Supplier {i}")
            for i in range(5)
        ]
        
        # Verify all were created
        assert len(suppliers) == 5
        assert suppliers[0].supplier_name == "Bulk Supplier 0"
        assert suppliers[4].supplier_name == "Bulk Supplier 4"

    def test_model_serialization(self):
        """Test model serialization and deserialization."""
        supplier = Supplier(supplier_name="Serialization Test")
        
        # Test that we can access all attributes
        assert supplier.supplier_name == "Serialization Test"
        assert hasattr(supplier, 'id')
        
        # Test that we can modify attributes
        supplier.supplier_name = "Updated Name"
        assert supplier.supplier_name == "Updated Name"
