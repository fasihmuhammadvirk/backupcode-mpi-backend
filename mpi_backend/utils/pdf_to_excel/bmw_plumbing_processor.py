import pandas as pd
import re
import fitz
import tabula
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data_for_database

regular_area = (300, 44, 300+341, 44+531)
credit_memo_area = (268,35.5, 268 + 342, 35.5 +540)
bmw_plumbing_columns = [44, 84.2, 165.5, 445.5, 508]
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
                                   columns=bmw_plumbing_columns)
        else:
            # Use enhanced processing for all other BMW invoices
            tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True, 
                                   columns=bmw_plumbing_columns)
    
    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)
    
    # Enhanced tax extraction for all BMW invoices
    tax = extract_tax(filename)
    
    # Extract freight amount for all BMW invoices
    freight = extract_freight(filename)

    # Preserve old credit memo logic
    if is_credit_memo:
        hit = re.search(r'Credit No.\s*([A-Za-z0-9\-]+)\n', raw_text)
        if hit: 
            ref_no = hit.group(1)
        try:
            tax = '-' + raw_text.rsplit('-',1)[-1].replace('$','').replace(',','')
            tax = float(tax)
        except:
            tax = 0

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no, freight)
    save_final_data_for_database(result, "BMW Plumbing Supplies", output_path)


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
    First tries to extract from data rows, falls back to raw text extraction if needed.
    """
    try:
        # First try raw text extraction (most reliable for BMW invoices)
        import fitz
        doc = fitz.open(filename)
        raw_text = doc[0].get_text()
        doc.close()
        
        # Look for tax patterns in raw text (enhanced to handle all tax codes)
        tax_patterns = [
            r'Tax\s*\(00[246]\)\s*([0-9,]+\.?[0-9]*)',  # Tax (002), Tax (004), or Tax (006) with amount
            r'Tax\s*\(00[246]\)\s*\$?([0-9,]+\.?[0-9]*)',  # Tax (002), Tax (004), or Tax (006) with $ and amount
            r'Tax\s*\([0-9]+\)\s*([0-9,]+\.?[0-9]*)',  # Tax with any number in parentheses
            r'Tax\s*\([0-9]+\)\s*\$?([0-9,]+\.?[0-9]*)',  # Tax with any number in parentheses and $
            r'Tax\s*([0-9,]+\.?[0-9]*)',  # Just Tax with amount
            r'Tax\s*\$?([0-9,]+\.?[0-9]*)',  # Tax with $ and amount
        ]
        
        for pattern in tax_patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                tax_value = match.group(1)
                # Clean up the extracted value
                tax_value = tax_value.replace(',', '').replace('$', '').strip()
                if tax_value and tax_value != '0':
                    return tax_value
        
        # If raw text patterns don't work, try to find tax on the line after any "Tax (XXX)" pattern
        lines = raw_text.split('\n')
        for i, line in enumerate(lines):
            # Look for any Tax pattern with parentheses
            if re.search(r'Tax\s*\([0-9]+\)', line, re.IGNORECASE):
                # Look for amount on the next line
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # Check if next line contains a number
                    amount_match = re.search(r'([0-9,]+\.?[0-9]*)', next_line)
                    if amount_match:
                        tax_value = amount_match.group(1)
                        tax_value = tax_value.replace(',', '').replace('$', '').strip()
                        if tax_value and tax_value != '0':
                            return tax_value
        
        # Fallback to tabula extraction if raw text fails
        try:
            tables = tabula.read_pdf(filename, pages='all')
            
            if not tables:
                return '0'
            
            # Get the last table (financial summary)
            last_table = tables[-1]
            
            # Try to extract tax from data rows
            tax_amount = extract_tax_from_data_rows(last_table)
            
            if tax_amount != '0':
                return tax_amount
            
            # Fallback to old method if new method didn't work
            return last_table.columns.values[-1].replace('$','').replace(',','')
            
        except Exception as tabula_error:
            print(f"Tabula extraction failed for {filename}: {tabula_error}")
            return '0'
        
    except Exception as e:
        # If anything fails, return 0 as fallback
        print(f"Error extracting tax from {filename}: {e}")
        return '0'


def extract_freight(filename):
    """
    Extract freight amount from BMW invoices.
    Handles different freight formats and patterns.
    Also handles cases where freight is combined with tax in the amount field.
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
            
            # Check for combined freight+tax strings in table data
            freight_amount = extract_freight_from_combined_strings(last_table)
            if freight_amount != 0:
                return freight_amount
        
        return 0.0
        
    except Exception as e:
        print(f"Error extracting freight from {filename}: {e}")
        return 0.0


