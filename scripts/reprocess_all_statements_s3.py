#!/usr/bin/env python3
"""
Complete S3 Statement Reprocessing Script

This script reprocesses ALL statements in the database using S3 PDFs.
It provides comprehensive options for filtering, batch processing, and detailed reporting.
"""

import sys
import os
import argparse
from datetime import datetime
import pandas as pd

# Add the parent directory to Python path to import mpi_backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import SessionLocal
from mpi_backend.database.controllers.StatementController import StatementController


def get_all_statements(db, supplier_filter=None):
    """Get ALL statements from the database"""
    controller = StatementController(db)
    
    # Get a very large number to ensure we get all statements
    statements = controller.get_statements_summary(
        supplier_id=0 if supplier_filter == '0' else None,
        limit=100000  # Very large limit to get all statements
    )
    
    return statements


def reprocess_all_statements_s3(db, statements, batch_size=50, start_from=0):
    """
    Reprocess ALL statements using S3 PDFs with batch processing
    
    Args:
        db: Database session
        statements: List of all statements to process
        batch_size: Number of statements to process in each batch
        start_from: Index to start processing from (for resuming)
    """
    controller = StatementController(db)
    
    total_statements = len(statements)
    results = []
    statistics = {
        'total': total_statements,
        'successful': 0,
        'failed': 0,
        'supplier_changes': 0,
        'errors': [],
        'processed': 0
    }
    
    print(f"\n{'='*80}")
    print(f"STARTING COMPLETE REPROCESSING OF ALL STATEMENTS")
    print(f"{'='*80}")
    print(f"Total Statements: {total_statements}")
    print(f"Batch Size: {batch_size}")
    print(f"Starting From: {start_from}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}")
    
    # Process statements in batches
    for batch_start in range(start_from, total_statements, batch_size):
        batch_end = min(batch_start + batch_size, total_statements)
        batch_statements = statements[batch_start:batch_end]
        
        print(f"\n{'='*60}")
        print(f"PROCESSING BATCH {batch_start//batch_size + 1}")
        print(f"Statements {batch_start + 1} to {batch_end} of {total_statements}")
        print(f"{'='*60}")
        
        batch_results = []
        batch_stats = {
            'successful': 0,
            'failed': 0,
            'supplier_changes': 0,
            'errors': []
        }
        
        for i, stmt in enumerate(batch_statements, 1):
            global_index = batch_start + i
            print(f"\n[{global_index}/{total_statements}] Processing Statement ID {stmt['id']}")
            print(f"  Supplier: {stmt['supplier_name']}")
            print(f"  Date: {stmt['statement_date']}")
            print(f"  Invoices: {stmt['total_invoices']}")
            
            try:
                # Reprocess the statement using S3
                result = controller.reprocess_statement(stmt['id'])
                
                if result['success']:
                    batch_stats['successful'] += 1
                    statistics['successful'] += 1
                    
                    details = result.get('details', {})
                    supplier_changed = details.get('supplier_changed', False)
                    
                    if supplier_changed:
                        batch_stats['supplier_changes'] += 1
                        statistics['supplier_changes'] += 1
                        print(f"  ⚠️  SUPPLIER CHANGED: {details['old_supplier_name']} → {details['supplier_name']}")
                    else:
                        print(f"  ✅ SUCCESS: {details.get('invoices_processed', 0)} invoices processed")
                    
                    batch_results.append({
                        'statement_id': stmt['id'],
                        'success': True,
                        'supplier_name': details.get('supplier_name', stmt['supplier_name']),
                        'supplier_changed': supplier_changed,
                        'old_supplier_name': details.get('old_supplier_name', stmt['supplier_name']),
                        'invoices_processed': details.get('invoices_processed', 0),
                        'total_amount': details.get('total_amount', 0),
                        'statement_date': stmt['statement_date'],
                        'new_statement_id': details.get('new_statement_id', stmt['id'])
                    })
                    
                else:
                    batch_stats['failed'] += 1
                    statistics['failed'] += 1
                    error_msg = result.get('error', 'Unknown error')
                    batch_stats['errors'].append(f"Statement {stmt['id']}: {error_msg}")
                    statistics['errors'].append(f"Statement {stmt['id']}: {error_msg}")
                    print(f"  ❌ FAILED: {error_msg}")
                    
                    batch_results.append({
                        'statement_id': stmt['id'],
                        'success': False,
                        'error': error_msg,
                        'supplier_name': stmt['supplier_name'],
                        'statement_date': stmt['statement_date']
                    })
                    
            except Exception as e:
                batch_stats['failed'] += 1
                statistics['failed'] += 1
                error_msg = f"Exception: {str(e)}"
                batch_stats['errors'].append(f"Statement {stmt['id']}: {error_msg}")
                statistics['errors'].append(f"Statement {stmt['id']}: {error_msg}")
                print(f"  ❌ EXCEPTION: {error_msg}")
                
                batch_results.append({
                    'statement_id': stmt['id'],
                    'success': False,
                    'error': error_msg,
                    'supplier_name': stmt['supplier_name'],
                    'statement_date': stmt['statement_date']
                })
            
            statistics['processed'] += 1
            
            # Progress update every 10 statements
            if global_index % 10 == 0:
                success_rate = (statistics['successful'] / statistics['processed']) * 100
                print(f"\n  📊 PROGRESS: {statistics['processed']}/{total_statements} ({success_rate:.1f}% success)")
        
        # Batch summary
        print(f"\n{'='*40}")
        print(f"BATCH {batch_start//batch_size + 1} SUMMARY")
        print(f"{'='*40}")
        print(f"Successful: {batch_stats['successful']}")
        print(f"Failed: {batch_stats['failed']}")
        print(f"Supplier Changes: {batch_stats['supplier_changes']}")
        
        if batch_stats['errors']:
            print(f"\nBatch Errors:")
            for error in batch_stats['errors'][:5]:  # Show first 5 errors
                print(f"  - {error}")
            if len(batch_stats['errors']) > 5:
                print(f"  ... and {len(batch_stats['errors']) - 5} more errors")
        
        results.extend(batch_results)
        
        # Overall progress
        overall_success_rate = (statistics['successful'] / statistics['processed']) * 100
        print(f"\n{'='*40}")
        print(f"OVERALL PROGRESS: {statistics['processed']}/{total_statements}")
        print(f"Success Rate: {overall_success_rate:.1f}%")
        print(f"Supplier Changes: {statistics['supplier_changes']}")
        print(f"{'='*40}")
        
        # Ask for confirmation to continue (optional)
        if batch_start + batch_size < total_statements:
            print(f"\nPress Enter to continue to next batch, or 'q' to quit...")
            try:
                user_input = input().strip().lower()
                if user_input == 'q':
                    print(f"\nStopping at user request. Processed {statistics['processed']}/{total_statements} statements.")
                    break
            except KeyboardInterrupt:
                print(f"\nStopping at user request. Processed {statistics['processed']}/{total_statements} statements.")
                break
    
    return results, statistics


