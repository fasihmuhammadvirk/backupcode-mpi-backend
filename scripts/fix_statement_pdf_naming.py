#!/usr/bin/env python3
"""
Fix Statement PDF Naming Issues

This script addresses the specific issue where statement PDF filenames
cause S3 key mismatches due to double .pdf extensions.

Issues addressed:
1. Database stores 'filename.PDF' but S3 key becomes 'filename.PDF.pdf'
2. Frontend can't download statements due to key mismatch
3. Inconsistent filename handling across upload/download

Solution:
1. Normalize all PDF filenames in database to not have extensions
2. Update S3 utils to handle extensions properly
3. Ensure consistent behavior for upload/download
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database.models.statement_models import PlumbingStatement
from mpi_backend.database import get_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def normalize_statement_filenames(dry_run=True):
    """
    Normalize statement PDF filenames to prevent S3 key issues
    
    This function:
    1. Finds all statements with PDF filenames that have extensions
    2. Removes the .pdf/.PDF extension from the database filename
    3. This ensures S3 upload/download logic works correctly
    """
    logger.info("Starting statement filename normalization...")
    
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        # Find statements with PDF extensions in filename
        statements = db.query(PlumbingStatement).filter(
            PlumbingStatement.pdf_filename.isnot(None),
            PlumbingStatement.pdf_filename != ''
        ).all()
        
        statements_to_fix = []
        
        for stmt in statements:
            filename = stmt.pdf_filename
            if filename and (filename.lower().endswith('.pdf') or 
                           filename.lower().endswith('.PDF')):
                # Remove the extension
                base_name = filename[:-4]  # Remove last 4 characters (.pdf/.PDF)
                statements_to_fix.append({
                    'id': stmt.id,
                    'old_filename': filename,
                    'new_filename': base_name
                })
        
        logger.info(f"Found {len(statements_to_fix)} statements to normalize")
        
        if not statements_to_fix:
            logger.info("No statements need filename normalization")
            return True
        
        # Show what will be changed
        for stmt_info in statements_to_fix:
            logger.info(f"Statement {stmt_info['id']}:")
            logger.info(f"  Old: {stmt_info['old_filename']}")
            logger.info(f"  New: {stmt_info['new_filename']}")
        
        if not dry_run:
            # Apply changes
            for stmt_info in statements_to_fix:
                stmt = db.query(PlumbingStatement).filter(
                    PlumbingStatement.id == stmt_info['id']
                ).first()
                
                if stmt:
                    stmt.pdf_filename = stmt_info['new_filename']
                    logger.info(f"Updated statement {stmt_info['id']}")
            
            db.commit()
            logger.info(f"Successfully updated {len(statements_to_fix)} statements")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during normalization: {e}")
        if not dry_run:
            db.rollback()
        return False
    finally:
        db.close()


def verify_statement_downloads():
    """
    Verify that all statements now have consistent S3 key patterns
    """
    logger.info("Verifying statement download patterns...")
    
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        statements = db.query(PlumbingStatement).filter(
            PlumbingStatement.pdf_filename.isnot(None),
            PlumbingStatement.pdf_filename != ''
        ).all()
        
        issues_found = []
        
        for stmt in statements:
            filename = stmt.pdf_filename
            
            # Check for issues
            if filename.lower().endswith('.pdf'):
                issues_found.append({
                    'id': stmt.id,
                    'filename': filename,
                    'issue': 'Filename still has .pdf extension'
                })
            
            # Expected S3 key after our fix
            expected_s3_key = f"statements/{filename}.pdf"
            logger.info(f"Statement {stmt.id}: {expected_s3_key}")
        
        if issues_found:
            logger.warning(f"Found {len(issues_found)} remaining issues:")
            for issue in issues_found:
                logger.warning(f"  Statement {issue['id']}: {issue['issue']}")
            return False
        else:
            logger.info("✅ All statements have consistent filename patterns")
            return True
        
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        return False
    finally:
        db.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix statement PDF naming issues')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Run in dry-run mode (default)')
    parser.add_argument('--apply-fixes', action='store_true',
                        help='Actually apply fixes (disables dry-run)')
    parser.add_argument('--verify-only', action='store_true',
                        help='Only verify current state')
    
    args = parser.parse_args()
    
    # Determine run mode
    dry_run = not args.apply_fixes
    
    if args.apply_fixes:
        logger.warning("LIVE MODE - Changes will be applied to the database!")
        confirmation = input("Are you sure you want to proceed? (yes/no): ")
        if confirmation.lower() != 'yes':
            logger.info("Operation cancelled by user")
            return
    
    try:
        if args.verify_only:
            # Just verify
            success = verify_statement_downloads()
            if success:
                logger.info("✅ Verification passed")
            else:
                logger.error("❌ Issues found")
            return
        
        # Fix filenames
        logger.info("Fixing statement PDF filename issues...")
        success = normalize_statement_filenames(dry_run=dry_run)
        
        if success:
            logger.info("✅ Statement filename normalization completed")
            
            # Verify results
            if not dry_run:
                verify_statement_downloads()
        else:
            logger.error("❌ Statement filename normalization failed")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 