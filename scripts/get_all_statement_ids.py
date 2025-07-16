#!/usr/bin/env python3
"""
Get All Statement IDs Script

This script fetches all statement IDs from the database and displays them
with additional information like supplier name, statement date, and PDF filename.
"""

import sys
import os
import argparse
import json
from datetime import datetime
from typing import List, Dict, Any

# Add the parent directory to Python path to import mpi_backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpi_backend.database import SessionLocal
from mpi_backend.database.controllers.StatementController import StatementController


def get_all_statements_with_details(db) -> List[Dict[str, Any]]:
    """
    Get all statements with full details from the database
    
    Args:
        db: Database session
        
    Returns:
        List of statement dictionaries with details
    """
    try:
        controller = StatementController(db)
        
        # Get all statements with a very large limit
        statements = controller.get_statements_summary(
            supplier_id=0,  # Get all suppliers
            limit=100000  # Very large limit to get all statements
        )
        
        print(f"Found {len(statements)} statements in database")
        return statements
        
    except Exception as e:
        print(f"Error getting statements: {str(e)}")
        return []


def get_statement_ids_only(db) -> List[int]:
    """
    Get only statement IDs from the database
    
    Args:
        db: Database session
        
    Returns:
        List of statement IDs
    """
    try:
        controller = StatementController(db)
        
        # Get all statements with a very large limit
        statements = controller.get_statements_summary(
            supplier_id=0,  # Get all suppliers
            limit=100000  # Very large limit to get all statements
        )
        
        # Extract statement IDs
        statement_ids = [stmt['id'] for stmt in statements]
        
        print(f"Found {len(statement_ids)} statement IDs in database")
        return statement_ids
        
    except Exception as e:
        print(f"Error getting statement IDs: {str(e)}")
        return []


def main():
    parser = argparse.ArgumentParser(
        description='Get all statement IDs from the database'
    )
    parser.add_argument(
        '--ids-only', 
        action='store_true', 
        help='Show only statement IDs (one per line)'
    )
    parser.add_argument(
        '--supplier', 
        type=str, 
        help='Filter by supplier name or ID'
    )
    parser.add_argument(
        '--output', 
        type=str, 
        help='Output file for results (JSON format)'
    )
    parser.add_argument(
        '--csv', 
        type=str, 
        help='Output file for results (CSV format)'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("GET ALL STATEMENT IDS")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Supplier Filter: {args.supplier or 'ALL SUPPLIERS'}")
    print("=" * 80)
    
    # Get statements from database
    db = SessionLocal()
    try:
        if args.ids_only:
            # Get only IDs
            statement_ids = get_statement_ids_only(db)
            
            if args.supplier:
                # Filter by supplier if specified
                all_statements = get_all_statements_with_details(db)
                filtered_statements = [
                    stmt for stmt in all_statements 
                    if args.supplier.lower() in stmt.get('supplier_name', '').lower()
                ]
                statement_ids = [stmt['id'] for stmt in filtered_statements]
                print(f"Filtered to {len(statement_ids)} statements for supplier: {args.supplier}")
            
            # Print IDs only
            for statement_id in statement_ids:
                print(statement_id)
            
            # Save to file if requested
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(statement_ids, f, indent=2)
                print(f"\nStatement IDs saved to: {args.output}")
                
        else:
            # Get full details
            statements = get_all_statements_with_details(db)
            
            if args.supplier:
                # Filter by supplier if specified
                statements = [
                    stmt for stmt in statements 
                    if args.supplier.lower() in stmt.get('supplier_name', '').lower()
                ]
                print(f"Filtered to {len(statements)} statements for supplier: {args.supplier}")
            
            # Display results
            print(f"\nFound {len(statements)} statements:")
            print("-" * 80)
            print(f"{'ID':<6} {'Supplier':<30} {'Statement Date':<15} {'PDF Filename':<40}")
            print("-" * 80)
            
            for stmt in statements:
                statement_id = stmt.get('id', 'N/A')
                supplier_name = stmt.get('supplier_name', 'N/A')[:29]
                statement_date = stmt.get('statement_date', 'N/A')
                pdf_filename = stmt.get('pdf_filename', 'N/A')[:39]
                
                print(f"{statement_id:<6} {supplier_name:<30} {statement_date:<15} {pdf_filename:<40}")
            
            # Save to file if requested
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(statements, f, indent=2, default=str)
                print(f"\nDetailed results saved to: {args.output}")
            
            if args.csv:
                import csv
                with open(args.csv, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['ID', 'Supplier', 'Statement Date', 'PDF Filename'])
                    for stmt in statements:
                        writer.writerow([
                            stmt.get('id', ''),
                            stmt.get('supplier_name', ''),
                            stmt.get('statement_date', ''),
                            stmt.get('pdf_filename', '')
                        ])
                print(f"CSV results saved to: {args.csv}")
        
        print(f"\nTotal statements: {len(statements) if not args.ids_only else len(statement_ids)}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    main() 