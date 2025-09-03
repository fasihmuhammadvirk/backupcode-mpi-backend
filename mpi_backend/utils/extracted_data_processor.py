"""
Enhanced Extracted Data Processor for MPI Backend

This module processes extracted data from PDF invoices and statements,
handling both immediate processing and background task processing
with enhanced error handling and logging.
"""

import logging
import traceback
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from contextlib import asynccontextmanager
import pandas as pd

from mpi_backend.database import get_async_db
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.StatementController import StatementController
from mpi_backend.config.logging_config import get_missing_logger

# Setup logging
logger = logging.getLogger(__name__)
missing_logger = get_missing_logger()

# Configuration
PROCESSING_BATCH_SIZE = 100  # Process files in batches
MAX_RETRIES = 3  # Maximum retries for failed processing
RETRY_DELAY_SECONDS = 5  # Delay between retries


@asynccontextmanager
async def get_db_session():
    """Get database session for data processing"""
    async for db in get_async_db():
        try:
            yield db
        finally:
            await db.close()


async def process_extracted_data(
    converted_files: List[str], 
    failed_files: List[str],
    background_processing: bool = False
) -> Dict[str, any]:
    """
    Process extracted data from converted files
    
    Args:
        converted_files: List of successfully converted file paths
        failed_files: List of failed conversion file paths
        background_processing: Whether this is running as background task
    
    Returns:
        Dictionary with processing results
    """
    logger.info(f"Starting data processing for {len(converted_files)} files")
    
    if background_processing:
        logger.info("Running in background processing mode")
    
    processing_results = {
        'success_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
        'errors': []
    }
    
    try:
        # Process files in batches
        for i in range(0, len(converted_files), PROCESSING_BATCH_SIZE):
            batch = converted_files[i:i + PROCESSING_BATCH_SIZE]
            logger.info(f"Processing batch {i//PROCESSING_BATCH_SIZE + 1}: {len(batch)} files")
            
            batch_results = await process_file_batch(batch)
            
            # Aggregate results
            processing_results['success_count'] += batch_results['success_count']
            processing_results['failed_count'] += batch_results['failed_count']
            processing_results['skipped_count'] += batch_results['skipped_count']
            processing_results['errors'].extend(batch_results['errors'])
            
            logger.info(f"Batch completed: {batch_results['success_count']} success, "
                       f"{batch_results['failed_count']} failed")
        
        # Log failed files
        if failed_files:
            logger.warning(f"Found {len(failed_files)} failed conversion files")
            for failed_file in failed_files:
                missing_logger.warning(f"Failed conversion: {failed_file}")
        
        logger.info(f"Data processing complete. "
                   f"Success: {processing_results['success_count']}, "
                   f"Failed: {processing_results['failed_count']}, "
                   f"Skipped: {processing_results['skipped_count']}")
        
        return processing_results
        
    except Exception as e:
        error_msg = f"Critical error in data processing: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        processing_results['errors'].append(error_msg)
        return processing_results


async def process_file_batch(files: List[str]) -> Dict[str, any]:
    """
    Process a batch of files
    
    Args:
        files: List of file paths to process
    
    Returns:
        Dictionary with batch processing results
    """
    batch_results = {
        'success_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
        'errors': []
    }
    
    async with get_db_session() as db:
        for file_path in files:
            try:
                result = await process_single_file(file_path, db)
                
                if result['success']:
                    batch_results['success_count'] += 1
                elif result['skipped']:
                    batch_results['skipped_count'] += 1
                else:
                    batch_results['failed_count'] += 1
                    if result['error']:
                        batch_results['errors'].append(result['error'])
                        
            except Exception as e:
                error_msg = f"Error processing {file_path}: {str(e)}"
                logger.error(error_msg)
                batch_results['failed_count'] += 1
                batch_results['errors'].append(error_msg)
    
    return batch_results


