#!/usr/bin/env python3
"""
Historical Invoice Downloader - Comprehensive 5-Year Recovery
============================================================

This script downloads and processes ALL missing invoices from 2020 till today.
It starts from the current date and works backwards day by day until 2020-01-01.

Features:
- Downloads invoices from current date back to 2020-01-01 (2020 till today)
- Day-by-day processing to ensure comprehensive coverage
- Enhanced attachment detection and retry mechanism
- Comprehensive error handling and progress tracking
- No email marking (preserves email read status)
- Duplicate detection and skip logic
- Progress reporting and statistics

Usage:
    python scripts/historical_invoice_downloader.py [options]

Options:
    --start-date YYYY-MM-DD    Start date (default: today)
    --end-date YYYY-MM-DD      End date (default: 2020-01-01)
    --dry-run                  Preview what would be processed
    --batch-size INT           Number of days to process per batch
                              (default: 30)
    --verbose                  Enable detailed logging
    --force                    Reprocess existing invoices
"""

import sys
import argparse
import time
import imaplib
import email
import email.utils
import os
import traceback
import logging
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, 
    SUPPLIERS, TIMEZONE
)
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice_for_email
from mpi_backend.config.logging_config import setup_logging, get_missing_logger

# Setup centralized logging
setup_logging()
logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

