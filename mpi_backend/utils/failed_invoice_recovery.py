#!/usr/bin/env python3
"""
failed_invoice_recovery.py

Enhanced utility for recovering failed invoices by searching the mailbox for missing attachments.
This utility:
1. Fetches ALL failed invoices from the system (status = 'Failed')
2. Processes them in batches to handle large volumes efficiently
3. Searches the mailbox for specific invoice numbers and suppliers
4. Downloads and processes the missing attachments
5. Includes comprehensive logging and error handling
6. Can be run as a background task or standalone

USAGE:
  $ python -m mpi_backend.utils.failed_invoice_recovery

FEATURES:
- Batch processing for large volumes of failed invoices
- Intelligent date-based searching to avoid overwhelming the mailbox
- Comprehensive logging with separate recovery tracking
- Retry mechanism for failed operations
- Background task integration
- Memory-efficient processing

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
from typing import List, Dict, Optional, Tuple, Generator
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from contextlib import contextmanager

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, 
    SUPPLIERS, TIMEZONE
)
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_converter import convert_invoice_for_email
from mpi_backend.database.controllers.StatementController import StatementController
from mpi_backend.database import SessionLocal
from mpi_backend.database import get_db
from mpi_backend.database.models.Invoice import Invoice
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.config.logging_config import get_missing_logger

# Create logs directory
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Use the centralized logging system
logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

# Configuration constants
BATCH_SIZE = 50  # Process failed invoices in batches
MAX_WORKERS = 3  # Number of concurrent workers for email processing
MAX_RETRIES = 3  # Maximum number of retries on failure
RETRY_DELAY_MINUTES = 5  # Delay between retries in minutes
EMAIL_SEARCH_TIMEOUT = 30  # Timeout for email operations in seconds
MAX_EMAILS_PER_INVOICE = 10  # Maximum emails to check per invoice


# Setup recovery tracking
def log_recovery_attempt(invoice_number: str, supplier_name: str, search_date: str, result: str, details: str = ""):
    """Log recovery attempts to the centralized missing log"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"RECOVERY ATTEMPT: {result} | Invoice: {invoice_number} | Supplier: {supplier_name} | Search Date: {search_date}"
    if details:
        log_entry += f" | Details: {details}"
    missing_logger.info(log_entry)

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

def fetch_email_thread(mail, email_id):
    """
    Fetch the full conversation thread for a given email
    
    Args:
        mail: IMAP connection
        email_id: Email UID to fetch thread for
    
    Returns:
        List of email messages in the thread (including the original email)
    """
    try:
        # First, get the original email to extract thread information
        result, response = mail.uid('fetch', email_id, '(BODY.PEEK[HEADER.FIELDS (SUBJECT IN-REPLY-TO REFERENCES MESSAGE-ID)])')
        
        if result != 'OK' or not response or not response[0]:
            logger.warning(f"Failed to fetch headers for email UID {email_id}")
            return []
        
        raw_email = response[0][1]
        msg = email.message_from_bytes(raw_email)
        
        # Extract thread identifiers
        in_reply_to = msg.get('In-Reply-To', '').strip()
        references = msg.get('References', '').strip()
        message_id = msg.get('Message-ID', '').strip()
        
        logger.debug(f"Thread info for UID {email_id}: In-Reply-To={in_reply_to}, References={references}, Message-ID={message_id}")
        
        # If no thread information, return just the original email
        if not in_reply_to and not references:
            logger.debug(f"No thread information found for UID {email_id}, returning original email only")
            return [email_id]
        
        # Build search criteria for thread emails
        search_criteria = []
        
        # Add Message-ID to search criteria
        if message_id:
            # Remove angle brackets if present
            clean_message_id = message_id.strip('<>')
            search_criteria.append(f'HEADER Message-ID "{clean_message_id}"')
        
        # Add In-Reply-To to search criteria
        if in_reply_to:
            # Remove angle brackets if present
            clean_in_reply_to = in_reply_to.strip('<>')
            search_criteria.append(f'HEADER In-Reply-To "{clean_in_reply_to}"')
        
        # Add References to search criteria
        if references:
            # References can contain multiple message IDs, split and search for each
            ref_ids = re.findall(r'<[^>]+>', references)
            for ref_id in ref_ids:
                clean_ref_id = ref_id.strip('<>')
                search_criteria.append(f'HEADER References "{clean_ref_id}"')
        
        # If we have search criteria, search for related emails
        thread_email_ids = [email_id]  # Always include the original email
        
        if search_criteria:
            # Search for emails matching any of the criteria
            search_string = f'({" ".join(search_criteria)})'
            logger.debug(f"Searching for thread emails with criteria: {search_string}")
            
            result, data = mail.uid('search', None, search_string)
            
            if result == 'OK' and data[0]:
                found_ids = data[0].split()
                for found_id in found_ids:
                    found_id = found_id.decode('utf-8') if isinstance(found_id, bytes) else found_id
                    if found_id != email_id and found_id not in thread_email_ids:
                        thread_email_ids.append(found_id)
                        logger.debug(f"Found thread email UID: {found_id}")
        
        logger.info(f"Thread for UID {email_id} contains {len(thread_email_ids)} emails")
        return thread_email_ids
        
    except Exception as e:
        logger.error(f"Error fetching email thread for UID {email_id}: {str(e)}")
        return [email_id]  # Return original email only on error

