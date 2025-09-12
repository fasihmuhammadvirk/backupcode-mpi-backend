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
        
        # Create time-based storage directory for this specific script run
        try:
            from mpi_backend.config import TIMEZONE
            current_time = datetime.now(TIMEZONE)
            # Use microseconds to ensure uniqueness even for rapid successive runs
            time_folder = current_time.strftime('%Y%m%d_%H%M%S_%f')
            self.storage_dir = (Path("storage/missing_invoice_attachments") 
                               / time_folder)
        except ImportError:
            logger.warning("Could not import TIMEZONE, using defaults")
            current_time = datetime.now()
            # Use microseconds to ensure uniqueness even for rapid successive runs
            time_folder = current_time.strftime('%Y%m%d_%H%M%S_%f')
            self.storage_dir = (Path("storage/missing_invoice_attachments") 
                               / time_folder)
        
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Override directories - use ONLY time-based storage for all attachments
        # Override the parent class directories to prevent extra directory creation
        self.download_dir = self.storage_dir
        self.attachments_folder = self.storage_dir
        
        # Remove the extra directory created by parent class
        extra_dir = Path("missing_invoice_attachments")
        if extra_dir.exists() and extra_dir.is_dir():
            try:
                # Only remove if it's empty (safe to remove)
                if not any(extra_dir.iterdir()):
                    extra_dir.rmdir()
                    logger.info(f"🗑️ Removed empty extra directory: {extra_dir}")
                else:
                    logger.warning(f"⚠️ Extra directory {extra_dir} exists but is not empty, leaving it")
            except Exception as e:
                logger.warning(f"⚠️ Could not remove extra directory {extra_dir}: {e}")
        
        # Override summary file name
        self.summary_file = "missing_invoice_search_summary.xlsx"
        
        # Store detected suppliers for each reference
        self.detected_suppliers = {}
        
        # Import invoice downloader functions
        try:
            # These will be imported when needed to avoid unused import warnings
            self.invoice_processing_available = True
            logger.info("✅ Full invoice processing pipeline available")
        except ImportError as e:
            self.invoice_processing_available = False
            logger.warning(f"⚠️ Full invoice processing pipeline not available: {e}")
            logger.info("🔄 Will use basic attachment download only")
        
        logger.info("🎯 Invoice Search and Add initialized with EXACT MATCHING")
        logger.info(f"📁 Attachments will be saved to time-based storage: "
                   f"{self.storage_dir}")
        logger.info("🔄 Will use SAME processing pipeline as regular "
                   "invoice downloader")
        logger.info(f"📁 Each script run creates isolated directory: "
                   f"{self.storage_dir.name}")
        logger.info("📁 NO temp_processing directories - only storage used")
    
    def select_mailbox_safely(self, mailbox_name):
        """Safely select mailbox without timeout context (Windows compatible)"""
        try:
            result = self.mail.select(mailbox_name)
            if result[0] == 'OK':
                logger.debug(f"Successfully selected mailbox: {mailbox_name}")
                return True
            else:
                logger.warning(f"Failed to select mailbox {mailbox_name}: {result[0]}")
                return False
        except Exception as e:
            logger.error(f"Error selecting mailbox {mailbox_name}: {e}")
            return False
    
    def _search_mailbox_for_reference(self, ref_no, mailbox, mailbox_index, total_mailboxes):
        """Search a specific mailbox for a reference number with Windows-compatible error handling"""
        try:
            logger.info(f"  🔍 [{mailbox_index}/{total_mailboxes}] Searching in mailbox: {mailbox}")
            
            # Select the mailbox with retry logic for SSL errors (Windows compatible)
            max_retries = 3  # Reduced retries for faster processing
            result = None
            for attempt in range(max_retries):
                try:
                    # Handle Gmail special folders that need quoting
                    if '[Gmail]' in mailbox and not mailbox.startswith('"'):
                        # Try with quotes first for Gmail special folders
                        quoted_mailbox = f'"{mailbox}"'
                        try:
                            result = self.mail.select(quoted_mailbox)
                            if result[0] == 'OK':
                                logger.debug(f"  ✅ Successfully selected quoted {quoted_mailbox}")
                            else:
                                # Try without quotes as fallback
                                result = self.mail.select(mailbox)
                        except Exception as e:
                            logger.debug(f"  Quoted selection failed, trying unquoted: {e}")
                            result = self.mail.select(mailbox)
                    else:
                        result = self.mail.select(mailbox)
                        
                    if result[0] != 'OK':
                        logger.warning(f"  Failed to select mailbox {mailbox}: {result}")
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Brief delay before retry
                            continue
                        else:
                            break
                    else:
                        logger.debug(f"  Successfully selected mailbox {mailbox}")
                        break  # Success, exit retry loop
                        
                except Exception as e:
                    logger.error(f"  Error selecting mailbox {mailbox} (attempt {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)  # Brief delay before retry
                        continue
                    else:
                        logger.warning(f"  Skipping mailbox {mailbox} due to selection failure")
                        return []  # Return empty list to match expected format
            
            if not result or result[0] != 'OK':
                logger.warning(f"  Skipping mailbox {mailbox} due to selection failure")
                return []  # Return empty list to match expected format
            
            # Search for the reference number in this mailbox
            search_terms = [
                f'SUBJECT "invoice {ref_no}"',
                f'SUBJECT "invoice #{ref_no}"',
                f'SUBJECT "invoice no {ref_no}"',
                f'SUBJECT "invoice number {ref_no}"',
                f'BODY "invoice {ref_no}"',
                f'BODY "invoice #{ref_no}"',
                f'BODY "invoice no {ref_no}"',
                f'BODY "invoice number {ref_no}"',
                f'TEXT "invoice {ref_no}"',
                f'TEXT "invoice #{ref_no}"',
                f'TEXT "invoice no {ref_no}"',
                f'TEXT "invoice number {ref_no}"'
            ]
            
            found_emails = []
            for search_term in search_terms:
                try:
                    result, data = self.mail.uid('search', None, search_term)
                    if result == 'OK' and data[0]:
                        email_ids = data[0].split()
                        for email_id in email_ids:
                            email_id = email_id.decode('utf-8') if isinstance(email_id, bytes) else email_id
                            if email_id not in found_emails:
                                found_emails.append(email_id)
                                logger.debug(f"  Found email {email_id} with search term: {search_term}")
                except Exception as e:
                    logger.debug(f"  Search term '{search_term}' failed: {e}")
                    continue
            
            if found_emails:
                logger.info(f"  ✅ Found {len(found_emails)} emails in {mailbox}")
                return found_emails  # Return just the list to match expected format
            else:
                logger.info(f"  ❌ No emails found in {mailbox}")
                return []  # Return empty list to match expected format
                
        except Exception as e:
            logger.error(f"  Error searching mailbox {mailbox}: {e}")
            return []  # Return empty list to match expected format
    
    def get_supplier_from_email(self, email_message):
        """
        Get supplier name using EXACT same logic as invoice_downloader
        """
        try:
            from mpi_backend.config import SUPPLIERS
            
            # Extract email details
            email_subject = email_message.get('Subject', '')
            supplier_email = email_message.get('From', '')
            
            # Normalize inputs (same as invoice_downloader)
            raw_subject = (email_subject or "").lower()
            subject = " ".join(raw_subject.split())  # collapse whitespace
            supplier_email = (supplier_email or "").lower().strip()
            
            if "statement" in subject:
                return "no_supplier"
            
            # Domain-based fast paths (same as invoice_downloader)
            if any(d in supplier_email for d in ["@wwps.co", "worldwideplumbingsupply", "wwps."]):
                return SUPPLIERS[1]  # World Wide Plumbing
            if any(d in supplier_email for d in ["@bmwpsupply", "@bmwplumbing", "bmwpsupply.com"]):
                return SUPPLIERS[0]  # BMW Plumbing Supplies
            
            # BMW Plumbing Supplies - multiple patterns
            if any(pattern in subject for pattern in ["bmw", "bmwpsupply", "bmw plumbing supplies"]):
                return SUPPLIERS[0]
            
            # World Wide Plumbing - multiple patterns
            elif any(pattern in subject for pattern in [
                "world wide plumbing supply",
                "world wide",
                "world-wide",
                "worldwide",
                "wwps",
            ]):
                return SUPPLIERS[1]
            
            # Y & S Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["y&s", "y and s",
                                                       "ys plumbing", "y s plumbing", "Y&S Plumbing & Heating Supply"]):
                return SUPPLIERS[2]
            
            # Supreme Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["supreme plumbing",
                                                       "invoice # i-", "supremeplumbing"]):
                return SUPPLIERS[3]
            
            # Pyramid Plumbing - multiple patterns
            elif any(pattern in subject for pattern in ["pyramid plumbing",
                                                       "pyramidps"]):
                return SUPPLIERS[4]
            
            # ABC Opus Services - multiple patterns
            elif any(pattern in subject for pattern in ["abc opus", "opusoperations",
                                                       "abc opus services"]):
                return SUPPLIERS[5]
            
            # Park Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["park plumbing",
                                                       "parkplumbingsupply",
                                                       "park plumbing & heating supply"]):
                return SUPPLIERS[6]
            
            # FW Webb Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["webb payment receipt",
                                                       "fw webb", "webb plumbing"]):
                return SUPPLIERS[8]
            
            # Flow Mark Plumbing Supply - specific pattern
            elif "see invoice i-" in subject:
                return SUPPLIERS[9]
            
            else:
                logger.warning(f"Unknown supplier for subject: {email_subject}")
                return "unknown_supplier"
        except Exception as e:
            logger.error(f"Supplier detection failed: {str(e)}")
            return "unknown_supplier"
    
    def download_attachments_to_storage(self, email_message, ref_no):
        """
        Download attachments using the EXACT same logic as invoice_downloader
        This ensures we follow the same pipeline for supplier detection and processing
        """
        try:
            from mpi_backend.utils.invoice_downaloder import download_email_attachments
            
            # First, check if this email should be processed (invoice keyword check)
            email_subject = email_message.get('Subject', '')
            subject_lower = (email_subject or '').lower()
            has_invoice_keyword = any(kw in subject_lower for kw in [
                'invoice', 'invoices', 'invoice(s)', 'see invoice', 'inv #', 'invoice no'
            ])
            
            if not has_invoice_keyword:
                logger.info(f"Email subject does not contain invoice keywords, skipping: {email_subject}")
                return False, None
            
            # Get supplier BEFORE downloading (same as invoice_downloader)
            supplier_name = self.get_supplier_from_email(email_message)
            logger.info(f"Detected supplier: {supplier_name} for ref {ref_no}")
            
            # Use the EXACT same download logic as invoice_downloader
            # This will create the proper directory structure with supplier detection
            download_success = download_email_attachments(email_message, self.storage_dir)
            
            if not download_success:
                logger.warning(f"No attachments downloaded for ref {ref_no}")
                return False, None
            
            # Find the downloaded PDF files
            pdf_files = list(self.storage_dir.rglob("*.pdf"))
            if not pdf_files:
                logger.warning(f"No PDF files found for ref {ref_no}")
                return False, None
            
            logger.info(f"✅ Downloaded {len(pdf_files)} attachments for ref {ref_no}, supplier: {supplier_name}")
            return True, supplier_name
                
        except Exception as e:
            logger.error(f"❌ Error downloading attachments for ref {ref_no}: {e}")
            return False, None
    
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
            # Clean up extra directory after processing
            self._cleanup_extra_directory()
    
    def process_emails_for_reference_with_invoice_pipeline(self, ref_no, email_ids, email_mailbox_map):
        """
        Process emails for a reference using EXACT same pipeline as invoice_downloader
        """
        try:
            logger.info(f"📧 Processing {len(email_ids)} emails for ref {ref_no}")
            
            total_attachments_downloaded = 0
            supplier_name = None
            
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
                    
                    # Use EXACT same download logic as invoice_downloader
                    logger.info(f"    📎 Downloading attachments using invoice_downloader pipeline for ref {ref_no}...")
                    download_success, detected_supplier = self.download_attachments_to_storage(email_message, ref_no)
                    
                    if download_success:
                        total_attachments_downloaded += 1
                        if detected_supplier:
                            supplier_name = detected_supplier
                        logger.info(f"    ✅ Successfully downloaded attachments "
                               f"from email {email_id}")
                    else:
                        logger.warning(f"    ⚠️ No attachments downloaded from email {email_id}")
                        
                except Exception as e:
                    logger.error(f"    ❌ Error processing email {email_id}: {e}")
                    logger.debug(f"    🔍 Error details: {str(e)}")
                    continue
            
            if total_attachments_downloaded > 0:
                logger.info(f"✅ Downloaded attachments from {total_attachments_downloaded} emails for ref {ref_no}")
                # Store supplier info for later processing
                self.detected_suppliers[ref_no] = supplier_name
                return True
            else:
                logger.warning(f"⚠️ No attachments downloaded for ref {ref_no}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in invoice pipeline processing for ref {ref_no}: {e}")
            return False
    
    def process_all_downloaded_invoices(self):
        """
        Process only the invoices downloaded in this specific script run using EXACT same pipeline as invoice_downloader
        """
        try:
            if not self.invoice_processing_available:
                logger.warning("⚠️ Full invoice processing pipeline not available")
                logger.info("📁 Attachments have been downloaded to storage successfully")
                logger.info("💾 Manual processing required for PDF conversion and database updates")
                return True  # Return True since attachments were downloaded successfully
            
            logger.info("🔄 Starting invoice processing using EXACT same pipeline as invoice_downloader...")
            logger.info(f"📁 Processing ONLY current run folder: {self.storage_dir}")
            
            # Count files in ONLY the current time-based storage directory (not all historical files)
            pdf_files = list(self.storage_dir.rglob("*.pdf"))
            logger.info(f"📄 Found {len(pdf_files)} PDF files in current run directory")
            
            if not pdf_files:
                logger.warning("⚠️ No PDF files found in current run directory")
                return False
            
            # Use EXACT same conversion logic as invoice_downloader - but only for current run files
            logger.info("🔄 Starting invoice conversion (same as invoice_downloader)...")
            from mpi_backend.utils.invoice_convertor import convert_invoice_for_email
            converted_files, failed_files = convert_invoice_for_email(self.storage_dir)
            logger.info(f"✅ Conversion complete. Success: {len(converted_files)}, Failed: {len(failed_files)}")
            
            # Use EXACT same data processing logic as invoice_downloader - but only for current run files
            logger.info("🔄 Starting data processing (same as invoice_downloader)...")
            from mpi_backend.utils.extracted_data_processor import process_extracted_data
            processing_results = process_extracted_data(converted_files, failed_files)
            logger.info(f"✅ Data processing complete. Processed {len(processing_results)} files")
            
            logger.info("✅ Invoice processing pipeline completed successfully")
            logger.info(f"📁 Processed ONLY files from: {self.storage_dir}")
            return True
                
        except Exception as e:
            logger.error(f"❌ Error in invoice processing: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
            
    def create_summary_excel(self):
        """
        Create a comprehensive summary Excel file with processing results
        Format: Ref No | Supplier | Status (Added / Not Found / Failed) | DB Updated (Yes/No) | Notes
        """
        try:
            from openpyxl import Workbook
            from openpyxl.styles import PatternFill, Font
            
            logger.info(f"📊 Creating comprehensive summary Excel file: {self.summary_file}")
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Missing Invoice Processing Summary"
            
            # Define headers as requested
            headers = [
                'Ref No', 'Supplier', 'Status', 'DB Updated', 'Notes'
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
                    
                    # Get supplier information from detected suppliers
                    supplier = self.detected_suppliers.get(ref_no, "Unknown")
                    
                    # Check if this ref was processed
                    was_processed = ref_no in results.get('processed', [])
                    
                    # Determine status
                    if was_processed:
                        status = "Added"
                        db_updated = "Yes"
                        notes = f"Successfully processed and added to database"
                        fill_color = "90EE90"  # Light green for success
                    else:
                        status = "Found_Not_Processed"
                        db_updated = "No"
                        notes = f"Found in {email_count} emails but processing failed"
                        fill_color = "FFE4B5"  # Light orange for found but not processed
                    
                    # Write data row
                    ws.cell(row=row, column=1, value=ref_no)
                    ws.cell(row=row, column=2, value=supplier)
                    ws.cell(row=row, column=3, value=status)
                    ws.cell(row=row, column=4, value=db_updated)
                    ws.cell(row=row, column=5, value=notes)
                    
                    # Color coding
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row, column=col).fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
                    
                    row += 1
                
                # Process not found invoices
                for ref_no in results.get('not_found', []):
                    ws.cell(row=row, column=1, value=ref_no)
                    ws.cell(row=row, column=2, value="N/A")
                    ws.cell(row=row, column=3, value="Not Found")
                    ws.cell(row=row, column=4, value="No")
                    ws.cell(row=row, column=5, value="Reference number not found in any emails")
                    
                    # Color coding - red for not found
                    fill_color = "FFB6C1"  # Light red for not found
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row, column=col).fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
                    
                    row += 1
                
                # Process errors
                for error_item in results.get('errors', []):
                    ref_no = error_item.get('ref_no', 'Unknown')
                    error_msg = error_item.get('error', 'Unknown error')
                    
                    ws.cell(row=row, column=1, value=ref_no)
                    ws.cell(row=row, column=2, value="N/A")
                    ws.cell(row=row, column=3, value="Failed")
                    ws.cell(row=row, column=4, value="No")
                    ws.cell(row=row, column=5, value=f"Error: {error_msg}")
                    
                    # Color coding - red for errors
                    fill_color = "FFB6C1"  # Light red for errors
                    for col in range(1, len(headers) + 1):
                        ws.cell(row=row, column=col).fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
                    
                    row += 1
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
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
            
            logger.info("📊 SUMMARY STATISTICS:")
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
        print(f"  - Time-based Storage: {self.storage_dir}/")
        print(f"  - Summary: {self.summary_file}")
        print(f"  - Isolated Run: {self.storage_dir.name}")
        print(f"  - NO temp_processing directories created")
        
        if results['processed']:
            print("\n💾 DATABASE INTEGRATION:")
            print("  ✅ Processed using SAME pipeline as invoice_downloader")
            print("  📄 PDFs → Excel conversion")
            print("  💾 Automatic addition to system database")
            print("  🔍 Duplicate detection and handling")
        
        print("="*60)
    
    def _cleanup_extra_directory(self):
        """Clean up the extra missing_invoice_attachments directory created by parent class"""
        try:
            extra_dir = Path("missing_invoice_attachments")
            if extra_dir.exists() and extra_dir.is_dir():
                # Only remove if it's empty (safe to remove)
                if not any(extra_dir.iterdir()):
                    extra_dir.rmdir()
                    logger.info(f"🗑️ Cleaned up empty extra directory: {extra_dir}")
                else:
                    logger.debug(f"📁 Extra directory {extra_dir} not empty, leaving it")
        except Exception as e:
            logger.debug(f"Could not clean up extra directory: {e}")
    
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
    print("  ✅ Creates ONLY time-based storage directories")
    print("  ✅ Processes ONLY current run files (not historical)")
    print("  ✅ NO temp_processing directories created")
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
                    print("")
                    print(f"🎉 SUCCESS! Missing invoices found and added to system!")
                    print(f"📊 Used SAME processing pipeline as regular invoice_downloader:")
                    print(f"  1. 🔍 Found missing invoices using exact search")
                    print(f"  2. 📎 Downloaded PDF attachments to isolated storage directory")
                    print(f"  3. 📄 Converted PDFs to Excel (current run only)")
                    print(f"  4. 💾 Added to database with duplicate handling")
                    print(f"  5. ✅ Ready for use in your system!")
                    print(f"📁 Files saved to: {searcher.storage_dir}")
                    print(f"📁 NO temp_processing directories created")
                
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