def extract_tax_from_combined_string(combined_string):
    """
    Extract tax amount from a combined string like:
    'Merchandise19.760FreightMiscCharges0.000.001SubTotal19.762Taxable0.003Tax(006)0.00'
    """
    try:
        # Pattern to match Tax(006) or Tax(004) followed by amount
        tax_pattern = r'Tax\s*\(00[46]\)\s*([0-9,]+\.?[0-9]*)'
        match = re.search(tax_pattern, combined_string, re.IGNORECASE)
        if match:
            tax_value = match.group(1)
            tax_value = tax_value.replace(',', '').replace('$', '').strip()
            return tax_value if tax_value and tax_value != '0' else '0'
        
        # Fallback pattern for just 'Tax' followed by amount
        tax_pattern_fallback = r'Tax\s*([0-9,]+\.?[0-9]*)'
        match = re.search(tax_pattern_fallback, combined_string, re.IGNORECASE)
        if match:
            tax_value = match.group(1)
            tax_value = tax_value.replace(',', '').replace('$', '').strip()
            return tax_value if tax_value and tax_value != '0' else '0'
        
        return '0'
    except Exception as e:
        print(f"Error extracting tax from combined string: {e}")
        return '0'


def extract_freight_from_combined_strings(table):
    """
    Extract freight amount from table data that contains combined freight+tax strings.
    """
    try:
        if hasattr(table, 'iloc'):
            for i in range(len(table)):
                try:
                    row_text = str(table.iloc[i]).lower()
                    if 'tax' in row_text and any(char.isdigit() for char in row_text):
                        # Found a tax row, check for combined freight+tax string
                        for col in table.columns:
                            cell_value = str(table.iloc[i][col])
                            if 'freight' in cell_value.lower() and 'tax' in cell_value.lower():
                                # Extract freight from combined string
                                freight_amount = extract_freight_from_combined_string(cell_value)
                                if freight_amount != 0:
                                    return freight_amount
                except:
                    continue
        return 0.0
    except Exception as e:
        print(f"Error extracting freight from combined strings: {e}")
        return 0.0


def extract_freight_from_combined_string(combined_string):
    """
    Extract freight amount from a combined string like:
    'Merchandise19.760FreightMiscCharges0.000.001SubTotal19.762Taxable0.003Tax(006)0.00'
    """
    try:
        # Pattern to match Freight followed by amount (with or without spaces)
        # Handle cases like 'FreightMiscCharges0.00' or 'Freight 25.50'
        freight_patterns = [
            r'Freight\s*([0-9,]+\.?[0-9]*)',  # Freight followed by amount
            r'Freight([0-9,]+\.?[0-9]*)',     # Freight directly followed by amount
            r'FreightMiscCharges([0-9,]+\.?[0-9]*)',  # FreightMiscCharges pattern
        ]
        
        for pattern in freight_patterns:
            match = re.search(pattern, combined_string, re.IGNORECASE)
            if match:
                freight_value = match.group(1)
                freight_value = freight_value.replace(',', '').replace('$', '').strip()
                return float(freight_value) if freight_value and freight_value != '0' else 0.0
        
        return 0.0
    except Exception as e:
        print(f"Error extracting freight from combined string: {e}")
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
                    if 'freight' in row_text and any(char.isdigit() for char in row_text):
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


