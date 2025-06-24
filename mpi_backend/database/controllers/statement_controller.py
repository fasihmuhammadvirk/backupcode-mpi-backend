from datetime import datetime, date
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, extract, func
from math import ceil
# Setup temporary directory for reprocessing
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
import tempfile
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
                    'system_amount': float(system_invoice.amount) if system_invoice.amount else 0.0,
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
                    'total_amount': float(statement.total_amount) if statement.total_amount else 0.0,
                    'total_invoices': len(statement_invoices),
                    'pdf_filename': statement.pdf_filename,
                    'invoices': []
                }
                
                overall_stats['total_statement_invoices'] += len(statement_invoices)
                overall_stats['total_statement_amount'] += float(statement.total_amount) if statement.total_amount else 0.0
                
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
                        'original_amount': float(stmt_invoice.original_amount) if stmt_invoice.original_amount else 0.0,
                        'payment_date': stmt_invoice.payment_date.isoformat() if stmt_invoice.payment_date else None,
                        'amount_paid': float(stmt_invoice.amount_paid) if stmt_invoice.amount_paid else 0.0,
                        'balance': float(stmt_invoice.balance) if stmt_invoice.balance else 0.0,
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
                        overall_stats['total_matched_amount'] += float(stmt_invoice.original_amount) if stmt_invoice.original_amount else 0.0
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
        
        Args:
            from_date: Start date filter (DD/MM/YYYY converted to date)
            to_date: End date filter (DD/MM/YYYY converted to date)
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            status: Invoice status filter (Processed/Failed)
            page: Page number (1-based)
            page_size: Number of items per page
            
        Returns:
            Dict with invoice data and pagination metadata
        """
        try:
            # Build base query joining all necessary tables
            query = (
                self.db.query(PlumbingInvoice, PlumbingStatement, PlumbingSupplier)
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
            )
            
            # Apply date filters on statement_date
            if from_date:
                query = query.filter(PlumbingStatement.statement_date >= from_date)
            if to_date:
                query = query.filter(PlumbingStatement.statement_date <= to_date)
            
            # Apply supplier filter - support ["All"], multiple supplier IDs, or supplier names
            # Handle supplier_id = 0 as "all suppliers"
            if supplier_names and not (len(supplier_names) == 1 and supplier_names[0].lower() == "all"):
                # Build OR conditions for multiple suppliers
                supplier_conditions = []
                
                for supplier_name in supplier_names:
                    # Check if supplier_name is a numeric ID
                    if supplier_name.isdigit():
                        supplier_id = int(supplier_name)
                        # Handle supplier_id = 0 as "all suppliers" - skip filtering
                        if supplier_id == 0:
                            # If any supplier_name is "0", treat as "all suppliers"
                            supplier_conditions = []
                            break
                        else:
                            # Filter by specific supplier ID
                            supplier_conditions.append(PlumbingSupplier.id == supplier_id)
                    else:
                        # Filter by supplier name (partial match)
                        supplier_conditions.append(
                            PlumbingSupplier.name.ilike(f"%{supplier_name}%")
                        )
                
                # Apply OR condition if any suppliers specified (and not "all suppliers")
                if supplier_conditions:
                    query = query.filter(or_(*supplier_conditions))
            
            # Get total count before pagination
            total_count = query.count()
            
            # Order by statement date (most recent first) BEFORE pagination
            query = query.order_by(PlumbingStatement.statement_date.desc())
            
            # Apply pagination
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)
            
            # Execute query
            results = query.all()
            
            # Handle "unlisted" status filter separately
            if status and status.lower() == "unlisted":
                # Return unlisted invoices instead
                return self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
            
            # Handle "missing" status filter separately
            if status and status.lower() == "missing":
                # Return missing/invalid invoices instead
                return self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
            
            # Process results and apply status filter if needed
            invoice_data = []
            for plumbing_invoice, plumbing_statement, plumbing_supplier in results:
                # Determine reconciliation status by checking system
                reconciliation_status = "Unknown"
                if status:
                    # Check if invoice exists in system for status filtering
                    match_result = self.check_invoice_exists_in_system(
                        plumbing_invoice.invoice_number,
                        plumbing_supplier.id,
                        plumbing_invoice.invoice_date
                    )
                    reconciliation_status = "Processed" if match_result['matched'] else "Failed"
                    
                    # Apply status filter
                    if status.lower() != "all":
                        if status.lower() == "processed" and not match_result['matched']:
                            continue
                        elif status.lower() == "failed" and match_result['matched']:
                            continue
                
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
            
            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1
            
            return {
                'success': True,
                'data': invoice_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': len(invoice_data),  # Actual results after status filter
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'supplier_filter_type': (
                        'all' if supplier_names and len(supplier_names) == 1 and supplier_names[0].lower() == 'all'
                        else 'all' if supplier_names and len(supplier_names) == 1 and supplier_names[0] == '0'
                        else 'multiple' if supplier_names and len(supplier_names) > 1
                        else 'id' if supplier_names and len(supplier_names) == 1 and supplier_names[0].isdigit()
                        else 'name' if supplier_names and len(supplier_names) == 1
                        else None
                    ),
                    'status': status
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
            s3_key = f"statements/{pdf_filename}"
            
            try:
                from mpi_backend.utils.s3_utils import get_presigned_url
                statement_url = get_presigned_url(
                    file_key=s3_key,
                    expiration_time=300,  # 5 minutes
                    is_invoice=False
                )
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
                response = requests.get(statement_url, timeout=30)
                if response.status_code != 200:
                    return {
                        'success': False,
                        'error': f'Failed to download PDF: Status {response.status_code}'
                    }
                
                with open(pdf_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"Downloaded PDF to {pdf_path}")
                
            except Exception as e:
                logger.error(f"Failed to download PDF: {str(e)}")
                return {
                    'success': False,
                    'error': f'Failed to download PDF: {str(e)}'
                }
            
            # Delete existing statement and invoice records
            logger.info(f"Deleting existing records for statement {statement_id}")
            try:
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
                    return {
                        'success': False,
                        'error': f'Failed to delete statement {statement_id}'
                    }
                
                self.db.commit()
                logger.info(f"Deleted statement {statement_id} and {invoice_count} associated invoices")
                
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
                
                # Create extractor WITHOUT pre-set supplier name to allow fresh detection
                extractor = StatementExtractor(
                    pdf_path=str(pdf_path),
                    save_to_db=True,
                    save_to_excel=False,
                    db_session=self.db,
                    supplier_name=filename_detected_supplier  # Use filename-detected or None for PDF detection
                )
                
                # Verify what supplier was actually detected
                detected_supplier = extractor.detect_supplier()
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
                
                # Extract all pages
                extract_success = extractor.extract_all_pages()
                if not extract_success:
                    return {
                        'success': False,
                        'error': 'Failed to extract data from PDF'
                    }
                
                # Save to database
                db_success = extractor.save_to_database()
                if not db_success:
                    return {
                        'success': False,
                        'error': 'Failed to save extracted data to database'
                    }
                
                # Get the new statement ID
                new_statement_id = extractor.statement_obj.id if extractor.statement_obj else None
                new_invoice_count = len(extractor.combined_data) if hasattr(extractor, 'combined_data') else 0
                
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
        invoice_number: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None, 
        supplier_names: Optional[List[str]] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        Search statement invoice data by invoice number with optional filters
        
        Args:
            invoice_number: Invoice number to search (partial match supported)
            from_date: Start date filter (DD/MM/YYYY converted to date)
            to_date: End date filter (DD/MM/YYYY converted to date)
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            status: Invoice status filter (Processed/Failed)
            page: Page number (1-based)
            page_size: Number of items per page
            
        Returns:
            Dict with invoice data and pagination metadata
        """
        try:
            # Build base query joining all necessary tables
            query = (
                self.db.query(PlumbingInvoice, PlumbingStatement, PlumbingSupplier)
                .join(PlumbingStatement, PlumbingInvoice.statement_id == PlumbingStatement.id)
                .join(PlumbingSupplier, PlumbingStatement.supplier_id == PlumbingSupplier.id)
            )
            
            # Apply invoice number filter (primary filter)
            query = query.filter(
                PlumbingInvoice.invoice_number.ilike(f"%{invoice_number}%")
            )
            
            # Apply date filters on statement_date
            if from_date:
                query = query.filter(PlumbingStatement.statement_date >= from_date)
            if to_date:
                query = query.filter(PlumbingStatement.statement_date <= to_date)
            
            # Apply supplier filter - same logic as existing method
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
            
            # Get total count before pagination
            total_count = query.count()
            
            # Order by statement date (most recent first) BEFORE pagination
            query = query.order_by(PlumbingStatement.statement_date.desc())
            
            # Apply pagination
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)
            
            # Execute query
            results = query.all()
            
            # Handle "unlisted" status filter separately for search
            if status and status.lower() == "unlisted":
                # For search with unlisted status, we need to find system invoices
                # that match the invoice number but are not in statements
                unlisted_results = self.get_unlisted_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
                
                # Filter by invoice number
                if unlisted_results['success']:
                    filtered_data = [
                        item for item in unlisted_results['data']
                        if invoice_number.lower() in item['invoice_number'].lower()
                    ]
                    unlisted_results['data'] = filtered_data
                    unlisted_results['pagination']['total_results'] = len(filtered_data)
                    unlisted_results['filters_applied'] = {
                        'invoice_number': invoice_number,
                        'from_date': from_date.isoformat() if from_date else None,
                        'to_date': to_date.isoformat() if to_date else None,
                        'supplier_names': supplier_names,
                        'status': status
                    }
                
                return unlisted_results
            
            # Handle "missing" status filter separately for search
            if status and status.lower() == "missing":
                # For search with missing status, we need to find system invoices
                # with missing/invalid data that match the invoice number
                missing_results = self.get_missing_invalid_invoices(
                    from_date=from_date,
                    to_date=to_date,
                    supplier_names=supplier_names,
                    page=page,
                    page_size=page_size
                )
                
                # Filter by invoice number
                if missing_results['success']:
                    filtered_data = [
                        item for item in missing_results['data']
                        if item['invoice_number'] != "MISSING" and
                        invoice_number.lower() in item['invoice_number'].lower()
                    ]
                    missing_results['data'] = filtered_data
                    missing_results['pagination']['total_results'] = len(filtered_data)
                    missing_results['filters_applied'] = {
                        'invoice_number': invoice_number,
                        'from_date': from_date.isoformat() if from_date else None,
                        'to_date': to_date.isoformat() if to_date else None,
                        'supplier_names': supplier_names,
                        'status': status
                    }
                
                return missing_results
            
            # Process results and apply status filter if needed
            invoice_data = []
            for plumbing_invoice, plumbing_statement, plumbing_supplier in results:
                # Determine reconciliation status by checking system
                reconciliation_status = "Unknown"
                if status:
                    match_result = self.check_invoice_exists_in_system(
                        plumbing_invoice.invoice_number,
                        plumbing_supplier.id,
                        plumbing_invoice.invoice_date
                    )
                    reconciliation_status = "Processed" if match_result['matched'] else "Failed"
                    
                    # Apply status filter
                    if status.lower() != "all":
                        if status.lower() == "processed" and not match_result['matched']:
                            continue
                        elif status.lower() == "failed" and match_result['matched']:
                            continue
                
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
            
            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1
            
            return {
                'success': True,
                'data': invoice_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': len(invoice_data),
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
                },
                'filters_applied': {
                    'invoice_number': invoice_number,
                    'from_date': from_date.isoformat() if from_date else None,
                    'to_date': to_date.isoformat() if to_date else None,
                    'supplier_names': supplier_names,
                    'supplier_filter_type': (
                        'all' if supplier_names and len(supplier_names) == 1 and supplier_names[0].lower() == 'all'
                        else 'all' if supplier_names and len(supplier_names) == 1 and supplier_names[0] == '0'
                        else 'multiple' if supplier_names and len(supplier_names) > 1
                        else 'id' if supplier_names and len(supplier_names) == 1 and supplier_names[0].isdigit()
                        else 'name' if supplier_names and len(supplier_names) == 1
                        else None
                    ),
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
        Find invoices that exist in our system but are not in any statement
        
        Args:
            from_date: Start date filter (filters by invoice date)
            to_date: End date filter (filters by invoice date)
            supplier_names: List of supplier names/IDs or ["All"] for all suppliers
            page: Page number (1-based)
            page_size: Number of items per page
            
        Returns:
            Dict with unlisted invoice data and pagination metadata
        """
        try:
            # Build base query for system invoices
            query = (
                self.db.query(InvoiceItem, Invoice)
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
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
            
            # Exclude invoices that exist in statement data
            subquery = self.db.query(PlumbingInvoice.invoice_number).subquery()
            query = query.filter(~InvoiceItem.ref_no.in_(subquery))
            
            # Get total count before pagination
            total_count = query.count()
            
            # Order by date (most recent first)
            query = query.order_by(InvoiceItem.date.desc())
            
            # Apply pagination
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)
            
            # Execute query and get supplier info
            results = query.all()
            
            # Process results
            invoice_data = []
            for invoice_item, invoice in results:
                # Get supplier name
                supplier = self.db.query(PlumbingSupplier).filter(
                    PlumbingSupplier.id == invoice.supplier_id
                ).first()
                supplier_name = supplier.name if supplier else "Unknown"
                
                invoice_data.append({
                    'invoice_number': invoice_item.ref_no,
                    'invoice_date': (
                        invoice_item.date.isoformat() 
                        if invoice_item.date else None
                    ),
                    'customer_po': invoice_item.po_number,
                    'statement_date': None,  # No statement for unlisted items
                    'supplier_name': supplier_name,
                    'status': 'Unlisted',
                    'original_amount': float(invoice_item.amount) if invoice_item.amount else 0.0,
                    'balance': 0.0,  # System invoices don't have balance
                    'statement_id': None,
                    'invoice_id': None,
                    'system_invoice_id': str(invoice.id),
                    'customer_job': invoice_item.customer_job
                })
            
            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1
            
            return {
                'success': True,
                'data': invoice_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': len(invoice_data),
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
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
        Find invoices that exist in our system but have missing or invalid data
        
        Checks for missing or invalid:
        - Amount (null, empty, or non-numeric values)
        - Date (null values)
        - Tax information (malformed tax entries like "zinexx tax 004 $3.93")
        - Invoice Number (null, empty, or invalid patterns like "inv # 88992")
        - Original Item description (null or empty)
        
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
            # Build base query for system invoices
            query = (
                self.db.query(InvoiceItem, Invoice)
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .join(PlumbingSupplier, Invoice.supplier_id == PlumbingSupplier.id)
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
            
            # Order by date (most recent first)
            query = query.order_by(InvoiceItem.date.desc())
            
            # Execute query to get all invoice items (we'll filter in Python)
            all_results = query.all()
            
            # Filter results in Python for complex validation
            filtered_results = []
            for invoice_item, invoice in all_results:
                has_issues = False
                
                # Check for missing/invalid amount
                if not invoice_item.amount or invoice_item.amount == "":
                    has_issues = True
                else:
                    try:
                        float(str(invoice_item.amount).strip())
                    except (ValueError, TypeError):
                        has_issues = True
                
                # Check for missing date
                if not invoice_item.date:
                    has_issues = True
                
                # Check for missing/invalid invoice number
                if not invoice_item.ref_no or invoice_item.ref_no == "":
                    has_issues = True
                else:
                    ref_no_str = str(invoice_item.ref_no).strip().lower()
                    if (ref_no_str.startswith("inv #") or 
                        ref_no_str.startswith("invoice #") or
                        ref_no_str.startswith("inv#") or
                        " # " in ref_no_str):
                        has_issues = True
                
                # Check for missing item description
                if not invoice_item.item or invoice_item.item == "":
                    has_issues = True
                
                # Check for tax format issues
                if invoice_item.description:
                    desc_str = str(invoice_item.description).lower()
                    if ("tax" in desc_str and 
                        any(char.isalpha() for char in desc_str) and
                        any(char.isdigit() for char in desc_str) and
                        "$" in desc_str):
                        if re.search(r'[a-zA-Z]+\s+tax\s+\d+\s*\$', desc_str):
                            has_issues = True
                
                if has_issues:
                    filtered_results.append((invoice_item, invoice))
            
            # Get total count of filtered results
            total_count = len(filtered_results)
            
            # Apply pagination to filtered results
            offset = (page - 1) * page_size
            results = filtered_results[offset:offset + page_size]
            
            # Process results
            invoice_data = []
            for invoice_item, invoice in results:
                # Get supplier name
                supplier = self.db.query(PlumbingSupplier).filter(
                    PlumbingSupplier.id == invoice.supplier_id
                ).first()
                supplier_name = supplier.name if supplier else "Unknown"
                
                # Determine specific issues with enhanced validation
                issues = []
                
                # Validate amount (check if non-numeric or empty)
                if not invoice_item.amount or invoice_item.amount == "":
                    issues.append("Missing Amount")
                else:
                    # Check if amount contains non-numeric characters (except decimal point and minus sign)
                    amount_str = str(invoice_item.amount).strip()
                    try:
                        float(amount_str)
                    except (ValueError, TypeError):
                        issues.append("Invalid Amount Format")
                
                # Validate date
                if not invoice_item.date:
                    issues.append("Missing Date")
                
                # Validate invoice number pattern
                if not invoice_item.ref_no or invoice_item.ref_no == "":
                    issues.append("Missing Invoice Number")
                else:
                    ref_no_str = str(invoice_item.ref_no).strip().lower()
                    # Check for invalid patterns like "inv # 88992"
                    if (ref_no_str.startswith("inv #") or 
                        ref_no_str.startswith("invoice #") or
                        ref_no_str.startswith("inv#") or
                        " # " in ref_no_str):
                        issues.append("Invalid Invoice Number Format")
                
                # Validate original item description
                if not invoice_item.item or invoice_item.item == "":
                    issues.append("Missing Original Item")
                
                # Check for tax-related issues in description or memo fields
                if invoice_item.description:
                    desc_str = str(invoice_item.description).lower()
                    # Look for tax entries with invalid format like "zinexx tax 004 $3.93"
                    if ("tax" in desc_str and 
                        any(char.isalpha() for char in desc_str) and
                        any(char.isdigit() for char in desc_str) and
                        "$" in desc_str):
                        # Check if it's a malformed tax entry
                        if re.search(r'[a-zA-Z]+\s+tax\s+\d+\s*\$', desc_str):
                            issues.append("Invalid Tax Format")
                
                # Only include items that actually have issues
                if issues:
                    # Try to parse amount safely
                    safe_amount = 0.0
                    if invoice_item.amount:
                        try:
                            safe_amount = float(str(invoice_item.amount).strip())
                        except (ValueError, TypeError):
                            safe_amount = 0.0
                    
                    invoice_data.append({
                        'invoice_number': invoice_item.ref_no or "MISSING",
                        'invoice_date': (
                            invoice_item.date.isoformat() 
                            if invoice_item.date else None
                        ),
                        'customer_po': invoice_item.po_number,
                        'statement_date': None,  # No statement for missing/invalid items
                        'supplier_name': supplier_name,
                        'status': 'Missing/Invalid',
                        'original_amount': safe_amount,
                        'balance': 0.0,  # System invoices don't have balance
                        'statement_id': None,
                        'invoice_id': None,
                        'system_invoice_id': str(invoice.id),
                        'customer_job': invoice_item.customer_job,
                        'issues': issues,  # List of specific data issues
                        'item_description': invoice_item.item,
                        'vendor': invoice_item.vendor
                    })
            
            # Calculate pagination metadata
            total_pages = ceil(total_count / page_size) if page_size > 0 else 1
            
            return {
                'success': True,
                'data': invoice_data,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_results': len(invoice_data),
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1
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