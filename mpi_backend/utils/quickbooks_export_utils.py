"""
QuickBooks-specific Excel export utilities with custom formatting.
"""
import pandas as pd
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def save_quickbooks_excel(df: pd.DataFrame, output_path: str):
    """
    Save QuickBooks data to Excel with special formatting for split invoices.
    
    Color Scheme:
    - Split account rows (regular items in split invoice): Light blue #C5D9F1
    - Total rows (is_total_row=True): Dark blue #538DD5 with white bold text
    - Normal rows (single account invoice): No special color
    
    Args:
        df: DataFrame with QuickBooks data
        output_path: Output file path
    """
    try:
        # Detect split invoices
        # Group by ref_no + vendor + date (same as controller logic) and count unique accounts
        # Create invoice key: ref_no|vendor|date

        df['invoice_key'] = df['Date'].astype(str) + '|' + df['Ref'].astype(str) + '|' + df['Vendor'].astype(str)

        split_invoice_keys = set()
        for invoice_key in df['invoice_key'].unique():
            my_set = set()
            for row_idx, row in df.iterrows():
                if row['invoice_key'] == invoice_key and row['is_total_row'] == False:
                    my_set.add(row['Account'] + '|' + row['Class'])
            if len(my_set) > 1:
                split_invoice_keys.add(invoice_key)

        logger.info(f"Found {len(split_invoice_keys)} split invoices out of {df['invoice_key'].nunique()} total invoices")

        # Exclude is_total_row and invoice_key from Excel output (keep it only for formatting logic)
        display_columns = [col for col in df.columns if col not in ['is_total_row', 'invoice_key']]
        df_display = df[display_columns].copy()

        # Use xlsxwriter for formatting
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            # Write data without formatting first (without is_total_row column)
            df_display.to_excel(writer, sheet_name='QuickBooks Export', index=False)

            workbook = writer.book
            worksheet = writer.sheets['QuickBooks Export']

            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D7E4BC',
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })

            normal_format = workbook.add_format({
                'border': 1,
                'align': 'left',
                'valign': 'top'
            })

            # Split row format (Light Blue)
            split_format = workbook.add_format({
                'bg_color': '#C5D9F1',
                'border': 1,
                'align': 'left',
                'valign': 'top'
            })

            # Total row format (Dark Blue/Black + White Bold)
            total_format = workbook.add_format({
                'bg_color': '#538DD5',
                'font_color': 'black',
                'bold': True,
                'border': 1,
                'align': 'left',
                'valign': 'top'
            })

            # Number formats
            normal_number_format = workbook.add_format({
                'num_format': '#,##0.00',
                'border': 1,
                'align': 'right'
            })

            split_number_format = workbook.add_format({
                'num_format': '#,##0.00',
                'bg_color': '#C5D9F1',
                'border': 1,
                'align': 'right'
            })

            total_number_format = workbook.add_format({
                'num_format': '#,##0.00',
                'bg_color': '#538DD5',
                'font_color': 'black',
                'bold': True,
                'border': 1,
                'align': 'right'
            })

            for col_num, value in enumerate(df_display.columns.values):
                worksheet.write(0, col_num, value, header_format)

            # Set column widths
            column_widths = {
                'Date': 12,
                'Ref': 15,
                'Vendor': 25,
                'Terms': 15,
                'Bill Due': 12,
                'Account': 50,
                'Amount': 12,
                'Memo': 40,
                'Customer Job': 30,
                'Class': 10
            }

            for col_num, col_name in enumerate(df_display.columns):
                width = column_widths.get(col_name, 15)
                worksheet.set_column(col_num, col_num, width)

            # Apply row formatting based on is_total_row and split invoice detection
            for row_num, (_, row) in enumerate(df.iterrows()):
                excel_row = row_num + 1  # +1 because Excel rows are 1-indexed and we have header

                invoice_key = row['invoice_key']
                is_total = row.get('is_total_row', False)
                is_split = invoice_key in split_invoice_keys

                # Determine format
                if is_total:
                    row_format = total_format
                    number_format = total_number_format
                elif is_split and not is_total:
                    row_format = split_format
                    number_format = split_number_format
                else:
                    row_format = normal_format
                    number_format = normal_number_format

                # Apply format to each cell (use df_display columns to exclude is_total_row)
                for col_num, col_name in enumerate(df_display.columns):
                    value = row[col_name]

                    # Use number format for numeric columns
                    if col_name in ['Amount']:
                        worksheet.write_number(excel_row, col_num, float(value) if pd.notna(value) else 0, number_format)
                    else:
                        worksheet.write(excel_row, col_num, value if pd.notna(value) else '', row_format)

            # Freeze header row
            worksheet.freeze_panes(1, 0)

        logger.info(f"QuickBooks Excel file saved successfully: {output_path}")

    except Exception as e:
        logger.error(f"Error saving QuickBooks Excel: {str(e)}")
        raise


def convert_quickbooks_items_to_dataframe(items: List[Dict]) -> pd.DataFrame:
    """
    Convert QuickBooks preview items to DataFrame for Excel export.
    
    Args:
        items: List of QuickBooksPreviewItem dicts
        
    Returns:
        DataFrame with properly formatted columns
    """
    if not items:
        return pd.DataFrame()

    df = pd.DataFrame(items)
    
    # Rename columns to match Excel headers
    column_mapping = {
        'date': 'Date',
        'ref_no': 'Ref',
        'ref': 'Ref',
        'vendor': 'Vendor',
        'account': 'Account',
        'amount': 'Amount',
        'memo': 'Memo',
        'customer_job': 'Customer Job',
        'class_field': 'Class',
        'class': 'Class'
    }
    
    df = df.rename(columns=column_mapping)
    
    # Add is_total_row if not present (needed for formatting)
    if 'is_total_row' not in df.columns:
        df['is_total_row'] = False
    
    # Add empty columns for user input
    df['Terms'] = ''
    df['Bill Due'] = ''
    
    # Select and order columns for export (exact order required)
    export_columns = [
        'Date',
        'Ref',
        'Vendor',
        'Terms',
        'Bill Due',
        'Account',
        'Amount',
        'Memo',
        'Customer Job',
        'Class'
    ]
    
    # Keep only export columns that exist (exclude is_total_row from display)
    available_columns = [col for col in export_columns if col in df.columns]
    
    # Reorder DataFrame to have export columns first, then is_total_row at the end
    df = df[available_columns + ['is_total_row']]
    
    # Ensure numeric columns are float
    for col in ['Amount']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    logger.info(f"Converted {len(df)} items to DataFrame with columns: {list(df.columns)}")
    
    return df
