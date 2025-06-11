import imaplib
import email
import re
import logging
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, TIMEZONE, INVOICE_DOWNLOAD_FOLDER
)
from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement
)
from mpi_backend.database import db_context
from mpi_backend.utils.s3_utils import upload_file
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Statement suppliers - using EXCLUDED_SENDERS pattern from invoices
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

# Suppliers that send monthly statements
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


def login():
    """Establish IMAP connection with error handling"""
    try:
        mail = imaplib.IMAP4_SSL(SMTP_SERVER)
        mail.login(LOGIN_EMAIL, LOGIN_PWD)
        mail.select('inbox')
        logger.info("Successfully connected to mailbox for statements")
        return mail
    except Exception as e:
        logger.error(f"IMAP connection failed: {str(e)}")
        raise


def search_statement_emails(mail):
    """Search for statement emails using same logic as invoice downloader"""
    try:
        # Search for emails from last 30 days (similar to invoice logic)
        date_30_days_ago = (datetime.now(TIMEZONE) - 
                           timedelta(days=30)).strftime('%d-%b-%Y')
        logger.info(f"Searching for statement emails since {date_30_days_ago}")
        
        # Search all emails in timeframe first
        result, data = mail.uid('search', None, 
                               f'(SINCE "{date_30_days_ago}")')
        if result != 'OK':
            logger.error(f"Statement email search failed: {result}")
            return []

        raw_email_ids = data[0].split()
        logger.info(f"Found {len(raw_email_ids)} emails in time frame")

        # Filter emails by statement criteria (like invoice EXCLUDED_SENDERS)
        filtered_email_ids = []
        for idx, email_id in enumerate(raw_email_ids, 1):
            try:
                email_id = (
                    email_id.decode('utf-8') 
                    if isinstance(email_id, bytes) else email_id
                )
                logger.debug(
                    f"Processing email {idx}/{len(raw_email_ids)} - "
                    f"UID: {email_id}"
                )

                # Always use BODY.PEEK to never mark emails as read
                result, msg_data = mail.uid(
                    'fetch', 
                    email_id, 
                    '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])'
                )

                if result != 'OK':
                    logger.warning(
                        f"Failed to fetch headers for UID {email_id}: {result}"
                    )
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                from_email = email.utils.parseaddr(msg.get('From', ''))[1]
                subject = msg.get('Subject', '').lower()

                # Check if from statement sender AND has statement keyword 
                # (case-insensitive)
                if (from_email in STATEMENT_SENDERS and 
                        'monthly statement' in subject):
                    filtered_email_ids.append(email_id)
                    logger.debug(
                        f"Statement email UID {email_id} from: {from_email}, "
                        f"subject: {subject}"
                    )

            except Exception as e:
                logger.error(
                    f"Error processing email UID {email_id}: {str(e)}"
                    f"\n{traceback.format_exc()}"
                )
                continue

        logger.info(f"Found {len(filtered_email_ids)} statement emails")
        return filtered_email_ids

    except Exception as e:
        logger.error(
            f"Error in search_statement_emails: {str(e)}"
            f"\n{traceback.format_exc()}"
        )
        return []


def get_statement_supplier(
    email_subject: str, 
    supplier_email: str
) -> Optional[str]:
    """Detect supplier from statement email - similar to invoice logic"""
    try:
        subject = (email_subject or "").lower()
        supplier_email = (supplier_email or "").lower()

        if "bmw" in subject or "bmwpsupply" in supplier_email:
            return "BMW Plumbing Supplies"
        elif "world wide" in subject or "wwps" in supplier_email:
            return "World Wide Plumbing"
        elif "y&s" in subject or "ysplumbing" in supplier_email:
            return "Y & S Plumbing Supply"
        elif "supreme" in subject or "supremeplumbingnj" in supplier_email:
            return "Supreme Plumbing Supply"
        elif "pyramid" in subject or "pyramidps" in supplier_email:
            return "Pyramid Plumbing"
        elif "abc opus" in subject or "opusoperations" in supplier_email:
            return "ABC Opus Services"
        elif ("park plumbing" in subject or 
              "parkplumbingsupply" in supplier_email):
            return "Park Plumbing Supply"
        elif "gotham" in subject or "gotham" in supplier_email:
            return "Gotham Plumbing Supply"
        elif "webb" in subject or "fwwebb" in supplier_email:
            return "FW Webb Plumbing Supply"
        elif "flow mark" in subject or "flowmarksupply" in supplier_email:
            return "Flow Mark Plumbing Supply"
        else:
            logger.warning(f"Unknown supplier for statement: {email_subject}")
            return "no_supplier"
    except Exception as e:
        logger.error(f"Supplier detection failed: {str(e)}")
        return "no_supplier"


