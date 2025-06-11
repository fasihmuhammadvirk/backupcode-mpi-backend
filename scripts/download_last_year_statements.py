#!/usr/bin/env python3
"""
Monthly Statement and Invoice Downloader for Historical Data
===========================================================

This script downloads and processes monthly statements and invoices from email for historical periods.
It handles:
- Email connection and search for statement emails (using BODY.PEEK to avoid marking as read)
- PDF download and processing for statements and associated invoice data
- Data extraction and database storage
- S3 upload for storage
- Duplicate detection and error handling
- Support for up to 10 years of historical data

The script ensures NO emails are marked as read during processing by using BODY.PEEK commands.

Usage:
    python scripts/download_last_year_statements.py [options]

Options:
    --from-months-ago INT    Number of months ago to start from (default: 12)
    --to-months-ago INT      Number of months ago to end at (default: 0)
    --download-all-historical Download all statements and invoices for past 10 years
    --suppliers TEXT         Comma-separated list of suppliers to process
    --dry-run               Preview what would be processed without downloading
    --force                 Reprocess existing statements
    --verbose               Enable detailed logging
"""

import sys
import argparse
import logging
import imaplib
import email
import re
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import List, Optional, Dict, Any
import time
from dateutil.relativedelta import relativedelta
from email.utils import parsedate_to_datetime

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, TIMEZONE,
    INVOICE_DOWNLOAD_FOLDER
)
from mpi_backend.database import get_db
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement
)
from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
from mpi_backend.utils.s3_utils import upload_file
from mpi_backend.database.controllers.statement_controller import (
    StatementController
)

# Configure logging
logger = logging.getLogger(__name__)

# Statement sender emails (using same pattern as invoice EXCLUDED_SENDERS)
STATEMENT_SENDERS = [  # Statement sender emails to include
    "info@wwps.co",
    "bmwpsupply@gmail.com", 
    "billing@ysplumbing.com",
    "accounting@supremeplumbingnj.com",
    "orders@supremeplumbingnj.com",
    "billing@pyramidps.com",
    "purchasing@pyramidps.com",
    "breindy@parkplumbingsupply.com",
    "accounting@kjpsinc.com",
    "billing@afsupply.com",
    "ar@opusoperations.com",
    "AR@opusoperations.com",
    "billing@flowmarksupply.com",
    "mendy@flowmarksupply.com",
    "Info@wwps.co"
]

# Statement suppliers that send monthly statements
STATEMENT_SUPPLIERS = [
    "BMW Plumbing Supplies",
    "World Wide Plumbing", 
    "Y & S Plumbing Supply",
    "Supreme Plumbing Supply",
    "Pyramid Plumbing",
    "ABC Opus Services",
    "Park Plumbing Supply",
    "Gotham Plumbing Supply",
    "FW Webb Plumbing Supply",
    "Flow Mark Plumbing Supply"
]

# Email patterns for each supplier
SUPPLIER_EMAIL_PATTERNS = {
    "BMW Plumbing Supplies": ["bmw", "bmwpsupply"],
    "World Wide Plumbing": ["world wide", "wwps"],
    "Y & S Plumbing Supply": ["y&s", "ysplumbing", "y s plumbing"],
    "Supreme Plumbing Supply": ["supreme", "supremeplumbingnj"],
    "Pyramid Plumbing": ["pyramid", "pyramidps"],
    "ABC Opus Services": ["abc opus", "opusoperations"],
    "Park Plumbing Supply": ["park plumbing", "parkplumbingsupply"],
    "Gotham Plumbing Supply": ["gotham"],
    "FW Webb Plumbing Supply": ["webb", "fwwebb"],
    "Flow Mark Plumbing Supply": ["flow mark", "flowmarksupply"]
}


