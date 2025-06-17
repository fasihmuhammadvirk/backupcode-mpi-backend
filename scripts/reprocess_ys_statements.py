#!/usr/bin/env python3
"""
Script to reprocess all Y&S monthly statements with improved extraction logic.

This script will:
1. Find all Y&S statements in the database
2. Delete existing statement and invoice records
3. Re-extract using the new specialized Y&S extractor
4. Save updated data to database

Usage:
    python scripts/reprocess_ys_statements.py [--dry-run] [--limit N]
    
Options:
    --dry-run    Show what would be processed without making changes
    --limit N    Limit processing to N statements (for testing)
    --force      Skip confirmation prompts
"""

import sys
import os
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement, PlumbingInvoice
)
from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
from mpi_backend.utils.s3_utils import get_presigned_url
from mpi_backend.config import BUCKET_NAME

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)



def get_ys_statements(db_session, limit=None):
    """Get all Y&S statements from the database"""
    try:
        # Get Y&S supplier
        ys_supplier = db_session.query(PlumbingSupplier).filter(
            PlumbingSupplier.name == "Y & S Plumbing Supply"
        ).first()
        
        if not ys_supplier:
            logger.error("Y & S Plumbing Supply supplier not found in database")
            return []
        
        # Get all Y&S statements
        query = db_session.query(PlumbingStatement).filter(
            PlumbingStatement.supplier_id == ys_supplier.id
        ).order_by(PlumbingStatement.statement_date.desc())
        
        if limit:
            query = query.limit(limit)
        
        statements = query.all()
        logger.info(f"Found {len(statements)} Y&S statements in database")
        
        return statements
        
    except Exception as e:
        logger.error(f"Error fetching Y&S statements: {str(e)}")
        return []

def get_statement_pdf_path(statement):
    """Get the S3 path or local path for the statement PDF"""
    try:
        # Try S3 path first
        s3_key = f"statements/{statement.pdf_filename}"
        try:
            s3_url = get_presigned_url(s3_key, expiration_time=3600, is_invoice=False)
            if s3_url:
                logger.debug(f"Found S3 URL for {statement.pdf_filename}")
                return s3_url
        except Exception as s3_error:
            logger.debug(f"S3 access failed for {statement.pdf_filename}: {s3_error}")
        
        # Try local path as fallback
        local_path = Path(f"storage/statements/{statement.pdf_filename}")
        if local_path.exists():
            logger.debug(f"Found local file for {statement.pdf_filename}")
            return str(local_path)
        
        logger.warning(f"PDF file not found for statement {statement.id}: {statement.pdf_filename}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting PDF path for statement {statement.id}: {str(e)}")
        return None

def delete_existing_statement_data(db_session, statement_id):
    """Delete existing statement and associated invoice records"""
    try:
        # Delete associated invoices first (foreign key constraint)
        invoice_count = db_session.query(PlumbingInvoice).filter(
            PlumbingInvoice.statement_id == statement_id
        ).count()
        
        db_session.query(PlumbingInvoice).filter(
            PlumbingInvoice.statement_id == statement_id
        ).delete()
        
        # Delete the statement
        statement_deleted = db_session.query(PlumbingStatement).filter(
            PlumbingStatement.id == statement_id
        ).delete()
        
        if statement_deleted:
            logger.info(f"Deleted statement {statement_id} and {invoice_count} associated invoices")
            return True
        else:
            logger.error(f"Failed to delete statement {statement_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error deleting statement {statement_id}: {str(e)}")
        return False

def reprocess_statement(statement, pdf_path, db_session, dry_run=False):
    """Reprocess a single Y&S statement"""
    try:
        logger.info(f"Processing statement {statement.id}: {statement.pdf_filename}")
        logger.info(f"  Original date: {statement.statement_date}")
        logger.info(f"  Original total: ${statement.total_amount}")
        logger.info(f"  Original invoices: {statement.total_invoices}")
        
        if dry_run:
            logger.info("  [DRY RUN] Would reprocess this statement")
            return {"success": True, "dry_run": True}
        
        # Delete existing records
        if not delete_existing_statement_data(db_session, statement.id):
            return {"success": False, "error": "Failed to delete existing records"}
        
        db_session.commit()
        
        # Re-extract using the new Y&S extractor
        logger.info(f"Re-extracting data using specialized Y&S extractor...")
        
        extractor = StatementExtractor(
            pdf_path=pdf_path,
            save_to_db=True,
            db_session=db_session,
            supplier_name="Y & S Plumbing Supply"
        )
        
        # Process the statement
        result = extractor.process_statement()
        
        if result.get('success', False):
            new_statement = extractor.statement_obj
            logger.info(f"✅ Successfully reprocessed statement {statement.id}")
            logger.info(f"  New total: ${new_statement.total_amount}")
            logger.info(f"  New invoices: {new_statement.total_invoices}")
            
            return {
                "success": True,
                "original_total": float(statement.total_amount or 0),
                "new_total": float(new_statement.total_amount or 0),
                "original_invoices": statement.total_invoices,
                "new_invoices": new_statement.total_invoices
            }
        else:
            error_msg = result.get('error_message', 'Unknown error during extraction')
            logger.error(f"❌ Failed to reprocess statement {statement.id}: {error_msg}")
            return {"success": False, "error": error_msg}
            
    except Exception as e:
        logger.error(f"❌ Error reprocessing statement {statement.id}: {str(e)}")
        return {"success": False, "error": str(e)}

