#!/usr/bin/env python3
"""
Delete Duplicate Statements Script
=================================

This script identifies and deletes duplicate statements based on filename.
It keeps the most recent statement and deletes all older duplicates along
with their invoice items.

Usage:
    python scripts/delete_duplicate_statements.py [options]

Options:
    --dry-run               Preview what would be deleted without actually
                            deleting
    --supplier TEXT         Filter by specific supplier name
    --verbose               Enable detailed logging
    --confirm               Skip confirmation prompt
"""

import sys
import os
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict
from pathlib import Path

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.config.logging_config import setup_logging
from mpi_backend.database import get_db
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement, PlumbingInvoice
)

from sqlalchemy.orm import joinedload

# Setup centralized logging
setup_logging()
logger = logging.getLogger(__name__)


class DuplicateCleaner:
    """Cleaner for duplicate statements"""
    
    def __init__(self, dry_run=False, supplier_filter=None, verbose=False):
        self.dry_run = dry_run
        self.supplier_filter = supplier_filter
        self.verbose = verbose
        
        # Statistics tracking
        self.stats = {
            'total_statements': 0,
            'duplicate_groups': 0,
            'statements_to_delete': 0,
            'invoices_to_delete': 0,
            'statements_deleted': 0,
            'invoices_deleted': 0,
            'errors': 0
        }
        
        # Setup logging level
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
    
    def find_duplicate_statements(
        self, db
    ) -> Dict[str, List[PlumbingStatement]]:
        """
        Find duplicate statements based on filename
        
        Returns:
            Dict with filename as key and list of statements as value
        """
        try:
            logger.info("Searching for duplicate statements...")
            
            # Build query
            query = db.query(PlumbingStatement).options(
                joinedload(PlumbingStatement.supplier)
            )
            
            # Apply supplier filter if specified
            if self.supplier_filter:
                query = query.join(PlumbingSupplier).filter(
                    PlumbingSupplier.name.ilike(f"%{self.supplier_filter}%")
                )
                logger.info(f"Filtering by supplier: {self.supplier_filter}")
            
            # Get all statements
            statements = query.all()
            self.stats['total_statements'] = len(statements)
            
            logger.info(f"Found {len(statements)} total statements")
            
            # Group by filename
            filename_groups = defaultdict(list)
            for statement in statements:
                if statement.pdf_filename:
                    filename_groups[statement.pdf_filename].append(statement)
            
            # Filter to only groups with duplicates
            duplicate_groups = {
                filename: statements_list 
                for filename, statements_list in filename_groups.items() 
                if len(statements_list) > 1
            }
            
            self.stats['duplicate_groups'] = len(duplicate_groups)
            
            logger.info(f"Found {len(duplicate_groups)} duplicate groups")
            
            return duplicate_groups
            
        except Exception as e:
            logger.error(f"Error finding duplicate statements: {str(e)}")
            self.stats['errors'] += 1
            return {}
    

    
    def analyze_duplicates(
        self, db, 
        duplicate_groups: Dict[str, List[PlumbingStatement]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze duplicate groups and determine which to keep/delete
        
        Returns:
            List of analysis results for each duplicate group
        """
        analysis_results = []
        
        for filename, statements in duplicate_groups.items():
            try:
                # Sort by creation date (most recent first)
                # Use statement_date as proxy for creation date
                sorted_statements = sorted(
                    statements, 
                    key=lambda s: s.statement_date or datetime.min,
                    reverse=True
                )
                
                # Keep the most recent (first after sorting)
                keep_statement = sorted_statements[0]
                delete_statements = sorted_statements[1:]
                
                # Count invoices for each statement
                keep_invoices = db.query(PlumbingInvoice).filter(
                    PlumbingInvoice.statement_id == keep_statement.id
                ).count()
                
                delete_invoices = 0
                for delete_stmt in delete_statements:
                    invoice_count = db.query(PlumbingInvoice).filter(
                        PlumbingInvoice.statement_id == delete_stmt.id
                    ).count()
                    delete_invoices += invoice_count
                
                analysis_result = {
                    'filename': filename,
                    'keep_statement': keep_statement,
                    'delete_statements': delete_statements,
                    'keep_invoices': keep_invoices,
                    'delete_invoices': delete_invoices,
                    'supplier_name': (
                        keep_statement.supplier.name 
                        if keep_statement.supplier else 'Unknown'
                    )
                }
                
                analysis_results.append(analysis_result)
                
                # Update statistics
                self.stats['statements_to_delete'] += len(delete_statements)
                self.stats['invoices_to_delete'] += delete_invoices
                
                if self.verbose:
                    logger.debug(f"Duplicate group: {filename}")
                    logger.debug(
                        f"  Keep: Statement {keep_statement.id} "
                        f"({keep_statement.statement_date}) - {keep_invoices} invoices"
                    )
                    for delete_stmt in delete_statements:
                        logger.debug(
                            f"  Delete: Statement {delete_stmt.id} "
                            f"({delete_stmt.statement_date})"
                        )
                
            except Exception as e:
                logger.error(
                    f"Error analyzing duplicates for {filename}: {str(e)}"
                )
                self.stats['errors'] += 1
                continue
        
        return analysis_results
    

    
    def delete_duplicates(
        self, db, analysis_results: List[Dict[str, Any]]
    ) -> bool:
        """
        Delete duplicate statements and their invoices
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(
                f"Starting deletion of {len(analysis_results)} duplicate groups..."
            )
            
            for analysis in analysis_results:
                try:
                    filename = analysis['filename']
                    delete_statements = analysis['delete_statements']
                    delete_invoices = analysis['delete_invoices']
                    keep_statement = analysis['keep_statement']
                    
                    logger.info(f"Processing duplicates for: {filename}")
                    logger.info(
                        f"  Keeping: Statement {keep_statement.id} "
                        f"({keep_statement.statement_date})"
                    )
                    logger.info(
                        f"  Deleting: {len(delete_statements)} statements "
                        f"with {delete_invoices} invoices"
                    )
                    
                    if self.dry_run:
                        logger.info(
                            f"[DRY RUN] Would delete {len(delete_statements)} "
                            f"statements and {delete_invoices} invoices"
                        )
                        continue
                    
                    # Delete invoices first (foreign key constraint)
                    for delete_stmt in delete_statements:
                        invoice_count = db.query(PlumbingInvoice).filter(
                            PlumbingInvoice.statement_id == delete_stmt.id
                        ).count()
                        
                        if invoice_count > 0:
                            db.query(PlumbingInvoice).filter(
                                PlumbingInvoice.statement_id == delete_stmt.id
                            ).delete()
                            self.stats['invoices_deleted'] += invoice_count
                            logger.debug(
                                f"  Deleted {invoice_count} invoices "
                                f"from statement {delete_stmt.id}"
                            )
                    
                    # Delete the statements
                    for delete_stmt in delete_statements:
                        db.delete(delete_stmt)
                        self.stats['statements_deleted'] += 1
                        logger.debug(f"  Deleted statement {delete_stmt.id}")
                    
                    # Commit after each group to avoid large transactions
                    db.commit()
                    logger.info(
                        f"  Successfully deleted duplicates for {filename}"
                    )
                    
                except Exception as e:
                    logger.error(
                        f"Error deleting duplicates for {analysis['filename']}: {str(e)}"
                    )
                    db.rollback()
                    self.stats['errors'] += 1
                    continue
            
            logger.info("Duplicate deletion completed")
            return True
            
        except Exception as e:
            logger.error(f"Error in delete_duplicates: {str(e)}")
            self.stats['errors'] += 1
            return False
    

    
    def print_analysis(
        self, analysis_results: List[Dict[str, Any]]
    ):
        """Print analysis of duplicates"""
        print("\n" + "="*80)
        print("DUPLICATE STATEMENTS ANALYSIS")
        print("="*80)
        
        if not analysis_results:
            print("✅ No duplicate statements found!")
            return
        
        print(f"Found {len(analysis_results)} duplicate groups:")
        print()
        
        for i, analysis in enumerate(analysis_results, 1):
            filename = analysis['filename']
            keep_stmt = analysis['keep_statement']
            delete_count = len(analysis['delete_statements'])
            delete_invoices = analysis['delete_invoices']
            supplier = analysis['supplier_name']
            
            print(f"{i}. {filename}")
            print(f"   Supplier: {supplier}")
            print(
                f"   Keep: Statement {keep_stmt.id} "
                f"({keep_stmt.statement_date}) - {analysis['keep_invoices']} invoices"
            )
            print(
                f"   Delete: {delete_count} statements with {delete_invoices} invoices"
            )
            print()
        
        print("="*80)
        print("SUMMARY:")
        print(f"  Total statements to keep: {len(analysis_results)}")
        print(
            f"  Total statements to delete: {self.stats['statements_to_delete']}"
        )
        print(
            f"  Total invoices to delete: {self.stats['invoices_to_delete']}"
        )
        print("="*80)
    

    
    def print_summary(self):
        """Print summary of the operation"""
        print("\n" + "="*60)
        print("DUPLICATE CLEANUP SUMMARY")
        print("="*60)
        print(
            f"Total statements scanned:    {self.stats['total_statements']:,}"
        )
        print(
            f"Duplicate groups found:      {self.stats['duplicate_groups']:,}"
        )
        print(
            f"Statements deleted:          {self.stats['statements_deleted']:,}"
        )
        print(
            f"Invoices deleted:            {self.stats['invoices_deleted']:,}"
        )
        

        
        print(
            f"Errors:                      {self.stats['errors']:,}"
        )
        print("="*60)
        
        if self.dry_run:
            print("⚠️  DRY RUN MODE - No actual deletions performed")
        else:
            print("✅ Duplicate cleanup completed successfully")
        print("="*60)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Delete duplicate statements based on filename",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview duplicates without deleting
  python scripts/delete_duplicate_statements.py --dry-run
  
  # Delete duplicates for all suppliers
  python scripts/delete_duplicate_statements.py --confirm
  
  # Delete duplicates for specific supplier
  python scripts/delete_duplicate_statements.py --supplier "World Wide Plumbing" 
  --confirm
  

  
  # Verbose mode with confirmation
  python scripts/delete_duplicate_statements.py --verbose --confirm
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--supplier',
        type=str,
        help='Filter by specific supplier name'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable detailed logging'
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Skip confirmation prompt'
    )

    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print("🧹 Duplicate Statement Cleaner")
    print("="*50)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual deletions will be performed")
    else:
        print(
            "⚠️  WARNING: This will permanently delete duplicate statements "
            "and their invoices!"
        )
        print("   Only the most recent statements will be kept.")
        
        if not args.confirm:
            confirmation = input(
                "\nAre you sure you want to continue? (y/N): "
            )
            if confirmation.lower() != 'y':
                print("Operation cancelled.")
                return 0
    
    # Create cleaner and run
    try:
        cleaner = DuplicateCleaner(
            dry_run=args.dry_run,
            supplier_filter=args.supplier,
            verbose=args.verbose
        )
        
        # Get database session
        db = next(get_db())
        
        try:
            # Find and process statement duplicates
            duplicate_groups = cleaner.find_duplicate_statements(db)
            
            if duplicate_groups:
                # Analyze duplicates
                analysis_results = cleaner.analyze_duplicates(
                    db, duplicate_groups
                )
                
                # Print analysis
                cleaner.print_analysis(analysis_results)
                
                if not args.dry_run:
                    # Perform deletion
                    success = cleaner.delete_duplicates(db, analysis_results)
                    if not success:
                        print("\n❌ Statement duplicate cleanup failed!")
                        return 1
            else:
                print("✅ No duplicate statements found!")
            

            
            if args.dry_run:
                print(
                    "🔍 Dry run completed. Use --confirm to perform actual deletion."
                )
                return 0
            
            # Print final summary
            cleaner.print_summary()
            print("\n✅ Duplicate cleanup completed successfully!")
                
        finally:
            db.close()
            
    except KeyboardInterrupt:
        print("\n⚠️  Operation interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        print(f"\n❌ Critical error: {str(e)}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main()) 