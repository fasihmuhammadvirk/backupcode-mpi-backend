import pandas as pd
import numpy as np
import os
import re
import fitz
import tabula
import PyPDF2
from .formatting_util import save_final_data
from .cleaning_util import clean_individual_table
from .extraction_util import extract_invoice_info, extract_tax_etc, extract_po, extract_buyer
from .supremePlumbing_uitl import get_pages

# QuickBooks-style configurations
regular_area = (300, 44, 300+341, 44+531)
credit_memo_area = (268, 35.5, 268 + 342, 35.5 + 540)
bmw_old_columns = [44, 84.2, 165.5, 445.5, 508]
credit_memo_columns = [35.5, 80.5, 138.6, 412.5, 494.8]

# Distribution-style configurations (same as World Wide Plumbing)
DIST_REGULAR_AREA = (290, 20, 290 + 420, 20 + 570)
DIST_LAST_PAGE_AREA = (290, 20, 290 + 375, 20 + 570)
DIST_COLUMNS = [20, 38, 68, 98, 128, 240, 375, 428, 470, 530]

SUPPLIER = "BMW Plumbing Supplies"


def is_distribution_style(raw_text):
    """Check if invoice is distribution-style (LN QNTY format)."""
    return 'LN QNTY' in raw_text or ('ORD' in raw_text and 'SHIP' in raw_text and 'B/O' in raw_text)


def process_invoice(filename, output_path):
    """Process BMW Plumbing invoice, auto-detecting format type."""
    doc = fitz.open(filename)
    raw_text = doc[0].get_text()
    doc.close()
    
    # Detect invoice format and try distribution-style first if detected
    if is_distribution_style(raw_text):
        try:
            return process_distribution_style(filename, output_path, raw_text)
        except (ValueError, KeyError) as e:
            # If distribution-style fails, fallback to QuickBooks-style
            print(f"Distribution-style extraction failed, trying QuickBooks-style: {e}")
            return process_quickbooks_style(filename, output_path, raw_text)
    else:
        return process_quickbooks_style(filename, output_path, raw_text)