def extract_tax_from_data_rows(table):
    """
    Extract tax amount from the actual data rows of the financial summary table.
    Handles different tax formats like 'Tax (004)', 'Tax (006)', 'Tax', etc.
    Also handles cases where freight is combined with tax in the amount field.
    """
    try:
        # Convert table to string for easier pattern matching
        table_str = str(table)
        
        # Look for tax patterns in the data (enhanced to handle all tax codes)
        tax_patterns = [
            r'Tax\s*\(00[246]\)\s*([0-9,]+\.?[0-9]*)',  # Tax (002), Tax (004), or Tax (006) with amount
            r'Tax\s*\(00[246]\)\s*\$?([0-9,]+\.?[0-9]*)',  # Tax (002), Tax (004), or Tax (006) with $ and amount
            r'Tax\s*\([0-9]+\)\s*([0-9,]+\.?[0-9]*)',  # Tax with any number in parentheses
            r'Tax\s*\([0-9]+\)\s*\$?([0-9,]+\.?[0-9]*)',  # Tax with any number in parentheses and $
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
        
        # If no pattern match found, try to find tax on the line after any "Tax (XXX)" pattern
        lines = table_str.split('\n')
        for i, line in enumerate(lines):
            # Look for any Tax pattern with parentheses
            if re.search(r'Tax\s*\([0-9]+\)', line, re.IGNORECASE):
                # Look for amount on the next line
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # Check if next line contains a number
                    amount_match = re.search(r'([0-9,]+\.?[0-9]*)', next_line)
                    if amount_match:
                        tax_value = amount_match.group(1)
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
                                # Check if this is a combined freight+tax string
                                if 'freight' in cell_value.lower() and 'tax' in cell_value.lower():
                                    # Extract tax from combined string
                                    tax_amount = extract_tax_from_combined_string(cell_value)
                                    if tax_amount != '0':
                                        return tax_amount
                                else:
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
    """Extract customer job (ship-to address) from BMW invoices"""
    try:
        lines = raw_text.split('\n')
        
        # Enhanced Ship To detection with multiple patterns
        ship_to_patterns = ['Ship To', 'SHIP TO', 'Ship-to', 'SHIP-TO']
        
        for i, line in enumerate(lines):
            if any(pattern in line for pattern in ship_to_patterns):
                print(f"BMW: Found Ship To pattern at line {i}: '{line.strip()}'")
                
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
                            print(f"BMW: Extracted customer job: '{address_line}' from line {j}")
                            return address_line
        
        # Fallback: look for address patterns near company names
        company_patterns = ['MPI PLUMBING', 'BMW PLUMBING', 'Y&S PLUMBING', 'PARK PLUMBING', 'WWPS']
        
        for i, line in enumerate(lines):
            if any(company in line.upper() for company in company_patterns):
                print(f"BMW: Found company pattern at line {i}: '{line.strip()}'")
                
                # Look for address in nearby lines (expanded range)
                for j in range(max(0, i-5), min(len(lines), i+8)):
                    address_line = lines[j].strip()
                    
                    if (address_line and 
                        len(address_line) > 3 and
                        not any(header in address_line.upper() for header in ['CUSTOMER #', 'ORDER DATE', 'SALES ORDER', 'BUYER', 'INVOICE #', 'INVOICE DATE', 'SHIP TO']) and
                        not re.match(r'^\d{2}/\d{2}/\d{4}', address_line) and  # Skip dates
                        not re.match(r'^Date:', address_line) and  # Skip date headers
                        any(char.isdigit() for char in address_line) and  # Address should contain numbers
                        any(char.isalpha() for char in address_line)):  # And letters
                        
                        print(f"BMW: Fallback extracted customer job: '{address_line}' from line {j}")
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
                    print(f"BMW: Regex extracted customer job: '{customer_job}'")
                    return customer_job
        
        # Original fallback method
        hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
        if hit:
            customer_job = hit.group(1).strip()
            if len(customer_job) > 3 and any(char.isalpha() for char in customer_job):
                print(f"BMW: Original regex extracted customer job: '{customer_job}'")
                return customer_job
            
        print("BMW: No customer job found with any method")
        return ''
        
    except Exception as e:
        print(f"BMW: Error extracting customer job: {e}")
        return ''


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
    # Handle various reference number formats: 066617, I-000987, 0081212A, 89779-I, etc.
    patterns = [
        r"\nInvoice #\s*([A-Za-z0-9\-]+)\n",  # General format: I-000987, 0081212A, 89779-I
        r"\nInvoice #\s*([0-9]+[A-Za-z]?)\n",  # Numbers with optional letters: 0081212A
        r"\nInvoice #\s*([A-Za-z]?[0-9]+)\n",  # Letters with numbers: I000987
        r"\nInvoice #\s*([0-9]+-[A-Za-z]+)\n",  # Numbers with dash and letters: 89779-I
        r"\nInvoice #\s*([A-Za-z]+-[0-9]+)\n",  # Letters with dash and numbers: I-000987
    ]
    
    for pattern in patterns:
        hit = re.search(pattern, text)
        if hit:
            ref_no = hit.group(1).strip()
            break
    
    return ref_no

