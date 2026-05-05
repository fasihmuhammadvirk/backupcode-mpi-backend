import tabula
import pandas as pd
import PyPDF2 as pyPdf
import fitz
import re
import os
import logging
from typing import Tuple
from .formatting_util import save_final_data
from .extraction_util import read_invoice
from .supremePlumbing_uitl import get_pages

# Original area definitions (preserved for backward compatibility)
area1 = [205.5, 16.67, 205.5 + 390, 16.67 + 573]
area2 = [227, 21.18, 704.30, 21.18 + 553.99]  # for credit invoices

# Define column positions
COLUMNS = [42.58, 126.13, 355.81, 409.3, 449.36, 495, 536]
CREDIT_COLUMNS = [33, 64, 144, 330, 380, 416, 466.5, 508, 557]


def process_invoice(filename, output_path):
    """Original process_invoice function preserved for backward compatibility"""
    raw_text = read_invoice(filename)
    invoice_items = extract_invoice_items(filename, raw_text)
    customer_job = extract_customer_job(raw_text)
    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    tax = extract_tax(raw_text)
    buyer = extract_buyer(raw_text)

    results = process_results(invoice_items, date, ref_no, tax, customer_job, po_no, buyer)
    save_final_data(results, "Lion Hvac Supplies", output_path)


def process_results(invoice_items, date, ref_no, tax, job_name="", po_no="", buyer=""):
    """Original process_results function preserved for backward compatibility"""
    results = invoice_items

    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row

    results["Date"] = date
    results["Ref NO"] = ref_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Lion Hvac Supplies"
    results["Class"] = ""
    results["Memo"] = ""

    return results


def extract_buyer(text):
    buyer = ''
    if 'Ordered By:' in text:
        hit = re.search(r'\n\s*(.*?)\s*Ordered By:', text)
        if hit: buyer = hit.group(1).strip()
    return buyer


def extract_tax(text):
    tax = ''
    if 'Sales Tax: 8.8750 %' in text:
        tax = text.split('Sales Tax: 8.8750 %\n', 1)[1].split('\n', 2)[0]
        return tax.replace('$', '').replace(',', '')
    elif 'Sales Tax:' in text:
        tax = text.split('Sales Tax:\n', 1)[1].split('\n', 2)[0]
        return tax.replace('$', '').replace(',', '')
    elif 'Tax' in text:
        tax = text.split('Tax\n', 1)[1].split('\n', 2)[0]
        return tax.replace('$', '').replace(',', '')
    return tax


