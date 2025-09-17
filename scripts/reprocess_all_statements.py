#!/usr/bin/env python3
"""
Reprocess All Statements Script

This script fetches all statement IDs from the database and uses the same code
as the /statements/reprocess endpoint to reprocess each statement one by one.
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
    Reprocess a single statement using the same code as the endpoint
    
    Args:
        controller: StatementController instance
        statement_id: ID of the statement to reprocess
        
    Returns:
        Result dictionary from reprocessing
    """
    try:
        print(f"  Processing Statement ID {statement_id}...")
        
        # This is the same code as in the /statements/reprocess endpoint
        # The controller.reprocess_statement method handles all the logic
        result = controller.reprocess_statement(statement_id)
        
        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Exception processing statement {statement_id}: {str(e)}'
        }


def reprocess_all_statements(supplier_filter: Optional[str] = None,
                            max_statements: int = 100) -> Dict[str, Any]:
    """
    Reprocess all statements using the same code as the endpoint
    
    Args:
        supplier_filter: Optional supplier filter
        max_statements: Maximum number of statements to process
        
    Returns:
        Summary of processing results
    """
    print(f"\n{'='*80}")
    print("REPROCESSING ALL STATEMENTS")
    print("="*80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Supplier Filter: {supplier_filter or 'ALL SUPPLIERS'}")
    print(f"Max Statements: {max_statements}")
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
        
        # Process statements one by one
        all_results = []
        successful = 0
        failed = 0
        supplier_changes = 0
        
        for i, statement_id in enumerate(statement_ids, 1):
            print(f"\n[{i}/{len(statement_ids)}] Processing Statement ID {statement_id}")
            
            # Use the same code as the endpoint
            result = reprocess_single_statement(controller, statement_id)
            
            if result.get('success'):
                successful += 1
                details = result.get('details', {})
                supplier_changed = details.get('supplier_changed', False)
                
                if supplier_changed:
                    supplier_changes += 1
                    old_supplier = details.get('old_supplier_name', 'Unknown')
                    new_supplier = details.get('supplier_name', 'Unknown')
                    print(f"  ⚠️  SUPPLIER CHANGED: {old_supplier} → {new_supplier}")
                else:
                    invoices_processed = details.get('invoices_processed', 0)
                    print(f"  ✅ SUCCESS: {invoices_processed} invoices processed")
            else:
                failed += 1
                error_msg = result.get('error', 'Unknown error')
                print(f"  ❌ FAILED: {error_msg}")
            
            all_results.append({
                'statement_id': statement_id,
                'result': result
            })
            
            # Small delay between statements
            time.sleep(0.5)
            
            # Progress update every 10 statements
            if i % 10 == 0:
                success_rate = (successful / i * 100)
                print(f"\n  📊 PROGRESS: {i}/{len(statement_ids)} ({success_rate:.1f}% success)")
        
        # Final summary
        success_rate = (successful / len(statement_ids) * 100) if statement_ids else 0
        
        return {
            'success': True,
            'summary': {
                'total_processed': len(statement_ids),
                'successful': successful,
                'failed': failed,
                'supplier_changes': supplier_changes,
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
        description='Reprocess all statements using the same code as the endpoint'
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
    print("REPROCESS ALL STATEMENTS")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Supplier Filter: {args.supplier or 'ALL SUPPLIERS'}")
    print(f"Max Statements: {args.max_statements}")
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
                
                if args.max_statements and len(statement_ids) > args.max_statements:
                    print(f"Would process first {args.max_statements} statements")
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
    result = reprocess_all_statements(
        supplier_filter=args.supplier,
        max_statements=args.max_statements
    )
    
    # Display results
    if result['success']:
        summary = result['summary']
        print("\n" + "=" * 80)
        print("REPROCESSING COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print(f"Total Processed: {summary['total_processed']}")
        print(f"Successful: {summary['successful']}")
        print(f"Failed: {summary['failed']}")
        print(f"Supplier Changes: {summary['supplier_changes']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        
        if summary['supplier_changes'] > 0:
            print(f"\n⚠️  SUPPLIER CORRECTIONS: {summary['supplier_changes']} statements had supplier corrections!")
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