def download_invoice_attachments_from_thread(mail, thread_email_ids, base_folder_path, target_invoice_number: str):
    """
    Download invoice attachments from all emails in a thread
    
    Args:
        mail: IMAP connection
        thread_email_ids: List of email UIDs in the thread
        base_folder_path: Base folder for downloads
        target_invoice_number: The invoice number being recovered
    
    Returns:
        Tuple of (total_attachments_found, total_attachments_downloaded)
    """
    total_attachments_found = 0
    total_attachments_downloaded = 0
    
    logger.info(f"Processing thread with {len(thread_email_ids)} emails for invoice {target_invoice_number}")
    
    for thread_idx, thread_email_id in enumerate(thread_email_ids, 1):
        try:
            logger.debug(f"Processing thread email {thread_idx}/{len(thread_email_ids)} - UID: {thread_email_id}")
            
            # Fetch the full email
            result, response = mail.uid('fetch', thread_email_id, '(BODY.PEEK[])')
            
            if result != 'OK' or not response or not response[0]:
                logger.warning(f"Failed to fetch thread email UID {thread_email_id}")
                continue
            
            try:
                raw_email = response[0][1].decode('utf-8')
            except UnicodeDecodeError:
                raw_email = response[0][1].decode('latin-1')
            
            email_message = email.message_from_string(raw_email)
            
            # Process attachments from this thread email
            found, downloaded = download_email_attachments(email_message, base_folder_path, target_invoice_number)
            total_attachments_found += found
            total_attachments_downloaded += downloaded
            
            if downloaded > 0:
                logger.info(f"Downloaded {downloaded} attachments from thread email UID {thread_email_id}")
            
        except Exception as e:
            logger.error(f"Error processing thread email UID {thread_email_id}: {str(e)}")
            continue
    
    logger.info(f"Thread processing complete: {total_attachments_found} attachments found, {total_attachments_downloaded} downloaded")
    return total_attachments_found, total_attachments_downloaded

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
            logger.debug(f"Searching emails from {start_date} to {end_date} for invoice {invoice_number}")
        else:
            # If no date, search last 2 years
            start_date = (datetime.now(TIMEZONE) - timedelta(days=730)).strftime('%d-%b-%Y')
            end_date = datetime.now(TIMEZONE).strftime('%d-%b-%Y')
            search_criteria.append(f'SINCE "{start_date}" BEFORE "{end_date}"')
            logger.debug(f"Searching emails from {start_date} to {end_date} for invoice {invoice_number} (no specific date)")
        
        # Add subject search for invoice number
        search_criteria.append(f'SUBJECT "{invoice_number}"')
        
        # Combine search criteria
        search_string = f'({" ".join(search_criteria)})'
        
        logger.debug(f"Searching with criteria: {search_string}")
        result, data = mail.uid('search', None, search_string)
        
        if result != 'OK':
            logger.error(f"Email search failed: {result}")
            return []
        
        raw_email_ids = data[0].split()
        logger.debug(f"Found {len(raw_email_ids)} emails with invoice number {invoice_number}")
        
        # Filter by supplier email addresses
        supplier_emails = get_supplier_emails(supplier_name)
        filtered_email_ids = []
        
        for idx, email_id in enumerate(raw_email_ids[:MAX_EMAILS_PER_INVOICE], 1):
            try:
                email_id = email_id.decode('utf-8') if isinstance(email_id, bytes) else email_id
                logger.debug(f"Processing email {idx}/{min(len(raw_email_ids), MAX_EMAILS_PER_INVOICE)} - UID: {email_id}")
                
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
                    logger.debug(f"Found matching email UID {email_id} from {from_email} with subject: {subject}")
                elif not supplier_emails:
                    # If no specific emails for supplier, accept any email with invoice number
                    filtered_email_ids.append(email_id)
                    logger.debug(f"Found email UID {email_id} from {from_email} with subject: {subject} (no supplier email mapping)")
                
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
                logger.debug(f"Downloaded attachment on attempt {attempt + 1}: {os.path.basename(filepath)}")
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
            logger.debug(f"Processing email with Subject: '{email_subject}'")
            supplier_name = get_supplier_from_email(
                email_subject,
                email_message.get('Return-Path', '')
            )
            logger.debug(f"Detected supplier: {supplier_name}")
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
        logger.debug(f"  {date_str} | {sender}")
        logger.debug(f"    Subject: {email_subject}")
        logger.debug(f"    Supplier: {supplier_name} | Target Invoice: {target_invoice_number}")

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
                    
                    logger.debug(f"Found attachment {attachments_found}: {filename} (Type: {content_type})")
                    
                    # Only process PDF files
                    if not is_pdf:
                        logger.debug(f"Skipping non-PDF attachment: {filename}")
                        continue
                    
                    # Download with retry mechanism
                    filepath = os.path.join(inner_dir_path, filename)
                    if download_attachment_with_retry(part, filepath):
                        attachments_downloaded += 1
                        logger.debug(f"Successfully saved: {filename} => {filepath}")
                    else:
                        logger.error(f"Failed to download after retries: {filename}")
                
            except Exception as part_error:
                logger.error(f"Error processing part {part_idx}: {str(part_error)}")
                continue

        # Log attachment summary
        if attachment_details:
            logger.debug(f"    Attachments: {attachments_found} total, {attachments_downloaded} PDFs")
            for detail in attachment_details:
                logger.debug(detail)
        else:
            logger.debug(f"    Attachments: 0 total, 0 PDFs")

        # Log final results
        logger.debug(f"Email processing complete - Found: {attachments_found} attachments, Downloaded: {attachments_downloaded} PDFs")
        
        # Return success status
        return attachments_downloaded > 0

    except Exception as e:
        logger.error(f"Error in download_email_attachments: {str(e)}\n{traceback.format_exc()}")
        return False