def extract_date(text):
    """Extract and normalize date from invoice text.
    Handles both standard and credit invoice formats.
    Normalizes single-digit months/days to two digits."""
    date = ''
    
    # Try standard date format
    if 'Date:' in text:
        hit = re.search(r'Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
        if hit:
            date = hit.group(1)
    
    # Try credit invoice formats if standard fails
    if not date:
        if 'Credit Issued:' in text:
            hit = re.search(r'Credit Issued:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
            if hit:
                date = hit.group(1)
        elif 'Credit Date:' in text:
            hit = re.search(r'Credit Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
            if hit:
                date = hit.group(1)
    
    # Normalize date format if we found a date
    if date:
        try:
            parts = date.split('/')
            date = f"{int(parts[0]):02d}/{int(parts[1]):02d}/{parts[2]}"
        except Exception:
            pass
    
    return date


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'SO#: (\d+)', text)
    if hit:
        po_no = hit.group(1)
    elif 'Packing Slip' in text:
        hit = re.search(r'Packing Slip #: (\d+)', text)
        if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    hit = re.search(r"#:(\d+)", text)
    if hit:
        ref_no = hit.group(1)
    else:
        hit = re.search(r"Credit # (\d+)", text)
        if hit: ref_no = hit.group(1).strip()
    return ref_no


def extract_customer_job(raw_text):
    customer_job = ''
    hit = re.search(r'Ship To:\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()

    if 'Credit To:' in raw_text:
        hit = re.search(r'Customer\sReturn\d+\s+([^\n]+)', raw_text, re.DOTALL)
        if hit: customer_job = hit.group(1).strip()

    return customer_job


def extract_invoice_items(filename, raw_text):
    """Original extract_invoice_items function preserved for backward compatibility"""
    table = tabula.read_pdf(filename, pages='all', guess=True, stream=False, area=[area1],
                            columns=[42.58, 126.13, 355.81, 409.3, 449.36, 495, 536])[0]
    table = table[~table.iloc[:, 0].astype(str).str.startswith('$')]

    if {'Orde', 'r Date', 'Purchase Order Shipment Me'}.issubset(table.columns):
        tables = tabula.read_pdf(filename, pages='all', guess=True, stream=False, area=[270, 6, 270 + 480, 6 + 560],
                                 columns=[33, 64, 144, 330, 380, 416, 466.5, 508, 557])
        table = pd.DataFrame()
        for tab in tables:
            tab = tab[tab.iloc[:, 0].astype(str).str.match(r'^\d{1,2}$')]
            tab = tab.iloc[:, :9]
            tab.columns = [tab.columns[0], 'Qty', 'Item', 'Description', tab.columns[4], tab.columns[5], 'Cost',
                           tab.columns[7], 'Amount']
            tab = tab[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
            table = pd.concat([table, tab], ignore_index=True)

    elif 'Page 1 of 2' in raw_text and 'Order' in str(table.columns[0]):  # Multi-page invoice handling
        tables = tabula.read_pdf(filename, pages='all')
        table = pd.DataFrame()
        for tab in tables:
            if tab.empty or len(tab.columns) == 3:  # Skip if no line items on second page
                continue
            tab = tab[tab.iloc[:, 0].astype(str).str.match(r'^\d{1,2}$')]
            tab = tab.iloc[:, :8]
            tab.columns = [tab.columns[0], 'Item', 'Description', 'Qty', tab.columns[4], 'Cost', tab.columns[6],
                           'Amount']
            tab = tab[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
            table = pd.concat([table, tab], ignore_index=True)

    elif 'Customer Credit' in raw_text:
        # Get the number of pages in the PDF
        pdf_doc = fitz.open(filename)
        num_pages = len(pdf_doc)
        pdf_doc.close()
        
        # Initialize an empty DataFrame to store combined data
        table = pd.DataFrame()
        
        # Process each page with appropriate area coordinates and column positions
        for page_num in range(1, num_pages + 1):
            try:
                # Different approach for first page vs subsequent pages
                if page_num == 1:
                    # First page - use original approach with standard area
                    area = [227, 21.18, 704.30, 21.18 + 553.99]  # First page area
                    
                    # Read the table using the standard approach
                    page_tables = tabula.read_pdf(filename, pages='1', guess=True, stream=False, area=[area])
                    
                    # Process the first page table
                    for tab in page_tables:
                        if tab.empty or len(tab.columns) < 7:  # Skip if empty or not enough columns
                            continue
                        
                        # Filter rows that start with a digit (line numbers)
                        filtered_tab = tab[tab.iloc[:, 0].astype(str).str[0].str.isdigit()]
                        
                        if not filtered_tab.empty:
                            # Rename columns - first page has standard headers
                            filtered_tab.columns = [filtered_tab.columns[0], 'Item', 'Description', 'Qty', 
                                                  filtered_tab.columns[4], 'Cost', filtered_tab.columns[6],
                                                  'Amount']
                            
                            # Select only the columns we need
                            filtered_tab = filtered_tab[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
                            
                            # Append to the main table
                            table = pd.concat([table, filtered_tab], ignore_index=True)


                else:  # For second page and beyond

                    area = [112.10, 21.18, 704.30, 21.18 + 553.99]

                    columns = [48, 146.70, 338.61, 395, 443.13, 475.5, 519.71, 574.7]

                    page_tables = tabula.read_pdf(filename, pages=str(page_num), area=[area], columns=columns,
                                                  guess=False, pandas_options={'header': None})

                    seen_rows = set()  # To track already processed unique rows

                    for tab in page_tables:
                        if tab.empty:
                            continue

                        raw_rows = tab.values.tolist()
                        cleaned_rows = []

                        for row in raw_rows:
                            if not row or not isinstance(row, list) or len(row) < 2:
                                continue

                            row = [str(cell).strip() if cell is not None else '' for cell in row]
                            if not row[0] or not row[0][0].isdigit():
                                continue  # Not a line item

                            row += [''] * (8 - len(row))  # Ensure row has 8 elements

                            # Create a unique key to detect duplicates
                            row_key = (row[0], row[1], row[7])  # Line, Item, Amount

                            if row_key in seen_rows:
                                continue  # Skip duplicate

                            seen_rows.add(row_key)  # Mark as seen

                            cleaned_rows.append({
                                'Line': row[0],
                                'Item': row[1],
                                'Description': row[2],
                                'Qty': row[3],
                                'UOM': row[4],
                                'Cost': row[5],
                                'UOM2': row[6],
                                'Amount': row[7]
                            })

                        if cleaned_rows:
                            df_cleaned = pd.DataFrame(cleaned_rows)
                            df_cleaned = df_cleaned[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
                            table = pd.concat([table, df_cleaned], ignore_index=True)
                            logging.info(f"Added {len(df_cleaned)} items from page {page_num}")
                        else:
                            logging.warning(f"No valid rows found on page {page_num}")

            except Exception as e:
                logging.warning(f"Error processing page {page_num}: {str(e)}")
                continue

    elif len(table.columns) == 10 and 'Order Date' in str(table.columns[0]):
        table = tabula.read_pdf(filename, pages='all', guess=False, stream=False,
                                area=[[210, 21.18, 210 + 196.56, 21.18 + 550.99]])[0]
        table.columns = [table.columns[0], 'Item', 'Description', 'Qty', table.columns[4], 'Cost', table.columns[6],
                         'Amount']
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]

    elif {'LineItem NumberDescriptionInvoicedUOMUnit PriceUOMItem Tota', 'Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2',
          'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6'}.issubset(table.columns) or len(table.columns[0]) > 20:
        table.columns = [table.columns[0], 'Item', 'Description', 'Qty', table.columns[4], 'Cost', table.columns[6],
                         'Amount']
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
    elif {'Line', 'Item Number', 'Description', 'Invoiced', 'UOM', 'Unit Price UOM', 'Unnamed: 0',
          'Item Tota'}.issubset(table.columns):
        table.rename(
            columns={'Item Number': 'Item', 'Invoiced': 'Qty', 'Unit Price UOM': 'Cost', 'Item Tota': 'Amount'},
            inplace=True)
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]

    elif 'Order' in str(table.columns[0]) or len(table.columns.to_list()) == 8:
        table.columns = [table.columns[0], 'Item', 'Description', 'Qty', table.columns[4], 'Cost', table.columns[6],
                         'Amount']
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        if table['Item'][0] == 'Item Number':
            table = table.drop(index=0).reset_index(drop=True)

    table = table[~table.iloc[:, 0].astype(str).str.startswith('$')]
    table = table[~table.iloc[:, 0].astype(str).str.startswith('nan')]
    table.dropna(how='all', inplace=True)
    table.dropna(subset=['Qty', 'Cost', 'Amount'], inplace=True)

    # dropping invalid rows
    def is_valid_number(value):
        try:
            val = str(value).replace('$', '').replace(',', '').strip()
            # Discard if it contains letters or slashes
            if any(c.isalpha() for c in val) or '/' in val:
                return False
            float(val)  # Try converting to float
            return True
        except:
            return False

    # Drop rows where 'Cost' or 'Amount' are not valid numbers
    table = table[
        table['Cost'].apply(is_valid_number) &
        table['Amount'].apply(is_valid_number)
        ]

    table.reset_index(drop=True, inplace=True)

    table['Amount'] = table['Amount'].str.replace(',', '').str.replace('$', '').str.replace('.00', '').astype(float)
    table['Cost'] = table['Cost'].str.replace(',', '').str.replace('$', '').str.replace('.00', '').astype(float)
    table['Qty'] = table['Qty'].astype(str).str.replace(',', '').str.replace('[a-zA-Z]', '', regex=True).str.replace(
        '[^0-9.]', '', regex=True).astype(float)
    table['Qty'] = table['Qty'].astype(int)
    return table


def safe_read_pdf(filename, **kwargs):
    """Safely read PDF file using tabula.

    Args:
        filename: Path to PDF file
        **kwargs: Additional arguments for tabula.read_pdf

    Returns:
        List of DataFrames containing tables from PDF
    """
    try:
        return tabula.read_pdf(filename, **kwargs)
    except Exception as e:
        return None
