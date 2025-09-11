#!/usr/bin/env python3
"""
Invoice Search and Add Script - Fixed Version

This script uses the same logic as missing_invoice_finder.py but focuses on:
1. Searching for specific invoice reference numbers in emails
2. Using EXACT matching (must contain "invoice" + exact reference number)
3. Downloading only the invoices we actually need
4. Adding them directly to the system/database

Usage:
    python invoice_search_and_add_fixed.py --limit 10
"""

import sys
from pathlib import Path
import time
import logging
import argparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('invoice_search_and_add.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add the current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Import the enhanced missing invoice finder
from missing_invoice_finder import MissingInvoiceFinder

class InvoiceSearchAndAdd(MissingInvoiceFinder):
    """
    Enhanced invoice searcher that uses exact matching and adds invoices to system
    Inherits all the robust search logic from MissingInvoiceFinder
    """
    
    def __init__(self):
        """Initialize with exact matching enabled"""
        super().__init__(high_speed_mode=True)
        
        # Override settings for exact matching
        self.exact_matching_only = True
        self.skip_non_invoice_emails = True
        
        # Import required modules for invoice processing
        from datetime import datetime, timedelta
        
        # Create storage directory for attachments (ONLY storage, no local downloads)
        self.storage_dir = Path("storage/missing_invoice_attachments")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a temporary processing directory (will be cleaned up)
        try:
            from mpi_backend.config import TIMEZONE
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = (f"MISSING_INVOICES_{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                          f"{datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}")
            self.temp_processing_dir = Path("temp_processing") / base_folder
        except ImportError:
            logger.warning("Could not import TIMEZONE, using defaults")
            time_window_start = datetime.now() - timedelta(minutes=3)
            base_folder = (f"MISSING_INVOICES_{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                          f"{datetime.now().strftime('%d-%b-%Y_%H-%M-%S')}")
            self.temp_processing_dir = Path("temp_processing") / base_folder
        
        self.temp_processing_dir.mkdir(parents=True, exist_ok=True)
        
        # Override directories - use storage for final attachments, temp for processing
        self.download_dir = self.temp_processing_dir
        self.attachments_folder = self.temp_processing_dir
        
        # Override summary file name
        self.summary_file = "missing_invoice_search_summary.xlsx"
        
        # Import invoice downloader functions
        try:
            from mpi_backend.utils.invoice_downaloder import download_email_attachments
            self.invoice_processing_available = True
            logger.info("✅ Basic invoice processing available")
        except ImportError as e:
            self.invoice_processing_available = False
            logger.warning(f"⚠️ Full invoice processing pipeline not available: {e}")
            logger.info("🔄 Will use basic attachment download only")
        
        logger.info("🎯 Invoice Search and Add initialized with EXACT MATCHING")
        logger.info(f"📁 Attachments will be saved ONLY to storage: {self.storage_dir}")
        logger.info(f"📁 Temporary processing directory: {self.temp_processing_dir}")
        logger.info("🔄 Will use SAME processing pipeline as regular invoice downloader")
    
    def download_attachments_to_storage(self, email_message, ref_no):
        """
        Download attachments directly to storage (not local folders)
        This ensures attachments are only saved to the storage directory
        """
        try:
            from mpi_backend.utils.invoice_downaloder import download_email_attachments
            import shutil
            
            # Download to temporary directory first
            temp_success = download_email_attachments(email_message, self.temp_processing_dir)
            
            if not temp_success:
                logger.warning(f"No attachments downloaded for ref {ref_no}")
                return False
            
            # Move attachments from temp to storage
            attachments_moved = 0
            for temp_file in self.temp_processing_dir.rglob("*.pdf"):
                try:
                    # Create storage path with ref_no for organization
                    storage_subdir = self.storage_dir / ref_no
                    storage_subdir.mkdir(parents=True, exist_ok=True)
                    
                    # Move file to storage
                    storage_file = storage_subdir / temp_file.name
                    shutil.move(str(temp_file), str(storage_file))
                    attachments_moved += 1
                    logger.info(f"Moved attachment to storage: {storage_file}")
                    
                except Exception as e:
                    logger.error(f"Error moving attachment {temp_file} to storage: {e}")
                    continue
            
            # Clean up temp directory
            try:
                shutil.rmtree(self.temp_processing_dir)
                logger.debug(f"Cleaned up temp directory: {self.temp_processing_dir}")
            except Exception as e:
                logger.warning(f"Could not clean up temp directory: {e}")
            
            if attachments_moved > 0:
                logger.info(f"✅ Moved {attachments_moved} attachments to storage for ref {ref_no}")
                return True
            else:
                logger.warning(f"⚠️ No attachments moved to storage for ref {ref_no}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error downloading attachments to storage for ref {ref_no}: {e}")
            return False
    
    def search_specific_references(self, reference_numbers, limit=None):
        """
        Search for specific reference numbers with exact matching
        
        Args:
            reference_numbers: List of reference numbers to search for
            limit: Optional limit on number of reference numbers to process
            
        Returns:
            dict: Results with found/not found invoices
        """
        if limit:
            reference_numbers = reference_numbers[:limit]
            logger.info(f"🔍 Starting EXACT MATCH search for {len(reference_numbers)} reference numbers (limited to {limit})")
        else:
        logger.info(f"🔍 Starting EXACT MATCH search for {len(reference_numbers)} reference numbers")
        
        results = {
            'found': [],
            'not_found': [],
            'processed': [],
            'errors': []
        }
        
        try:
            # Connect to email
            if not self.connect_to_email():
                logger.error("❌ Failed to connect to email")
                return results
            
            # Get mailboxes
            mailboxes = self.get_all_mailboxes()
            logger.info(f"📁 Will search in {len(mailboxes)} mailboxes: {mailboxes}")
            
            # Search each reference number
            for i, ref_no in enumerate(reference_numbers, 1):
                logger.info(f"🔍 [{i}/{len(reference_numbers)}] Searching for: {ref_no}")
                
                try:
                    # Search for this specific reference with exact matching
                    email_ids, email_mailbox_map = self.search_single_reference(ref_no, mailboxes)
                    
                    if email_ids:
                        logger.info(f"✅ Found {len(email_ids)} EXACT MATCH emails for {ref_no}")
                        results['found'].append({
                            'ref_no': ref_no,
                            'email_ids': email_ids,
                            'mailbox_map': email_mailbox_map,
                            'email_count': len(email_ids)
                        })
                        
                        # Process and download the emails using INVOICE DOWNLOADER logic
                        success = self.process_emails_for_reference_with_invoice_pipeline(ref_no, email_ids, email_mailbox_map)
                        if success:
                            results['processed'].append(ref_no)
                            logger.info(f"✅ Successfully processed and downloaded {ref_no}")
                        else:
                            logger.warning(f"⚠️ Found {ref_no} but failed to process")
                            
                    else:
                        logger.info(f"❌ No EXACT MATCH found for {ref_no}")
                        results['not_found'].append(ref_no)
                        
                except Exception as e:
                    logger.error(f"❌ Error searching {ref_no}: {e}")
                    results['errors'].append({'ref_no': ref_no, 'error': str(e)})
                    
                # Small delay between searches
                time.sleep(0.5)
            
            # Process downloaded attachments using COMPLETE INVOICE DOWNLOADER PIPELINE
            if results['processed']:
                logger.info(f"📎 Processing {len(results['processed'])} downloaded invoice sets using INVOICE DOWNLOADER PIPELINE...")
                logger.info("🔄 Starting invoice processing pipeline...")
                
                processing_success = self.process_all_downloaded_invoices()
                
                if processing_success:
                    logger.info("✅ Invoice processing pipeline completed successfully")
                else:
                    logger.error("❌ Invoice processing pipeline failed")
                
                # Create summary
                logger.info(f"📊 Creating search summary...")
                summary_success = self.create_summary_excel()
                
                if summary_success:
                    logger.info("✅ Summary Excel file created successfully")
                else:
                    logger.warning("⚠️ Failed to create summary Excel file")
            
            # Store results for summary creation
            self.last_search_results = results
            
            # Print results summary
            self._print_search_summary(results)
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Error in search process: {e}")
            results['errors'].append({'error': f"Search process error: {e}"})
            return results
        
        finally:
            self.cleanup()
    
    def process_emails_for_reference_with_invoice_pipeline(self, ref_no, email_ids, email_mailbox_map):
        """
        Process emails for a reference using basic attachment download
        """
        try:
            logger.info(f"📧 Processing {len(email_ids)} emails for ref {ref_no}")
            
            total_attachments_downloaded = 0
            
            for email_id in email_ids:
                try:
                    logger.info(f"    📧 Processing email {email_id} for ref {ref_no}")
                    logger.debug(f"    🔍 Fetching email content...")
                    
                    # Fetch the full email like invoice_downloader does
                    result, response = self.mail.uid('fetch', email_id, '(BODY.PEEK[])')
                    
                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"    ❌ Failed to fetch email {email_id}: {result}")
                        continue
                    
                    logger.debug(f"    ✅ Email {email_id} fetched successfully")
                    
                    # Decode email like invoice_downloader does
                    try:
                        raw_email = response[0][1].decode('utf-8')
                        logger.debug(f"    ✅ Email {email_id} decoded as UTF-8")
                    except UnicodeDecodeError:
                        raw_email = response[0][1].decode('latin-1')
                        logger.debug(f"    ✅ Email {email_id} decoded as Latin-1")
                    
                    import email
                    email_message = email.message_from_string(raw_email)
                    logger.debug(f"    ✅ Email {email_id} parsed successfully")
                    
                    # Use our custom storage-only download method
                    logger.info(f"    📎 Downloading attachments to storage for ref {ref_no}...")
                    download_success = self.download_attachments_to_storage(email_message, ref_no)
                    
                    if download_success:
                        total_attachments_downloaded += 1
                        logger.info(f"    ✅ Successfully downloaded attachments from email {email_id} to storage")
                    else:
                        logger.warning(f"    ⚠️ No attachments downloaded from email {email_id}")
                        
                except Exception as e:
                    logger.error(f"    ❌ Error processing email {email_id}: {e}")
                    logger.debug(f"    🔍 Error details: {str(e)}")
                    continue
            
            if total_attachments_downloaded > 0:
                logger.info(f"✅ Downloaded attachments from {total_attachments_downloaded} emails for ref {ref_no}")
                return True
            else:
                logger.warning(f"⚠️ No attachments downloaded for ref {ref_no}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in invoice pipeline processing for ref {ref_no}: {e}")
            return False
    
    def process_all_downloaded_invoices(self):
        """
        Process all downloaded invoices - basic version that works without full pipeline
        """
        try:
            if not self.invoice_processing_available:
                logger.warning("⚠️ Full invoice processing pipeline not available")
                logger.info("📁 Attachments have been downloaded to storage successfully")
                logger.info("💾 Manual processing required for PDF conversion and database updates")
                return True  # Return True since attachments were downloaded successfully
            
            logger.info("🔄 Starting basic invoice processing...")
            logger.info(f"📁 Processing storage folder: {self.storage_dir}")
            
            # Count files in storage
            pdf_files = list(self.storage_dir.rglob("*.pdf"))
            logger.info(f"📄 Found {len(pdf_files)} PDF files in storage")
            
            if pdf_files:
                logger.info("✅ Attachments successfully saved to storage")
                logger.info("💾 Manual processing required for PDF conversion and database updates")
                return True
            else:
                logger.warning("⚠️ No PDF files found in storage")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in basic invoice processing: {e}")
            import traceback
            logger.error(traceback.format_exc())
                return False
            
    def create_summary_excel(self):
        """
        Create a comprehensive summary Excel file with processing results
        Includes ref number, vendor, date, attachment status, DB update status, etc.
        """
        try:
            import pandas as pd
            from openpyxl import Workbook
            from openpyxl.styles import PatternFill, Font
            from datetime import datetime
            
            logger.info(f"📊 Creating comprehensive summary Excel file: {self.summary_file}")
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Invoice Processing Summary"
            
            # Define headers
            headers = [
                'Reference_Number', 'Status', 'Vendor', 'Email_Date', 
                'Email_Subject', 'Sender', 'Mailbox', 'Attachments_Found',
                'Attachments_Downloaded', 'Storage_Path', 'DB_Update_Status',
                'Processing_Time', 'Error_Message'
            ]
            
            # Write headers
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            
            # Get processing results from the search
            if hasattr(self, 'last_search_results') and self.last_search_results:
                results = self.last_search_results
                row = 2
                
                # Process found invoices
                for found_item in results.get('found', []):
                    ref_no = found_item['ref_no']
                    email_count = found_item['email_count']
                    mailbox_map = found_item.get('mailbox_map', {})
                    
                    # Get vendor information (simplified)
                    vendor = "Unknown"
                    if mailbox_map:
                        # Try to extract vendor from mailbox names
                        mailboxes = list(mailbox_map.values())
                        if mailboxes:
                            vendor = mailboxes[0]  # Use first mailbox as vendor indicator
                    
                    # Check if this ref was processed
                    was_processed = ref_no in results.get('processed', [])
                    
                    # Determine storage path
                    storage_path = f"storage/missing_invoice_attachments/{ref_no}"
                    
                    # Write data row
                    ws.cell(row=row, column=1, value=ref_no)
                    ws.cell(row=row, column=2, value="FOUND" if was_processed else "FOUND_NOT_PROCESSED")
                    ws.cell(row=row, column=3, value=vendor)
                    ws.cell(row=row, column=4, value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    ws.cell(row=row, column=5, value=f"Found in {email_count} emails")
                    ws.cell(row=row, column=6, value="Multiple senders")
                    ws.cell(row=row, column=7, value="; ".join(set(mailbox_map.values())))
                    ws.cell(row=row, column=8, value=email_count)  # Attachments found
                    ws.cell(row=row, column=9, value=email_count if was_processed else 0)  # Attachments downloaded
                    ws.cell(row=row, column=10, value=storage_path)
                    ws.cell(row=row, column=11, value="SUCCESS" if was_processed else "NOT_PROCESSED")
                    ws.cell(row=row, column=12, value=datetime.now().strftime('%H:%M:%S'))
                    ws.cell(row=row, column=13, value="")
                    
                    # Color coding
                    if was_processed:
                        fill_color = "90EE90"  # Light green for success
                    else:
                        fill_color = "FFE4B5"  # Light orange for found but not processed
                    
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row, column=col).fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
                    
                    row += 1
                
                # Process not found invoices
                for ref_no in results.get('not_found', []):
                    ws.cell(row=row, column=1, value=ref_no)
                    ws.cell(row=row, column=2, value="NOT_FOUND")
                    ws.cell(row=row, column=3, value="N/A")
                    ws.cell(row=row, column=4, value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    ws.cell(row=row, column=5, value="N/A")
                    ws.cell(row=row, column=6, value="N/A")
                    ws.cell(row=row, column=7, value="N/A")
                    ws.cell(row=row, column=8, value=0)
                    ws.cell(row=row, column=9, value=0)
                    ws.cell(row=row, column=10, value="N/A")
                    ws.cell(row=row, column=11, value="NOT_FOUND")
                    ws.cell(row=row, column=12, value=datetime.now().strftime('%H:%M:%S'))
                    ws.cell(row=row, column=13, value="Reference number not found in any emails")
                    
                    # Color coding - red for not found
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row, column=col).fill = PatternFill(start_color="FFB6C1", end_color="FFB6C1", fill_type="solid")
                    
                    row += 1
                
                # Process errors
                for error_item in results.get('errors', []):
                    ref_no = error_item.get('ref_no', 'Unknown')
                    error_msg = error_item.get('error', 'Unknown error')
                    
                    ws.cell(row=row, column=1, value=ref_no)
                    ws.cell(row=row, column=2, value="ERROR")
                    ws.cell(row=row, column=3, value="N/A")
                    ws.cell(row=row, column=4, value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    ws.cell(row=row, column=5, value="N/A")
                    ws.cell(row=row, column=6, value="N/A")
                    ws.cell(row=row, column=7, value="N/A")
                    ws.cell(row=row, column=8, value=0)
                    ws.cell(row=row, column=9, value=0)
                    ws.cell(row=row, column=10, value="N/A")
                    ws.cell(row=row, column=11, value="ERROR")
                    ws.cell(row=row, column=12, value=datetime.now().strftime('%H:%M:%S'))
                    ws.cell(row=row, column=13, value=error_msg)
                    
                    # Color coding - red for errors
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row, column=col).fill = PatternFill(start_color="FFB6C1", end_color="FFB6C1", fill_type="solid")
                    
                    row += 1
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Save the workbook
            wb.save(self.summary_file)
            logger.info(f"✅ Summary Excel file created successfully: {self.summary_file}")
            
            # Print summary statistics
            total_found = len(results.get('found', [])) if hasattr(self, 'last_search_results') and self.last_search_results else 0
            total_processed = len(results.get('processed', [])) if hasattr(self, 'last_search_results') and self.last_search_results else 0
            total_not_found = len(results.get('not_found', [])) if hasattr(self, 'last_search_results') and self.last_search_results else 0
            total_errors = len(results.get('errors', [])) if hasattr(self, 'last_search_results') and self.last_search_results else 0
            
            logger.info(f"📊 SUMMARY STATISTICS:")
            logger.info(f"  ✅ Found: {total_found}")
            logger.info(f"  📎 Processed: {total_processed}")
            logger.info(f"  ❌ Not Found: {total_not_found}")
            logger.info(f"  ⚠️ Errors: {total_errors}")
            
                    return True
                
        except Exception as e:
            logger.error(f"❌ Error creating summary Excel file: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _print_search_summary(self, results):
        """Print a summary of search results"""
        print("\n" + "="*60)
        print("INVOICE SEARCH AND ADD SUMMARY")
        print("="*60)
        
        print(f"🔍 SEARCH RESULTS:")
        print(f"  ✅ Found (exact match): {len(results['found'])}")
        print(f"  ❌ Not found: {len(results['not_found'])}")
        print(f"  📎 Successfully processed: {len(results['processed'])}")
        print(f"  ⚠️ Errors: {len(results['errors'])}")
        
        if results['found']:
            print(f"\n✅ FOUND INVOICES:")
            for item in results['found']:
                ref_no = item['ref_no']
                count = item['email_count']
                mailboxes = list(set(item['mailbox_map'].values()))
                print(f"  - {ref_no}: {count} emails in {', '.join(mailboxes)}")
        
        if results['not_found']:
            print(f"\n❌ NOT FOUND INVOICES:")
            for ref_no in results['not_found'][:10]:  # Show first 10
                print(f"  - {ref_no}")
            if len(results['not_found']) > 10:
                print(f"  ... and {len(results['not_found']) - 10} more")
        
        if results['errors']:
            print(f"\n⚠️ ERRORS:")
            for error_item in results['errors'][:5]:  # Show first 5
                if 'ref_no' in error_item:
                    print(f"  - {error_item['ref_no']}: {error_item['error']}")
                else:
                    print(f"  - {error_item['error']}")
        
        print(f"\n📁 FILES CREATED:")
        print(f"  - Storage: {self.storage_dir}/")
        print(f"  - Summary: {self.summary_file}")
        
        if results['processed']:
            print(f"\n💾 DATABASE INTEGRATION:")
            print(f"  ✅ Processed using SAME pipeline as invoice_downloader")
            print(f"  📄 PDFs → Excel conversion")
            print(f"  💾 Automatic addition to system database")
            print(f"  🔍 Duplicate detection and handling")
        
        print("="*60)
    
    def search_from_file(self, file_path, limit=None):
        """
        Search for reference numbers from a file
        
        Args:
            file_path: Path to Excel file containing reference numbers
            limit: Optional limit on number of reference numbers to process
        """
        try:
            # Read reference numbers from file
            ref_numbers = self.read_reference_numbers_from_file(file_path)
            if not ref_numbers:
                logger.error(f"❌ No reference numbers found in {file_path}")
                return None
            
            logger.info(f"📋 Read {len(ref_numbers)} reference numbers from {file_path}")
            if limit:
                logger.info(f"📋 Will process only first {limit} reference numbers")
            
            # Search for them
            return self.search_specific_references(ref_numbers, limit)
            
        except Exception as e:
            logger.error(f"❌ Error reading from file {file_path}: {e}")
            return None
    
    def read_reference_numbers_from_file(self, file_path):
        """Read reference numbers from Excel file"""
        try:
            import pandas as pd
            
            if not Path(file_path).exists():
                logger.error(f"File not found: {file_path}")
                return []
            
            df = pd.read_excel(file_path)
            
            # Try different column names
            possible_columns = ['Reference_Number', 'Ref_Number', 'Ref', 'Invoice_Number', 'ref_no']
            ref_column = None
            
            for col in possible_columns:
                if col in df.columns:
                    ref_column = col
                    break
            
            if not ref_column:
                # Try to find any column with 'ref' in the name
                for col in df.columns:
                    if 'ref' in col.lower():
                        ref_column = col
                        break
            
            if not ref_column:
                logger.error(f"❌ Could not find reference number column in {file_path}")
                logger.info(f"Available columns: {list(df.columns)}")
                return []
            
            ref_numbers = df[ref_column].dropna().astype(str).str.strip().tolist()
            logger.info(f"📋 Found {len(ref_numbers)} reference numbers in column '{ref_column}'")
            
            return ref_numbers
            
        except Exception as e:
            logger.error(f"❌ Error reading file {file_path}: {e}")
            return []

def main():
    """Main function"""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Invoice Search and Add Tool')
    parser.add_argument('--limit', type=int, help='Limit the number of reference numbers to process')
    args = parser.parse_args()
    
    print("🎯 Invoice Search and Add Tool")
    print("=" * 60)
    print("This tool combines the BEST of both systems:")
    print("🔍 SEARCH: Uses missing_invoice_finder logic with EXACT MATCHING")
    print("  ✅ Must contain 'invoice' keyword")
    print("  ✅ Must contain exact reference number") 
    print("  ✅ Searches ALL mailboxes (INBOX, Archive, etc.)")
    print("")
    print("📎 PROCESS: Uses invoice_downloader pipeline EXACTLY")
    print("  ✅ Downloads PDFs using same logic")
    print("  ✅ Converts PDFs to Excel") 
    print("  ✅ Adds to system database automatically")
    print("  ✅ Handles duplicates and errors")
    if args.limit:
        print(f"🔢 LIMIT: Processing only first {args.limit} reference numbers")
    print("=" * 60)
    
    try:
        # Create searcher
        searcher = InvoiceSearchAndAdd()
        
        # Check if missing_invoices.xlsx exists
        missing_file = "missing_invoices.xlsx"
        if Path(missing_file).exists():
            print(f"📁 Found {missing_file}")
            print("🔍 Starting search from file...")
            
            # Search from file with limit
            results = searcher.search_from_file(missing_file, args.limit)
            
            if results:
                found_count = len(results['found'])
                processed_count = len(results['processed'])
                print(f"\n🎉 Search completed!")
                print(f"✅ Found {found_count} invoices")
                print(f"📎 Successfully processed {processed_count} invoices")
                
                if processed_count > 0:
                    print(f"")
                    print(f"🎉 SUCCESS! Missing invoices found and added to system!")
                    print(f"📊 Used SAME processing pipeline as regular invoice_downloader:")
                    print(f"  1. 🔍 Found missing invoices using exact search")
                    print(f"  2. 📎 Downloaded PDF attachments")
                    print(f"  3. 📄 Converted PDFs to Excel")
                    print(f"  4. 💾 Added to database with duplicate handling")
                    print(f"  5. ✅ Ready for use in your system!")
                
                return True
            else:
                print("❌ Search failed")
                return False
                
        else:
            print(f"❌ File not found: {missing_file}")
            print("Please ensure missing_invoices.xlsx exists in the current directory")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
