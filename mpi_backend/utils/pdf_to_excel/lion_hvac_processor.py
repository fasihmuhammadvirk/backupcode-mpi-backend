import tabula
import pandas as pd
import PyPDF2 as pyPdf
import fitz
import re
import os
import logging
from typing import Tuple
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data, save_final_data_for_database
from mpi_backend.utils.pdf_to_excel.extraction_util import read_invoice
from mpi_backend.utils.pdf_to_excel.supreme_plumbing_util import get_pages

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
    freight = extract_freight(filename)
    buyer = extract_buyer(raw_text)

    results = process_results(invoice_items, date, ref_no, tax, customer_job, po_no, buyer, freight)
    save_final_data_for_database(results, "Lion Hvac Supplies", output_path)


def process_results(invoice_items, date, ref_no, tax, job_name="", po_no="", buyer="", freight=0.0):
    """Original process_results function preserved for backward compatibility"""
    results = invoice_items
    
    # Always add freight and tax as a consecutive pair at the end
    # Freight must always be immediately before tax
    try:
        freight_value = float(freight)
    except (ValueError, TypeError):
        freight_value = 0.0
        
    try:
        tax_value = float(tax)
    except (ValueError, TypeError):
        tax_value = 0.0
    
    # Add freight row first (immediately before tax) only if freight > 0
    if freight_value > 0:
        freight_row = ["10 Materials", "Freight", "", "", freight_value]
        results.loc[len(results)] = freight_row
    
    # Add tax row immediately after freight
    tax_row = ["10 Materials", "Tax", "", "", tax_value]
    results.loc[len(results)] = tax_row

    results["Date"] = date
    results["Ref NO"] = str(ref_no)  # Ensure reference number is stored as string to preserve leading zeros
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


def extract_freight(filename):
    """
    Extract freight amount from Lion Hvac invoices.
    Handles different freight formats and patterns.
    """
    try:
        # Get raw text from PDF
        raw_text = fitz.open(filename)
        raw_text = raw_text[0].get_text()
        
        # Look for freight patterns in the text
        freight_patterns = [
            r'Freight\s*\$?([0-9,]+\.?[0-9]*)',  # Freight $71.70
            r'Freight\s*\n\s*\$?([0-9,]+\.?[0-9]*)',  # Freight on new line
            r'Freight\s*:\s*\$?([0-9,]+\.?[0-9]*)',  # Freight: $71.70
            r'Shipping\s*\$?([0-9,]+\.?[0-9]*)',  # Shipping $71.70
            r'Delivery\s*\$?([0-9,]+\.?[0-9]*)',  # Delivery $71.70
        ]
        
        for pattern in freight_patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE)
            if match:
                freight_value = match.group(1)
                # Clean up the extracted value
                freight_value = freight_value.replace(',', '').replace('$', '').strip()
                if freight_value and freight_value != '0':
                    return float(freight_value)
        
        # Try to extract from financial summary table
        tables = tabula.read_pdf(filename, pages='all')
        if tables:
            last_table = tables[-1]
            freight_amount = extract_freight_from_table(last_table)
            if freight_amount != 0:
                return freight_amount
        
        return 0.0
        
    except Exception as e:
        print(f"Error extracting freight from {filename}: {e}")
        return 0.0


def extract_freight_from_table(table):
    """
    Extract freight amount from the financial summary table.
    """
    try:
        # Convert table to string for easier pattern matching
        table_str = str(table)
        
        # Look for freight patterns in the table data
        freight_patterns = [
            r'Freight\s*\$?([0-9,]+\.?[0-9]*)',  # Freight $71.70
            r'Freight\s*:\s*\$?([0-9,]+\.?[0-9]*)',  # Freight: $71.70
            r'Shipping\s*\$?([0-9,]+\.?[0-9]*)',  # Shipping $71.70
            r'Delivery\s*\$?([0-9,]+\.?[0-9]*)',  # Delivery $71.70
        ]
        
        for pattern in freight_patterns:
            match = re.search(pattern, table_str, re.IGNORECASE)
            if match:
                freight_value = match.group(1)
                # Clean up the extracted value
                freight_value = freight_value.replace(',', '').replace('$', '').strip()
                if freight_value and freight_value != '0':
                    return float(freight_value)
        
        # If no pattern match found, try to find freight row by iterating through table data
        if hasattr(table, 'iloc'):
            for i in range(len(table)):
                try:
                    row_text = str(table.iloc[i]).lower()
                    if ('freight' in row_text or 'shipping' in row_text or 'delivery' in row_text) and any(char.isdigit() for char in row_text):
                        # Found a freight row, try to extract the amount
                        for col in table.columns:
                            cell_value = str(table.iloc[i][col])
                            # Check if this cell contains a numeric value
                            if any(char.isdigit() for char in cell_value):
                                # Clean and return the value
                                clean_value = cell_value.replace(',', '').replace('$', '').strip()
                                if clean_value and clean_value != '0':
                                    return float(clean_value)
                except:
                    continue
        
        return 0.0
        
    except Exception as e:
        print(f"Error in extract_freight_from_table: {e}")
        return 0.0


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
    # Handle various reference formats: #:0081212A, #:I-000987, Credit # 89779-I, etc.
    patterns = [
        r"#:([A-Za-z0-9\-]+)",  # General format: #:I-000987, #:0081212A, #:89779-I
        r"#:([0-9]+[A-Za-z]?)",  # Numbers with optional letters: #:0081212A
        r"#:([A-Za-z]?[0-9]+)",  # Letters with numbers: #:I000987
        r"#:([0-9]+-[A-Za-z]+)",  # Numbers with dash and letters: #:89779-I
        r"#:([A-Za-z]+-[0-9]+)",  # Letters with dash and numbers: #:I-000987
    ]
    
    for pattern in patterns:
        hit = re.search(pattern, text)
        if hit:
            ref_no = hit.group(1).strip()
            break
    
    if not ref_no:
        # Try credit patterns
        credit_patterns = [
            r"Credit # ([A-Za-z0-9\-]+)",  # General format for credit
            r"Credit # ([0-9]+[A-Za-z]?)",  # Numbers with optional letters
            r"Credit # ([A-Za-z]?[0-9]+)",  # Letters with numbers
        ]
        for pattern in credit_patterns:
            hit = re.search(pattern, text)
            if hit:
                ref_no = hit.group(1).strip()
                break
    
    return ref_no