def extract_statement_date_from_subject(subject: str) -> Optional[datetime]:
    """Extract statement date from email subject"""
    try:
        # Common patterns for statement dates in subjects
        date_patterns = [
            r'(\d{1,2}/\d{1,2}/\d{2,4})',  # MM/DD/YYYY or M/D/YY
            r'(\d{1,2}-\d{1,2}-\d{2,4})',  # MM-DD-YYYY
            r'(\w+\s+\d{4})',              # Month YYYY (e.g., "April 2024")
            r'(\d{4}-\d{2})',              # YYYY-MM
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, subject)
            if match:
                date_str = match.group(1)
                try:
                    # Try different date formats
                    for fmt in ['%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', 
                                '%B %Y', '%Y-%m']:
                        try:
                            return datetime.strptime(date_str, fmt)
                        except ValueError:
                            continue
                except Exception:
                    continue
        
        # Default to current month if no date found
        now = datetime.now()
        return datetime(now.year, now.month, 1)
        
    except Exception as e:
        logger.error(f"Date extraction failed: {str(e)}")
        return datetime.now().replace(day=1)


def ensure_suppliers_exist(db: Session):
    """Ensure all statement suppliers exist in database"""
    try:
        for supplier_name in STATEMENT_SUPPLIERS:
            existing_supplier = db.query(PlumbingSupplier).filter(
                PlumbingSupplier.name == supplier_name
            ).first()
            
            if not existing_supplier:
                new_supplier = PlumbingSupplier(
                    name=supplier_name,
                    is_active="Active"
                )
                db.add(new_supplier)
                logger.info(f"Created supplier: {supplier_name}")
        
        db.commit()
        logger.info("All statement suppliers verified/created")
        
    except Exception as e:
        logger.error(f"Error ensuring suppliers exist: {str(e)}")
        db.rollback()
        raise


def statement_already_exists(
    supplier_name: str, 
    statement_date: datetime, 
    db: Session
) -> bool:
    """Check if statement already exists for supplier and month"""
    try:
        # Get supplier
        supplier = db.query(PlumbingSupplier).filter(
            PlumbingSupplier.name == supplier_name
        ).first()
        
        if not supplier:
            return False
            
        # Check if statement exists for this month/year
        month_start = statement_date.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        
        existing_statement = db.query(PlumbingStatement).filter(
            PlumbingStatement.supplier_id == supplier.id,
            PlumbingStatement.statement_date >= month_start,
            PlumbingStatement.statement_date < next_month
        ).first()
        
        return existing_statement is not None
        
    except Exception as e:
        logger.error(f"Error checking statement existence: {str(e)}")
        return False