async def process_single_file(file_path: str, db) -> Dict[str, any]:
    """
    Process a single file
    
    Args:
        file_path: Path to the file to process
        db: Database session
    
    Returns:
        Dictionary with processing result
    """
    try:
        file_path_obj = Path(file_path)
        
        if not file_path_obj.exists():
            return {
                'success': False,
                'skipped': False,
                'error': f"File not found: {file_path}"
            }
        
        # Determine file type and process accordingly
        file_extension = file_path_obj.suffix.lower()
        
        # Excel files (.xlsx) are always invoice files from PDF conversion
        if file_extension == '.xlsx':
            return await process_invoice_file(file_path, db)
        elif 'invoice' in file_path.lower():
            return await process_invoice_file(file_path, db)
        elif 'statement' in file_path.lower():
            return await process_statement_file(file_path, db)
        else:
            return await process_generic_file(file_path, db)
            
    except Exception as e:
        return {
            'success': False,
            'skipped': False,
            'error': f"Error processing {file_path}: {str(e)}"
        }


async def process_invoice_file(file_path: str, db, existing_invoice_id: Optional[str] = None) -> Dict[str, any]:
    """
    Process an invoice file
    
    Args:
        file_path: Path to the invoice file
        db: Database session
    
    Returns:
        Dictionary with processing result
    """
    try:
        # Use InvoiceItemController for invoice processing
        controller = InvoiceItemController(db)
        
        # Process the invoice file
        result = await controller.process_invoice_file(file_path, existing_invoice_id)
        
        if result.get('success'):
            return {
                'success': True,
                'skipped': False,
                'error': None,
                'invoice_id': result.get('invoice_id'),
                'status': result.get('status'),
                'message': result.get('message'),
                'ref_no': result.get('ref_no'),
                'vendor': result.get('vendor'),
                'date': result.get('date')
            }
        else:
            return {
                'success': False,
                'skipped': False,
                'error': result.get('error', 'Unknown error'),
                'status': result.get('status', 'error'),
                'message': result.get('message', result.get('error', 'Unknown error'))
            }
            
    except Exception as e:
        return {
            'success': False,
            'skipped': False,
            'error': f"Error processing invoice {file_path}: {str(e)}"
        }


async def process_statement_file(file_path: str, db) -> Dict[str, any]:
    """
    Process a statement file
    
    Args:
        file_path: Path to the statement file
        db: Database session
    
    Returns:
        Dictionary with processing result
    """
    try:
        # Use StatementController for statement processing
        controller = StatementController(db)
        
        # Process the statement file
        result = await controller.process_statement_file(file_path)
        
        if result.get('success'):
                return {
                'success': True,
                'skipped': False,
                'error': None
                }
        else:
            return {
                'success': False,
                'skipped': False,
                'error': result.get('error', 'Unknown error')
            }
            
    except Exception as e:
        return {
            'success': False,
            'skipped': False,
            'error': f"Error processing statement {file_path}: {str(e)}"
        }


async def process_generic_file(file_path: str, db) -> Dict[str, any]:
    """
    Process a generic file (fallback)
    
    Args:
        file_path: Path to the generic file
        db: Database session
    
    Returns:
        Dictionary with processing result
    """
    try:
        # Try to determine file type from content or extension
        file_path_obj = Path(file_path)
        file_extension = file_path_obj.suffix.lower()
        
        if file_extension == '.pdf':
            # Try to process as invoice first
            result = await process_invoice_file(file_path, db)
            if result['success']:
                return result
            
            # Try to process as statement
            result = await process_statement_file(file_path, db)
            if result['success']:
                return result
        
        # If we can't determine the type, skip it
        logger.warning(f"Unable to determine file type for {file_path}, skipping")
        return {
            'success': False,
            'skipped': True,
            'error': f"Unable to determine file type for {file_path}"
        }

    except Exception as e:
        return {
            'success': False,
            'skipped': False,
            'error': f"Error processing generic file {file_path}: {str(e)}"
        }


# Background task wrapper
async def process_extracted_data_background_task(
    converted_files: List[str], 
    failed_files: List[str]
) -> Dict[str, any]:
    """
    Background task wrapper for data processing
    
    Args:
        converted_files: List of successfully converted file paths
        failed_files: List of failed conversion file paths
    
    Returns:
        Dictionary with processing results
    """
    logger.info("Starting background data processing task")
    
    try:
        result = await process_extracted_data(
            converted_files, 
            failed_files, 
            background_processing=True
        )
        
        logger.info("Background data processing task completed")
        return result
        
    except Exception as e:
        error_msg = f"Background data processing task failed: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        
        return {
            'success_count': 0,
            'failed_count': len(converted_files),
            'skipped_count': 0,
            'errors': [error_msg]
        }