class StatementDownloader:
    """Enhanced statement downloader for historical data using invoice logic"""
    
    def __init__(self, dry_run=False, force=False, verbose=False):
        self.dry_run = dry_run
        self.force = force
        self.verbose = verbose
        self.mail = None
        self.db_session = None
        self.controller = None
        
        # Statistics tracking
        self.stats = {
            'emails_searched': 0,
            'emails_found': 0,
            'pdfs_downloaded': 0,
            'statements_processed': 0,
            'statements_saved': 0,
            'errors': 0,
            'skipped_existing': 0
        }
        
        # Setup logging
        log_level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(
                    f'statement_download_'
                    f'{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
                )
            ]
        )
    
    def __enter__(self):
        """Context manager entry"""
        self.connect_to_email()
        self.connect_to_database()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()
    
    def connect_to_email(self):
        """Establish IMAP connection"""
        try:
            logger.info("Connecting to email server...")
            self.mail = imaplib.IMAP4_SSL(SMTP_SERVER)
            self.mail.login(LOGIN_EMAIL, LOGIN_PWD)
            self.mail.select('inbox')
            logger.info("Successfully connected to email")
        except Exception as e:
            logger.error(f"Failed to connect to email: {str(e)}")
            raise
    
    def connect_to_database(self):
        """Establish database connection"""
        try:
            logger.info("Connecting to database...")
            db_context = contextmanager(get_db)
            self.db_session = db_context().__enter__()
            self.controller = StatementController(self.db_session)
            logger.info("Successfully connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise
    
    def cleanup(self):
        """Clean up connections"""
        try:
            if self.mail:
                self.mail.close()
                self.mail.logout()
                logger.info("Email connection closed")
        except Exception as e:
            logger.warning(f"Error closing email connection: {str(e)}")
        
        try:
            if self.db_session:
                self.db_session.close()
                logger.info("Database connection closed")
        except Exception as e:
            logger.warning(f"Error closing database connection: {str(e)}")
    
    def generate_date_ranges(self, from_months_ago: int, 
                            to_months_ago: int) -> List[tuple]:
        """Generate date ranges for each month to search"""
        date_ranges = []
        current_date = datetime.now(TIMEZONE)
        
        for months_back in range(to_months_ago, from_months_ago + 1):
            # Calculate target month using relativedelta for accurate arithmetic
            target_date = current_date - relativedelta(months=months_back)
            
            # Get first and last day of that month
            first_day = target_date.replace(day=1)
            # Get last day of the month
            if target_date.month == 12:
                last_day = (target_date.replace(year=target_date.year + 1, 
                                               month=1, day=1) - 
                           timedelta(days=1))
            else:
                last_day = (target_date.replace(month=target_date.month + 1, 
                                               day=1) - 
                           timedelta(days=1))
            
            date_ranges.append((first_day, last_day))
        
        return date_ranges
    
    def ensure_suppliers_exist(self):
        """Ensure all statement suppliers exist in database"""
        try:
            logger.info("Ensuring all suppliers exist in database...")
            
            for supplier_name in STATEMENT_SUPPLIERS:
                existing = self.db_session.query(PlumbingSupplier).filter(
                    PlumbingSupplier.name == supplier_name
                ).first()
                
                if not existing:
                    supplier = PlumbingSupplier(
                        name=supplier_name,
                        is_active="Active"
                    )
                    self.db_session.add(supplier)
                    logger.info(f"Created supplier: {supplier_name}")
            
            self.db_session.commit()
            logger.info("All suppliers verified in database")
            
        except Exception as e:
            logger.error(f"Error ensuring suppliers exist: {str(e)}")
            self.db_session.rollback()
            raise
    
    def detect_supplier_from_email(self, email_subject: str, 
                                  sender_email: str) -> Optional[str]:
        """Detect supplier from email subject and sender - invoice logic"""
        try:
            subject = (email_subject or "").lower()
            sender = (sender_email or "").lower()
            
            for supplier_name, patterns in SUPPLIER_EMAIL_PATTERNS.items():
                for pattern in patterns:
                    pattern_lower = pattern.lower()
                    if pattern_lower in subject or pattern_lower in sender:
                        logger.debug(
                            f"Detected supplier '{supplier_name}' from "
                            f"pattern '{pattern}' in subject: '{email_subject}' "
                            f"or sender: '{sender_email}'"
                        )
                        return supplier_name
            
            # Log unknown suppliers for manual review
            logger.warning(
                f"Unknown supplier - Subject: '{email_subject}', "
                f"Sender: '{sender_email}'"
            )
            return "no_supplier"
            
        except Exception as e:
            logger.error(f"Error detecting supplier: {str(e)}")
            return "no_supplier"
    
    def extract_statement_date_from_subject(self, 
                                           subject: str) -> Optional[datetime]:
        """Extract statement date from email subject"""
        try:
            if not subject:
                return datetime.now()
                
            # Common patterns for statement dates in subjects
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',    # MM/DD/YYYY or M/D/YYYY
                r'(\d{1,2}/\d{1,2}/\d{2})',    # MM/DD/YY or M/D/YY  
                r'(\d{1,2}-\d{1,2}-\d{4})',    # MM-DD-YYYY
                r'(\d{1,2}-\d{1,2}-\d{2})',    # MM-DD-YY
                r'(\w+\s+\d{4})',              # Month YYYY 
                r'(\d{4}-\d{2})',              # YYYY-MM
                r'(\d{2}/\d{4})',              # MM/YYYY
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, subject)
                if match:
                    date_str = match.group(1)
                    logger.debug(
                        f"Found date pattern '{date_str}' in subject: "
                        f"'{subject}'"
                    )
                    
                    # Try different date formats
                    formats_to_try = [
                        '%m/%d/%Y', '%m/%d/%y', 
                        '%m-%d-%Y', '%m-%d-%y',
                        '%B %Y', '%b %Y',
                        '%Y-%m', '%m/%Y'
                    ]
                    
                    for fmt in formats_to_try:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt)
                            logger.debug(
                                f"Successfully parsed date '{date_str}' "
                                f"with format '{fmt}' -> {parsed_date}"
                            )
                            return parsed_date
                        except ValueError:
                            continue
            
            # If no date found in subject, default to current month
            logger.debug(
                f"No date pattern found in subject: '{subject}', "
                f"using current month"
            )
            return datetime.now()
            
        except Exception as e:
            logger.error(
                f"Date extraction failed for subject '{subject}': {str(e)}"
            )
            return datetime.now()
    
    def search_emails_for_date_range(self, start_date: datetime, 
                                    end_date: datetime) -> List[str]:
        """Search for statement emails in date range - using invoice logic"""
        try:
            # Format dates for IMAP search
            since_date = start_date.strftime('%d-%b-%Y')
            before_date = (end_date + timedelta(days=1)).strftime('%d-%b-%Y')
            
            logger.info(
                f"Searching emails from {since_date} to "
                f"{end_date.strftime('%d-%b-%Y')}"
            )
            
            # Search all emails in timeframe first (like invoice downloader)
            search_query = f'(SINCE {since_date} BEFORE {before_date})'
            
            if self.verbose:
                logger.debug(f"Search query: {search_query}")
            
            # Execute search
            result, data = self.mail.uid('search', None, search_query)
            if result != 'OK':
                logger.error(f"Email search failed: {result}")
                return []
            
            raw_email_ids = data[0].split() if data[0] else []
            logger.info(f"Found {len(raw_email_ids)} emails in time frame")
            
            # Filter emails like invoice downloader (by sender + subject)
            filtered_email_ids = []
            for idx, email_id in enumerate(raw_email_ids, 1):
                try:
                    email_id = (email_id.decode('utf-8') 
                               if isinstance(email_id, bytes) else email_id)
                    logger.debug(
                        f"Processing email {idx}/{len(raw_email_ids)} - "
                        f"UID: {email_id}"
                    )

                    # Always use BODY.PEEK to never mark emails as read
                    result, msg_data = self.mail.uid(
                        'fetch', email_id, 
                        '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])'
                    )

                    if result != 'OK':
                        logger.warning(
                            f"Failed to fetch headers for UID {email_id}: "
                            f"{result}"
                        )
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    from_email = email.utils.parseaddr(msg.get('From', ''))[1]
                    subject = msg.get('Subject', '').lower()

                    # Filter by statement senders AND subject keyword
                    # (case-insensitive)
                    if (from_email in STATEMENT_SENDERS and 
                        'monthly statement' in subject):
                        filtered_email_ids.append(email_id)
                        logger.debug(
                            f"Statement email UID {email_id} from: {from_email}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing email UID {email_id}: {str(e)}"
                        f"\n{traceback.format_exc()}"
                    )
                    continue
            
            self.stats['emails_found'] += len(filtered_email_ids)
            logger.info(
                f"Found {len(filtered_email_ids)} statement emails"
            )
            return filtered_email_ids
            
        except Exception as e:
            logger.error(
                f"Error searching emails: {str(e)}"
                f"\n{traceback.format_exc()}"
            )
            return []
    
    def statement_already_exists(self, supplier_name: str, 
                                statement_date: datetime) -> bool:
        """Check if statement already exists for supplier and month"""
        try:
            # Get supplier
            supplier = self.db_session.query(PlumbingSupplier).filter(
                PlumbingSupplier.name == supplier_name
            ).first()
            
            if not supplier:
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
            
            existing_statement = self.db_session.query(
                PlumbingStatement
            ).filter(
                PlumbingStatement.supplier_id == supplier.id,
                PlumbingStatement.statement_date >= month_start.date(),
                PlumbingStatement.statement_date < next_month.date()
            ).first()
            
            return existing_statement is not None
            
        except Exception as e:
            logger.error(f"Error checking statement existence: {str(e)}")
            return False
    
    def download_attachments_from_email(self, email_id: str, 
                                       base_folder: Path) -> List[str]:
        """Download PDF attachments from email - using invoice logic"""
        try:
            # Always use BODY.PEEK to never mark emails as read
            result, response = self.mail.uid(
                'fetch', email_id, '(BODY.PEEK[])'
            )
            if result != 'OK' or not response or not response[0]:
                logger.error(f"Failed to fetch email UID {email_id}")
                return []
            
            # Parse email
            try:
                raw_email = response[0][1].decode('utf-8')
            except UnicodeDecodeError:
                raw_email = response[0][1].decode('latin-1')
            
            email_message = email.message_from_string(raw_email)
            
            # Get email metadata
            subject = email_message.get('Subject', '')
            sender = email.utils.parseaddr(email_message.get('From', ''))[1]
            
            # Detect supplier
            supplier_name = self.detect_supplier_from_email(subject, sender)
            if supplier_name == "no_supplier":
                logger.warning(
                    f"Cannot detect supplier for email {email_id}, skipping"
                )
                return []
            
            # Date handling (same as invoice downloader)
            date_header = email_message.get('Date', '')
            if not date_header:
                logger.warning(
                    "No Date header in email, using current time"
                )
                date_time_obj = datetime.now(TIMEZONE)
            else:
                try:
                    date_time_obj = parsedate_to_datetime(
                        date_header
                    ).astimezone(TIMEZONE)
                except Exception as date_error:
                    logger.error(
                        f"Date parsing failed: {str(date_error)}, "
                        f"using current time"
                    )
                    date_time_obj = datetime.now(TIMEZONE)
            
            # Extract statement date
            statement_date = self.extract_statement_date_from_subject(subject)
            
            # Check if already exists (unless force mode)
            if not self.force and self.statement_already_exists(
                supplier_name, statement_date
            ):
                logger.info(
                    f"Statement already exists for {supplier_name} - "
                    f"{statement_date.strftime('%Y-%m')}, skipping"
                )
                self.stats['skipped_existing'] += 1
                return []
            
            # Download attachments (using invoice structure)
            downloaded_files = []
            
            for part in email_message.walk():
                try:
                    if (part.get_content_maintype() != 'multipart' and 
                            part.get('Content-Disposition') is not None):
                        
                        filename = part.get_filename()
                        if (not filename or 
                            not filename.lower().endswith(('.pdf', '.PDF'))):
                            continue
                        
                        # Create folder structure like invoice downloader
                        inner_dir = (
                            f'{date_time_obj.month}-{date_time_obj.day}-'
                            f'{date_time_obj.year}'
                        )
                        supplier_folder = base_folder / supplier_name
                        supplier_folder.mkdir(parents=True, exist_ok=True)
                        inner_dir_path = supplier_folder / inner_dir
                        inner_dir_path.mkdir(parents=True, exist_ok=True)
                        
                        # Create unique filename
                        month_year = statement_date.strftime('%Y-%m')
                        unique_filename = (
                            f"{supplier_name}_{month_year}_{filename}"
                        )
                        filepath = inner_dir_path / unique_filename
                        
                        if self.dry_run:
                            logger.info(
                                f"[DRY RUN] Would download: {unique_filename}"
                            )
                            downloaded_files.append(str(filepath))
                        else:
                            # Save file
                            with open(filepath, 'wb') as f:
                                f.write(part.get_payload(decode=True))
                            
                            logger.info(f"Downloaded: {unique_filename}")
                            downloaded_files.append(str(filepath))
                            self.stats['pdfs_downloaded'] += 1
                
                except Exception as part_error:
                    logger.error(
                        f"Error processing attachment in email {email_id}: "
                        f"{str(part_error)}\n{traceback.format_exc()}"
                    )
                    continue
            
            return downloaded_files
            
        except Exception as e:
            logger.error(
                f"Error downloading attachments from email {email_id}: "
                f"{str(e)}\n{traceback.format_exc()}"
            )
            self.stats['errors'] += 1
            return []
    
    def process_statement_file(self, file_path: str) -> bool:
        """Process a downloaded statement file"""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would process: {file_path}")
                return True
            
            logger.info(f"Processing statement file: {file_path}")
            
            # Extract supplier name from file path structure
            # Path structure: base_folder/supplier_name/date_folder/filename
            supplier_name = None
            file_path_obj = Path(file_path)
            
            if len(file_path_obj.parts) >= 2:
                # Get the supplier directory name (second to last in path)
                supplier_dir = file_path_obj.parts[-3]  # Go up 3 levels: filename -> date_folder -> supplier_name
                # Check if this matches one of our known suppliers
                if supplier_dir in STATEMENT_SUPPLIERS:
                    supplier_name = supplier_dir
                    logger.info(f"Extracted supplier from path: {supplier_name}")
                else:
                    # Try to extract from filename if path doesn't work
                    # Filename format: supplier_name_YYYY-MM_original_filename.pdf
                    for supplier in STATEMENT_SUPPLIERS:
                        supplier_underscore = supplier.replace(' ', '_').replace('&', '')
                        if file_path_obj.name.startswith(supplier_underscore):
                            supplier_name = supplier
                            logger.info(f"Extracted supplier from filename: {supplier_name}")
                            break
            
            if not supplier_name:
                logger.warning(f"Could not extract supplier name for {file_path}, will rely on PDF detection")
            
            # Extract data using statement extractor with supplier name
            extractor = StatementExtractor(
                pdf_path=file_path,
                save_to_db=True,
                save_to_excel=False,
                db_session=self.db_session,
                supplier_name=supplier_name  # Pass email-detected supplier name
            )
            
            # Extract data
            success = extractor.extract_all_pages()
            if not success:
                logger.error(f"Failed to extract data from: {file_path}")
                self.stats['errors'] += 1
                return False
            
            # Save to database
            db_success = extractor.save_to_database()
            if not db_success:
                logger.error(f"Failed to save to database: {file_path}")
                self.stats['errors'] += 1
                return False
            
            # Upload to S3
            try:
                file_key = f"statements/{Path(file_path).name}"
                upload_file(file_path, file_key, is_invoice=False)
                logger.info(f"Uploaded to S3: {file_key}")
            except Exception as s3_error:
                logger.warning(
                    f"S3 upload failed for {file_path}: {str(s3_error)}"
                )
                # Don't fail the whole process for S3 issues
            
            self.stats['statements_processed'] += 1
            self.stats['statements_saved'] += 1
            
            logger.info(f"Successfully processed: {file_path}")
            return True
            
        except Exception as e:
            logger.error(
                f"Error processing statement {file_path}: {str(e)}"
                f"\n{traceback.format_exc()}"
            )
            self.stats['errors'] += 1
            return False
    
    def download_statements_for_period(self, from_months_ago: int, 
                                      to_months_ago: int, 
                                      supplier_filter: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Main method to download statements for a period
        
        Downloads monthly statements which contain detailed invoice data for each supplier.
        Each statement PDF contains a table of all invoices for that month, so this
        effectively downloads both statements AND all the invoice records within them.
        
        Uses BODY.PEEK to ensure NO emails are marked as read during processing.
        """
        try:
            # Ensure suppliers exist in database
            self.ensure_suppliers_exist()
            
            # Generate date ranges
            date_ranges = self.generate_date_ranges(
                from_months_ago, to_months_ago
            )
            
            # Setup download directory (like invoice downloader)
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = (
                f"{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                f"{datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}"
            )
            base_folder_path = (Path(INVOICE_DOWNLOAD_FOLDER) / 
                               "historical_statements" / base_folder)
            
            if not self.dry_run:
                base_folder_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created download directory: {base_folder_path}")
            
            # Process each date range
            all_downloaded_files = []
            
            for start_date, end_date in date_ranges:
                logger.info(
                    f"Processing period: {start_date.strftime('%Y-%m')} "
                    f"to {end_date.strftime('%Y-%m')}"
                )
                
                # Search for emails in this period
                email_ids = self.search_emails_for_date_range(
                    start_date, end_date
                )
                self.stats['emails_searched'] += len(email_ids)
                
                # Process each email
                for email_id in email_ids:
                    try:
                        downloaded_files = self.download_attachments_from_email(
                            email_id, base_folder_path
                        )
                        all_downloaded_files.extend(downloaded_files)
                        
                        # Small delay to be nice to the email server
                        time.sleep(0.1)
                        
                    except Exception as email_error:
                        logger.error(
                            f"Error processing email {email_id}: "
                            f"{str(email_error)}\n{traceback.format_exc()}"
                        )
                        self.stats['errors'] += 1
                        continue
            
            # Process downloaded files
            if not self.dry_run:
                logger.info(
                    f"Processing {len(all_downloaded_files)} downloaded files..."
                )
                
                for file_path in all_downloaded_files:
                    try:
                        # Apply supplier filter if specified
                        if supplier_filter:
                            file_supplier = None
                            for supplier in supplier_filter:
                                if supplier.replace(' ', '_') in file_path:
                                    file_supplier = supplier
                                    break
                            
                            if not file_supplier:
                                logger.info(
                                    f"Skipping {file_path} - "
                                    f"not in supplier filter"
                                )
                                continue
                        
                        self.process_statement_file(file_path)
                        
                    except Exception as process_error:
                        logger.error(
                            f"Error processing file {file_path}: "
                            f"{str(process_error)}\n{traceback.format_exc()}"
                        )
                        self.stats['errors'] += 1
                        continue
                
                # Clean up temporary files
                try:
                    import shutil
                    shutil.rmtree(base_folder_path)
                    logger.info(
                        f"Cleaned up temporary directory: {base_folder_path}"
                    )
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to clean up {base_folder_path}: "
                        f"{str(cleanup_error)}"
                    )
            
            # Return results
            return {
                'success': True,
                'statistics': self.stats,
                'period': f"{from_months_ago} to {to_months_ago} months ago",
                'files_processed': len(all_downloaded_files)
            }
            
        except Exception as e:
            logger.error(
                f"Error in download_statements_for_period: {str(e)}"
                f"\n{traceback.format_exc()}"
            )
            return {
                'success': False,
                'error': str(e),
                'statistics': self.stats
            }
    
    def print_summary(self):
        """Print a summary of the operation"""
        print("\n" + "="*60)
        print("STATEMENT AND INVOICE DOWNLOAD SUMMARY")
        print("="*60)
        print(f"Emails searched:       {self.stats['emails_searched']:,}")
        print(f"Emails found:          {self.stats['emails_found']:,}")
        print(f"PDFs downloaded:       {self.stats['pdfs_downloaded']:,}")
        print(f"Statements processed:  {self.stats['statements_processed']:,}")
        print(f"Statements saved:      {self.stats['statements_saved']:,}")
        print(f"Skipped existing:      {self.stats['skipped_existing']:,}")
        print(f"Errors:                {self.stats['errors']:,}")
        print("="*60)
        print("📧 No emails were marked as read (used BODY.PEEK)")
        print("📄 Each statement contains multiple invoice records")
        print("="*60)


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Download and process monthly statements and invoices for historical periods (up to 10 years)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download statements and invoices from the last 12 months
  python scripts/download_last_year_statements.py
  
  # Download statements and invoices from the last 24 months
  python scripts/download_last_year_statements.py --from-months-ago 24
  
  # Download 10 years of historical statements and invoices for all suppliers
  python scripts/download_last_year_statements.py --download-all-historical
  
  # Download for specific suppliers only
  python scripts/download_last_year_statements.py --suppliers "World Wide Plumbing,Y & S Plumbing Supply"
  
  # Preview what would be downloaded without actually processing
  python scripts/download_last_year_statements.py --download-all-historical --dry-run
        """
    )
    
    # Time range options
    parser.add_argument(
        '--from-months-ago',
        type=int,
        default=12,
        help='Number of months ago to start from (default: 12)'
    )
    parser.add_argument(
        '--to-months-ago',
        type=int,
        default=0,
        help='Number of months ago to end at (default: 0 - current month)'
    )
    
    # Historical download option
    parser.add_argument(
        '--download-all-historical',
        action='store_true',
        help='Download all historical statements and invoices for the past 10 years (overrides --from-months-ago)'
    )
    
    # Supplier filtering
    parser.add_argument(
        '--suppliers',
        type=str,
        help='Comma-separated list of suppliers to process (e.g., "BMW Plumbing Supplies,World Wide Plumbing")'
    )
    
    # Processing options
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be processed without downloading/processing'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Reprocess existing statements (skip duplicate check)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable detailed logging'
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    
    # Parse supplier filter
    supplier_filter = None
    if args.suppliers:
        supplier_filter = [s.strip() for s in args.suppliers.split(',')]
        logger.info(f"Supplier filter: {supplier_filter}")
    
    # Set time range
    if args.download_all_historical:
        from_months_ago = 120  # 10 years (12 months * 10)
        to_months_ago = 0
        logger.info("🚀 DOWNLOADING ALL HISTORICAL STATEMENTS AND INVOICES (PAST 10 YEARS)")
        logger.info("This will download statements and associated invoice data from all suppliers for the past 10 years")
        logger.info("📧 Using BODY.PEEK commands to ensure NO emails are marked as read")
        if not args.dry_run:
            confirmation = input("This is a large operation that will process 10 years of data. Continue? (y/N): ")
            if confirmation.lower() != 'y':
                print("Operation cancelled.")
                return
    else:
        from_months_ago = args.from_months_ago
        to_months_ago = args.to_months_ago
        logger.info(f"📧 Using BODY.PEEK commands to ensure NO emails are marked as read")
    
    # Create downloader and run
    try:
        with StatementDownloader(
            dry_run=args.dry_run, 
            force=args.force, 
            verbose=args.verbose
        ) as downloader:
            
            # Download statements for the specified period
            result = downloader.download_statements_for_period(
                from_months_ago=from_months_ago,
                to_months_ago=to_months_ago,
                supplier_filter=supplier_filter
            )
            
            # Print results
            downloader.print_summary()
            
            if result['success']:
                print(f"\n✅ Operation completed successfully!")
                print(f"Period: {result['period']}")
                print(f"Files processed: {result['files_processed']}")
                
                if args.download_all_historical:
                    print("\n🎉 Historical download completed!")
                    print("All available monthly statements and invoices from the past 10 years have been processed.")
                    print("📧 No emails were marked as read during this process.")
                    print("Check the summary above for detailed statistics.")
                else:
                    print("📧 No emails were marked as read during this process.")
            else:
                print(f"\n❌ Operation failed: {result.get('error', 'Unknown error')}")
                return 1
                
    except KeyboardInterrupt:
        print("\n⚠️ Operation interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        print(f"\n❌ Critical error: {str(e)}")
        return 1
    
    return 0


if __name__ == "__main__":
    main() 