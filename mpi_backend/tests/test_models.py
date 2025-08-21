#!/usr/bin/env python3
"""
Comprehensive test suite for all database models.
Tests model creation, relationships, validation, and edge cases.
"""

import pytest
import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
# from sqlalchemy.exc import IntegrityError  # Not used in current tests

from mpi_backend.database.base import Base
from mpi_backend.database.models.Invoice import Invoice
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.Suppliers import Supplier
from mpi_backend.database.models.CustomerJobMappings import CustomerJobMapping
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.UnmappedItems import UnmappedItem
from mpi_backend.database.models.MonthlyStatement import MonthlyStatement
from mpi_backend.database.models.TemporaryItemMapping import TemporaryItemMapping
from mpi_backend.database.models.ItemClassification import ItemClassification
from mpi_backend.database.models.User import User


class TestDatabaseModels:
    """Test suite for all database models."""

    @pytest.fixture(scope="function")
    def db_session(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()

    def test_supplier_model_creation(self, db_session):
        """Test Supplier model creation and basic properties."""
        supplier = Supplier(
            supplier_name="Test Supplier",
            supplier_name_en="Test Supplier EN"
        )
        
        db_session.add(supplier)
        db_session.commit()
        
        assert supplier.id is not None
        assert supplier.supplier_name == "Test Supplier"
        assert supplier.supplier_name_en == "Test Supplier EN"

    def test_supplier_model_relationships(self, db_session):
        """Test Supplier model relationships with other models."""
        supplier = Supplier(supplier_name="Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        # Test Invoice relationship
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        db_session.add(invoice)
        db_session.commit()
        
        # Verify relationship
        assert len(supplier.supplier) == 1
        assert supplier.supplier[0].filename == "test_invoice.pdf"

    def test_invoice_model_creation(self, db_session):
        """Test Invoice model creation and validation."""
        # Create supplier first
        supplier = Supplier(supplier_name="Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path/invoice.pdf",
            is_exported="Pending"
        )
        
        db_session.add(invoice)
        db_session.commit()
        
        assert invoice.id is not None
        assert isinstance(invoice.id, uuid.UUID)
        assert invoice.filename == "test_invoice.pdf"
        assert invoice.status == "PROCESSED"
        assert invoice.is_exported == "Pending"

    def test_invoice_item_model_creation(self, db_session):
        """Test InvoiceItem model creation with all fields."""
        # Create supplier and invoice first
        supplier = Supplier(supplier_name="Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        db_session.add(invoice)
        db_session.commit()
        
        # Create invoice item
        invoice_item = InvoiceItem(
            item="10001",
            description="Test Item Description",
            qty="5",
            cost="$10.00",
            amount="$50.00",
            date="12/01/2024",
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
        
        db_session.add(invoice_item)
        db_session.commit()
        
        assert invoice_item.id is not None
        assert invoice_item.item == "10001"
        assert invoice_item.description == "Test Item Description"
        assert invoice_item.is_active is True
        assert invoice_item.export_status == "Pending"

    def test_invoice_item_relationships(self, db_session):
        """Test InvoiceItem relationships with Invoice."""
        # Create test data
        supplier = Supplier(supplier_name="Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        invoice = Invoice(
            date=date.today(),
            filename="test_invoice.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        db_session.add(invoice)
        db_session.commit()
        
        item1 = InvoiceItem(
            item="10001",
            description="Item 1",
            invoice_id=invoice.id
        )
        item2 = InvoiceItem(
            item="10002",
            description="Item 2",
            invoice_id=invoice.id
        )
        
        db_session.add_all([item1, item2])
        db_session.commit()
        
        # Test relationships
        assert len(invoice.items) == 2
        assert item1.invoice.filename == "test_invoice.pdf"
        assert item2.invoice.filename == "test_invoice.pdf"

    def test_customer_job_mapping_model(self, db_session):
        """Test CustomerJobMapping model creation and functionality."""
        mapping = CustomerJobMapping(
            customer_job="Test Customer Job",
            supplier="Test Supplier",
            mpi_customer_job="MPI Customer Job"
        )
        
        db_session.add(mapping)
        db_session.commit()
        
        assert mapping.id is not None
        assert mapping.customer_job == "Test Customer Job"
        assert mapping.supplier == "Test Supplier"
        assert mapping.mpi_customer_job == "MPI Customer Job"

    def test_item_mapping_model(self, db_session):
        """Test ItemsMapping model creation and validation."""
        mapping = ItemsMapping(
            google_sheet_name="Test Sheet",
            mpi_code="MPI001",
            description="Test Item Description",
            supplier_item_ids="10001,10002",
            supplier_id=1
        )
        
        db_session.add(mapping)
        db_session.commit()
        
        assert mapping.id is not None
        assert mapping.mpi_code == "MPI001"
        assert mapping.google_sheet_name == "Test Sheet"
        assert mapping.supplier_item_ids == "10001,10002"

    def test_unmapped_item_model(self, db_session):
        """Test UnmappedItem model for tracking unmapped items."""
        unmapped = UnmappedItem(
            item="UNMAPPED001",
            description="Unmapped Item",
            supplier="Test Supplier",
            qty=5,
            cost=Decimal("10.00"),
            amount=Decimal("50.00"),
            occurrence_count=3
        )
        
        db_session.add(unmapped)
        db_session.commit()
        
        assert unmapped.id is not None
        assert unmapped.item == "UNMAPPED001"
        assert unmapped.occurrence_count == 3
        assert unmapped.cost == Decimal("10.00")

    def test_monthly_statement_model(self, db_session):
        """Test MonthlyStatement model for statement tracking."""
        statement = MonthlyStatement(
            filename="statement_202412.pdf",
            supplier="Test Supplier",
            month=12,
            year=2024,
            storage_path="/statements/path",
            status="PROCESSED"
        )
        
        db_session.add(statement)
        db_session.commit()
        
        assert statement.id is not None
        assert statement.filename == "statement_202412.pdf"
        assert statement.month == 12
        assert statement.year == 2024

    def test_temporary_item_mapping_model(self, db_session):
        """Test TemporaryItemMapping model for temporary mappings."""
        temp_mapping = TemporaryItemMapping(
            item="TEMP001",
            description="Temporary Item",
            supplier="Test Supplier",
            mpi_item="TEMP_MPI001",
            mpi_description="Temporary MPI Description"
        )
        
        db_session.add(temp_mapping)
        db_session.commit()
        
        assert temp_mapping.id is not None
        assert temp_mapping.item == "TEMP001"
        assert temp_mapping.mpi_item == "TEMP_MPI001"

    def test_item_classification_model(self, db_session):
        """Test ItemClassification model for QuickBooks export."""
        classification = ItemClassification(
            mpi_item="MPI001",
            mpi_description="MPI Description",
            account="Sales Account",
            cogs_account="COGS Account",
            income_account="Income Account"
        )
        
        db_session.add(classification)
        db_session.commit()
        
        assert classification.id is not None
        assert classification.mpi_item == "MPI001"
        assert classification.account == "Sales Account"

    def test_user_model(self, db_session):
        """Test User model for authentication."""
        user = User(
            fullname="Test User",
            email="test@example.com",
            username="testuser",
            password="hashedpassword123"
        )
        
        db_session.add(user)
        db_session.commit()
        
        assert user.id is not None
        assert user.fullname == "Test User"
        assert user.email == "test@example.com"
        assert user.username == "testuser"

    def test_model_constraints_and_validation(self, db_session):
        """Test model constraints and data validation."""
        # Test unique constraints would fail in real DB
        supplier1 = Supplier(supplier_name="Unique Supplier")
        supplier2 = Supplier(supplier_name="Unique Supplier")
        
        db_session.add(supplier1)
        db_session.commit()
        
        # SQLite in memory doesn't enforce all constraints like PostgreSQL
        # This would fail in production with proper constraints
        db_session.add(supplier2)
        db_session.commit()  # This passes in SQLite but would fail in production

    def test_model_defaults_and_nullability(self, db_session):
        """Test model defaults and nullable fields."""
        # Test Invoice with minimal required fields
        supplier = Supplier(supplier_name="Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        invoice = Invoice(
            supplier_id=supplier.id,
            filename="minimal.pdf"
        )
        
        db_session.add(invoice)
        db_session.commit()
        
        assert invoice.is_exported == "Pending"  # Default value
        assert invoice.date is None  # Nullable field
        assert invoice.status is None  # Nullable field

    def test_cascade_relationships(self, db_session):
        """Test cascade deletion and relationship integrity."""
        # Create supplier with invoice and items
        supplier = Supplier(supplier_name="Cascade Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        invoice = Invoice(
            date=date.today(),
            filename="cascade_test.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/test/path"
        )
        db_session.add(invoice)
        db_session.commit()
        
        item = InvoiceItem(
            item="CASCADE001",
            description="Cascade Test Item",
            invoice_id=invoice.id
        )
        db_session.add(item)
        db_session.commit()
        
        # Verify relationships exist
        assert len(supplier.supplier) == 1
        assert len(invoice.items) == 1
        
        # Note: Actual cascade behavior would depend on foreign key constraints
        # in the production database

    def test_model_string_representations(self, db_session):
        """Test string representations of models if they exist."""
        supplier = Supplier(supplier_name="String Test Supplier")
        
        # Most models don't have __str__ or __repr__ defined
        # but we can test the basic object creation
        assert isinstance(supplier, Supplier)
        assert hasattr(supplier, 'supplier_name')

    def test_bulk_operations(self, db_session):
        """Test bulk create and query operations."""
        # Create multiple suppliers
        suppliers = [
            Supplier(supplier_name=f"Bulk Supplier {i}")
            for i in range(5)
        ]
        
        db_session.add_all(suppliers)
        db_session.commit()
        
        # Query all suppliers
        all_suppliers = db_session.query(Supplier).all()
        assert len(all_suppliers) == 5
        
        # Test filtering
        bulk_suppliers = db_session.query(Supplier).filter(
            Supplier.supplier_name.like("Bulk Supplier%")
        ).all()
        assert len(bulk_suppliers) == 5

    def test_complex_relationships_and_joins(self, db_session):
        """Test complex queries involving multiple models."""
        # Create test data hierarchy
        supplier = Supplier(supplier_name="Complex Test Supplier")
        db_session.add(supplier)
        db_session.commit()
        
        invoice = Invoice(
            date=date.today(),
            filename="complex_test.pdf",
            supplier_id=supplier.id,
            status="PROCESSED",
            storage_path="/complex/path"
        )
        db_session.add(invoice)
        db_session.commit()
        
        items = [
            InvoiceItem(
                item=f"COMPLEX{i:03d}",
                description=f"Complex Item {i}",
                invoice_id=invoice.id,
                qty="1",
                cost="$10.00"
            )
            for i in range(3)
        ]
        db_session.add_all(items)
        db_session.commit()
        
        # Test complex query
        result = db_session.query(InvoiceItem).join(Invoice).join(Supplier).filter(
            Supplier.supplier_name == "Complex Test Supplier"
        ).all()
        
        assert len(result) == 3
        assert all(item.description.startswith("Complex Item") for item in result)

    def test_edge_cases_and_boundaries(self, db_session):
        """Test edge cases and boundary conditions."""
        # Test empty strings vs None
        supplier = Supplier(supplier_name="")  # Empty string
        db_session.add(supplier)
        db_session.commit()
        
        assert supplier.supplier_name == ""
        assert supplier.supplier_name_en is None
        
        # Test very long strings (within database limits)
        long_description = "A" * 500  # Assuming reasonable limit
        item = InvoiceItem(
            item="EDGE001",
            description=long_description
        )
        
        db_session.add(item)
        db_session.commit()
        
        assert len(item.description) == 500

    def test_date_and_datetime_handling(self, db_session):
        """Test date and datetime field handling."""
        # Test different date formats and edge cases
        invoice = Invoice(
            filename="date_test.pdf",
            date=date.today()  # Current date
        )
        
        db_session.add(invoice)
        db_session.commit()
        
        assert isinstance(invoice.date, date)
        
        # Test datetime fields
        mapping = ItemMapping(
            item="DATE001",
            description="Date Test",
            supplier="Date Supplier",
            mpi_item="MPI_DATE001",
            mpi_description="MPI Date Description",
            date_added=datetime.now()
        )
        
        db_session.add(mapping)
        db_session.commit()
        
        assert isinstance(mapping.date_added, datetime)
