#!/usr/bin/env python3
"""
Direct Statement Reprocessing Script

This script directly uses the StatementController to reprocess all statements
in the database. It bypasses the API endpoint and works directly with the database.

This approach is simpler and doesn't require authentication or API server setup.
"""

import sys
import os
import argparse
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add the parent directory to Python path to import mpi_backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import SessionLocal
from mpi_backend.database.controllers.StatementController import StatementController


def get_all_statement_ids(db, supplier_filter=None) -> List[int]:
    """
    Get all statement IDs from the database
    
    Args:
        db: Database session
        supplier_filter: Optional supplier filter
        
    Returns:
        List of statement IDs
    """
    try:
        controller = StatementController(db)
        
        # Get all statements with a very large limit
        statements = controller.get_statements_summary(
            supplier_id=0 if supplier_filter == '0' else None,
            limit=100000  # Very large limit to get all statements
        )
        
        # Extract statement IDs
        statement_ids = [stmt['id'] for stmt in statements]
        
        print(f"Found {len(statement_ids)} statements in database")
        return statement_ids
        
    except Exception as e:
        print(f"Error getting statement IDs: {str(e)}")
        return []


def reprocess_single_statement(controller: StatementController, statement_id: int) -> Dict[str, Any]:
    """
    Reprocess a single statement using the controller
    
    Args:
        controller: StatementController instance
        statement_id: ID of the statement to reprocess
        
    Returns:
        Result dictionary from reprocessing
    """
    try:
        print(f"  Processing Statement ID {statement_id}...")
        result = controller.reprocess_statement(statement_id)
        return result
    except Exception as e:
        return {
            'success': False,
            'error': f'Exception processing statement {statement_id}: {str(e)}'
        }


