#!/usr/bin/env python3
"""
Reprocess Files Utility

This utility allows reprocessing of previously processed files
with enhanced error handling and logging.
"""

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from mpi_backend.database import get_async_db
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.utils.invoice_convertor import convert_invoice_for_email

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_session():
    """Get database session for reprocessing"""
    async for db in get_async_db():
        try:
            yield db
        finally:
            await db.close()


async def reprocess_files(
    file_paths: list,
    existing_invoice_id: str = None,
    background_processing: bool = False
) -> dict:
    """
    Reprocess files with enhanced error handling
    
    Args:
        file_paths: List of file paths to reprocess
        existing_invoice_id: Optional existing invoice ID to preserve
        background_processing: Whether this is running as background task
    
    Returns:
        Dictionary with reprocessing results
    """
    logger.info(f"Starting reprocessing of {len(file_paths)} files")
    
    if background_processing:
        logger.info("Running in background processing mode")
    
    if existing_invoice_id:
        logger.info(f"Reprocessing mode: Preserving invoice ID {existing_invoice_id}")
    
    results = {
        'success_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
        'errors': [],
        'reprocessed_files': []
    }
    
    try:
        # Convert files first
        logger.info("Starting file conversion")
        converted_files, failed_files = convert_invoice_for_email(
            base_folder_path=Path("."),
            file_paths=file_paths
        )
        
        logger.info(f"Conversion complete. Success: {len(converted_files)}, "
                   f"Failed: {len(failed_files)}")
        
        # Process converted files
        if converted_files:
            logger.info("Starting data processing for converted files")
            processing_result = await process_extracted_data(
                converted_files, 
                failed_files,
                background_processing=background_processing
            )
            
            # Aggregate results
            results['success_count'] = processing_result.get('success_count', 0)
            results['failed_count'] = processing_result.get('failed_count', 0)
            results['skipped_count'] = processing_result.get('skipped_count', 0)
            results['errors'].extend(processing_result.get('errors', []))
            results['reprocessed_files'] = converted_files
        
        # Handle failed files
        if failed_files:
            logger.warning(f"Found {len(failed_files)} failed conversion files")
            results['failed_count'] += len(failed_files)
            for failed_file in failed_files:
                results['errors'].append(f"Failed conversion: {failed_file}")
        
        logger.info(f"Reprocessing complete. "
                   f"Success: {results['success_count']}, "
                   f"Failed: {results['failed_count']}, "
                   f"Skipped: {results['skipped_count']}")
        
        return results
        
    except Exception as e:
        error_msg = f"Critical error in reprocessing: {str(e)}"
        logger.error(error_msg)
        results['errors'].append(error_msg)
        results['failed_count'] = len(file_paths)
        return results


async def reprocess_single_file(
    file_path: str,
    existing_invoice_id: str = None
) -> dict:
    """
    Reprocess a single file
    
    Args:
        file_path: Path to the file to reprocess
        existing_invoice_id: Optional existing invoice ID to preserve
    
    Returns:
        Dictionary with reprocessing result
    """
    logger.info(f"Reprocessing single file: {file_path}")
    
    try:
        result = await reprocess_files(
            [file_path], 
            existing_invoice_id,
            background_processing=False
        )
        
        return result
        
    except Exception as e:
        error_msg = f"Error reprocessing {file_path}: {str(e)}"
        logger.error(error_msg)
        return {
            'success_count': 0,
            'failed_count': 1,
            'skipped_count': 0,
            'errors': [error_msg],
            'reprocessed_files': []
        }


async def reprocess_directory(
    directory_path: str,
    file_pattern: str = "*.pdf",
    existing_invoice_id: str = None
) -> dict:
    """
    Reprocess all files in a directory matching a pattern
    
    Args:
        directory_path: Path to directory containing files
        file_pattern: File pattern to match (default: *.pdf)
        existing_invoice_id: Optional existing invoice ID to preserve
    
    Returns:
        Dictionary with reprocessing results
    """
    logger.info(f"Reprocessing directory: {directory_path} with pattern: {file_pattern}")
    
    try:
        directory = Path(directory_path)
        
        if not directory.exists():
            error_msg = f"Directory not found: {directory_path}"
            logger.error(error_msg)
            return {
                'success_count': 0,
                'failed_count': 0,
                'skipped_count': 0,
                'errors': [error_msg],
                'reprocessed_files': []
            }
        
        # Find matching files
        matching_files = list(directory.glob(file_pattern))
        
        if not matching_files:
            logger.info(f"No files found matching pattern: {file_pattern}")
            return {
                'success_count': 0,
                'failed_count': 0,
                'skipped_count': 0,
                'errors': [],
                'reprocessed_files': []
            }
        
        logger.info(f"Found {len(matching_files)} files to reprocess")
        
        # Convert file paths to strings
        file_paths = [str(f) for f in matching_files]
        
        # Reprocess all files
        result = await reprocess_files(
            file_paths,
            existing_invoice_id,
            background_processing=False
        )
        
        return result
        
    except Exception as e:
        error_msg = f"Error reprocessing directory {directory_path}: {str(e)}"
        logger.error(error_msg)
        return {
            'success_count': 0,
            'failed_count': 0,
            'skipped_count': 0,
            'errors': [error_msg],
            'reprocessed_files': []
        }


# Background task wrapper
async def reprocess_files_background_task(
    file_paths: list,
    existing_invoice_id: str = None
) -> dict:
    """
    Background task wrapper for reprocessing files
    
    Args:
        file_paths: List of file paths to reprocess
        existing_invoice_id: Optional existing invoice ID to preserve
    
    Returns:
        Dictionary with reprocessing results
    """
    logger.info("Starting background reprocessing task")
    
    try:
        result = await reprocess_files(
            file_paths,
            existing_invoice_id,
            background_processing=True
        )
        
        logger.info("Background reprocessing task completed")
        return result
        
    except Exception as e:
        error_msg = f"Background reprocessing task failed: {str(e)}"
        logger.error(error_msg)
        
        return {
            'success_count': 0,
            'failed_count': len(file_paths),
            'skipped_count': 0,
            'errors': [error_msg],
            'reprocessed_files': []
        }


# Main execution function for standalone use
async def main():
    """Main function for standalone execution"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python reprocess-files.py <file_path> [existing_invoice_id]")
        print("   or: python reprocess-files.py --directory <dir_path> [pattern]")
        sys.exit(1)
    
    try:
        if sys.argv[1] == "--directory":
            if len(sys.argv) < 3:
                print("Error: Directory path required")
                sys.exit(1)
            
            directory_path = sys.argv[2]
            file_pattern = sys.argv[3] if len(sys.argv) > 3 else "*.pdf"
            
            result = await reprocess_directory(directory_path, file_pattern)
        else:
            file_path = sys.argv[1]
            existing_invoice_id = sys.argv[2] if len(sys.argv) > 2 else None
            
            result = await reprocess_single_file(file_path, existing_invoice_id)
        
        # Print results
        print(f"\nReprocessing Results:")
        print(f"Success: {result['success_count']}")
        print(f"Failed: {result['failed_count']}")
        print(f"Skipped: {result['skipped_count']}")
        
        if result['errors']:
            print(f"\nErrors:")
            for error in result['errors']:
                print(f"  - {error}")
        
        if result['reprocessed_files']:
            print(f"\nReprocessed Files:")
            for file_path in result['reprocessed_files']:
                print(f"  - {file_path}")
        
        # Exit with appropriate code
        if result['failed_count'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
