#!/usr/bin/env python3
"""
Last 4 Days Invoice Downloader Script

This script downloads invoices from the last 4 days using the exact same concept
as the regular email downloader, including email marking behavior.

Usage:
    python download_past_49_hours.py

Features:
    - Downloads invoices from last 4 days
    - Uses same supplier detection logic
    - Same attachment processing
    - Same email marking behavior (marks as read after successful download)
    - Organized folder structure
    - Comprehensive logging
    - EXACTLY like regular email downloader
"""

import sys
import os
import time
import imaplib
import email
import email.utils
import traceback
import logging
from pathlib import Path
from datetime import datetime, timedelta
import pytz

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import configuration and utilities
from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, INVOICE_DOWNLOAD_FOLDER,
    SUPPLIERS, TIMEZONE
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('past_49_hours_download.log')
    ]
)
logger = logging.getLogger(__name__)

# Excluded senders (same as regular downloader)
EXCLUDED_SENDERS = [
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
        logger.info("SUCCESS: Successfully connected to mailbox")
        return mail
    except imaplib.IMAP4.error as imap_error:
        logger.error(f"ERROR: IMAP connection failed: {str(imap_error)}")
        raise
    except Exception as e:
        logger.error(f"ERROR: Unexpected error during login: {str(e)}")
        if mail:
            mail.logout()
        raise

def search_last_4_days_emails(mail):
    """Search for emails from the last 4 days with error handling"""
    try:
        # Calculate time range: last 4 days
        now = datetime.now(TIMEZONE)
        last_4_days = now - timedelta(days=4)
        
        # Format for IMAP search
        time_frame = last_4_days.strftime('%d-%b-%Y')
        logger.info(f"SEARCH: Searching for emails since {time_frame} (last 4 days)")
        logger.info(f"   From: {last_4_days.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info(f"   To:   {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        # Search for emails in the last 4 days (not just unseen)
        result, data = mail.uid('search', None, f'(SINCE {time_frame})')
        if result != 'OK':
            logger.error(f"❌ Email search failed: {result}")
            return []

        raw_email_ids = data[0].split()
        logger.info(f"FOUND: Found {len(raw_email_ids)} emails in time frame")

        filtered_email_ids = []
        for idx, email_id in enumerate(raw_email_ids, 1):
            try:
                email_id = (email_id.decode('utf-8') if isinstance(email_id, bytes)
                           else email_id)
                logger.debug(f"Processing email {idx}/{len(raw_email_ids)} - UID: {email_id}")

                # Fetch email headers to check sender and date
                result, msg_data = mail.uid('fetch', email_id,
                                          '(BODY.PEEK[HEADER.FIELDS (FROM DATE)])')

                if result != 'OK':
                    logger.warning(f"⚠️ Failed to fetch headers for UID {email_id}: {result}")
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                from_email = email.utils.parseaddr(msg.get('From', ''))[1]
                
                # Check if email is from excluded sender
                if from_email in EXCLUDED_SENDERS:
                    filtered_email_ids.append(email_id)
                    logger.debug(f"EMAIL: Email UID {email_id} from excluded sender: {from_email}")
                else:
                    logger.debug(f"EMAIL: Email UID {email_id} from non-excluded sender: {from_email}")

            except Exception as e:
                logger.error(f"❌ Error processing email UID {email_id}: {str(e)}")
                continue

        logger.info(f"FOUND: Found {len(filtered_email_ids)} emails from excluded senders")
        return filtered_email_ids

    except Exception as e:
        logger.error(f"ERROR: Error in search_past_49_hours_emails: {str(e)}")
        return []

def get_supplier(email_subject, supplier_email) -> str:
    """Get supplier name with error handling (same as regular downloader)"""
    try:
        # Normalize inputs
        raw_subject = (email_subject or "").lower()
        subject = " ".join(raw_subject.split())  # collapse whitespace
        supplier_email = (supplier_email or "").lower().strip()

        if "statement" in subject:
            return "no_supplier"

        # Domain-based fast paths
        if any(d in supplier_email for d in ["@wwps.co", "worldwideplumbingsupply", "wwps."]):
            return SUPPLIERS[1]
        if any(d in supplier_email for d in ["@bmwpsupply", "@bmwplumbing", "bmwpsupply.com"]):
            return SUPPLIERS[0]

        # BMW Plumbing Supplies - multiple patterns
        if any(pattern in subject for pattern in ["bmw", "bmwpsupply", "bmw plumbing supplies"]):
            return SUPPLIERS[0]

        # World Wide Plumbing - multiple patterns
        elif any(pattern in subject for pattern in [
            "world wide plumbing supply", "world wide", "world-wide", "worldwide", "wwps",
        ]):
            return SUPPLIERS[1]

        # Y & S Plumbing Supply - multiple patterns
        elif any(pattern in subject for pattern in ["y&s", "y and s", "ys plumbing", "y s plumbing", "Y&S Plumbing & Heating Supply"]):
            return SUPPLIERS[2]

        # Supreme Plumbing Supply - multiple patterns
        elif any(pattern in subject for pattern in ["supreme plumbing", "invoice # i-", "supremeplumbing"]):
            return SUPPLIERS[3]

        # Pyramid Plumbing Supply - multiple patterns
        elif any(pattern in subject for pattern in ["pyramid", "pyramid plumbing", "pyramidps"]):
            return SUPPLIERS[4]

        # Bruce Supply - multiple patterns
        elif any(pattern in subject for pattern in ["bruce", "brucesupply", "bruce supply"]):
            return SUPPLIERS[5]

        # Certified Lumber - multiple patterns
        elif any(pattern in subject for pattern in ["certified lumber", "certifiedlumber"]):
            return SUPPLIERS[6]

        # Park Plumbing Supply - multiple patterns
        elif any(pattern in subject for pattern in ["park plumbing", "parkplumbingsupply"]):
            return SUPPLIERS[7]

        # KJP Services - multiple patterns
        elif any(pattern in subject for pattern in ["kjp", "kjpsinc", "kjp services"]):
            return SUPPLIERS[8]

        # NEFCO - multiple patterns
        elif any(pattern in subject for pattern in ["nefco", "nefcocorp", "billtrust"]):
            return SUPPLIERS[9]

        # AWISCO - multiple patterns
        elif any(pattern in subject for pattern in ["awisco", "timsfile"]):
            return SUPPLIERS[10]

        # AF Supply - multiple patterns
        elif any(pattern in subject for pattern in ["af supply", "afsupply"]):
            return SUPPLIERS[11]

        # Sparkleen - multiple patterns
        elif any(pattern in subject for pattern in ["sparkleen", "sparkleening"]):
            return SUPPLIERS[12]

        # Positive Technology - multiple patterns
        elif any(pattern in subject for pattern in ["positive tech", "positive.tech"]):
            return SUPPLIERS[13]

        # Opus Operations - multiple patterns
        elif any(pattern in subject for pattern in ["opus", "opusoperations"]):
            return SUPPLIERS[14]

        # CardKnox - multiple patterns
        elif any(pattern in subject for pattern in ["cardknox", "card knox"]):
            return SUPPLIERS[15]

        # Flow Mark Supply - multiple patterns
        elif any(pattern in subject for pattern in ["flow mark", "flowmarksupply"]):
            return SUPPLIERS[16]

        # MPI Plumbing - multiple patterns
        elif any(pattern in subject for pattern in ["mpi plumbing", "mpiplumbingcorp"]):
            return SUPPLIERS[17]

        return "unknown"

    except Exception as e:
        logger.error(f"ERROR: Error in get_supplier: {str(e)}")
        return "unknown"

def download_email_attachments(email_message, base_folder_path):
    """Download email attachments with supplier detection"""
    try:
        email_subject = email_message.get('Subject', '')
        sender_email = email.utils.parseaddr(email_message.get('From', ''))[1]
        
        # Detect supplier
        supplier = get_supplier(email_subject, sender_email)
        logger.info(f"SUPPLIER: Detected supplier: {supplier} for email: {email_subject[:50]}...")
        
        # Create supplier-specific folder
        supplier_folder = base_folder_path / supplier
        supplier_folder.mkdir(parents=True, exist_ok=True)
        
        downloaded_count = 0
        
        # Process email parts
        for part in email_message.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue
                
            filename = part.get_filename()
            if filename:
                # Clean filename
                filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
                if not filename:
                    filename = f"attachment_{downloaded_count + 1}"
                
                # Add timestamp to avoid conflicts
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = f"{timestamp}_{filename}"
                
                file_path = supplier_folder / safe_filename
                
                # Save attachment
                with open(file_path, 'wb') as f:
                    f.write(part.get_payload(decode=True))
                
                downloaded_count += 1
                logger.info(f"DOWNLOADED: Downloaded: {safe_filename} to {supplier}")
        
        return downloaded_count > 0
        
    except Exception as e:
        logger.error(f"ERROR: Error downloading attachments: {str(e)}")
        return False

def fetch_email_thread(mail, email_id):
    """Fetch email thread (same as regular downloader)"""
    try:
        # Get email headers to find thread
        result, response = mail.uid('fetch', email_id, '(BODY.PEEK[HEADER.FIELDS (REFERENCES IN-REPLY-TO)])')
        if result != 'OK':
            return [email_id]
        
        # For simplicity, return single email ID
        # In production, you might want to implement full thread detection
        return [email_id]
        
    except Exception as e:
        logger.error(f"ERROR: Error fetching email thread: {str(e)}")
        return [email_id]

def download_invoice_attachments_from_thread(mail, thread_email_ids, base_folder_path):
    """Download attachments from email thread"""
    try:
        total_downloaded = 0
        
        for email_id in thread_email_ids:
            try:
                # Fetch email content
                result, response = mail.uid('fetch', email_id, '(BODY.PEEK[])')
                if result != 'OK':
                    continue
                
                raw_email = response[0][1]
                try:
                    email_content = raw_email.decode('utf-8')
                except UnicodeDecodeError:
                    email_content = raw_email.decode('latin-1')
                
                email_message = email.message_from_string(email_content)
                download_success = download_email_attachments(email_message, base_folder_path)
                
                if download_success:
                    total_downloaded += 1
                    
            except Exception as e:
                logger.error(f"ERROR: Error processing thread email {email_id}: {str(e)}")
                continue
        
        return True, total_downloaded
        
    except Exception as e:
        logger.error(f"ERROR: Error processing email thread: {str(e)}")
        return False, 0

def download_last_4_days_invoices():
    """Main function to download invoices from last 4 days"""
    logger.info("STARTING: STARTING LAST 4 DAYS INVOICE DOWNLOADER")
    logger.info("=" * 80)
    logger.info(f"Session started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("Scope: Last 4 days, ALL emails (not just unseen)")
    logger.info("Behavior: EXACTLY like regular email downloader - marks as read after success")

    mail = None
    try:
        # Setup directory structure
        try:
            now = datetime.now(TIMEZONE)
            last_4_days = now - timedelta(days=4)
            
            base_folder = f"LAST_4_DAYS_{last_4_days.strftime('%d-%b-%Y_%H-%M-%S')}_to_{now.strftime('%d-%b-%Y_%H-%M-%S')}"
            base_folder_path = Path(INVOICE_DOWNLOAD_FOLDER) / base_folder
            base_folder_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"DIRECTORY: Created download directory: {base_folder_path}")
        except Exception as dir_error:
            logger.error(f"ERROR: Directory creation failed: {str(dir_error)}")
            raise

        # Email processing
        try:
            mail = login()
            filtered_ids = search_last_4_days_emails(mail)

            if not filtered_ids:
                logger.info("EMAILS: No emails found in last 4 days")
                logger.info("=" * 80)
                return

            logger.info(f"EMAILS: Processing {len(filtered_ids)} emails from last 4 days")
            logger.info("-" * 80)
            successfully_processed_emails = []

            for idx, e_id in enumerate(filtered_ids, 1):
                try:
                    logger.info(f"EMAIL: Processing email {idx}/{len(filtered_ids)} - UID: {e_id}")
                    
                    # Check if this email has invoice keywords in subject
                    result, response = mail.uid('fetch', e_id, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
                    
                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"ERROR: Failed to fetch subject for email UID {e_id}")
                        continue
                    
                    raw_email = response[0][1]
                    msg = email.message_from_bytes(raw_email)
                    subject = (msg.get('Subject', '') or '').lower()
                    
                    # Check for invoice keywords
                    has_invoice_keyword = any(kw in subject
                                            for kw in ['invoice', 'invoices', 'invoice(s)'])
                    
                    if has_invoice_keyword:
                        logger.info(f"EMAIL: Email UID {e_id} contains invoice keywords, processing thread")
                        
                        # Fetch the full conversation thread
                        thread_email_ids = fetch_email_thread(mail, e_id)
                        
                        if len(thread_email_ids) > 1:
                            logger.info(f"EMAIL: Found thread with {len(thread_email_ids)} emails for UID {e_id}")
                            # Process the entire thread for attachments
                            thread_found, thread_downloaded = download_invoice_attachments_from_thread(
                                mail, thread_email_ids, base_folder_path
                            )
                            
                            if thread_downloaded > 0:
                                successfully_processed_emails.append(e_id)
                                logger.info(f"SUCCESS: Email UID {e_id} thread processed successfully with {thread_downloaded} attachments")
                            else:
                                logger.warning(f"WARNING: Email UID {e_id} thread processed but no attachments downloaded")
                        else:
                            logger.info(f"EMAIL: Email UID {e_id} has no thread, processing as single email")
                            # Process as single email
                            result, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')
                            
                            if result != 'OK' or not response or not response[0]:
                                logger.error(f"ERROR: Failed to fetch email UID {e_id}")
                                continue
                            
                            try:
                                raw_email = response[0][1].decode('utf-8')
                            except UnicodeDecodeError:
                                raw_email = response[0][1].decode('latin-1')
                            
                            email_message = email.message_from_string(raw_email)
                            download_success = download_email_attachments(email_message, base_folder_path)
                            
                            if download_success:
                                successfully_processed_emails.append(e_id)
                                logger.info(f"SUCCESS: Email UID {e_id} processed successfully with attachments")
                            else:
                                logger.warning(f"WARNING: Email UID {e_id} processed but no attachments downloaded")
                    else:
                        logger.debug(f"EMAIL: Email UID {e_id} does not contain invoice keywords, skipping")
                        
                except Exception as e:
                    logger.error(f"ERROR: Error processing email UID {e_id}: {str(e)}")
                    continue

            logger.info("-" * 80)

            # CRITICAL: Mark emails as read after successful processing (same as regular downloader)
            logger.info(f"MARKING: Marking {len(successfully_processed_emails)} "
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

                        # Check if should be marked as read (same logic as regular downloader)
                        has_invoice_keyword = any(kw in subject
                                                for kw in ['invoice', 'invoices', 'invoice(s)'])
                        is_excluded_sender = sender in EXCLUDED_SENDERS

                        if is_excluded_sender and has_invoice_keyword:
                            mail.uid('store', e_id, '+FLAGS', '(\\Seen)')
                            logger.info(f"SUCCESS: Marked email UID {e_id} as read "
                                      f"(sender: {sender})")
                        else:
                            logger.debug(f"EMAIL: Email UID {e_id} not marked as read "
                                       f"(sender: {sender}, has_invoice: {has_invoice_keyword})")

                except Exception as flag_error:
                    logger.error(f"ERROR: Error marking email UID {e_id} as read: "
                               f"{str(flag_error)}")

            # Summary
            logger.info("-" * 80)
            logger.info(f"SUMMARY: DOWNLOAD SUMMARY:")
            logger.info(f"   Total emails found: {len(filtered_ids)}")
            logger.info(f"   Successfully processed: {len(successfully_processed_emails)}")
            logger.info(f"   Failed: {len(filtered_ids) - len(successfully_processed_emails)}")
            logger.info(f"   Download folder: {base_folder_path}")
            logger.info("=" * 80)
            logger.info("SUCCESS: LAST 4 DAYS INVOICE DOWNLOAD COMPLETED")

        except Exception as processing_error:
            logger.error(f"ERROR: Email processing failed: {str(processing_error)}")
            raise

    except Exception as e:
        logger.error(f"ERROR: LAST 4 DAYS DOWNLOAD FAILED: {str(e)}")
        logger.error(traceback.format_exc())
        raise

    finally:
        if mail:
            try:
                mail.logout()
                logger.info("CLOSED: Mailbox connection closed")
            except Exception as e:
                logger.error(f"ERROR: Error closing mailbox connection: {str(e)}")

if __name__ == "__main__":
    try:
        print("STARTING: Starting Last 4 Days Invoice Downloader")
        print("=" * 60)
        print("This script will download invoices from the last 4 days")
        print("using the same logic as your regular email downloader.")
        print()
        
        # Run the download
        download_last_4_days_invoices()
        
        print("\nSUCCESS: Script completed successfully!")
        print("Check the log file 'past_49_hours_download.log' for details.")
        
    except Exception as e:
        print(f"\nERROR: Script failed: {str(e)}")
        print("Check the log file for detailed error information.")
        sys.exit(1)
