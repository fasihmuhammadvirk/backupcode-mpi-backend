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

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, 
    SUPPLIERS, TIMEZONE
)
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice_for_email

logger = logging.getLogger(__name__)



EXCLUDED_SENDERS = [  # suppliers marked as read after download
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


def login():
    """Establish IMAP connection with error handling"""
    try:
        mail = imaplib.IMAP4_SSL(SMTP_SERVER)
        mail.login(LOGIN_EMAIL, LOGIN_PWD)
        mail.select('inbox')
        logger.info("Successfully connected to mailbox for missing invoices")
        return mail
    except Exception as e:
        logger.error(f"IMAP connection failed: {str(e)}")
        raise


def search_previous_week_emails(mail):
    """Search for emails from the last 7 days"""
    try:
        # Search for emails from 7 days ago to yesterday
        start_date = (datetime.now(TIMEZONE) - timedelta(days=7)).strftime('%d-%b-%Y')
        end_date = datetime.now(TIMEZONE).strftime('%d-%b-%Y')
        
        logger.info(f"Searching for emails from last 7 days: {start_date} to {end_date}")
        search_criteria = f'(SINCE "{start_date}" BEFORE "{end_date}")'
        result, data = mail.uid('search', None, search_criteria)

        if result != 'OK':
            logger.error(f"Email search failed: {result}")
            return []

        raw_email_ids = data[0].split()
        logger.info(f"Found {len(raw_email_ids)} emails in previous week")

        filtered_email_ids = []
        for idx, email_id in enumerate(raw_email_ids, 1):
            try:
                email_id = email_id.decode('utf-8') if isinstance(email_id, bytes) else email_id
                logger.debug(f"Processing email {idx}/{len(raw_email_ids)} - UID: {email_id}")

                result, msg_data = mail.uid('fetch', email_id, '(BODY.PEEK[HEADER.FIELDS (FROM)])')

                if result != 'OK':
                    logger.warning(f"Failed to fetch headers for UID {email_id}: {result}")
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                from_email = email.utils.parseaddr(msg.get('From', ''))[1]

                if from_email in EXCLUDED_SENDERS:
                    filtered_email_ids.append(email_id)
                    logger.debug(f"Email UID {email_id} from excluded sender: {from_email}")
                else:
                    logger.debug(f"Email UID {email_id} from non-excluded sender: {from_email}")

            except Exception as e:
                logger.error(f"Error processing email UID {email_id}: {str(e)}\n{traceback.format_exc()}")
                continue

        logger.info(f"Found {len(filtered_email_ids)} emails from excluded senders in last 7 days")
        return filtered_email_ids

    except Exception as e:
        logger.error(f"Error in search_previous_week_emails: {str(e)}\n{traceback.format_exc()}")
        return []


def get_supplier(email_subject, supplier_email) -> str:
    """Get supplier name with error handling"""
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
            return "unknown_supplier"  # Changed to continue processing
    except Exception as e:
        logger.error(f"Supplier detection failed: {str(e)}\n{traceback.format_exc()}")
        return "unknown_supplier"  # Changed to continue processing


def download_attachment_with_retry(part, filepath, max_retries=3):
    """Download attachment with retry mechanism"""
    for attempt in range(max_retries):
        try:
            attachment_data = part.get_payload(decode=True)
            if attachment_data:
                with open(filepath, 'wb') as f:
                    f.write(attachment_data)
                logger.info(
                    f"Downloaded attachment on attempt {attempt + 1}: "
                    f"{os.path.basename(filepath)}"
                )
                return True
            else:
                logger.warning(f"Attempt {attempt + 1}: No attachment data found")
        except Exception as e:
            logger.error(
                f"Attempt {attempt + 1} failed to download "
                f"{os.path.basename(filepath)}: {str(e)}"
            )
            if attempt < max_retries - 1:
                time.sleep(1)  # Wait 1 second before retry
            else:
                logger.error(
                    f"All {max_retries} attempts failed for "
                    f"{os.path.basename(filepath)}"
                )
    return False


def download_email_attachments(email_message, base_folder_path):
    """Download attachments with comprehensive error handling and retry mechanism"""
    
    attachments_found = 0
    attachments_downloaded = 0
    supplier_name = "unknown"
    
    try:
        # Enhanced supplier detection with fallback
        try:
            logger.info(f"Processing email with Subject: '{email_message.get('Subject', 'No Subject')}'")
            supplier_name = get_supplier(
                email_message.get('Subject', ''),
                email_message.get('Return-Path', '')
            )
            logger.info(f"Detected supplier: {supplier_name}")
        except Exception as sup_error:
            logger.error(f"Supplier detection failed: {str(sup_error)}")
            supplier_name = "unknown_supplier"

        # Date handling with comprehensive fallback
        date_header = email_message.get('Date', '')
        if not date_header:
            logger.warning("No Date header in email, using current time")
            date_time_obj = datetime.now(TIMEZONE)
        else:
            try:
                date_time_obj = parsedate_to_datetime(date_header).astimezone(TIMEZONE)
            except Exception as date_error:
                logger.error(f"Date parsing failed: {str(date_error)}, using current time")
                date_time_obj = datetime.now(TIMEZONE)

        # Enhanced directory structure creation with fallback
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
                logger.error(f"Fallback directory creation also failed: {str(fallback_error)}, continuing without this email")
                return attachments_downloaded > 0  # Return current progress rather than False

        # CRITICAL FIX: Enhanced attachment detection logic
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
                            filename = f"attachment_{part_idx}_{date_time_obj.strftime('%Y%m%d_%H%M%S')}.pdf"
                        else:
                            logger.warning(f"Attachment {part_idx} has no filename and unknown type: {content_type}")
                            continue
                    
                    logger.info(f"Found attachment {attachments_found}: {filename} (Type: {content_type})")
                    
                    # Only process PDF files
                    if not filename.lower().endswith(('.pdf', '.PDF')):
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
                logger.error(f"Error processing part {part_idx}: {str(part_error)}\n{traceback.format_exc()}")
                continue

        # Log final results
        logger.info(f"Email processing complete - Found: {attachments_found} attachments, Downloaded: {attachments_downloaded} PDFs")
        
        # Return success status
        return attachments_downloaded > 0

    except Exception as e:
        logger.error(f"Error in download_email_attachments: {str(e)}\n{traceback.format_exc()}")
        return False


def missing_email_download_background_task():
    """Daily missing invoice download task - downloads last 7 days, NO EMAIL MARKING"""
    logger.debug("Starting daily missing invoice download task")
    
    mail = None
    try:
        # Setup directory structure
        try:
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = f"MISSING_{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - {datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}"
            base_folder_path = Path(INVOICE_DOWNLOAD_FOLDER) / base_folder
            base_folder_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created missing invoices download directory: {base_folder_path}")
        except Exception as dir_error:
            logger.error(f"Directory creation failed: {str(dir_error)}")
            raise

        # Email processing
        try:
            mail = login()
            filtered_ids = search_previous_week_emails(mail)

            if not filtered_ids:
                logger.info("No emails from last 7 days to process")
                return

            logger.info(f"Processing {len(filtered_ids)} emails from last 7 days")
            successfully_processed_emails = 0
            
            for idx, e_id in enumerate(filtered_ids, 1):
                try:
                    logger.info(f"Processing email {idx}/{len(filtered_ids)} - UID: {e_id}")
                    # Use BODY.PEEK to avoid marking emails as read
                    result, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')

                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"Failed to fetch email UID {e_id}")
                        continue
                    
                    try:
                        raw_email = response[0][1].decode('utf-8')
                    except UnicodeDecodeError:
                        raw_email = response[0][1].decode('latin-1')

                    email_message = email.message_from_string(raw_email)
                    
                    # Download attachments (no marking logic)
                    download_success = download_email_attachments(email_message, base_folder_path)
                    
                    if download_success:
                        successfully_processed_emails += 1
                        logger.info(f"Email UID {e_id} processed successfully with attachments")
                    else:
                        logger.debug(f"Email UID {e_id} processed but no attachments found")

                except Exception as email_error:
                    logger.error(f"Failed to process email UID {e_id}: {str(email_error)}\n{traceback.format_exc()}")
                    continue

            logger.info(f"Successfully processed {successfully_processed_emails} emails with attachments from last 7 days")

        except Exception as processing_error:
            logger.error(f"Email processing failed: {str(processing_error)}\n{traceback.format_exc()}")
            # Continue to post-processing even if email processing partially failed

        # Post-processing
        try:
            logger.info("Starting missing invoice conversion")
            converted_files, failed_files = convert_invoice_for_email(base_folder_path)
            logger.info(f"Missing invoice conversion complete. Success: {len(converted_files)}, Failed: {len(failed_files)}")

            logger.info("Starting missing invoice data processing")
            process_extracted_data(converted_files, failed_files)
            logger.info("Missing invoice data processing complete")

        except Exception as post_error:
            logger.error(f"Post-processing failed: {str(post_error)}\n{traceback.format_exc()}")
            # Log error but don't crash the entire process

    except Exception as main_error:
        logger.error(f"Critical error in missing invoice background task: {str(main_error)}\n{traceback.format_exc()}")
        # Log error but allow graceful cleanup in finally block

    finally:
        try:
            if mail:
                logger.info("Closing IMAP connection")
                mail.close()
                mail.logout()
        except Exception as logout_error:
            logger.error(f"Error closing connection: {str(logout_error)}")