def main():
    """Main function to reprocess Y&S statements"""
    parser = argparse.ArgumentParser(description="Reprocess Y&S monthly statements")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Show what would be processed without making changes")
    parser.add_argument("--limit", type=int, 
                       help="Limit processing to N statements (for testing)")
    parser.add_argument("--force", action="store_true",
                       help="Skip confirmation prompts")
    
    args = parser.parse_args()
    
    logger.info("🚀 Starting Y&S statement reprocessing...")
    logger.info(f"🔧 Mode: {'DRY RUN' if args.dry_run else 'LIVE PROCESSING'}")
    
    if args.limit:
        logger.info(f"📊 Limit: Processing max {args.limit} statements")
    
    # Get database session
    db_session = SessionLocal()
    
    try:
        # Get Y&S statements
        statements = get_ys_statements(db_session, limit=args.limit)
        
        if not statements:
            logger.warning("No Y&S statements found to process")
            return
        
        logger.info(f"📋 Found {len(statements)} Y&S statements to process")
        
        # Show summary and get confirmation
        if not args.dry_run and not args.force:
            print(f"\n⚠️  WARNING: This will reprocess {len(statements)} Y&S statements")
            print("   This will delete existing records and re-extract data")
            print("   Make sure you have a database backup!")
            
            response = input("\nDo you want to continue? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                logger.info("Operation cancelled by user")
                return
        
        # Process statements
        results = {
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "total_amount_diff": 0.0,
            "total_invoice_diff": 0
        }
        
        for i, statement in enumerate(statements, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing {i}/{len(statements)}: Statement {statement.id}")
            logger.info(f"{'='*60}")
            
            # Get PDF path
            pdf_path = get_statement_pdf_path(statement)
            
            if not pdf_path:
                logger.warning(f"Skipping statement {statement.id}: PDF not found")
                results["skipped"] += 1
                continue
            
            # Process the statement
            result = reprocess_statement(statement, pdf_path, db_session, args.dry_run)
            results["processed"] += 1
            
            if result["success"]:
                results["successful"] += 1
                if not args.dry_run and not result.get("dry_run", False):
                    # Track improvements
                    amount_diff = result["new_total"] - result["original_total"]
                    invoice_diff = result["new_invoices"] - result["original_invoices"]
                    
                    results["total_amount_diff"] += amount_diff
                    results["total_invoice_diff"] += invoice_diff
                    
                    if amount_diff != 0:
                        logger.info(f"💰 Amount difference: ${amount_diff:+.2f}")
                    if invoice_diff != 0:
                        logger.info(f"📊 Invoice count difference: {invoice_diff:+d}")
            else:
                results["failed"] += 1
                logger.error(f"Failed: {result.get('error', 'Unknown error')}")
        
        # Final summary
        logger.info(f"\n{'='*80}")
        logger.info("📋 REPROCESSING SUMMARY")
        logger.info(f"{'='*80}")
        logger.info(f"Total statements found: {len(statements)}")
        logger.info(f"Statements processed: {results['processed']}")
        logger.info(f"Successfully reprocessed: {results['successful']}")
        logger.info(f"Failed: {results['failed']}")
        logger.info(f"Skipped (PDF not found): {results['skipped']}")
        
        if not args.dry_run and results["successful"] > 0:
            logger.info(f"\n💰 Total amount difference: ${results['total_amount_diff']:+.2f}")
            logger.info(f"📊 Total invoice count difference: {results['total_invoice_diff']:+d}")
            
            if results["total_amount_diff"] > 0:
                logger.info("✅ Improved extraction captured more invoice amounts")
            elif results["total_amount_diff"] < 0:
                logger.warning("⚠️  New extraction shows lower amounts - verify results")
            
            if results["total_invoice_diff"] > 0:
                logger.info("✅ Improved extraction found more invoices")
            elif results["total_invoice_diff"] < 0:
                logger.warning("⚠️  New extraction shows fewer invoices - verify results")
        
        success_rate = (results["successful"] / results["processed"] * 100) if results["processed"] > 0 else 0
        logger.info(f"\n🎯 Success rate: {success_rate:.1f}%")
        
        if args.dry_run:
            logger.info("\n💡 This was a dry run. Use without --dry-run to actually reprocess.")
        elif results["successful"] > 0:
            logger.info("\n🎉 Y&S statement reprocessing completed!")
            logger.info("✅ Statements now use improved Y&S extraction logic")
        
    except Exception as e:
        logger.error(f"❌ Error during reprocessing: {str(e)}")
        db_session.rollback()
    
    finally:
        db_session.close()

if __name__ == "__main__":
    main() 