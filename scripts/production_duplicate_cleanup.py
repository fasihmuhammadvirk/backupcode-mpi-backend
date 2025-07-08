#!/usr/bin/env python3
"""
Production script to clean duplicate invoices and statements.

This script safely removes:
1. Duplicate statement invoices (same ref_no + supplier, keeps newest)
2. Duplicate statements (same PDF filename, keeps first)

Features:
- Safe execution with rollback on errors
- Comprehensive logging
- Dry run mode for testing
- Database backup recommendation
- Production safety checks
"""

import sys
import os
import logging
from collections import defaultdict
from datetime import datetime

# Setup imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database.models.statement_models import (
    PlumbingStatement, PlumbingInvoice, PlumbingSupplier
)
from mpi_backend.database import get_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'duplicate_cleanup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("production_duplicate_cleanup")


class DuplicateCleanup:
    """Production-safe duplicate cleanup utility."""
    
    def __init__(self, db):
        self.db = db
        self.stats = {
            'duplicate_invoices_found': 0,
            'duplicate_statements_found': 0,
            'invoices_deleted': 0,
            'statements_deleted': 0,
            'errors': 0
        }
    
    def analyze_duplicate_invoices(self):
        """Find duplicate invoices by ref_no + supplier."""
        logger.info("Analyzing duplicate statement invoices...")
        
        try:
            # Get all statement invoices with supplier info
            stmt_invoices = self.db.query(
                PlumbingInvoice, PlumbingStatement, PlumbingSupplier
            ).join(
                PlumbingStatement, 
                PlumbingInvoice.statement_id == PlumbingStatement.id
            ).join(
                PlumbingSupplier, 
                PlumbingStatement.supplier_id == PlumbingSupplier.id
            ).filter(
                PlumbingInvoice.invoice_number.isnot(None),
                PlumbingInvoice.invoice_number != ""
            ).all()
            
            # Group by (ref_no, supplier_id)
            groups = defaultdict(list)
            for invoice, statement, supplier in stmt_invoices:
                key = (invoice.invoice_number.strip(), supplier.id)
                groups[key].append({
                    'invoice': invoice,
                    'statement': statement,
                    'supplier': supplier
                })
            
            # Find duplicates
            duplicates = {k: v for k, v in groups.items() if len(v) > 1}
            
            self.stats['duplicate_invoices_found'] = sum(
                len(inv) - 1 for inv in duplicates.values()
            )
            
            logger.info(f"Found {len(duplicates)} ref_no+supplier combinations with duplicates")
            logger.info(f"Total duplicate invoices: {self.stats['duplicate_invoices_found']}")
            
            return duplicates
            
        except Exception as e:
            logger.error(f"Error analyzing duplicate invoices: {str(e)}")
            self.stats['errors'] += 1
            return {}
    
    def analyze_duplicate_statements(self):
        """Find duplicate statements by PDF filename."""
        logger.info("Analyzing duplicate statements by PDF...")
        
        try:
            statements = self.db.query(PlumbingStatement).all()
            groups = defaultdict(list)
            
            for stmt in statements:
                if stmt.pdf_filename and stmt.pdf_filename.strip():
                    groups[stmt.pdf_filename.strip()].append(stmt)
            
            duplicates = {k: v for k, v in groups.items() if len(v) > 1}
            
            self.stats['duplicate_statements_found'] = sum(
                len(stmts) - 1 for stmts in duplicates.values()
            )
            
            logger.info(f"Found {len(duplicates)} PDF files with duplicate statements")
            logger.info(f"Total duplicate statements: {self.stats['duplicate_statements_found']}")
            
            return duplicates
            
        except Exception as e:
            logger.error(f"Error analyzing duplicate statements: {str(e)}")
            self.stats['errors'] += 1
            return {}
    
    def remove_duplicate_invoices(self, duplicates, dry_run=True):
        """Remove duplicate invoices, keeping the newest."""
        if not duplicates:
            logger.info("No duplicate invoices to remove")
            return 0
        
        deleted_count = 0
        
        try:
            for (ref_no, supplier_id), invoice_list in duplicates.items():
                # Sort by statement date (newest first), then by statement ID
                invoice_list.sort(key=lambda x: (
                    x['statement'].statement_date or datetime.min,
                    x['statement'].id
                ), reverse=True)
                
                # Keep the first (newest), delete the rest
                to_keep = invoice_list[0]
                to_delete = invoice_list[1:]
                
                supplier_name = to_keep['supplier'].name
                
                logger.info(f"Processing ref_no='{ref_no}' from '{supplier_name}':")
                logger.info(f"  Keeping invoice from statement {to_keep['statement'].id} "
                           f"(date: {to_keep['statement'].statement_date})")
                
                for item in to_delete:
                    invoice_id = item['invoice'].id
                    statement_id = item['statement'].id
                    statement_date = item['statement'].statement_date
                    
                    if dry_run:
                        logger.info(f"  [DRY RUN] Would delete invoice {invoice_id} "
                                   f"from statement {statement_id} "
                                   f"(date: {statement_date})")
                    else:
                        logger.info(f"  Deleting invoice {invoice_id} "
                                   f"from statement {statement_id}")
                        self.db.delete(item['invoice'])
                        deleted_count += 1
            
            if not dry_run and deleted_count > 0:
                self.db.commit()
                logger.info(f"Successfully deleted {deleted_count} duplicate invoices")
                self.stats['invoices_deleted'] = deleted_count
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error removing duplicate invoices: {str(e)}")
            if not dry_run:
                self.db.rollback()
            self.stats['errors'] += 1
            return 0
    
    def remove_duplicate_statements(self, duplicates, dry_run=True):
        """Remove duplicate statements, keeping the first."""
        if not duplicates:
            logger.info("No duplicate statements to remove")
            return 0
        
        deleted_count = 0
        
        try:
            for pdf_filename, statements in duplicates.items():
                # Keep the first statement (oldest ID)
                statements.sort(key=lambda x: x.id)
                to_keep = statements[0]
                to_delete = statements[1:]
                
                logger.info(f"Processing PDF '{pdf_filename}':")
                logger.info(f"  Keeping statement {to_keep.id}")
                
                for stmt in to_delete:
                    # Count invoices that will be deleted
                    invoice_count = self.db.query(PlumbingInvoice).filter(
                        PlumbingInvoice.statement_id == stmt.id
                    ).count()
                    
                    if dry_run:
                        logger.info(f"  [DRY RUN] Would delete statement {stmt.id} "
                                   f"and {invoice_count} invoices")
                    else:
                        logger.info(f"  Deleting statement {stmt.id} "
                                   f"and {invoice_count} invoices")
                        # Delete invoices first (foreign key constraint)
                        self.db.query(PlumbingInvoice).filter(
                            PlumbingInvoice.statement_id == stmt.id
                        ).delete()
                        self.db.delete(stmt)
                        deleted_count += 1
            
            if not dry_run and deleted_count > 0:
                self.db.commit()
                logger.info(f"Successfully deleted {deleted_count} duplicate statements")
                self.stats['statements_deleted'] = deleted_count
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error removing duplicate statements: {str(e)}")
            if not dry_run:
                self.db.rollback()
            self.stats['errors'] += 1
            return 0
    
    def get_database_stats(self):
        """Get current database statistics."""
        try:
            return {
                'statements': self.db.query(PlumbingStatement).count(),
                'plumbing_invoices': self.db.query(PlumbingInvoice).count(),
                'total_processing_time': datetime.now()
            }
        except Exception as e:
            logger.error(f"Error getting database stats: {str(e)}")
            return {}
    
    def print_summary(self):
        """Print cleanup summary."""
        logger.info("\n" + "="*60)
        logger.info("CLEANUP SUMMARY")
        logger.info("="*60)
        logger.info(f"Duplicate invoices found: {self.stats['duplicate_invoices_found']}")
        logger.info(f"Duplicate statements found: {self.stats['duplicate_statements_found']}")
        logger.info(f"Invoices deleted: {self.stats['invoices_deleted']}")
        logger.info(f"Statements deleted: {self.stats['statements_deleted']}")
        logger.info(f"Errors encountered: {self.stats['errors']}")
        logger.info("="*60)


