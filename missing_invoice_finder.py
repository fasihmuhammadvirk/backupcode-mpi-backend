#!/usr/bin/env python3
"""
Missing Invoice Finder and Email Search Script

This script:
1. Reads missing reference numbers from missing_invoices.xlsx file
2. Searches emails for missing reference numbers
3. Downloads and processes attachments like regular emails
4. Creates summary Excel with email details
5. Adds processed invoices to database

Usage:
    python missing_invoice_finder.py
"""

import os
import pandas as pd
import logging
import imaplib
import email
import email.utils
from pathlib import Path
from datetime import datetime
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font
import traceback
import time
import signal
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Load environment variables
load_dotenv()

# Import existing invoice processing functions
try:
    from mpi_backend.utils.invoice_convertor import (
        convert_invoice_for_email
    )
    from mpi_backend.utils.extracted_data_processor import (
        process_extracted_data
    )
    INVOICE_PROCESSING_AVAILABLE = True
except ImportError:
    INVOICE_PROCESSING_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('missing_invoice_finder.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class MissingInvoiceFinder:
    def __init__(self, high_speed_mode=True):
        """Initialize the missing invoice finder"""
        self.missing_file = "missing_invoices.xlsx"
        self.summary_file = "invoice_summary.xlsx"
        self.high_speed_mode = high_speed_mode
        
        # Email connection parameters
        self.smtp_server = os.getenv("SMTP_SERVER")
        self.email_address = os.getenv("LOGIN_EMAIL")
        self.email_password = os.getenv("LOGIN_PWD")
        
        # Create directories
        self.download_dir = Path("missing_invoice_attachments")
        self.download_dir.mkdir(exist_ok=True)
        self.attachments_folder = self.download_dir  # Alias for compatibility
        
        # Also create storage directory for additional copy
        self.storage_dir = Path("storage/missing_invoice_attachments")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Robust error handling and recovery settings
        self.max_retries = 5
        self.retry_delay = 3
        self.operation_timeout = 30  # seconds
        self.connection_timeout = 120  # seconds - increased for stability
        self.max_consecutive_errors = 10
        self.consecutive_errors = 0
        self.should_stop = False
        
        # Additional safeguards to prevent getting stuck
        self.max_processing_time_per_ref = 300  # 5 minutes max per reference
        self.last_activity_time = time.time()
        self.heartbeat_interval = 30  # Check every 30 seconds
        self.max_batch_time = 7200  # 2 hours max per batch (increased for large batches)
        self.batch_start_time = time.time()
        
        # Long session stability (for 4000+ invoices)
        self.connection_start_time = time.time()
        self.max_connection_time = 3600  # 1 hour max per connection
        self.session_refresh_interval = 500  # Refresh connection every 500 invoices
        self.invoices_processed_in_session = 0
        
        # Performance optimization settings
        self.batch_size = 500  # Process invoices in larger batches for speed
        self.current_batch = []
        self.batch_number = 0
        
        # Speed optimization settings based on mode
        if self.high_speed_mode:
            self.parallel_processing = False  # Disable parallel to prevent overwhelming Gmail
            self.max_workers = 1  # Single worker to prevent connection issues
            self.quick_mode = True  # Skip non-essential processing
            self.minimal_delays = False  # Add delays to prevent rate limiting
            self.batch_size = 1000  # Smaller batches to prevent timeouts
            self.operation_timeout = 30  # Longer timeouts for stability
            self.max_retries = 3  # More retries for reliability
            logger.info("🚀 HIGH SPEED MODE ENABLED - Optimized for stability and speed")
        else:
            self.parallel_processing = False
            self.max_workers = 2
            self.quick_mode = False
            self.minimal_delays = False
            logger.info("🐌 Standard mode enabled")
        
        # Progress tracking and checkpoint system
        self.progress_file = "missing_invoice_progress.json"
        self.checkpoint_interval = 50  # Save progress every 50 references
        self.last_checkpoint = 0
        
        # Statistics tracking - enhanced for comprehensive reporting
        self.stats = {
            'missing_ref_numbers': 0,
            'emails_found': 0,
            'attachments_downloaded': 0,
            'emails_processed': 0,
            'errors': 0,
            'invoices_processed': 0,
            'database_records_added': 0,
            'database_records_updated': 0,
            'database_duplicates_found': 0,
            'missing_invoices_found_in_email': 0,
            'missing_invoices_not_found_in_email': 0,
            'total_mailboxes_searched': 0,
            'total_search_patterns_used': 0,
            'found_in_inbox': 0,
            'found_in_archive': 0,
            'archive_searches_skipped': 0,
            'connection_retries': 0,
            'operation_timeouts': 0,
            'recoveries_attempted': 0,
            'recoveries_successful': 0,
            'processing_start_time': time.time(),
            'batches_completed': 0,
            'average_time_per_batch': 0,
            'estimated_completion_time': None
        }
        
        self.missing_ref_numbers = []
        self.email_results = []
        self.mail = None
        # Track invoices not found in any email
        self.missing_invoices_not_found = []
        # Store email details by reference number
        self.email_details_by_ref = {}
        
        # Persistent summary data (never cleaned up for complete excel summary)
        self.persistent_summary_data = []
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.warning(f"Received signal {signum}, initiating graceful shutdown...")
            self.should_stop = True
            self._save_progress()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    @contextmanager
    def timeout_context(self, seconds):
        """Context manager for operation timeouts"""
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {seconds} seconds")
        
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    
    def _save_progress(self):
        """Save current progress to file for recovery"""
        try:
            import json
            progress_data = {
                'processed_refs': list(self.email_details_by_ref.keys()) if hasattr(self, 'email_details_by_ref') else [],
                'failed_refs': getattr(self, 'missing_invoices_not_found', []),
                'current_batch': getattr(self, 'current_batch', []),
                'batch_number': getattr(self, 'batch_number', 0),
                'stats': self.stats,
                'timestamp': datetime.now().isoformat(),
                'last_checkpoint': self.last_checkpoint,
                'total_refs': getattr(self, 'missing_ref_numbers', []),
                'remaining_refs': self._get_remaining_refs(),
                'processing_state': 'in_progress'
            }
            with open(self.progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
            logger.info(f"Progress saved to {self.progress_file}")
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")
    
    def _get_remaining_refs(self):
        """Get list of remaining reference numbers to process"""
        try:
            if not hasattr(self, 'missing_ref_numbers') or not self.missing_ref_numbers:
                return []
            
            processed = set()
            if hasattr(self, 'email_details_by_ref'):
                processed.update(self.email_details_by_ref.keys())
            if hasattr(self, 'missing_invoices_not_found'):
                processed.update(self.missing_invoices_not_found)
            
            return [ref for ref in self.missing_ref_numbers if ref not in processed]
        except Exception as e:
            logger.error(f"Error getting remaining refs: {e}")
            return []
    
    def _load_progress(self):
        """Load progress from file for recovery"""
        try:
            import json
            if Path(self.progress_file).exists():
                with open(self.progress_file, 'r') as f:
                    progress_data = json.load(f)
                
                # Validate progress data
                if self._validate_progress_data(progress_data):
                    logger.info(f"✅ Loaded progress from {self.progress_file}")
                    logger.info(f"📊 Previously processed: {len(progress_data.get('processed_refs', []))} refs")
                    logger.info(f"❌ Previously failed: {len(progress_data.get('failed_refs', []))} refs")
                    logger.info(f"📦 Last batch: {progress_data.get('batch_number', 0)}")
                    logger.info(f"⏰ Last saved: {progress_data.get('timestamp', 'Unknown')}")
                    return progress_data
                else:
                    logger.warning("⚠️ Progress data validation failed, starting fresh")
                    return None
        except Exception as e:
            logger.error(f"Failed to load progress: {e}")
        return None
    
    def _validate_progress_data(self, progress_data):
        """Validate loaded progress data"""
        try:
            required_fields = ['processed_refs', 'stats', 'timestamp']
            for field in required_fields:
                if field not in progress_data:
                    logger.warning(f"Missing required field: {field}")
                    return False
            
            # Check if stats is a dictionary
            if not isinstance(progress_data['stats'], dict):
                logger.warning("Stats field is not a dictionary")
                return False
            
            # Check if processed_refs is a list
            if not isinstance(progress_data['processed_refs'], list):
                logger.warning("Processed_refs field is not a list")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error validating progress data: {e}")
            return False
    
    def _check_should_stop(self):
        """Check if we should stop processing"""
        if self.should_stop:
            logger.warning("Stop signal received, halting processing")
            return True
        
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.error(f"Too many consecutive errors ({self.consecutive_errors}), stopping")
            return True
        
        # Check if we've been stuck too long on a single reference
        current_time = time.time()
        if current_time - self.last_activity_time > self.max_processing_time_per_ref:
            logger.error(f"Processing stuck for {self.max_processing_time_per_ref} seconds, stopping")
            return True
        
        # Check if batch is taking too long
        if hasattr(self, 'batch_start_time'):
            batch_elapsed = current_time - self.batch_start_time
            if batch_elapsed > self.max_batch_time:
                logger.error(f"Batch taking too long ({batch_elapsed:.1f}s), stopping")
                return True
        
        return False
    
    def _update_heartbeat(self):
        """Update the last activity time to prevent timeout"""
        self.last_activity_time = time.time()
    
    def _check_and_refresh_connection(self):
        """Check if connection needs refresh for long sessions (4000+ invoices)"""
        try:
            current_time = time.time()
            connection_age = current_time - self.connection_start_time
            
            # Check if we need to refresh based on time or invoice count
            needs_refresh = (
                connection_age > self.max_connection_time or  # Connection too old
                self.invoices_processed_in_session >= self.session_refresh_interval  # Too many invoices
            )
            
            if needs_refresh:
                logger.warning(f"🔄 Connection refresh needed - Age: {connection_age/60:.1f}min, Invoices: {self.invoices_processed_in_session}")
                
                # Attempt to refresh the connection
                if self._refresh_gmail_connection():
                    logger.info(f"✅ Connection refreshed successfully")
                    # Reset counters
                    self.connection_start_time = time.time()
                    self.invoices_processed_in_session = 0
                    return True
                else:
                    logger.error(f"❌ Connection refresh failed")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking connection: {e}")
            return False
    
    def _refresh_gmail_connection(self):
        """Refresh Gmail connection to prevent timeouts in long sessions"""
        try:
            logger.info(f"🔄 Refreshing Gmail connection for long session stability...")
            
            # Safely close existing connection
            if hasattr(self, 'mail') and self.mail:
                try:
                    self.mail.logout()
                except:
                    pass  # Ignore logout errors
            
            # Re-establish connection
            success = self.connect_to_email()
            if success:
                logger.info(f"✅ Gmail connection refreshed successfully")
                return True
            else:
                logger.error(f"❌ Failed to refresh Gmail connection")
                return False
                
        except Exception as e:
            logger.error(f"Error refreshing connection: {e}")
            return False
    
    def _handle_gmail_timeout(self):
        """Handle Gmail connection timeouts with progressive backoff"""
        try:
            logger.warning("🔄 Gmail connection timeout detected - attempting recovery...")
            
            # Progressive backoff delays
            backoff_delays = [10, 30, 60, 120, 300]  # 10s, 30s, 1m, 2m, 5m
            
            for attempt, delay in enumerate(backoff_delays, 1):
                logger.info(f"⏳ Attempt {attempt}/5 - Waiting {delay} seconds for Gmail recovery...")
                time.sleep(delay)
                
                try:
                    # Force reconnection
                    if hasattr(self, 'mail') and self.mail:
                        try:
                            self.mail.logout()
                        except:
                            pass
                    
                    # Reconnect
                    self.connect_to_email()
                    self._update_heartbeat()
                    
                    logger.info(f"✅ Gmail connection recovered on attempt {attempt}")
                    return True
                    
                except Exception as e:
                    logger.warning(f"⚠️ Recovery attempt {attempt} failed: {e}")
                    continue
            
            logger.error("❌ All Gmail recovery attempts failed")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error in Gmail timeout handler: {e}")
            return False
    
    def _detect_stuck_process(self):
        """Detect if the process is stuck and needs recovery"""
        try:
            current_time = time.time()
            
            # Check if we've been inactive too long
            if current_time - self.last_activity_time > self.max_processing_time_per_ref:
                logger.warning(f"⚠️ Process appears stuck - no activity for {self.max_processing_time_per_ref}s")
                return True
            
            # Check if batch is taking too long
            if hasattr(self, 'batch_start_time'):
                batch_elapsed = current_time - self.batch_start_time
                if batch_elapsed > self.max_batch_time:
                    logger.warning(f"⚠️ Batch appears stuck - running for {batch_elapsed:.1f}s")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error detecting stuck process: {e}")
            return False
    
    def _recover_from_stuck(self):
        """Attempt to recover from a stuck state"""
        try:
            logger.info("🔄 Attempting to recover from stuck state...")
            
            # Save current progress
            self._save_progress()
            
            # Try to reconnect to email
            if self.mail:
                try:
                    self.mail.close()
                    self.mail.logout()
                except:
                    pass
                self.mail = None
            
            # Reconnect
            if self.connect_to_email():
                logger.info("✅ Successfully reconnected to email server")
                self.consecutive_errors = 0
                return True
            else:
                logger.error("❌ Failed to reconnect to email server")
                return False
                
        except Exception as e:
            logger.error(f"Error during recovery: {e}")
            return False
    
    def _cleanup_memory(self):
        """Clean up memory after each batch to optimize memory usage"""
        try:
            import gc
            import psutil
            import os
            
            # Get current memory usage
            process = psutil.Process(os.getpid())
            memory_before = process.memory_info().rss / 1024 / 1024  # MB
            
            # Clear email details for processed batches
            if hasattr(self, 'email_details_by_ref'):
                # Keep only the last batch in memory
                if len(self.email_details_by_ref) > self.batch_size:
                    # Remove old batches (keep only recent ones)
                    refs_to_remove = list(self.email_details_by_ref.keys())[:-self.batch_size]
                    for ref in refs_to_remove:
                        del self.email_details_by_ref[ref]
            
            # Clear email results for processed batches
            if hasattr(self, 'email_results') and len(self.email_results) > self.batch_size * 2:
                # Keep only recent results
                self.email_results = self.email_results[-self.batch_size:]
            
            # Clear any temporary variables
            if hasattr(self, 'current_batch'):
                self.current_batch.clear()
            
            # Force garbage collection
            gc.collect()
            
            # Get memory usage after cleanup
            memory_after = process.memory_info().rss / 1024 / 1024  # MB
            memory_freed = memory_before - memory_after
            
            logger.info(f"🧹 Memory cleanup: {memory_before:.1f}MB → {memory_after:.1f}MB "
                       f"(freed {memory_freed:.1f}MB)")
            
        except ImportError:
            # psutil not available, just do basic cleanup
            import gc
            gc.collect()
            logger.debug("Memory cleanup completed (basic)")
        except Exception as e:
            logger.warning(f"Error during memory cleanup: {e}")
    
    def _process_batch(self, batch_refs, mailboxes):
        """Process a batch of reference numbers"""
        try:
            # Reset batch timer
            self.batch_start_time = time.time()
            logger.info(f"🔄 Processing batch {self.batch_number + 1} with {len(batch_refs)} references")
            
            batch_processed = []
            batch_failed = []
            
            for i, ref_no in enumerate(batch_refs, 1):
                # Check if we should stop
                if self._check_should_stop():
                    logger.warning("Stop signal received during batch processing")
                    break
                
                # Check if process is stuck and try to recover
                if self._detect_stuck_process():
                    logger.warning("Process appears stuck, attempting recovery...")
                    if self._recover_from_stuck():
                        logger.info("Recovery successful, continuing...")
                    else:
                        logger.error("Recovery failed, stopping batch")
                        break
                
                # Check and refresh connection for long sessions (prevents 4000+ invoice timeouts)
                if not self._check_and_refresh_connection():
                    logger.error("Connection refresh failed, attempting recovery...")
                    if not self.connect_to_email():
                        logger.error("Failed to recover connection, stopping batch")
                        break
                
                # Increment session counter
                self.invoices_processed_in_session += 1
                
                # Ensure Gmail connection is still active before each reference
                if not self.mail or hasattr(self.mail, 'state') and self.mail.state == 'LOGOUT':
                    logger.warning(f"Gmail connection lost at reference {i}, reconnecting...")
                    try:
                        self.connect_to_email()
                        logger.info("Gmail reconnection successful")
                    except Exception as e:
                        logger.error(f"Failed to reconnect to Gmail: {e}")
                        break
                
                logger.info(f"📋 [Batch {self.batch_number + 1}] [{i}/{len(batch_refs)}] Processing: {ref_no}")
                self._update_heartbeat()
                
                try:
                    # Use timeout for the entire reference processing
                    with self.timeout_context(self.operation_timeout):
                        # Step 1: Search for emails containing this ref
                        self._update_heartbeat()
                        email_ids, email_mailbox_map = self.search_single_reference(ref_no, mailboxes)
                        
                        if email_ids:
                            logger.info(f"📧 Found {len(email_ids)} emails for ref {ref_no}")
                            self.stats['missing_invoices_found_in_email'] += 1
                            
                            # Step 2: Process emails and download attachments
                            self._update_heartbeat()
                            success = self.process_emails_for_reference(ref_no, email_ids, email_mailbox_map)
                            
                            if success:
                                batch_processed.append(ref_no)
                                self.consecutive_errors = 0
                                logger.info(f"✅ Successfully processed ref {ref_no}")
                                
                                # Update summary every 100 invoices processed
                                total_processed = len(batch_processed)
                                if total_processed % 100 == 0:
                                    try:
                                        logger.info(f"📊 Updating invoice_summary.xlsx at {total_processed} invoices processed in this batch")
                                        self.create_summary_excel()
                                        logger.info(f"✅ Summary updated successfully")
                                    except Exception as e:
                                        logger.error(f"❌ Error updating summary: {e}")
                                        # Continue processing even if summary fails
                            else:
                                batch_failed.append(ref_no)
                                self._handle_error(f"Failed to process ref {ref_no}", "email_processing")
                        else:
                            logger.info(f"❌ No emails found for ref {ref_no}")
                            self.missing_invoices_not_found.append(ref_no)
                            self.stats['missing_invoices_not_found_in_email'] += 1
                            batch_failed.append(ref_no)
                            
                            # Add to persistent summary data for complete excel summary
                            self.persistent_summary_data.append({
                                'Reference_Number': ref_no,
                                'Status': 'Not Found in Email',
                                'Email_ID': '',
                                'Subject': '',
                                'Sender': '',
                                'Date': '',
                                'Mailbox': '',
                                'Folder_Path': '',
                                'Attachments_Found': 0,
                                'Attachments_Downloaded': 0,
                                'Attachment_Files': '',
                                'Search_Status': 'NOT_FOUND'
                            })
                            self.consecutive_errors = 0
                            
                except TimeoutError:
                    logger.error(f"⏰ Timeout processing ref {ref_no} after {self.operation_timeout}s")
                    self.stats['operation_timeouts'] += 1
                    self._handle_error(f"Timeout processing ref {ref_no}", "timeout")
                    batch_failed.append(ref_no)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing ref {ref_no}: {e}")
                    self._handle_error(e, f"processing_ref_{ref_no}")
                    self.missing_invoices_not_found.append(ref_no)
                    self.stats['missing_invoices_not_found_in_email'] += 1
                    batch_failed.append(ref_no)
                    continue
                
                # Add delay to prevent overwhelming Gmail servers
                self._update_heartbeat()
                time.sleep(0.5)  # Increased delay to prevent connection timeouts
            
            # Process downloaded attachments for this batch
            try:
                logger.info(f"📎 Processing attachments for batch {self.batch_number + 1}")
                self.process_downloaded_attachments()
                logger.info(f"✅ Attachments processed for batch {self.batch_number + 1}")
            except Exception as e:
                logger.error(f"❌ Error processing attachments for batch {self.batch_number + 1}: {e}")
            
            # Create summary for this batch
            try:
                logger.info(f"📊 Creating summary for batch {self.batch_number + 1}")
                self.create_summary_excel()
                logger.info(f"✅ Summary created for batch {self.batch_number + 1}")
            except Exception as e:
                logger.error(f"❌ Error creating summary for batch {self.batch_number + 1}: {e}")
            
            # Clean up memory after batch
            self._cleanup_memory()
            
            # Update performance statistics
            batch_time = time.time() - self.batch_start_time
            self.stats['batches_completed'] += 1
            self.stats['average_time_per_batch'] = (
                (self.stats['average_time_per_batch'] * (self.stats['batches_completed'] - 1) + batch_time) / 
                self.stats['batches_completed']
            )
            
            # Estimate completion time
            remaining_batches = ((len(self.missing_ref_numbers) - (self.batch_number * self.batch_size)) / self.batch_size)
            estimated_remaining_time = remaining_batches * self.stats['average_time_per_batch']
            self.stats['estimated_completion_time'] = time.time() + estimated_remaining_time
            
            logger.info(f"📊 Batch {self.batch_number + 1} Summary:")
            logger.info(f"  ✅ Successfully processed: {len(batch_processed)} refs")
            logger.info(f"  ❌ Failed: {len(batch_failed)} refs")
            logger.info(f"  ⏱️ Batch time: {batch_time:.1f}s")
            logger.info(f"  🚀 Average time per batch: {self.stats['average_time_per_batch']:.1f}s")
            if estimated_remaining_time > 0:
                logger.info(f"  ⏰ Estimated remaining time: {estimated_remaining_time/60:.1f} minutes")
            
            return batch_processed, batch_failed
            
        except Exception as e:
            logger.error(f"Error processing batch {self.batch_number + 1}: {e}")
            self._handle_error(e, f"batch_processing_{self.batch_number + 1}")
            return [], batch_refs
    
    def _handle_error(self, error, operation="operation"):
        """Handle errors with retry logic and recovery"""
        self.stats['errors'] += 1
        self.consecutive_errors += 1
        
        logger.error(f"Error in {operation}: {error}")
        
        # Check if it's a connection error
        if any(keyword in str(error).lower() for keyword in ['ssl', 'socket', 'eof', 'connection', 'timeout']):
            logger.warning("Connection error detected, attempting recovery...")
            self.stats['recoveries_attempted'] += 1
            
            if self._recover_connection():
                self.stats['recoveries_successful'] += 1
                self.consecutive_errors = 0  # Reset on successful recovery
                logger.info("Connection recovery successful")
            else:
                logger.error("Connection recovery failed")
        
        # If we have too many consecutive errors, try a full reconnection
        if self.consecutive_errors >= 3:
            logger.warning("Multiple consecutive errors, attempting full reconnection...")
            if self.connect_to_email():
                self.consecutive_errors = 0
                logger.info("Full reconnection successful")
            else:
                logger.error("Full reconnection failed")
    
    def _recover_connection(self):
        """Attempt to recover email connection"""
        try:
            if self.mail:
                try:
                    self.mail.close()
                except:
                    pass
                try:
                    self.mail.logout()
                except:
                    pass
            
            time.sleep(self.retry_delay)
            return self.connect_to_email()
        except Exception as e:
            logger.error(f"Connection recovery failed: {e}")
            return False
        
    def validate_environment(self):
        """Validate required files and environment variables"""
        # Check if missing invoices file exists
        if not Path(self.missing_file).exists():
            logger.error(f"Missing invoices file '{self.missing_file}' not found!")
            return False
            
        # Check email environment
        required_email_vars = ["SMTP_SERVER", "LOGIN_EMAIL", "LOGIN_PWD"]
        missing_email_vars = [var for var in required_email_vars 
                             if not os.getenv(var)]
        
        if missing_email_vars:
            logger.error(f"Missing email environment variables: "
                        f"{', '.join(missing_email_vars)}")
            return False
            
        return True
    
    
    def read_missing_invoices_file(self):
        """Read the existing missing_invoices.xlsx file"""
        try:
            if not Path(self.missing_file).exists():
                logger.error(f"Missing invoices file '{self.missing_file}' not found!")
                return []
            
            logger.info(f"Reading existing missing invoices file: {self.missing_file}")
            df = pd.read_excel(self.missing_file)
            
            # Extract reference numbers from the file
            ref_numbers = []
            if 'Reference_Number' in df.columns:
                ref_numbers = df['Reference_Number'].dropna().astype(str).str.strip().tolist()
            elif 'Ref. #' in df.columns:
                ref_numbers = df['Ref. #'].dropna().astype(str).str.strip().tolist()
            else:
                # Try to find reference numbers in any column
                for col in df.columns:
                    if 'ref' in col.lower() or 'reference' in col.lower():
                        ref_numbers = df[col].dropna().astype(str).str.strip().tolist()
                        break
            
            logger.info(f"Found {len(ref_numbers)} missing reference numbers in file")
            return ref_numbers
            
        except Exception as e:
            logger.error(f"Error reading missing invoices file: {e}")
            return []
    
    
    
    
    def connect_to_email(self):
        """Establish IMAP connection"""
        try:
            logger.info("Connecting to email server...")
            self.mail = imaplib.IMAP4_SSL(self.smtp_server)
            self.mail.login(self.email_address, self.email_password)
            logger.info("Successfully connected to email server")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to email server: {e}")
            return False
    
    def reconnect_email(self):
        """Reconnect to email server with cleanup"""
        try:
            if self.mail:
                try:
                    self.mail.close()
                    self.mail.logout()
                except:
                    pass  # Ignore errors during cleanup
                self.mail = None
            
            return self.connect_to_email()
        except Exception as e:
            logger.error(f"Failed to reconnect to email server: {e}")
            return False
    
    def get_all_mailboxes(self):
        """Get list of specific mailboxes - INBOX first, then All Mail"""
        try:
            # Focus on specific mailboxes to avoid SSL errors
            # Priority order: INBOX first, then Archive options with proper encoding
            target_mailboxes = ['INBOX', '"[Gmail]/All Mail"', '[Gmail]/All Mail', 'Archive', '"[Gmail]/Archive"', '[Gmail]/Archive']
            available_mailboxes = []
            
            try:
                result, mailboxes = self.mail.list()
                if result == 'OK':
                    mailbox_list = []
                    for mailbox in mailboxes:
                        mailbox_str = mailbox.decode('utf-8')
                        # Extract mailbox name properly
                        if '"' in mailbox_str:
                            parts = mailbox_str.split('"')
                            if len(parts) >= 2:
                                mailbox_name = parts[-2]
                            else:
                                mailbox_name = 'INBOX'
                        else:
                            mailbox_name = 'INBOX'
                        mailbox_list.append(mailbox_name)
                    
                    logger.info(f"Found mailboxes: {mailbox_list}")
                    
                    # Check which target mailboxes are available
                    for target in target_mailboxes:
                        if target in mailbox_list:
                            available_mailboxes.append(target)
                            logger.info(f"Found target mailbox: {target}")
                        else:
                            # Try case-insensitive matching
                            for mb in mailbox_list:
                                if target.lower() in mb.lower() or mb.lower() in target.lower():
                                    available_mailboxes.append(mb)
                                    logger.info(f"Found similar mailbox: {mb} (for {target})")
                                    break
            except Exception as e:
                logger.warning(f"Error listing mailboxes: {e}")
            
            # Fallback to basic mailboxes if listing fails
            if not available_mailboxes:
                available_mailboxes = ['INBOX']
                # Try to find All Mail if it exists
                try:
                    result = self.mail.select('[Gmail]/All Mail')
                    if result[0] == 'OK':
                        available_mailboxes.append('[Gmail]/All Mail')
                except Exception:
                    pass
            
            # Ensure INBOX is first, All Mail is second
            ordered_mailboxes = []
            if 'INBOX' in available_mailboxes:
                ordered_mailboxes.append('INBOX')
            if '[Gmail]/All Mail' in available_mailboxes and '[Gmail]/All Mail' not in ordered_mailboxes:
                ordered_mailboxes.append('[Gmail]/All Mail')
            
            # Add any other mailboxes found
            for mb in available_mailboxes:
                if mb not in ordered_mailboxes:
                    ordered_mailboxes.append(mb)
            
            logger.info("Using mailboxes in order: %s", ordered_mailboxes)
            return ordered_mailboxes
            
        except Exception as e:
            logger.error(f"Error getting mailboxes: {e}")
            return ['INBOX']
    
    def process_missing_invoices_in_batches(self, missing_ref_numbers):
        """Process missing invoices in batches of 100 for memory optimization with robust resume capability"""
        try:
            logger.info(f"🔄 Processing {len(missing_ref_numbers)} missing reference numbers in batches of {self.batch_size}...")
            
            # Load previous progress if available
            progress_data = self._load_progress()
            if progress_data:
                # Restore state from previous run
                already_processed = set(progress_data.get('processed_refs', []))
                already_failed = set(progress_data.get('failed_refs', []))
                self.batch_number = progress_data.get('batch_number', 0)
                
                # Restore stats if available
                if 'stats' in progress_data:
                    self.stats.update(progress_data['stats'])
                
                logger.info(f"🔄 Resuming from previous run:")
                logger.info(f"  ✅ Already processed: {len(already_processed)} refs")
                logger.info(f"  ❌ Already failed: {len(already_failed)} refs")
                logger.info(f"  📦 Last batch: {self.batch_number}")
                
                # Restore missing invoices not found list
                self.missing_invoices_not_found = list(already_failed)
            else:
                already_processed = set()
                already_failed = set()
                logger.info("🆕 Starting fresh - no previous progress found")
            
            mailboxes = self.get_all_mailboxes()
            self.stats['total_mailboxes_searched'] = len(mailboxes)
            
            # Filter out already processed references
            remaining_refs = [ref for ref in missing_ref_numbers 
                            if ref not in already_processed and ref not in already_failed]
            logger.info(f"📋 {len(remaining_refs)} references remaining to process")
            
            if not remaining_refs:
                logger.info("🎉 All references have been processed! Nothing to do.")
                return list(already_processed), list(already_failed)
            
            all_processed_refs = list(already_processed)  # Include already processed
            all_failed_refs = list(already_failed)  # Include already failed
            
            # Process in batches
            total_batches = (len(remaining_refs) + self.batch_size - 1) // self.batch_size
            logger.info(f"📦 Will process {total_batches} batches of up to {self.batch_size} references each")
            
            # Estimate total processing time  
            estimated_total_time = total_batches * 60  # Estimate 60 minutes per batch (more realistic)
            logger.info(f"⏰ Estimated total processing time: {estimated_total_time:.1f} minutes")
            logger.info(f"🎯 Target: Complete all {len(remaining_refs)} invoices (may take 2-3 hours for 5000+)")
            
            for batch_start in range(0, len(remaining_refs), self.batch_size):
                batch_end = min(batch_start + self.batch_size, len(remaining_refs))
                batch_refs = remaining_refs[batch_start:batch_end]
                
                # Check if we should stop
                if self._check_should_stop():
                    logger.warning("Processing stopped due to error threshold or stop signal")
                    break
                
                logger.info(f"🚀 Starting batch {self.batch_number + 1}/{total_batches} "
                          f"({len(batch_refs)} references)")
                
                # Save progress before starting batch (in case it gets stuck)
                self._save_progress()
                
                # Process this batch
                batch_processed, batch_failed = self._process_batch(batch_refs, mailboxes)
                
                # Update overall results
                all_processed_refs.extend(batch_processed)
                all_failed_refs.extend(batch_failed)
                
                # Update batch number
                self.batch_number += 1
                
                # Save progress after each batch
                self._save_progress()
                
                # Add delay between batches to prevent overwhelming Gmail
                if batch_end < len(remaining_refs):  # Not the last batch
                    logger.info(f"⏳ Waiting 5 seconds before next batch to prevent timeouts...")
                    time.sleep(5)  # Increased to 5 seconds to allow Gmail to recover
            
            # Mark processing as completed and clean up progress file
            try:
                import json
                if Path(self.progress_file).exists():
                    with open(self.progress_file, 'r') as f:
                        progress_data = json.load(f)
                    progress_data['processing_state'] = 'completed'
                    progress_data['completion_timestamp'] = datetime.now().isoformat()
                    with open(self.progress_file, 'w') as f:
                        json.dump(progress_data, f, indent=2)
                    
                # Clean up progress file after successful completion
                if Path(self.progress_file).exists():
                    Path(self.progress_file).unlink()
                    logger.info("🧹 Progress file cleaned up after successful completion")
            except Exception as e:
                logger.warning(f"Could not mark processing as completed: {e}")
            
            # Final progress save
            self._save_progress()
            
            # Final summary update to include all processed invoices
            try:
                logger.info(f"📊 Creating final invoice_summary.xlsx with all processed invoices")
                self.create_summary_excel()
                logger.info(f"✅ Final summary created successfully")
            except Exception as e:
                logger.error(f"❌ Error creating final summary: {e}")
                # Continue even if final summary fails
            
            logger.info("📊 Final Processing Summary:")
            logger.info(f"  📦 Total batches processed: {self.batch_number}")
            logger.info(f"  ✅ Successfully processed: {len(all_processed_refs)} refs")
            logger.info(f"  ❌ Failed: {len(all_failed_refs)} refs")
            logger.info(f"  🔄 Connection retries: {self.stats['connection_retries']}")
            logger.info(f"  ⏰ Timeouts: {self.stats['operation_timeouts']}")
            logger.info(f"  🔧 Recoveries attempted: {self.stats['recoveries_attempted']}")
            logger.info(f"  ✅ Recoveries successful: {self.stats['recoveries_successful']}")
            
            return all_processed_refs, all_failed_refs
            
        except Exception as e:
            logger.error(f"Error in batch processing: {e}")
            self._handle_error(e, "main_processing")
            # Save progress even on error
            self._save_progress()
            return [], missing_ref_numbers
    
    def search_single_reference(self, ref_no, mailboxes):
        """Search for emails containing a single reference number across ALL mailboxes systematically"""
        email_ids = set()
        email_mailbox_map = {}  # Track which mailbox each email was found in
        mailboxes_searched = []
        
        # Check if we have a valid connection before starting
        if not self.mail:
            logger.warning(f"  No email connection available for ref {ref_no}")
            return list(email_ids), email_mailbox_map
        
        try:
            # EFFICIENCY: Search INBOX first, other mailboxes only if not found
            inbox_found = False
            
            # Step 1: Search INBOX first (most emails are here)
            for i, mailbox in enumerate(mailboxes, 1):
                if mailbox == 'INBOX':
                    logger.info(f"    [{i}/{len(mailboxes)}] 📥 Searching INBOX first")
                    
                    mailbox_found = self._search_mailbox_for_reference(ref_no, mailbox, i, len(mailboxes))
                    mailboxes_searched.append(mailbox)
                    
                    if mailbox_found:
                        email_ids.update(mailbox_found)
                        for email_id in mailbox_found:
                            email_mailbox_map[email_id] = mailbox
                        
                        self.stats['found_in_inbox'] += 1
                        inbox_found = True
                        
                        logger.info(f"    ✅ Found {len(mailbox_found)} emails in INBOX - STOPPING search (efficiency)")
                        break
                    else:
                        logger.info(f"    📭 Not found in INBOX")
            
            # Step 2: Only search other mailboxes if NOT found in INBOX
            if not inbox_found:
                logger.info(f"    📁 Not in INBOX, searching other mailboxes...")
                
                for i, mailbox in enumerate(mailboxes, 1):
                    # Skip INBOX (already searched)
                    if mailbox == 'INBOX':
                        continue
                        
                    logger.info(f"    [{i}/{len(mailboxes)}] 🗃️  Searching {mailbox}")
                    
                    mailbox_found = self._search_mailbox_for_reference(ref_no, mailbox, i, len(mailboxes))
                    mailboxes_searched.append(mailbox)
                    
                    if mailbox_found:
                        email_ids.update(mailbox_found)
                        for email_id in mailbox_found:
                            email_mailbox_map[email_id] = mailbox
                        
                        self.stats['found_in_archive'] += 1
                        
                        logger.info(f"    ✅ Found {len(mailbox_found)} emails in {mailbox} - STOPPING search")
                        break
                    else:
                        logger.info(f"    📭 Not found in {mailbox}")
            
            # Log search results
            if email_ids:
                logger.info(f"  ✅ FOUND {len(email_ids)} emails for ref {ref_no} (searched {len(mailboxes_searched)}/{len(mailboxes)} mailboxes)")
            else:
                logger.warning(f"  ❌ NO EMAILS FOUND for ref {ref_no} in ANY of {len(mailboxes_searched)} mailboxes: {mailboxes_searched}")
        
        except Exception as e:
            logger.error(f"  Error searching for ref {ref_no}: {e}")
            self._handle_error(e, f"search_ref_{ref_no}")
        
        return list(email_ids), email_mailbox_map
    
    def _search_mailbox_for_reference(self, ref_no, mailbox, mailbox_index, total_mailboxes):
        """Search a specific mailbox for a reference number with robust error handling"""
        try:
            logger.info(f"  🔍 [{mailbox_index}/{total_mailboxes}] Searching in mailbox: {mailbox}")
            
            # Select the mailbox with retry logic for SSL errors
            max_retries = self.max_retries
            result = None
            for attempt in range(max_retries):
                try:
                    # Use timeout for mailbox selection with Gmail special folder handling
                    with self.timeout_context(10):  # 10 second timeout for mailbox selection
                        # Handle Gmail special folders that need quoting
                        if '[Gmail]' in mailbox and not mailbox.startswith('"'):
                            # Try with quotes first for Gmail special folders
                            quoted_mailbox = f'"{mailbox}"'
                            try:
                                result = self.mail.select(quoted_mailbox)
                                if result[0] == 'OK':
                                    logger.info(f"  ✅ Successfully selected quoted {quoted_mailbox}")
                                else:
                                    # Try without quotes as fallback
                                    result = self.mail.select(mailbox)
                            except Exception as e:
                                logger.debug(f"  Quoted selection failed, trying unquoted: {e}")
                                result = self.mail.select(mailbox)
                        else:
                            result = self.mail.select(mailbox)
                            
                        if result[0] != 'OK':
                            logger.warning(f"  Failed to select mailbox {mailbox}: {result}")
                            break
                        else:
                            logger.debug(f"  Successfully selected mailbox {mailbox}")
                            break  # Success, exit retry loop
                            
                except TimeoutError:
                    logger.warning(f"  Timeout selecting {mailbox} (attempt {attempt + 1})")
                    self.stats['operation_timeouts'] += 1
                    if attempt < max_retries - 1:
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        result = None
                        break
                        
                except Exception as e:
                    error_str = str(e).lower()
                    if any(keyword in error_str for keyword in ['ssl', 'socket', 'eof', 'connection']):
                        logger.warning(f"  Connection error selecting {mailbox} (attempt {attempt + 1}): {e}")
                        self.stats['connection_retries'] += 1
                        
                        if attempt < max_retries - 1:
                            # Try to reconnect on connection errors
                            logger.info(f"  Attempting to reconnect due to connection error...")
                            if self._recover_connection():
                                logger.info(f"  Successfully reconnected to email server")
                            else:
                                logger.warning(f"  Reconnection failed, will retry with existing connection")
                            
                            time.sleep(self.retry_delay)
                            continue
                        else:
                            logger.error(f"  Failed to select {mailbox} after {max_retries} attempts")
                            result = None
                            break
                    else:
                        logger.error(f"  Error selecting {mailbox}: {e}")
                        
                        # Check if it's a connection/auth error and attempt recovery
                        error_str = str(e).lower()
                        if any(keyword in error_str for keyword in ["logout", "auth", "timed out", "timeout", "connection", "illegal"]):
                            logger.warning(f"  Detected connection error for {mailbox}: {e}")
                            if self._handle_gmail_timeout():
                                logger.info(f"  Retrying {mailbox} after connection recovery...")
                                continue  # Retry the same mailbox
                        
                        result = None
                        break
            
            # Skip this mailbox if selection failed
            if result is None or result[0] != 'OK':
                logger.warning(f"  Skipping mailbox {mailbox} due to selection failure")
                return []
            
            # EXACT MATCH search patterns - must contain "invoice" AND exact reference number
            if self.quick_mode:
                # Quick mode: search for invoice emails with exact reference number
                search_patterns = [
                    f'(SUBJECT "invoice" SUBJECT "{ref_no}")',  # Subject contains both "invoice" and ref_no
                    f'(SUBJECT "invoices" SUBJECT "{ref_no}")', # Subject contains both "invoices" and ref_no
                    f'(SUBJECT "invoice(s)" SUBJECT "{ref_no}")'  # Subject contains both "invoice(s)" and ref_no
                ]
            else:
                # Full search patterns - all require invoice keyword + exact reference
                search_patterns = [
                    f'(SUBJECT "invoice" SUBJECT "{ref_no}")',  # Subject: invoice + ref_no
                    f'(SUBJECT "invoices" SUBJECT "{ref_no}")', # Subject: invoices + ref_no  
                    f'(SUBJECT "invoice(s)" SUBJECT "{ref_no}")', # Subject: invoice(s) + ref_no
                    f'(BODY "invoice" BODY "{ref_no}")',        # Body: invoice + ref_no
                    f'(BODY "invoices" BODY "{ref_no}")',       # Body: invoices + ref_no
                    f'(TEXT "invoice" TEXT "{ref_no}")'         # Anywhere: invoice + ref_no
                ]
            
            all_found_ids = set()
            
            for i, search_pattern in enumerate(search_patterns, 1):
                try:
                    logger.debug(f"  Trying search pattern {i}: {search_pattern}")
                    
                    # Use timeout for search operations
                    with self.timeout_context(15):  # 15 second timeout for search
                        result, data = self.mail.uid('search', None, search_pattern)
                    
                    if result == 'OK' and data[0]:
                        found_ids = data[0].split()
                        if found_ids:
                            logger.info(f"  Pattern {i} found {len(found_ids)} emails")
                            all_found_ids.update(found_ids)
                        else:
                            logger.debug(f"  Pattern {i} found no emails")
                    else:
                        logger.debug(f"  Pattern {i} search failed: {result}")
                        
                except TimeoutError:
                    logger.warning(f"  Timeout on search pattern {i}")
                    self.stats['operation_timeouts'] += 1
                    continue
                    
                except Exception as e:
                    error_str = str(e).lower()
                    if any(keyword in error_str for keyword in ['ssl', 'socket', 'eof', 'connection']):
                        logger.warning(f"  Connection error in pattern {i}: {e}")
                        self.stats['connection_retries'] += 1
                        # Try to recover connection
                        if self._recover_connection():
                            logger.info(f"  Connection recovered, retrying pattern {i}")
                            try:
                                with self.timeout_context(15):
                                    result, data = self.mail.uid('search', None, search_pattern)
                                if result == 'OK' and data[0]:
                                    found_ids = data[0].split()
                                    if found_ids:
                                        logger.info(f"  Pattern {i} found {len(found_ids)} emails after recovery")
                                        all_found_ids.update(found_ids)
                            except Exception as retry_e:
                                logger.debug(f"  Pattern {i} retry error: {retry_e}")
                        continue
                    else:
                        logger.debug(f"  Pattern {i} error: {e}")
                        continue
            
            # Track search patterns used
            self.stats['total_search_patterns_used'] += len(search_patterns)
            
            if all_found_ids:
                # Filter by invoice keywords with exact reference matching
                filtered_ids = self._filter_emails_by_invoice_keywords(list(all_found_ids), ref_no)
                
                if filtered_ids:
                    logger.info(f"  ✅ Found {len(filtered_ids)} emails in {mailbox} after strict filtering")
                    return filtered_ids
                else:
                    logger.info(f"  ❌ Found {len(all_found_ids)} emails but none matched strict invoice criteria")
                    return []
            else:
                logger.info(f"  ❌ No emails found in {mailbox} with any pattern")
                return []
            
        except Exception as e:
            logger.error(f"  Error searching mailbox {mailbox}: {e}")
            return []
    
    def _filter_emails_by_invoice_keywords(self, email_ids, ref_no):
        """Filter emails by strict invoice criteria - must contain 'invoice' AND exact reference number"""
        filtered_ids = []
        
        for email_id in email_ids:
            try:
                # Fetch subject and a bit of body for comprehensive checking
                result, response = self.mail.uid('fetch', email_id, 
                                               '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
                
                if result != 'OK' or not response or not response[0]:
                    continue
                
                raw_email = response[0][1]
                msg = email.message_from_bytes(raw_email)
                subject = (msg.get('Subject', '') or '').lower()
                sender = (msg.get('From', '') or '').lower()
                
                # STRICT filtering criteria:
                # 1. Must contain invoice keyword
                invoice_keywords = ['invoice', 'invoices', 'invoice(s)']
                has_invoice_keyword = any(kw in subject for kw in invoice_keywords)
                
                # 2. Must contain exact reference number 
                has_exact_ref = ref_no.lower() in subject
                
                # 3. Additional validation - check if it looks like an invoice email
                looks_like_invoice = (
                    has_invoice_keyword and 
                    has_exact_ref and
                    not any(spam_word in subject for spam_word in ['spam', 'promotion', 'advertisement', 'unsubscribe'])
                )
                
                if looks_like_invoice:
                    filtered_ids.append(email_id)
                    logger.debug(f"    ✅ EXACT MATCH: Found invoice email for {ref_no}: {email_id}")
                    logger.debug(f"       Subject: {subject}")
                else:
                    logger.debug(f"    ❌ FILTERED OUT: {email_id} - Invoice: {has_invoice_keyword}, Ref: {has_exact_ref}")
                    logger.debug(f"       Subject: {subject}")
                    
            except Exception as e:
                logger.debug(f"    Error filtering email {email_id}: {e}")
                continue
        
        return filtered_ids
    
    def fetch_email_details(self, email_id):
        """Fetch email details and return email message object"""
        try:
            result, data = self.mail.fetch(email_id, '(RFC822)')
            
            if result != 'OK' or not data or not data[0]:
                logger.warning(f"Failed to fetch email {email_id}")
                return None
            
            raw_email = data[0][1]
            email_message = email.message_from_bytes(raw_email)
            return email_message
            
        except Exception as e:
            logger.error(f"Error fetching email {email_id}: {e}")
            return None
    
    def process_emails_for_reference(self, ref_no, email_ids, email_mailbox_map=None):
        """Process emails for a single reference number - download, convert, process"""
        try:
            logger.info(f"📥 Processing {len(email_ids)} emails for ref {ref_no}")
            
            email_details = []
            attachments_downloaded = 0
            
            for email_id in email_ids:
                try:
                    logger.info(f"    📧 Processing email {email_id} for ref {ref_no}")
                    self._update_heartbeat()  # Update heartbeat for each email
                    
                    # Get mailbox information for this email
                    mailbox = email_mailbox_map.get(email_id, 'Unknown') if email_mailbox_map else 'Unknown'
                    
                    # Fetch email with retry logic - try multiple approaches
                    email_message = self.fetch_email_with_retry(email_id)
                    
                    if not email_message:
                        # Try alternative fetch method as last resort
                        logger.warning(f"    ⚠️  Primary fetch failed for {email_id}, trying alternative method...")
                        email_message = self._alternative_fetch_email(email_id)
                        
                        if not email_message:
                            logger.error(f"    ❌ Failed to fetch email {email_id} after all attempts")
                            # Still create a basic email detail for tracking
                            email_detail = {
                                'ref_no': ref_no,
                                'email_id': email_id.decode() if isinstance(email_id, bytes) else email_id,
                                'subject': 'Failed to fetch',
                                'sender': 'Unknown',
                                'date': 'Unknown',
                                'folder': 'N/A',
                                'mailbox': mailbox,
                                'attachments': [],
                                'error': 'Failed to fetch email content'
                            }
                            email_details.append(email_detail)
                            continue
                    
                    # Extract email details with mailbox information
                    email_detail = self.extract_email_details(email_message, email_id, ref_no, mailbox)
                    email_details.append(email_detail)
                    
                    # Download and process attachments
                    self._update_heartbeat()  # Update heartbeat before attachment processing
                    success = self.download_and_process_attachments(email_message, email_detail)
                    if success:
                        attachments_downloaded += 1
                        logger.info(f"    ✅ Successfully processed email {email_id}")
                    else:
                        logger.warning(f"    ⚠️  Email {email_id} processed but no attachments downloaded")
                    
                except Exception as e:
                    logger.error(f"    ❌ Error processing email {email_id}: {e}")
                    # Still create a basic email detail for tracking
                    try:
                        mailbox = email_mailbox_map.get(email_id, 'Unknown') if email_mailbox_map else 'Unknown'
                        email_detail = {
                            'ref_no': ref_no,
                            'email_id': email_id.decode() if isinstance(email_id, bytes) else email_id,
                            'subject': 'Error processing',
                            'sender': 'Unknown',
                            'date': 'Unknown',
                            'folder': 'N/A',
                            'mailbox': mailbox,
                            'attachments': [],
                            'error': str(e)
                        }
                        email_details.append(email_detail)
                    except Exception:
                        pass  # If even this fails, just continue
                    continue
            
            # Store email details for this reference
            if not hasattr(self, 'email_details_by_ref'):
                self.email_details_by_ref = {}
            self.email_details_by_ref[ref_no] = email_details
            
            # Also store in persistent summary data for complete excel summary
            for email_detail in email_details:
                self.persistent_summary_data.append({
                    'Reference_Number': ref_no,
                    'Status': 'Found in Email',
                    'Email_ID': email_detail['email_id'],
                    'Subject': email_detail['subject'],
                    'Sender': email_detail['sender'],
                    'Date': email_detail['date'],
                    'Mailbox': email_detail['mailbox'],
                    'Folder_Path': email_detail['folder'],
                    'Attachments_Found': email_detail.get('attachments_found', 0),
                    'Attachments_Downloaded': email_detail.get('attachments_downloaded', 0),
                    'Attachment_Files': ', '.join([att.get('filename', '') for att in email_detail.get('attachments', [])]),
                    'Search_Status': 'SUCCESS'
                })
            
            # Count successful and failed emails
            successful_emails = len([ed for ed in email_details if 'error' not in ed])
            failed_emails = len([ed for ed in email_details if 'error' in ed])
            
            logger.info(f"✅ Processed {len(email_details)} emails for ref {ref_no} "
                       f"(✅ {successful_emails} successful, ⚠️ {failed_emails} with errors), "
                       f"downloaded {attachments_downloaded} attachments")
            
            # Update statistics
            self.stats['emails_processed'] += len(email_details)
            self.stats['emails_found'] += len(email_ids)
            
            return len(email_details) > 0
            
        except Exception as e:
            logger.error(f"Error processing emails for ref {ref_no}: {e}")
            return False
    
    def fetch_email_with_retry(self, email_id, max_retries=5):
        """Fetch email with retry logic to handle SSL errors"""
        import time
        
        for attempt in range(max_retries):
            try:
                # Use UID fetch instead of regular fetch
                result, data = self.mail.uid('fetch', email_id, '(RFC822)')
                
                if result != 'OK' or not data or not data[0]:
                    logger.warning(f"Failed to fetch email {email_id} (attempt {attempt + 1}): {result}")
                    if attempt < max_retries - 1:
                        time.sleep(2)  # Wait before retry
                        continue
                    return None
                
                raw_email = data[0][1]
                email_message = email.message_from_bytes(raw_email)
                logger.debug(f"Successfully fetched email {email_id} on attempt {attempt + 1}")
                return email_message
                
            except Exception as e:
                logger.warning(f"Error fetching email {email_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    # Try to reconnect on SSL errors
                    if "SSL" in str(e) or "socket" in str(e):
                        try:
                            logger.info(f"Attempting to reconnect due to SSL error...")
                            self.mail.close()
                            self.mail.logout()
                            self.connect_to_email()
                        except Exception as reconnect_error:
                            logger.warning(f"Reconnection failed: {reconnect_error}")
                    
                    time.sleep(3)  # Wait longer before retry
                    continue
                else:
                    logger.error(f"Failed to fetch email {email_id} after {max_retries} attempts")
                    return None
        
        return None
    
    def _alternative_fetch_email(self, email_id):
        """Alternative method to fetch email when primary method fails"""
        try:
            logger.info(f"    🔄 Trying alternative fetch method for {email_id}")
            
            # Try different fetch approaches
            fetch_methods = [
                lambda: self.mail.uid('fetch', email_id, '(RFC822)'),
                lambda: self.mail.uid('fetch', email_id, '(BODY[])'),
                lambda: self.mail.fetch(email_id, '(RFC822)'),
                lambda: self.mail.fetch(email_id, '(BODY[])')
            ]
            
            for i, fetch_method in enumerate(fetch_methods, 1):
                try:
                    logger.debug(f"    Trying fetch method {i} for {email_id}")
                    result, data = fetch_method()
                    
                    if result == 'OK' and data and data[0]:
                        raw_email = data[0][1]
                        email_message = email.message_from_bytes(raw_email)
                        logger.info(f"    ✅ Alternative fetch method {i} succeeded for {email_id}")
                        return email_message
                    else:
                        logger.debug(f"    Fetch method {i} failed: {result}")
                        
                except Exception as e:
                    logger.debug(f"    Fetch method {i} error: {e}")
                    continue
            
            logger.warning(f"    All alternative fetch methods failed for {email_id}")
            return None
            
        except Exception as e:
            logger.error(f"    Error in alternative fetch for {email_id}: {e}")
            return None
    
    def extract_email_details(self, email_message, email_id, ref_no, mailbox=None):
        """Extract email details for summary"""
        try:
            subject = email_message.get('Subject', 'No Subject')
            sender = email_message.get('From', 'Unknown Sender')
            date_str = email_message.get('Date', 'Unknown Date')
            
            # Parse date
            try:
                email_date = parsedate_to_datetime(date_str)
                formatted_date = email_date.strftime('%Y-%m-%d %H:%M:%S')
            except:
                formatted_date = date_str
            
            # Create folder name
            folder_name = f"ref_{ref_no}_email_{email_id.decode() if isinstance(email_id, bytes) else email_id}"
            email_folder = Path(self.attachments_folder) / folder_name
            email_folder.mkdir(parents=True, exist_ok=True)
            
            return {
                'ref_no': ref_no,
                'email_id': email_id.decode() if isinstance(email_id, bytes) else email_id,
                'subject': subject,
                'sender': sender,
                'date': formatted_date,
                'folder': str(email_folder),
                'mailbox': mailbox or 'Unknown',
                'attachments': []
            }
            
        except Exception as e:
            logger.error(f"Error extracting email details: {e}")
            return None
    
    def download_attachments(self, email_message, email_id):
        """Download attachments from email message"""
        try:
            # Get email details
            subject = email_message.get('Subject', 'No Subject')
            sender = email.utils.parseaddr(email_message.get('From', ''))[1]
            date_str = email_message.get('Date', '')
            
            # Parse date
            try:
                date_obj = parsedate_to_datetime(date_str)
                date_formatted = date_obj.strftime('%Y-%m-%d_%H-%M-%S')
            except Exception:
                date_formatted = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            
            # Create email-specific folder
            safe_subject = "".join(
                c for c in subject if c.isalnum() or c in (' ', '-', '_')
            ).strip()
            safe_subject = safe_subject[:50]
            
            email_folder = self.download_dir / (
                f"{date_formatted}_{safe_subject}_{email_id.decode()}"
            )
            email_folder.mkdir(exist_ok=True)
            
            # Store email details for summary
            email_detail = {
                'email_id': email_id.decode(),
                'subject': subject,
                'sender': sender,
                'date': date_str,
                'date_formatted': date_formatted,
                'folder': str(email_folder),
                'attachments_found': 0,
                'attachments_downloaded': 0,
                'attachment_files': []
            }
            
            attachments_found = 0
            attachments_downloaded = 0
            
            # Use existing invoice downloader logic if available
            if INVOICE_PROCESSING_AVAILABLE:
                try:
                    from mpi_backend.utils.invoice_downaloder import download_email_attachments
                    download_success = download_email_attachments(email_message, email_folder)
                    # The invoice downloader returns a boolean, not a tuple
                    # We'll count attachments by checking the folder contents
                    if download_success:
                        attachment_files = list(email_folder.glob("*"))
                        attachments_found = len(attachment_files)
                        attachments_downloaded = len(attachment_files)
                        logger.info(f"Downloaded {attachments_downloaded} attachments using invoice downloader")
                    else:
                        attachments_found = 0
                        attachments_downloaded = 0
                        logger.warning("Invoice downloader returned False - no attachments downloaded")
                    
                    # Get list of downloaded files
                    for file_path in email_folder.glob("*"):
                        if file_path.is_file():
                            email_detail['attachment_files'].append(str(file_path))
                            
                except Exception as e:
                    logger.error(f"Error using invoice downloader: {e}")
                    # Fallback to simple download
                    attachments_found, attachments_downloaded = self._simple_download_attachments(
                        email_message, email_folder, email_detail
                    )
            else:
                # Fallback to simple download if invoice processing not available
                attachments_found, attachments_downloaded = self._simple_download_attachments(
                    email_message, email_folder, email_detail
                )
            
            email_detail['attachments_found'] = attachments_found
            email_detail['attachments_downloaded'] = attachments_downloaded
            
            self.stats['attachments_downloaded'] += attachments_downloaded
            self.email_results.append(email_detail)
            
            logger.info(f"Email {email_id.decode()}: {attachments_found} found, {attachments_downloaded} downloaded")
            return attachments_downloaded > 0
            
        except Exception as e:
            logger.error(f"Error downloading attachments for email {email_id}: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def download_and_process_attachments(self, email_message, email_detail):
        """Download and process attachments for a single email with timeout protection"""
        try:
            # Use timeout to prevent getting stuck on attachment download
            with self.timeout_context(60):  # 60 second timeout for attachment download
                # Use the existing download_attachments method
                email_id = email_detail['email_id'].encode() if isinstance(email_detail['email_id'], str) else email_detail['email_id']
                success = self.download_attachments(email_message, email_id)
                
                if success:
                    # Update email_detail with attachment information
                    email_folder = Path(email_detail['folder'])
                    if email_folder.exists():
                        attachment_files = list(email_folder.glob('*'))
                        email_detail['attachments'] = [
                            {'filename': f.name, 'path': str(f)} for f in attachment_files if f.is_file()
                        ]
                        email_detail['attachments_found'] = len(email_detail['attachments'])
                        email_detail['attachments_downloaded'] = len(email_detail['attachments'])
                        email_detail['attachment_files'] = [att['filename'] for att in email_detail['attachments']]
                
                return success
                
        except TimeoutError:
            logger.error(f"Timeout downloading attachments for email {email_detail.get('email_id', 'unknown')}")
            return False
        except Exception as e:
            logger.error(f"Error in download_and_process_attachments: {e}")
            return False
    
    def _simple_download_attachments(self, email_message, email_folder, email_detail):
        """Simple attachment download fallback method"""
        attachments_found = 0
        attachments_downloaded = 0
        
        # Process email parts for attachments
        for part in email_message.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            
            if part.get('Content-Disposition') is None:
                continue
            
            filename = part.get_filename()
            if filename:
                attachments_found += 1
                
                # Clean filename
                filename = "".join(
                    c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')
                ).rstrip()
                if not filename:
                    filename = f"attachment_{attachments_found}"
                
                # Add timestamp to avoid conflicts
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = f"{timestamp}_{filename}"
                
                file_path = email_folder / safe_filename
                
                try:
                    # Save attachment
                    with open(file_path, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                    
                    attachments_downloaded += 1
                    email_detail['attachment_files'].append(str(file_path))
                    logger.info(f"Downloaded: {safe_filename}")
                    
                except Exception as e:
                    logger.error(f"Error downloading {filename}: {e}")
        
        # Copy attachments to storage directory as well
        self._copy_attachments_to_storage(email_folder)
        
        return attachments_found, attachments_downloaded
    
    def _copy_attachments_to_storage(self, email_folder):
        """Copy downloaded attachments to storage directory as well"""
        try:
            if not email_folder.exists():
                return
            
            # Create corresponding folder structure in storage
            relative_path = email_folder.relative_to(self.download_dir)
            storage_folder = self.storage_dir / relative_path
            storage_folder.mkdir(parents=True, exist_ok=True)
            
            # Copy all files from email folder to storage
            import shutil
            files_copied = 0
            for file_path in email_folder.rglob('*'):
                if file_path.is_file():
                    storage_file_path = storage_folder / file_path.relative_to(email_folder)
                    storage_file_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, storage_file_path)
                    files_copied += 1
            
            if files_copied > 0:
                logger.info(f"📁 Copied {files_copied} files to storage/missing_invoice_attachments/: {storage_folder}")
                
        except Exception as e:
            logger.error(f"❌ Error copying attachments to storage: {e}")
            # Don't fail the entire process if storage copy fails
    
    def process_emails(self, email_ids):
        """Process all found emails"""
        logger.info(f"Processing {len(email_ids)} emails...")
        
        for i, email_id in enumerate(email_ids, 1):
            try:
                logger.info(f"Processing email {i}/{len(email_ids)}: {email_id.decode()}")
                
                email_message = self.fetch_email_details(email_id)
                if email_message:
                    self.download_attachments(email_message, email_id)
                    self.stats['emails_processed'] += 1
                else:
                    self.stats['errors'] += 1
                    
            except Exception as e:
                logger.error(f"Error processing email {email_id}: {e}")
                self.stats['errors'] += 1
    
    def process_downloaded_attachments(self):
        """Process downloaded attachments using existing invoice processing pipeline with database integration"""
        if not INVOICE_PROCESSING_AVAILABLE:
            logger.warning("Invoice processing not available, skipping attachment processing")
            return
        
        try:
            logger.info("Processing downloaded attachments using invoice processing pipeline...")
            
            # Get all downloaded folders from current batch
            downloaded_folders = []
            if hasattr(self, 'email_details_by_ref'):
                for ref_no, email_details in self.email_details_by_ref.items():
                    for email_detail in email_details:
                        if email_detail.get('attachments', []):
                            folder_path = Path(email_detail['folder'])
                            if folder_path.exists():
                                downloaded_folders.append(folder_path)
            
            if not downloaded_folders:
                logger.info("No attachments to process in current batch")
                return
            
            total_processed = 0
            total_database_added = 0
            
            for folder in downloaded_folders:
                try:
                    logger.info(f"Processing attachments in folder: {folder}")
                    
                    # Convert PDFs to Excel using existing converter
                    converted_files, failed_files = convert_invoice_for_email(folder)
                    
                    if converted_files:
                        logger.info(f"Converted {len(converted_files)} files in {folder}")
                        
                        # Process extracted data using existing processor WITH database integration
                        # This follows the same workflow as regular email processing
                        results = process_extracted_data(converted_files, failed_files)
                        
                        # Count results by status
                        successful_results = [r for r in results if r.get('status') in ['created', 'updated']]
                        created_results = [r for r in results if r.get('status') == 'created']
                        updated_results = [r for r in results if r.get('status') == 'updated']
                        duplicate_results = [r for r in results if r.get('status') == 'duplicate']
                        
                        total_processed += len(successful_results)
                        total_database_added += len(created_results)
                        
                        logger.info(f"✅ Processed {len(successful_results)} invoices from {folder}")
                        logger.info(f"  📝 Created: {len(created_results)}")
                        logger.info(f"  🔄 Updated: {len(updated_results)}")
                        logger.info(f"  🔁 Duplicates: {len(duplicate_results)}")
                        
                        # Log any failed conversions
                        if failed_files:
                            logger.warning(f"⚠️ Failed to convert {len(failed_files)} files in {folder}")
                    else:
                        logger.info(f"❌ No files converted in {folder}")
                        
                except Exception as e:
                    logger.error(f"❌ Error processing folder {folder}: {e}")
                    continue
            
            logger.info(f"📊 Batch Processing Summary:")
            logger.info(f"  📁 Folders processed: {len(downloaded_folders)}")
            logger.info(f"  📄 Total invoices processed: {total_processed}")
            logger.info(f"  💾 Added to database: {total_database_added}")
            
            self.stats['invoices_processed'] += total_processed
            self.stats['database_records_added'] = self.stats.get('database_records_added', 0) + total_database_added
            
        except Exception as e:
            logger.error(f"❌ Error in attachment processing: {e}")
    
    def create_summary_excel(self):
        """Create comprehensive summary Excel file with email details and missing invoice tracking"""
        try:
            logger.info(f"Creating comprehensive summary Excel file: {self.summary_file}")
            
            # Use persistent summary data for complete coverage (never gets cleaned up)
            summary_data = []
            
            # Use persistent summary data if available (this contains ALL processed invoices)
            if hasattr(self, 'persistent_summary_data') and self.persistent_summary_data:
                summary_data = self.persistent_summary_data.copy()
                logger.info(f"📊 Using persistent summary data: {len(summary_data)} records")
            else:
                # Fallback to old method if persistent data not available
                logger.warning(f"⚠️ Persistent summary data not available, using fallback method")
                
                # Add invoices found in email
                if hasattr(self, 'email_details_by_ref') and self.email_details_by_ref:
                    for ref_no, email_details in self.email_details_by_ref.items():
                        for email_detail in email_details:
                            summary_data.append({
                                'Reference_Number': ref_no,
                                'Status': 'Found in Email',
                                'Email_ID': email_detail['email_id'],
                                'Subject': email_detail['subject'],
                                'Sender': email_detail['sender'],
                                'Date': email_detail['date'],
                                'Mailbox': email_detail.get('mailbox', 'Unknown'),
                                'Folder_Path': email_detail['folder'],
                                'Attachments_Found': len(email_detail.get('attachments', [])),
                                'Attachments_Downloaded': email_detail.get('attachments_downloaded', 0),
                                'Attachment_Files': '; '.join([att.get('filename', '') for att in email_detail.get('attachments', [])]),
                                'Search_Status': 'SUCCESS'
                            })
                
                # Add invoices NOT found in email (marked in red)
                for ref_no in self.missing_invoices_not_found:
                    summary_data.append({
                        'Reference_Number': ref_no,
                        'Status': 'NOT FOUND IN EMAIL',
                        'Email_ID': 'N/A',
                        'Subject': 'N/A',
                        'Sender': 'N/A',
                        'Date': 'N/A',
                        'Mailbox': 'N/A',
                        'Folder_Path': 'N/A',
                        'Attachments_Found': 0,
                        'Attachments_Downloaded': 0,
                        'Attachment_Files': 'N/A',
                        'Search_Status': 'NOT FOUND'
                    })
            
            # Log summary statistics
            if summary_data:
                found_count = len([item for item in summary_data if item['Status'] == 'Found in Email'])
                not_found_count = len([item for item in summary_data if item['Status'] == 'Not Found in Email'])
                logger.info(f"📊 Summary includes {len(summary_data)} processed records ({found_count} found, {not_found_count} not found)")
            
            if not summary_data:
                logger.warning("No data to create summary")
                return False
            
            df_summary = pd.DataFrame(summary_data)
            
            # Create Excel file with enhanced formatting
            wb = Workbook()
            ws = wb.active
            ws.title = "Comprehensive Invoice Search Summary"
            
            # Define colors for highlighting
            red_fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")  # Red for not found
            green_fill = PatternFill(start_color="00FF00", end_color="00FF00", fill_type="solid")  # Green for headers
            yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")  # Yellow for found
            
            # Add headers
            headers = list(df_summary.columns)
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)
                cell.fill = green_fill
            
            # Add data with conditional formatting
            for row_idx, (_, row) in enumerate(df_summary.iterrows(), 2):
                for col_idx, value in enumerate(row, 1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=value)
                    
                    # Highlight rows based on status
                    if row['Search_Status'] == 'NOT FOUND':
                        cell.fill = red_fill
                        cell.font = Font(bold=True, color="FFFFFF")  # White text on red background
                    elif row['Search_Status'] == 'SUCCESS':
                        cell.fill = yellow_fill
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Add summary statistics sheet
            self.create_summary_statistics_sheet(wb)
            
            wb.save(self.summary_file)
            logger.info(f"Comprehensive summary Excel file created: {self.summary_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error creating summary Excel file: {e}")
            return False
    
    def create_summary_statistics_sheet(self, wb):
        """Create a separate sheet with comprehensive statistics"""
        try:
            # Create statistics sheet
            stats_ws = wb.create_sheet("Search Statistics")
            
            # Define colors
            green_fill = PatternFill(start_color="00FF00", end_color="00FF00", fill_type="solid")
            blue_fill = PatternFill(start_color="ADD8E6", end_color="ADD8E6", fill_type="solid")
            
            # Add title
            stats_ws.cell(row=1, column=1, value="COMPREHENSIVE INVOICE SEARCH STATISTICS")
            stats_ws.cell(row=1, column=1).font = Font(bold=True, size=16)
            stats_ws.cell(row=1, column=1).fill = green_fill
            
            # Add statistics data
            stats_data = [
                ("Metric", "Value", "Description"),
                ("", "", ""),
                ("Missing Reference Numbers", self.stats['missing_ref_numbers'], "Ref numbers from missing_invoices.xlsx file"),
                ("", "", ""),
                ("Missing Invoices Found in Email", self.stats['missing_invoices_found_in_email'], "Missing invoices found in email folders"),
                ("Missing Invoices NOT Found in Email", self.stats['missing_invoices_not_found_in_email'], "Missing invoices not found in any email folder"),
                ("", "", ""),
                ("Found in INBOX", self.stats['found_in_inbox'], "Invoices found in INBOX (fastest)"),
                ("Found in Archive", self.stats['found_in_archive'], "Invoices found in Archive folder"),
                ("Archive Searches Skipped", self.stats['archive_searches_skipped'], "Archive searches skipped due to INBOX finds"),
                ("", "", ""),
                ("Total Mailboxes Searched", self.stats['total_mailboxes_searched'], "Number of email folders searched"),
                ("Total Search Patterns Used", self.stats['total_search_patterns_used'], "Total search patterns executed"),
                ("", "", ""),
                ("Emails Found", self.stats['emails_found'], "Total emails found for missing invoices"),
                ("Emails Processed", self.stats['emails_processed'], "Emails successfully processed"),
                ("Attachments Downloaded", self.stats['attachments_downloaded'], "Total attachments downloaded"),
                ("Invoices Processed", self.stats['invoices_processed'], "Invoices successfully processed"),
                ("", "", ""),
                ("Database Records Added", self.stats.get('database_records_added', 0), "New records added to database"),
                ("Database Records Updated", self.stats.get('database_records_updated', 0), "Existing records updated in database"),
                ("Database Duplicates Found", self.stats.get('database_duplicates_found', 0), "Duplicate records found (not added)"),
                ("", "", ""),
                ("Batches Completed", self.stats.get('batches_completed', 0), "Number of batches processed"),
                ("Average Time per Batch", f"{self.stats.get('average_time_per_batch', 0):.1f}s", "Average processing time per batch"),
                ("", "", ""),
                ("Errors Encountered", self.stats['errors'], "Total errors during processing"),
                ("", "", ""),
                ("Success Rate (Found/Total)", f"{self.stats['missing_invoices_found_in_email']}/{self.stats['missing_ref_numbers']}", "Percentage of missing invoices found in email"),
                ("Processing Rate (Processed/Found)", f"{self.stats['emails_processed']}/{self.stats['emails_found']}", "Percentage of found emails successfully processed"),
            ]
            
            # Add headers
            for col, header in enumerate(stats_data[0], 1):
                cell = stats_ws.cell(row=3, column=col, value=header)
                cell.font = Font(bold=True)
                cell.fill = blue_fill
            
            # Add data
            for row_idx, (metric, value, description) in enumerate(stats_data[1:], 4):
                stats_ws.cell(row=row_idx, column=1, value=metric)
                stats_ws.cell(row=row_idx, column=2, value=value)
                stats_ws.cell(row=row_idx, column=3, value=description)
            
            # Auto-adjust column widths
            for column in stats_ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
                        pass
                adjusted_width = min(max_length + 2, 60)
                stats_ws.column_dimensions[column_letter].width = adjusted_width
            
            logger.info("Statistics sheet created successfully")
            
        except Exception as e:
            logger.error(f"Error creating statistics sheet: {e}")
    
    def cleanup(self):
        """Clean up email connection"""
        try:
            if self.mail:
                self.mail.close()
                self.mail.logout()
                logger.info("Email connection closed")
        except Exception as e:
            logger.warning(f"Error closing email connection: {e}")
    
    def _log_memory_usage(self):
        """Log current memory usage"""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 Current memory usage: {memory_mb:.1f}MB")
        except ImportError:
            logger.debug("psutil not available for memory monitoring")
        except Exception as e:
            logger.debug(f"Could not get memory usage: {e}")
    
    def run_complete_process(self):
        """Main method to run the complete process with robust error handling"""
        logger.info("🚀 Starting missing invoice finder process...")
        self._log_memory_usage()
        
        try:
            # Validate environment
            if not self.validate_environment():
                logger.error("❌ Environment validation failed")
                return False
            
            # Step 1: Read existing missing invoices file
            missing_ref_numbers = self.read_missing_invoices_file()
            if not missing_ref_numbers:
                logger.error("❌ No missing reference numbers found in file!")
                return False
            
            self.missing_ref_numbers = missing_ref_numbers
            self.stats['missing_ref_numbers'] = len(missing_ref_numbers)
            
            logger.info(f"📋 Found {len(missing_ref_numbers)} missing reference numbers to process")
            
            # Step 2: Connect to email with retry
            max_connection_attempts = 3
            for attempt in range(max_connection_attempts):
                if self.connect_to_email():
                    logger.info("✅ Email connection successful")
                    break
                else:
                    logger.warning(f"❌ Email connection attempt {attempt + 1} failed")
                    if attempt < max_connection_attempts - 1:
                        logger.info(f"Retrying connection in {self.retry_delay} seconds...")
                        time.sleep(self.retry_delay)
                    else:
                        logger.error("❌ Failed to connect to email after all attempts")
                        return False
            
            # Step 3: Process missing invoices in batches for memory optimization
            try:
                processed_refs, failed_refs = self.process_missing_invoices_in_batches(missing_ref_numbers)
            except KeyboardInterrupt:
                logger.warning("⚠️ Process interrupted by user")
                self._save_progress()
                return False
            except Exception as e:
                logger.error(f"❌ Error during processing: {e}")
                self._handle_error(e, "main_processing")
                self._save_progress()
                return False
            
            # Note: Attachments and summary are now processed within each batch for memory optimization
            
            # Create final comprehensive summary Excel file
            try:
                logger.info("📊 Creating final comprehensive summary Excel file...")
                self.create_summary_excel()
                logger.info("✅ Final summary Excel file created successfully")
            except Exception as e:
                logger.error(f"❌ Error creating final summary Excel: {e}")
                self._handle_error(e, "final_summary_excel")
            
            # Print final summary
            try:
                self.print_final_summary()
            except Exception as e:
                logger.error(f"❌ Error printing final summary: {e}")
                self._handle_error(e, "final_summary")
            
            # Clean up progress file on successful completion
            try:
                if Path(self.progress_file).exists():
                    Path(self.progress_file).unlink()
                    logger.info("🧹 Progress file cleaned up")
            except Exception as e:
                logger.warning(f"Could not clean up progress file: {e}")
            
            logger.info("✅ Missing invoice finder process completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Critical error in complete process: {e}")
            logger.error(traceback.format_exc())
            self._handle_error(e, "critical_error")
            self._save_progress()
            return False
        finally:
            try:
                self.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
    
    def print_final_summary(self):
        """Print comprehensive final summary to console"""
        print("\n" + "="*80)
        print("COMPREHENSIVE MISSING INVOICE FINDER SUMMARY")
        print("="*80)
        
        # Basic statistics
        print(f"📊 BASIC STATISTICS:")
        print(f"  Missing reference numbers: {self.stats['missing_ref_numbers']}")
        
        # Search statistics
        print(f"\n🔍 SEARCH STATISTICS:")
        print(f"  Total mailboxes searched: {self.stats['total_mailboxes_searched']}")
        print(f"  Total search patterns used: {self.stats['total_search_patterns_used']}")
        print(f"  Found in INBOX: {self.stats['found_in_inbox']}")
        print(f"  Found in Archive: {self.stats['found_in_archive']}")
        print(f"  Archive searches skipped: {self.stats['archive_searches_skipped']}")
        print(f"  Missing invoices found in email: {self.stats['missing_invoices_found_in_email']}")
        print(f"  Missing invoices NOT found in email: {self.stats['missing_invoices_not_found_in_email']}")
        
        # Processing statistics
        print(f"\n📧 EMAIL PROCESSING:")
        print(f"  Emails found: {self.stats['emails_found']}")
        print(f"  Emails processed: {self.stats['emails_processed']}")
        print(f"  Attachments downloaded: {self.stats['attachments_downloaded']}")
        print(f"  Invoices processed: {self.stats.get('invoices_processed', 0)}")
        
        # Success rates
        if self.stats['missing_ref_numbers'] > 0:
            success_rate = (self.stats['missing_invoices_found_in_email'] / self.stats['missing_ref_numbers']) * 100
            print(f"\n📈 SUCCESS RATES:")
            print(f"  Email search success rate: {success_rate:.1f}% ({self.stats['missing_invoices_found_in_email']}/{self.stats['missing_ref_numbers']})")
        
        if self.stats['emails_found'] > 0:
            processing_rate = (self.stats['emails_processed'] / self.stats['emails_found']) * 100
            print(f"  Email processing success rate: {processing_rate:.1f}% ({self.stats['emails_processed']}/{self.stats['emails_found']})")
        
        # Error tracking
        print(f"\n⚠️  ERRORS:")
        print(f"  Total errors encountered: {self.stats['errors']}")
        
        # Files created
        print(f"\n📁 FILES CREATED:")
        print(f"  - {self.missing_file}")
        print(f"  - {self.summary_file}")
        print(f"  - Attachments in: {self.download_dir}")
        
        # Missing invoices not found (highlighted)
        if self.missing_invoices_not_found:
            print(f"\n🔴 MISSING INVOICES NOT FOUND IN EMAIL ({len(self.missing_invoices_not_found)}):")
            for ref_no in self.missing_invoices_not_found[:10]:  # Show first 10
                print(f"  - {ref_no}")
            if len(self.missing_invoices_not_found) > 10:
                print(f"  ... and {len(self.missing_invoices_not_found) - 10} more")
        
        print("="*80)
        print("✅ Comprehensive missing invoice finder completed successfully!")
        print("="*80)


def main():
    """Main function"""
    try:
        print("🔍 Starting Missing Invoice Finder...")
        print("🚀 HIGH SPEED MODE - Optimized for 5000+ invoices in under 1 hour")
        print("=" * 60)
        
        # Create and run the finder in high speed mode
        finder = MissingInvoiceFinder(high_speed_mode=True)
        success = finder.run_complete_process()
        
        if success:
            print("\n✅ Missing invoice finder completed successfully!")
            print("📊 Check the generated Excel files and downloaded attachments")
        else:
            print("\n❌ Missing invoice finder failed!")
            print("📝 Check the log file for error details")
            return False
            
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