def reprocess_all_statements_direct(supplier_filter: Optional[str] = None,
                                   max_statements: int = 100,
                                   batch_size: int = 10) -> Dict[str, Any]:
    """
    Reprocess all statements directly using the controller
    
    Args:
        supplier_filter: Optional supplier filter
        max_statements: Maximum number of statements to process
        batch_size: Number of statements to process in each batch
        
    Returns:
        Summary of processing results
    """
    print(f"\n{'='*80}")
    print("REPROCESSING ALL STATEMENTS (DIRECT CONTROLLER)")
    print("="*80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Supplier Filter: {supplier_filter or 'ALL SUPPLIERS'}")
    print(f"Max Statements: {max_statements}")
    print(f"Batch Size: {batch_size}")
    print("="*80)
    
    # Get all statement IDs from database
    db = SessionLocal()
    try:
        statement_ids = get_all_statement_ids(db, supplier_filter)
        if not statement_ids:
            return {
                'success': False,
                'error': 'No statements found to process'
            }
        
        # Limit the number of statements to process
        if max_statements and len(statement_ids) > max_statements:
            statement_ids = statement_ids[:max_statements]
            print(f"Limited to {max_statements} statements")
        
        print(f"Processing {len(statement_ids)} statements")
        
        # Create controller instance
        controller = StatementController(db)
        
        # Process statements in batches
        total_batches = (len(statement_ids) + batch_size - 1) // batch_size
        all_results = []
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(statement_ids))
            batch_ids = statement_ids[start_idx:end_idx]
            
            print(f"\n{'='*60}")
            print(f"PROCESSING BATCH {batch_num + 1}/{total_batches}")
            print(f"Statements {start_idx + 1} to {end_idx} of {len(statement_ids)}")
            print("="*60)
            
            batch_results = []
            batch_successful = 0
            batch_failed = 0
            batch_supplier_changes = 0
            
            for i, statement_id in enumerate(batch_ids, 1):
                global_index = start_idx + i
                print(f"\n[{global_index}/{len(statement_ids)}] Processing Statement ID {statement_id}")
                
                result = reprocess_single_statement(controller, statement_id)
                
                if result.get('success'):
                    batch_successful += 1
                    details = result.get('details', {})
                    supplier_changed = details.get('supplier_changed', False)
                    
                    if supplier_changed:
                        batch_supplier_changes += 1
                        old_supplier = details.get('old_supplier_name', 'Unknown')
                        new_supplier = details.get('supplier_name', 'Unknown')
                        print(f"  ⚠️  SUPPLIER CHANGED: {old_supplier} → {new_supplier}")
                    else:
                        invoices_processed = details.get('invoices_processed', 0)
                        print(f"  ✅ SUCCESS: {invoices_processed} invoices processed")
                else:
                    batch_failed += 1
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ❌ FAILED: {error_msg}")
                
                batch_results.append({
                    'statement_id': statement_id,
                    'result': result
                })
                
                # Small delay between statements
                time.sleep(0.5)
            
            # Batch summary
            print(f"\n{'='*40}")
            print(f"BATCH {batch_num + 1} SUMMARY")
            print("="*40)
            print(f"Successful: {batch_successful}")
            print(f"Failed: {batch_failed}")
            print(f"Supplier Changes: {batch_supplier_changes}")
            
            all_results.extend(batch_results)
            
            # Overall progress
            total_processed_so_far = len(all_results)
            total_successful_so_far = sum(1 for r in all_results if r['result'].get('success'))
            success_rate = (total_successful_so_far / total_processed_so_far * 100) if total_processed_so_far > 0 else 0
            
            print(f"\n{'='*40}")
            print(f"OVERALL PROGRESS: {total_processed_so_far}/{len(statement_ids)}")
            print(f"Success Rate: {success_rate:.1f}%")
            print("="*40)
            
            # Ask for confirmation to continue (optional)
            if batch_num < total_batches - 1:
                print(f"\nPress Enter to continue to next batch, or 'q' to quit...")
                try:
                    user_input = input().strip().lower()
                    if user_input == 'q':
                        print(f"\nStopping at user request. Processed {total_processed_so_far}/{len(statement_ids)} statements.")
                        break
                except KeyboardInterrupt:
                    print(f"\nStopping at user request. Processed {total_processed_so_far}/{len(statement_ids)} statements.")
                    break
        
        # Compile final results
        total_processed = len(all_results)
        total_successful = sum(1 for r in all_results if r['result'].get('success'))
        total_failed = total_processed - total_successful
        total_supplier_changes = sum(
            1 for r in all_results 
            if r['result'].get('success') and r['result'].get('details', {}).get('supplier_changed', False)
        )
        
        success_rate = (total_successful / total_processed * 100) if total_processed > 0 else 0
        
        return {
            'success': True,
            'summary': {
                'total_processed': total_processed,
                'total_successful': total_successful,
                'total_failed': total_failed,
                'total_supplier_changes': total_supplier_changes,
                'success_rate': success_rate
            },
            'detailed_results': all_results
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Processing error: {str(e)}'
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description='Reprocess all statements directly using the controller'
    )
    parser.add_argument(
        '--supplier', 
        type=str, 
        help='Filter by supplier name or ID (use 0 for all suppliers)'
    )
    parser.add_argument(
        '--max-statements', 
        type=int, 
        default=100, 
        help='Maximum number of statements to process (default: 100)'
    )
    parser.add_argument(
        '--batch-size', 
        type=int, 
        default=10, 
        help='Number of statements to process in each batch (default: 10)'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='Show what would be processed without actually doing it'
    )
    parser.add_argument(
        '--output', 
        type=str, 
        help='Output file for detailed results (JSON format)'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("DIRECT STATEMENT REPROCESSING SCRIPT")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Supplier Filter: {args.supplier or 'ALL SUPPLIERS'}")
    print(f"Max Statements: {args.max_statements}")
    print(f"Batch Size: {args.batch_size}")
    print(f"Dry Run: {args.dry_run}")
    print("=" * 80)
    
    if args.dry_run:
        print("\nDRY RUN - Showing what would be processed:")
        print("-" * 50)
        
        # Get statement IDs for dry run
        db = SessionLocal()
        try:
            statement_ids = get_all_statement_ids(db, args.supplier)
            if statement_ids:
                print(f"Found {len(statement_ids)} statements to process")
                
                # Show sample of statement IDs
                sample_ids = statement_ids[:10]
                print(f"Sample statement IDs: {sample_ids}")
                
                if len(statement_ids) > 10:
                    print(f"... and {len(statement_ids) - 10} more")
                
                estimated_batches = (len(statement_ids) + args.batch_size - 1) // args.batch_size
                print(f"Estimated batches: {estimated_batches}")
            else:
                print("No statements found to process")
        finally:
            db.close()
        return
    
    # Confirm before starting
    print(f"\n⚠️  WARNING: This will reprocess up to {args.max_statements} statements!")
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
    result = reprocess_all_statements_direct(
        supplier_filter=args.supplier,
        max_statements=args.max_statements,
        batch_size=args.batch_size
    )
    
    # Display results
    if result['success']:
        summary = result['summary']
        print("\n" + "=" * 80)
        print("REPROCESSING COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print(f"Total Processed: {summary['total_processed']}")
        print(f"Successful: {summary['total_successful']}")
        print(f"Failed: {summary['total_failed']}")
        print(f"Supplier Changes: {summary['total_supplier_changes']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        
        if summary['total_supplier_changes'] > 0:
            print(f"\n⚠️  SUPPLIER CORRECTIONS: {summary['total_supplier_changes']} statements had supplier corrections!")
            print("   This indicates previous misassignments that have now been fixed.")
        
        # Save detailed results to JSON if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\nDetailed results saved to: {args.output}")
    else:
        print(f"\n❌ REPROCESSING FAILED: {result.get('error')}")
    
    print(f"\nReprocessing completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main() 