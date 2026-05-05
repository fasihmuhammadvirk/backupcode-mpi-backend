"""
Test data factories for invoice-related entities.

Provides reusable test data builders for invoices and invoice items.
"""

from datetime import date, datetime
from typing import Optional, Dict, Any
from uuid import uuid4, UUID


class InvoiceItemFactory:
    """Factory for creating test invoice item data."""
    
    @staticmethod
    def create(
        id: Optional[int] = None,
        invoice_id: Optional[str] = None,
        filename: str = "test_invoice.xlsx",
        sheet_name: str = "Sheet1",
        mpi_item: str = "TEST-001",
        mpi_description: str = "Test Item Description",
        item: str = "TEST-001",
        description: str = "Test Item Description",
        qty: int = 10,
        cost: float = 15.50,
        amount: str = "155.00",
        date: Optional[date] = None,
        ref_no: str = "REF-001",
        po_number: str = "PO-12345",
        customer_job: str = "Test Site A",
        bill: str = "BILL-001",
        vendor: str = "Test Vendor",
        class_: str = "Class A",
        export_status: str = "Pending",
        memo: str = "",
        buyer: str = "Test Buyer",
        date_added: Optional[date] = None,
        is_active: bool = True,
        account: str = "1000-Materials",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test invoice item.
        
        Args:
            id: Item ID
            invoice_id: Invoice UUID
            filename: Excel filename
            sheet_name: Sheet name in Excel
            mpi_item: MPI item code
            mpi_description: MPI item description
            item: Item code
            description: Item description
            qty: Quantity
            cost: Unit cost
            amount: Total amount
            date: Invoice date
            ref_no: Reference number
            po_number: PO number
            customer_job: Customer job/site
            bill: Bill number
            vendor: Vendor name
            class_: Item class
            export_status: Export status
            memo: Memo text
            buyer: Buyer name
            date_added: Date added to system
            is_active: Is active flag
            account: Account code
            **kwargs: Additional fields
            
        Returns:
            Dictionary with invoice item data
        """
        return {
            "id": id or 1,
            "invoice_id": invoice_id or str(uuid4()),
            "filename": filename,
            "sheet_name": sheet_name,
            "mpi_item": mpi_item,
            "mpi_description": mpi_description,
            "item": item,
            "description": description,
            "qty": qty,
            "cost": cost,
            "amount": amount,
            "date": date or date(2024, 7, 15),
            "ref_no": ref_no,
            "po_number": po_number,
            "customer_job": customer_job,
            "bill": bill,
            "vendor": vendor,
            "class_": class_,
            "export_status": export_status,
            "memo": memo,
            "buyer": buyer,
            "date_added": date_added or date(2024, 7, 10),
            "is_active": is_active,
            "account": account,
            **kwargs
        }
    
    @staticmethod
    def create_multiple(count: int, **base_kwargs) -> list[Dict[str, Any]]:
        """
        Create multiple invoice items with sequential IDs.
        
        Args:
            count: Number of items to create
            **base_kwargs: Base attributes for all items
            
        Returns:
            List of invoice item dictionaries
        """
        items = []
        for i in range(count):
            item_kwargs = base_kwargs.copy()
            item_kwargs['id'] = i + 1
            item_kwargs['mpi_item'] = item_kwargs.get('mpi_item', f'TEST-{i+1:03d}')
            items.append(InvoiceItemFactory.create(**item_kwargs))
        return items
    
    @staticmethod
    def create_with_leading_zeros_ref_no(ref_no: str = "066617", **kwargs) -> Dict[str, Any]:
        """Create invoice item with leading zeros in reference number."""
        return InvoiceItemFactory.create(ref_no=ref_no, **kwargs)
    
    @staticmethod
    def create_duplicate_detection_scenario(
        ref_no: str = "INV-001",
        vendor: str = "Test Vendor",
        date: Optional[date] = None,
        amount: str = "1000.00",
        customer_job: str = "Site A",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create invoice item for duplicate detection testing.
        
        Args:
            ref_no: Reference number
            vendor: Vendor name
            date: Invoice date
            amount: Total amount
            customer_job: Customer job
            **kwargs: Additional fields
            
        Returns:
            Invoice item dictionary
        """
        return InvoiceItemFactory.create(
            ref_no=ref_no,
            vendor=vendor,
            date=date or date(2024, 7, 15),
            amount=amount,
            customer_job=customer_job,
            **kwargs
        )


class InvoiceFactory:
    """Factory for creating test invoice data."""
    
    @staticmethod
    def create(
        id: Optional[UUID] = None,
        supplier_id: int = 1,
        filename: str = "test_invoice.pdf",
        pdf_path: str = "/path/to/test.pdf",
        excel_path: str = "/path/to/test.xlsx",
        status: str = "completed",
        ref_no: str = "REF-001",
        vendor: str = "Test Vendor",
        date: Optional[date] = None,
        total_amount: float = 1000.00,
        tax_amount: Optional[float] = None,
        created_at: Optional[datetime] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a test invoice.
        
        Args:
            id: Invoice UUID
            supplier_id: Supplier ID
            filename: PDF filename
            pdf_path: Path to PDF
            excel_path: Path to Excel
            status: Invoice status
            ref_no: Reference number
            vendor: Vendor name
            date: Invoice date
            total_amount: Total invoice amount
            tax_amount: Tax amount
            created_at: Creation timestamp
            **kwargs: Additional fields
            
        Returns:
            Dictionary with invoice data
        """
        return {
            "id": id or uuid4(),
            "supplier_id": supplier_id,
            "filename": filename,
            "pdf_path": pdf_path,
            "excel_path": excel_path,
            "status": status,
            "ref_no": ref_no,
            "vendor": vendor,
            "date": date or date(2024, 7, 15),
            "total_amount": total_amount,
            "tax_amount": tax_amount,
            "created_at": created_at or datetime.now(),
            **kwargs
        }
    
    @staticmethod
    def create_with_items(
        item_count: int = 3,
        **invoice_kwargs
    ) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
        """
        Create invoice with related items.
        
        Args:
            item_count: Number of items to create
            **invoice_kwargs: Invoice attributes
            
        Returns:
            Tuple of (invoice dict, list of item dicts)
        """
        invoice = InvoiceFactory.create(**invoice_kwargs)
        items = InvoiceItemFactory.create_multiple(
            item_count,
            invoice_id=str(invoice['id']),
            vendor=invoice['vendor'],
            ref_no=invoice['ref_no'],
            date=invoice['date']
        )
        return invoice, items


# Preset scenarios for common test cases
class InvoiceScenarios:
    """Predefined invoice scenarios for testing."""
    
    @staticmethod
    def exact_duplicate() -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Create two identical invoices for exact duplicate testing.
        
        Returns:
            Tuple of (existing invoice, new invoice)
        """
        base = InvoiceItemFactory.create_duplicate_detection_scenario(
            ref_no="INV-001",
            vendor="BMW Plumbing Supplies",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site A"
        )
        new = base.copy()
        new['id'] = 2
        return base, new
    
    @staticmethod
    def updated_invoice_different_amount() -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Create invoices with same ref/vendor/date but different amount.
        
        Returns:
            Tuple of (existing invoice, updated invoice)
        """
        existing = InvoiceItemFactory.create_duplicate_detection_scenario(
            ref_no="INV-002",
            vendor="Flow Mark",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site B"
        )
        updated = existing.copy()
        updated['id'] = 2
        updated['amount'] = "1100.00"  # Different amount
        return existing, updated
    
    @staticmethod
    def new_invoice_different_date() -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Create invoices with same ref/vendor but different date.
        
        Returns:
            Tuple of (existing invoice, new invoice)
        """
        existing = InvoiceItemFactory.create_duplicate_detection_scenario(
            ref_no="INV-003",
            vendor="Supreme Plumbing",
            date=date(2024, 7, 15),
            amount="1000.00",
            customer_job="Site C"
        )
        new = existing.copy()
        new['id'] = 2
        new['date'] = date(2024, 7, 20)  # Different date
        return existing, new
    
    @staticmethod
    def quickbooks_export_with_tax() -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
        """
        Create invoice scenario for QuickBooks export with tax testing.
        
        Returns:
            Tuple of (invoice dict, list of invoice items)
        """
        invoice = InvoiceFactory.create(
            ref_no="QB-001",
            vendor="BMW Plumbing Supplies",
            total_amount=1000.00,
            tax_amount=100.00
        )
        
        items = [
            InvoiceItemFactory.create(
                id=1,
                invoice_id=str(invoice['id']),
                mpi_item="ITEM-E1",
                description="Equipment Item 1",
                amount="100.00",
                cost=100.00,
                qty=1,
                class_="",
                account="E"
            ),
            InvoiceItemFactory.create(
                id=2,
                invoice_id=str(invoice['id']),
                mpi_item="ITEM-E2",
                description="Equipment Item 2",
                amount="200.00",
                cost=200.00,
                qty=1,
                class_="",
                account="E"
            ),
            InvoiceItemFactory.create(
                id=3,
                invoice_id=str(invoice['id']),
                mpi_item="ITEM-M1",
                description="Material Item 1",
                amount="600.00",
                cost=600.00,
                qty=1,
                class_="",
                account="M"
            ),
        ]
        
        return invoice, items