def get_failed_invoices_batch(from_date: Optional[date] = None, to_date: Optional[date] = None, 
                             page: int = 1, page_size: int = BATCH_SIZE) -> Tuple[List[Dict], int]:
    """
    Get failed invoices from the system in batches
    
    Args:
        from_date: Start date filter (optional)
        to_date: End date filter (optional)
        page: Page number for pagination
        page_size: Number of invoices per page
    
    Returns:
        Tuple of (failed_invoices_list, total_count)
    """
    try:
        db = SessionLocal()
        controller = StatementController(db)
        
        # Get failed invoices using the existing API
        result = controller.get_statement_invoice_data(
            from_date=from_date,
            to_date=to_date,
            status='failed',
            page=page,
            page_size=page_size
        )
        
        if not result['success']:
            logger.error(f"Failed to get failed invoices: {result.get('error', 'Unknown error')}")
            db.close()
            return [], 0
        
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
        
        total_count = result.get('total', 0)
        db.close()
        logger.info(f"Retrieved batch {page}: {len(failed_invoices)} failed invoices (Total: {total_count})")
        return failed_invoices, total_count
        
    except Exception as e:
        logger.error(f"Error getting failed invoices batch: {str(e)}\n{traceback.format_exc()}")
        if 'db' in locals():
            db.close()
        return [], 0

def get_all_failed_invoices(from_date: Optional[date] = None, to_date: Optional[date] = None) -> Generator[List[Dict], None, None]:
    """
    Generator to get all failed invoices in batches
    
    Args:
        from_date: Start date filter (optional)
        to_date: End date filter (optional)
    
    Yields:
        Batches of failed invoice dictionaries
    """
    page = 1
    total_processed = 0
    
    while True:
        batch, total_count = get_failed_invoices_batch(from_date, to_date, page, BATCH_SIZE)
        
        if not batch:
            break
            
        total_processed += len(batch)
        logger.info(f"Processing batch {page}: {len(batch)} invoices (Total processed: {total_processed}/{total_count})")
        
        yield batch
        
        if total_processed >= total_count:
            break
            
        page += 1