def extract_customer_job(raw_text):
    """Extract customer job (ship-to address) from Lion HVAC invoices"""
    try:
        lines = raw_text.split('\n')
        
        # Enhanced Ship To detection with multiple patterns
        ship_to_patterns = ['Ship To', 'SHIP TO', 'Ship-to', 'SHIP-TO']
        
        for i, line in enumerate(lines):
            if any(pattern in line for pattern in ship_to_patterns):
                print(f"Lion HVAC: Found Ship To pattern at line {i}: '{line.strip()}'")
                
                # Look for address in the next 30 lines (expanded range to find actual addresses)
                for j in range(i+1, min(i+31, len(lines))):
                    address_line = lines[j].strip()
                    
                    # Skip empty lines and common headers
                    skip_headers = [
                        'Customer #', 'Order Date', 'Sales Order', 'Buyer', 
                        'Invoice #', 'Invoice Date', 'SHIP TO',
                        'Customer P/O #', 'Quote Number', 'NET', 'PREPAID',
                        'Ship Via', 'SHIP VIA', 'Ship via',  # Skip Ship Via
                        'Salesman', 'SALESMAN', 'salesman',  # Skip Salesman
                        'Job Number', 'Terms', 'Freight Terms', 'Ship Date'
                    ]
                    
                    if (address_line and 
                        len(address_line) > 3 and
                        not any(header in address_line for header in skip_headers) and
                        not address_line.isdigit() and  # Skip pure numbers
                        not re.match(r'^\d{2}/\d{2}/\d{4}', address_line) and  # Skip dates
                        not re.match(r'^[A-Z]{2,}\s*\d+$', address_line) and  # Skip codes like "NET 120"
                        not re.match(r'^[A-Z]{1,2}\d+$', address_line) and  # Skip codes like "M9291012"
                        not re.match(r'^[A-Z]{2,}\s+[A-Z]{2,}$', address_line)):  # Skip state codes like "NY 11212"
                        
                        # Enhanced validation: look for street address patterns
                        # Should contain letters and numbers, and look like an address
                        if (any(char.isalpha() for char in address_line) and
                            any(char.isdigit() for char in address_line) and
                            (re.search(r'\d+\s+[A-Z]', address_line) or  # "123 STREET" pattern
                             re.search(r'[A-Z]+\s+\d+', address_line) or  # "STREET 123" pattern
                             re.search(r'\d+.*[A-Z].*[A-Z]', address_line))):  # Mixed pattern
                            print(f"Lion HVAC: Extracted customer job: '{address_line}' from line {j}")
                            return address_line
        
        # Original fallback method
        customer_job = ''
        hit = re.search(r'Ship To:\s*\n(.*?)\n', raw_text, re.DOTALL)
        if hit:
            customer_job = hit.group(1).strip()
            if len(customer_job) > 3 and any(char.isalpha() for char in customer_job):
                print(f"Lion HVAC: Regex fallback extracted customer job: '{customer_job}'")
                return customer_job

        if 'Credit To:' in raw_text:
            hit = re.search(r'Customer\sReturn\d+\s+([^\n]+)', raw_text, re.DOTALL)
            if hit: 
                customer_job = hit.group(1).strip()
                if len(customer_job) > 3 and any(char.isalpha() for char in customer_job):
                    print(f"Lion HVAC: Credit To fallback extracted customer job: '{customer_job}'")
                    return customer_job
        
        print("Lion HVAC: No customer job found with any method")
        return ''
        
    except Exception as e:
        print(f"Lion HVAC: Error extracting customer job: {e}")
        return ''


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
