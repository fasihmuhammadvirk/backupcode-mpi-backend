#!/usr/bin/env python3
"""
Script to identify missing sheet name classifications by comparing:
1. Unique sheet names from invoice_items table
2. Unique google_sheet_name from supplier_item_mappings table  
3. Against existing item classifications in item_classification table

This script will help identify which sheet names need classifications added.
"""

import os
import sys
import pandas as pd
from datetime import datetime
from sqlalchemy import distinct
from sqlalchemy.orm import Session

# Add the parent directory to sys.path to allow imports from mpi_backend
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

# Import database components
from mpi_backend.database import SessionLocal
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.ItemClassification import ItemClassification


def get_unique_sheet_names_from_invoice_items(db: Session):
    """
    Get unique sheet names from invoice_items table where sheet_name is not null/empty
    """
    print(" Fetching unique sheet names from invoice_items table...")
    
    result = db.query(distinct(InvoiceItem.sheet_name)).filter(
        InvoiceItem.sheet_name.is_not(None),
        InvoiceItem.sheet_name != ''
    ).all()
    
    # Extract sheet names from result tuples
    sheet_names = {row[0] for row in result if row[0] and row[0].strip()}
    
    print(f"    Found {len(sheet_names)} unique sheet names in invoice_items")
    return sheet_names


def get_unique_sheet_names_from_mappings(db: Session):
    """
    Get unique google_sheet_name from supplier_item_mappings table where not null/empty
    """
    print(" Fetching unique sheet names from supplier_item_mappings table...")
    
    result = db.query(distinct(ItemsMapping.google_sheet_name)).filter(
        ItemsMapping.google_sheet_name.is_not(None),
        ItemsMapping.google_sheet_name != ''
    ).all()
    
    # Extract sheet names from result tuples
    sheet_names = {row[0] for row in result if row[0] and row[0].strip()}
    
    print(f"    Found {len(sheet_names)} unique sheet names in supplier_item_mappings")
    return sheet_names


def get_existing_classifications(db: Session):
    """
    Get existing item classifications from item_classification table
    """
    print(" Fetching existing classifications from item_classification table...")
    
    result = db.query(distinct(ItemClassification.item)).filter(
        ItemClassification.item.is_not(None),
        ItemClassification.item != ''
    ).all()
    
    # Extract item names from result tuples
    classified_items = {row[0] for row in result if row[0] and row[0].strip()}
    
    print(f"    Found {len(classified_items)} existing classifications")
    return classified_items


def analyze_missing_classifications(invoice_sheet_names, mapping_sheet_names, classified_items):
    """
    Analyze which sheet names are missing classifications
    """
    print("\n Analyzing missing classifications...")
    
    # Combine all unique sheet names from both sources
    all_sheet_names = invoice_sheet_names.union(mapping_sheet_names)
    
    # Find missing classifications
    missing_from_invoice_items = invoice_sheet_names - classified_items
    missing_from_mappings = mapping_sheet_names - classified_items
    missing_overall = all_sheet_names - classified_items
    
    # Sort for better readability
    missing_from_invoice_items = sorted(list(missing_from_invoice_items))
    missing_from_mappings = sorted(list(missing_from_mappings))
    missing_overall = sorted(list(missing_overall))
    
    return {
        'all_sheet_names': sorted(list(all_sheet_names)),
        'missing_from_invoice_items': missing_from_invoice_items,
        'missing_from_mappings': missing_from_mappings,
        'missing_overall': missing_overall
    }


