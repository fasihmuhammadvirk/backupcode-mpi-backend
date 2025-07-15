#!/usr/bin/env python3
"""
failed_invoice_recovery.py

A script to recover failed invoices by searching the mailbox for missing attachments.
This script:
1. Fetches failed invoices from the system (status = 'Failed')
2. Searches the mailbox for specific invoice numbers and suppliers
3. Downloads and processes the missing attachments
4. Runs as a background job that can be scheduled daily

USAGE:
  $ python scripts/failed_invoice_recovery.py

RECOMMENDED:
- Schedule this script to run daily using cron or a task scheduler
- The script will only search for invoices that are marked as 'Failed' in the system
- It uses intelligent date-based searching to avoid overwhelming the mailbox

"""
import time
import imaplib
import email
import email.utils
import os
import traceback
import logging
import sys
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
import re

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, 
    SUPPLIERS, TIMEZONE
)
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice_for_email
from mpi_backend.database.controllers.StatementController import StatementController
from mpi_backend.database import SessionLocal

# Create logs directory
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Setup dedicated logger for failed invoice recovery
def setup_recovery_logger():
    """Setup dedicated logger for failed invoice recovery"""
    log_filename = LOGS_DIR / f"failed_invoice_recovery_{datetime.now().strftime('%Y%m%d')}.log"
    
    # Create logger
    recovery_logger = logging.getLogger('failed_invoice_recovery')
    recovery_logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    recovery_logger.handlers.clear()
    
    # Create file handler
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(logging.INFO)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    recovery_logger.addHandler(file_handler)
    recovery_logger.addHandler(console_handler)
    
    return recovery_logger

logger = setup_recovery_logger()

# Setup recovery tracking
def log_recovery_attempt(invoice_number: str, supplier_name: str, search_date: str, result: str, details: str = ""):
    """Log recovery attempts to a separate file"""
    recovery_log_file = LOGS_DIR / f"failed_invoice_recovery_{datetime.now().strftime('%Y%m%d')}.txt"
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] RECOVERY ATTEMPT: {result}\n"
    log_entry += f"  Invoice: {invoice_number}\n"
    log_entry += f"  Supplier: {supplier_name}\n"
    log_entry += f"  Search Date: {search_date}\n"
    if details:
        log_entry += f"  Details: {details}\n"
    log_entry += "-" * 80 + "\n"
    
    with open(recovery_log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)

# Email sender mapping for suppliers
SUPPLIER_EMAIL_MAPPING = {
    'BMW Plumbing Supplies': ['bmwpsupply@gmail.com'],
    'World Wide Plumbing': ['info@wwps.co', 'Info@wwps.co'],
    'Y & S Plumbing Supply': ['billing@ysplumbing.com'],
    'Supreme Plumbing Supply': ['accounting@supremeplumbingnj.com', 'orders@supremeplumbingnj.com'],
    'Pyramid Plumbing': ['billing@pyramidps.com', 'purchasing@pyramidps.com'],
    'ABC Opus Services': ['ar@opusoperations.com', 'AR@opusoperations.com'],
    'Park Plumbing Supply': ['breindy@parkplumbingsupply.com'],
    'Gotham Plumbing Supply': ['billing@gothamsupply.com'],
    'FW Webb Plumbing Supply': ['billing@fwwebb.com'],
    'Flow Mark Plumbing Supply': ['billing@flowmarksupply.com', 'mendy@flowmarksupply.com'],
    'AF Supply': ['billing@afsupply.com'],
    'Lion Hvac Supplies': ['billing@lionhvac.com']
}

def get_supplier_emails(supplier_name: str) -> List[str]:
    """Get email addresses for a supplier"""
    return SUPPLIER_EMAIL_MAPPING.get(supplier_name, [])

def login():
    """Establish IMAP connection with error handling"""
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(SMTP_SERVER)
        mail.login(LOGIN_EMAIL, LOGIN_PWD)
        mail.select('inbox')
        logger.info("Successfully connected to mailbox for failed invoice recovery")
        return mail
    except imaplib.IMAP4.error as imap_error:
        logger.error(f"IMAP connection failed: {str(imap_error)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login: {str(e)}")
        if mail:
            mail.logout()
        raise