def process_distribution_style(filename, output_path, raw_text):
    """Process distribution-style invoice (same format as World Wide Plumbing)."""
    # Extract tables from PDF
    tables = tabula.read_pdf(
        filename,
        pages='all',
        area=DIST_REGULAR_AREA,
        guess=False,
        stream=True,
        columns=DIST_COLUMNS
    )

    finalized_tables = []

    # Get actual PDF page count
    with open(filename, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        actual_page_count = len(reader.pages)

    # Process all pages except the last
    if len(tables) > 1:
        for i in range(len(tables) - 1):
            current_table = tables[i]
            current_table = clean_individual_table(current_table, page=i + 1, check_row_count=True)
            if current_table is not None:
                finalized_tables.append(current_table)

    # Process last page with different area
    last_tables = tabula.read_pdf(
        filename,
        pages=actual_page_count,
        area=DIST_LAST_PAGE_AREA,
        guess=False,
        stream=True,
        columns=DIST_COLUMNS
    )

    if last_tables:
        last_table = clean_individual_table(last_tables[0], page=-1, check_row_count=True)
        if last_table is not None:
            finalized_tables.append(last_table)

    if not finalized_tables:
        raise ValueError(f"No invoice items could be extracted from {filename}")

    # Combine all tables
    final_df = pd.concat(finalized_tables).reset_index(drop=True)
    final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Qty BO", "Cost", "Amount"])

    # Extract metadata using distribution-style extractors
    invoice_num, invoice_date = extract_invoice_info(filename)
    financial_data = extract_tax_etc(filename)
    buyer = extract_buyer(filename)
    po = extract_po(filename)
    
    # Extract customer job from raw text
    customer_job = ''
    hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()

    # Add tax rows
    for i, item in enumerate(financial_data):
        if i == 0:
            tax_row = ["10 Materials", item.capitalize(), "", "", "", financial_data[item]]
            if 'Qty BO' in final_df.columns and final_df['Qty BO'].sum() == 0:
                final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Cost", "Amount"])
                tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            final_df.loc[len(final_df)] = tax_row
        else:
            tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            if "Qty BO" in final_df.columns:
                tax_row = ["10 Materials", item.capitalize(), "", "", "", financial_data[item]]
                qty_bo_sum = pd.to_numeric(final_df['Qty BO'], errors='coerce').sum()
                if qty_bo_sum == 0:
                    final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Cost", "Amount"])
                    tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            final_df.loc[len(final_df)] = tax_row

    # Add metadata columns
    final_df['Date'] = invoice_date
    final_df['Ref NO'] = str(invoice_num)
    final_df['PO #'] = po
    final_df['Customer Job'] = customer_job
    final_df['Bill'] = "Bill"
    final_df["Vendor"] = SUPPLIER
    final_df["Class"] = ""
    final_df["Memo"] = ""
    final_df["Buyer"] = buyer

    # Reorder columns if Qty BO exists
    if "Qty BO" in final_df.columns:
        final_df = final_df.reindex(columns=[
            "Item", "Description", "Qty", "Cost", "Amount", "Date",
            "Ref NO", "PO #", "Customer Job", "Bill", "Vendor", "Class", "Memo", "Buyer"
        ])

    save_final_data(final_df, SUPPLIER, output_path)
    return None


def process_quickbooks_style(filename, output_path, raw_text):
    """Process QuickBooks-style invoice (simple table format)."""
    is_credit_memo = False
    tables = None
    invoice_items = pd.DataFrame()
    
    if 'Credit Memo' in raw_text:
        tables = tabula.read_pdf(filename, pages='all', area=credit_memo_area, guess=False, stream=True,
                                columns=credit_memo_columns)
        is_credit_memo = True
        invoice_items = extract_invoice_items_quickbooks(tables)
    else:
        # Try different extraction methods
        tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True, columns=bmw_old_columns)
        invoice_items = extract_invoice_items_quickbooks(tables)
        
        # If primary fails, try with tabula guess
        if invoice_items.empty:
            tables = tabula.read_pdf(filename, pages='all', guess=True)
            invoice_items = extract_invoice_items_quickbooks(tables)

    if invoice_items.empty:
        raise ValueError(f"No invoice items could be extracted from {filename}")

    ref_no = extract_ref_no_quickbooks(raw_text)
    po_no = extract_po_no_quickbooks(raw_text)
    date = extract_date_quickbooks(raw_text)
    customer_job = extract_customer_job_quickbooks(raw_text)
    tax = extract_tax_quickbooks(filename)

    if is_credit_memo:
        hit = re.search(r'Credit No.\s*(\d+)\n', raw_text)
        if hit: ref_no = hit.group(1)
        try:
            # Extract and clean the tax string
            tax_str = raw_text.rsplit('-', 1)[-1].replace('$', '').replace(',', '').strip()
            # Validate before conversion
            if not tax_str:
                tax = 0
            else:
                tax = float('-' + tax_str)
        except (ValueError, IndexError, TypeError):
            tax = 0

    result = process_results_quickbooks(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data(result, SUPPLIER, output_path)
    return []


def process_results_quickbooks(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    """Process results for QuickBooks-style invoices."""
    results = invoice_items.copy()
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = SUPPLIER
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_invoice_items_quickbooks(tables):
    """Extract invoice items from QuickBooks-style tables."""
    invoice_items = []
    for table in tables:
        try:
            columns = table.columns.values.tolist()
            
            # Credit memo type
            if columns == ['Unnamed: 0', 'Qty', 'Item', 'Description', 'Rate', 'Amount']:
                table = table.copy()
                table.rename(columns={'Rate': 'Cost'}, inplace=True)
            # Standard invoice with 'Price each'
            elif 'Price each' in columns:
                table = table.copy()
                table.rename(columns={'Price each': 'Cost'}, inplace=True)
            # Check if required columns exist
            elif 'Amount' not in columns:
                print(f"Warning: Skipping table with unexpected columns: {columns}")
                continue
            
            if 'Amount' not in table.columns:
                print(f"Warning: 'Amount' column not found after rename. Columns: {table.columns.tolist()}")
                continue
                
            table = table.copy()
            table['Amount'] = table['Amount'].astype(str).str.replace('T', '')
            
            # Ensure required columns exist before selecting
            required_cols = ['Item', 'Description', 'Qty', 'Cost', 'Amount']
            missing_cols = [col for col in required_cols if col not in table.columns]
            if missing_cols:
                print(f"Warning: Missing columns {missing_cols}. Available: {table.columns.tolist()}")
                continue
                
            table = table[required_cols].copy()
            table = table.dropna(subset=['Qty'])
            
            if table.empty:
                continue
                
            table.loc[:, 'Qty'] = table['Qty'].astype(str).str.replace(',', '').astype(float)
            table.loc[:, 'Qty'] = table['Qty'].astype(int)
            table.reset_index(drop=True, inplace=True)
            invoice_items.append(table)
        except Exception as e:
            print(f"Warning: Error processing table: {e}")
            continue
    
    if not invoice_items:
        return pd.DataFrame()
    
    merged_invoice_items = pd.concat(invoice_items, ignore_index=True)
    return merged_invoice_items


def extract_tax_quickbooks(filename):
    """Extract tax from QuickBooks-style invoice."""
    try:
        tables = tabula.read_pdf(filename, pages='all')
        tax_str = tables[-1].columns.values[-1].replace('$','').replace(',','')
        return float(tax_str)
    except (IndexError, ValueError, AttributeError) as e:
        print(f"Warning: Could not extract tax: {e}")
        return 0.0


def extract_customer_job_quickbooks(raw_text):
    """Extract customer job from QuickBooks-style invoice."""
    customer_job = ''
    hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()
    return customer_job


def extract_date_quickbooks(text):
    """Extract date from QuickBooks-style invoice."""
    date = ''
    hit = re.search(r'Date\s*\n(\d{1,2}/\d{1,2}/\d{4})', text)
    if hit: date = hit.group(1)
    return date


def extract_po_no_quickbooks(text):
    """Extract PO number from QuickBooks-style invoice."""
    po_no = ''
    hit = re.search(r'P.O. No.\s*(\d+)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no_quickbooks(text):
    """Extract invoice reference number from QuickBooks-style invoice."""
    ref_no = ''
    hit = re.search(r"\nInvoice #\s*(\d+)\n", text)
    if hit: ref_no = hit.group(1)
    return ref_no

