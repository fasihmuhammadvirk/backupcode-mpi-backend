import time
import imaplib
import email
import os
import re
import traceback
from pathlib import Path
from email.utils import parsedate_to_datetime
import pytz
import logging

logger = logging.getLogger(__name__)

from mpi_backend.config import SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER, SUPPLIERS, TIMEZONE
from datetime import datetime, timedelta

from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice

EXCLUDED_SENDERS = [
    "info@wwps.co", "bmwpsupply@gmail.com", "billing@ysplumbing.com", "accounting@supremeplumbingnj.com",
    "orders@supremeplumbingnj.com", "billing@pyramidps.com", "purchasing@pyramidps.com",
    "donotreply@brucesupply.net", "donotreply@certifiedlumber.com", "breindy@parkplumbingsupply.com",
    "accounting@kjpsinc.com", "nefcocorp@billtrust.com", "timsfile@awisco.net", "billing@afsupply.com",
    "billing@sparkleening.com", "billing@positive.tech", "ar@opusoperations.com", "donotreply@cardknox.com",
    "billing@flowmarksupply.com", "mendy@flowmarksupply.com", "billing@mpiplumbingcorp.com", "Info@wwps.co"
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
    except Exception as e:
        logger.error(f"IMAP connection failed: {str(e)}")
        if mail:
            mail.logout()
        raise


def search_emails_last_30_days(mail):
    """Search for emails from the last 30 days, including both read and unread messages."""
    try:
        thirty_days_ago = (datetime.now(TIMEZONE) - timedelta(days=30)).strftime('%d-%b-%Y')
        logger.info(f"Searching for emails since {thirty_days_ago}")

        result, data = mail.uid('search', None, f'(SINCE "{thirty_days_ago}")')
        if result != 'OK':
            logger.error(f"Email search failed: {result}")
            return []

        email_ids = data[0].split()
        logger.info(f"Found {len(email_ids)} emails in the last 30 days")
        return email_ids

    except Exception as e:
        logger.error(f"Error in search_emails_last_30_days: {str(e)}\n{traceback.format_exc()}")
        return []


def download_email_attachments(email_message, base_folder_path):
    """Download attachments with improved error handling"""
    try:
        supplier_name = "unknown"
        processed_parts = 0
        saved_attachments = 0

        for part_idx, part in enumerate(email_message.walk(), 1):
            processed_parts += 1
            try:
                payload = part.get_payload()
                payload_text = ' '.join(str(p) for p in payload) if isinstance(payload, list) else str(payload)

                if ((part.get_content_maintype() != 'multipart' and part.get('Content-Disposition') is not None) or
                        ('customer of World Wide' in payload_text)):

                    # Supplier detection
                    try:
                        logger.info(f"Emailed with Subject: {email_message.get('Subject')}")
                        supplier_name = get_supplier(
                            email_message.get('Subject', ''),
                            email_message.get('Return-Path', '')
                        )
                        if supplier_name == "no_supplier":
                            logger.warning(f"Skipping email with undetermined supplier")
                            return
                    except Exception as sup_error:
                        logger.error(f"Supplier detection failed: {str(sup_error)}")
                        return

                    # Date handling
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

                    # Path construction
                    try:
                        inner_dir = f'{date_time_obj.month}-{date_time_obj.day}-{date_time_obj.year}'
                        supplier_path = os.path.join(base_folder_path, supplier_name)
                        Path(supplier_path).mkdir(parents=True, exist_ok=True)
                        inner_dir_path = os.path.join(supplier_path, inner_dir)
                        Path(inner_dir_path).mkdir(parents=True, exist_ok=True)
                    except OSError as dir_error:
                        logger.error(f"Directory creation failed: {str(dir_error)}")
                        return

                    # File handling
                    filename = part.get_filename()
                    if not filename:
                        logger.warning("Attachment missing filename, skipping")
                        continue

                    if not filename.lower().endswith(('.pdf', '.PDF')):
                        logger.debug(f"Skipping non-PDF attachment: {filename}")
                        continue

                    filepath = os.path.join(inner_dir_path, filename)
                    try:
                        with open(filepath, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                            saved_attachments += 1
                            logger.info(f"Saved attachment: {filename} => {filepath}")
                    except IOError as file_error:
                        logger.error(f"Failed to save file {filename}: {str(file_error)}")
                        continue

            except Exception as part_error:
                logger.error(f"Error processing part {part_idx}: {str(part_error)}\n{traceback.format_exc()}")
                continue

        logger.info(f"Processed {processed_parts} MIME parts, saved {saved_attachments} attachments")

    except Exception as e:
        logger.error(f"Error in download_email_attachments: {str(e)}\n{traceback.format_exc()}")


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
            return "no_supplier"
    except Exception as e:
        logger.error(f"Supplier detection failed: {str(e)}\n{traceback.format_exc()}")
        return "no_supplier"


def email_download_background_task():
    """Main task function with comprehensive error handling"""
    mail = None
    try:
        mail = login()
        email_ids = search_emails_last_30_days(mail)

        if not email_ids:
            logger.info("No new emails to process")
            return

        logger.info(f"Processing {len(email_ids)} emails")
        for idx, e_id in enumerate(email_ids, 1):
            try:
                logger.info(f"Processing email {idx}/{len(email_ids)} - UID: {e_id}")
                result, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')
                if result != 'OK' or not response or not response[0]:
                    logger.error(f"Failed to fetch email UID {e_id}")
                    continue

                try:
                    raw_email = response[0][1].decode('utf-8')
                except UnicodeDecodeError:
                    raw_email = response[0][1].decode('latin-1')

                email_message = email.message_from_string(raw_email)
                download_email_attachments(email_message, INVOICE_DOWNLOAD_FOLDER)

            except Exception as email_error:
                logger.error(f"Failed to process email UID {e_id}: {str(email_error)}\n{traceback.format_exc()}")
                continue

    except Exception as main_error:
        logger.error(f"Critical error in background task: {str(main_error)}\n{traceback.format_exc()}")
        raise

    finally:
        try:
            if mail:
                logger.info("Closing IMAP connection")
                mail.close()
                mail.logout()
        except Exception as logout_error:
            logger.error(f"Error closing connection: {str(logout_error)}")