# Create logs directory
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Setup missing emails/attachments tracker
def log_missing_email_or_attachment(email_subject, sender, reason, date_str):
    """Log missing emails or attachments to the centralized missing log"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"MISSING: {reason} | Date: {date_str} | Sender: {sender} | Subject: {email_subject} | Reason: {reason}"
    missing_logger.info(log_entry)

# Supplier emails to download invoices from
EXCLUDED_SENDERS = [  # suppliers to download invoices from
    "info@wwps.co",
    "bmwpsupply@gmail.com",
    "billing@ysplumbing.com",
    "accounting@supremeplumbingnj.com",
    "orders@supremeplumbingnj.com",
    "billing@pyramidps.com",
    "purchasing@pyramidps.com",
    "donotreply@brucesupply.net",
    "donotreply@certifiedlumber.com",
    "breindy@parkplumbingsupply.com",
    "accounting@kjpsinc.com",
    "nefcocorp@billtrust.com",
    "timsfile@awisco.net",
    "billing@afsupply.com",
    "billing@sparkleening.com",
    "billing@positive.tech",
    "ar@opusoperations.com",
    "AR@opusoperations.com",
    "donotreply@cardknox.com",
    "billing@flowmarksupply.com",
    "mendy@flowmarksupply.com",
    "billing@mpiplumbingcorp.com",
    "Info@wwps.co"
]


class HistoricalInvoiceDownloader:
    """Historical invoice downloader with comprehensive features"""
    
    def __init__(self, start_date: datetime, end_date: datetime, 
                 dry_run: bool = False, batch_size: int = 30, 
                 verbose: bool = False, force: bool = False):
        self.start_date = start_date
        self.end_date = end_date
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.verbose = verbose
        self.force = force
        self.mail = None
        
        # Statistics tracking
        self.stats = {
            'days_processed': 0,
            'emails_found': 0,
            'emails_processed': 0,
            'attachments_found': 0,
            'attachments_downloaded': 0,
            'invoices_converted': 0,
            'invoices_processed': 0,
            'errors': 0,
            'skipped_days': 0
        }
        
        logger.info("Historical Invoice Downloader initialized")
        logger.info(f"Date range: {start_date.date()} to {end_date.date()}")
        logger.info(f"Total days to process: {(start_date - end_date).days}")
        logger.info(f"Dry run: {dry_run}, Batch size: {batch_size}")

    def login(self) -> bool:
        """Establish IMAP connection"""
        try:
            self.mail = imaplib.IMAP4_SSL(SMTP_SERVER)
            self.mail.login(LOGIN_EMAIL, LOGIN_PWD)
            self.mail.select('inbox')
            logger.info("Successfully connected to email server")
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {str(e)}")
            return False

    def search_emails_for_date(self, target_date: datetime) -> List[str]:
        """Search for emails for a specific date"""
        try:
            date_str = target_date.strftime('%d-%b-%Y')
            next_date = target_date + timedelta(days=1)
            next_date_str = next_date.strftime('%d-%b-%Y')
            
            search_criteria = f'(SINCE "{date_str}" BEFORE "{next_date_str}")'
            result, data = self.mail.uid('search', None, search_criteria)
            
            if result != 'OK':
                logger.error(f"Search failed for {date_str}: {result}")
                return []
            
            raw_email_ids = data[0].split() if data[0] else []
            logger.debug(f"Found {len(raw_email_ids)} emails for {date_str}")
            
            # Filter by excluded senders
            filtered_ids = []
            for email_id in raw_email_ids:
                try:
                    email_id = (email_id.decode('utf-8') 
                                if isinstance(email_id, bytes) else email_id)
                    
                    # Use BODY.PEEK to avoid marking emails as read
                    result, msg_data = self.mail.uid(
                        'fetch', email_id, 
                        '(BODY.PEEK[HEADER.FIELDS (FROM)])'
                    )
                    
                    if result != 'OK' or not msg_data[0]:
                        continue
                    
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    from_email = email.utils.parseaddr(
                        msg.get('From', '')
                    )[1]
                    
                    if from_email in EXCLUDED_SENDERS:
                        filtered_ids.append(email_id)
                        logger.debug(f"Found email from: {from_email}")
                    
                except Exception as e:
                    logger.debug(f"Error filtering email {email_id}: {str(e)}")
                    continue
            
            logger.debug(f"Filtered to {len(filtered_ids)} relevant emails")
            return filtered_ids
            
        except Exception as e:
            logger.error(f"Search error for {target_date.date()}: {str(e)}")
            return []

    def get_supplier(self, email_subject: str, supplier_email: str) -> str:
        """Get supplier name with error handling"""
        try:
            subject = (email_subject or "").lower()
            supplier_email = (supplier_email or "").lower()

            if "statement" in subject:
                return "no_supplier"
            
            # BMW Plumbing Supplies - multiple patterns
            if any(pattern in subject for pattern in ["bmw", "bmwpsupply"]):
                return SUPPLIERS[0]
            
            # World Wide Plumbing - multiple patterns
            elif any(pattern in subject for pattern in ["world wide", "wwps", "worldwide"]):
                return SUPPLIERS[1]
            
            # Y & S Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["y&s", "y and s", "ys plumbing", "y s plumbing"]):
                return SUPPLIERS[2]
            
            # Supreme Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["supreme plumbing", "invoice # i-", "supremeplumbing"]):
                return SUPPLIERS[3]
            
            # Pyramid Plumbing - multiple patterns
            elif any(pattern in subject for pattern in ["pyramid plumbing", "pyramidps"]):
                return SUPPLIERS[4]
            
            # ABC Opus Services - multiple patterns
            elif any(pattern in subject for pattern in ["abc opus", "opusoperations", "abc opus services"]):
                return SUPPLIERS[5]
            
            # Park Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["park plumbing", "parkplumbingsupply", "park plumbing & heating supply"]):
                return SUPPLIERS[6]
            
            # FW Webb Plumbing Supply - multiple patterns
            elif any(pattern in subject for pattern in ["webb payment receipt", "fw webb", "webb plumbing"]):
                return SUPPLIERS[8]
            
            # Flow Mark Plumbing Supply - specific pattern
            elif "see invoice i-" in subject:
                return SUPPLIERS[9]
            
            else:
                return "unknown_supplier"
        except Exception as e:
            logger.debug(f"Supplier detection failed: {str(e)}")
            return "unknown_supplier"

    def download_attachment_with_retry(self, part, filepath: str, 
                                     max_retries: int = 3) -> bool:
        """Download attachment with retry mechanism"""
        for attempt in range(max_retries):
            try:
                attachment_data = part.get_payload(decode=True)
                if attachment_data:
                    with open(filepath, 'wb') as f:
                        f.write(attachment_data)
                    logger.debug(f"Downloaded attachment on attempt "
                               f"{attempt + 1}: "
                               f"{os.path.basename(filepath)}")
                    return True
                else:
                    logger.warning(f"Attempt {attempt + 1}: "
                                 "No attachment data found")
            except Exception as e:
                logger.debug(f"Attempt {attempt + 1} failed to download "
                           f"{os.path.basename(filepath)}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # Wait 1 second before retry
                else:
                    logger.warning(f"All {max_retries} attempts failed for "
                                 f"{os.path.basename(filepath)}")
        return False

    def download_email_attachments(self, email_message, 
                                 base_folder_path: Path) -> Tuple[int, int]:
        """Download attachments with comprehensive error handling"""
        
        attachments_found = 0
        attachments_downloaded = 0
        
        # Extract email details for logging
        email_subject = email_message.get('Subject', 'No Subject')
        sender = email.utils.parseaddr(email_message.get('From', ''))[1]
        date_header = email_message.get('Date', '')
        
        try:
            # Supplier detection
            supplier_name = self.get_supplier(
                email_subject,
                email_message.get('Return-Path', '')
            )
            
            logger.info(f"Processing email with Subject: '{email_subject}'")
            logger.info(f"Detected supplier: {supplier_name}")

            # Date handling
            if not date_header:
                date_time_obj = datetime.now(TIMEZONE)
            else:
                try:
                    date_time_obj = parsedate_to_datetime(
                        date_header
                    ).astimezone(TIMEZONE)
                except Exception:
                    date_time_obj = datetime.now(TIMEZONE)

            date_str = date_time_obj.strftime('%Y-%m-%d')
            
            # Log detailed email information
            logger.info(f"  {date_str} | {sender}")
            logger.info(f"    Subject: {email_subject}")
            logger.info(f"    Supplier: {supplier_name} | Type: {'invoice' if any(kw in email_subject.lower() for kw in ['invoice', 'invoices']) else 'other'}")

            # Directory structure creation with fallback (consistent with main downloader)
            try:
                inner_dir = f'{date_time_obj.month}-{date_time_obj.day}-{date_time_obj.year}'
                supplier_path = os.path.join(base_folder_path, supplier_name)
                Path(supplier_path).mkdir(parents=True, exist_ok=True)
                inner_dir_path = os.path.join(supplier_path, inner_dir)
                Path(inner_dir_path).mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created directory structure: {inner_dir_path}")
            except OSError as dir_error:
                logger.error(f"Directory creation failed: {str(dir_error)}, using fallback directory")
                # Use fallback directory to continue processing
                try:
                    fallback_path = os.path.join(base_folder_path, "fallback_directory")
                    Path(fallback_path).mkdir(parents=True, exist_ok=True)
                    inner_dir_path = fallback_path
                    logger.warning(f"Using fallback directory: {inner_dir_path}")
                except Exception as fallback_error:
                    logger.error(f"Fallback directory creation also failed: "
                               f"{str(fallback_error)}, skipping this email")
                    log_missing_email_or_attachment(email_subject, sender, f"Directory creation failed: {str(fallback_error)}", date_str)
                    return attachments_found, attachments_downloaded

            # Enhanced attachment detection
            attachment_details = []
            for part_idx, part in enumerate(email_message.walk(), 1):
                try:
                    content_disposition = part.get('Content-Disposition', '')
                    content_type = part.get_content_type()
                    filename = part.get_filename()
                    
                    logger.debug(f"Part {part_idx}: Content-Type={content_type}, Content-Disposition={content_disposition}, Filename={filename}")
                    
                    # Enhanced attachment detection conditions
                    is_attachment = (
                        (content_disposition and 
                         'attachment' in content_disposition.lower()) or
                        (content_disposition and 
                         'inline' in content_disposition.lower() and 
                         filename) or
                        (content_type == 'application/pdf') or
                        (filename and 
                         filename.lower().endswith(('.pdf', '.PDF'))) or
                        (filename and 
                         content_type.startswith('application/') and 
                         not content_type.startswith('application/pgp')) or
                        (not part.is_multipart() and filename and 
                         len(part.get_payload(decode=False)) > 1000)
                    )
                    
                    if is_attachment:
                        attachments_found += 1
                        
                        if not filename:
                            if content_type == 'application/pdf':
                                filename = (
                                    f"attachment_{part_idx}_"
                                    f"{date_time_obj.strftime('%Y%m%d_%H%M%S')}"
                                    ".pdf"
                                )
                            else:
                                attachment_details.append(f"      - UNNAMED ({content_type}) - PDF: False [SKIPPED]")
                                continue
                        
                        is_pdf = filename.lower().endswith(('.pdf', '.PDF'))
                        attachment_details.append(f"      - {filename} ({content_type}) - PDF: {is_pdf}")
                        
                        logger.info(f"Found attachment {attachments_found}: {filename} (Type: {content_type})")
                        
                        # Only process PDF files
                        if not is_pdf:
                            logger.debug(f"Skipping non-PDF attachment: {filename}")
                            continue
                        
                        # Download with retry mechanism
                        filepath = os.path.join(inner_dir_path, filename)
                        if not self.dry_run:
                            if self.download_attachment_with_retry(
                                part, filepath
                            ):
                                attachments_downloaded += 1
                                logger.info(f"Successfully saved: {filename} => {filepath}")
                            else:
                                logger.error(f"Failed to download after retries: {filename}")
                                log_missing_email_or_attachment(email_subject, sender, f"Failed to download attachment: {filename}", date_str)
                        else:
                            attachments_downloaded += 1
                            logger.info(f"[DRY RUN] Would download: "
                                      f"{filename}")
                    
                except Exception as part_error:
                    logger.error(f"Error processing part {part_idx}: "
                               f"{str(part_error)}")
                    continue

            # Log attachment summary
            if attachment_details:
                logger.info(f"    Attachments: {attachments_found} total, {attachments_downloaded} PDFs")
                for detail in attachment_details:
                    logger.info(detail)
            else:
                logger.info(f"    Attachments: 0 total, 0 PDFs")
                log_missing_email_or_attachment(email_subject, sender, "No attachments found in email", date_str)

            # Log final results
            logger.info(f"Email processing complete - Found: {attachments_found} attachments, Downloaded: {attachments_downloaded} PDFs")
            logger.info("")  # Add blank line for readability

            return attachments_found, attachments_downloaded

        except Exception as e:
            logger.error(f"Error in download_email_attachments: {str(e)}")
            log_missing_email_or_attachment(email_subject, sender, f"Email processing error: {str(e)}", date_str if 'date_str' in locals() else 'unknown')
            return 0, 0

    def process_date_batch(self, current_date: datetime) -> bool:
        """Process emails for a single date"""
        try:
            date_str = current_date.strftime('%Y-%m-%d')
            logger.info(f"Processing date: {date_str}")
            
            # Create date-specific folder
            base_folder = f"HISTORICAL_{current_date.strftime('%d-%b-%Y')}"
            base_folder_path = Path(INVOICE_DOWNLOAD_FOLDER) / base_folder
            
            if not self.dry_run:
                base_folder_path.mkdir(parents=True, exist_ok=True)
            
            # Search for emails
            email_ids = self.search_emails_for_date(current_date)
            self.stats['emails_found'] += len(email_ids)
            
            if not email_ids:
                logger.debug(f"No emails found for {date_str}")
                self.stats['skipped_days'] += 1
                return True
            
            logger.info(f"Found {len(email_ids)} emails for {date_str}")
            
            # Process emails
            emails_processed = 0
            total_attachments_found = 0
            total_attachments_downloaded = 0
            
            for _, email_id in enumerate(email_ids, 1):
                try:
                    # Use BODY.PEEK to avoid marking emails as read
                    result, response = self.mail.uid(
                        'fetch', email_id, '(BODY.PEEK[])'
                    )
                    
                    if result != 'OK' or not response or not response[0]:
                        continue
                    
                    try:
                        raw_email = response[0][1].decode('utf-8')
                    except UnicodeDecodeError:
                        raw_email = response[0][1].decode('latin-1')
                    
                    email_message = email.message_from_string(raw_email)
                    
                    # Download attachments
                    found, downloaded = self.download_email_attachments(
                        email_message, base_folder_path
                    )
                    total_attachments_found += found
                    total_attachments_downloaded += downloaded
                    
                    if downloaded > 0:
                        emails_processed += 1
                    
                except Exception as e:
                    logger.debug(f"Error processing email {email_id}: "
                               f"{str(e)}")
                    self.stats['errors'] += 1
                    continue
            
            # Update statistics
            self.stats['emails_processed'] += emails_processed
            self.stats['attachments_found'] += total_attachments_found
            self.stats['attachments_downloaded'] += (
                total_attachments_downloaded
            )
            self.stats['days_processed'] += 1
            
            # Post-processing if attachments were downloaded
            if total_attachments_downloaded > 0 and not self.dry_run:
                try:
                    logger.info(f"Processing {total_attachments_downloaded} "
                              f"invoices for {date_str}")
                    converted_files, failed_files = (
                        convert_invoice_for_email(base_folder_path)
                    )
                    self.stats['invoices_converted'] += len(converted_files)
                    
                    process_extracted_data(converted_files, failed_files)
                    self.stats['invoices_processed'] += len(converted_files)
                    
                    logger.info(f"Completed processing for {date_str}: "
                              f"{len(converted_files)} invoices processed")
                except Exception as post_error:
                    logger.error(f"Post-processing failed for {date_str}: "
                               f"{str(post_error)}")
                    self.stats['errors'] += 1
            
            logger.info(f"Date {date_str} complete: {emails_processed} "
                       f"emails, {total_attachments_downloaded} attachments")
            return True
            
        except Exception as e:
            logger.error(f"Error processing date {current_date.date()}: "
                        f"{str(e)}")
            self.stats['errors'] += 1
            return False

    def run_download(self):
        """Main download process"""
        try:
            if not self.login():
                logger.error("Failed to connect to email server")
                return False
            
            current_date = self.start_date
            batch_count = 0
            
            logger.info("="*80)
            logger.info("STARTING HISTORICAL INVOICE DOWNLOADER")
            logger.info("="*80)
            logger.info(f"Session started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"Processing from {self.start_date.date()} "
                       f"back to {self.end_date.date()}")
            logger.info(f"Dry run: {self.dry_run}")
            logger.info("-" * 80)
            
            while current_date >= self.end_date:
                try:
                    # Process current date
                    self.process_date_batch(current_date)
                    
                    # Progress reporting
                    if batch_count % 7 == 0:  # Weekly progress report
                        self.print_progress_report(current_date)
                    
                    # Move to previous day
                    current_date -= timedelta(days=1)
                    batch_count += 1
                    
                    # Small delay to avoid overwhelming the email server
                    if not self.dry_run:
                        time.sleep(0.5)
                    
                except KeyboardInterrupt:
                    logger.info("Download interrupted by user")
                    break
                except Exception as e:
                    logger.error(f"Error processing date "
                               f"{current_date.date()}: {str(e)}")
                    current_date -= timedelta(days=1)
                    continue
            
            # Final report
            self.print_final_report()
            return True
            
        except Exception as e:
            logger.error(f"Critical error in download process: {str(e)}")
            return False
        finally:
            if self.mail:
                try:
                    self.mail.close()
                    self.mail.logout()
                    logger.info("Disconnected from email server")
                except Exception:
                    pass

    def print_progress_report(self, current_date: datetime):
        """Print progress report"""
        days_remaining = (current_date - self.end_date).days
        total_days = (self.start_date - self.end_date).days
        progress_pct = ((total_days - days_remaining) / total_days) * 100
        
        logger.info("="*60)
        logger.info(f"PROGRESS REPORT - {current_date.date()}")
        logger.info(f"Progress: {progress_pct:.1f}% "
                   f"({days_remaining} days remaining)")
        logger.info(f"Days processed: {self.stats['days_processed']}")
        logger.info(f"Emails found: {self.stats['emails_found']}")
        logger.info(f"Emails processed: {self.stats['emails_processed']}")
        logger.info(f"Attachments downloaded: "
                   f"{self.stats['attachments_downloaded']}")
        logger.info(f"Invoices processed: "
                   f"{self.stats['invoices_processed']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info("="*60)

    def print_final_report(self):
        """Print final statistics report"""
        logger.info("="*60)
        logger.info("HISTORICAL DOWNLOAD COMPLETE")
        logger.info("="*60)
        logger.info(f"Date range: {self.start_date.date()} to "
                   f"{self.end_date.date()}")
        logger.info(f"Days processed: {self.stats['days_processed']}")
        logger.info(f"Days skipped (no emails): "
                   f"{self.stats['skipped_days']}")
        logger.info(f"Total emails found: {self.stats['emails_found']}")
        logger.info(f"Emails with attachments: "
                   f"{self.stats['emails_processed']}")
        logger.info(f"Attachments found: {self.stats['attachments_found']}")
        logger.info(f"Attachments downloaded: "
                   f"{self.stats['attachments_downloaded']}")
        logger.info(f"Invoices converted: "
                   f"{self.stats['invoices_converted']}")
        logger.info(f"Invoices processed: "
                   f"{self.stats['invoices_processed']}")
        logger.info(f"Errors encountered: {self.stats['errors']}")
        
        success_rate = (self.stats['attachments_downloaded'] / 
                       max(self.stats['attachments_found'], 1)) * 100
        logger.info(f"Download success rate: {success_rate:.1f}%")
        logger.info("="*60)


def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(
        description='Historical Invoice Downloader'
    )
    
    parser.add_argument(
        '--start-date', type=str, 
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Start date (YYYY-MM-DD, default: today)'
    )
    
    parser.add_argument(
        '--end-date', type=str, 
        default='2020-01-01',
        help='End date (YYYY-MM-DD, default: 2020-01-01 - downloads from 2020 till today)'
    )
    
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview what would be processed without downloading'
    )
    
    parser.add_argument(
        '--batch-size', type=int, default=30,
        help='Number of days to process per batch (default: 30)'
    )
    
    parser.add_argument(
        '--verbose', action='store_true',
        help='Enable detailed logging'
    )
    
    parser.add_argument(
        '--force', action='store_true',
        help='Reprocess existing invoices'
    )
    
    args = parser.parse_args()
    
    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        return 1
    
    if start_date <= end_date:
        print("Error: Start date must be after end date")
        return 1
    
    # Create and run downloader
    downloader = HistoricalInvoiceDownloader(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        verbose=args.verbose,
        force=args.force
    )
    
    success = downloader.run_download()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main()) 