def print_summary(invoice_sheet_names, mapping_sheet_names, classified_items, analysis):
    """
    Print a comprehensive summary of the analysis
    """
    print(f"\n" + "="*80)
    print(f" SUMMARY REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"="*80)
    
    print(f"\n COUNTS:")
    print(f"   • Unique sheet names in invoice_items:        {len(invoice_sheet_names)}")
    print(f"   • Unique sheet names in supplier_item_mappings: {len(mapping_sheet_names)}")
    print(f"   • Total unique sheet names (combined):       {len(analysis['all_sheet_names'])}")
    print(f"   • Existing classifications:                  {len(classified_items)}")
    print(f"   • Missing classifications (overall):         {len(analysis['missing_overall'])}")
    
    print(f"\nERROR: MISSING CLASSIFICATIONS BREAKDOWN:")
    print(f"   • Missing from invoice_items only:           {len(analysis['missing_from_invoice_items'])}")
    print(f"   • Missing from supplier_item_mappings only:  {len(analysis['missing_from_mappings'])}")
    print(f"   • Missing overall (from both sources):       {len(analysis['missing_overall'])}")
    
    # Show overlap analysis
    overlap = invoice_sheet_names.intersection(mapping_sheet_names)
    print(f"\n OVERLAP ANALYSIS:")
    print(f"   • Sheet names in both tables:                {len(overlap)}")
    print(f"   • Sheet names only in invoice_items:         {len(invoice_sheet_names - mapping_sheet_names)}")
    print(f"   • Sheet names only in supplier_item_mappings: {len(mapping_sheet_names - invoice_sheet_names)}")


def print_detailed_missing_items(analysis):
    """
    Print detailed lists of missing items
    """
    print(f"\n" + "="*80)
    print(f" DETAILED MISSING CLASSIFICATIONS")
    print(f"="*80)
    
    if analysis['missing_overall']:
        print(f"\nERROR: ALL MISSING CLASSIFICATIONS ({len(analysis['missing_overall'])} items):")
        print(f"   (These sheet names exist in database but have no classification)")
        for i, sheet_name in enumerate(analysis['missing_overall'], 1):
            print(f"   {i:3d}. '{sheet_name}'")
    else:
        print(f"\n NO MISSING CLASSIFICATIONS FOUND!")
        print(f"   All sheet names in the database have corresponding classifications.")
    
    if analysis['missing_from_invoice_items'] and analysis['missing_from_invoice_items'] != analysis['missing_overall']:
        print(f"\n MISSING FROM INVOICE_ITEMS ONLY ({len(analysis['missing_from_invoice_items'])} items):")
        for i, sheet_name in enumerate(analysis['missing_from_invoice_items'], 1):
            print(f"   {i:3d}. '{sheet_name}'")
    
    if analysis['missing_from_mappings'] and analysis['missing_from_mappings'] != analysis['missing_overall']:
        print(f"\n  MISSING FROM SUPPLIER_ITEM_MAPPINGS ONLY ({len(analysis['missing_from_mappings'])} items):")
        for i, sheet_name in enumerate(analysis['missing_from_mappings'], 1):
            print(f"   {i:3d}. '{sheet_name}'")


def save_missing_to_file(analysis):
    """
    Save missing classifications to a text file for reference
    """
    if not analysis['missing_overall']:
        return None
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'missing_sheet_classifications_{timestamp}.txt'
    
    # Save to project root (same level as script directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    filepath = os.path.join(project_root, filename)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"Missing Sheet Classifications Report\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"="*50 + "\n\n")
            
            f.write(f"Total missing classifications: {len(analysis['missing_overall'])}\n\n")
            
            f.write(f"Missing sheet names:\n")
            for i, sheet_name in enumerate(analysis['missing_overall'], 1):
                f.write(f"{i:3d}. {sheet_name}\n")
        
        print(f"\n Missing classifications saved to: {filename}")
        return filepath
    except Exception as e:
        print(f"\n⚠  Warning: Could not save to file: {e}")
        return None


def export_missing_to_excel(analysis, invoice_sheet_names, mapping_sheet_names):
    """
    Export missing classifications to an Excel file with detailed information
    """
    if not analysis['missing_overall']:
        print(f"\n No missing classifications to export to Excel.")
        return None
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'missing_sheet_classifications_{timestamp}.xlsx'
    
    # Save to project root (same level as script directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    filepath = os.path.join(project_root, filename)
    
    try:
        # Prepare data for Excel export
        data = []
        for sheet_name in analysis['missing_overall']:
            # Determine source of the sheet name
            in_invoice_items = sheet_name in invoice_sheet_names
            in_mappings = sheet_name in mapping_sheet_names
            
            source = []
            if in_invoice_items:
                source.append("invoice_items")
            if in_mappings:
                source.append("supplier_item_mappings")
            
            # Suggest category based on name (same logic as existing scripts)
            suggested_category = determine_category_for_sheet(sheet_name)
            category_description = "Equipment" if suggested_category == 'E' else "Materials"
            
            data.append({
                'Sheet Name': sheet_name,
                'Found In Tables': ', '.join(source),
                'In Invoice Items': 'Yes' if in_invoice_items else 'No',
                'In Supplier Mappings': 'Yes' if in_mappings else 'No',
                'Suggested Category Code': suggested_category,
                'Suggested Category': category_description,
                'Status': 'Missing Classification',
                'Notes': f'Add to item_classification table'
            })
        
        # Create DataFrame and export to Excel
        df = pd.DataFrame(data)
        
        # Create Excel writer with multiple sheets
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Main sheet with missing classifications
            df.to_excel(writer, sheet_name='Missing Classifications', index=False)
            
            # Summary sheet
            summary_data = [
                ['Metric', 'Count'],
                ['Total Unique Sheet Names (Combined)', len(analysis['all_sheet_names'])],
                ['Sheet Names in Invoice Items', len(invoice_sheet_names)],
                ['Sheet Names in Supplier Mappings', len(mapping_sheet_names)],
                ['Existing Classifications', len(analysis['all_sheet_names']) - len(analysis['missing_overall'])],
                ['Missing Classifications', len(analysis['missing_overall'])],
                ['', ''],
                ['Generated On', datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
            ]
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False, header=False)
            
            # All sheet names for reference
            all_sheets_data = []
            for sheet_name in sorted(analysis['all_sheet_names']):
                has_classification = sheet_name not in analysis['missing_overall']
                all_sheets_data.append({
                    'Sheet Name': sheet_name,
                    'Has Classification': 'Yes' if has_classification else 'No',
                    'In Invoice Items': 'Yes' if sheet_name in invoice_sheet_names else 'No',
                    'In Supplier Mappings': 'Yes' if sheet_name in mapping_sheet_names else 'No'
                })
            
            all_sheets_df = pd.DataFrame(all_sheets_data)
            all_sheets_df.to_excel(writer, sheet_name='All Sheet Names', index=False)
        
        print(f"\n Excel file created: {filename}")
        print(f"    Missing Classifications sheet: {len(data)} items")
        print(f"    Summary sheet: Overview statistics")
        print(f"    All Sheet Names sheet: Complete reference")
        
        return filepath
        
    except Exception as e:
        print(f"\n⚠  Error creating Excel file: {e}")
        return None


def determine_category_for_sheet(sheet_name):
    """
    Determine category for a sheet name (M=Materials, E=Equipment)
    Same logic as existing classification scripts
    """
    sheet_lower = sheet_name.lower()
    
    # Equipment-related keywords
    equipment_keywords = [
        'equipment', 'tool', 'machinery', 'pump', 'motor', 'generator',
        'compressor', 'drill', 'saw', 'grinder', 'welder', 'crane',
        'valve', 'fitting', 'coupling', 'elbow', 'tee', 'adapter'
    ]
    
    # Check if it's equipment-related
    for keyword in equipment_keywords:
        if keyword in sheet_lower:
            return 'E'
    
    # Default to materials
    return 'M'


def main():
    """Main function to run the script"""
    print(" Starting Sheet Name Classification Analysis")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Fetch data from all sources
        invoice_sheet_names = get_unique_sheet_names_from_invoice_items(db)
        mapping_sheet_names = get_unique_sheet_names_from_mappings(db)
        classified_items = get_existing_classifications(db)
        
        # Analyze missing classifications
        analysis = analyze_missing_classifications(
            invoice_sheet_names, 
            mapping_sheet_names, 
            classified_items
        )
        
        # Print comprehensive summary
        print_summary(invoice_sheet_names, mapping_sheet_names, classified_items, analysis)
        
        # Print detailed missing items
        print_detailed_missing_items(analysis)
        
        # Save to file if there are missing items
        save_missing_to_file(analysis)
        
        # Export to Excel if there are missing items
        excel_file = export_missing_to_excel(analysis, invoice_sheet_names, mapping_sheet_names)
        
        # Final status
        if analysis['missing_overall']:
            print(f"\n⚠  ACTION REQUIRED:")
            print(f"   {len(analysis['missing_overall'])} sheet names need classifications added.")
            print(f"   Consider running the 'add_missing_classifications.py' script to resolve this.")
            if excel_file:
                print(f"    Excel report available: {os.path.basename(excel_file)}")
        else:
            print(f"\n ALL SHEET NAMES HAVE CLASSIFICATIONS!")
            print(f"   Your system is up to date.")
            print(f"    No Excel file generated (no missing classifications found).")
        
        print(f"\n Analysis completed successfully!")
        
    except Exception as e:
        print(f"ERROR: Error during analysis: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main() 