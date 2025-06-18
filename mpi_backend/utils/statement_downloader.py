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


def extract_supplier_from_filename(filename: str) -> Optional[str]:
    """
    Extract supplier name from statement filename with multiple fallback strategies
    """
    try:
        basename = filename.replace('.pdf', '').replace('.PDF', '')
        
        # Strategy 1: Direct supplier name matching (filename starts with exact supplier name)
        for supplier in STATEMENT_SUPPLIERS:
            if basename.startswith(supplier + '_'):
                logger.info(f"Extracted supplier from filename (direct match): {supplier}")
                return supplier
        
        # Strategy 2: Underscore replacement matching
        for supplier in STATEMENT_SUPPLIERS:
            supplier_underscore = supplier.replace(' ', '_').replace('&', '_')
            if basename.startswith(supplier_underscore + '_'):
                logger.info(f"Extracted supplier from filename (underscore match): {supplier}")
                return supplier
        
        # Strategy 2b: Special case for Y & S with different underscore patterns
        for supplier in STATEMENT_SUPPLIERS:
            if "Y & S" in supplier:
                patterns = [
                    "Y_&_S_Plumbing_Supply",
                    "Y_and_S_Plumbing_Supply", 
                    "Y_S_Plumbing_Supply",
                    "YS_Plumbing_Supply"
                ]
                for pattern in patterns:
                    if basename.startswith(pattern + '_'):
                        logger.info(f"Extracted supplier from filename (Y&S special match): {supplier}")
                        return supplier
        
        # Strategy 3: Pattern matching for special cases
        basename_lower = basename.lower()
        if 'bmw' in basename_lower:
            return "BMW Plumbing Supplies"
        elif 'world_wide' in basename_lower or 'wwps' in basename_lower:
            return "World Wide Plumbing"
        elif 'y_s' in basename_lower or 'ys_' in basename_lower:
            return "Y & S Plumbing Supply"
        elif 'supreme' in basename_lower:
            return "Supreme Plumbing Supply"
        elif 'pyramid' in basename_lower:
            return "Pyramid Plumbing"
        elif 'opus' in basename_lower:
            return "ABC Opus Services"
        elif 'park' in basename_lower:
            return "Park Plumbing Supply"
        elif 'gotham' in basename_lower:
            return "Gotham Plumbing Supply"
        elif 'webb' in basename_lower:
            return "FW Webb Plumbing Supply"
        elif 'flow' in basename_lower or 'mark' in basename_lower:
            return "Flow Mark Plumbing Supply"
        
        logger.warning(f"Could not extract supplier from filename: {filename}")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting supplier from filename {filename}: {str(e)}")
        return None


