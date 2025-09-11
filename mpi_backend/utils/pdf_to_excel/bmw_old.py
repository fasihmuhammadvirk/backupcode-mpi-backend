import pandas as pd
import numpy as np
import os
import re
import fitz
import tabula
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data, save_final_data_for_database

regular_area = (300, 44, 300+341, 44+531)
credit_memo_area = (268,35.5, 268 + 342, 35.5 +540)
bmw_old_columns = [44, 84.2, 165.5, 445.5, 508]
credit_memo_columns = [35.5, 80.5, 138.6, 412.5, 494.8]


def process_invoice(filename, output_path):
    """
    Enhanced BMW invoice processing that handles both old and new formats.
    Preserves old functionality while ensuring proper tax extraction for all invoices.
    """
    is_credit_memo = False
    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()
    
    # Check if this is a credit memo (preserve old functionality)
    if 'Credit Memo' in raw_text:
        tables = tabula.read_pdf(filename, pages='all', area=credit_memo_area, guess=False, stream=True,
                                columns=credit_memo_columns)
        is_credit_memo = True
    else:
        # Check if this is a Project invoice (old functionality)
        if 'Project' in raw_text:
            # Use old processing method for Project invoices
            tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True, 
                                   columns=bmw_old_columns)
        else:
            # Use enhanced processing for all other BMW invoices
            tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True, 
                                   columns=bmw_old_columns)
    
    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)
    
    # Enhanced tax extraction for all BMW invoices
    tax = extract_tax(filename)

    # Preserve old credit memo logic
    if is_credit_memo:
        hit = re.search(r'Credit No.\s*(\d+)\n', raw_text)
        if hit: 
            ref_no = hit.group(1)
        try:
            tax = '-' + raw_text.rsplit('-',1)[-1].replace('$','').replace(',','')
            tax = float(tax)
        except:
            tax = 0

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data_for_database(result, "BMW Plumbing Supplies", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "BMW Plumbing Supplies"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if table.columns.values.tolist() == ['Unnamed: 0', 'Qty', 'Item', 'Description', 'Rate', 'Amount']: # credit memo type
            table.rename(columns={'Rate': 'Cost'}, inplace=True)
        else:
            table.rename(columns={'Price each': 'Cost'}, inplace=True)
        table['Amount'] = table['Amount'].str.replace('T', '')
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        table.dropna(subset=['Qty'],inplace=True)

        table['Amount'] = table['Amount'].astype(str).str.replace(',', '').str.replace('$', '')
        table['Cost'] = table['Cost'].astype(str).str.replace(',', '').str.replace('$', '')
        table['Qty'] = table['Qty'].astype(str).str.replace(',', '').astype(float)
        table['Qty'] = table['Qty'].astype(int)
        table.reset_index(drop=True, inplace=True)
        invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items


def extract_tax(filename):
    """
    Enhanced tax extraction for BMW invoices that handles both old and new formats.
    First tries to extract from data rows, falls back to old method if needed.
    """
    try:
        # Get all tables from the PDF
        tables = tabula.read_pdf(filename, pages='all')
        
        if not tables:
            # Fallback to old method if no tables found
            return '0'
        
        # Get the last table (financial summary)
        last_table = tables[-1]
        
        # Try to extract tax from data rows first (new method)
        tax_amount = extract_tax_from_data_rows(last_table)
        
        if tax_amount != '0':
            return tax_amount
        
        # Fallback to old method if new method didn't work
        return last_table.columns.values[-1].replace('$','').replace(',','')
        
    except Exception as e:
        # If anything fails, return 0 as fallback
        print(f"Error extracting tax from {filename}: {e}")
        return '0'


def extract_tax_from_data_rows(table):
    """
    Extract tax amount from the actual data rows of the financial summary table.
    Handles different tax formats like 'Tax (004)', 'Tax (006)', 'Tax', etc.
    """
    try:
        # Convert table to string for easier pattern matching
        table_str = str(table)
        
        # Look for tax patterns in the data
        tax_patterns = [
            r'Tax\s*\(00[46]\)\s*([0-9,]+\.?[0-9]*)',  # Tax (004) or Tax (006) with amount
            r'Tax\s*\(00[46]\)\s*\$?([0-9,]+\.?[0-9]*)',  # Tax (004) or Tax (006) with $ and amount
            r'Tax\s*([0-9,]+\.?[0-9]*)',  # Just Tax with amount
            r'Tax\s*\$?([0-9,]+\.?[0-9]*)',  # Tax with $ and amount
        ]
        
        for pattern in tax_patterns:
            match = re.search(pattern, table_str, re.IGNORECASE)
            if match:
                tax_value = match.group(1)
                # Clean up the extracted value
                tax_value = tax_value.replace(',', '').replace('$', '').strip()
                if tax_value and tax_value != '0':
                    return tax_value
        
        # If no pattern match found, try to find tax row by iterating through table data
        if hasattr(table, 'iloc'):
            for i in range(len(table)):
                try:
                    row_text = str(table.iloc[i]).lower()
                    if 'tax' in row_text and any(char.isdigit() for char in row_text):
                        # Found a tax row, try to extract the amount
                        for col in table.columns:
                            cell_value = str(table.iloc[i][col])
                            # Check if this cell contains a numeric value
                            if any(char.isdigit() for char in cell_value):
                                # Clean and return the value
                                clean_value = cell_value.replace(',', '').replace('$', '').strip()
                                if clean_value and clean_value != '0':
                                    return clean_value
                except:
                    continue
        
        return '0'
        
    except Exception as e:
        print(f"Error in extract_tax_from_data_rows: {e}")
        return '0'


def extract_customer_job(raw_text):
    customer_job =''
    hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()
    return customer_job


def extract_date(text):
    date = ''
    hit = re.search(r'Date\s*\n(\d{1,2}/\d{1,2}/\d{4})', text)
    if hit: date = hit.group(1)
    return date


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'P.O. No.\s*(\d+)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    hit = re.search(r"\nInvoice #\s*(\d+)\n", text)
    if hit : ref_no = hit.group(1)
    return ref_no