def production_safety_check():
    """Perform production safety checks."""
    logger.info("Performing production safety checks...")
    
    # Check if we're in a production environment
    env_indicators = [
        os.getenv('ENVIRONMENT'),
        os.getenv('ENV'),
        os.getenv('NODE_ENV')
    ]
    
    is_production = any(
        env and env.lower() in ['production', 'prod', 'live'] 
        for env in env_indicators
    )
    
    if is_production:
        logger.warning("PRODUCTION ENVIRONMENT DETECTED!")
        logger.warning("Please ensure you have:")
        logger.warning("1. Created a database backup")
        logger.warning("2. Tested this script in staging")
        logger.warning("3. Notified the team")
        
        response = input("Continue in production? (type 'CONFIRM' to proceed): ")
        if response != 'CONFIRM':
            logger.info("Production safety check failed. Exiting.")
            return False
    
    return True


def main():
    """Main execution function."""
    logger.info("Starting production duplicate cleanup")
    
    # Production safety check
    if not production_safety_check():
        return
    
    # Get database connection
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        # Initialize cleanup utility
        cleanup = DuplicateCleanup(db)
        
        # Get initial database stats
        initial_stats = cleanup.get_database_stats()
        logger.info(f"Initial database stats: {initial_stats}")
        
        # Analyze duplicates
        logger.info("\n" + "="*60)
        logger.info("ANALYSIS PHASE")
        logger.info("="*60)
        
        duplicate_invoices = cleanup.analyze_duplicate_invoices()
        duplicate_statements = cleanup.analyze_duplicate_statements()
        
        if not duplicate_invoices and not duplicate_statements:
            logger.info("No duplicates found! Database is clean.")
            return
        
        # Show dry run results
        logger.info("\n" + "="*60)
        logger.info("DRY RUN PREVIEW")
        logger.info("="*60)
        
        cleanup.remove_duplicate_invoices(duplicate_invoices, dry_run=True)
        cleanup.remove_duplicate_statements(duplicate_statements, dry_run=True)
        
        # Ask for confirmation
        logger.info("\n" + "="*60)
        print("Review the dry run results above.")
        response = input("Proceed with actual cleanup? (yes/no): ").strip().lower()
        
        if response in ['yes', 'y']:
            logger.info("\n" + "="*60)
            logger.info("EXECUTING CLEANUP")
            logger.info("="*60)
            
            # Perform actual cleanup
            cleanup.remove_duplicate_invoices(duplicate_invoices, dry_run=False)
            cleanup.remove_duplicate_statements(duplicate_statements, dry_run=False)
            
            # Get final stats
            final_stats = cleanup.get_database_stats()
            logger.info(f"Final database stats: {final_stats}")
            
            # Print summary
            cleanup.print_summary()
            
            if cleanup.stats['errors'] == 0:
                logger.info("Cleanup completed successfully!")
            else:
                logger.warning(f"Cleanup completed with {cleanup.stats['errors']} errors. "
                              "Check logs for details.")
        else:
            logger.info("Cleanup cancelled by user.")
            
    except Exception as e:
        logger.error(f"Critical error during cleanup: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()