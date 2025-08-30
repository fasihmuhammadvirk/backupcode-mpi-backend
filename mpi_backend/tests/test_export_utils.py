#!/usr/bin/env python3
"""
Test export utilities for converting and exporting invoice data.
"""
import pandas as pd
from unittest.mock import Mock
from mpi_backend.utils.export_utils import (
    convert_items_to_dataframe,
    convert_items_to_dataframe_optimized
)


class TestExportUtils:
    """Test cases for export utilities."""

    def test_convert_items_to_dataframe_basic(self):
        """Test basic DataFrame conversion."""
        # Mock invoice items
        mock_items = [
            Mock(
                item="ITEM001",
                description="Test Item 1",
                qty=5,
                cost=10.50,
                amount="52.50",
                date="2024-01-01",
                ref_no="REF001",
                po_number="PO001",
                customer_job="Job1",
                bill="Bill1",
                vendor="Vendor1",
                class_="Class1",
                account="Account1",
                memo="Memo1",
                buyer="Buyer1",
                filename="test.pdf",
                sheet_name="Sheet1",
                mpi_item="MPI001",
                mpi_description="MPI Desc 1",
                date_added="2024-01-01"
            ),
            Mock(
                item="ITEM002",
                description="Test Item 2",
                qty=3,
                cost=15.00,
                amount="45.00",
                date="2024-01-01",
                ref_no="REF002",
                po_number="PO002",
                customer_job="Job2",
                bill="Bill2",
                vendor="Vendor2",
                class_="Class2",
                account="Account2",
                memo="Memo2",
                buyer="Buyer2",
                filename="test.pdf",
                sheet_name="Sheet1",
                mpi_item="MPI002",
                mpi_description="MPI Desc 2",
                date_added="2024-01-01"
            )
        ]

        # Set up the __dict__ attribute for each mock
        for item in mock_items:
            item.__dict__ = {
                'item': item.item,
                'description': item.description,
                'qty': item.qty,
                'cost': item.cost,
                'amount': item.amount,
                'date': item.date,
                'ref_no': item.ref_no,
                'po_number': item.po_number,
                'customer_job': item.customer_job,
                'bill': item.bill,
                'vendor': item.vendor,
                'class_': item.class_,
                'account': item.account,
                'memo': item.memo,
                'buyer': item.buyer,
                'filename': item.filename,
                'sheet_name': item.sheet_name,
                'mpi_item': item.mpi_item,
                'mpi_description': item.mpi_description,
                'date_added': item.date_added
            }

        df = convert_items_to_dataframe(mock_items)
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert 'Item' in df.columns
        assert 'Description' in df.columns
        assert 'Cost' in df.columns
        assert 'Amount' in df.columns

    def test_convert_items_to_dataframe_empty_list(self):
        """Test DataFrame conversion with empty item list."""
        df = convert_items_to_dataframe([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_convert_items_to_dataframe_with_none_values(self):
        """Test DataFrame conversion with None values."""
        mock_item = Mock()
        mock_item.__dict__ = {
            'item': "ITEM001",
            'description': None,
            'qty': None,
            'cost': None,
            'amount': None,
            'date': None,
            'ref_no': None,
            'po_number': None,
            'customer_job': None,
            'bill': None,
            'vendor': None,
            'class_': None,
            'account': None,
            'memo': None,
            'buyer': None,
            'filename': None,
            'sheet_name': None,
            'mpi_item': None,
            'mpi_description': None,
            'date_added': None
        }

        df = convert_items_to_dataframe([mock_item])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df.iloc[0]['Description'] is None

    async def test_convert_items_to_dataframe_optimized_basic(self):
        """Test optimized DataFrame conversion."""
        # Mock SQLAlchemy ORM query behavior
        mock_query = Mock()
        # Mock results as tuples (like SQLAlchemy ORM returns)
        mock_results = [
            ('ITEM001', 'Test Item 1', 5, 10.50, '52.50'),
            ('ITEM002', 'Test Item 2', 3, 15.00, '45.00')
        ]
        mock_query.all.return_value = mock_results
        
        mock_db_session = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query

        df = await convert_items_to_dataframe_optimized(
            mock_db_session, 
            [1, 2], 
            ['item', 'description', 'qty', 'cost', 'amount']
        )
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert 'Item' in df.columns
        assert 'Description' in df.columns

    async def test_convert_items_to_dataframe_optimized_empty_ids(self):
        """Test optimized conversion with empty ID list."""
        mock_db_session = Mock()
        df = await convert_items_to_dataframe_optimized(mock_db_session, [])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    async def test_convert_items_to_dataframe_optimized_no_columns(self):
        """Test optimized conversion without specifying columns."""
        # Mock SQLAlchemy ORM query behavior
        mock_query = Mock()
        mock_results = [
            ('ITEM001', 'Test Item 1', 5, 10.50, '52.50')
        ]
        mock_query.all.return_value = mock_results
        
        mock_db_session = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        df = await convert_items_to_dataframe_optimized(mock_db_session, [1])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    def test_convert_items_to_dataframe_use_suffix_parameter(self):
        """Test that use_suffix parameter is handled (deprecated but supported)."""
        mock_items = [
            Mock(
                item="ITEM001",
                description="Test Item",
                qty=1,
                cost=10.00,
                amount="10.00"
            )
        ]

        # Set up the __dict__ attribute
        for item in mock_items:
            item.__dict__ = {
                'item': item.item,
                'description': item.description,
                'qty': item.qty,
                'cost': item.cost,
                'amount': item.amount
            }

        # Test with both True and False (should work the same now)
        df1 = convert_items_to_dataframe(mock_items, use_suffix=True)
        df2 = convert_items_to_dataframe(mock_items, use_suffix=False)
        
        assert df1.equals(df2)

    def test_convert_items_to_dataframe_column_mapping(self):
        """Test that column mapping is applied correctly."""
        mock_item = Mock()
        mock_item.__dict__ = {
            'item': "ITEM001",
            'description': "Test Description",
            'qty': 5,
            'cost': 10.00,
            'amount': "50.00"
        }

        df = convert_items_to_dataframe([mock_item])
        
        # Check that internal names are mapped to display names
        assert 'Item' in df.columns  # maps from 'item'
        assert 'Description' in df.columns  # maps from 'description'
        assert 'Qty' in df.columns  # maps from 'qty'
        assert 'Cost' in df.columns  # maps from 'cost'
        # maps from 'amount'
        assert 'Amount' in df.columns

    def test_convert_items_to_dataframe_missing_columns(self):
        """Test handling of missing columns in data."""
        mock_item = Mock()
        mock_item.__dict__ = {
            'item': "ITEM001",
            'description': "Test Description"
            # Missing other fields
        }

        df = convert_items_to_dataframe([mock_item])
        
        # Should only include columns that exist
        assert 'Item' in df.columns
        assert 'Description' in df.columns
        assert len(df.columns) == 2

    async def test_convert_items_to_dataframe_optimized_with_order_by(self):
        """Test optimized conversion with order_by parameter."""
        # Mock SQLAlchemy ORM query behavior
        mock_query = Mock()
        mock_results = [
            ('ITEM001', 'Test Item')
        ]
        mock_query.all.return_value = mock_results
        
        mock_db_session = Mock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query

        # Mock OrderByFilter objects with proper attributes
        mock_order_by = [Mock()]
        mock_order_by[0].column = 'item'
        mock_order_by[0].order = 'asc'
        
        df = await convert_items_to_dataframe_optimized(
            mock_db_session, 
            [1], 
            order_by=mock_order_by
        )
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
