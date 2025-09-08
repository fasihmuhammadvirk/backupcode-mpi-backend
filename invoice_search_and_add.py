#!/usr/bin/env python3
"""
Invoice Search and Add Script

This script uses the same logic as missing_invoice_finder.py but focuses on:
1. Searching for specific invoice reference numbers in emails
2. Using EXACT matching (must contain "invoice" + exact reference number)
3. Downloading only the invoices we actually need
4. Adding them directly to the system/database

Usage:
    python invoice_search_and_add.py
"""

import sys
from pathlib import Path
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('invoice_search_and_add.log'),
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
        
        try:
            from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER, TIMEZONE
            # Create timestamped folder like invoice_downloader does
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = (f"MISSING_INVOICES_{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                          f"{datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}")
            self.invoice_download_path = Path(INVOICE_DOWNLOAD_FOLDER) / base_folder
        except ImportError:
            logger.warning("Could not import INVOICE_DOWNLOAD_FOLDER/TIMEZONE, using defaults")
            # Create timestamped folder with defaults
            time_window_start = datetime.now() - timedelta(minutes=3)
            base_folder = (f"MISSING_INVOICES_{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                          f"{datetime.now().strftime('%d-%b-%Y_%H-%M-%S')}")
            self.invoice_download_path = Path("downloads") / base_folder
        
        self.invoice_download_path.mkdir(parents=True, exist_ok=True)
        
        # Override directories to use invoice downloader structure
        self.download_dir = self.invoice_download_path
        self.attachments_folder = self.invoice_download_path
        self.storage_dir = Path("storage/missing_invoice_attachments")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Override summary file name
        self.summary_file = "missing_invoice_search_summary.xlsx"
        
        # Import invoice downloader functions
        try:
            from mpi_backend.utils.invoice_downaloder import download_email_attachments
            from mpi_backend.utils.invoice_convertor import convert_invoice_for_email
            from mpi_backend.utils.extracted_data_processor import process_extracted_data
            self.invoice_processing_available = True
            logger.info("✅ Invoice processing pipeline available")
        except ImportError as e:
            self.invoice_processing_available = False
            logger.error(f"❌ Invoice processing pipeline not available: {e}")
        
        logger.info("🎯 Invoice Search and Add initialized with EXACT MATCHING")
        logger.info(f"📁 Downloads will be saved to: {self.invoice_download_path}")
        logger.info(f"📁 Storage copy will be saved to: {self.storage_dir}")
        logger.info("🔄 Will use SAME processing pipeline as regular invoice downloader")
    
    def search_specific_references(self, reference_numbers):
        """
        Search for specific reference numbers with exact matching
        
        Args:
            reference_numbers: List of reference numbers to search for
            
        Returns:
            dict: Results with found/not found invoices
        """
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
                self.process_all_downloaded_invoices()
                
                # Create summary
                logger.info(f"📊 Creating search summary...")
                self.create_summary_excel()
            
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
        Process emails for a reference using the SAME logic as invoice_downloader
        This ensures we download, convert, and add to system exactly like regular invoices
        """
        try:
            if not self.invoice_processing_available:
                logger.error("❌ Invoice processing pipeline not available")
                return False
            
            logger.info(f"📧 Processing {len(email_ids)} emails for ref {ref_no} using INVOICE DOWNLOADER pipeline")
            
            from mpi_backend.utils.invoice_downaloder import download_email_attachments
            
            total_attachments_downloaded = 0
            
            for email_id in email_ids:
                try:
                    logger.info(f"    📧 Processing email {email_id} for ref {ref_no}")
                    
                    # Fetch the full email like invoice_downloader does
                    result, response = self.mail.uid('fetch', email_id, '(BODY.PEEK[])')
                    
                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"    ❌ Failed to fetch email {email_id}")
                        continue
                    
                    # Decode email like invoice_downloader does
                    try:
                        raw_email = response[0][1].decode('utf-8')
                    except UnicodeDecodeError:
                        raw_email = response[0][1].decode('latin-1')
                    
                    import email
                    email_message = email.message_from_string(raw_email)
                    
                    # Use the EXACT SAME download_email_attachments function as invoice_downloader
                    download_success = download_email_attachments(email_message, self.invoice_download_path)
                    
                    if download_success:
                        total_attachments_downloaded += 1
                        logger.info(f"    ✅ Successfully downloaded attachments from email {email_id}")
                    else:
                        logger.warning(f"    ⚠️ No attachments downloaded from email {email_id}")
                        
                except Exception as e:
                    logger.error(f"    ❌ Error processing email {email_id}: {e}")
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
        Process all downloaded invoices using the COMPLETE invoice downloader pipeline:
        1. Convert PDFs to Excel (same as invoice_downloader)
        2. Process extracted data and add to database (same as invoice_downloader)
        """
        try:
            if not self.invoice_processing_available:
                logger.error("❌ Invoice processing pipeline not available")
                return False
            
            logger.info("🔄 Starting COMPLETE invoice processing pipeline...")
            logger.info(f"📁 Processing folder: {self.invoice_download_path}")
            
            # Step 1: Convert invoices (SAME as invoice_downloader)
            from mpi_backend.utils.invoice_convertor import convert_invoice_for_email
            
            logger.info("📄 Step 1: Converting PDFs to Excel...")
            converted_files, failed_files = convert_invoice_for_email(self.invoice_download_path)
            logger.info(f"✅ Conversion complete. Success: {len(converted_files)}, Failed: {len(failed_files)}")
            
            if failed_files:
                logger.warning(f"⚠️ Failed to convert {len(failed_files)} files:")
                for failed_file in failed_files[:5]:  # Show first 5
                    logger.warning(f"  - {failed_file}")
            
            # Step 2: Process extracted data and add to database (SAME as invoice_downloader)
            from mpi_backend.utils.extracted_data_processor import process_extracted_data
            
            logger.info("💾 Step 2: Processing extracted data and adding to database...")
            results = process_extracted_data(converted_files, failed_files)
            logger.info("✅ Data processing complete")
            
            # Log results like invoice_downloader does
            if results:
                created_count = len([r for r in results if r.get('status') == 'created'])
                updated_count = len([r for r in results if r.get('status') == 'updated'])
                duplicate_count = len([r for r in results if r.get('status') == 'duplicate'])
                error_count = len([r for r in results if r.get('status') == 'error'])
                
                logger.info(f"📊 DATABASE RESULTS:")
                logger.info(f"  ✅ Created: {created_count} new invoice records")
                logger.info(f"  🔄 Updated: {updated_count} existing records") 
                logger.info(f"  🔁 Duplicates: {duplicate_count} (skipped)")
                logger.info(f"  ❌ Errors: {error_count}")
                
                if created_count > 0 or updated_count > 0:
                    logger.info("💾 Successfully added missing invoices to system!")
                    return True
                else:
                    logger.warning("⚠️ No invoices were added to system")
                    return False
            else:
                logger.warning("⚠️ No results from data processing")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in complete invoice processing pipeline: {e}")
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
        print(f"  - Downloads: {self.invoice_download_path}/")
        print(f"  - Storage: {self.storage_dir}/")
        print(f"  - Summary: {self.summary_file}")
        
        if results['processed']:
            print(f"\n💾 DATABASE INTEGRATION:")
            print(f"  ✅ Processed using SAME pipeline as invoice_downloader")
            print(f"  📄 PDFs → Excel conversion")
            print(f"  💾 Automatic addition to system database")
            print(f"  🔍 Duplicate detection and handling")
        
        print("="*60)
    
    def search_from_file(self, file_path):
        """
        Search for reference numbers from a file
        
        Args:
            file_path: Path to Excel file containing reference numbers
        """
        try:
            # Read reference numbers from file
            ref_numbers = self.read_reference_numbers_from_file(file_path)
            if not ref_numbers:
                logger.error(f"❌ No reference numbers found in {file_path}")
                return None
            
            logger.info(f"📋 Read {len(ref_numbers)} reference numbers from {file_path}")
            
            # Search for them
            return self.search_specific_references(ref_numbers)
            
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
    print("=" * 60)
    
    try:
        # Create searcher
        searcher = InvoiceSearchAndAdd()
        
        # Check if missing_invoices.xlsx exists
        missing_file = "missing_invoices.xlsx"
        if Path(missing_file).exists():
            print(f"📁 Found {missing_file}")
            print("🔍 Starting search from file...")
            
            # Search from file
            results = searcher.search_from_file(missing_file)
            
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