def download_statement_attachments(email_message, base_folder_path: Path):
    """Download statement attachments - using invoice downloader logic"""
    try:
        supplier_name = "unknown"
        processed_parts = 0
        saved_attachments = 0
        
        for part_idx, part in enumerate(email_message.walk(), 1):
            processed_parts += 1
            try:
                payload = part.get_payload()
                payload_text = (' '.join(str(p) for p in payload) 
                               if isinstance(payload, list) 
                               else str(payload))

                if ((part.get_content_maintype() != 'multipart' and 
                     part.get('Content-Disposition') is not None) or
                        ('customer of World Wide' in payload_text)):
                    
                    # Supplier detection (similar to invoice logic)
                    try:
                        logger.info(
                            f"Statement email with Subject: "
                            f"{email_message.get('Subject')}"
                        )
                        supplier_name = get_statement_supplier(
                            email_message.get('Subject', ''),
                            email_message.get('Return-Path', '')
                        )
                        if supplier_name == "no_supplier":
                            logger.warning(
                                "Skipping email with undetermined supplier"
                            )
                            return []
                    except Exception as sup_error:
                        logger.error(
                            f"Supplier detection failed: {str(sup_error)}"
                        )
                        return []
                    
                    # Date handling (same as invoice logic)
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
                    
                    # Statement date from subject
                    statement_date = extract_statement_date_from_subject(
                        email_message.get('Subject', '')
                    )
                    
                    # Check if statement already exists
                    with db_context() as db:
                        if statement_already_exists(
                            supplier_name, statement_date, db
                        ):
                            logger.info(
                                f"Statement already exists for "
                                f"{supplier_name} - "
                                f"{statement_date.strftime('%Y-%m')}, skipping"
                            )
                            return []
                    
                    # Path construction (similar to invoice structure)
                    try:
                        inner_dir = (
                            f'{date_time_obj.month}-{date_time_obj.day}-'
                            f'{date_time_obj.year}'
                        )
                        supplier_path = base_folder_path / supplier_name
                        supplier_path.mkdir(parents=True, exist_ok=True)
                        inner_dir_path = supplier_path / inner_dir
                        inner_dir_path.mkdir(parents=True, exist_ok=True)
                    except OSError as dir_error:
                        logger.error(
                            f"Directory creation failed: {str(dir_error)}"
                        )
                        return []
                    
                    # File handling (same as invoice logic)
                    filename = part.get_filename()
                    if not filename:
                        logger.warning(
                            f"Attachment missing filename, skipping of "
                            f"{email_message.get('Subject')}"
                        )
                        continue

                    if not filename.lower().endswith(('.pdf', '.PDF')):
                        logger.debug(
                            f"Skipping non-PDF attachment: {filename}"
                        )
                        continue

                    # Create unique filename with statement date
                    month_year = statement_date.strftime('%Y-%m')
                    unique_filename = (
                        f"{supplier_name}_{month_year}_{filename}"
                    )
                    filepath = inner_dir_path / unique_filename
                    
                    try:
                        with open(filepath, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                            saved_attachments += 1
                            logger.info(
                                f"Saved statement: {unique_filename} => "
                                f"{filepath}"
                            )
                    except IOError as file_error:
                        logger.error(
                            f"Failed to save file {filename}: "
                            f"{str(file_error)}"
                        )
                        continue
                
            except Exception as part_error:
                logger.error(
                    f"Error processing part {part_idx}: {str(part_error)}"
                    f"\n{traceback.format_exc()}"
                )
                continue
        
        logger.info(
            f"Processed {processed_parts} MIME parts, "
            f"saved {saved_attachments} statement attachments"
        )
        return saved_attachments > 0
        
    except Exception as e:
        logger.error(
            f"Error in download_statement_attachments: {str(e)}"
            f"\n{traceback.format_exc()}"
        )
        return False


def process_statement_files(base_folder_path: Path):
    """Process all downloaded statement files"""
    try:
        logger.info("Starting statement file processing")
        processed_count = 0
        
        # Find all PDF files in the download directory
        for pdf_file in base_folder_path.rglob('*.pdf'):
            try:
                logger.info(f"Processing statement file: {pdf_file}")
                
                # Extract data using statement extractor
                with db_context() as db:
                    extractor = StatementExtractor(
                        pdf_path=str(pdf_file),
                        save_excel=False,  # Don't save Excel, extract to DB
                        db_session=db
                    )
                    
                    success = extractor.extract_all_pages()
                    if success:
                        # Save to database
                        db_success = extractor.save_to_database()
                        if db_success:
                            logger.info(
                                f"Successfully processed and saved statement: "
                                f"{pdf_file}"
                            )
                            
                            # Upload PDF to S3 for storage
                            file_key = f"statements/{pdf_file.name}"
                            upload_file(str(pdf_file), file_key, 
                                       is_invoice=False)
                            
                            processed_count += 1
                        else:
                            logger.error(
                                f"Failed to save statement to database: "
                                f"{pdf_file}"
                            )
                    else:
                        logger.error(
                            f"Failed to extract statement data: {pdf_file}"
                        )
                        
            except Exception as file_error:
                logger.error(
                    f"Error processing statement {pdf_file}: {str(file_error)}"
                    f"\n{traceback.format_exc()}"
                )
        
        logger.info(
            f"Statement processing complete. Processed {processed_count} files"
        )
        return processed_count
        
    except Exception as e:
        logger.error(
            f"Error in process_statement_files: {str(e)}"
            f"\n{traceback.format_exc()}"
        )
        return 0


def statement_download_background_task():
    """Main background task for downloading and processing monthly statements 
    using invoice downloader logic"""
    mail = None
    try:
        # Ensure all suppliers exist in database
        with db_context() as db:
            ensure_suppliers_exist(db)
        
        # Setup directory structure (same as invoice downloader)
        try:
            time_window_start = datetime.now(TIMEZONE) - timedelta(minutes=3)
            base_folder = (
                f"{time_window_start.strftime('%d-%b-%Y_%H-%M-%S')} - "
                f"{datetime.now(TIMEZONE).strftime('%d-%b-%Y_%H-%M-%S')}"
            )
            base_folder_path = (Path(INVOICE_DOWNLOAD_FOLDER) / 
                               "statements" / base_folder)
            base_folder_path.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"Created statement download directory: {base_folder_path}"
            )
        except Exception as dir_error:
            logger.error(f"Directory creation failed: {str(dir_error)}")
            raise
        
        # Email processing (same structure as invoice downloader)
        try:
            mail = login()
            filtered_ids = search_statement_emails(mail)
            
            if not filtered_ids:
                logger.info("No new statement emails to process")
                return
            
            logger.info(f"Processing {len(filtered_ids)} statement emails")
            for idx, e_id in enumerate(filtered_ids, 1):
                try:
                    logger.info(
                        f"Processing statement email "
                        f"{idx}/{len(filtered_ids)} - UID: {e_id}"
                    )
                    
                    # Always use BODY.PEEK to never mark emails as read
                    result, response = mail.uid(
                        'fetch', e_id, '(BODY.PEEK[])'
                    )
                    
                    if result != 'OK' or not response or not response[0]:
                        logger.error(f"Failed to fetch email UID {e_id}")
                        continue
                    
                    try:
                        raw_email = response[0][1].decode('utf-8')
                    except UnicodeDecodeError:
                        raw_email = response[0][1].decode('latin-1')
                    
                    email_message = email.message_from_string(raw_email)
                    download_statement_attachments(
                        email_message, base_folder_path
                    )
                    
                except Exception as email_error:
                    logger.error(
                        f"Failed to process email UID {e_id}: "
                        f"{str(email_error)}\n{traceback.format_exc()}"
                    )
                    continue
        
        except Exception as processing_error:
            logger.error(
                f"Email processing failed: {str(processing_error)}"
                f"\n{traceback.format_exc()}"
            )
            raise
        
        # Post-processing (similar to invoice conversion)
        try:
            logger.info("Starting statement processing")
            processed_count = process_statement_files(base_folder_path)
            logger.info(
                f"Statement processing complete. "
                f"Successfully processed {processed_count} files"
            )
        except Exception as post_error:
            logger.error(
                f"Post-processing failed: {str(post_error)}"
                f"\n{traceback.format_exc()}"
            )
            raise
        
        # Clean up temporary files
        try:
            import shutil
            shutil.rmtree(base_folder_path)
            logger.info(f"Cleaned up temporary directory: {base_folder_path}")
        except Exception as cleanup_error:
            logger.warning(
                f"Failed to clean up directory {base_folder_path}: "
                f"{str(cleanup_error)}"
            )
        
    except Exception as main_error:
        logger.error(
            f"Critical error in statement background task: {str(main_error)}"
            f"\n{traceback.format_exc()}"
        )
        raise
    
    finally:
        try:
            if mail:
                logger.info("Closing IMAP connection")
                mail.close()
                mail.logout()
        except Exception as logout_error:
            logger.error(f"Error closing connection: {str(logout_error)}") 