def process_statement_files(base_folder_path: Path):
    """Process all downloaded statement files with improved supplier detection"""
    try:
        logger.info("Starting statement file processing with improved supplier detection")
        processed_count = 0
        
        # Find all PDF files in the download directory
        for pdf_file in base_folder_path.rglob('*.pdf'):
            try:
                logger.info(f"Processing statement file: {pdf_file}")
                
                # BULLETPROOF supplier name extraction with multiple strategies
                path_supplier = None
                filename_supplier = None
                final_supplier = None
                
                # Strategy 1: Extract from file path directory structure
                if len(pdf_file.parts) >= 3:
                    supplier_dir = pdf_file.parts[-3]  # supplier_name directory
                    if supplier_dir in STATEMENT_SUPPLIERS:
                        path_supplier = supplier_dir
                        logger.info(f"📁 Path extracted supplier: {path_supplier}")
                
                # Strategy 2: Extract from filename (FIXED LOGIC)
                filename_supplier = extract_supplier_from_filename(pdf_file.name)
                if filename_supplier:
                    logger.info(f"📄 Filename extracted supplier: {filename_supplier}")
                
                # Strategy 3: Determine final supplier with priority
                if path_supplier and filename_supplier and path_supplier == filename_supplier:
                    final_supplier = path_supplier
                    logger.info(f"🎯 Supplier confirmed by both path and filename: {final_supplier}")
                elif path_supplier:
                    final_supplier = path_supplier
                    logger.info(f"🎯 Using path-extracted supplier: {final_supplier}")
                elif filename_supplier:
                    final_supplier = filename_supplier
                    logger.info(f"🎯 Using filename-extracted supplier: {final_supplier}")
                else:
                    logger.error(f"CRITICAL: Could not extract supplier name for {pdf_file}")
                    logger.error(f"Path parts: {pdf_file.parts}")
                    logger.error(f"Filename: {pdf_file.name}")
                    logger.error("This statement will use unreliable PDF OCR detection!")
                
                # Log comprehensive supplier information for verification
                logger.info(f"SUPPLIER DETECTION SUMMARY:")
                logger.info(f"Path supplier: {path_supplier}")
                logger.info(f"Filename supplier: {filename_supplier}")
                logger.info(f"Final supplier: {final_supplier}")
                
                if not final_supplier:
                    logger.warning(f"Could not extract supplier name for {pdf_file}, will rely on PDF detection")
                
                # Extract data using statement extractor with supplier name
                with db_context() as db:
                    extractor = StatementExtractor(
                        pdf_path=str(pdf_file),
                        save_to_db=True,  # Save to database
                        save_to_excel=False,  # Don't save Excel
                        db_session=db,
                        supplier_name=final_supplier  # Pass the final determined supplier
                    )
                    
                    # Verify what supplier the extractor is actually using
                    detected_supplier = extractor.detect_supplier()
                    logger.info(f"🔍 StatementExtractor detected supplier: {detected_supplier}")
                    
                    # Critical validation: Check for supplier mismatch
                    if final_supplier and detected_supplier != final_supplier:
                        logger.error(f"🚨 CRITICAL SUPPLIER MISMATCH DETECTED!")
                        logger.error(f"   Expected (from email/path): {final_supplier}")
                        logger.error(f"   StatementExtractor using: {detected_supplier}")
                        logger.error(f"   PDF File: {pdf_file}")
                        # This could indicate a serious issue
                    
                    success = extractor.extract_all_pages()
                    if success:
                        # Save to database
                        db_success = extractor.save_to_database()
                        if db_success:
                            logger.info(f"✅ Successfully processed and saved statement: {pdf_file}")
                            logger.info(f"   Final supplier used: {detected_supplier}")
                            
                            # Upload PDF to S3 for storage
                            file_key = f"statements/{pdf_file.name}"
                            upload_file(str(pdf_file), file_key, 
                                       is_invoice=True)
                            
                            processed_count += 1
                        else:
                            logger.error(f"Failed to save statement to database: {pdf_file}")
                    else:
                        logger.error(f"Failed to extract statement data: {pdf_file}")
                        
            except Exception as file_error:
                logger.error(
                    f"Error processing statement {pdf_file}: {str(file_error)}"
                    f"\n{traceback.format_exc()}"
                )
        
        logger.info(f"Statement processing complete. Processed {processed_count} files")
        return processed_count
        
    except Exception as e:
        logger.error(
            f"Error in process_statement_files: {str(e)}"
            f"\n{traceback.format_exc()}"
        )
        return 0


def statement_download_background_task():
    """ENHANCED: Statement download with migrate-all priority awareness"""
    # ABSOLUTE PRIORITY: Check if migrate-all operation is active
    try:
        from mpi_backend.utils.quickbooks_priority import is_migrate_all_active
        if is_migrate_all_active():
            logger.info("Statement download paused - MIGRATE-ALL has absolute priority")
            return
    except ImportError:
        pass
    
    # FALLBACK: Check if any QuickBooks export is active
    try:
        from mpi_backend.utils.quickbooks_priority import is_qb_export_active
        if is_qb_export_active():
            logger.info("Statement download paused - QuickBooks priority export in progress")
            return
    except ImportError:
        pass
    
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