def process_invoice_batch(batch: List[Dict], mail, base_folder_path: Path) -> List[str]:
    """
    Process a batch of failed invoices
    
    Args:
        batch: List of failed invoice dictionaries
        mail: IMAP connection
        base_folder_path: Base folder for downloads
    
    Returns:
        List of successfully processed invoice numbers
    """
    successfully_processed_invoices = []
    
    for idx, invoice in enumerate(batch, 1):
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
            
            logger.info(f"Processing failed invoice {idx}/{len(batch)}: {invoice_number} from {supplier_name}")
            
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
                    logger.debug(f"Processing email {email_idx}/{len(matching_email_ids)} for invoice {invoice_number} - UID: {e_id}")
                    
                    # First, check if this email has invoice keywords in subject
                    result, response = mail.uid('fetch', e_id, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
                    
                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"Failed to fetch subject for email UID {e_id}")
                        continue
                    
                    raw_email = response[0][1]
                    msg = email.message_from_bytes(raw_email)
                    subject = (msg.get('Subject', '') or '').lower()
                    
                    # Check for invoice keywords
                    has_invoice_keyword = any(kw in subject
                                            for kw in ['invoice', 'invoices', 'invoice(s)'])
                    
                    if has_invoice_keyword:
                        logger.info(f"Email UID {e_id} contains invoice keywords, processing thread for invoice {invoice_number}")
                        
                        # Fetch the full conversation thread
                        thread_email_ids = fetch_email_thread(mail, e_id)
                        
                        if len(thread_email_ids) > 1:
                            logger.info(f"Found thread with {len(thread_email_ids)} emails for UID {e_id}")
                            # Process the entire thread for attachments
                            thread_found, thread_downloaded = download_invoice_attachments_from_thread(
                                mail, thread_email_ids, base_folder_path, invoice_number
                            )
                            
                            if thread_downloaded > 0:
                                invoice_processed = True
                                logger.info(f"Successfully processed thread for email UID {e_id} with {thread_downloaded} attachments")
                                break  # Found and processed the invoice, no need to check other emails
                            else:
                                logger.warning(f"Thread for email UID {e_id} had no attachments")
                        else:
                            logger.info(f"Email UID {e_id} has no thread, processing as single email")
                            # Process as single email (existing logic)
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
                    else:
                        logger.info(f"Email UID {e_id} does not contain invoice keywords, processing as single email")
                        # Process as single email (existing logic)
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
            time.sleep(0.5)
            
        except Exception as invoice_error:
            logger.error(f"Failed to process invoice {invoice_number}: {str(invoice_error)}")
            log_recovery_attempt(invoice_number, supplier_name, invoice_date_str or "unknown", "ERROR", str(invoice_error))
            continue
    
    return successfully_processed_invoices

def process_failed_invoice_recovery():
    """Main function to process failed invoice recovery with enhanced batch processing"""
    logger.info("="*80)
    logger.info("STARTING ENHANCED FAILED INVOICE RECOVERY")
    logger.info("="*80)
    logger.info(f"Session started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    mail = None
    all_successfully_processed_invoices = []
    
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
            total_batches = 0
            total_invoices = 0
            
            # Process all failed invoices in batches
            for batch in get_all_failed_invoices(from_date=from_date):
                total_batches += 1
                total_invoices += len(batch)
                
                if not batch:
                    logger.info("No failed invoices found to process")
                    break
                
                logger.info(f"Processing batch {total_batches}: {len(batch)} failed invoices")
                logger.info("-" * 80)
                
                # Email processing for this batch
                try:
                    if mail is None:
                        mail = login()
                    
                    batch_successful = process_invoice_batch(batch, mail, base_folder_path)
                    all_successfully_processed_invoices.extend(batch_successful)
                    
                    logger.info(f"Batch {total_batches} completed: {len(batch_successful)}/{len(batch)} invoices recovered")
                    logger.info("-" * 80)
                    
                except Exception as batch_error:
                    logger.error(f"Failed to process batch {total_batches}: {str(batch_error)}")
                    # Try to reconnect for next batch
                    try:
                        if mail:
                            mail.close()
                            mail.logout()
                    except:
                        pass
                    mail = None
                    continue
            
            logger.info(f"Completed processing all batches: {total_batches} batches, {total_invoices} total invoices")
            
        except Exception as invoice_error:
            logger.error(f"Failed to get failed invoices: {str(invoice_error)}")
            raise

        # Post-processing for successfully downloaded files
        try:
            if all_successfully_processed_invoices:
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
        logger.info(f"ENHANCED FAILED INVOICE RECOVERY COMPLETED")
        logger.info(f"Total invoices processed: {total_invoices}")
        logger.info(f"Successfully recovered: {len(all_successfully_processed_invoices)}")
        logger.info("="*80)

def failed_invoice_recovery_background_task():
    """Background task wrapper for failed invoice recovery"""
    try:
        logger.info("Starting failed invoice recovery background task")
        process_failed_invoice_recovery()
        logger.info("Failed invoice recovery background task completed successfully")
    except Exception as e:
        logger.error(f"Failed invoice recovery background task failed: {str(e)}", exc_info=True)

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