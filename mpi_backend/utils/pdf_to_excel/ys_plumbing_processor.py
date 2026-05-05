import pandas as pd
import numpy as np
import os
import re
import fitz
import tabula
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data, save_final_data_for_database

regular_area = (309,34,292+309, 34+540)
columns = [287,383,477.6]


def process_invoice(filename, output_path):

    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()

    tables = tabula.read_pdf(filename, pages='all', area=regular_area, stream=False, columns=columns)

    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)
    tax= extract_tax(raw_text)
    freight = extract_freight(filename)

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no, freight)
    save_final_data_for_database(result, "Y & S Plumbing Supplies", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no="", freight=0.0):
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
    results["Ref NO"] = str(invoice_no)  # Ensure reference number is stored as string to preserve leading zeros
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Y & S Plumbing Supplies"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if table.columns.values.tolist() == ['Description', 'Qty', 'Rate', 'Amount']:
            table.rename(columns={'Rate': 'Cost'}, inplace=True)
            table['Item'] = '' # credit memo doesnot contain items column, but is expected in excel format

        table['Amount'] = table['Amount'].str.replace('T', '')
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        dropna = table.dropna(subset=['Qty'], inplace=True)
        table['Qty'] = table['Qty'].astype(str).str.replace(',', '').astype(float)
        table['Qty'] = table['Qty'].astype(int)
        table.reset_index(drop=True, inplace=True)
        invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items


def extract_tax(text):
    try :
        tax = text.rsplit('$',3)[2]
        tax = re.sub(r'[^0-9.]', '', tax) # keep only digits and decimal
    except:
        tax=0
    return tax


def extract_freight(filename):
    """
    Extract freight amount from Y & S Plumbing invoices.
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


def extract_customer_job(raw_text):
    """Extract customer job (ship-to address) from Y&S invoices"""
    try:
        lines = raw_text.split('\n')
        
        # Enhanced Ship To detection with multiple patterns
        ship_to_patterns = ['Ship To', 'SHIP TO', 'Ship-to', 'SHIP-TO']
        
        for i, line in enumerate(lines):
            if any(pattern in line for pattern in ship_to_patterns):
                print(f"Y&S: Found Ship To pattern at line {i}: '{line.strip()}'")
                
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
                            print(f"Y&S: Extracted customer job: '{address_line}' from line {j}")
                            return address_line
        
        # Fallback: look for address patterns near company names
        company_patterns = ['MPI PLUMBING', 'BMW PLUMBING', 'Y&S PLUMBING', 'PARK PLUMBING', 'WWPS']
        
        for i, line in enumerate(lines):
            if any(company in line.upper() for company in company_patterns):
                print(f"Y&S: Found company pattern at line {i}: '{line.strip()}'")
                
                # Look for address in nearby lines (expanded range)
                for j in range(max(0, i-5), min(len(lines), i+8)):
                    address_line = lines[j].strip()
                    
                    if (address_line and 
                        len(address_line) > 3 and
                        not any(header in address_line.upper() for header in ['CUSTOMER #', 'ORDER DATE', 'SALES ORDER', 'BUYER', 'INVOICE #', 'INVOICE DATE', 'SHIP TO']) and
                        any(char.isdigit() for char in address_line) and  # Address should contain numbers
                        any(char.isalpha() for char in address_line)):  # And letters
                        
                        print(f"Y&S: Fallback extracted customer job: '{address_line}' from line {j}")
                        return address_line
        
        # Enhanced regex fallback for Ship To patterns
        ship_to_regex_patterns = [
            r'Ship\s*To\s*\n(.*?)\n',  # Ship To followed by newline
            r'SHIP\s*TO\s*\n(.*?)\n',  # SHIP TO followed by newline
            r'Ship\s*To\s*:\s*(.*?)\n',  # Ship To: followed by content
            r'SHIP\s*TO\s*:\s*(.*?)\n',  # SHIP TO: followed by content
        ]
        
        for pattern in ship_to_regex_patterns:
            match = re.search(pattern, raw_text, re.DOTALL | re.IGNORECASE)
            if match:
                customer_job = match.group(1).strip()
                if len(customer_job) > 3 and any(char.isalpha() for char in customer_job):
                    print(f"Y&S: Regex extracted customer job: '{customer_job}'")
                    return customer_job
        
        # Original fallback method
        hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
        if hit:
            customer_job = hit.group(1).strip()
            if len(customer_job) > 3 and any(char.isalpha() for char in customer_job):
                print(f"Y&S: Original regex extracted customer job: '{customer_job}'")
                return customer_job
            
        print("Y&S: No customer job found with any method")
        return ''
        
    except Exception as e:
        print(f"Y&S: Error extracting customer job: {e}")
        return ''


def extract_date(text):
    date = ''
    hit = re.search(r'Date\s*\n(\d{1,2}/\d{1,2}/\d{4})', text)
    if hit: date = hit.group(1)
    return date


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'P.O. No.\n(\w*\d*)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    # Handle various reference number formats: 069036, I-000987, 0081212A, 89779-I, etc.
    patterns = [
        r"\nInvoice #\s*([A-Za-z0-9\-]+)\n",  # General format: I-000987, 0081212A, 89779-I
        r"\nInvoice #\s*([0-9]+[A-Za-z]?)\n",  # Numbers with optional letters: 0081212A
        r"\nInvoice #\s*([A-Za-z]?[0-9]+)\n",  # Letters with numbers: I000987
        r"\nInvoice #\s*([0-9]+-[A-Za-z]+)\n",  # Numbers with dash and letters: 89779-I
        r"\nInvoice #\s*([A-Za-z]+-[0-9]+)\n",  # Letters with dash and numbers: I-000987
    ]
    
    if 'Credit No.' in text:
        credit_patterns = [
            r"\nCredit No.\s*([A-Za-z0-9\-]+)\n",  # General format for credit memos
            r"\nCredit No.\s*([0-9]+[A-Za-z]?)\n",  # Numbers with optional letters
            r"\nCredit No.\s*([A-Za-z]?[0-9]+)\n",  # Letters with numbers
        ]
        for pattern in credit_patterns:
            hit = re.search(pattern, text)
            if hit:
                ref_no = hit.group(1).strip()
                break
    else:
        for pattern in patterns:
            hit = re.search(pattern, text)
            if hit:
                ref_no = hit.group(1).strip()
                break
    
    return ref_no

