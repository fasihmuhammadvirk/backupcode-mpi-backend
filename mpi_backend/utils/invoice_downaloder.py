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
from mpi_backend.config.logging_config import get_missing_logger

# Create logs directory
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Use the centralized logging system
logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

# Setup missing emails / attachments tracker

def log_missing_email_or_attachment(email_subject, sender, reason, date_str):
    """Log missing emails or attachments to the centralized missing log"""
    log_entry = (f"MISSING: {reason} | Date: {date_str} | Sender: {sender} | "
                f"Subject: {email_subject} | Reason: {reason}")
    missing_logger.info(log_entry)

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
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(SMTP_SERVER)
        mail.login(LOGIN_EMAIL, LOGIN_PWD)
        mail.select('inbox')
        logger.info("Successfully connected to mailbox")
        return mail
    except imaplib.IMAP4.error as imap_error:
        logger.error(f"IMAP connection failed: {str(imap_error)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login: {str(e)}")
        if mail:
            mail.logout()
        raise

def search_new_emails(mail):
    """Search for new emails with error handling"""
    try:

        time_frame = datetime.now(TIMEZONE).strftime('%d-%b-%Y')
        logger.info(f"Searching for emails since {time_frame}")

        result, data = mail.uid('search', None, f'(SINCE {time_frame} UNSEEN)')
        if result != 'OK':
            logger.error(f"Email search failed: {result}")
            return []

        raw_email_ids = data[0].split()
        logger.info(f"Found {len(raw_email_ids)} emails in time frame")

        filtered_email_ids = []
        for idx, email_id in enumerate(raw_email_ids, 1):
            try:
                email_id = (email_id.decode('utf - 8') if isinstance(email_id, bytes)
                           else email_id)
                logger.debug(f"Processing email {idx}/{len(raw_email_ids)} - "
                           f"UID: {email_id}")

                result, msg_data = mail.uid('fetch', email_id,
                                          '(BODY.PEEK[HEADER.FIELDS (FROM)])')

                if result != 'OK':
                    logger.warning(f"Failed to fetch headers for UID {email_id}: "
                                 f"{result}")
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                from_email = email.utils.parseaddr(msg.get('From', ''))[1]

                if from_email in EXCLUDED_SENDERS:
                    filtered_email_ids.append(email_id)
                    logger.debug(f"Email UID {email_id} from excluded sender: "
                               f"{from_email}")

                else:
                    logger.debug(f"Email UID {email_id} from non - excluded sender: "
                               f"{from_email}")

            except Exception as e:
                logger.error(f"Error processing email UID {email_id}: {str(e)}"
                           f"\n{traceback.format_exc()}")
                continue

        logger.info(f"Found {len(filtered_email_ids)} emails from excluded "
                   f"senders")
        return filtered_email_ids

    except Exception as e:
        logger.error(f"Error in search_new_emails: {str(e)}\n{traceback.format_exc()}")
        return []

