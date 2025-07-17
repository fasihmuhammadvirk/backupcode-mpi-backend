from datetime import datetime, date
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from math import ceil
import pandas as pd
# Setup temporary directory for reprocessing
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
import requests
import re
from pathlib import Path
import logging

from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement, PlumbingInvoice
)
from mpi_backend.database.models.invoice import Invoice
from mpi_backend.database.models.InvoiceItems import InvoiceItem

logger = logging.getLogger(__name__)

import sys
import os
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
                date_start = datetime.combine(invoice_date, datetime.min.time())
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
                
                overall_stats['total_statement_invoices'] += len(statement_invoices)
                # Convert to float only for calculation, keep string for output
                stmt_amount = float(statement.total_amount) if statement.total_amount else 0.0
                overall_stats['total_statement_amount'] += stmt_amount
                
                # Check each invoice in the statement
                for stmt_invoice in statement_invoices:
                    # Apply status filter if provided
                    if status and status.lower() != 'all':
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
                    if status and status.lower() != 'all':
                        if status.lower() == 'processed' and not match_result['matched']:
                            continue
                        elif status.lower() == 'failed' and match_result['matched']:
                            continue
                    
                    statement_result['invoices'].append(invoice_result)
                    
                    # Update stats
                    if match_result['matched']:
                        overall_stats['matched_invoices'] += 1
                        # Convert to float only for calculation
                        matched_amount = float(stmt_invoice.original_amount) if stmt_invoice.original_amount else 0.0
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
            
            if supplier_id:
                query = query.filter(PlumbingStatement.supplier_id == supplier_id)
            
            statements = query.order_by(
                PlumbingStatement.statement_date.desc()
            ).limit(limit).all()
            
            return [
                {
                    'id': stmt.id,
                    'supplier_name': stmt.supplier.name,
                    'statement_date': stmt.statement_date.isoformat() if stmt.statement_date else None,
                    'total_amount': float(stmt.total_amount) if stmt.total_amount else 0.0,
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
            from mpi_backend.database.models.invoice import Invoice
            
            # Handle special status filters BEFORE executing query
            if status and status.lower() == "unlisted":
                return self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
            if status and (status.lower() == "missing" or 
                          status.lower() == "missing system" or 
                          status.lower() == "missing statement"):
                return self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
            if status and status.lower() == "all":
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
            )
            
            # Apply date filters on invoice_date
            if from_date:
                query = query.filter(PlumbingInvoice.invoice_date >= from_date)
            if to_date:
                query = query.filter(PlumbingInvoice.invoice_date <= to_date)
            
            # Apply supplier filter - support ["All"], multiple supplier IDs, or supplier names
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        if supplier_id == 0:
                            supplier_conditions = []
                            break
                        else:
                            supplier_conditions.append(PlumbingSupplier.id == supplier_id)
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
                key = (plumbing_invoice.invoice_number, plumbing_supplier.name, plumbing_invoice.invoice_date)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                # Apply status filter
                if status and status.lower() != "all":
                    if status.lower() == "processed" and not system_invoice_id:
                        continue  # Skip if looking for processed but invoice doesn't exist in InvoiceItem
                    elif status.lower() == "failed" and system_invoice_id:
                        continue  # Skip if looking for failed but invoice exists in InvoiceItem
                filtered_results.append({
                    'plumbing_invoice': plumbing_invoice,
                    'plumbing_statement': plumbing_statement,
                    'plumbing_supplier': plumbing_supplier,
                    'status': reconciliation_status
                })
            # Sort by invoice_date desc
            filtered_results.sort(
                key=lambda x: x['plumbing_invoice'].invoice_date if x['plumbing_invoice'].invoice_date else date.min,
                reverse=True
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
                        float(plumbing_invoice.original_amount) 
                        if plumbing_invoice.original_amount else 0.0
                    ),
                    'balance': (
                        float(plumbing_invoice.balance) 
                        if plumbing_invoice.balance else 0.0
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
                        'all' if supplier_names and len(supplier_names) == 1 and supplier_names[0].lower() == 'all'
                        else 'all' if supplier_names and len(supplier_names) == 1 and supplier_names[0] == '0'
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
            logger.error(f"Error getting statement by ID {statement_id}: {str(e)}")
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
                    logger.error(f"Failed to generate presigned URL for {s3_key}")
                    
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
                            s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
                            logger.error(f"File exists in S3 but presigned URL generation failed for key: {s3_key}")
                            return {
                                'success': False,
                                'error': f'S3 file exists but could not generate download URL. This might be a permissions issue. S3 key: {s3_key}'
                            }
                        except s3_client.exceptions.NoSuchKey:
                            logger.error(f"File does not exist in S3. S3 key: {s3_key}")
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
                        logger.error(f"Failed to initialize S3 client: {str(config_error)}")
                        return {
                            'success': False,
                            'error': f'Could not generate download URL for statement PDF: {s3_key}. S3 client error: {str(config_error)}'
                        }
                
                logger.info(f"Successfully generated presigned URL for key: {s3_key}")
                    
            except Exception as e:
                logger.error(f"Failed to get presigned URL for {s3_key}: {str(e)}")
                return {
                    'success': False,
                    'error': f'Could not access statement PDF: {str(e)}'
                }
            
            
            # Create temporary folder
            temp_dir = Path(INVOICE_DOWNLOAD_FOLDER) / "temp_reprocess" / f"statement_{statement_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Download the PDF file
            pdf_path = temp_dir / pdf_filename
            
            try:
                # Add retry logic for download
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = requests.get(statement_url, timeout=60)  # Increased timeout
                        if response.status_code == 200:
                            with open(pdf_path, 'wb') as f:
                                f.write(response.content)
                            logger.info(f"Downloaded PDF to {pdf_path} (attempt {attempt + 1})")
                            break
                        elif response.status_code == 404:
                            logger.error(f"PDF not found on S3 (404) - URL may be expired or file doesn't exist")
                            return {
                                'success': False,
                                'error': f'PDF not found on S3 (404). The file may not exist or the URL has expired. S3 key: {s3_key}'
                            }
                        else:
                            logger.warning(f"Download attempt {attempt + 1} failed with status {response.status_code}")
                            if attempt == max_retries - 1:
                                return {
                                    'success': False,
                                    'error': f'Failed to download PDF after {max_retries} attempts. Last status: {response.status_code}'
                                }
                    except requests.exceptions.Timeout:
                        logger.warning(f"Download attempt {attempt + 1} timed out")
                        if attempt == max_retries - 1:
                            return {
                                'success': False,
                                'error': f'Download timed out after {max_retries} attempts'
                            }
                    except Exception as download_error:
                        logger.warning(f"Download attempt {attempt + 1} failed: {str(download_error)}")
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
            logger.info(f"Deleting existing records for statement {statement_id}")
            try:
                # Check if statement still exists (might have been deleted by another process)
                existing_statement = self.db.query(PlumbingStatement).filter(
                    PlumbingStatement.id == statement_id
                ).first()
                
                if not existing_statement:
                    logger.warning(f"Statement {statement_id} no longer exists in database")
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
                        logger.warning(f"Statement {statement_id} was already deleted")
                    else:
                        logger.info(f"Deleted statement {statement_id} and {invoice_count} associated invoices")
                
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
                from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
                
                # FRESH SUPPLIER DETECTION: Don't use old (potentially wrong) supplier
                # Instead, let the system re-detect supplier from filename and PDF
                old_supplier_name = statement_info['supplier_name']
                logger.info(f" REPROCESSING: Old supplier was: {old_supplier_name}")
                logger.info(f" FRESH DETECTION: Re-detecting supplier from filename and PDF content...")
                
                # Try to detect supplier from filename first (using our improved logic)
                filename_detected_supplier = self._detect_supplier_from_filename(pdf_filename)
                if filename_detected_supplier:
                    logger.info(f" Filename detected supplier: {filename_detected_supplier}")
                else:
                    logger.warning(f"  Could not detect supplier from filename: {pdf_filename}")
                
                # Create extractor with the new unified interface
                extractor = StatementExtractor(
                    pdf_path=str(pdf_path),
                    supplier_name=filename_detected_supplier  # Use filename-detected or None for PDF detection
                )
                
                # Extract data using the new unified method
                result = extractor.extract_full_statement()
                
                if result['invoice_data'].empty:
                    logger.error(f"No invoice data extracted from PDF: {pdf_path}")
                    return {
                        'success': False,
                        'error': 'Failed to extract invoice data from PDF. The PDF might be corrupted, empty, or in an unsupported format.'
                    }
                
                logger.info(f"Successfully extracted {len(result['invoice_data'])} invoices from PDF")
                
                # Get detected supplier from metadata
                detected_supplier = result['metadata'].get('supplier_name', '')
                logger.info(f" FINAL DETECTED SUPPLIER: {detected_supplier}")
                
                # Compare with old assignment
                if old_supplier_name != detected_supplier:
                    logger.warning(f" SUPPLIER CHANGE DETECTED!")
                    logger.warning(f"   OLD: {old_supplier_name}")
                    logger.warning(f"   NEW: {detected_supplier}")
                    logger.warning(f"   This indicates the previous assignment was incorrect!")
                else:
                    logger.info(f" Supplier assignment confirmed: {detected_supplier}")
                
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
                        logger.error(f"Supplier {final_supplier_name} not found in database")
                        return {
                            'success': False,
                            'error': f'Supplier {final_supplier_name} not found in database'
                        }
                    
                    # Create new statement
                    
                    new_statement = PlumbingStatement(
                        supplier_id=supplier.id,
                        statement_date=result['metadata'].get('statement_date'),
                        account_number=result['metadata'].get('account_number', ''),
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
                            invoice_number=str(row['Invoice Number']) if pd.notna(row['Invoice Number']) else None,
                            invoice_date=row.get('Invoice Date'),
                            customer_po=str(row.get('Customer PO', '')) if pd.notna(row.get('Customer PO')) else None,
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
                    logger.error(f"Failed to save to database: {str(db_error)}")
                    logger.error(f"Database error details: {type(db_error).__name__}: {str(db_error)}")
                    return {
                        'success': False,
                        'error': f'Failed to save to database: {str(db_error)}. Please check if the supplier exists and the data format is correct.'
                    }
                
                logger.info(f"Successfully reprocessed statement. New ID: {new_statement_id}, Invoices: {new_invoice_count}")
                
                # Clean up temporary files
                try:
                    import shutil
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up {temp_dir}: {str(cleanup_error)}")
                
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
                temp_dir = Path(INVOICE_DOWNLOAD_FOLDER) / "temp_reprocess" / f"statement_{statement_id}"
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
            logger.warning(f"Could not detect supplier from filename {filename}: {str(e)}")
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
                logger.warning(f"Supplier {supplier_name} not found in database")
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
            logger.info(f"Starting bulk reprocessing - Supplier: {supplier_name or 'All'}, Max: {max_statements}")
            
            # Build query for statements to reprocess with eager loading of supplier
            query = self.db.query(PlumbingStatement).options(joinedload(PlumbingStatement.supplier))
            
            # Apply supplier filter if provided
            if supplier_name:
                if supplier_name.isdigit():
                    supplier_id = int(supplier_name)
                    # Handle supplier_id = 0 as "all suppliers" - skip filtering
                    if supplier_id != 0:
                        # Filter by specific supplier ID
                        query = query.filter(PlumbingStatement.supplier_id == supplier_id)
                    # If supplier_id == 0, don't apply any filter (all suppliers)
                else:
                    # Filter by supplier name (partial match) - need to join for this
                    query = query.join(PlumbingSupplier).filter(
                        PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                    )
            
            # Order by most recent first and limit
            statements = query.order_by(PlumbingStatement.statement_date.desc()).limit(max_statements).all()
            
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
                    logger.info(f"Processing statement {idx}/{len(statements)} - ID: {statement.id}")
                    
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
                        new_supplier_name = details.get('supplier_name', old_supplier_name)
                        supplier_changed = details.get('supplier_changed', False)
                        
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
                            logger.warning(f" Statement {statement.id} reprocessed successfully - SUPPLIER CHANGED!")
                            logger.warning(f"   OLD: {old_supplier_name} → NEW: {new_supplier_name}")
                        else:
                            logger.info(f" Statement {statement.id} reprocessed successfully - supplier confirmed: {new_supplier_name}")
                    else:
                        statement_result.update({
                            'supplier_name': old_supplier_name,  # Keep old if reprocessing failed
                            'supplier_changed': False,
                            'error': result.get('error', 'Unknown error')
                        })
                        statistics['failed'] += 1
                        statistics['errors'].append(f"Statement {statement.id}: {result.get('error', 'Unknown error')}")
                        logger.error(f" Statement {statement.id} reprocessing failed: {result.get('error')}")
                    
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
            success_rate = (statistics['successful'] / statistics['total_statements']) * 100 if statistics['total_statements'] > 0 else 0
            supplier_change_count = statistics['supplier_changes']
            
            logger.info(f"Bulk reprocessing completed: {statistics['successful']}/{statistics['total_statements']} successful ({success_rate:.1f}%)")
            if supplier_change_count > 0:
                logger.warning(f" SUPPLIER CHANGES: {supplier_change_count} statements had supplier corrections!")
                logger.warning("   This indicates previous misassignments that have now been fixed.")
            else:
                logger.info(" No supplier changes detected - all assignments were already correct.")
            
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
            if status and status.lower() == "unlisted":
                # For unlisted, search system invoices not in statements
                unlisted_results = self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
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
                    unlisted_results['data'] = filtered_data
                    unlisted_results['pagination']['total_results'] = len(filtered_data)
                    unlisted_results['filters_applied']['search'] = search
                
                return unlisted_results

            if status and (status.lower() == "missing" or 
                          status.lower() == "missing system" or 
                          status.lower() == "missing statement"):
                # For missing, search invalid invoices
                missing_results = self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
                
                # Filter by search term with priority for "starts with" matches
                if missing_results['success']:
                    filtered_data = [
                        item for item in missing_results['data']
                        if item['invoice_number'] != "MISSING" and
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
                    missing_results['data'] = filtered_data
                    missing_results['pagination']['total_results'] = len(filtered_data)
                    missing_results['filters_applied']['search'] = search
                
                return missing_results

            if status and status.lower() == "all":
                # For all status, search across all invoice types
                all_results = self.get_all_invoices_combined(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
                
                # Filter by search term with priority for "starts with" matches
                if all_results['success']:
                    filtered_data = [
                        item for item in all_results['data']
                        if item['invoice_number'] != "MISSING" and
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
                    all_results['data'] = filtered_data
                    all_results['pagination']['total_results'] = len(filtered_data)
                    all_results['filters_applied']['search'] = search
                
                return all_results

            # For default search (Processed/Failed/No specific status)
            # Search in BOTH statement invoices AND system invoices
            
            all_matching_invoices = []
            
            # 1. Search in PlumbingInvoice (statement invoices)
            # Use OR condition to prioritize "starts with" matches first
            statement_query = (
                self.db.query(PlumbingInvoice, PlumbingStatement, PlumbingSupplier)
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
                .filter(
                    or_(
                        PlumbingInvoice.invoice_number.ilike(f"{search}%"),  # Starts with
                        PlumbingInvoice.invoice_number.ilike(f"%{search}%")   # Contains
                    )
                )
            )
            
            # Apply filters to statement query
            if from_date:
                statement_query = statement_query.filter(PlumbingInvoice.invoice_date >= from_date)
            if to_date:
                statement_query = statement_query.filter(PlumbingInvoice.invoice_date <= to_date)
            
            # Apply supplier filter to statement query
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        if supplier_id == 0:
                            supplier_conditions = []
                            break
                        else:
                            supplier_conditions.append(PlumbingSupplier.id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )
                
                if supplier_conditions:
                    statement_query = statement_query.filter(or_(*supplier_conditions))
            
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
                if status and status.lower() not in ["all", None]:
                    if status.lower() == "processed" and not match_result['matched']:
                        continue
                    elif status.lower() == "failed" and match_result['matched']:
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
            from mpi_backend.database.models.invoice import Invoice
            
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
                system_query = system_query.filter(InvoiceItem.date >= from_date)
            if to_date:
                system_query = system_query.filter(InvoiceItem.date <= to_date)
            
            # Apply supplier filter to system query
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        if supplier_id == 0:
                            supplier_conditions = []
                            break
                        else:
                            supplier_conditions.append(Invoice.supplier_id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )
                
                if supplier_conditions:
                    system_query = system_query.filter(or_(*supplier_conditions))
            
            # Exclude system invoices that are already in statement data to avoid duplicates
            statement_invoice_numbers = [plumbing_invoice.invoice_number for plumbing_invoice, _, _ in statement_results]
            if statement_invoice_numbers:
                system_query = system_query.filter(
                    ~InvoiceItem.ref_no.in_(statement_invoice_numbers)
                )
            
            # Get system results
            system_results = system_query.all()
            
            # Process system invoices (these are "Unlisted" status)
            for invoice_item, invoice, supplier in system_results:
                # Apply status filter if specified (system invoices are Unlisted)
                if status and status.lower() not in ["all", "unlisted", None]:
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
                    'original_amount': float(invoice_item.amount) if invoice_item.amount else 0.0,
                    'balance': 0.0,  # System invoices don't have balance
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
                date_priority = datetime.fromisoformat(x['invoice_date']) if x.get('invoice_date') else datetime.min
                
                return (starts_with_priority, date_priority)
            
            all_matching_invoices.sort(key=sort_key, reverse=False)
            
            # Apply pagination
            total_count = len(all_matching_invoices)
            offset = (page - 1) * page_size
            paginated_invoices = all_matching_invoices[offset:offset + page_size]
            
            logger.info(f"Search completed - Found {total_count} total matches, returning {len(paginated_invoices)} for page {page}")
            
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
            from mpi_backend.database.models.invoice import Invoice
            
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
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                supplier_conditions = []
                for supplier_name in supplier_names:
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        if supplier_id == 0:
                            supplier_conditions = []
                            break
                        else:
                            supplier_conditions.append(Invoice.supplier_id == supplier_id)
                    else:
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )
                if supplier_conditions:
                    query = query.filter(or_(*supplier_conditions))
            
            # Exclude invoices that exist in statement data (PlumbingInvoice)
            subquery = self.db.query(PlumbingInvoice.invoice_number).subquery()
            query = query.filter(~InvoiceItem.ref_no.in_(subquery))
            
            # Get total count for pagination
            total_count = query.count()
            
            # Order by date (most recent first) and apply pagination
            query = query.order_by(InvoiceItem.date.desc())
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
            
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                for supplier_name in supplier_names:
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        if supplier_id != 0:
                            supplier_conditions_system.append(Invoice.supplier_id == supplier_id)
                            supplier_conditions_statement.append(PlumbingStatement.supplier_id == supplier_id)
                    else:
                        supplier_conditions_system.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
                        supplier_conditions_statement.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
            
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
                system_query = system_query.filter(InvoiceItem.date >= from_date)
            if to_date:
                system_query = system_query.filter(InvoiceItem.date <= to_date)
            if supplier_conditions_system:
                system_query = system_query.filter(or_(*supplier_conditions_system))
            
            # Order system query (no limit for comprehensive data)
            system_query = system_query.order_by(InvoiceItem.date.desc())
            
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
            
            # Apply filters to statement query
            if from_date:
                statement_query = statement_query.filter(PlumbingInvoice.invoice_date >= from_date)
            if to_date:
                statement_query = statement_query.filter(PlumbingInvoice.invoice_date <= to_date)
            if supplier_conditions_statement:
                statement_query = statement_query.filter(or_(*supplier_conditions_statement))
            
            # Order statement query (no limit for comprehensive data)
            statement_query = statement_query.order_by(PlumbingInvoice.invoice_date.desc())
            
            # Execute both queries
            system_invoices = system_query.all()
            statement_invoices = statement_query.all()
            
            logger.info(f"Missing/Invalid - Retrieved {len(system_invoices)} system invoices and {len(statement_invoices)} statement invoices")
            
            # Process and filter system invoices efficiently (no Python-level deduplication needed due to DISTINCT)
            missing_system_invoices = []
            for inv in system_invoices:
                # Use optimized validation helper
                if self._has_validation_issues_system(inv):
                    # Get detailed issues for response
                    issues = self._get_detailed_issues_system(inv)
                    
                    missing_system_invoices.append({
                        'invoice_number': inv.invoice_number or "MISSING",
                        'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
                        'customer_po': inv.customer_po,
                        'statement_date': None,
                        'supplier_name': inv.supplier_name,
                        'status': 'Missing System',
                        'original_amount': str(inv.original_amount) if inv.original_amount else "0",
                        'balance': "0",
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
                # Use optimized validation helper
                if self._has_validation_issues_statement(inv):
                    # Get detailed issues for response
                    issues = self._get_detailed_issues_statement(inv)
                    
                    missing_statement_invoices.append({
                        'invoice_number': inv.invoice_number or "MISSING",
                        'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
                        'customer_po': inv.customer_po,
                        'statement_date': inv.statement_date.isoformat() if inv.statement_date else None,
                        'supplier_name': inv.supplier_name,
                        'status': 'Missing Statement',
                        'original_amount': str(inv.original_amount) if inv.original_amount else "0",
                        'balance': str(inv.balance) if inv.balance else "0",
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
            
            # Sort by invoice_date (most recent first)
            all_missing_invoices.sort(key=lambda x: 
                datetime.fromisoformat(x['invoice_date']) if x.get('invoice_date') else datetime.min, 
                reverse=True
            )
            
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
            
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                for supplier_name in supplier_names:
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        if supplier_id != 0:
                            supplier_conditions_system.append(Invoice.supplier_id == supplier_id)
                            supplier_conditions_statement.append(PlumbingStatement.supplier_id == supplier_id)
                    else:
                        supplier_conditions_system.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
                        supplier_conditions_statement.append(PlumbingSupplier.name.ilike(f"%{supplier_name}%"))
            
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
                .filter(InvoiceItem.ref_no.isnot(None))  # Exclude null invoice numbers
                .distinct(InvoiceItem.ref_no, PlumbingSupplier.name, InvoiceItem.date)
            )
            
            # Apply filters to system query
            if from_date:
                system_base_query = system_base_query.filter(InvoiceItem.date >= from_date)
            if to_date:
                system_base_query = system_base_query.filter(InvoiceItem.date <= to_date)
            if supplier_conditions_system:
                system_base_query = system_base_query.filter(or_(*supplier_conditions_system))
            
            # Order system invoices (no limit for comprehensive data)
            system_base_query = system_base_query.order_by(InvoiceItem.date.desc())
            
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
                .filter(PlumbingInvoice.invoice_number.isnot(None))  # Exclude null invoice numbers
                .distinct(PlumbingInvoice.invoice_number, PlumbingSupplier.name, PlumbingInvoice.invoice_date)
            )
            
            # Apply filters to statement query
            if from_date:
                statement_base_query = statement_base_query.filter(PlumbingInvoice.invoice_date >= from_date)
            if to_date:
                statement_base_query = statement_base_query.filter(PlumbingInvoice.invoice_date <= to_date)
            if supplier_conditions_statement:
                statement_base_query = statement_base_query.filter(or_(*supplier_conditions_statement))
            
            # Order statement invoices (no limit for comprehensive data)
            statement_base_query = statement_base_query.order_by(PlumbingInvoice.invoice_date.desc())
            
            # Execute both queries
            system_invoices = system_base_query.all()
            statement_invoices = statement_base_query.all()
            
            logger.info(f"Retrieved {len(system_invoices)} system invoices and {len(statement_invoices)} statement invoices")
            
            # OPTIMIZED: Bulk check for statement matches using a single query
            system_invoice_numbers = [inv.invoice_number for inv in system_invoices if inv.invoice_number]
            statement_matches = set()
            if system_invoice_numbers:
                matched_statements = (
                    self.db.query(PlumbingInvoice.invoice_number)
                    .filter(PlumbingInvoice.invoice_number.in_(system_invoice_numbers))
                    .distinct()
                    .all()
                )
                statement_matches = {match.invoice_number for match in matched_statements}
            
            # OPTIMIZED: Bulk check for system matches using a single query
            statement_invoice_numbers = [inv.invoice_number for inv in statement_invoices if inv.invoice_number]
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
                    'original_amount': str(inv.original_amount) if inv.original_amount else "0",
                    'balance': "0",
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
                    'original_amount': str(inv.original_amount) if inv.original_amount else "0",
                    'balance': str(inv.balance) if inv.balance else "0",
                    'statement_id': inv.statement_id,
                    'invoice_id': inv.invoice_id,
                    'system_invoice_id': None,
                    'customer_job': None,
                    'source': 'statement'
                })
            all_invoices.sort(key=lambda x: (
                datetime.fromisoformat(x['invoice_date']) if x.get('invoice_date') else datetime.min,
                x['source'] == 'statement'  # False for system (comes first), True for statement
            ), reverse=True)
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
        
        # Check for tax format issues
        if invoice.description:
            desc_str = str(invoice.description).lower()
            if ("tax" in desc_str and 
                any(char.isalpha() for char in desc_str) and
                any(char.isdigit() for char in desc_str) and
                "$" in desc_str):
                if re.search(r'[a-zA-Z]+\s+tax\s+\d+\s*\$', desc_str):
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
                amount_str = str(invoice.original_amount).strip().replace(',', '')
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
        
        # Validate item description (system invoices only)
        if hasattr(invoice, 'item') and (not invoice.item or str(invoice.item).strip() == ""):
            issues.append("Missing Original Item")
        
        # Check for tax format issues
        if hasattr(invoice, 'description') and invoice.description:
            desc_str = str(invoice.description).lower()
            if ("tax" in desc_str and 
                any(char.isalpha() for char in desc_str) and
                any(char.isdigit() for char in desc_str) and
                "$" in desc_str):
                if re.search(r'[a-zA-Z]+\s+tax\s+\d+\s*\$', desc_str):
                    issues.append("Invalid Tax Format")
        
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
                amount_str = str(invoice.original_amount).strip().replace(',', '')
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