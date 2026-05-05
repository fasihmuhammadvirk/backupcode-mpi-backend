#!/usr/bin/env python3
"""
Script to find and reprocess invoices with reference numbers that:
1. Do not start with "0"

This script uses the same technique as the reprocess endpoint:
- Uses invoice ID to fetch invoice from S3 (same as working reprocess endpoint)
- Downloads invoice to temporary file
- Extracts reference numbers using PDF to Excel extraction
- Updates only the reference numbers in database
- Cleans up temporary files
"""

import os
import sys
import logging
import re
import requests
import tempfile
from pathlib import Path
from typing import List, Dict, Any

# Add the parent directory to Python path to import mpi_backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from mpi_backend.database import get_db
from mpi_backend.database.models import Invoice, InvoiceItem, Supplier
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.utils.s3_utils import get_presigned_url
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.pdf_to_excel.extraction_util import extract_invoice_info
from mpi_backend.utils.pdf_to_excel.supreme_plumbing_util import extract_refno
from mpi_backend.utils.pdf_to_excel.ys_plumbing_processor import (
    extract_ref_no as ys_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.bmw_plumbing_processor import (
    extract_ref_no as bmw_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.lion_hvac_processor import (
    extract_ref_no as lion_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.af_supply_processor import (
    extract_ref_no as af_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.fw_webb_plumbing_processor import (
    extract_ref_no as fw_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.flow_mark_plumbing_processor import (
    extract_ref_no as flow_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.plumbing_exchange_processor import (
    extract_invoice_num as pe_extract_ref_no
)
from mpi_backend.utils.pdf_to_excel.gotham_plumbing_processor import (
    extract_invoice_no as gotham_extract_ref_no
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reprocess_non_zero_ref_numbers.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def _sanitize_path_component(component: str) -> str:
    """Sanitize a path component for filesystem safety"""
    import re
    # Remove or replace characters that are problematic in file paths
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', component)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(' .')
    # Replace multiple underscores with single underscore
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized

class ShortRefNumberReprocessor:
    """Handles finding and reprocessing invoices with reference numbers not starting with '0'

    This class provides functionality to find invoices with reference numbers
    that don't start with '0', then reprocess them to extract and update only 
    the reference numbers.
    """

    def __init__(self):
        self.db = None
        self.supplier_ref_extractors = {
            'Supreme Plumbing Supply': self._extract_supreme_ref,
            'Y & S Plumbing Supply': self._extract_ys_ref,
            'BMW Plumbing Supplies': self._extract_bmw_ref,
            'Lion Hvac Supplies': self._extract_lion_ref,
            'AF Supply': self._extract_af_ref,
            'FW Webb Plumbing Supply': self._extract_fw_ref,
            'Flow Mark Plumbing Supply': self._extract_flow_ref,
            'Plumbing Exchange': self._extract_pe_ref,
            'Gotham Plumbing Supply': self._extract_gotham_ref,
        }

    def _get_db_session(self):
        """Get database session"""
        if self.db is None:
            self.db = next(get_db())
        return self.db
    
    def _download_invoice_from_s3(self, supplier_name: str, invoice_id: str, filename: str) -> str:
        """
        Download invoice from S3 using same path structure as reprocess endpoint
        
        Args:
            supplier_name: Name of the supplier
            invoice_id: ID of the invoice (used as S3 key)
            filename: Original filename of the invoice
            
        Returns:
            str: Local file path of downloaded invoice, or empty string if failed
        """
        try:
            # Get presigned URL for the invoice using invoice_id as key (same as working endpoint)
            file_key = f'{supplier_name}/{invoice_id}'
            s3_url = get_presigned_url(file_key=file_key)
            
            if not s3_url:
                logger.error(f"Could not get S3 URL for {file_key}")
                return ""
            
            # Create upload directory (same as reprocess endpoint)
            safe_supplier = _sanitize_path_component(supplier_name)
            upload_folder = os.path.join(INVOICE_DOWNLOAD_FOLDER, safe_supplier)
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            # Download the file to the same location as reprocess endpoint
            file_path = os.path.join(upload_folder, filename)
            response = requests.get(s3_url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to download invoice {invoice_id} from S3: {response.status_code}")
                return ""
            
            # Write file to the same location as reprocess endpoint
            with open(file_path, 'wb') as file:
                file.write(response.content)
            
            logger.info(f"Downloaded invoice {invoice_id} from S3 to {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error downloading invoice {invoice_id} from S3: {e}")
            return ""
    
    def find_invoices_with_short_ref_numbers(self) -> List[Dict[str, Any]]:
        """
        Find all invoices with reference numbers that:
        - Do not start with "0"
        """
        db = self._get_db_session()

        # Query to find invoices with reference numbers not starting with "0"
        query = db.query(
            Invoice.id,
            Invoice.filename,
            Invoice.storage_path,
            Invoice.date,
            Supplier.supplier_name,
            InvoiceItem.ref_no
        ).join(
            Supplier, Invoice.supplier_id == Supplier.id
        ).join(
            InvoiceItem, Invoice.id == InvoiceItem.invoice_id
        ).filter(
            InvoiceItem.is_active.is_(True),
            InvoiceItem.ref_no.isnot(None),
            InvoiceItem.ref_no != '',
            ~InvoiceItem.ref_no.like('0%')  # Does not start with 0
        ).distinct()

        # Get all results
        all_invoices = query.all()
        invoices_to_reprocess = []

        for invoice in all_invoices:
            ref_no = str(invoice.ref_no).strip()
            invoices_to_reprocess.append({
                'invoice_id': invoice.id,
                'filename': invoice.filename,
                'storage_path': invoice.storage_path,
                'date': invoice.date,
                'supplier_name': invoice.supplier_name,
                'current_ref_no': ref_no
            })

        logger.info(f"Found {len(invoices_to_reprocess)} invoices with reference "
                    f"numbers not starting with '0'")
        return invoices_to_reprocess
    
    def _extract_supreme_ref(self, file_path: str) -> str:
        """Extract reference number for Supreme Plumbing Supply"""
        try:
            return extract_refno(file_path)
        except Exception as e:
            logger.error(f"Error extracting Supreme ref from {file_path}: {e}")
            return ""

    def _extract_ys_ref(self, file_path: str) -> str:
        """Extract reference number for Y & S Plumbing Supply"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return ys_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting Y&S ref from {file_path}: {e}")
            return ""

    def _extract_bmw_ref(self, file_path: str) -> str:
        """Extract reference number for BMW Plumbing Supplies"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return bmw_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting BMW ref from {file_path}: {e}")
            return ""

    def _extract_lion_ref(self, file_path: str) -> str:
        """Extract reference number for Lion Hvac Supplies"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return lion_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting Lion ref from {file_path}: {e}")
            return ""

    def _extract_af_ref(self, file_path: str) -> str:
        """Extract reference number for AF Supply"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return af_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting AF ref from {file_path}: {e}")
            return ""

    def _extract_fw_ref(self, file_path: str) -> str:
        """Extract reference number for FW Webb Plumbing Supply"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return fw_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting FW ref from {file_path}: {e}")
            return ""

    def _extract_flow_ref(self, file_path: str) -> str:
        """Extract reference number for Flow Mark Plumbing Supply"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return flow_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting Flow ref from {file_path}: {e}")
            return ""

    def _extract_pe_ref(self, file_path: str) -> str:
        """Extract reference number for Plumbing Exchange"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = doc[0].get_text()
            doc.close()
            return pe_extract_ref_no(text)
        except Exception as e:
            logger.error(f"Error extracting PE ref from {file_path}: {e}")
            return ""

    def _extract_gotham_ref(self, file_path: str) -> str:
        """Extract reference number for Gotham Plumbing Supply"""
        try:
            # Gotham's extract_invoice_no function expects a table, not text
            import tabula
            tables = tabula.read_pdf(file_path, pages="all", stream=True)
            if tables:
                return gotham_extract_ref_no(tables[0])
            return ""
        except Exception as e:
            logger.error(f"Error extracting Gotham ref from {file_path}: {e}")
            return ""

    def _extract_generic_ref(self, file_path: str) -> str:
        """Generic reference number extraction using main extractor"""
        try:
            # Use the main extraction utility
            invoice_num, _ = extract_invoice_info(file_path)
            return str(invoice_num) if invoice_num else ""
        except Exception as e:
            logger.error(f"Error extracting generic ref from {file_path}: {e}")
            return ""
    
    def extract_new_reference_number(self, file_path: str,
                                     supplier_name: str) -> str:
        """
        Extract new reference number from PDF file using appropriate extractor
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return ""

        # Use supplier-specific extractor if available
        if supplier_name in self.supplier_ref_extractors:
            new_ref = self.supplier_ref_extractors[supplier_name](file_path)
        else:
            # Fall back to generic extraction
            new_ref = self._extract_generic_ref(file_path)

        # Clean and validate the reference number
        if new_ref:
            new_ref = str(new_ref).strip()
            # Remove any leading/trailing whitespace and special characters
            new_ref = re.sub(r'^[^\w\d]+|[^\w\d]+$', '', new_ref)

        return new_ref

    def update_invoice_reference_number(self, invoice_id: str, new_ref_no: str) -> bool:
        """
        Update the reference number for all items in an invoice
        """
        try:
            db = self._get_db_session()
            controller = InvoiceItemController(db)

            updated_count = controller.update_invoice_reference_number(
                invoice_id, new_ref_no
            )

            if updated_count > 0:
                logger.info(f"Successfully updated {updated_count} items for "
                            f"invoice {invoice_id} with new ref: {new_ref_no}")
                return True
            else:
                logger.warning(f"No items updated for invoice {invoice_id}")
                return False

        except Exception as e:
            logger.error(f"Error updating reference number for invoice "
                         f"{invoice_id}: {e}")
            return False
    
    def reprocess_invoices(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Main method to find and reprocess invoices with reference numbers not starting with '0'

        Args:
            dry_run: If True, only log what would be done without making changes

        Returns:
            Dictionary with processing results
        """
        results = {
            'total_found': 0,
            'successfully_processed': 0,
            'failed': 0,
            'skipped': 0,
            'details': []
        }

        logger.info("Starting reprocessing of invoices with reference numbers "
                    "not starting with '0'")
        logger.info("Using same technique as reprocess endpoint: invoice ID -> S3 -> local storage -> extract ref number")
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made")

        # Find invoices with reference numbers not starting with '0'
        invoices_to_reprocess = self.find_invoices_with_short_ref_numbers()
        results['total_found'] = len(invoices_to_reprocess)

        if not invoices_to_reprocess:
            logger.info("No invoices found with reference numbers not starting with '0'")
            return results

        logger.info(f"Found {len(invoices_to_reprocess)} invoices to process")

        for invoice_data in invoices_to_reprocess:
            invoice_id = invoice_data['invoice_id']
            filename = invoice_data['filename']
            supplier_name = invoice_data['supplier_name']
            current_ref = invoice_data['current_ref_no']

            logger.info(f"Processing invoice {invoice_id}: {filename} "
                        f"(Current ref: {current_ref})")

            # Download invoice from S3 using invoice_id (same as reprocess endpoint)
            file_path = self._download_invoice_from_s3(supplier_name, invoice_id, filename)
            
            if not file_path:
                logger.error(f"Failed to download invoice {invoice_id} from S3")
                results['failed'] += 1
                results['details'].append({
                    'invoice_id': invoice_id,
                    'filename': filename,
                    'status': 'failed',
                    'reason': 'Failed to download from S3',
                    'current_ref': current_ref,
                    'new_ref': None
                })
                continue

            # Extract new reference number
            new_ref = self.extract_new_reference_number(file_path,
                                                        supplier_name)

            # Clean up downloaded file (same as reprocess endpoint)
            try:
                os.unlink(file_path)
                logger.debug(f"Cleaned up downloaded file: {file_path}")
            except Exception as e:
                logger.warning(f"Could not clean up downloaded file {file_path}: {e}")

            if not new_ref:
                logger.warning(f"Could not extract new reference number for "
                               f"{filename}")
                results['skipped'] += 1
                results['details'].append({
                    'invoice_id': invoice_id,
                    'filename': filename,
                    'status': 'skipped',
                    'reason': 'Could not extract new reference number',
                    'current_ref': current_ref,
                    'new_ref': None
                })
                continue

            # Check if the new reference number is different and valid
            if new_ref == current_ref:
                logger.info(f"Reference number unchanged for {filename}: "
                           f"{new_ref}")
                results['skipped'] += 1
                results['details'].append({
                    'invoice_id': invoice_id,
                    'filename': filename,
                    'status': 'skipped',
                    'reason': 'Reference number unchanged',
                    'current_ref': current_ref,
                    'new_ref': new_ref
                })
                continue


            logger.info(f"Extracted new reference number for {filename}: "
                       f"{current_ref} -> {new_ref}")

            if not dry_run:
                # Update the reference number in the database
                success = self.update_invoice_reference_number(invoice_id, new_ref)

                if success:
                    results['successfully_processed'] += 1
                    results['details'].append({
                        'invoice_id': invoice_id,
                        'filename': filename,
                        'status': 'success',
                        'reason': 'Successfully updated',
                        'current_ref': current_ref,
                        'new_ref': new_ref
                    })
                else:
                    results['failed'] += 1
                    results['details'].append({
                        'invoice_id': invoice_id,
                        'filename': filename,
                        'status': 'failed',
                        'reason': 'Database update failed',
                        'current_ref': current_ref,
                        'new_ref': new_ref
                    })
            else:
                # Dry run - just log what would be done
                results['successfully_processed'] += 1
                results['details'].append({
                    'invoice_id': invoice_id,
                    'filename': filename,
                    'status': 'would_update',
                    'reason': 'Would update (dry run)',
                    'current_ref': current_ref,
                    'new_ref': new_ref
                })

        # Log summary
        logger.info("Reprocessing complete:")
        logger.info(f"  Total found: {results['total_found']}")
        logger.info(f"  Successfully processed: {results['successfully_processed']}")
        logger.info(f"  Failed: {results['failed']}")
        logger.info(f"  Skipped: {results['skipped']}")

        return results

def main():
    """Main function to run the reprocessing script"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Reprocess invoices with reference numbers not starting with "0" (downloads from S3)'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Run in dry-run mode (no changes will be made)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create reprocessor instance
    reprocessor = ShortRefNumberReprocessor()

    try:
        # Run the reprocessing
        results = reprocessor.reprocess_invoices(dry_run=args.dry_run)

        # Print detailed results
        print("\n" + "="*80)
        print("REPROCESSING RESULTS")
        print("="*80)
        print(f"Total invoices found: {results['total_found']}")
        print(f"Successfully processed: {results['successfully_processed']}")
        print(f"Failed: {results['failed']}")
        print(f"Skipped: {results['skipped']}")

        if results['details']:
            print("\nDetailed Results:")
            print("-" * 80)
            for detail in results['details']:
                print(f"Invoice ID: {detail['invoice_id']}")
                print(f"  File: {detail['filename']}")
                print(f"  Status: {detail['status']}")
                print(f"  Reason: {detail['reason']}")
                print(f"  Current Ref: {detail['current_ref']}")
                print(f"  New Ref: {detail['new_ref']}")
                print()

        return 0 if results['failed'] == 0 else 1

    except Exception as e:
        logger.error(f"Fatal error during reprocessing: {e}")
        return 1
    finally:
        # Clean up database connection
        if reprocessor.db:
            reprocessor.db.close()


if __name__ == "__main__":
    exit(main())