def search_emails_for_invoice(mail, invoice_number: str, supplier_name: str, invoice_date: Optional[date] = None) -> List[str]:
    """
    Search for emails containing specific invoice number and supplier
    
    Args:
        mail: IMAP connection
        invoice_number: The invoice number to search for
        supplier_name: The supplier name
        invoice_date: The invoice date (optional, for date-based searching)
    
    Returns:
        List of email UIDs that match the criteria
    """
    try:
        # Build search criteria
        search_criteria = []
        
        # Add date-based search if invoice_date is provided
        if invoice_date:
            # Search within a reasonable range (1 month before and after)
            start_date = (invoice_date - timedelta(days=30)).strftime('%d-%b-%Y')
            end_date = (invoice_date + timedelta(days=30)).strftime('%d-%b-%Y')
            search_criteria.append(f'SINCE "{start_date}" BEFORE "{end_date}"')
            logger.info(f"Searching emails from {start_date} to {end_date} for invoice {invoice_number}")
        else:
            # If no date, search last 2 years
            start_date = (datetime.now(TIMEZONE) - timedelta(days=730)).strftime('%d-%b-%Y')
            end_date = datetime.now(TIMEZONE).strftime('%d-%b-%Y')
            search_criteria.append(f'SINCE "{start_date}" BEFORE "{end_date}"')
            logger.info(f"Searching emails from {start_date} to {end_date} for invoice {invoice_number} (no specific date)")
        
        # Add subject search for invoice number
        search_criteria.append(f'SUBJECT "{invoice_number}"')
        
        # Combine search criteria
        search_string = f'({" ".join(search_criteria)})'
        
        logger.info(f"Searching with criteria: {search_string}")
        result, data = mail.uid('search', None, search_string)
        
        if result != 'OK':
            logger.error(f"Email search failed: {result}")
            return []
        
        raw_email_ids = data[0].split()
        logger.info(f"Found {len(raw_email_ids)} emails with invoice number {invoice_number}")
        
        # Filter by supplier email addresses
        supplier_emails = get_supplier_emails(supplier_name)
        filtered_email_ids = []
        
        for idx, email_id in enumerate(raw_email_ids, 1):
            try:
                email_id = email_id.decode('utf-8') if isinstance(email_id, bytes) else email_id
                logger.debug(f"Processing email {idx}/{len(raw_email_ids)} - UID: {email_id}")
                
                result, msg_data = mail.uid('fetch', email_id, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')
                
                if result != 'OK':
                    logger.warning(f"Failed to fetch headers for UID {email_id}: {result}")
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                from_email = email.utils.parseaddr(msg.get('From', ''))[1]
                subject = msg.get('Subject', '')
                
                # Check if email is from the correct supplier
                if supplier_emails and from_email in supplier_emails:
                    filtered_email_ids.append(email_id)
                    logger.info(f"Found matching email UID {email_id} from {from_email} with subject: {subject}")
                elif not supplier_emails:
                    # If no specific emails for supplier, accept any email with invoice number
                    filtered_email_ids.append(email_id)
                    logger.info(f"Found email UID {email_id} from {from_email} with subject: {subject} (no supplier email mapping)")
                
            except Exception as e:
                logger.error(f"Error processing email UID {email_id}: {str(e)}")
                continue
        
        logger.info(f"Found {len(filtered_email_ids)} emails matching invoice {invoice_number} and supplier {supplier_name}")
        return filtered_email_ids
        
    except Exception as e:
        logger.error(f"Error in search_emails_for_invoice: {str(e)}\n{traceback.format_exc()}")
        return []

def get_supplier_from_email(email_subject: str, supplier_email: str) -> str:
    """Get supplier name from email subject and sender"""
    try:
        subject = (email_subject or "").lower()
        supplier_email = (supplier_email or "").lower()
        
        if "statement" in subject:
            return "no_supplier"
        if "bmw" in subject:
            return SUPPLIERS[0]
        elif "world wide" in subject:
            return SUPPLIERS[1]
        elif "y&s" in subject:
            return SUPPLIERS[2]
        elif "invoice # i-" in subject or "supreme plumbing" in subject:
            return SUPPLIERS[3]
        elif "pyramid plumbing invoice" in subject:
            return SUPPLIERS[4]
        elif "abc opus services" in subject:
            return SUPPLIERS[5]
        elif "park plumbing & heating supply - invoices overnight" in subject:
            return SUPPLIERS[6]
        elif "webb payment receipt" in subject:
            return SUPPLIERS[8]
        elif "see invoice i-" in subject:
            return SUPPLIERS[9]
        else:
            logger.warning(f"Unknown supplier for subject: {email_subject}")
            return "unknown_supplier"
    except Exception as e:
        logger.error(f"Supplier detection failed: {str(e)}")
        return "unknown_supplier"

def download_attachment_with_retry(part, filepath, max_retries=3):
    """Download attachment with retry mechanism"""
    for attempt in range(max_retries):
        try:
            attachment_data = part.get_payload(decode=True)
            if attachment_data:
                with open(filepath, 'wb') as f:
                    f.write(attachment_data)
                logger.info(f"Downloaded attachment on attempt {attempt + 1}: {os.path.basename(filepath)}")
                return True
            else:
                logger.warning(f"Attempt {attempt + 1}: No attachment data found")
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed to download {os.path.basename(filepath)}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                logger.error(f"All {max_retries} attempts failed for {os.path.basename(filepath)}")
    return False

def download_email_attachments(email_message, base_folder_path, target_invoice_number: str):
    """Download attachments for a specific invoice"""
    
    attachments_found = 0
    attachments_downloaded = 0
    supplier_name = "unknown"
    
    # Extract email details for logging
    email_subject = email_message.get('Subject', 'No Subject')
    sender = email.utils.parseaddr(email_message.get('From', ''))[1]
    date_header = email_message.get('Date', '')
    
    try:
        # Enhanced supplier detection with fallback
        try:
            logger.info(f"Processing email with Subject: '{email_subject}'")
            supplier_name = get_supplier_from_email(
                email_subject,
                email_message.get('Return-Path', '')
            )
            logger.info(f"Detected supplier: {supplier_name}")
        except Exception as sup_error:
            logger.error(f"Supplier detection failed: {str(sup_error)}")
            supplier_name = "unknown_supplier"

        # Date handling with comprehensive fallback
        if not date_header:
            logger.warning("No Date header in email, using current time")
            date_time_obj = datetime.now(TIMEZONE)
        else:
            try:
                date_time_obj = parsedate_to_datetime(date_header).astimezone(TIMEZONE)
            except Exception as date_error:
                logger.error(f"Date parsing failed: {str(date_error)}, using current time")
                date_time_obj = datetime.now(TIMEZONE)

        date_str = date_time_obj.strftime('%Y-%m-%d')
        
        # Log detailed email information
        logger.info(f"  {date_str} | {sender}")
        logger.info(f"    Subject: {email_subject}")
        logger.info(f"    Supplier: {supplier_name} | Target Invoice: {target_invoice_number}")

        # Enhanced directory structure creation
        try:
            inner_dir = f'{date_time_obj.month}-{date_time_obj.day}-{date_time_obj.year}'
            supplier_path = os.path.join(base_folder_path, supplier_name)
            Path(supplier_path).mkdir(parents=True, exist_ok=True)
            inner_dir_path = os.path.join(supplier_path, inner_dir)
            Path(inner_dir_path).mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory structure: {inner_dir_path}")
        except OSError as dir_error:
            logger.error(f"Directory creation failed: {str(dir_error)}")
            return False

        # Enhanced attachment detection logic
        attachment_details = []
        for part_idx, part in enumerate(email_message.walk(), 1):
            try:
                # Check multiple conditions for attachments
                content_disposition = part.get('Content-Disposition', '')
                content_type = part.get_content_type()
                filename = part.get_filename()
                
                logger.debug(f"Part {part_idx}: Content-Type={content_type}, Content-Disposition={content_disposition}, Filename={filename}")
                
                # Enhanced attachment detection conditions
                is_attachment = (
                    # Standard attachment detection
                    (content_disposition and 'attachment' in content_disposition.lower()) or
                    # Inline attachments
                    (content_disposition and 'inline' in content_disposition.lower() and filename) or
                    # PDF files regardless of disposition
                    (content_type == 'application/pdf') or
                    # Files with PDF extension
                    (filename and filename.lower().endswith(('.pdf', '.PDF'))) or
                    # Binary content with filename
                    (filename and content_type.startswith('application/') and not content_type.startswith('application/pgp')) or
                    # Special case for multipart/mixed with binary payload
                    (not part.is_multipart() and filename and len(part.get_payload(decode=False)) > 1000)
                )
                
                if is_attachment:
                    attachments_found += 1
                    
                    if not filename:
                        # Generate filename for unnamed attachments
                        if content_type == 'application/pdf':
                            filename = f"recovery_{target_invoice_number}_{part_idx}_{date_time_obj.strftime('%Y%m%d_%H%M%S')}.pdf"
                        else:
                            logger.warning(f"Attachment {part_idx} has no filename and unknown type: {content_type}")
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
                    if download_attachment_with_retry(part, filepath):
                        attachments_downloaded += 1
                        logger.info(f"Successfully saved: {filename} => {filepath}")
                    else:
                        logger.error(f"Failed to download after retries: {filename}")
                
            except Exception as part_error:
                logger.error(f"Error processing part {part_idx}: {str(part_error)}")
                continue

        # Log attachment summary
        if attachment_details:
            logger.info(f"    Attachments: {attachments_found} total, {attachments_downloaded} PDFs")
            for detail in attachment_details:
                logger.info(detail)
        else:
            logger.info(f"    Attachments: 0 total, 0 PDFs")

        # Log final results
        logger.info(f"Email processing complete - Found: {attachments_found} attachments, Downloaded: {attachments_downloaded} PDFs")
        logger.info("")  # Add blank line for readability
        
        # Return success status
        return attachments_downloaded > 0

    except Exception as e:
        logger.error(f"Error in download_email_attachments: {str(e)}\n{traceback.format_exc()}")
        return False

def get_failed_invoices(from_date: Optional[date] = None, to_date: Optional[date] = None, limit: int = 50) -> List[Dict]:
    """
    Get failed invoices from the system
    
    Args:
        from_date: Start date filter (optional)
        to_date: End date filter (optional)
        limit: Maximum number of invoices to process
    
    Returns:
        List of failed invoice dictionaries
    """
    try:
        db = SessionLocal()
        controller = StatementController(db)
        
        # Get failed invoices using the existing API
        result = controller.get_statement_invoice_data(
            from_date=from_date,
            to_date=to_date,
            status='failed',
            page=1,
            page_size=limit
        )
        
        if not result['success']:
            logger.error(f"Failed to get failed invoices: {result.get('error', 'Unknown error')}")
            db.close()
            return []
        
        failed_invoices = []
        for invoice in result['data']:
            if invoice['status'] == 'Failed':
                failed_invoices.append({
                    'invoice_number': invoice['invoice_number'],
                    'invoice_date': invoice['invoice_date'],
                    'supplier_name': invoice['supplier_name'],
                    'original_amount': invoice['original_amount'],
                    'customer_po': invoice['customer_po'],
                    'statement_date': invoice['statement_date']
                })
        
        db.close()
        logger.info(f"Found {len(failed_invoices)} failed invoices to process")
        return failed_invoices
        
    except Exception as e:
        logger.error(f"Error getting failed invoices: {str(e)}\n{traceback.format_exc()}")
        if 'db' in locals():
            db.close()
        return []

def process_failed_invoice_recovery():
    """Main function to process failed invoice recovery"""
    logger.info("="*80)
    logger.info("STARTING FAILED INVOICE RECOVERY")
    logger.info("="*80)
    logger.info(f"Session started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    mail = None
    db = None
    
    try:
        # Setup directory structure
        try:
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = f"recovery_{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - {datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}"
            base_folder_path = Path(INVOICE_DOWNLOAD_FOLDER) / base_folder
            base_folder_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created recovery directory: {base_folder_path}")
        except Exception as dir_error:
            logger.error(f"Directory creation failed: {str(dir_error)}")
            raise

        # Get failed invoices from last 2 years (to avoid processing very old invoices)
        try:
            from_date = datetime.now(TIMEZONE).date() - timedelta(days=730)  # 2 years back
            failed_invoices = get_failed_invoices(from_date=from_date, limit=100)
            
            if not failed_invoices:
                logger.info("No failed invoices found to process")
                logger.info("="*80)
                return
            
            logger.info(f"Processing {len(failed_invoices)} failed invoices")
            logger.info("-" * 80)
            
        except Exception as invoice_error:
            logger.error(f"Failed to get failed invoices: {str(invoice_error)}")
            raise

        # Email processing
        try:
            mail = login()
            successfully_processed_invoices = []
            
            for idx, invoice in enumerate(failed_invoices, 1):
                try:
                    invoice_number = invoice['invoice_number']
                    supplier_name = invoice['supplier_name']
                    invoice_date_str = invoice['invoice_date']
                    
                    # Parse invoice date
                    invoice_date = None
                    if invoice_date_str:
                        try:
                            invoice_date = datetime.fromisoformat(invoice_date_str).date()
                        except:
                            logger.warning(f"Could not parse invoice date: {invoice_date_str}")
                    
                    logger.info(f"Processing failed invoice {idx}/{len(failed_invoices)}: {invoice_number} from {supplier_name}")
                    
                    # Search for emails containing this invoice
                    matching_email_ids = search_emails_for_invoice(mail, invoice_number, supplier_name, invoice_date)
                    
                    if not matching_email_ids:
                        logger.warning(f"No emails found for invoice {invoice_number} from {supplier_name}")
                        log_recovery_attempt(invoice_number, supplier_name, invoice_date_str or "unknown", "NO_EMAILS_FOUND")
                        continue
                    
                    logger.info(f"Found {len(matching_email_ids)} emails for invoice {invoice_number}")
                    
                    # Process each matching email
                    invoice_processed = False
                    for email_idx, e_id in enumerate(matching_email_ids, 1):
                        try:
                            logger.info(f"Processing email {email_idx}/{len(matching_email_ids)} for invoice {invoice_number} - UID: {e_id}")
                            
                            result, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')
                            
                            if result != 'OK' or not response or not response[0]:
                                logger.error(f"Failed to fetch email UID {e_id}")
                                continue
                            
                            try:
                                raw_email = response[0][1].decode('utf-8')
                            except UnicodeDecodeError:
                                raw_email = response[0][1].decode('latin-1')

                            email_message = email.message_from_string(raw_email)
                            
                            # Download attachments for this specific invoice
                            download_success = download_email_attachments(email_message, base_folder_path, invoice_number)
                            
                            if download_success:
                                invoice_processed = True
                                logger.info(f"Successfully processed email UID {e_id} for invoice {invoice_number}")
                                break  # Found and processed the invoice, no need to check other emails
                            else:
                                logger.warning(f"Email UID {e_id} for invoice {invoice_number} had no attachments")
                                
                        except Exception as email_error:
                            logger.error(f"Failed to process email UID {e_id} for invoice {invoice_number}: {str(email_error)}")
                            continue
                    
                    if invoice_processed:
                        successfully_processed_invoices.append(invoice_number)
                        log_recovery_attempt(invoice_number, supplier_name, invoice_date_str or "unknown", "SUCCESS", f"Processed from email UID {e_id}")
                    else:
                        log_recovery_attempt(invoice_number, supplier_name, invoice_date_str or "unknown", "NO_ATTACHMENTS", "No valid attachments found in any matching emails")
                    
                    # Small delay between invoices to avoid overwhelming the server
                    time.sleep(1)
                    
                except Exception as invoice_error:
                    logger.error(f"Failed to process invoice {invoice_number}: {str(invoice_error)}")
                    log_recovery_attempt(invoice_number, supplier_name, invoice_date_str or "unknown", "ERROR", str(invoice_error))
                    continue

            logger.info("-" * 80)
            logger.info(f"Successfully processed {len(successfully_processed_invoices)} invoices out of {len(failed_invoices)}")
            
            if successfully_processed_invoices:
                logger.info("Successfully recovered invoices: " + ", ".join(successfully_processed_invoices))

        except Exception as processing_error:
            logger.error(f"Email processing failed: {str(processing_error)}\n{traceback.format_exc()}")
            raise

        # Post-processing for successfully downloaded files
        try:
            if successfully_processed_invoices:
                logger.info("Starting invoice conversion for recovered files")
                converted_files, failed_files = convert_invoice_for_email(base_folder_path)
                logger.info(f"Conversion complete. Success: {len(converted_files)}, Failed: {len(failed_files)}")

                logger.info("Starting data processing for recovered files")
                process_extracted_data(converted_files, failed_files)
                logger.info("Data processing complete for recovered files")
            else:
                logger.info("No files to convert or process")

        except Exception as post_error:
            logger.error(f"Post-processing failed: {str(post_error)}\n{traceback.format_exc()}")
            raise

    except Exception as main_error:
        logger.error(f"Critical error in failed invoice recovery: {str(main_error)}\n{traceback.format_exc()}")
        raise

    finally:
        try:
            if mail:
                logger.info("Closing IMAP connection")
                mail.close()
                mail.logout()
        except Exception as logout_error:
            logger.error(f"Error closing connection: {str(logout_error)}")
        
        logger.info("="*80)
        logger.info("FAILED INVOICE RECOVERY COMPLETED")
        logger.info("="*80)

def main():
    """Main entry point"""
    try:
        process_failed_invoice_recovery()
    except KeyboardInterrupt:
        logger.info("Failed invoice recovery stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Fatal error in failed invoice recovery: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    main() 