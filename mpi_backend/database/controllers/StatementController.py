import os
import sys
from datetime import datetime, date
from calendar import monthrange
from typing import List, Optional, Dict, Any, Generator
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, select
from math import ceil
import pandas as pd
# Setup temporary directory for reprocessing
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
import requests
import re
from pathlib import Path
import logging

from mpi_backend.database.models.MonthlyStatement import (
    PlumbingSupplier, PlumbingStatement, PlumbingInvoice
)
from mpi_backend.database.models.Invoice import Invoice
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.utils.number_formatter import format_currency

# Query type constants
QUERY_TYPE_PROCESSED_FAILED: str = 'processed_failed'
QUERY_TYPE_UNLISTED: str = 'unlisted'
QUERY_TYPE_MISSING: str = 'missing'
QUERY_TYPE_ALL_COMBINED: str = 'all_combined'

# Status constants
STATUS_ALL: str = "all"
STATUS_PROCESSED: str = "processed"
STATUS_FAILED: str = "failed"
STATUS_UNLISTED: str = "unlisted"
STATUS_MISSING: str = "missing"
STATUS_MISSING_SYSTEM: str = "missing system"
STATUS_MISSING_STATEMENT: str = "missing statement"

# Invoice constants
INVOICE_NUMBER_MISSING: str = "MISSING"

logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class StatementController:
    """Controller for managing statement operations and reconciliation"""

    def __init__(self, db: Session):
        self.db = db

    def get_supplier_by_name_or_id(self, supplier: str) -> Optional[PlumbingSupplier]:
        """Get supplier by name or ID"""
        try:
            # Try to get by ID first
            if supplier.isdigit():
                supplier_obj = self.db.query(PlumbingSupplier).filter(
                    PlumbingSupplier.id == int(supplier)
                ).first()
                if supplier_obj:
                    return supplier_obj

            # Try to get by name
            return self.db.query(PlumbingSupplier).filter(
                PlumbingSupplier.name.ilike(f"%{supplier}%")
            ).first()

        except Exception as e:
            logger.error(f"Error getting supplier: {str(e)}")
            return None

    def get_statements_in_date_range(
        self,
        supplier_id: int,
        from_date: date,
        to_date: date
    ) -> List[PlumbingStatement]:
        """Get statements for a supplier within date range"""
        try:
            return self.db.query(PlumbingStatement).filter(
                and_(
                    PlumbingStatement.supplier_id == supplier_id,
                    PlumbingStatement.statement_date >= from_date,
                    PlumbingStatement.statement_date <= to_date
                )
            ).order_by(PlumbingStatement.statement_date.desc()).all()

        except Exception as e:
            logger.error(f"Error getting statements in date range: {str(e)}")
            return []

    def get_statement_invoices(self, statement_id: int) -> List[PlumbingInvoice]:
        """Get all invoices for a specific statement"""
        try:
            return self.db.query(PlumbingInvoice).filter(
                PlumbingInvoice.statement_id == statement_id
            ).all()

        except Exception as e:
            logger.error(f"Error getting statement invoices: {str(e)}")
            return []

    def check_invoice_exists_in_system(
        self,
        invoice_number: str,
        supplier_id: int,
        invoice_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Check if an invoice exists in our system
        Returns dict with status and details
        """
        try:
            # First check in InvoiceItem table (main system invoices)
            query = self.db.query(InvoiceItem).join(Invoice).filter(
                and_(
                    InvoiceItem.ref_no == invoice_number,
                    Invoice.supplier_id == supplier_id
                )
            )

            # Add date filter if provided (within reasonable range)
            if invoice_date:
                date_start = datetime.combine(
                    invoice_date, datetime.min.time())
                date_end = datetime.combine(invoice_date, datetime.max.time())
                query = query.filter(
                    InvoiceItem.date.between(date_start, date_end)
                )

            system_invoice = query.first()

            if system_invoice:
                return {
                    'status': 'Found',
                    'matched': True,
                    'system_invoice_id': str(system_invoice.invoice_id),
                    'system_ref_no': system_invoice.ref_no,
                    'system_date': system_invoice.date,
                    'system_amount': str(system_invoice.amount) if system_invoice.amount else "0",
                    'customer_job': system_invoice.customer_job,
                    'export_status': system_invoice.export_status
                }
            else:
                return {
                    'status': 'Not Found',
                    'matched': False,
                    'system_invoice_id': None,
                    'system_ref_no': None,
                    'system_date': None,
                    'system_amount': None,
                    'customer_job': None,
                    'export_status': None
                }

        except Exception as e:
            logger.error(f"Error checking invoice existence: {str(e)}")
            return {
                'status': 'Error',
                'matched': False,
                'error': str(e)
            }

    def reconcile_statement_with_system(
        self,
        supplier: str,
        from_date: str,
        to_date: str,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main reconciliation method that compares statement invoices with system invoices

        Args:
            supplier: Supplier name or ID
            from_date: Start date in MM/YYYY format
            to_date: End date in MM/YYYY format  
            status: Optional filter for invoice status

        Returns:
            Dict with reconciliation results
        """
        try:
            # Parse dates from MM/YYYY format
            from_month, from_year = map(int, from_date.split('/'))
            to_month, to_year = map(int, to_date.split('/'))

            from_date_obj = date(from_year, from_month, 1)
            # Get last day of to_month
            if to_month == 12:
                to_date_obj = date(to_year + 1, 1, 1)
            else:
                to_date_obj = date(to_year, to_month + 1, 1)

            # Get supplier
            supplier_obj = self.get_supplier_by_name_or_id(supplier)
            if not supplier_obj:
                return {
                    'success': False,
                    'error': f'Supplier not found: {supplier}'
                }

            # Get statements in date range
            statements = self.get_statements_in_date_range(
                supplier_obj.id, from_date_obj, to_date_obj
            )

            if not statements:
                return {
                    'success': False,
                    'error': f'No statements found for {supplier_obj.name} in the specified date range'
                }

            # Process each statement
            reconciliation_results = []
            overall_stats = {
                'total_statements': len(statements),
                'total_statement_invoices': 0,
                'matched_invoices': 0,
                'unmatched_invoices': 0,
                'total_statement_amount': 0.0,
                'total_matched_amount': 0.0
            }

            for statement in statements:
                statement_invoices = self.get_statement_invoices(statement.id)
                statement_result = {
                    'statement_id': statement.id,
                    'statement_date': statement.statement_date.isoformat() if statement.statement_date else None,
                    'account_number': statement.account_number,
                    'total_amount': str(statement.total_amount) if statement.total_amount else "0",
                    'total_invoices': len(statement_invoices),
                    'pdf_filename': statement.pdf_filename,
                    'invoices': []
                }

                overall_stats['total_statement_invoices'] += len(
                    statement_invoices)
                # Convert to float only for calculation, keep string for output
                stmt_amount = float(
                    statement.total_amount) if statement.total_amount else 0.0
                overall_stats['total_statement_amount'] += stmt_amount

                # Check each invoice in the statement
                for stmt_invoice in statement_invoices:
                    # Apply status filter if provided
                    if status and status.lower() != STATUS_ALL:
                        # We'll determine status based on matching
                        pass

                    # Check if invoice exists in system
                    match_result = self.check_invoice_exists_in_system(
                        stmt_invoice.invoice_number,
                        supplier_obj.id,
                        stmt_invoice.invoice_date
                    )

                    invoice_result = {
                        'statement_invoice_id': stmt_invoice.id,
                        'invoice_number': stmt_invoice.invoice_number,
                        'invoice_date': stmt_invoice.invoice_date.isoformat() if stmt_invoice.invoice_date else None,
                        'customer_po': stmt_invoice.customer_po,
                        'original_amount': str(stmt_invoice.original_amount) if stmt_invoice.original_amount else "0",
                        'payment_date': stmt_invoice.payment_date.isoformat() if stmt_invoice.payment_date else None,
                        'amount_paid': str(stmt_invoice.amount_paid) if stmt_invoice.amount_paid else "0",
                        'balance': str(stmt_invoice.balance) if stmt_invoice.balance else "0",
                        'reconciliation_status': 'Processed' if match_result['matched'] else 'Failed',
                        'match_details': match_result
                    }

                    # Apply status filter
                    if status and status.lower() != STATUS_ALL:
                        if status.lower() == STATUS_PROCESSED and not match_result['matched']:
                            continue
                        elif status.lower() == STATUS_FAILED and match_result['matched']:
                            continue

                    statement_result['invoices'].append(invoice_result)

                    # Update stats
                    if match_result['matched']:
                        overall_stats['matched_invoices'] += 1
                        # Convert to float only for calculation
                        matched_amount = float(
                            stmt_invoice.original_amount) if stmt_invoice.original_amount else 0.0
                        overall_stats['total_matched_amount'] += matched_amount
                    else:
                        overall_stats['unmatched_invoices'] += 1

                reconciliation_results.append(statement_result)

            return {
                'success': True,
                'supplier': {
                    'id': supplier_obj.id,
                    'name': supplier_obj.name
                },
                'date_range': {
                    'from_date': from_date,
                    'to_date': to_date,
                    'from_date_parsed': from_date_obj.isoformat(),
                    'to_date_parsed': to_date_obj.isoformat()
                },
                'statistics': overall_stats,
                'statements': reconciliation_results
            }

        except ValueError as e:
            return {
                'success': False,
                'error': f'Invalid date format. Use MM/YYYY format: {str(e)}'
            }
        except Exception as e:
            logger.error(f"Error in reconciliation: {str(e)}")
            return {
                'success': False,
                'error': f'Reconciliation failed: {str(e)}'
            }

    def get_all_suppliers(self) -> List[PlumbingSupplier]:
        """Get all active statement suppliers"""
        try:
            return self.db.query(PlumbingSupplier).filter(
                PlumbingSupplier.is_active == "Active"
            ).order_by(PlumbingSupplier.name).all()

        except Exception as e:
            logger.error(f"Error getting suppliers: {str(e)}")
            return []

    def get_statements_summary(
        self,
        supplier_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get summary of recent statements"""
        try:
            query = self.db.query(PlumbingStatement).join(PlumbingSupplier)

            if supplier_id is not None:
                query = query.filter(
                    PlumbingStatement.supplier_id == supplier_id)

            statements = query.order_by(
                PlumbingStatement.statement_date.desc()
            ).limit(limit).all()

            return [
                {
                    'id': stmt.id,
                    'supplier_name': stmt.supplier.name,
                    'statement_date': stmt.statement_date.isoformat() if stmt.statement_date else None,
                    'total_amount': format_currency(stmt.total_amount) if stmt.total_amount else format_currency(0.0),
                    'total_invoices': stmt.total_invoices,
                    'account_number': stmt.account_number,
                    'pdf_filename': stmt.pdf_filename
                }
                for stmt in statements
            ]

        except Exception as e:
            logger.error(f"Error getting statements summary: {str(e)}")
            return []

    def get_statement_invoice_data(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        Get statement invoice data with filters and pagination

        Status filtering logic:
        - Processed: PlumbingInvoice records that exist in InvoiceItem (matched)
        - Failed: PlumbingInvoice records that don't exist in InvoiceItem (unmatched)
        - Unlisted: InvoiceItem records that don't exist in PlumbingInvoice
        - Missing: Invoices with validation issues (as is)
        - All: Combined data from Unlisted, Missing, Failed, and Processed
        """
        try:
            from mpi_backend.database.models.InvoiceItems import InvoiceItem
            from mpi_backend.database.models.Invoice import Invoice

            # Handle special status filters BEFORE executing query
            if status and status.lower() == STATUS_UNLISTED:
                return self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
            if status and (status.lower() == STATUS_MISSING or
                           status.lower() == STATUS_MISSING_SYSTEM or
                           status.lower() == STATUS_MISSING_STATEMENT):
                return self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
            if status and status.lower() == STATUS_ALL:
                return self.get_all_invoices_combined(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )

            # For Processed/Failed status: Compare PlumbingInvoice with InvoiceItem
            # Build base query joining all necessary tables
            query = (
                self.db.query(
                    PlumbingInvoice,
                    PlumbingStatement,
                    PlumbingSupplier,
                    InvoiceItem.id.label('system_invoice_id')
                )
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                .outerjoin(
                    InvoiceItem,
                    (InvoiceItem.ref_no == PlumbingInvoice.invoice_number) &
                    (InvoiceItem.date == PlumbingInvoice.invoice_date) &
                    (InvoiceItem.vendor == PlumbingSupplier.name)
                )
                .order_by(PlumbingInvoice.invoice_number.asc(), PlumbingInvoice.invoice_date.desc())
            )

            # Apply date filters for statement invoices by statement_date (month/year only)
            normalized_from = (
                date(from_date.year, from_date.month, 1) if from_date else None
            )
            normalized_to = (
                date(
                    to_date.year,
                    to_date.month,
                    monthrange(to_date.year, to_date.month)[1]
                ) if to_date else None
            )

            if normalized_from:
                query = query.filter(
                    PlumbingStatement.statement_date >= normalized_from
                )
            if normalized_to:
                query = query.filter(
                    PlumbingStatement.statement_date <= normalized_to
                )

            # Apply supplier filter - support ["All"], multiple supplier IDs, or supplier names
            if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    # Check if None or empty string - means "all suppliers"
                    if supplier_name is None or supplier_name == '':
                        supplier_conditions = []
                        break
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Note: 0 is a valid supplier_id (Unknown Supplier)
                        supplier_conditions.append(
                            PlumbingSupplier.id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )
                if supplier_conditions:
                    query = query.filter(or_(*supplier_conditions))

            # Execute query and filter by status
            all_results = query.all()
            filtered_results = []
            seen_keys = set()
            for plumbing_invoice, plumbing_statement, plumbing_supplier, system_invoice_id in all_results:
                # Determine status: Processed if exists in InvoiceItem, Failed if not
                reconciliation_status = "Processed" if system_invoice_id else "Failed"
                # Unique key for deduplication
                key = (plumbing_invoice.invoice_number,
                       plumbing_supplier.name, plumbing_invoice.invoice_date)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                # Apply status filter
                if status and status.lower() != STATUS_ALL:
                    if status.lower() == STATUS_PROCESSED and not system_invoice_id:
                        continue  # Skip if looking for processed but invoice doesn't exist in InvoiceItem
                    elif status.lower() == STATUS_FAILED and system_invoice_id:
                        continue  # Skip if looking for failed but invoice exists in InvoiceItem
                filtered_results.append({
                    'plumbing_invoice': plumbing_invoice,
                    'plumbing_statement': plumbing_statement,
                    'plumbing_supplier': plumbing_supplier,
                    'status': reconciliation_status
                })
            # Stable sort: by invoice_date desc, then invoice_number asc, then supplier_name asc
            filtered_results.sort(
                key=lambda x: (
                    -(
                        (x['plumbing_invoice'].invoice_date or date.min).toordinal()
                    ),
                    x['plumbing_invoice'].invoice_number or '',
                    x['plumbing_supplier'].name or ''
                )
            )
            # Apply pagination
            total_count = len(filtered_results)
            offset = (page - 1) * page_size
            paginated_results = filtered_results[offset:offset + page_size]
            # Format results
            invoice_data = []
            for result in paginated_results:
                plumbing_invoice = result['plumbing_invoice']
                plumbing_statement = result['plumbing_statement']
                plumbing_supplier = result['plumbing_supplier']
                reconciliation_status = result['status']
                invoice_data.append({
                    'invoice_number': plumbing_invoice.invoice_number,
                    'invoice_date': (
                        plumbing_invoice.invoice_date.isoformat()
                        if plumbing_invoice.invoice_date else None
                    ),
                    'customer_po': plumbing_invoice.customer_po,
                    'statement_date': (
                        plumbing_statement.statement_date.isoformat()
                        if plumbing_statement.statement_date else None
                    ),
                    'supplier_name': plumbing_supplier.name,
                    'status': reconciliation_status,
                    'original_amount': (
                        format_currency(plumbing_invoice.original_amount)
                        if plumbing_invoice.original_amount else format_currency(0.0)
                    ),
                    'balance': (
                        format_currency(plumbing_invoice.balance)
                        if plumbing_invoice.balance else format_currency(0.0)
                    ),
                    'statement_id': plumbing_statement.id,
                    'invoice_id': plumbing_invoice.id
                })
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1
            return {
                'success': True,
                'data': invoice_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'status': status,
                    'supplier_filter_type': (
                        STATUS_ALL if supplier_names and len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL
                        else 'multiple' if supplier_names and len(supplier_names) > 1
                        else 'single'
                    )
                }
            }

        except Exception as e:
            logger.error(f"Error getting statement invoice data: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'data': [],
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': 0,
                    'total_pages': 0,
                    'has_next': False,
                    'has_previous': False
                }
            }

    def get_statement_by_id(self, statement_id: int) -> Optional[Dict[str, Any]]:
        """
        Get statement by ID with supplier information for PDF download

        Args:
            statement_id: ID of the statement

        Returns:
            Dict with statement and supplier info, or None if not found
        """
        try:
            result = (
                self.db.query(PlumbingStatement, PlumbingSupplier)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                .filter(PlumbingStatement.id == statement_id)
                .first()
            )

            if not result:
                return None

            statement, supplier = result

            return {
                'statement_id': statement.id,
                'supplier_name': supplier.name,
                'statement_date': (
                    statement.statement_date.isoformat()
                    if statement.statement_date else None
                ),
                'account_number': statement.account_number,
                'total_amount': (
                    float(statement.total_amount)
                    if statement.total_amount else 0.0
                ),
                'total_invoices': statement.total_invoices,
                'pdf_filename': statement.pdf_filename
            }

        except Exception as e:
            logger.error(
                f"Error getting statement by ID {statement_id}: {str(e)}")
            return None

    def reprocess_statement(self, statement_id: int) -> Dict[str, Any]:
        """
        Reprocess a statement by downloading PDF from S3 and re-extracting data

        Args:
            statement_id: ID of the statement to reprocess

        Returns:
            Dict with success status and details
        """
        try:
            # Get statement details
            statement_info = self.get_statement_by_id(statement_id)
            if not statement_info:
                return {
                    'success': False,
                    'error': f'Statement with ID {statement_id} not found'
                }

            logger.info(f"Starting reprocessing of statement {statement_id}")

            # Get the statement PDF from S3
            pdf_filename = statement_info['pdf_filename']
            if not pdf_filename:
                return {
                    'success': False,
                    'error': f'No PDF file associated with statement {statement_id}'
                }

            # Generate S3 key for statement PDF
            # Statements are stored with .pdf extension due to is_invoice=True
            s3_key = f"statements/{pdf_filename}"
            logger.info(f"Generated S3 key for reprocessing: {s3_key}")

            try:
                from mpi_backend.utils.s3_utils import get_presigned_url

                # Use the same simple approach as the download endpoint
                # This ensures consistency between viewing and reprocessing
                statement_url = get_presigned_url(
                    file_key=s3_key,
                    expiration_time=600,  # 10 minutes for reprocessing
                    is_invoice=True
                )

                if not statement_url:
                    logger.error(
                        f"Failed to generate presigned URL for {s3_key}")

                    # Try to check if the file exists in S3 to provide better error message
                    try:
                        import boto3
                        from mpi_backend.config import AWS_SERVER_PUBLIC_KEY, AWS_SERVER_SECRET_KEY, REGION, BUCKET_NAME

                        s3_client = boto3.client(
                            's3',
                            aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
                            aws_secret_access_key=AWS_SERVER_SECRET_KEY,
                            region_name=REGION
                        )

                        try:
                            s3_client.head_object(
                                Bucket=BUCKET_NAME, Key=s3_key)
                            logger.error(
                                f"File exists in S3 but presigned URL generation failed for key: {s3_key}")
                            return {
                                'success': False,
                                'error': f'S3 file exists but could not generate download URL. This might be a permissions issue. S3 key: {s3_key}'
                            }
                        except s3_client.exceptions.NoSuchKey:
                            logger.error(
                                f"File does not exist in S3. S3 key: {s3_key}")
                            return {
                                'success': False,
                                'error': f'Statement PDF file not found in S3. The file may have been deleted or never uploaded. S3 key: {s3_key}'
                            }
                        except Exception as s3_error:
                            logger.error(f"S3 check failed: {str(s3_error)}")
                            return {
                                'success': False,
                                'error': f'Could not verify S3 file existence. S3 key: {s3_key}. Error: {str(s3_error)}'
                            }
                    except Exception as config_error:
                        logger.error(
                            f"Failed to initialize S3 client: {str(config_error)}")
                        return {
                            'success': False,
                            'error': f'Could not generate download URL for statement PDF: {s3_key}. S3 client error: {str(config_error)}'
                        }

                logger.info(
                    f"Successfully generated presigned URL for key: {s3_key}")

            except Exception as e:
                logger.error(
                    f"Failed to get presigned URL for {s3_key}: {str(e)}")
                return {
                    'success': False,
                    'error': f'Could not access statement PDF: {str(e)}'
                }

            # Create temporary folder
            temp_dir = Path(INVOICE_DOWNLOAD_FOLDER) / \
                "temp_reprocess" / f"statement_{statement_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Download the PDF file
            pdf_path = temp_dir / pdf_filename

            try:
                # Add retry logic for download
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = requests.get(
                            statement_url, timeout=60)  # Increased timeout
                        if response.status_code == 200:
                            with open(pdf_path, 'wb') as f:
                                f.write(response.content)
                            logger.info(
                                f"Downloaded PDF to {pdf_path} (attempt {attempt + 1})")
                            break
                        elif response.status_code == 404:
                            logger.error(
                                f"PDF not found on S3 (404) - URL may be expired or file doesn't exist")
                            return {
                                'success': False,
                                'error': f'PDF not found on S3 (404). The file may not exist or the URL has expired. S3 key: {s3_key}'
                            }
                        else:
                            logger.warning(
                                f"Download attempt {attempt + 1} failed with status {response.status_code}")
                            if attempt == max_retries - 1:
                                return {
                                    'success': False,
                                    'error': f'Failed to download PDF after {max_retries} attempts. Last status: {response.status_code}'
                                }
                    except requests.exceptions.Timeout:
                        logger.warning(
                            f"Download attempt {attempt + 1} timed out")
                        if attempt == max_retries - 1:
                            return {
                                'success': False,
                                'error': f'Download timed out after {max_retries} attempts'
                            }
                    except Exception as download_error:
                        logger.warning(
                            f"Download attempt {attempt + 1} failed: {str(download_error)}")
                        if attempt == max_retries - 1:
                            return {
                                'success': False,
                                'error': f'Failed to download PDF: {str(download_error)}'
                            }

            except Exception as e:
                logger.error(f"Failed to download PDF: {str(e)}")
                return {
                    'success': False,
                    'error': f'Failed to download PDF: {str(e)}'
                }

            # Delete existing statement and invoice records
            logger.info(
                f"Deleting existing records for statement {statement_id}")
            try:
                # Check if statement still exists (might have been deleted by another process)
                existing_statement = self.db.query(PlumbingStatement).filter(
                    PlumbingStatement.id == statement_id
                ).first()

                if not existing_statement:
                    logger.warning(
                        f"Statement {statement_id} no longer exists in database")
                    # Continue with reprocessing - we'll create a new statement
                else:
                    # Delete associated invoices first (foreign key constraint)
                    invoice_count = self.db.query(PlumbingInvoice).filter(
                        PlumbingInvoice.statement_id == statement_id
                    ).count()

                    self.db.query(PlumbingInvoice).filter(
                        PlumbingInvoice.statement_id == statement_id
                    ).delete()

                    # Delete the statement
                    statement_deleted = self.db.query(PlumbingStatement).filter(
                        PlumbingStatement.id == statement_id
                    ).delete()

                    if not statement_deleted:
                        logger.warning(
                            f"Statement {statement_id} was already deleted")
                    else:
                        logger.info(
                            f"Deleted statement {statement_id} and {invoice_count} associated invoices")

                self.db.commit()

            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to delete existing records: {str(e)}")
                return {
                    'success': False,
                    'error': f'Failed to delete existing records: {str(e)}'
                }

            # Re-extract and process the statement
            logger.info(f"Re-extracting data from {pdf_path}")
            try:
                from mpi_backend.utils.statement_processing.extractor import StatementExtractor

                # FRESH SUPPLIER DETECTION: Don't use old (potentially wrong) supplier
                # Instead, let the system re-detect supplier from filename and PDF
                old_supplier_name = statement_info['supplier_name']
                logger.info(
                    f" REPROCESSING: Old supplier was: {old_supplier_name}")
                logger.info(
                    f" FRESH DETECTION: Re-detecting supplier from filename and PDF content...")

                # Try to detect supplier from filename first (using our improved logic)
                filename_detected_supplier = self._detect_supplier_from_filename(
                    pdf_filename)
                if filename_detected_supplier:
                    logger.info(
                        f" Filename detected supplier: {filename_detected_supplier}")
                else:
                    logger.warning(
                        f"  Could not detect supplier from filename: {pdf_filename}")

                # Create extractor with the new unified interface
                extractor = StatementExtractor(
                    pdf_path=str(pdf_path),
                    # Use filename-detected or None for PDF detection
                    supplier_name=filename_detected_supplier
                )

                # Extract data using the new unified method
                result = extractor.extract_full_statement()

                if result['invoice_data'].empty:
                    logger.error(
                        f"No invoice data extracted from PDF: {pdf_path}")
                    return {
                        'success': False,
                        'error': 'Failed to extract invoice data from PDF. The PDF might be corrupted, empty, or in an unsupported format.'
                    }

                logger.info(
                    f"Successfully extracted {len(result['invoice_data'])} invoices from PDF")

                # Get detected supplier from metadata
                detected_supplier = result['metadata'].get('supplier_name', '')
                logger.info(f" FINAL DETECTED SUPPLIER: {detected_supplier}")

                # Compare with old assignment
                if old_supplier_name != detected_supplier:
                    logger.warning(f" SUPPLIER CHANGE DETECTED!")
                    logger.warning(f"   OLD: {old_supplier_name}")
                    logger.warning(f"   NEW: {detected_supplier}")
                    logger.warning(
                        f"   This indicates the previous assignment was incorrect!")
                else:
                    logger.info(
                        f" Supplier assignment confirmed: {detected_supplier}")

                final_supplier_name = detected_supplier

                # Save to database using the new unified method
                # Note: The new extractor doesn't have save_to_database method, so we need to implement it
                # For now, we'll create the database records manually
                try:
                    # Get or create supplier
                    supplier = self.db.query(PlumbingSupplier).filter(
                        PlumbingSupplier.name == final_supplier_name
                    ).first()

                    if not supplier:
                        logger.error(
                            f"Supplier {final_supplier_name} not found in database")
                        return {
                            'success': False,
                            'error': f'Supplier {final_supplier_name} not found in database'
                        }

                    # Create new statement

                    new_statement = PlumbingStatement(
                        supplier_id=supplier.id,
                        statement_date=result['metadata'].get(
                            'statement_date'),
                        account_number=result['metadata'].get(
                            'account_number', ''),
                        total_amount=result['total_amount'],
                        total_invoices=result['total_invoices'],
                        pdf_filename=pdf_filename
                    )

                    self.db.add(new_statement)
                    self.db.flush()  # Get the statement ID

                    # Create invoice records
                    for _, row in result['invoice_data'].iterrows():
                        invoice = PlumbingInvoice(
                            statement_id=new_statement.id,
                            invoice_number=str(row['Invoice Number']) if pd.notna(
                                row['Invoice Number']) else None,
                            invoice_date=row.get('Invoice Date'),
                            customer_po=str(row.get('Customer PO', '')) if pd.notna(
                                row.get('Customer PO')) else None,
                            original_amount=row.get('Original Inv Amount'),
                            payment_date=row.get('Payment Date'),
                            amount_paid=row.get('Amount Paid'),
                            balance=row.get('Invoice Balance')
                        )
                        self.db.add(invoice)

                    self.db.commit()

                    new_statement_id = new_statement.id
                    new_invoice_count = result['total_invoices']

                except Exception as db_error:
                    self.db.rollback()
                    logger.error(
                        f"Failed to save to database: {str(db_error)}")
                    logger.error(
                        f"Database error details: {type(db_error).__name__}: {str(db_error)}")
                    return {
                        'success': False,
                        'error': f'Failed to save to database: {str(db_error)}. Please check if the supplier exists and the data format is correct.'
                    }

                logger.info(
                    f"Successfully reprocessed statement. New ID: {new_statement_id}, Invoices: {new_invoice_count}")

                # Clean up temporary files
                try:
                    import shutil
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to clean up {temp_dir}: {str(cleanup_error)}")

                return {
                    'success': True,
                    'message': f'Statement reprocessed successfully',
                    'details': {
                        'original_statement_id': statement_id,
                        'new_statement_id': new_statement_id,
                        'invoices_processed': new_invoice_count,
                        'supplier_name': final_supplier_name,
                        'old_supplier_name': old_supplier_name,
                        'supplier_changed': old_supplier_name != final_supplier_name,
                        'statement_date': statement_info['statement_date'],
                        'pdf_filename': pdf_filename
                    }
                }

            except Exception as e:
                logger.error(f"Error during re-extraction: {str(e)}")
                return {
                    'success': False,
                    'error': f'Error during re-extraction: {str(e)}'
                }

        except Exception as e:
            logger.error(f"Error in reprocess_statement: {str(e)}")
            return {
                'success': False,
                'error': f'Internal error: {str(e)}'
            }
        finally:
            # Ensure cleanup in case of errors
            try:
                temp_dir = Path(INVOICE_DOWNLOAD_FOLDER) / \
                    "temp_reprocess" / f"statement_{statement_id}"
                if temp_dir.exists():
                    import shutil
                    shutil.rmtree(temp_dir)
            except:
                pass

    def _get_supplier_name_safe(self, statement: PlumbingStatement) -> str:
        """Safely get supplier name from a statement, handling session issues"""
        try:
            if statement.supplier:
                return statement.supplier.name
        except Exception:
            # If we can't access supplier relationship, try to get it from database
            try:
                supplier_obj = self.db.query(PlumbingSupplier).filter(
                    PlumbingSupplier.id == statement.supplier_id
                ).first()
                if supplier_obj:
                    return supplier_obj.name
            except Exception:
                pass
        return 'Unknown'

    def _detect_supplier_from_filename(self, filename: str) -> Optional[str]:
        """
        Detect supplier from PDF filename using the same logic as statement_downloader
        This ensures consistency with the download process
        """
        try:
            # Import the function from statement_downloader
            from mpi_backend.utils.statement_downloader import extract_supplier_from_filename
            return extract_supplier_from_filename(filename)
        except Exception as e:
            logger.warning(
                f"Could not detect supplier from filename {filename}: {str(e)}")
            return None

    def delete_existing_statement(self, supplier_name: str,
                                  statement_date: datetime) -> bool:
        """Delete existing statement and its records for supplier and month"""
        try:
            # Get supplier
            supplier = self.db.query(PlumbingSupplier).filter(
                PlumbingSupplier.name == supplier_name
            ).first()

            if not supplier:
                logger.warning(
                    f"Supplier {supplier_name} not found in database")
                return False

            # Check if statement exists for this month/year
            month_start = statement_date.replace(day=1)
            if statement_date.month == 12:
                next_month = statement_date.replace(
                    year=statement_date.year + 1, month=1, day=1
                )
            else:
                next_month = statement_date.replace(
                    month=statement_date.month + 1, day=1
                )

            existing_statement = self.db.query(PlumbingStatement).filter(
                PlumbingStatement.supplier_id == supplier.id,
                PlumbingStatement.statement_date >= month_start.date(),
                PlumbingStatement.statement_date < next_month.date()
            ).first()

            if existing_statement:
                logger.info(
                    f"Found existing statement for {supplier_name} - "
                    f"{statement_date.strftime('%Y-%m')}, deleting..."
                )

                # Delete associated invoices first (foreign key constraint)
                invoice_count = self.db.query(PlumbingInvoice).filter(
                    PlumbingInvoice.statement_id == existing_statement.id
                ).count()

                self.db.query(PlumbingInvoice).filter(
                    PlumbingInvoice.statement_id == existing_statement.id
                ).delete()

                # Delete the statement
                self.db.delete(existing_statement)
                self.db.commit()

                logger.info(
                    f"Deleted statement {existing_statement.id} and "
                    f"{invoice_count} associated invoices for "
                    f"{supplier_name} - {statement_date.strftime('%Y-%m')}"
                )
                return True
            else:
                logger.debug(
                    f"No existing statement found for {supplier_name} - "
                    f"{statement_date.strftime('%Y-%m')}"
                )
                return False

        except Exception as e:
            logger.error(f"Error deleting existing statement: {str(e)}")
            self.db.rollback()
            return False

    def reprocess_all_statements(self, supplier_name: Optional[str] = None, max_statements: int = 100) -> Dict[str, Any]:
        """
        Reprocess multiple statements with optional filtering

        Args:
            supplier_name: Optional supplier name filter
            max_statements: Maximum number of statements to process

        Returns:
            Dict with success status, results, and statistics
        """
        try:
            logger.info(
                f"Starting bulk reprocessing - Supplier: {supplier_name or 'All'}, Max: {max_statements}")

            # Build query for statements to reprocess with eager loading of supplier
            query = self.db.query(PlumbingStatement).options(
                joinedload(PlumbingStatement.supplier))

            # Apply supplier filter if provided
            # Note: None or empty string means "all suppliers" (no filter)
            if supplier_name and supplier_name != '':
                if supplier_name.isdigit():
                    supplier_id = int(supplier_name)
                    # Filter by specific supplier ID (including 0 for Unknown Supplier)
                    query = query.filter(PlumbingStatement.supplier_id == supplier_id)
                else:
                    # Filter by supplier name (partial match) - need to join for this
                    query = query.join(PlumbingSupplier).filter(
                        PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                    )

            # Order by most recent first and limit
            statements = query.order_by(
                PlumbingStatement.statement_date.desc()).limit(max_statements).all()

            if not statements:
                return {
                    'success': False,
                    'error': f'No statements found for processing (Supplier: {supplier_name or "All"})'
                }

            logger.info(f"Found {len(statements)} statements to reprocess")

            # Initialize tracking
            results = []
            statistics = {
                'total_statements': len(statements),
                'successful': 0,
                'failed': 0,
                'supplier_changes': 0,  # Track supplier changes
                'errors': []
            }

            # Process each statement
            for idx, statement in enumerate(statements, 1):
                try:
                    logger.info(
                        f"Processing statement {idx}/{len(statements)} - ID: {statement.id}")

                    # Reprocess the statement
                    result = self.reprocess_statement(statement.id)

                    # Track result with proper supplier information
                    old_supplier_name = self._get_supplier_name_safe(statement)

                    statement_result = {
                        'original_id': statement.id,
                        'old_supplier_name': old_supplier_name,
                        'statement_date': statement.statement_date.isoformat() if statement.statement_date else None,
                        'success': result['success']
                    }

                    if result['success']:
                        # Get the NEW supplier information from reprocessing result
                        details = result.get('details', {})
                        new_supplier_name = details.get(
                            'supplier_name', old_supplier_name)
                        supplier_changed = details.get(
                            'supplier_changed', False)

                        statement_result.update({
                            'new_id': details.get('new_statement_id'),
                            'invoices_processed': details.get('invoices_processed'),
                            'supplier_name': new_supplier_name,  # Use NEW supplier name
                            'supplier_changed': supplier_changed
                        })

                        statistics['successful'] += 1

                        # Track supplier changes
                        if supplier_changed:
                            statistics['supplier_changes'] += 1

                        # Enhanced logging with supplier change information
                        if supplier_changed:
                            logger.warning(
                                f" Statement {statement.id} reprocessed successfully - SUPPLIER CHANGED!")
                            logger.warning(
                                f"   OLD: {old_supplier_name} → NEW: {new_supplier_name}")
                        else:
                            logger.info(
                                f" Statement {statement.id} reprocessed successfully - supplier confirmed: {new_supplier_name}")
                    else:
                        statement_result.update({
                            'supplier_name': old_supplier_name,  # Keep old if reprocessing failed
                            'supplier_changed': False,
                            'error': result.get('error', 'Unknown error')
                        })
                        statistics['failed'] += 1
                        statistics['errors'].append(
                            f"Statement {statement.id}: {result.get('error', 'Unknown error')}")
                        logger.error(
                            f" Statement {statement.id} reprocessing failed: {result.get('error')}")

                    results.append(statement_result)

                    # Small delay to prevent overwhelming the system
                    import time
                    time.sleep(0.1)

                except Exception as stmt_error:
                    error_msg = f"Exception processing statement {statement.id}: {str(stmt_error)}"
                    logger.error(error_msg)
                    statistics['failed'] += 1
                    statistics['errors'].append(error_msg)

                    results.append({
                        'original_id': statement.id,
                        'supplier_name': self._get_supplier_name_safe(statement),
                        'statement_date': statement.statement_date.isoformat() if statement.statement_date else None,
                        'success': False,
                        'error': str(stmt_error)
                    })
                    continue

            # Compile final results
            success_rate = (statistics['successful'] / statistics['total_statements']
                            ) * 100 if statistics['total_statements'] > 0 else 0
            supplier_change_count = statistics['supplier_changes']

            logger.info(
                f"Bulk reprocessing completed: {statistics['successful']}/{statistics['total_statements']} successful ({success_rate:.1f}%)")
            if supplier_change_count > 0:
                logger.warning(
                    f" SUPPLIER CHANGES: {supplier_change_count} statements had supplier corrections!")
                logger.warning(
                    "   This indicates previous misassignments that have now been fixed.")
            else:
                logger.info(
                    " No supplier changes detected - all assignments were already correct.")

            return {
                'success': True,
                'message': f'Bulk reprocessing completed: {statistics["successful"]}/{statistics["total_statements"]} successful ({success_rate:.1f}%), {supplier_change_count} supplier corrections',
                'statistics': statistics,
                'results': results,
                'filter_applied': {
                    'supplier_name': supplier_name,
                    'max_statements': max_statements
                }
            }

        except Exception as e:
            logger.error(f"Error in reprocess_all_statements: {str(e)}")
            return {
                'success': False,
                'error': f'Bulk reprocessing failed: {str(e)}',
                'statistics': {
                    'total_statements': 0,
                    'successful': 0,
                    'failed': 0,
                    'errors': [str(e)]
                }
            }

    def delete_statement(self, statement_id: int) -> Dict[str, Any]:
        """
        Delete a statement and all its associated invoice items

        Args:
            statement_id: ID of the statement to delete

        Returns:
            Dict with success status and details
        """
        try:
            logger.info(f"Starting deletion of statement ID: {statement_id}")

            # First, check if the statement exists
            statement = self.db.query(PlumbingStatement).filter(
                PlumbingStatement.id == statement_id
            ).first()

            if not statement:
                return {
                    'success': False,
                    'error': f'Statement with ID {statement_id} not found'
                }

            # Get supplier name for logging
            supplier_name = self._get_supplier_name_safe(statement)
            statement_date = statement.statement_date

            # Count associated invoices before deletion
            invoice_count = self.db.query(PlumbingInvoice).filter(
                PlumbingInvoice.statement_id == statement_id
            ).count()

            logger.info(
                f"Statement {statement_id} ({supplier_name}, {statement_date}) "
                f"has {invoice_count} associated invoices"
            )

            # Delete all associated invoices first
            deleted_invoices = self.db.query(PlumbingInvoice).filter(
                PlumbingInvoice.statement_id == statement_id
            ).delete()

            # Delete the statement
            deleted_statement = self.db.query(PlumbingStatement).filter(
                PlumbingStatement.id == statement_id
            ).delete()

            # Commit the transaction
            self.db.commit()

            logger.info(
                f"Successfully deleted statement {statement_id}: "
                f"{deleted_invoices} invoices and 1 statement record removed"
            )

            return {
                'success': True,
                'message': f'Statement {statement_id} deleted successfully',
                'details': {
                    'statement_id': statement_id,
                    'supplier_name': supplier_name,
                    'statement_date': statement_date.isoformat() if statement_date else None,
                    'invoices_deleted': deleted_invoices,
                    'statements_deleted': deleted_statement
                }
            }

        except Exception as e:
            # Rollback in case of error
            self.db.rollback()
            logger.error(f"Error deleting statement {statement_id}: {str(e)}")
            return {
                'success': False,
                'error': f'Failed to delete statement: {str(e)}'
            }

    def search_statement_invoice_data(
        self,
        search: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        Search statement invoice data by search term with optional filters

        Searches in BOTH:
        - PlumbingInvoice table (statement invoices)
        - InvoiceItem table (system invoices)

        Args:
            search: Search term to look for in invoice numbers (partial match supported)
            from_date: Start date filter (DD/MM/YYYY converted to date) - filters by invoice_date
            to_date: End date filter (DD/MM/YYYY converted to date) - filters by invoice_date
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            status: Invoice status filter (Processed/Failed/Unlisted/Missing System/Missing Statement/All)
            page: Page number (1-based)
            page_size: Number of items per page

        Returns:
            Dict with invoice data and pagination metadata
        """
        try:
            # Clean and validate search term
            search = (search or '').strip()
            if not search:
                return {
                    'success': False,
                    'error': 'Search term is required',
                    'data': [],
                    'pagination': {
                        'current_page': page,
                        'page_size': page_size,
                        'total_results': 0,
                        'total_pages': 0,
                        'has_next': False,
                        'has_previous': False
                    }
                }

            logger.info(f"Searching statement invoice data - Search: '{search}', Date range: {from_date} to {to_date}, "
                        f"Suppliers: {supplier_names}, Status: {status}, Page: {page}, Size: {page_size}")

            # Handle special status filters separately
            if status and status.lower() == STATUS_UNLISTED:
                # For unlisted, search system invoices not in statements
                unlisted_results = self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=1,  # Get all data for filtering
                    page_size=200000  # Large page size to get all data
                )

                # Filter by search term with priority for "starts with" matches
                if unlisted_results['success']:
                    filtered_data = [
                        item for item in unlisted_results['data']
                        if search.lower() in item['invoice_number'].lower()
                    ]

                    # Sort by search relevance (starts with first)
                    def sort_key(item):
                        invoice_number = item['invoice_number'].lower()
                        search_lower = search.lower()
                        if invoice_number.startswith(search_lower):
                            return 0
                        return 1

                    filtered_data.sort(key=sort_key)

                    # Apply pagination to filtered results
                    total_count = len(filtered_data)
                    offset = (page - 1) * page_size
                    paginated_data = filtered_data[offset:offset + page_size]

                    # Calculate pagination metadata from filtered results
                    total_pages = ceil(
                        total_count / page_size) if page_size > 0 else 1

                    unlisted_results['data'] = paginated_data
                    unlisted_results['pagination'] = {
                        'current_page': page,
                        'page_size': page_size,
                        'total_results': total_count,
                        'total_pages': total_pages,
                        'has_next': page < total_pages,
                        'has_previous': page > 1
                    }
                    unlisted_results['filters_applied']['search'] = search

                return unlisted_results

            if status and (status.lower() == STATUS_MISSING or
                           status.lower() == STATUS_MISSING_SYSTEM or
                           status.lower() == STATUS_MISSING_STATEMENT):
                # For missing, search invalid invoices
                missing_results = self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=1,  # Get all data for filtering
                    page_size=200000  # Large page size to get all data
                )

                # Filter by search term with priority for "starts with" matches
                if missing_results['success']:
                    filtered_data = [
                        item for item in missing_results['data']
                        if item['invoice_number'] != INVOICE_NUMBER_MISSING and
                        search.lower() in item['invoice_number'].lower()
                    ]

                    # Sort by search relevance (starts with first)
                    def sort_key(item):
                        invoice_number = item['invoice_number'].lower()
                        search_lower = search.lower()
                        if invoice_number.startswith(search_lower):
                            return 0
                        return 1

                    filtered_data.sort(key=sort_key)

                    # Apply pagination to filtered results
                    total_count = len(filtered_data)
                    offset = (page - 1) * page_size
                    paginated_data = filtered_data[offset:offset + page_size]

                    # Calculate pagination metadata from filtered results
                    total_pages = ceil(
                        total_count / page_size) if page_size > 0 else 1

                    missing_results['data'] = paginated_data
                    missing_results['pagination'] = {
                        'current_page': page,
                        'page_size': page_size,
                        'total_results': total_count,
                        'total_pages': total_pages,
                        'has_next': page < total_pages,
                        'has_previous': page > 1
                    }
                    missing_results['filters_applied']['search'] = search

                return missing_results

            if status and status.lower() == STATUS_ALL:
                # For all status, search across all invoice types
                all_results = self.get_all_invoices_combined(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=1,  # Get all data for filtering
                    page_size=200000  # Large page size to get all data
                )

                # Filter by search term with priority for "starts with" matches
                if all_results['success']:
                    filtered_data = [
                        item for item in all_results['data']
                        if item['invoice_number'] != INVOICE_NUMBER_MISSING and
                        (search.lower() in item['invoice_number'].lower())
                    ]

                    # Sort by search relevance (starts with first)
                    def sort_key(item):
                        invoice_number = item['invoice_number'].lower()
                        search_lower = search.lower()
                        if invoice_number.startswith(search_lower):
                            return 0
                        return 1

                    filtered_data.sort(key=sort_key)

                    # Apply pagination to filtered results
                    total_count = len(filtered_data)
                    offset = (page - 1) * page_size
                    paginated_data = filtered_data[offset:offset + page_size]

                    # Calculate pagination metadata from filtered results
                    total_pages = ceil(
                        total_count / page_size) if page_size > 0 else 1

                    # Calculate summary from filtered results
                    status_counts = {}
                    for item in filtered_data:
                        status = item['status']
                        status_counts[status] = status_counts.get(
                            status, 0) + 1

                    all_results['data'] = paginated_data
                    all_results['pagination'] = {
                        'current_page': page,
                        'page_size': page_size,
                        'total_results': total_count,
                        'total_pages': total_pages,
                        'has_next': page < total_pages,
                        'has_previous': page > 1
                    }
                    all_results['filters_applied']['search'] = search
                    all_results['summary'] = {
                        'total_all_categories': total_count,
                        'missing_system_count': status_counts.get('Missing System', 0),
                        'missing_statement_count': status_counts.get('Missing Statement', 0),
                        'unlisted_count': status_counts.get('Unlisted', 0),
                        'processed_count': status_counts.get('Processed', 0),
                        'failed_count': status_counts.get('Failed', 0),
                        'system_source_count': len([item for item in filtered_data if item['source'] == 'system']),
                        'statement_source_count': len([item for item in filtered_data if item['source'] == 'statement'])
                    }

                return all_results

            # For default search (Processed/Failed/No specific status)
            # Search in BOTH statement invoices AND system invoices

            all_matching_invoices = []

            # 1. Search in PlumbingInvoice (statement invoices)
            # Use OR condition to prioritize "starts with" matches first
            statement_query = (
                self.db.query(PlumbingInvoice, PlumbingStatement,
                              PlumbingSupplier)
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                .filter(
                    or_(
                        PlumbingInvoice.invoice_number.ilike(
                            f"{search}%"),  # Starts with
                        PlumbingInvoice.invoice_number.ilike(
                            f"%{search}%")   # Contains
                    )
                )
            )

            # Apply date filters to statement query by statement_date (month/year only)
            normalized_from = (
                date(from_date.year, from_date.month, 1) if from_date else None
            )
            normalized_to = (
                date(
                    to_date.year,
                    to_date.month,
                    monthrange(to_date.year, to_date.month)[1]
                ) if to_date else None
            )
            if normalized_from:
                statement_query = statement_query.filter(
                    PlumbingStatement.statement_date >= normalized_from
                )
            if normalized_to:
                statement_query = statement_query.filter(
                    PlumbingStatement.statement_date <= normalized_to
                )

            # Apply supplier filter to statement query
            if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    # Check if None or empty string - means "all suppliers"
                    if supplier_name is None or supplier_name == '':
                        supplier_conditions = []
                        break
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Note: 0 is a valid supplier_id (Unknown Supplier)
                        supplier_conditions.append(PlumbingSupplier.id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )

                if supplier_conditions:
                    statement_query = statement_query.filter(
                        or_(*supplier_conditions))

            # Get statement results
            statement_results = statement_query.all()

            # Process statement invoices
            for plumbing_invoice, plumbing_statement, plumbing_supplier in statement_results:
                # Check reconciliation status
                match_result = self.check_invoice_exists_in_system(
                    plumbing_invoice.invoice_number,
                    plumbing_supplier.id,
                    plumbing_invoice.invoice_date
                )
                reconciliation_status = "Processed" if match_result['matched'] else "Failed"

                # Apply status filter if specified
                if status and status.lower() not in [STATUS_ALL, None]:
                    if status.lower() == STATUS_PROCESSED and not match_result['matched']:
                        continue
                    elif status.lower() == STATUS_FAILED and match_result['matched']:
                        continue

                all_matching_invoices.append({
                    'invoice_number': plumbing_invoice.invoice_number,
                    'invoice_date': (
                        plumbing_invoice.invoice_date.isoformat()
                        if plumbing_invoice.invoice_date else None
                    ),
                    'customer_po': plumbing_invoice.customer_po,
                    'statement_date': (
                        plumbing_statement.statement_date.isoformat()
                        if plumbing_statement.statement_date else None
                    ),
                    'supplier_name': plumbing_supplier.name,
                    'status': reconciliation_status,
                    'original_amount': (
                        float(plumbing_invoice.original_amount)
                        if plumbing_invoice.original_amount else 0.0
                    ),
                    'balance': (
                        float(plumbing_invoice.balance)
                        if plumbing_invoice.balance else 0.0
                    ),
                    'statement_id': plumbing_statement.id,
                    'invoice_id': plumbing_invoice.id,
                    'source': 'statement'
                })

            # 2. Search in InvoiceItem (system invoices) for unlisted items
            from mpi_backend.database.models.InvoiceItems import InvoiceItem
            from mpi_backend.database.models.Invoice import Invoice

            system_query = (
                self.db.query(InvoiceItem, Invoice, PlumbingSupplier)
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
                .filter(
                    or_(
                        InvoiceItem.ref_no.ilike(f"{search}%"),  # Starts with
                        InvoiceItem.ref_no.ilike(f"%{search}%")   # Contains
                    )
                )
                .filter(InvoiceItem.ref_no.isnot(None))
            )

            # Apply filters to system query
            if from_date:
                system_query = system_query.filter(
                    InvoiceItem.date >= from_date)
            if to_date:
                system_query = system_query.filter(InvoiceItem.date <= to_date)

            # Apply supplier filter to system query
            if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    # Check if None or empty string - means "all suppliers"
                    if supplier_name is None or supplier_name == '':
                        supplier_conditions = []
                        break
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Note: 0 is a valid supplier_id (Unknown Supplier)
                        supplier_conditions.append(Invoice.supplier_id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )

                if supplier_conditions:
                    system_query = system_query.filter(
                        or_(*supplier_conditions))

            # Exclude invoices that exist in statement data (PlumbingInvoice)
            subquery = self.db.query(PlumbingInvoice.invoice_number).subquery()
            system_query = system_query.filter(
                ~InvoiceItem.ref_no.in_(select(subquery.c.invoice_number)))

            # Get system results
            system_results = system_query.all()

            # Process system invoices (these are "Unlisted" status)
            for invoice_item, invoice, supplier in system_results:
                # Apply status filter if specified (system invoices are Unlisted)
                if status and status.lower() not in [STATUS_ALL, STATUS_UNLISTED, None]:
                    continue  # Skip if not looking for unlisted items

                all_matching_invoices.append({
                    'invoice_number': invoice_item.ref_no,
                    'invoice_date': (
                        invoice_item.date.isoformat()
                        if invoice_item.date else None
                    ),
                    'customer_po': invoice_item.po_number,
                    'statement_date': None,  # No statement for system invoices
                    'supplier_name': supplier.name,
                    'status': 'Unlisted',
                    'original_amount': format_currency(invoice_item.amount) if invoice_item.amount else format_currency(0.0),
                    'balance': format_currency(0.0),  # System invoices don't have balance
                    'statement_id': None,
                    'invoice_id': None,
                    'system_invoice_id': str(invoice.id),
                    'customer_job': invoice_item.customer_job,
                    'source': 'system'
                })

            # Sort by search relevance first (starts with matches first), then by invoice date (most recent first)
            def sort_key(x):
                invoice_number = x.get('invoice_number', '').lower()
                search_lower = search.lower()

                # Priority 1: Starts with search term
                if invoice_number.startswith(search_lower):
                    starts_with_priority = 0
                else:
                    starts_with_priority = 1

                # Priority 2: Invoice date (most recent first)
                date_priority = datetime.fromisoformat(
                    x['invoice_date']) if x.get('invoice_date') else datetime.min

                return (starts_with_priority, date_priority)

            all_matching_invoices.sort(key=sort_key, reverse=False)

            # Apply pagination
            total_count = len(all_matching_invoices)
            offset = (page - 1) * page_size
            paginated_invoices = all_matching_invoices[offset:offset + page_size]

            logger.info(
                f"Search completed - Found {total_count} total matches, returning {len(paginated_invoices)} for page {page}")

            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1

            return {
                'success': True,
                'data': paginated_invoices,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'search': search,
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'status': status
                }
            }

        except Exception as e:
            logger.error(f"Error searching statement invoice data: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'data': [],
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': 0,
                    'total_pages': 0,
                    'has_next': False,
                    'has_previous': False
                }
            }

    def get_unlisted_invoices(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        Find invoices that exist in our system (InvoiceItem) but are not in any statement (PlumbingInvoice)

        This method filters all InvoiceItem records that don't exist in PlumbingInvoice table.
        """
        try:
            from mpi_backend.database.models.InvoiceItems import InvoiceItem
            from mpi_backend.database.models.Invoice import Invoice

            # Build optimized query with DISTINCT to avoid duplicates at database level
            query = (
                self.db.query(
                    InvoiceItem.ref_no,
                    InvoiceItem.date,
                    InvoiceItem.po_number,
                    InvoiceItem.amount,
                    InvoiceItem.customer_job,
                    Invoice.id.label('invoice_id'),
                    PlumbingSupplier.name.label('supplier_name'),
                    PlumbingSupplier.id.label('supplier_id')
                )
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
                .distinct(InvoiceItem.ref_no, PlumbingSupplier.name, InvoiceItem.date)
            )

            # Apply date filters on InvoiceItem date
            if from_date:
                query = query.filter(InvoiceItem.date >= from_date)
            if to_date:
                query = query.filter(InvoiceItem.date <= to_date)

            # Apply supplier filter
            if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    # Check if None or empty string - means "all suppliers"
                    if supplier_name is None or supplier_name == '':
                        supplier_conditions = []
                        break
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Note: 0 is a valid supplier_id (Unknown Supplier)
                        supplier_conditions.append(
                            Invoice.supplier_id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )
                if supplier_conditions:
                    query = query.filter(or_(*supplier_conditions))

            # Exclude invoices that exist in statement data (PlumbingInvoice)
            subquery = self.db.query(PlumbingInvoice.invoice_number).subquery()
            query = query.filter(~InvoiceItem.ref_no.in_(
                select(subquery.c.invoice_number)))

            # Get total count for pagination
            total_count = query.count()

            # Stable ordering to match DISTINCT key and tie-break by id/date
            query = query.order_by(
                InvoiceItem.ref_no.asc(),
                PlumbingSupplier.name.asc(),
                InvoiceItem.date.desc(),
                InvoiceItem.id.desc(),
            )
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)

            # Execute query
            results = query.all()

            # Process results
            invoice_data = []
            for result in results:
                invoice_data.append({
                    'invoice_number': result.ref_no,
                    'invoice_date': (
                        result.date.isoformat()
                        if result.date else None
                    ),
                    'customer_po': result.po_number,
                    'statement_date': None,  # No statement for unlisted items
                    'supplier_name': result.supplier_name,
                    'status': 'Unlisted',
                    'original_amount': str(result.amount) if result.amount else "0",
                    'balance': "0",  # System invoices don't have balance
                    'statement_id': None,
                    'invoice_id': None,
                    'system_invoice_id': str(result.invoice_id),
                    'customer_job': result.customer_job
                })

            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1

            return {
                'success': True,
                'data': invoice_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'status': 'unlisted'
                }
            }

        except Exception as e:
            logger.error(f"Error getting unlisted invoices: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'data': [],
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': 0,
                    'total_pages': 0,
                    'has_next': False,
                    'has_previous': False
                }
            }

    def get_missing_invalid_invoices(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        OPTIMIZED: Find invoices with missing/invalid data efficiently

        Uses optimized SQL queries and bulk validation to avoid performance issues.
        Checks both system invoices (InvoiceItem) and statement invoices (PlumbingInvoice)
        for missing or invalid:
        - Amount (null, empty, or non-numeric values)
        - Date (null values)  
        - Tax information (malformed tax entries like "zinexx tax 004 $3.93")
        - Invoice Number (null, empty, or invalid patterns like "inv # 88992")
        - Original Item description (null or empty - system only)

        Args:
            from_date: Start date filter (filters by invoice date)
            to_date: End date filter (filters by invoice date) 
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            page: Page number (1-based)
            page_size: Number of items per page

        Returns:
            Dict with missing/invalid invoice data and pagination metadata
        """
        try:
            # Increased limit for comprehensive data
            max_records_per_source = 100000

            # Build supplier conditions once for reuse
            supplier_conditions_system = []
            supplier_conditions_statement = []

            if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                for supplier_name in supplier_names:
                    # Check if None or empty string - means "all suppliers"
                    if supplier_name is None or supplier_name == '':
                        supplier_conditions_system = []
                        supplier_conditions_statement = []
                        break
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Note: 0 is a valid supplier_id (Unknown Supplier)
                        supplier_conditions_system.append(
                            Invoice.supplier_id == supplier_id)
                        supplier_conditions_statement.append(
                            PlumbingStatement.supplier_id == supplier_id)
                    else:
                        supplier_conditions_system.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
                        supplier_conditions_statement.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%"))

            # OPTIMIZED: Build system invoices query with all needed fields and DISTINCT
            system_query = (
                self.db.query(
                    InvoiceItem.ref_no.label('invoice_number'),
                    InvoiceItem.date.label('invoice_date'),
                    InvoiceItem.po_number.label('customer_po'),
                    InvoiceItem.amount.label('original_amount'),
                    InvoiceItem.customer_job,
                    InvoiceItem.item,
                    InvoiceItem.description,
                    InvoiceItem.vendor.label('vendor'),
                    Invoice.id.label('system_invoice_id'),
                    PlumbingSupplier.name.label('supplier_name'),
                    PlumbingSupplier.id.label('supplier_id')
                )
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
                .distinct(InvoiceItem.ref_no, PlumbingSupplier.name, InvoiceItem.date)
            )

            # Apply filters to system query
            if from_date:
                system_query = system_query.filter(
                    InvoiceItem.date >= from_date)
            if to_date:
                system_query = system_query.filter(InvoiceItem.date <= to_date)
            if supplier_conditions_system:
                system_query = system_query.filter(
                    or_(*supplier_conditions_system))

            # Order system query to match DISTINCT ON stability: DISTINCT keys first, then tie-breakers
            system_query = system_query.order_by(
                InvoiceItem.ref_no.asc(),
                PlumbingSupplier.name.asc(),
                InvoiceItem.date.desc(),
                InvoiceItem.id.desc(),
            )

            # OPTIMIZED: Build statement invoices query with all needed fields and DISTINCT
            statement_query = (
                self.db.query(
                    PlumbingInvoice.invoice_number,
                    PlumbingInvoice.invoice_date,
                    PlumbingInvoice.customer_po,
                    PlumbingInvoice.original_amount,
                    PlumbingInvoice.balance,
                    PlumbingInvoice.id.label('invoice_id'),
                    PlumbingStatement.id.label('statement_id'),
                    PlumbingStatement.statement_date,
                    PlumbingSupplier.name.label('supplier_name'),
                    PlumbingSupplier.id.label('supplier_id')
                )
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                .distinct(PlumbingInvoice.invoice_number, PlumbingSupplier.name, PlumbingInvoice.invoice_date)
            )

            # Apply filters to statement query by statement_date (month/year only)
            normalized_from = (
                date(from_date.year, from_date.month, 1) if from_date else None
            )
            normalized_to = (
                date(
                    to_date.year,
                    to_date.month,
                    monthrange(to_date.year, to_date.month)[1]
                ) if to_date else None
            )
            if normalized_from:
                statement_query = statement_query.filter(
                    PlumbingStatement.statement_date >= normalized_from
                )
            if normalized_to:
                statement_query = statement_query.filter(
                    PlumbingStatement.statement_date <= normalized_to
                )
            # Apply filters to statement query by statement_date (month/year only)
            normalized_from = (
                date(from_date.year, from_date.month, 1) if from_date else None
            )
            normalized_to = (
                date(
                    to_date.year,
                    to_date.month,
                    monthrange(to_date.year, to_date.month)[1]
                ) if to_date else None
            )
            if normalized_from:
                statement_query = statement_query.filter(
                    PlumbingStatement.statement_date >= normalized_from
                )
            if normalized_to:
                statement_query = statement_query.filter(
                    PlumbingStatement.statement_date <= normalized_to
                )
            if supplier_conditions_statement:
                statement_query = statement_query.filter(
                    or_(*supplier_conditions_statement))

            # Order statement query to match DISTINCT ON stability: DISTINCT keys first, then tie-breakers
            statement_query = statement_query.order_by(
                PlumbingInvoice.invoice_number.asc(),
                PlumbingSupplier.name.asc(),
                PlumbingInvoice.invoice_date.desc(),
                PlumbingInvoice.id.desc(),
            )

            # Execute both queries with consistent ordering
            system_invoices = system_query.all()
            statement_invoices = statement_query.all()

            # Ensure consistent ordering of raw data (stable and matches ORDER BY above)
            system_invoices = sorted(system_invoices, key=lambda x: (
                x.invoice_number or '',
                getattr(x, 'supplier_name', '') or '',
                x.invoice_date or datetime.min,
                getattr(x, 'system_invoice_id', 0) or 0,
            ), reverse=False)

            statement_invoices = sorted(statement_invoices, key=lambda x: (
                x.invoice_number or '',
                getattr(x, 'supplier_name', '') or '',
                x.invoice_date or datetime.min,
                getattr(x, 'invoice_id', 0) or 0,
            ), reverse=False)

            logger.info(
                f"Missing/Invalid - Retrieved {len(system_invoices)} system invoices and {len(statement_invoices)} statement invoices")

            # Process and filter system invoices efficiently (no Python-level deduplication needed due to DISTINCT)
            missing_system_invoices = []
            for inv in system_invoices:
                # Get detailed issues for response first
                issues = self._get_detailed_issues_system(inv)

                # Debug logging for invoice 185606
                if inv.invoice_number == '185606':
                    logger.info(
                        f"DEBUG Invoice 185606 - Amount: {inv.original_amount}, Description: {getattr(inv, 'description', 'N/A')}, Issues: {issues}")

                # Only add to missing list if there are validation issues
                if issues:
                    # Sort issues for consistent ordering
                    issues.sort()
                    missing_system_invoices.append({
                        'invoice_number': inv.invoice_number or "MISSING",
                        'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
                        'customer_po': inv.customer_po,
                        'statement_date': None,
                        'supplier_name': inv.supplier_name,
                        'status': 'Missing System',
                        'original_amount': format_currency(inv.original_amount) if inv.original_amount else format_currency(0.0),
                        'balance': format_currency(0.0),
                        'statement_id': None,
                        'invoice_id': None,
                        'system_invoice_id': str(inv.system_invoice_id),
                        'customer_job': inv.customer_job,
                        'issues': issues,
                        'item_description': inv.item,
                        'vendor': inv.vendor,
                        'source': 'system'
                    })

            # Process and filter statement invoices efficiently (no Python-level deduplication needed due to DISTINCT)
            missing_statement_invoices = []
            for inv in statement_invoices:
                # Get detailed issues for response first
                issues = self._get_detailed_issues_statement(inv)

                # Only add to missing list if there are validation issues
                if issues:
                    # Sort issues for consistent ordering
                    issues.sort()
                    missing_statement_invoices.append({
                        'invoice_number': inv.invoice_number or "MISSING",
                        'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
                        'customer_po': inv.customer_po,
                        'statement_date': inv.statement_date.isoformat() if inv.statement_date else None,
                        'supplier_name': inv.supplier_name,
                        'status': 'Missing Statement',
                        'original_amount': format_currency(inv.original_amount) if inv.original_amount else format_currency(0.0),
                        'balance': format_currency(inv.balance) if inv.balance else format_currency(0.0),
                        'statement_id': inv.statement_id,
                        'invoice_id': inv.invoice_id,
                        'system_invoice_id': None,
                        'customer_job': None,
                        'issues': issues,
                        'item_description': None,
                        'vendor': inv.supplier_name,
                        'source': 'statement'
                    })

            # Combine and sort all missing invoices
            all_missing_invoices = missing_system_invoices + missing_statement_invoices

            # Sort by explicit stable key: invoice_number, supplier_name, invoice_date desc
            all_missing_invoices.sort(key=lambda x: (
                x.get('invoice_number', ''),
                x.get('supplier_name', ''),
                datetime.fromisoformat(x['invoice_date']) if x.get('invoice_date') else datetime.min,
            ), reverse=False)
            # Now reverse only by date within same key by resorting groups if needed is overkill; above order is stable

            # Apply pagination
            total_count = len(all_missing_invoices)
            offset = (page - 1) * page_size
            paginated_data = all_missing_invoices[offset:offset + page_size]

            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1

            return {
                'success': True,
                'data': paginated_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'status': 'missing'
                },
                'summary': {
                    'total_missing': total_count,
                    'missing_system_count': len(missing_system_invoices),
                    'missing_statement_count': len(missing_statement_invoices)
                }
            }

        except Exception as e:
            logger.error(f"Error getting missing/invalid invoices: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'data': [],
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': 0,
                    'total_pages': 0,
                    'has_next': False,
                    'has_previous': False
                }
            }

    def get_all_invoices_combined(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        Get ALL invoices from all categories: Unlisted, Missing, Failed, and Processed

        This method combines data from all status categories:
        - Unlisted: InvoiceItem records not in PlumbingInvoice
        - Missing: Invoices with validation issues
        - Failed: PlumbingInvoice records not in InvoiceItem  
        - Processed: PlumbingInvoice records that exist in InvoiceItem

        Args:
            from_date: Start date filter (filters by invoice date)
            to_date: End date filter (filters by invoice date)
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            page: Page number (1-based)
            page_size: Number of items per page

        Returns:
            Dict with combined invoice data from all categories and pagination metadata
        """
        try:
            # For "all" status, we want comprehensive data without artificial limits
            # Use a much higher limit to ensure we get all data
            max_total_records = 200000

            logger.info(f"Getting all invoices combined - Date range: {from_date} to {to_date}, "
                        f"Suppliers: {supplier_names}, Page: {page}, Size: {page_size}")

            # Build supplier conditions once for reuse
            supplier_conditions_system = []
            supplier_conditions_statement = []

            if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                for supplier_name in supplier_names:
                    # Check if None or empty string - means "all suppliers"
                    if supplier_name is None or supplier_name == '':
                        supplier_conditions_system = []
                        supplier_conditions_statement = []
                        break
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Note: 0 is a valid supplier_id (Unknown Supplier)
                        supplier_conditions_system.append(
                            Invoice.supplier_id == supplier_id)
                        supplier_conditions_statement.append(
                            PlumbingStatement.supplier_id == supplier_id)
                    else:
                        supplier_conditions_system.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
                        supplier_conditions_statement.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%"))

            # OPTIMIZED: Single efficient query for system invoices with all needed data and DISTINCT
            system_base_query = (
                self.db.query(
                    InvoiceItem.ref_no.label('invoice_number'),
                    InvoiceItem.date.label('invoice_date'),
                    InvoiceItem.po_number.label('customer_po'),
                    InvoiceItem.amount.label('original_amount'),
                    InvoiceItem.customer_job,
                    InvoiceItem.item,
                    InvoiceItem.description,
                    Invoice.id.label('system_invoice_id'),
                    PlumbingSupplier.name.label('supplier_name'),
                    PlumbingSupplier.id.label('supplier_id')
                )
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
                # Exclude null invoice numbers
                .filter(InvoiceItem.ref_no.isnot(None))
                .distinct(InvoiceItem.ref_no, PlumbingSupplier.name, InvoiceItem.date)
            )

            # Apply filters to system query
            if from_date:
                system_base_query = system_base_query.filter(
                    InvoiceItem.date >= from_date)
            if to_date:
                system_base_query = system_base_query.filter(
                    InvoiceItem.date <= to_date)
            if supplier_conditions_system:
                system_base_query = system_base_query.filter(
                    or_(*supplier_conditions_system))

            system_base_query = system_base_query.order_by(
                InvoiceItem.ref_no.asc(),
                PlumbingSupplier.name.asc(),
                InvoiceItem.date.desc(),
                InvoiceItem.id.desc()
            )

            # OPTIMIZED: Single query for statement invoices with all needed data and DISTINCT
            statement_base_query = (
                self.db.query(
                    PlumbingInvoice.invoice_number,
                    PlumbingInvoice.invoice_date,
                    PlumbingInvoice.customer_po,
                    PlumbingInvoice.original_amount,
                    PlumbingInvoice.balance,
                    PlumbingInvoice.id.label('invoice_id'),
                    PlumbingStatement.id.label('statement_id'),
                    PlumbingStatement.statement_date,
                    PlumbingSupplier.name.label('supplier_name'),
                    PlumbingSupplier.id.label('supplier_id')
                )
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                # Exclude null invoice numbers
                .filter(PlumbingInvoice.invoice_number.isnot(None))
                .distinct(PlumbingInvoice.invoice_number, PlumbingSupplier.name, PlumbingInvoice.invoice_date)
            )

            # Apply filters to statement query by statement_date (month/year only)
            normalized_from = (
                date(from_date.year, from_date.month, 1) if from_date else None
            )
            normalized_to = (
                date(
                    to_date.year,
                    to_date.month,
                    monthrange(to_date.year, to_date.month)[1]
                ) if to_date else None
            )
            if normalized_from:
                statement_base_query = statement_base_query.filter(
                    PlumbingStatement.statement_date >= normalized_from
                )
            if normalized_to:
                statement_base_query = statement_base_query.filter(
                    PlumbingStatement.statement_date <= normalized_to
                )
            if supplier_conditions_statement:
                statement_base_query = statement_base_query.filter(
                    or_(*supplier_conditions_statement))

            statement_base_query = statement_base_query.order_by(
                PlumbingInvoice.invoice_number.asc(),
                PlumbingSupplier.name.asc(),
                PlumbingInvoice.invoice_date.desc(),
                PlumbingInvoice.id.desc()
            )

            # Execute both queries
            system_invoices = system_base_query.all()
            statement_invoices = statement_base_query.all()

            logger.info(
                f"Retrieved {len(system_invoices)} system invoices and {len(statement_invoices)} statement invoices")

            # OPTIMIZED: Bulk check for statement matches using a single query
            system_invoice_numbers = [
                inv.invoice_number for inv in system_invoices if inv.invoice_number]
            statement_matches = set()
            if system_invoice_numbers:
                matched_statements = (
                    self.db.query(PlumbingInvoice.invoice_number)
                    .filter(PlumbingInvoice.invoice_number.in_(system_invoice_numbers))
                    .distinct()
                    .all()
                )
                statement_matches = {
                    match.invoice_number for match in matched_statements}

            # OPTIMIZED: Bulk check for system matches using a single query
            statement_invoice_numbers = [
                inv.invoice_number for inv in statement_invoices if inv.invoice_number]
            system_matches = set()
            if statement_invoice_numbers:
                matched_systems = (
                    self.db.query(InvoiceItem.ref_no)
                    .filter(InvoiceItem.ref_no.in_(statement_invoice_numbers))
                    .distinct()
                    .all()
                )
                system_matches = {match.ref_no for match in matched_systems}

            # Process all invoices efficiently (no Python-level deduplication needed due to DISTINCT)
            all_invoices = []

            # Process system invoices (InvoiceItem records)
            for inv in system_invoices:
                has_issues = self._has_validation_issues_system(inv)
                if has_issues:
                    status = "Missing System"
                elif inv.invoice_number in statement_matches:
                    status = "Processed"
                else:
                    status = "Unlisted"
                all_invoices.append({
                    'invoice_number': inv.invoice_number,
                    'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
                    'customer_po': inv.customer_po,
                    'statement_date': None,
                    'supplier_name': inv.supplier_name,
                    'status': status,
                    'original_amount': format_currency(inv.original_amount) if inv.original_amount else format_currency(0.0),
                    'balance': format_currency(0.0),
                    'statement_id': None,
                    'invoice_id': None,
                    'system_invoice_id': str(inv.system_invoice_id),
                    'customer_job': inv.customer_job,
                    'source': 'system'
                })

            # Process statement invoices (PlumbingInvoice records)
            for inv in statement_invoices:
                has_issues = self._has_validation_issues_statement(inv)
                if has_issues:
                    status = "Missing Statement"
                elif inv.invoice_number in system_matches:
                    status = "Processed"
                else:
                    status = "Failed"
                all_invoices.append({
                    'invoice_number': inv.invoice_number,
                    'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
                    'customer_po': inv.customer_po,
                    'statement_date': inv.statement_date.isoformat() if inv.statement_date else None,
                    'supplier_name': inv.supplier_name,
                    'status': status,
                    'original_amount': format_currency(inv.original_amount) if inv.original_amount else format_currency(0.0),
                    'balance': format_currency(inv.balance) if inv.balance else format_currency(0.0),
                    'statement_id': inv.statement_id,
                    'invoice_id': inv.invoice_id,
                    'system_invoice_id': None,
                    'customer_job': None,
                    'source': 'statement'
                })
            # Stable sort: by invoice_date desc, then invoice_number asc, supplier asc, and source (system first)
            all_invoices.sort(key=lambda x: (
                -(
                    (datetime.fromisoformat(x['invoice_date']) if x.get('invoice_date') else datetime.min).toordinal()
                ),
                x.get('invoice_number', ''),
                x.get('supplier_name', ''),
                x['source'] == 'statement',
            ))
            total_count = len(all_invoices)
            offset = (page - 1) * page_size
            paginated_data = all_invoices[offset:offset + page_size]

            logger.info(f"After processing: {len(all_invoices)} total invoices, {total_count} unique invoices, "
                        f"showing {len(paginated_data)} for page {page}")

            # Log detailed breakdown by status
            status_breakdown = {}
            for invoice in all_invoices:
                status = invoice['status']
                status_breakdown[status] = status_breakdown.get(status, 0) + 1

            logger.info(f"Status breakdown: {status_breakdown}")

            # Calculate counts by status
            status_counts = {}
            for invoice in all_invoices:
                status = invoice['status']
                status_counts[status] = status_counts.get(status, 0) + 1

            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1

            return {
                'success': True,
                'data': paginated_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'status': 'all'
                },
                'summary': {
                    'total_all_categories': total_count,
                    'missing_system_count': status_counts.get('Missing System', 0),
                    'missing_statement_count': status_counts.get('Missing Statement', 0),
                    'unlisted_count': status_counts.get('Unlisted', 0),
                    'processed_count': status_counts.get('Processed', 0),
                    'failed_count': status_counts.get('Failed', 0),
                    'system_source_count': len([inv for inv in all_invoices if inv['source'] == 'system']),
                    'statement_source_count': len([inv for inv in all_invoices if inv['source'] == 'statement'])
                }
            }

        except Exception as e:
            logger.error(f"Error getting all combined invoices: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'data': [],
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': 0,
                    'total_pages': 0,
                    'has_next': False,
                    'has_previous': False
                }
            }

    def _has_validation_issues_system(self, invoice) -> bool:
        """
        Efficiently check if a system invoice has validation issues

        Args:
            invoice: System invoice record with fields: original_amount, invoice_date, 
                    invoice_number, item, description

        Returns:
            bool: True if invoice has validation issues
        """
        # Check for missing/invalid amount
        if not invoice.original_amount or invoice.original_amount == "":
            return True

        try:
            # Remove commas for validation, but amounts with commas are valid
            amount_str = str(invoice.original_amount).strip().replace(',', '')
            # Check if amount contains alphabetic characters (invalid)
            if any(char.isalpha() for char in amount_str):
                return True
            # Check for malformed concatenated strings (no spaces, mixed content)
            if re.search(r'\$[a-z]+\d+[a-z]+\d+', amount_str.lower()):
                return True
            float(amount_str)
        except (ValueError, TypeError):
            return True

        # Check for missing date
        if not invoice.invoice_date:
            return True

        # Check for missing/invalid invoice number
        if not invoice.invoice_number or invoice.invoice_number == "":
            return True

        ref_no_str = str(invoice.invoice_number).strip().lower()
        if (ref_no_str.startswith("inv #") or
            ref_no_str.startswith("invoice #") or
            ref_no_str.startswith("inv#") or
                " # " in ref_no_str):
            return True

        # Check for missing item description
        if not invoice.item or invoice.item == "":
            return True

        # Enhanced tax format validation
        if invoice.description:
            desc_str = str(invoice.description).lower()
            if "tax" in desc_str:
                # Check for malformed concatenated strings (no spaces, mixed content)
                if re.search(r'\$[a-z]+\d+[a-z]+\d+', desc_str):
                    return True
                # Check for various invalid tax formats
                # Pattern 1: Text followed by tax followed by numbers and $
                if re.search(r'[a-zA-Z]+\s+tax\s+\d+\s*\$', desc_str):
                    return True
                # Pattern 2: Tax with alphabetic characters mixed with numbers
                if re.search(r'tax.*[a-zA-Z].*\d+.*\$', desc_str):
                    return True
                # Pattern 3: Tax with invalid characters (not just numbers, decimal, minus, plus)
                if re.search(r'tax.*[^0-9\-\+\.\,\s\$]', desc_str):
                    return True
                # Pattern 4: Tax amount that can't be converted to float
                # Updated regex to handle negative amounts and $ before or after the number
                tax_match = re.search(
                    r'tax.*?(\-?\$?\d+[\.\d]*\$?)\s*', desc_str)
                if tax_match:
                    try:
                        tax_amount = tax_match.group(
                            1).replace(',', '').replace('$', '')
                        if any(char.isalpha() for char in tax_amount):
                            return True
                        float(tax_amount)
                    except (ValueError, TypeError):
                        return True

        return False

    def _has_validation_issues_statement(self, invoice) -> bool:
        """
        Efficiently check if a statement invoice has validation issues

        Args:
            invoice: Statement invoice record with fields: original_amount, invoice_date, 
                    invoice_number

        Returns:
            bool: True if invoice has validation issues
        """
        # Check for missing/invalid amount
        if not invoice.original_amount or invoice.original_amount == "":
            return True

        try:
            # Remove commas for validation, but amounts with commas are valid
            amount_str = str(invoice.original_amount).strip().replace(',', '')
            # Check if amount contains alphabetic characters (invalid)
            if any(char.isalpha() for char in amount_str):
                return True
            # Check for malformed concatenated strings (no spaces, mixed content)
            if re.search(r'\$[a-z]+\d+[a-z]+\d+', amount_str.lower()):
                return True
            float(amount_str)
        except (ValueError, TypeError):
            return True

        # Check for missing date
        if not invoice.invoice_date:
            return True

        # Check for missing/invalid invoice number
        if not invoice.invoice_number or invoice.invoice_number == "":
            return True

        ref_no_str = str(invoice.invoice_number).strip().lower()
        if (ref_no_str.startswith("inv #") or
            ref_no_str.startswith("invoice #") or
            ref_no_str.startswith("inv#") or
                " # " in ref_no_str):
            return True

        return False

    def _get_detailed_issues_system(self, invoice) -> List[str]:
        """
        Get detailed list of validation issues for system invoices

        Args:
            invoice: System invoice object to analyze

        Returns:
            List[str]: List of specific validation issues
        """
        issues = []

        # Validate amount
        if not invoice.original_amount or str(invoice.original_amount).strip() == "":
            issues.append("Missing Amount")
        else:
            try:
                amount_str = str(
                    invoice.original_amount).strip().replace(',', '')

                # Debug logging for amount validation
                if '$370.93' in str(invoice.original_amount):
                    logger.info(
                        f"DEBUG Amount validation for $370.93 - Amount: {invoice.original_amount}, Amount_str: {amount_str}")

                # Check if amount contains alphabetic characters (invalid)
                if any(char.isalpha() for char in amount_str):
                    issues.append(
                        "Invalid Amount Format")
                # Check for malformed concatenated strings (no spaces, mixed content)
                elif re.search(r'\$[a-z]+\d+[a-z]+\d+', amount_str.lower()):
                    issues.append("Invalid Amount Format")
                else:
                    float(amount_str)
            except (ValueError, TypeError):
                issues.append("Invalid Amount Format")

        # Validate date
        if not invoice.invoice_date:
            issues.append("Missing Date")

        # Validate invoice number
        if not invoice.invoice_number or str(invoice.invoice_number).strip() == "":
            issues.append("Missing Invoice Number")
        else:
            ref_no_str = str(invoice.invoice_number).strip().lower()
            if (ref_no_str.startswith("inv #") or
                ref_no_str.startswith("invoice #") or
                ref_no_str.startswith("inv#") or
                    " # " in ref_no_str):
                issues.append("Invalid Invoice Number")

        # Validate item description (system invoices only)
        if hasattr(invoice, 'item') and (not invoice.item or str(invoice.item).strip() == ""):
            issues.append("Missing Original Item")

        # Enhanced tax format validation
        if hasattr(invoice, 'description') and invoice.description:
            desc_str = str(invoice.description).lower()
            if "tax" in desc_str:
                # Debug logging for tax validation
                if '$370.93' in str(invoice.description):
                    logger.info(
                        f"DEBUG Tax validation for $370.93 - Description: {invoice.description}")

                # Check for malformed concatenated strings (no spaces, mixed content)
                if re.search(r'\$[a-z]+\d+[a-z]+\d+', desc_str):
                    issues.append("Invalid Tax Format - Malformed Description")
                # Check for various invalid tax formats
                # Pattern 1: Text followed by tax followed by numbers and $
                elif re.search(r'[a-zA-Z]+\s+tax\s+\d+\s*\$', desc_str):
                    issues.append("Invalid Tax Format - Text Before Tax")
                # Pattern 2: Tax with alphabetic characters mixed with numbers
                elif re.search(r'tax.*[a-zA-Z].*\d+.*\$', desc_str):
                    issues.append("Invalid Tax Format")
                # Pattern 3: Tax with invalid characters (not just numbers, decimal, minus, plus)
                elif re.search(r'tax.*[^0-9\-\+\.\,\s\$]', desc_str):
                    issues.append("Invalid Tax Format")
                # Pattern 4: Tax amount that can't be converted to float
                else:
                    # Updated regex to handle negative amounts and $ before or after the number
                    tax_match = re.search(
                        r'tax.*?(\-?\$?\d+[\.\d]*\$?)\s*', desc_str)
                    if tax_match:
                        try:
                            tax_amount = tax_match.group(
                                1).replace(',', '').replace('$', '')
                            if any(char.isalpha() for char in tax_amount):
                                issues.append(
                                    "Invalid Tax Format")
                            else:
                                # Try to convert to float - if it works, it's valid
                                float(tax_amount)
                                # If we get here, the tax amount is valid, so don't add an issue
                        except (ValueError, TypeError):
                            issues.append(
                                "Invalid Tax Format")

        return issues

    def _get_detailed_issues_statement(self, invoice) -> List[str]:
        """
        Get detailed list of validation issues for statement invoices

        Args:
            invoice: Statement invoice object to analyze

        Returns:
            List[str]: List of specific validation issues  
        """
        issues = []

        # Validate amount
        if not invoice.original_amount or str(invoice.original_amount).strip() == "":
            issues.append("Missing Amount")
        else:
            try:
                amount_str = str(
                    invoice.original_amount).strip().replace(',', '')
                # Check if amount contains alphabetic characters (invalid)
                if any(char.isalpha() for char in amount_str):
                    issues.append(
                        "Invalid Amount Format")
                else:
                    float(amount_str)
            except (ValueError, TypeError):
                issues.append("Invalid Amount Format")

        # Validate date
        if not invoice.invoice_date:
            issues.append("Missing Date")

        # Validate invoice number
        if not invoice.invoice_number or str(invoice.invoice_number).strip() == "":
            issues.append("Missing Invoice Number")
        else:
            ref_no_str = str(invoice.invoice_number).strip().lower()
            if (ref_no_str.startswith("inv #") or
                ref_no_str.startswith("invoice #") or
                ref_no_str.startswith("inv#") or
                    " # " in ref_no_str):
                issues.append("Invalid Invoice Number Format")

        return issues

    def get_aggregate_monthly(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get aggregated statistics for statement invoices with filters.
        
        Aggregates amounts from all/processed/failed/unlisted/missing invoices
        based on the selected filters.
        
        Args:
            from_date: Start date filter
            to_date: End date filter
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            status: Filter by status (Processed/Failed/Unlisted/Missing/All)
        
        Returns:
            Dict with aggregated statistics
        """
        try:
            from mpi_backend.database.models.InvoiceItems import InvoiceItem
            from mpi_backend.database.models.Invoice import Invoice
            from sqlalchemy import func
            from decimal import Decimal
            
            total_original_amount = Decimal('0.0')
            total_balance = Decimal('0.0')
            invoice_count = 0
            supplier_count = 0
            
            # Determine which data to aggregate based on status
            if status and status.lower() == STATUS_UNLISTED:
                # Get unlisted invoices (InvoiceItem not in PlumbingInvoice)
                result = self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=1,
                    page_size=999999
                )
                
                if result['success']:
                    for invoice in result['data']:
                        amount_str = str(invoice.get('original_amount', '0')).replace('$', '').replace(',', '').strip()
                        try:
                            total_original_amount += Decimal(amount_str)
                        except:
                            pass
                        
                        balance_str = str(invoice.get('balance', '0')).replace('$', '').replace(',', '').strip()
                        try:
                            total_balance += Decimal(balance_str)
                        except:
                            pass
                    
                    invoice_count = result['pagination']['total_results']
                    suppliers = set(inv['supplier_name'] for inv in result['data'])
                    supplier_count = len(suppliers)
                    
            elif status and (status.lower() == STATUS_MISSING or 
                           status.lower() == STATUS_MISSING_SYSTEM or 
                           status.lower() == STATUS_MISSING_STATEMENT):
                # Get missing/invalid invoices
                result = self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=1,
                    page_size=999999
                )
                
                if result['success']:
                    for invoice in result['data']:
                        amount_str = str(invoice.get('original_amount', '0')).replace('$', '').replace(',', '').strip()
                        try:
                            total_original_amount += Decimal(amount_str)
                        except:
                            pass
                        
                        balance_str = str(invoice.get('balance', '0')).replace('$', '').replace(',', '').strip()
                        try:
                            total_balance += Decimal(balance_str)
                        except:
                            pass
                    
                    invoice_count = result['pagination']['total_results']
                    suppliers = set(inv['supplier_name'] for inv in result['data'])
                    supplier_count = len(suppliers)
                    
            elif status and status.lower() == STATUS_ALL:
                # Get all invoices combined
                result = self.get_all_invoices_combined(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=1,
                    page_size=999999
                )
                
                if result['success']:
                    for invoice in result['data']:
                        amount_str = str(invoice.get('original_amount', '0')).replace('$', '').replace(',', '').strip()
                        try:
                            total_original_amount += Decimal(amount_str)
                        except:
                            pass
                        
                        balance_str = str(invoice.get('balance', '0')).replace('$', '').replace(',', '').strip()
                        try:
                            total_balance += Decimal(balance_str)
                        except:
                            pass
                    
                    invoice_count = result['pagination']['total_results']
                    suppliers = set(inv['supplier_name'] for inv in result['data'])
                    supplier_count = len(suppliers)
                    
            else:
                # For Processed/Failed status: Query PlumbingInvoice directly
                normalized_from = (
                    date(from_date.year, from_date.month, 1) if from_date else None
                )
                normalized_to = (
                    date(
                        to_date.year,
                        to_date.month,
                        monthrange(to_date.year, to_date.month)[1]
                    ) if to_date else None
                )
                
                query = (
                    self.db.query(
                        PlumbingInvoice,
                        PlumbingStatement,
                        PlumbingSupplier,
                        InvoiceItem.id.label('system_invoice_id')
                    )
                    .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                    .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                    .outerjoin(
                        InvoiceItem,
                        (InvoiceItem.ref_no == PlumbingInvoice.invoice_number) &
                        (InvoiceItem.date == PlumbingInvoice.invoice_date) &
                        (InvoiceItem.vendor == PlumbingSupplier.name)
                    )
                )
                
                if normalized_from:
                    query = query.filter(
                        PlumbingStatement.statement_date >= normalized_from
                    )
                if normalized_to:
                    query = query.filter(
                        PlumbingStatement.statement_date <= normalized_to
                    )
                
                # Apply supplier filter
                if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
                    supplier_conditions = []
                    for supplier_name in supplier_names:
                        # Check if None or empty string - means "all suppliers"
                        if supplier_name is None or supplier_name == '':
                            supplier_conditions = []
                            break
                        if supplier_name.isdigit():
                            supplier_id = int(supplier_name)
                            # Note: 0 is a valid supplier_id (Unknown Supplier)
                            supplier_conditions.append(PlumbingSupplier.id == supplier_id)
                        else:
                            supplier_conditions.append(
                                PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                            )
                    if supplier_conditions:
                        query = query.filter(or_(*supplier_conditions))
                
                all_results = query.all()
                seen_keys = set()
                suppliers = set()
                
                for plumbing_invoice, plumbing_statement, plumbing_supplier, system_invoice_id in all_results:
                    reconciliation_status = "Processed" if system_invoice_id else "Failed"
                    
                    key = (plumbing_invoice.invoice_number,
                           plumbing_supplier.name, plumbing_invoice.invoice_date)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    
                    # Apply status filter
                    if status and status.lower() != STATUS_ALL:
                        if status.lower() == STATUS_PROCESSED and not system_invoice_id:
                            continue
                        elif status.lower() == STATUS_FAILED and system_invoice_id:
                            continue
                    
                    # Aggregate amounts
                    if plumbing_invoice.original_amount:
                        try:
                            total_original_amount += Decimal(str(plumbing_invoice.original_amount))
                        except:
                            pass
                    
                    if plumbing_invoice.balance:
                        try:
                            total_balance += Decimal(str(plumbing_invoice.balance))
                        except:
                            pass
                    
                    invoice_count += 1
                    suppliers.add(plumbing_supplier.name)
                
                supplier_count = len(suppliers)
            
            # Calculate average
            average_amount = Decimal('0.0')
            if invoice_count > 0:
                average_amount = total_original_amount / invoice_count
            
            return {
                'success': True,
                'quantity': invoice_count,
                'average': format_currency(float(average_amount)),
                'amount': format_currency(float(total_original_amount)),
                'filters_applied': {
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'status': status
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting aggregate monthly: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'quantity': 0,
                'average': format_currency(0.0),
                'amount': format_currency(0.0)
            }

    def _build_export_query(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        status: Optional[str] = None,
        excluded_ints: Optional[set] = None
    ) -> Any:
        """
        Build a SQLAlchemy query object for export that can use yield_per for streaming.
        Returns a query object, not results.
        
        This method mirrors the logic from get_statement_invoice_data but returns queries
        instead of executing them, allowing for streaming with yield_per.
        
        Args:
            from_date: Start date filter
            to_date: End date filter
            supplier_names: List of supplier names or IDs
            status: Status filter (Processed, Failed, Unlisted, Missing, All)
            excluded_ints: Set of integer IDs to exclude at database level
        """
        
        # Handle different status types
        status_lower: Optional[str] = status.lower() if status else None
        
        if status_lower == STATUS_UNLISTED:
            return self._build_unlisted_query(from_date, to_date, supplier_names, excluded_ints)
        elif status_lower in (STATUS_MISSING, STATUS_MISSING_SYSTEM, STATUS_MISSING_STATEMENT):
            return self._build_missing_query(from_date, to_date, supplier_names, excluded_ints)
        elif status_lower == STATUS_ALL:
            return self._build_all_combined_query(from_date, to_date, supplier_names, excluded_ints)
        else:
            # Processed/Failed status
            return self._build_processed_failed_query(from_date, to_date, supplier_names, status, excluded_ints)
    
    def _build_processed_failed_query(
        self,
        from_date: Optional[date],
        to_date: Optional[date],
        supplier_names: Optional[List[str]],
        status: Optional[str],
        excluded_ints: Optional[set] = None
    ) -> tuple:
        """Build query for Processed/Failed status"""
        
        query = (
            self.db.query(
                PlumbingInvoice,
                PlumbingStatement,
                PlumbingSupplier,
                InvoiceItem.id.label('system_invoice_id')
            )
            .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
            .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
            .outerjoin(
                InvoiceItem,
                (InvoiceItem.ref_no == PlumbingInvoice.invoice_number) &
                (InvoiceItem.date == PlumbingInvoice.invoice_date) &
                (InvoiceItem.vendor == PlumbingSupplier.name)
            )
        )
        
        # Apply date filters
        normalized_from: Optional[date] = date(from_date.year, from_date.month, 1) if from_date else None
        normalized_to: Optional[date] = (
            date(to_date.year, to_date.month, monthrange(to_date.year, to_date.month)[1]) 
            if to_date else None
        )
        
        if normalized_from:
            query = query.filter(PlumbingStatement.statement_date >= normalized_from)
        if normalized_to:
            query = query.filter(PlumbingStatement.statement_date <= normalized_to)
        
        # Apply supplier filter
        if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
            supplier_conditions: List = []
            for supplier_name in supplier_names:
                # Check if None or empty string - means "all suppliers"
                if supplier_name is None or supplier_name == '':
                    supplier_conditions = []
                    break
                if supplier_name.isdigit():
                    supplier_id: int = int(supplier_name)
                    # Note: 0 is a valid supplier_id (Unknown Supplier)
                    supplier_conditions.append(PlumbingSupplier.id == supplier_id)
                else:
                    supplier_conditions.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
            if supplier_conditions:
                query = query.filter(or_(*supplier_conditions))

        # Apply exclusion filter at database level
        if excluded_ints:
            query = query.filter(~PlumbingInvoice.id.in_(excluded_ints))
        
        query = query.order_by(
            PlumbingInvoice.invoice_number.asc(),
            PlumbingSupplier.name.asc(),
            PlumbingInvoice.invoice_date.desc(),
            PlumbingInvoice.id.desc()
        )
        
        return query, QUERY_TYPE_PROCESSED_FAILED
    
    def _build_unlisted_query(self, from_date: Optional[date], to_date: Optional[date], supplier_names: Optional[List[str]], excluded_ints: Optional[set] = None) -> tuple:
        """Build query for Unlisted invoices"""
        
        query = (
            self.db.query(
                InvoiceItem.ref_no,
                InvoiceItem.date,
                InvoiceItem.po_number,
                InvoiceItem.amount,
                InvoiceItem.customer_job,
                Invoice.id.label('invoice_id'),
                PlumbingSupplier.name.label('supplier_name'),
                PlumbingSupplier.id.label('supplier_id')
            )
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
            .distinct(InvoiceItem.ref_no, PlumbingSupplier.name, InvoiceItem.date)
        )
        
        # Apply date filters
        if from_date:
            query = query.filter(InvoiceItem.date >= from_date)
        if to_date:
            query = query.filter(InvoiceItem.date <= to_date)
        
        # Apply supplier filter
        if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
            supplier_conditions: List = []
            for supplier_name in supplier_names:
                # Check if None or empty string - means "all suppliers"
                if supplier_name is None or supplier_name == '':
                    supplier_conditions = []
                    break
                if supplier_name.isdigit():
                    supplier_id: int = int(supplier_name)
                    # Note: 0 is a valid supplier_id (Unknown Supplier)
                    supplier_conditions.append(Invoice.supplier_id == supplier_id)
                else:
                    supplier_conditions.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
            if supplier_conditions:
                query = query.filter(or_(*supplier_conditions))

        # Exclude invoices in PlumbingInvoice
        subquery = self.db.query(PlumbingInvoice.invoice_number).subquery()
        query = query.filter(~InvoiceItem.ref_no.in_(select(subquery.c.invoice_number)))
        
        # Apply exclusion filter at database level
        if excluded_ints:
            query = query.filter(~Invoice.id.in_(excluded_ints))
        
        query = query.order_by(
            InvoiceItem.ref_no.asc(),
            PlumbingSupplier.name.asc(),
            InvoiceItem.date.desc(),
            InvoiceItem.id.desc()
        )
        
        return query, QUERY_TYPE_UNLISTED
    
    def _build_system_and_statement_queries(
        self, 
        from_date: Optional[date], 
        to_date: Optional[date], 
        supplier_names: Optional[List[str]], 
        excluded_ints: Optional[set] = None,
        filter_missing: bool = False
    ) -> tuple:
        """
        Build queries for system and statement invoices with optional validation filters.
        
        This unified method handles both "Missing/Invalid" and "All Combined" query types:
        - When filter_missing=True: Returns only invoices with validation issues (QUERY_TYPE_MISSING)
        - When filter_missing=False: Returns all valid invoices (QUERY_TYPE_ALL_COMBINED)
        
        Args:
            from_date: Start date filter
            to_date: End date filter
            supplier_names: List of supplier names/IDs
            excluded_ints: Set of integer IDs to exclude at database level
            filter_missing: If True, filter for validation issues; if False, filter for valid records
            
        Returns:
            Tuple of ([system_query, statement_query], query_type_constant)
        """
        
        # Build supplier conditions
        supplier_conditions_system: List = []
        supplier_conditions_statement: List = []
        
        if supplier_names and not (len(supplier_names) == 1 and (supplier_names[0] or '').lower() == STATUS_ALL):
            for supplier_name in supplier_names:
                # Check if None or empty string - means "all suppliers"
                if supplier_name is None or supplier_name == '':
                    supplier_conditions_system = []
                    supplier_conditions_statement = []
                    break
                if supplier_name.isdigit():
                    supplier_id = int(supplier_name)
                    # Note: 0 is a valid supplier_id (Unknown Supplier)
                    supplier_conditions_system.append(Invoice.supplier_id == supplier_id)
                    supplier_conditions_statement.append(PlumbingStatement.supplier_id == supplier_id)
                else:
                    supplier_conditions_system.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
                    supplier_conditions_statement.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))

        # System invoices query - base structure
        system_query = (
            self.db.query(
                InvoiceItem.ref_no.label('invoice_number'),
                InvoiceItem.date.label('invoice_date'),
                InvoiceItem.po_number.label('customer_po'),
                InvoiceItem.amount.label('original_amount'),
                InvoiceItem.customer_job,
                Invoice.id.label('system_invoice_id'),
                PlumbingSupplier.name.label('supplier_name')
            )
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
            .distinct(InvoiceItem.ref_no, PlumbingSupplier.name, InvoiceItem.date)
        )
        
        # Apply validation filter based on mode
        if filter_missing:
            # Filter for invoices WITH validation issues
            system_query = system_query.filter(
                or_(
                    InvoiceItem.amount.is_(None),
                    InvoiceItem.date.is_(None),
                    InvoiceItem.ref_no.is_(None),
                    InvoiceItem.item.is_(None),
                    InvoiceItem.item == ''
                )
            )
        else:
            # Filter for valid invoices only (exclude null invoice numbers)
            system_query = system_query.filter(InvoiceItem.ref_no.isnot(None))
        
        # Apply date filters
        if from_date:
            system_query = system_query.filter(InvoiceItem.date >= from_date)
        if to_date:
            system_query = system_query.filter(InvoiceItem.date <= to_date)
        if supplier_conditions_system:
            system_query = system_query.filter(or_(*supplier_conditions_system))
        
        # Apply exclusion filter
        if excluded_ints:
            system_query = system_query.filter(~Invoice.id.in_(excluded_ints))
        
        # Apply ordering
        system_query = system_query.order_by(
            InvoiceItem.ref_no.asc(),
            PlumbingSupplier.name.asc(),
            InvoiceItem.date.desc(),
            InvoiceItem.id.desc()
        )
        
        # Statement invoices query - base structure
        statement_query = (
            self.db.query(
                PlumbingInvoice.invoice_number,
                PlumbingInvoice.invoice_date,
                PlumbingInvoice.customer_po,
                PlumbingInvoice.original_amount,
                PlumbingInvoice.balance,
                PlumbingInvoice.id.label('invoice_id'),
                PlumbingStatement.id.label('statement_id'),
                PlumbingStatement.statement_date,
                PlumbingSupplier.name.label('supplier_name')
            )
            .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
            .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
            .distinct(PlumbingInvoice.invoice_number, PlumbingSupplier.name, PlumbingInvoice.invoice_date)
        )
        
        # Apply validation filter based on mode
        if filter_missing:
            # Filter for invoices WITH validation issues
            statement_query = statement_query.filter(
                or_(
                    PlumbingInvoice.original_amount.is_(None),
                    PlumbingInvoice.invoice_date.is_(None),
                    PlumbingInvoice.invoice_number.is_(None)
                )
            )
        else:
            # Filter for valid invoices only (exclude null invoice numbers)
            statement_query = statement_query.filter(PlumbingInvoice.invoice_number.isnot(None))
        
        # Apply date filters (normalized by month)
        normalized_from = date(from_date.year, from_date.month, 1) if from_date else None
        normalized_to = (
            date(to_date.year, to_date.month, monthrange(to_date.year, to_date.month)[1]) 
            if to_date else None
        )
        
        if normalized_from:
            statement_query = statement_query.filter(PlumbingStatement.statement_date >= normalized_from)
        if normalized_to:
            statement_query = statement_query.filter(PlumbingStatement.statement_date <= normalized_to)
        if supplier_conditions_statement:
            statement_query = statement_query.filter(or_(*supplier_conditions_statement))
        
        # Apply exclusion filter
        if excluded_ints:
            statement_query = statement_query.filter(~PlumbingInvoice.id.in_(excluded_ints))
        
        # Apply ordering - must match DISTINCT ON columns first
        statement_query = statement_query.order_by(
            PlumbingInvoice.invoice_number.asc(),
            PlumbingSupplier.name.asc(),
            PlumbingInvoice.invoice_date.desc(),
            PlumbingStatement.statement_date.desc(),
            PlumbingInvoice.id.desc(),
        )
        
        # Return appropriate query type based on mode
        query_type = QUERY_TYPE_MISSING if filter_missing else QUERY_TYPE_ALL_COMBINED
        return [system_query, statement_query], query_type
    
    def _build_missing_query(self, from_date: Optional[date], to_date: Optional[date], supplier_names: Optional[List[str]], excluded_ints: Optional[set] = None) -> tuple:
        """Build queries for Missing/Invalid invoices (wrapper for unified method)"""
        return self._build_system_and_statement_queries(from_date, to_date, supplier_names, excluded_ints, filter_missing=True)
    
    def _build_all_combined_query(self, from_date: Optional[date], to_date: Optional[date], supplier_names: Optional[List[str]], excluded_ints: Optional[set] = None) -> tuple:
        """Build queries for All combined invoices (wrapper for unified method)"""
        return self._build_system_and_statement_queries(from_date, to_date, supplier_names, excluded_ints, filter_missing=False)
    
    def _stream_and_process_rows(
        self,
        query_info: tuple,
        status: Optional[str] = None,
        batch_size: int = 1000
    ) -> Generator[dict, None, None]:
        """
        Stream rows from database using yield_per and process them in batches.
        Yields processed invoice data dictionaries.
        
        Args:
            query_info: Query object(s) and query type from _build_export_query
            status: Status filter
            batch_size: Number of rows to fetch per batch
            
        Yields:
            Processed invoice data dictionaries
        """
        query_obj, query_type = query_info
        
        # Note: QUERY_TYPE_* are module-level constants, not class attributes
        if query_type == QUERY_TYPE_PROCESSED_FAILED:
            # Single query returning PlumbingInvoice objects
            for row in query_obj.yield_per(batch_size):
                plumbing_invoice, plumbing_statement, plumbing_supplier, system_invoice_id = row
                
                # Determine status
                reconciliation_status = "Processed" if system_invoice_id else "Failed"
                
                # Apply status filter
                if status and status.lower() != STATUS_ALL:
                    if status.lower() == STATUS_PROCESSED and not system_invoice_id:
                        continue
                    elif status.lower() == STATUS_FAILED and system_invoice_id:
                        continue
                
                
                yield {
                    'invoice_number': plumbing_invoice.invoice_number,
                    'invoice_date': plumbing_invoice.invoice_date.isoformat() if plumbing_invoice.invoice_date else None,
                    'statement_date': plumbing_statement.statement_date.isoformat() if plumbing_statement.statement_date else None,
                    'supplier_name': plumbing_supplier.name,
                    'status': reconciliation_status,
                    'original_amount': format_currency(plumbing_invoice.original_amount) if plumbing_invoice.original_amount else format_currency(0.0),
                    'balance': format_currency(plumbing_invoice.balance) if plumbing_invoice.balance else format_currency(0.0),
                    'invoice_id': plumbing_invoice.id,
                    'statement_id': plumbing_statement.id
                }
        
        elif query_type == QUERY_TYPE_UNLISTED:
            # Single query returning InvoiceItem data
            for row in query_obj.yield_per(batch_size):
                yield {
                    'invoice_number': row.ref_no,
                    'invoice_date': row.date.isoformat() if row.date else None,
                    'statement_date': None,
                    'supplier_name': row.supplier_name,
                    'status': 'Unlisted',
                    'original_amount': format_currency(row.amount) if row.amount else format_currency(0.0),
                    'balance': format_currency(0.0),
                    'system_invoice_id': row.invoice_id
                }
        
        elif query_type in (QUERY_TYPE_MISSING, QUERY_TYPE_ALL_COMBINED):
            # Multiple queries - iterate through each
            for query in query_obj:
                for row in query.yield_per(batch_size):
                    # Determine if this is system or statement data based on available attributes
                    if hasattr(row, 'system_invoice_id') and row.system_invoice_id:
                        # System invoice
                        yield {
                            'invoice_number': row.invoice_number,
                            'invoice_date': row.invoice_date.isoformat() if row.invoice_date else None,
                            'statement_date': None,
                            'supplier_name': row.supplier_name,
                            'status': 'Missing' if query_type == QUERY_TYPE_MISSING else 'Unlisted',
                            'original_amount': format_currency(row.original_amount) if row.original_amount else format_currency(0.0),
                            'balance': format_currency(0.0),
                            'system_invoice_id': row.system_invoice_id
                        }
                    else:
                        # Statement invoice
                        yield {
                            'invoice_number': row.invoice_number,
                            'invoice_date': row.invoice_date.isoformat() if row.invoice_date else None,
                            'statement_date': row.statement_date.isoformat() if hasattr(row, 'statement_date') and row.statement_date else None,
                            'supplier_name': row.supplier_name,
                            'status': 'Missing' if query_type == QUERY_TYPE_MISSING else 'Failed',
                            'original_amount': format_currency(row.original_amount) if row.original_amount else format_currency(0.0),
                            'balance': format_currency(row.balance) if hasattr(row, 'balance') and row.balance else format_currency(0.0),
                            'invoice_id': row.invoice_id if hasattr(row, 'invoice_id') else None,
                            'statement_id': row.statement_id if hasattr(row, 'statement_id') else None
                        }

    def export_monthly_statement(
        self,
        from_date: date,
        to_date: date,
        supplier_names: Optional[List[str]] = None,
        status: Optional[str] = None,
        excluded_invoice_ids: Optional[List[str]] = None
    ) -> str:
        """
        Export monthly statement data to Excel with invoice details using streaming.
        Uses yield_per for efficient memory usage with large datasets.
        Streams rows directly to Excel file as they come from the database.
        
        Args:
            from_date (date): Start date for the date range
            to_date (date): End date for the date range
            supplier_names (List[str], optional): List of supplier names or ['All'] for all suppliers
            status (str, optional): Invoice status filter - 'Processed', 'Failed', 'Unlisted', 'Missing', etc.
            excluded_invoice_ids (List[str], optional): Invoice IDs to exclude from export
            
        Returns:
            str: Presigned S3 URL for downloading the Excel file
        """
        try:
            import os
            import xlsxwriter
            from datetime import datetime
            from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
            from mpi_backend.utils.s3_utils import upload_export_and_get_url
            from fastapi import HTTPException
            
            logger.info(f"Starting STREAMING export with filters - from_date: {from_date}, to_date: {to_date}, "
                       f"supplier_names: {supplier_names}, status: {status}")
            
            # Separate excluded IDs into UUIDs and integers
            import uuid as uuid_lib
            excluded_ints = set()
            
            if excluded_invoice_ids:
                for id_str in excluded_invoice_ids:
                    try:
                        excluded_ints.add(int(id_str))
                    except (ValueError, TypeError):
                        raise HTTPException(
                            status_code=400, 
                            detail=f"Invalid excluded ID format: {id_str}. Must be integer."
                        )
                        
            
            # Determine filename first
            is_all_suppliers = (
                supplier_names is None or 
                len(supplier_names) == 0 or 
                'All' in supplier_names or
                (len(supplier_names) == 1 and supplier_names[0] in ['All', '', None])
            )
            is_single_supplier = not is_all_suppliers and len(supplier_names) == 1
            
            month_str = from_date.strftime('%Y-%m')
            upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            if is_all_suppliers:
                filename = f'MonthlyStatement_{month_str}_AllSuppliers.xlsx'
            elif is_single_supplier:
                clean_supplier = supplier_names[0].replace(' ', '').replace('/', '').replace('\\', '')[:30]
                filename = f'MonthlyStatement_{month_str}_{clean_supplier}.xlsx'
            else:
                filename = f'MonthlyStatement_{month_str}_AllSuppliers.xlsx'
            
            file_path = f'{upload_folder}{filename}'
            
            # Create Excel workbook and formats upfront
            workbook = xlsxwriter.Workbook(file_path, {'constant_memory': True})
            
            # Define formats
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D7E4BC',
                'border': 1,
                'align': 'center'
            })
            
            text_format = workbook.add_format({
                'num_format': '@',
                'border': 1,
                'align': 'left'
            })
            
            date_format = workbook.add_format({
                'num_format': 'yyyy-mm-dd',
                'border': 1,
                'align': 'center'
            })
            
            currency_format = workbook.add_format({
                'num_format': '$#,##0.00',
                'border': 1,
                'align': 'right'
            })
            
            # Track worksheets and row positions for each supplier
            supplier_worksheets = {}
            supplier_row_counts = {}
            supplier_data_for_sorting = {}  # Temporary storage for sorting before writing
            
            total_rows = 0
            parse_errors = []
            seen_keys = set()  # For deduplication
            
            logger.info("Starting to stream and write rows to Excel file...")
            
            # Build query for streaming with exclusions handled at database level
            query_info = self._build_export_query(from_date, to_date, supplier_names, status, excluded_ints)
            
            # First pass: collect and sort data per supplier (needed for proper sorting by invoice date)
            # We collect in batches and write periodically to reduce memory usage
            BATCH_SIZE = 1000  # Write to file every 50 rows per supplier
            
            for item in self._stream_and_process_rows(query_info, status):
                try:
                    # Deduplication key
                    key = (item.get('invoice_number'), item.get('supplier_name'), item.get('invoice_date'))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    
                    # Parse currency strings back to float for Excel formatting
                    original_amount_str = item.get('original_amount', '$0.00')
                    balance_str = item.get('balance', '$0.00')
                    
                    if not original_amount_str or original_amount_str == '':
                        original_amount_str = '$0.00'
                    if not balance_str or balance_str == '':
                        balance_str = '$0.00'
                    
                    try:
                        original_amount = float(str(original_amount_str).replace('$', '').replace(',', '').strip())
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"Failed to parse original_amount '{original_amount_str}': {e}")
                        original_amount = 0.0
                    
                    try:
                        balance = float(str(balance_str).replace('$', '').replace(',', '').strip())
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"Failed to parse balance '{balance_str}': {e}")
                        balance = 0.0
                    
                    supplier_name = item.get('supplier_name', 'Unknown')
                    
                    # Initialize supplier data if needed
                    if supplier_name not in supplier_data_for_sorting:
                        supplier_data_for_sorting[supplier_name] = []
                    
                    # Add row data
                    row_data = {
                        'invoice_number': item.get('invoice_number', ''),
                        'invoice_date': item.get('invoice_date', ''),
                        'statement_date': item.get('statement_date', ''),
                        'supplier_name': supplier_name,
                        'status': item.get('status', ''),
                        'original_amount': original_amount,
                        'balance': balance
                    }
                    
                    supplier_data_for_sorting[supplier_name].append(row_data)
                    total_rows += 1
                    
                    # Write batch to file if we've accumulated enough rows for this supplier
                    if len(supplier_data_for_sorting[supplier_name]) >= BATCH_SIZE:
                        self._write_supplier_batch_to_excel(
                            workbook, supplier_worksheets, supplier_row_counts,
                            supplier_name, supplier_data_for_sorting[supplier_name],
                            header_format, text_format, date_format, currency_format
                        )
                        # Clear the batch for this supplier
                        supplier_data_for_sorting[supplier_name] = []
                    
                    # Log progress every 10000 rows
                    if total_rows % 10000 == 0:
                        logger.info(f"Processed {total_rows} rows so far across {len(supplier_worksheets)} suppliers...")
                
                except Exception as e:
                    invoice_number = item.get('invoice_number', 'UNKNOWN')
                    logger.error(f"Error processing invoice #{invoice_number}: {str(e)}", exc_info=True)
                    parse_errors.append(f"Invoice #{invoice_number}: {str(e)}")
                    continue
            
            # Write any remaining batches
            for supplier_name, remaining_data in supplier_data_for_sorting.items():
                if remaining_data:
                    self._write_supplier_batch_to_excel(
                        workbook, supplier_worksheets, supplier_row_counts,
                        supplier_name, remaining_data,
                        header_format, text_format, date_format, currency_format
                    )
            
            logger.info(f"Completed streaming. Total rows written: {total_rows} across {len(supplier_worksheets)} suppliers")
            
            if parse_errors:
                logger.warning(f"Encountered {len(parse_errors)} parsing errors: {parse_errors[:10]}")
            
            # Close the workbook to finalize the file
            workbook.close()
            
            if total_rows == 0:
                logger.warning(f"No data found for filters")
                # Clean up empty file
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HTTPException(
                    status_code=404, 
                    detail="No statement invoice data found for the specified filters."
                )
            
            logger.info(f"Excel file written successfully: {file_path}")

            logger.info("Uploading to S3...")
            download_url = upload_export_and_get_url(file_path)

            logger.info(f"Export completed successfully. URL: {download_url}")
            return download_url

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error exporting monthly statement: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
    
    def _write_supplier_batch_to_excel(
        self,
        workbook,
        supplier_worksheets: dict,
        supplier_row_counts: dict,
        supplier_name: str,
        rows_data: list,
        header_format,
        text_format,
        date_format,
        currency_format
    ):
        """
        Write a batch of rows for a supplier to the Excel file.
        Creates worksheet if it doesn't exist, sorts data by invoice date, and writes rows.
        
        Args:
            workbook: xlsxwriter Workbook object
            supplier_worksheets: Dict mapping supplier names to worksheet objects
            supplier_row_counts: Dict tracking current row number for each supplier
            supplier_name: Name of the supplier
            rows_data: List of row data dictionaries to write
            header_format, text_format, date_format, currency_format: Excel format objects
        """
        # Sort rows by invoice_date ascending before writing
        rows_data.sort(key=lambda x: x.get('invoice_date', '') or '')
        
        # Create worksheet if it doesn't exist
        if supplier_name not in supplier_worksheets:
            # Create sheet name (max 31 chars for Excel)
            sheet_name = supplier_name[:31] if len(supplier_name) > 31 else supplier_name
            
            try:
                worksheet = workbook.add_worksheet(sheet_name)
            except Exception as e:
                logger.warning(f"Failed to create sheet '{sheet_name}': {e}. Using sanitized name.")
                # Sanitize sheet name more aggressively
                sheet_name = ''.join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_'))[:31]
                worksheet = workbook.add_worksheet(sheet_name)
            
            supplier_worksheets[supplier_name] = worksheet
            supplier_row_counts[supplier_name] = 0
            
            # Set column widths
            worksheet.set_column('A:A', 18)  # Invoice Number
            worksheet.set_column('B:B', 15)  # Invoice Date
            worksheet.set_column('C:C', 15)  # Statement Date
            worksheet.set_column('D:D', 25)  # Supplier Name
            worksheet.set_column('E:E', 12)  # Status
            worksheet.set_column('F:F', 15)  # Original Amount
            worksheet.set_column('G:G', 15)  # Balance
            
            # Write header row
            headers = ['Invoice Number', 'Invoice Date', 'Statement Date', 'Supplier Name', 'Status', 'Original Amount', 'Balance']
            for col_num, header in enumerate(headers):
                worksheet.write(0, col_num, header, header_format)
            
            supplier_row_counts[supplier_name] = 1  # Start after header
            
            logger.info(f"Created worksheet '{sheet_name}' for supplier '{supplier_name}'")
        
        worksheet = supplier_worksheets[supplier_name]
        current_row = supplier_row_counts[supplier_name]
        
        # Write data rows
        for row_data in rows_data:
            worksheet.write(current_row, 0, row_data['invoice_number'], text_format)
            worksheet.write(current_row, 1, row_data['invoice_date'], date_format)
            worksheet.write(current_row, 2, row_data['statement_date'], date_format)
            worksheet.write(current_row, 3, row_data['supplier_name'], text_format)
            worksheet.write(current_row, 4, row_data['status'], text_format)
            worksheet.write(current_row, 5, row_data['original_amount'], currency_format)
            worksheet.write(current_row, 6, row_data['balance'], currency_format)
            
            current_row += 1
        
        supplier_row_counts[supplier_name] = current_row
        logger.debug(f"Wrote {len(rows_data)} rows to '{supplier_name}' sheet (total: {current_row - 1} data rows)")

    def _format_monthly_statement_sheet(self, workbook, worksheet, df):
        """
        Apply formatting to monthly statement Excel sheet.
        
        Args:
            workbook: xlsxwriter Workbook object
            worksheet: xlsxwriter Worksheet object
            df: DataFrame with the data
        
        Columns:
            A: Invoice Number (text)
            B: Invoice Date (date)
            C: Statement Date (date)
            D: Supplier Name (text)
            E: Status (text)
            F: Original Amount (currency)
            G: Balance (currency)
        """
        # Header format
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D7E4BC',
            'border': 1,
            'align': 'center'
        })
        
        # Text format
        text_format = workbook.add_format({
            'num_format': '@',
            'border': 1,
            'align': 'left'
        })
        
        # Currency format
        currency_format = workbook.add_format({
            'num_format': '$#,##0.00',
            'border': 1,
            'align': 'right'
        })
        
        # Date format
        date_format = workbook.add_format({
            'num_format': 'yyyy-mm-dd',
            'border': 1,
            'align': 'center'
        })
        
        # Set column widths and formats
        worksheet.set_column('A:A', 18, text_format)  # Invoice Number
        worksheet.set_column('B:B', 15, date_format)  # Invoice Date
        worksheet.set_column('C:C', 15, date_format)  # Statement Date
        worksheet.set_column('D:D', 30, text_format)  # Supplier Name
        worksheet.set_column('E:E', 12, text_format)  # Status
        worksheet.set_column('F:F', 15, currency_format)  # Original Amount
        worksheet.set_column('G:G', 15, currency_format)  # Balance
        
        # Format header row
        for col_num, column in enumerate(df.columns):
            worksheet.write(0, col_num, column, header_format)
        
        # Apply autofilter
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    def export_selected_statements(
        self,
        invoice_ids: List[str]
    ) -> str:
        """
        Export specific statement invoices by their IDs to Excel.
        Intelligently handles three types of IDs:
        1. UUID - From Invoice table (parent invoice containing items)
        2. Integer invoice_id - From plumbing_invoices table (statement invoices)
        3. Integer item_id - From invoice_items table (individual items)
        
        Args:
            invoice_ids (List[str]): List of IDs - can be UUIDs or integers
            
        Returns:
            str: Presigned S3 URL for downloading the Excel file
        """
        try:
            import pandas as pd
            import os
            from datetime import datetime
            import uuid as uuid_lib
            from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
            from mpi_backend.utils.s3_utils import upload_export_and_get_url
            from fastapi import HTTPException
            
            if not invoice_ids:
                raise HTTPException(status_code=400, detail="invoice_ids list cannot be empty")
            
            # Separate UUIDs from integers
            uuid_ids = []
            integer_ids = []
            
            for id_str in invoice_ids:
                try:
                    # Try to parse as UUID first
                    uuid_obj = uuid_lib.UUID(id_str)
                    uuid_ids.append(uuid_obj)
                except (ValueError, AttributeError):
                    # Not a UUID, try as integer
                    try:
                        integer_ids.append(int(id_str))
                    except (ValueError, TypeError):
                        raise HTTPException(
                            status_code=400, 
                            detail=f"Invalid ID format: {id_str}. Must be UUID or integer."
                        )
            
            logger.info(f"Exporting {len(invoice_ids)} selected invoices - {len(uuid_ids)} UUIDs, {len(integer_ids)} integers")
            
            data = []
            seen_keys = set()
            
            # Step 1: Handle UUIDs - Query Invoice table to get all related InvoiceItems
            if uuid_ids:
                uuid_query = self.db.query(
                    InvoiceItem.ref_no,
                    InvoiceItem.date,
                    InvoiceItem.amount,
                    InvoiceItem.customer_job,
                    PlumbingSupplier.name.label('supplier_name'),
                    InvoiceItem.id,
                    Invoice.id.label('invoice_uuid')
                ).join(
                    Invoice,
                    InvoiceItem.invoice_id == Invoice.id
                ).join(
                    PlumbingSupplier,
                    Invoice.supplier_id == PlumbingSupplier.id
                ).filter(
                    Invoice.id.in_(uuid_ids)
                ).order_by(InvoiceItem.date.asc())
                
                uuid_results = uuid_query.all()
                logger.info(f"Found {len(uuid_results)} invoice items from {len(uuid_ids)} Invoice UUIDs")
                
                # Process invoice items from UUIDs
                for result in uuid_results:
                    key = (result.ref_no, result.supplier_name, result.date)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    
                    data.append({
                        'Invoice Number': str(result.ref_no) if result.ref_no else '',
                        'Invoice Date': result.date.strftime('%Y-%m-%d') if result.date else '',
                        'Statement Date': '',  # System invoices don't have statement date
                        'Supplier Name': result.supplier_name if result.supplier_name else '',
                        'Status': 'Unlisted',  # Invoice items are typically unlisted
                        'Original Amount': round(float(result.amount) if result.amount else 0.0, 2),
                        'Balance': 0.0,  # System invoices don't have balance
                        'Customer Job': result.customer_job or ''
                    })
            
            # Step 2: Query statement invoices (plumbing_invoices table) by integer invoice_id
            if integer_ids:
                statement_query = self.db.query(
                    PlumbingInvoice,
                    PlumbingStatement,
                    PlumbingSupplier,
                    InvoiceItem.id.label('system_invoice_id')
                ).join(
                    PlumbingStatement,
                    PlumbingInvoice.statement_id == PlumbingStatement.id
                ).join(
                    PlumbingSupplier,
                    PlumbingStatement.supplier_id == PlumbingSupplier.id
                ).outerjoin(
                    InvoiceItem,
                    and_(
                        InvoiceItem.ref_no == PlumbingInvoice.invoice_number,
                        InvoiceItem.date == PlumbingInvoice.invoice_date,
                        InvoiceItem.vendor == PlumbingSupplier.name
                    )
                ).filter(
                    PlumbingInvoice.id.in_(integer_ids)
                ).order_by(PlumbingInvoice.invoice_date.asc())
                
                statement_results = statement_query.all()
                logger.info(f"Found {len(statement_results)} statement invoices from integer IDs")
                
                # Process statement invoices
                for plumbing_invoice, plumbing_statement, plumbing_supplier, system_invoice_id in statement_results:
                    key = (plumbing_invoice.invoice_number, plumbing_supplier.name, plumbing_invoice.invoice_date)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    
                    reconciliation_status = "Processed" if system_invoice_id else "Failed"
                    
                    data.append({
                        'Invoice Number': str(plumbing_invoice.invoice_number) if plumbing_invoice.invoice_number else '',
                        'Invoice Date': plumbing_invoice.invoice_date.strftime('%Y-%m-%d') if plumbing_invoice.invoice_date else '',
                        'Statement Date': plumbing_statement.statement_date.strftime('%Y-%m-%d') if plumbing_statement.statement_date else '',
                        'Supplier Name': plumbing_supplier.name if plumbing_supplier.name else '',
                        'Status': reconciliation_status,
                        'Original Amount': round(float(plumbing_invoice.original_amount) if plumbing_invoice.original_amount else 0.0, 2),
                        'Balance': round(float(plumbing_invoice.balance) if plumbing_invoice.balance else 0.0, 2),
                        'Customer Job': plumbing_invoice.customer_po or ''
                    })
                
                # Step 3: Query invoice_items table for integer IDs not found in statement invoices
                # Only query for IDs not found in statement invoices
                found_statement_ids = {result[0].id for result in statement_results}
                remaining_ids = [id for id in integer_ids if id not in found_statement_ids]
            else:
                remaining_ids = []
            
            if remaining_ids:
                system_query = self.db.query(
                    InvoiceItem.ref_no,
                    InvoiceItem.date,
                    InvoiceItem.amount,
                    InvoiceItem.customer_job,
                    PlumbingSupplier.name.label('supplier_name'),
                    InvoiceItem.id
                ).join(
                    Invoice,
                    InvoiceItem.invoice_id == Invoice.id
                ).join(
                    PlumbingSupplier,
                    Invoice.supplier_id == PlumbingSupplier.id
                ).filter(
                    InvoiceItem.id.in_(remaining_ids)
                ).order_by(InvoiceItem.date.asc())
                
                system_results = system_query.all()
                logger.info(f"Found {len(system_results)} system-only invoices")
                
                # Process system invoices
                for result in system_results:
                    key = (result.ref_no, result.supplier_name, result.date)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    
                    data.append({
                        'Invoice Number': str(result.ref_no) if result.ref_no else '',
                        'Invoice Date': result.date.strftime('%Y-%m-%d') if result.date else '',
                        'Statement Date': '',  # System invoices don't have statement date
                        'Supplier Name': result.supplier_name if result.supplier_name else '',
                        'Status': 'Unlisted',  # System-only invoices are unlisted
                        'Original Amount': round(float(result.amount) if result.amount else 0.0, 2),
                        'Balance': 0.0,  # System invoices don't have balance
                        'Customer Job': result.customer_job or ''
                    })
            
            if not data:
                raise HTTPException(status_code=404, detail="No invoices found with the specified IDs")
            
            logger.info(f"Successfully collected {len(data)} invoices for export")
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Prepare file paths
            upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = f'MonthlyStatement_Selected_{timestamp}.xlsx'
            file_path = f'{upload_folder}{filename}'
            
            # Create Excel file with separate sheets per supplier
            with pd.ExcelWriter(file_path, engine='xlsxwriter') as writer:
                workbook = writer.book
                
                # Get unique suppliers and create a sheet for each
                suppliers = df['Supplier Name'].unique()
                suppliers = sorted(suppliers)
                
                for supplier in suppliers:
                    supplier_df = df[df['Supplier Name'] == supplier].copy()
                    supplier_df = supplier_df.sort_values('Invoice Date', ascending=True)
                    
                    # Create sheet name (max 31 chars for Excel)
                    sheet_name = supplier[:31] if len(supplier) > 31 else supplier
                    
                    # Write to sheet
                    supplier_df.to_excel(writer, sheet_name=sheet_name, index=False)
                    
                    # Get worksheet for formatting
                    worksheet = writer.sheets[sheet_name]
                    
                    # Apply formatting
                    self._format_monthly_statement_sheet(workbook, worksheet, supplier_df)
            
            download_url = upload_export_and_get_url(file_path)

            logger.info(f"Successfully exported {len(data)} invoices to {filename}")
            return download_url

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error exporting selected statements: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Export failed") from e
