#!/usr/bin/env python3
"""
Fix Statement S3 Key Issues Script

This script addresses the S3 key mismatch issue where:
1. Database stores filename as 'filename.PDF' 
2. S3 upload adds '.pdf' suffix, creating 'filename.PDF.pdf'
3. Download tries to access 'statements/filename.PDF.pdf'
4. But should access 'statements/filename.PDF' without additional .pdf

The script will:
1. Analyze current statement S3 keys and mismatches
2. Fix database pdf_filename entries to match actual S3 keys
3. Update any statements with incorrect S3 key references
4. Verify all statements can be downloaded correctly

Usage:
python scripts/fix_statement_s3_keys.py [--dry-run] [--fix-all]
"""

import sys
import os
import logging
import argparse
import boto3
from datetime import datetime
from typing import Dict, List, Tuple
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database.models.statement_models import (
    PlumbingStatement, PlumbingSupplier
)
from mpi_backend.database import get_db
from mpi_backend.config import (
    AWS_SERVER_PUBLIC_KEY, 
    AWS_SERVER_SECRET_KEY, 
    REGION, 
    BUCKET_NAME
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'statement_s3_fix_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class StatementS3KeyFixer:
    """Fix S3 key issues for statements"""
    
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.s3_client = self._init_s3_client()
        self.stats = {
            'total_statements': 0,
            'missing_s3_files': 0,
            'key_mismatches': 0,
            'fixed_statements': 0,
            'errors': 0,
            'verified_working': 0
        }
    
    def _init_s3_client(self):
        """Initialize S3 client"""
        try:
            return boto3.client(
                's3',
                aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
                aws_secret_access_key=AWS_SERVER_SECRET_KEY,
                region_name=REGION
            )
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise
    
    def analyze_statement_s3_keys(self) -> Dict:
        """Analyze all statements and their S3 key status"""
        logger.info("Analyzing statement S3 keys...")
        
        db_gen = get_db()
        db = next(db_gen)
        
        analysis_results = {
            'statements': [],
            'missing_files': [],
            'key_mismatches': [],
            'working_statements': [],
            'error_statements': []
        }
        
        try:
            # Get all statements with PDF filenames
            statements = db.query(PlumbingStatement).filter(
                PlumbingStatement.pdf_filename.isnot(None),
                PlumbingStatement.pdf_filename != ''
            ).all()
            
            self.stats['total_statements'] = len(statements)
            logger.info(f"Found {len(statements)} statements with PDF filenames")
            
            for stmt in statements:
                stmt_analysis = self._analyze_single_statement(stmt)
                analysis_results['statements'].append(stmt_analysis)
                
                # Categorize based on status
                if stmt_analysis['status'] == 'missing':
                    analysis_results['missing_files'].append(stmt_analysis)
                elif stmt_analysis['status'] == 'mismatch':
                    analysis_results['key_mismatches'].append(stmt_analysis)
                elif stmt_analysis['status'] == 'working':
                    analysis_results['working_statements'].append(stmt_analysis)
                else:
                    analysis_results['error_statements'].append(stmt_analysis)
            
            # Update stats
            self.stats['missing_s3_files'] = len(analysis_results['missing_files'])
            self.stats['key_mismatches'] = len(analysis_results['key_mismatches'])
            self.stats['verified_working'] = len(analysis_results['working_statements'])
            self.stats['errors'] = len(analysis_results['error_statements'])
            
            logger.info("Analysis complete:")
            logger.info(f"  Total statements: {self.stats['total_statements']}")
            logger.info(f"  Working correctly: {self.stats['verified_working']}")
            logger.info(f"  Key mismatches: {self.stats['key_mismatches']}")
            logger.info(f"  Missing S3 files: {self.stats['missing_s3_files']}")
            logger.info(f"  Errors: {self.stats['errors']}")
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            raise
        finally:
            db.close()
    
    def _analyze_single_statement(self, stmt: PlumbingStatement) -> Dict:
        """Analyze a single statement's S3 key status"""
        pdf_filename = stmt.pdf_filename
        statement_info = {
            'statement_id': stmt.id,
            'pdf_filename': pdf_filename,
            'supplier_id': stmt.supplier_id,
            'statement_date': stmt.statement_date.isoformat() if stmt.statement_date else None,
            'status': 'unknown',
            'current_s3_key': None,
            'working_s3_key': None,
            'recommended_fix': None
        }
        
        try:
            # Test different S3 key patterns to see what exists
            test_keys = [
                f"statements/{pdf_filename}",  # Direct filename
                f"statements/{pdf_filename}.pdf",  # With .pdf suffix
            ]
            
            # Remove .pdf and try with .pdf
            if pdf_filename.lower().endswith('.pdf'):
                base_name = pdf_filename[:-4]
                test_keys.append(f"statements/{base_name}")
                test_keys.append(f"statements/{base_name}.pdf")
            
            working_key = None
            for key in test_keys:
                if self._s3_key_exists(key):
                    working_key = key
                    break
            
            if working_key:
                statement_info['working_s3_key'] = working_key
                
                # Determine if current database entry matches working key
                expected_key = f"statements/{pdf_filename}"
                if working_key == expected_key:
                    statement_info['status'] = 'working'
                else:
                    statement_info['status'] = 'mismatch'
                    statement_info['current_s3_key'] = expected_key
                    
                    # Recommend fix
                    if working_key.endswith('.pdf.pdf'):
                        # S3 has double .pdf, fix database
                        new_filename = working_key.replace('statements/', '')
                        statement_info['recommended_fix'] = f"Update pdf_filename to '{new_filename}'"
                    else:
                        # S3 is correct, database might need adjustment
                        new_filename = working_key.replace('statements/', '')
                        statement_info['recommended_fix'] = f"Update pdf_filename to '{new_filename}'"
            else:
                statement_info['status'] = 'missing'
                statement_info['current_s3_key'] = f"statements/{pdf_filename}"
                statement_info['recommended_fix'] = "Upload missing PDF to S3"
            
        except Exception as e:
            logger.error(f"Error analyzing statement {stmt.id}: {e}")
            statement_info['status'] = 'error'
            statement_info['error'] = str(e)
        
        return statement_info
    
    def _s3_key_exists(self, key: str) -> bool:
        """Check if an S3 key exists"""
        try:
            self.s3_client.head_object(Bucket=BUCKET_NAME, Key=key)
            return True
        except self.s3_client.exceptions.NoSuchKey:
            return False
        except Exception as e:
            logger.warning(f"Error checking S3 key {key}: {e}")
            return False
    
    def fix_statement_s3_keys(self, analysis_results: Dict) -> bool:
        """Fix statement S3 key mismatches"""
        logger.info("Starting statement S3 key fixes...")
        
        if self.dry_run:
            logger.info("DRY RUN MODE - No actual changes will be made")
        
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            # Fix key mismatches
            for stmt_info in analysis_results['key_mismatches']:
                if self._fix_single_statement_key(stmt_info, db):
                    self.stats['fixed_statements'] += 1
            
            if not self.dry_run:
                db.commit()
                logger.info("Database changes committed")
            
            return True
            
        except Exception as e:
            logger.error(f"Error during fixes: {e}")
            if not self.dry_run:
                db.rollback()
            return False
        finally:
            db.close()
    
    def _fix_single_statement_key(self, stmt_info: Dict, db) -> bool:
        """Fix a single statement's S3 key"""
        try:
            statement_id = stmt_info['statement_id']
            working_key = stmt_info['working_s3_key']
            
            if not working_key:
                logger.warning(f"No working S3 key found for statement {statement_id}")
                return False
            
            # Extract correct filename from working S3 key
            correct_filename = working_key.replace('statements/', '')
            
            logger.info(f"Fixing statement {statement_id}:")
            logger.info(f"  Current: {stmt_info['pdf_filename']}")
            logger.info(f"  New: {correct_filename}")
            logger.info(f"  Working S3 key: {working_key}")
            
            if not self.dry_run:
                # Update database
                stmt = db.query(PlumbingStatement).filter(
                    PlumbingStatement.id == statement_id
                ).first()
                
                if stmt:
                    stmt.pdf_filename = correct_filename
                    logger.info(f"Updated statement {statement_id} pdf_filename")
                else:
                    logger.error(f"Statement {statement_id} not found in database")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error fixing statement {stmt_info['statement_id']}: {e}")
            return False
    
    def verify_all_statements(self) -> bool:
        """Verify all statements can be accessed correctly"""
        logger.info("Verifying all statements can be accessed...")
        
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            statements = db.query(PlumbingStatement).filter(
                PlumbingStatement.pdf_filename.isnot(None),
                PlumbingStatement.pdf_filename != ''
            ).all()
            
            verification_results = {
                'total': len(statements),
                'working': 0,
                'broken': 0,
                'broken_statements': []
            }
            
            for stmt in statements:
                expected_key = f"statements/{stmt.pdf_filename}"
                
                if self._s3_key_exists(expected_key):
                    verification_results['working'] += 1
                else:
                    verification_results['broken'] += 1
                    verification_results['broken_statements'].append({
                        'id': stmt.id,
                        'pdf_filename': stmt.pdf_filename,
                        'expected_key': expected_key
                    })
            
            logger.info("Verification Results:")
            logger.info(f"  Total statements: {verification_results['total']}")
            logger.info(f"  Working: {verification_results['working']}")
            logger.info(f"  Still broken: {verification_results['broken']}")
            
            if verification_results['broken'] > 0:
                logger.warning("Still broken statements:")
                for broken in verification_results['broken_statements']:
                    logger.warning(f"  ID {broken['id']}: {broken['expected_key']}")
            
            return verification_results['broken'] == 0
            
        except Exception as e:
            logger.error(f"Error during verification: {e}")
            return False
        finally:
            db.close()
    
    def generate_report(self, analysis_results: Dict) -> str:
        """Generate a comprehensive report"""
        report_lines = [
            "=" * 80,
            "STATEMENT S3 KEY ANALYSIS REPORT",
            "=" * 80,
            f"Generated: {datetime.now().isoformat()}",
            f"Mode: {'DRY RUN' if self.dry_run else 'LIVE RUN'}",
            "",
            "SUMMARY:",
            f"  Total statements analyzed: {self.stats['total_statements']}",
            f"  Working correctly: {self.stats['verified_working']}",
            f"  Key mismatches: {self.stats['key_mismatches']}",
            f"  Missing S3 files: {self.stats['missing_s3_files']}",
            f"  Errors: {self.stats['errors']}",
            f"  Statements fixed: {self.stats['fixed_statements']}",
            ""
        ]
        
        if analysis_results['key_mismatches']:
            report_lines.extend([
                "KEY MISMATCHES FOUND:",
                "-" * 40
            ])
            for mismatch in analysis_results['key_mismatches']:
                report_lines.extend([
                    f"Statement ID: {mismatch['statement_id']}",
                    f"  Database filename: {mismatch['pdf_filename']}",
                    f"  Working S3 key: {mismatch['working_s3_key']}",
                    f"  Recommended fix: {mismatch['recommended_fix']}",
                    ""
                ])
        
        if analysis_results['missing_files']:
            report_lines.extend([
                "MISSING S3 FILES:",
                "-" * 40
            ])
            for missing in analysis_results['missing_files']:
                report_lines.extend([
                    f"Statement ID: {missing['statement_id']}",
                    f"  Missing file: {missing['current_s3_key']}",
                    f"  Recommended: {missing['recommended_fix']}",
                    ""
                ])
        
        return "\n".join(report_lines)


def main():
    parser = argparse.ArgumentParser(description='Fix statement S3 key issues')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Run in dry-run mode (default)')
    parser.add_argument('--fix-all', action='store_true',
                        help='Actually apply fixes (disables dry-run)')
    parser.add_argument('--verify-only', action='store_true',
                        help='Only verify existing statements')
    
    args = parser.parse_args()
    
    # Determine run mode
    dry_run = not args.fix_all
    
    if args.fix_all:
        logger.warning("LIVE MODE - Changes will be applied to the database!")
        confirmation = input("Are you sure you want to proceed? (yes/no): ")
        if confirmation.lower() != 'yes':
            logger.info("Operation cancelled by user")
            return
    
    try:
        fixer = StatementS3KeyFixer(dry_run=dry_run)
        
        if args.verify_only:
            # Just verify
            success = fixer.verify_all_statements()
            if success:
                logger.info("✅ All statements verified successfully")
            else:
                logger.error("❌ Some statements still have issues")
            return
        
        # Full analysis and fix process
        logger.info("Starting statement S3 key analysis and fix process...")
        
        # Step 1: Analyze
        analysis_results = fixer.analyze_statement_s3_keys()
        
        # Step 2: Generate report
        report = fixer.generate_report(analysis_results)
        print(report)
        
        # Step 3: Fix if needed
        if analysis_results['key_mismatches']:
            if fixer.fix_statement_s3_keys(analysis_results):
                logger.info("✅ Statement S3 key fixes completed successfully")
            else:
                logger.error("❌ Some fixes failed")
        else:
            logger.info("✅ No fixes needed - all statements working correctly")
        
        # Step 4: Final verification
        if not dry_run:
            logger.info("Performing final verification...")
            if fixer.verify_all_statements():
                logger.info("✅ Final verification passed")
            else:
                logger.warning("⚠️  Some issues remain after fixes")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 