def main():
    parser = argparse.ArgumentParser(
        description='Reprocess ALL statements in the database using S3 PDFs'
    )
    parser.add_argument(
        '--supplier', 
        type=str, 
        help='Filter by supplier name or ID (use 0 for all suppliers)'
    )
    parser.add_argument(
        '--batch-size', 
        type=int, 
        default=50, 
        help='Number of statements to process in each batch (default: 50)'
    )
    parser.add_argument(
        '--start-from', 
        type=int, 
        default=0, 
        help='Index to start processing from (for resuming interrupted runs)'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='Show what would be processed without actually doing it'
    )
    parser.add_argument(
        '--output', 
        type=str, 
        help='Output file for detailed results (CSV format)'
    )
    parser.add_argument(
        '--summary-only', 
        action='store_true', 
        help='Show only summary statistics, not detailed progress'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("COMPLETE S3 STATEMENT REPROCESSING SCRIPT")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Supplier Filter: {args.supplier or 'ALL SUPPLIERS'}")
    print(f"Batch Size: {args.batch_size}")
    print(f"Start From: {args.start_from}")
    print(f"Dry Run: {args.dry_run}")
    print(f"Summary Only: {args.summary_only}")
    print("=" * 80)
    
    # Create database session
    db = SessionLocal()
    try:
        # Get ALL statements
        print("\nFetching all statements from database...")
        statements = get_all_statements(db, args.supplier)
        
        if not statements:
            print("No statements found to process.")
            return
        
        print(f"Found {len(statements)} statements to process")
        
        if args.dry_run:
            print("\nDRY RUN - Showing what would be processed:")
            print("-" * 50)
            
            # Show sample of statements
            for i, stmt in enumerate(statements[:10]):
                print(f"  {i+1}. ID: {stmt['id']}, Supplier: {stmt['supplier_name']}, "
                      f"Date: {stmt['statement_date']}, Invoices: {stmt['total_invoices']}")
            
            if len(statements) > 10:
                print(f"  ... and {len(statements) - 10} more statements")
            
            print(f"\nTotal: {len(statements)} statements would be reprocessed")
            print(f"Estimated batches: {len(statements) // args.batch_size + 1}")
            return
        
        # Confirm before starting
        if not args.summary_only:
            print(f"\n⚠️  WARNING: This will reprocess ALL {len(statements)} statements!")
            print("This operation will:")
            print("  - Delete existing statement and invoice records")
            print("  - Re-extract data from S3 PDFs")
            print("  - Create new records with potentially corrected supplier assignments")
            print("  - Potentially change supplier assignments")
            
            print(f"\nPress Enter to continue, or 'q' to quit...")
            try:
                user_input = input().strip().lower()
                if user_input == 'q':
                    print("Operation cancelled.")
                    return
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                return
        
        # Process all statements
        if args.summary_only:
            print("\nProcessing with summary-only mode...")
            # Use the existing controller method for summary processing
            controller = StatementController(db)
            result = controller.reprocess_all_statements(
                supplier_name=args.supplier,
                max_statements=len(statements)
            )
            
            if result['success']:
                stats = result['statistics']
                print(f"\n✅ REPROCESSING COMPLETED!")
                print("=" * 50)
                print(f"Total Statements: {stats['total_statements']}")
                print(f"Successful: {stats['successful']}")
                print(f"Failed: {stats['failed']}")
                print(f"Supplier Changes: {stats['supplier_changes']}")
                
                success_rate = (stats['successful'] / stats['total_statements']) * 100
                print(f"Success Rate: {success_rate:.1f}%")
                
                if stats['supplier_changes'] > 0:
                    print(f"\n⚠️  SUPPLIER CORRECTIONS: {stats['supplier_changes']} statements had supplier corrections!")
            else:
                print(f"\n❌ REPROCESSING FAILED: {result.get('error')}")
        else:
            # Process with detailed progress
            results, statistics = reprocess_all_statements_s3(
                db, statements, args.batch_size, args.start_from
            )
            
            # Final summary
            print("\n" + "=" * 80)
            print("FINAL REPROCESSING SUMMARY")
            print("=" * 80)
            print(f"Total Statements: {statistics['total']}")
            print(f"Processed: {statistics['processed']}")
            print(f"Successful: {statistics['successful']}")
            print(f"Failed: {statistics['failed']}")
            print(f"Supplier Changes: {statistics['supplier_changes']}")
            
            success_rate = (statistics['successful'] / statistics['processed']) * 100
            print(f"Success Rate: {success_rate:.1f}%")
            
            if statistics['supplier_changes'] > 0:
                print(f"\n⚠️  SUPPLIER CORRECTIONS: {statistics['supplier_changes']} statements had supplier corrections!")
                print("   This indicates previous misassignments that have now been fixed.")
            
            if statistics['errors']:
                print(f"\nErrors encountered ({len(statistics['errors'])} total):")
                for error in statistics['errors'][:10]:  # Show first 10 errors
                    print(f"  - {error}")
                if len(statistics['errors']) > 10:
                    print(f"  ... and {len(statistics['errors']) - 10} more errors")
            
            # Save detailed results to CSV if requested
            if args.output:
                df = pd.DataFrame(results)
                df.to_csv(args.output, index=False)
                print(f"\nDetailed results saved to: {args.output}")
        
        print(f"\nReprocessing completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
    except Exception as e:
        print(f"\n❌ SCRIPT ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        
    finally:
        db.close()
        print(f"\nDatabase connection closed.")


if __name__ == "__main__":
    main() 