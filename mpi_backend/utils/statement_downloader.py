import imaplib
import email
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from mpi_backend.config import SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, TIMEZONE
from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement
)
from mpi_backend.database import db_context
from mpi_backend.utils.s3_utils import upload_file
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Statement download folder (separate from invoices)
STATEMENT_DOWNLOAD_FOLDER = "mpi_backend/storage/statements"

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
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(SMTP_SERVER)
        mail.login(LOGIN_EMAIL, LOGIN_PWD)
        mail.select('inbox')
        logger.info("Successfully connected to mailbox for statements")
        return mail
    except imaplib.IMAP4.error as imap_error:
        logger.error(f"IMAP connection failed: {str(imap_error)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login: {str(e)}")
        if mail:
            mail.logout()
        raise


def search_statement_emails(mail):
    """Search for statement emails without marking as read"""
    try:
        # Search for emails from the last 30 days with statement keywords
        search_date = (datetime.now(TIMEZONE) - timedelta(days=30)).strftime(
            '%d-%b-%Y'
        )
        logger.info(f"Searching for statement emails since {search_date}")

        # Search for emails with statement keywords in subject
        statement_keywords = [
            'monthly statement',
            'statement',
            'aging report',
            'account statement',
            'monthly aging'
        ]
        
        search_criteria = []
        for keyword in statement_keywords:
            search_criteria.append(f'SUBJECT "{keyword}"')
        
        # Combine with date criteria
        search_query = (
            f'(SINCE {search_date} ({" OR ".join(search_criteria)}))'
        )
        
        result, data = mail.uid('search', None, search_query)
        if result != 'OK':
            logger.error(f"Statement email search failed: {result}")
            return []

        raw_email_ids = data[0].split()
        logger.info(f"Found {len(raw_email_ids)} potential statement emails")

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

                # Check if it's a statement email
                if any(keyword in subject for keyword in statement_keywords):
                    filtered_email_ids.append(email_id)
                    logger.debug(
                        f"Statement email UID {email_id} from: {from_email}, "
                        f"subject: {subject}"
                    )

            except Exception as e:
                logger.error(
                    f"Error processing email UID {email_id}: {str(e)}"
                )
                continue

        logger.info(f"Found {len(filtered_email_ids)} statement emails")
        return filtered_email_ids

    except Exception as e:
        logger.error(f"Error in search_statement_emails: {str(e)}")
        return []


def get_statement_supplier(
    email_subject: str, 
    supplier_email: str
) -> Optional[str]:
    """Detect supplier from statement email"""
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
            return None
    except Exception as e:
        logger.error(f"Supplier detection failed: {str(e)}")
        return None


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
    """Download statement attachments"""
    try:
        processed_files = []
        
        for part in email_message.walk():
            try:
                if (part.get_content_maintype() != 'multipart' and 
                        part.get('Content-Disposition') is not None):
                    
                    # Get supplier info
                    supplier_name = get_statement_supplier(
                        email_message.get('Subject', ''),
                        email_message.get('From', '')
                    )
                    
                    if not supplier_name:
                        logger.warning(
                            "Could not determine supplier, skipping"
                        )
                        continue
                    
                    # Get statement date
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
                            continue
                    
                    # Create supplier folder
                    supplier_path = base_folder_path / supplier_name
                    supplier_path.mkdir(parents=True, exist_ok=True)
                    
                    # Get filename
                    filename = part.get_filename()
                    if not filename:
                        logger.warning("Attachment missing filename, skipping")
                        continue
                    
                    if not filename.lower().endswith(('.pdf', '.PDF')):
                        logger.debug(
                            f"Skipping non-PDF attachment: {filename}"
                        )
                        continue
                    
                    # Create unique filename with date
                    month_year = statement_date.strftime('%Y-%m')
                    unique_filename = (
                        f"{supplier_name}_{month_year}_{filename}"
                    )
                    filepath = supplier_path / unique_filename
                    
                    # Save file
                    with open(filepath, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                        logger.info(
                            f"Saved statement: {unique_filename} => {filepath}"
                        )
                        processed_files.append(str(filepath))
                
            except Exception as part_error:
                logger.error(f"Error processing attachment: {str(part_error)}")
                continue
        
        return processed_files
        
    except Exception as e:
        logger.error(f"Error in download_statement_attachments: {str(e)}")
        return []


def process_statement_file(file_path: str):
    """Process a downloaded statement file"""
    try:
        logger.info(f"Processing statement file: {file_path}")
        
        # Extract data using statement extractor
        with db_context() as db:
            extractor = StatementExtractor(
                pdf_path=file_path,
                save_excel=False,  # Don't save Excel, just extract to DB
                db_session=db
            )
            
            success = extractor.extract_all_pages()
            if success:
                # Save to database
                db_success = extractor.save_to_database()
                if db_success:
                    logger.info(
                        f"Successfully processed and saved statement: "
                        f"{file_path}"
                    )
                    
                    # Upload PDF to S3 for storage
                    file_key = f"statements/{Path(file_path).name}"
                    upload_file(file_path, file_key, is_invoice=False)
                    
                    return True
                else:
                    logger.error(
                        f"Failed to save statement to database: {file_path}"
                    )
            else:
                logger.error(
                    f"Failed to extract statement data: {file_path}"
                )
                
    except Exception as e:
        logger.error(f"Error processing statement {file_path}: {str(e)}")
        
    return False


def statement_download_background_task():
    """Main background task for downloading and processing monthly statements"""
    mail = None
    try:
        # Ensure all suppliers exist in database
        with db_context() as db:
            ensure_suppliers_exist(db)
        
        # Setup directory structure
        timestamp = datetime.now(TIMEZONE).strftime('%Y-%m-%d_%H-%M-%S')
        base_folder = f"statements_{timestamp}"
        base_folder_path = Path(STATEMENT_DOWNLOAD_FOLDER) / base_folder
        base_folder_path.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"Created statement download directory: {base_folder_path}"
        )
        
        # Email processing
        mail = login()
        email_ids = search_statement_emails(mail)
        
        if not email_ids:
            logger.info("No new statement emails to process")
            return
        
        logger.info(f"Processing {len(email_ids)} statement emails")
        processed_files = []
        
        for idx, email_id in enumerate(email_ids, 1):
            try:
                logger.info(
                    f"Processing statement email {idx}/{len(email_ids)} - "
                    f"UID: {email_id}"
                )
                
                # Fetch email (PEEK to not mark as read)
                result, response = mail.uid(
                    'fetch', email_id, '(BODY.PEEK[])'
                )
                
                if result != 'OK' or not response or not response[0]:
                    logger.error(f"Failed to fetch email UID {email_id}")
                    continue
                
                try:
                    raw_email = response[0][1].decode('utf-8')
                except UnicodeDecodeError:
                    raw_email = response[0][1].decode('latin-1')
                
                email_message = email.message_from_string(raw_email)
                
                # Download attachments
                files = download_statement_attachments(
                    email_message, base_folder_path
                )
                processed_files.extend(files)
                
            except Exception as email_error:
                logger.error(
                    f"Failed to process email UID {email_id}: "
                    f"{str(email_error)}"
                )
                continue
        
        # Process downloaded files
        logger.info(
            f"Processing {len(processed_files)} downloaded statement files"
        )
        success_count = 0
        
        for file_path in processed_files:
            try:
                if process_statement_file(file_path):
                    success_count += 1
            except Exception as process_error:
                logger.error(
                    f"Error processing file {file_path}: {str(process_error)}"
                )
        
        logger.info(
            f"Statement processing complete. Successfully processed "
            f"{success_count}/{len(processed_files)} files"
        )
        
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