def get_supplier(email_subject, supplier_email) -> str:
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
        elif any(pattern in subject for pattern in ["world wide", "wwps",
                                                   "worldwide"]):
            return SUPPLIERS[1]

        # Y & S Plumbing Supply - multiple patterns
        elif any(pattern in subject for pattern in ["y&s", "y and s",
                                                   "ys plumbing", "y s plumbing"]):
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
            return "unknown_supplier"  # Changed from "no_supplier" to continue processing
    except Exception as e:
        logger.error(f"Supplier detection failed: {str(e)}"
                   f"\n{traceback.format_exc()}")
        return "unknown_supplier"  # Changed from "no_supplier" to continue processing

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

    # Extract email details for logging
    email_subject = email_message.get('Subject', 'No Subject')
    sender = email.utils.parseaddr(email_message.get('From', ''))[1]
    date_header = email_message.get('Date', '')

    try:
        # Enhanced supplier detection with fallback
        try:
            logger.info(f"Processing email with Subject: '{email_subject}'")
            supplier_name = get_supplier(
                email_subject,
                email_message.get('Return - Path', '')
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
                date_time_obj = (parsedate_to_datetime(date_header)
                               .astimezone(TIMEZONE))
            except Exception as date_error:
                logger.error(f"Date parsing failed: {str(date_error)}, "
                           f"using current time")
                date_time_obj = datetime.now(TIMEZONE)

        date_str = date_time_obj.strftime('%Y-%m-%d')

        # Log detailed email information
        logger.info(f"  {date_str} | {sender}")
        logger.info(f"    Subject: {email_subject}")
        invoice_type = ('invoice' if any(kw in email_subject.lower()
                                       for kw in ['invoice', 'invoices'])
                       else 'other')
        logger.info(f"    Supplier: {supplier_name} | Type: {invoice_type}")

        # Enhanced directory structure creation
        try:
            inner_dir = (f'{date_time_obj.month}-{date_time_obj.day}'
                        f'-{date_time_obj.year}')
            supplier_path = os.path.join(base_folder_path, supplier_name)
            Path(supplier_path).mkdir(parents=True, exist_ok=True)
            inner_dir_path = os.path.join(supplier_path, inner_dir)
            Path(inner_dir_path).mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory structure: {inner_dir_path}")
        except OSError as dir_error:
            logger.error(f"Directory creation failed: {str(dir_error)}")
            log_missing_email_or_attachment(
                email_subject, sender,
                f"Directory creation failed: {str(dir_error)}", date_str
            )
            return False

        # CRITICAL FIX: Enhanced attachment detection logic
        attachment_details = []
        for part_idx, part in enumerate(email_message.walk(), 1):
            try:
                # Check multiple conditions for attachments
                content_disposition = part.get('Content - Disposition', '')
                content_type = part.get_content_type()
                filename = part.get_filename()

                logger.debug(f"Part {part_idx}: Content - Type={content_type}, "
                           f"Content - Disposition={content_disposition}, "
                           f"Filename={filename}")

                # Enhanced attachment detection conditions
                is_attachment = (
                    # Standard attachment detection
                    (content_disposition and 'attachment' in content_disposition.lower()) or
                    # Inline attachments
                    (content_disposition and 'inline' in content_disposition.lower() and filename) or
                    # PDF files regardless of disposition
                    (content_type == 'application / pdf') or
                    # Files with PDF extension
                    (filename and filename.lower().endswith(('.pdf', '.PDF'))) or
                    # Binary content with filename
                    (filename and content_type.startswith('application/') and
                     not content_type.startswith('application / pgp')) or
                    # Special case for multipart / mixed with binary payload
                    (not part.is_multipart() and filename and
                     len(part.get_payload(decode=False)) > 1000)
                )

                if is_attachment:
                    attachments_found += 1

                    if not filename:
                        # Generate filename for unnamed attachments
                        if content_type == 'application / pdf':
                            filename = (f"attachment_{part_idx}_"
                                      f"{date_time_obj.strftime('%Y%m%d_%H%M%S')}.pdf")
                        else:
                            logger.warning(f"Attachment {part_idx} has no filename "
                                         f"and unknown type: {content_type}")
                            attachment_details.append(
                                f"      - UNNAMED ({content_type}) - PDF: False [SKIPPED]"
                            )
                            continue

                    is_pdf = filename.lower().endswith(('.pdf', '.PDF'))
                    attachment_details.append(
                        f"      - {filename} ({content_type}) - PDF: {is_pdf}"
                    )

                    logger.info(f"Found attachment {attachments_found}: "
                              f"{filename} (Type: {content_type})")

                    # Only process PDF files
                    if not is_pdf:
                        logger.debug(f"Skipping non - PDF attachment: {filename}")
                        continue

                    # Download with retry mechanism
                    filepath = os.path.join(inner_dir_path, filename)
                    if download_attachment_with_retry(part, filepath):
                        attachments_downloaded += 1
                        logger.info(f"Successfully saved: {filename} => {filepath}")
                    else:
                        logger.error(f"Failed to download after retries: {filename}")
                        log_missing_email_or_attachment(
                            email_subject, sender,
                            f"Failed to download attachment: {filename}", date_str
                        )

            except Exception as part_error:
                logger.error(f"Error processing part {part_idx}: {str(part_error)}\n{traceback.format_exc()}")
                continue

        # Log attachment summary
        if attachment_details:
            logger.info(f"    Attachments: {attachments_found} total, "
                       f"{attachments_downloaded} PDFs")
            for detail in attachment_details:
                logger.info(detail)
        else:
            logger.info("    Attachments: 0 total, 0 PDFs")
            log_missing_email_or_attachment(
                email_subject, sender, "No attachments found in email", date_str
            )

        # Log final results
        logger.info(f"Email processing complete - Found: {attachments_found} "
                   f"attachments, Downloaded: {attachments_downloaded} PDFs")
        logger.info("")  # Add blank line for readability

        # Return success status
        return attachments_downloaded > 0

    except Exception as e:
        logger.error(f"Error in download_email_attachments: {str(e)}"
                   f"\n{traceback.format_exc()}")
        log_missing_email_or_attachment(
            email_subject, sender,
            f"Email processing error: {str(e)}",
            date_str if 'date_str' in locals() else 'unknown'
        )
        return False

def email_download_background_task():
    """Invoice download background task - runs continuously without interruption"""
    logger.info("="*80)
    logger.info("STARTING REGULAR INVOICE DOWNLOADER")
    logger.info("="*80)
    logger.info(f"Session started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    mail = None
    try:
        # Setup directory structure
        try:
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = (f"{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                          f"{datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}")
            base_folder_path = Path(INVOICE_DOWNLOAD_FOLDER) / base_folder
            base_folder_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created download directory: {base_folder_path}")
        except Exception as dir_error:
            logger.error(f"Directory creation failed: {str(dir_error)}")
            raise

        # Email processing
        try:
            mail = login()
            filtered_ids = search_new_emails(mail)

            if not filtered_ids:
                logger.info("No new emails to process")
                logger.info("="*80)
                return

            logger.info(f"Processing {len(filtered_ids)} emails")
            logger.info("-" * 80)
            successfully_processed_emails = []

            for idx, e_id in enumerate(filtered_ids, 1):
                try:
                    logger.info(f"Processing email {idx}/{len(filtered_ids)} - "
                              f"UID: {e_id}")
                    result, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')

                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"Failed to fetch email UID {e_id}")
                        continue

                    try:
                        raw_email = response[0][1].decode('utf - 8')
                    except UnicodeDecodeError:
                        raw_email = response[0][1].decode('latin - 1')

                    email_message = email.message_from_string(raw_email)

                    # CRITICAL FIX: Only mark as read if attachments were successfully downloaded
                    download_success = download_email_attachments(email_message, base_folder_path)

                    if download_success:
                        successfully_processed_emails.append(e_id)
                        logger.info(f"Email UID {e_id} processed successfully "
                                  f"with attachments")
                    else:
                        logger.warning(f"Email UID {e_id} processed but no "
                                     f"attachments downloaded - NOT marking as read")

                except Exception as email_error:
                    logger.error(f"Failed to process email UID {e_id}: "
                               f"{str(email_error)}\n{traceback.format_exc()}")
                    continue

            logger.info("-" * 80)

            # CRITICAL FIX: Only mark emails as read after successful processing
            logger.info(f"Marking {len(successfully_processed_emails)} "
                       f"successfully processed emails as read")
            for e_id in successfully_processed_emails:
                try:
                    # Get email details for conditional marking
                    result, response = mail.uid('fetch', e_id,
                                              '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
                    if result == 'OK' and response[0]:
                        raw_email = response[0][1]
                        msg = email.message_from_bytes(raw_email)
                        subject = (msg.get('Subject', '') or '').lower()
                        sender = email.utils.parseaddr(msg.get('From', ''))[1]

                        # Check if should be marked as read
                        has_invoice_keyword = any(kw in subject
                                                for kw in ['invoice', 'invoices', 'invoice(s)'])
                        is_excluded_sender = sender in EXCLUDED_SENDERS

                        if is_excluded_sender and has_invoice_keyword:
                            mail.uid('store', e_id, '+FLAGS', '(\\Seen)')
                            logger.info(f"Marked email UID {e_id} as read "
                                      f"(sender: {sender})")
                        else:
                            logger.debug(f"Email UID {e_id} not marked as read "
                                       f"(sender: {sender}, has_invoice: {has_invoice_keyword})")

                except Exception as flag_error:
                    logger.error(f"Error marking email UID {e_id} as read: "
                               f"{str(flag_error)}")

        except Exception as processing_error:
            logger.error(f"Email processing failed: {str(processing_error)}\n{traceback.format_exc()}")
            raise

        # Post - processing
        try:
            logger.info("Starting invoice conversion")
            converted_files, failed_files = convert_invoice_for_email(base_folder_path)
            logger.info(f"Conversion complete. Success: {len(converted_files)}, "
                       f"Failed: {len(failed_files)}")

            logger.info("Starting data processing")
            process_extracted_data(converted_files, failed_files)
            logger.info("Data processing complete")

        except Exception as post_error:
            logger.error(f"Post - processing failed: {str(post_error)}"
                       f"\n{traceback.format_exc()}")
            raise

    except Exception as main_error:
        logger.error(f"Critical error in background task: {str(main_error)}"
                   f"\n{traceback.format_exc()}")
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
        logger.info("REGULAR INVOICE DOWNLOADER COMPLETED")
        logger.info("="*80)
