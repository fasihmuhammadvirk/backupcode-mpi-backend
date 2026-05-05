import tabula
import pandas as pd
import re
from .formatting_util import save_final_data
from .extraction_util import read_invoice

# Define extraction areas for YYBUNKER HVAC LLC invoice
# These areas are specifically calibrated for the YYBUNKER invoice format
INVOICE_HEADER_AREA = [50, 20, 150, 350]  # Area for invoice header info
INVOICE_ITEMS_AREA = [480, 20, 1100, 750]  # Updated area for invoice items table

# More precise area coordinates based on the invoice image structure
TABLE_AREA_COORDS = [
    [500, 0, 650, 600],    # Main table area - adjusted to capture the items table
    [480, 0, 680, 620],    # Slightly larger area
    [450, 0, 700, 650],    # Even larger fallback
    [400, 0, 750, 700],    # Maximum coverage area
]

# Column positions based on the table structure in the invoice
TABLE_COLUMNS = [75, 150, 400, 520, 580]  # Qty | Item Code | Description | Price Each | Amount

# Improved patterns for better item recognition
ITEM_KEYWORDS = [
    'ductwork', 'duct', 'fabrication', 'stainless', 'hvac', 'installation', 
    'ventilation', 'air', 'conditioning', 'heating', 'pipe', 'fitting', 'sheet', 'metal'
]

AMOUNT_PATTERN = r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
TAXABLE_AMOUNT_PATTERN = r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)T?'

def process_invoice(filename, output_path):
    """
    Process YYBUNKER HVAC LLC invoice and extract relevant information
    
    Args:
        filename: Path to the PDF invoice file
        output_path: Path to save the extracted data
    """
    print(f"\n=== Processing YYBUNKER HVAC LLC Invoice: {filename} ===")
    
    try:
        # Extract raw text from the invoice
        raw_text = read_invoice(filename)
        print(f"Successfully extracted text from invoice (length: {len(raw_text)})")
        
        # Extract all required information
        invoice_items = extract_invoice_items(filename, raw_text)
        customer_job = extract_customer_job(raw_text)
        ref_no = extract_ref_no(raw_text)
        po_no = extract_po_no(raw_text)
        date = extract_date(raw_text)
        tax = extract_tax(raw_text)
        buyer = extract_buyer(raw_text)
        
        # Validate extracted data
        if invoice_items.empty:
            print("WARNING: No invoice items extracted!")
        if not date:
            print("WARNING: No date extracted!")
        if not ref_no:
            print("WARNING: No invoice number extracted!")
            
        print(f"Extraction summary:")
        print(f"  - Items: {len(invoice_items)}")
        print(f"  - Date: {date}")
        print(f"  - Invoice #: {ref_no}")
        print(f"  - Buyer: {buyer}")
        print(f"  - Customer Job: {customer_job}")
        print(f"  - Tax: {tax}")
        
        # Process results and save to Excel
        results = process_results(invoice_items, date, ref_no, tax, customer_job, po_no, buyer)
        save_final_data(results, "YYBUNKER HVAC LLC", output_path)
        print(f"Successfully saved results to: {output_path}")
        
    except Exception as e:
        print(f"Error processing YYBUNKER HVAC LLC invoice: {e}")
        import traceback
        traceback.print_exc()
        raise

def process_results(invoice_items, date, ref_no, tax, job_name="", po_no="", buyer=""):
    """
    Process extracted invoice items and add metadata
    
    Args:
        invoice_items: DataFrame containing invoice line items
        date: Invoice date
        ref_no: Invoice reference number
        tax: Tax amount
        job_name: Customer job name
        po_no: Purchase order number
        buyer: Buyer name
        
    Returns:
        DataFrame with all required information formatted for Excel
    """
    if invoice_items.empty:
        print("Warning: No invoice items to process, creating empty results DataFrame")
        results = pd.DataFrame(columns=["Item", "Description", "Qty", "Cost", "Amount"])
    else:
        results = invoice_items.copy()
    
    # Check if a tax row already exists in the invoice items
    has_tax_row = False
    if not results.empty:
        for idx, row in results.iterrows():
            if 'sales tax' in str(row['Description']).lower() or 'tax' in str(row['Item']).lower():
                has_tax_row = True
                print(f"Tax row already exists in invoice items at index {idx}")
                break
    
    # Add tax row only if one doesn't already exist and tax amount is valid
    if not has_tax_row and tax:
        try:
            tax_value = float(str(tax).replace(',', '').replace('$', ''))
            if tax_value > 0:
                # Format tax amount with commas if needed
                if tax_value > 999:
                    tax_formatted = f"{tax_value:,.2f}"
                else:
                    tax_formatted = f"{tax_value:.2f}"
                
                tax_row = pd.DataFrame([{
                    "Item": "10 Materials",
                    "Description": "Sales Tax", 
                    "Qty": "",
                    "Cost": "", 
                    "Amount": tax_formatted
                }])
                results = pd.concat([results, tax_row], ignore_index=True)
                print(f"Added tax row with value: {tax_formatted}")
        except (ValueError, TypeError) as e:
            print(f"Error adding tax row: {e}")
    
    # Add metadata columns with proper defaults
    results["Date"] = date or ""
    results["Ref NO"] = ref_no or ""
    results["PO #"] = po_no or ""
    results['Customer Job'] = job_name or ""
    results["Bill"] = "Bill"
    results["Vendor"] = "YYBUNKER HVAC LLC"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = buyer or ""
    
    # Clean numeric columns for Excel compatibility
    for col in ['Qty', 'Cost', 'Amount']:
        if col in results.columns:
            # Ensure clean strings for Excel
            results[col] = results[col].astype(str).str.replace('$', '').str.strip()
            # For empty quantities, keep empty instead of converting to 0
            if col == 'Qty':
                results[col] = results[col].replace('', '')
            else:
                # For Cost and Amount, replace empty with 0 but preserve formatting
                mask = (results[col] == '') | (results[col] == 'nan')
                results.loc[mask, col] = '0.00'
    
    return results

def extract_buyer(text):
    """
    Extract buyer information from invoice text with improved pattern matching
    
    Args:
        text: Raw text from invoice
        
    Returns:
        Buyer name as string
    """
    buyer = ''
    
    print("\nExtracting buyer (Bill To) from text:")
    
    try:
        # Method 1: Look for Bill To section in table format (most reliable)
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if 'bill to' in line.lower() and 'ship to' in line.lower():
                # This is the header line, check the next line for values
                if i + 1 < len(lines):
                    values_line = lines[i + 1].strip()
                    print(f"  Found header line: {line}")
                    print(f"  Found values line: {values_line}")
                    
                    # Split by multiple spaces to separate bill to and ship to
                    parts = re.split(r'\s{2,}', values_line)
                    print(f"  Split parts: {parts}")
                    if len(parts) >= 1:
                        # First part should be the buyer (bill to)
                        buyer_part = parts[0].strip()
                        if buyer_part and not any(keyword in buyer_part.lower() for keyword in 
                                                ['invoice', 'date', 'yybunker', 'preston', 'brooklyn']):
                            buyer = buyer_part
                            print(f"  Found buyer: {buyer}")
                            return buyer
        
        # Method 2: Look for Bill To followed by content on next line
        if not buyer:
            for i, line in enumerate(lines):
                if 'bill to' in line.lower() and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not any(keyword in next_line.lower() for keyword in 
                                          ['ship to', 'invoice', 'date', 'yybunker', 'preston', 'brooklyn']):
                        buyer = next_line
                        print(f"  Found buyer in next line: {buyer}")
                        return buyer
        
        # Method 3: Look for pattern "Bill To: buyer_name"
        if not buyer:
            bill_to_match = re.search(r'Bill\s+To\s*:?\s*([^\n\r]+)', text, re.IGNORECASE)
            if bill_to_match:
                potential_buyer = bill_to_match.group(1).strip()
                # Clean up if it contains ship to information
                if 'ship to' in potential_buyer.lower():
                    parts = re.split(r'\s+ship\s+to\s+', potential_buyer, flags=re.IGNORECASE)
                    buyer = parts[0].strip()
                else:
                    buyer = potential_buyer
                print(f"  Found buyer using pattern matching: {buyer}")
                
    except Exception as e:
        print(f"  Error during buyer extraction: {e}")
    
    if not buyer:
        print("  No buyer found in text")
    
    return buyer

def extract_tax(text):
    """
    Extract sales tax amount from invoice text with improved accuracy
    
    Args:
        text: Raw text from invoice
        
    Returns:
        Sales tax amount as a float
    """
    tax_amount = 0.0
    
    print("\nExtracting tax amount from text:")
    
    try:
        lines = text.split('\n')
        
        # Method 1: Look for dedicated "Sales Tax" line
        for i, line in enumerate(lines):
            if 'sales tax' in line.lower():
                print(f"  Found Sales Tax line: {line}")
                
                # Extract all numbers from the line
                numbers = re.findall(AMOUNT_PATTERN, line)
                print(f"  Found numbers: {numbers}")
                
                # Skip percentage rates, look for actual amounts
                for num_str in reversed(numbers):  # Check from right to left
                    if '%' not in line[line.find(num_str):line.find(num_str) + len(num_str) + 5]:
                        try:
                            amount = float(num_str.replace(',', ''))
                            if amount > 0.01:  # Reasonable tax amount
                                tax_amount = amount
                                print(f"  Found tax amount: {tax_amount}")
                                return tax_amount
                        except ValueError:
                            continue
        
        # Method 2: Look for tax pattern with percentage
        tax_pattern = r'(\d+\.?\d*)\s*%\s*.*?(\d+(?:,\d{3})*\.?\d*)'
        matches = re.findall(tax_pattern, text)
        for rate, amount in matches:
            try:
                amount_val = float(amount.replace(',', ''))
                if 5 <= float(rate) <= 15 and amount_val > 1:  # Reasonable tax rate and amount
                    tax_amount = amount_val
                    print(f"  Found tax amount with rate pattern: {tax_amount}")
                    return tax_amount
            except ValueError:
                continue
        
        # Method 3: Look near total amount
        for i, line in enumerate(lines):
            if 'total' in line.lower():
                # Check previous lines for tax information
                for j in range(max(0, i-3), i):
                    check_line = lines[j]
                    if 'tax' in check_line.lower():
                        amounts = re.findall(AMOUNT_PATTERN, check_line)
                        if amounts:
                            try:
                                amount_val = float(amounts[-1].replace(',', ''))
                                if 1 < amount_val < 10000:  # Reasonable range
                                    tax_amount = amount_val
                                    print(f"  Found tax amount near total: {tax_amount}")
                                    return tax_amount
                            except ValueError:
                                continue
                        
    except Exception as e:
        print(f"  Error during tax extraction: {e}")
    
    if tax_amount == 0.0:
        print("  No tax amount found in text")
    
    return tax_amount

def extract_date(text):
    """
    Extract date from invoice text with multiple format support
    
    Args:
        text: Raw text from invoice
        
    Returns:
        Date as string in MM/DD/YYYY format
    """
    date = ''
    
    print("\nExtracting date from text:")
    
    try:
        # Enhanced patterns for date detection
        date_patterns = [
            r'Date\s+Invoice\s*#\s*\n[^\d]*(\d{1,2}/\d{1,2}/\d{4})',  # Table format
            r'Date\s+(\d{1,2}/\d{1,2}/\d{4})',  # Direct pattern
            r'Date[\s\n]+(\d{1,2}/\d{1,2}/\d{4})',  # With newline
            r'Date\s*:\s*(\d{1,2}/\d{1,2}/\d{4})',  # With colon
            r'(\d{1,2}/\d{1,2}/\d{4})\s+\d+',  # Date followed by invoice number
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                date_str = match.group(1)
                # Normalize date format to MM/DD/YYYY
                parts = date_str.split('/')
                if len(parts) == 3:
                    month, day, year = parts
                    date = f"{int(month):02d}/{int(day):02d}/{year}"
                    print(f"  Found date: {date}")
                    return date
        
        # Table-based extraction
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if 'date' in line.lower() and 'invoice' in line.lower():
                # Check next lines for date value
                for j in range(i+1, min(i+4, len(lines))):
                    if j < len(lines):
                        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', lines[j])
                        if date_match:
                            date_str = date_match.group(1)
                            parts = date_str.split('/')
                            if len(parts) == 3:
                                month, day, year = parts
                                date = f"{int(month):02d}/{int(day):02d}/{year}"
                                print(f"  Found date in table: {date}")
                                return date
                                
    except Exception as e:
        print(f"  Error during date extraction: {e}")
    
    if not date:
        print("  No date found in text")
    
    return date

def extract_po_no(text):
    """
    Extract purchase order number from invoice text
    
    Args:
        text: Raw text from invoice
        
    Returns:
        PO number as string
    """
    po_no = ''
    
    print("\nExtracting PO number from text:")
    
    try:
        lines = text.split('\n')
        
        # Method 1: Look for P.O. Number in table format and check if there's an actual value
        for i, line in enumerate(lines):
            if 'p.o.' in line.lower() and 'number' in line.lower():
                print(f"  Found P.O. Number header at line {i}: {line}")
                
                # Check the next few lines for the actual PO number
                for j in range(i + 1, min(i + 4, len(lines))):
                    if j < len(lines):
                        check_line = lines[j].strip()
                        print(f"  Checking line {j}: '{check_line}'")
                        
                        # Skip common field headers and empty lines
                        if (not check_line or 
                            check_line.lower() in ['terms', 'rep', 'ship', 'via', 'f.o.b.', 'project', 'total'] or
                            'due on receipt' in check_line.lower() or
                            'item code' in check_line.lower() or
                            'description' in check_line.lower() or
                            check_line.lower().startswith('yybunker')):
                            continue
                        
                        # Look for a valid PO number (alphanumeric, not just "Due")
                        po_match = re.search(r'^([A-Za-z0-9\-]{3,})$', check_line)
                        if po_match:
                            po_candidate = po_match.group(1).strip()
                            # Additional validation - exclude common non-PO terms
                            if (po_candidate.lower() not in ['due', 'receipt', 'terms', 'rep', 'ship', 'via', 'project'] 
                                and not po_candidate.isdigit() or len(po_candidate) >= 3):
                                po_no = po_candidate
                                print(f"  Found valid PO number: {po_no}")
                                return po_no
                
                # If we found a P.O. Number header but no valid value after it, 
                # it means the PO field is empty
                print("  P.O. Number field appears to be empty")
                return ''
        
        # Method 2: Direct pattern matching for cases where PO is inline
        po_patterns = [
            r'P\.O\.\s*Number\s*:?\s*([A-Za-z0-9\-]{3,})',
            r'PO\s*Number\s*:?\s*([A-Za-z0-9\-]{3,})',
            r'P\.O\.\s*#\s*([A-Za-z0-9\-]{3,})',
            r'Purchase\s+Order\s*:?\s*([A-Za-z0-9\-]{3,})',
        ]
        
        for pattern in po_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                po_candidate = match.group(1).strip()
                # Validate PO number 
                if (po_candidate.lower() not in ['due', 'receipt', 'terms', 'rep', 'ship', 'via', 'project', 'total'] 
                    and len(po_candidate) >= 3):
                    po_no = po_candidate
                    print(f"  Found PO number with pattern: {po_no}")
                    return po_no
                    
    except Exception as e:
        print(f"  Error during PO number extraction: {e}")
    
    if not po_no:
        print("  No PO number found in text")
    
    return po_no

def extract_ref_no(text):
    """
    Extract invoice reference number from invoice text with improved accuracy
    
    Args:
        text: Raw text from invoice
        
    Returns:
        Invoice number as string
    """
    ref_no = ''
    
    print("\nExtracting invoice number from text:")
    
    try:
        # Method 1: Table format extraction (most reliable for YYBUNKER)
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if 'date' in line.lower() and 'invoice' in line.lower() and '#' in line:
                # This is the header line, check the next line for values
                if i + 1 < len(lines):
                    values_line = lines[i + 1].strip()
                    print(f"  Found header line: {line}")
                    print(f"  Found values line: {values_line}")
                    
                    # Split by multiple spaces to separate date and invoice number
                    parts = re.split(r'\s{2,}', values_line)
                    print(f"  Split parts: {parts}")
                    if len(parts) >= 2:
                        # Second part should be the invoice number
                        invoice_part = parts[1].strip()
                        print(f"  Invoice part: '{invoice_part}'")
                        # Extract digits from the invoice part
                        invoice_match = re.search(r'^(\d+)$', invoice_part)
                        if invoice_match:
                            ref_no = invoice_match.group(1).strip()
                            print(f"  Found invoice number in table: {ref_no}")
                            return ref_no
        
        # Method 2: Direct pattern matching
        invoice_patterns = [
            r'Invoice\s*#\s*(\d{2,})',  # At least 2 digits
            r'Invoice\s+#\s+(\d{2,})',
            r'Invoice\s*:\s*(\d{2,})',
            r'Invoice\s+Number\s*:?\s*(\d{2,})',
        ]
        
        for pattern in invoice_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ref_no = match.group(1).strip()
                print(f"  Found invoice number with pattern: {ref_no}")
                return ref_no
        
        # Method 3: Context-based extraction
        for i, line in enumerate(lines):
            if 'invoice' in line.lower() and '#' in line and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # Look for a multi-digit number
                number_match = re.search(r'\b(\d{2,})\b', next_line)
                if number_match:
                    ref_no = number_match.group(1).strip()
                    print(f"  Found invoice number after header: {ref_no}")
                    return ref_no
                    
    except Exception as e:
        print(f"  Error during invoice number extraction: {e}")
    
    if not ref_no:
        print("  No invoice number found in text")
    
    return ref_no

def extract_customer_job(text):
    """
    Extract customer job from invoice text with better address handling
    
    Args:
        text: Raw text from invoice
        
    Returns:
        Customer job name as string
    """
    print("\nExtracting customer job (Ship To) from text:")
    job_name = ''
    
    try:
        lines = text.split('\n')
        
        # Method 1: Table format extraction
        for i, line in enumerate(lines):
            if 'bill to' in line.lower() and 'ship to' in line.lower():
                print(f"  Found header line: {line}")
                
                # Collect ship to address from subsequent lines
                address_parts = []
                for j in range(i + 1, min(i + 6, len(lines))):
                    if j < len(lines):
                        values_line = lines[j].strip()
                        if values_line:
                            print(f"  Processing line {j}: {values_line}")
                            
                            # Check if this line contains table headers or invoice fields that should stop processing
                            stop_keywords = [
                                'p.o.', 'terms', 'invoice', 'date', 'quantity', 'item', 'amount',
                                'due on receipt', 'rep', 'ship', 'via', 'f.o.b.', 'project'
                            ]
                            
                            if any(keyword in values_line.lower() for keyword in stop_keywords):
                                print(f"  Stopping at line {j} - found stop keyword in: {values_line}")
                                break
                            
                            # Split by multiple spaces to separate Bill To and Ship To columns
                            parts = re.split(r'\s{2,}', values_line)
                            print(f"  Split parts: {parts}")
                            
                            if len(parts) >= 2:
                                # Second part is Ship To address
                                ship_to_part = parts[1].strip()
                                
                                # Don't include dates or other invoice-related content
                                if (ship_to_part and 
                                    not any(keyword in ship_to_part.lower() for keyword in stop_keywords) and
                                    not re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', ship_to_part)):  # Skip dates like 4/3/2025
                                    address_parts.append(ship_to_part)
                                    print(f"  Found ship to part: {ship_to_part}")
                            elif len(parts) == 1 and j > i + 1:
                                # Continuation line with just ship to address
                                line_content = parts[0].strip()
                                
                                # Don't include dates or other invoice-related content
                                if (line_content and 
                                    not any(keyword in line_content.lower() for keyword in stop_keywords) and
                                    not re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', line_content)):  # Skip dates like 4/3/2025
                                    address_parts.append(line_content)
                                    print(f"  Found continuation line: {line_content}")
                
                # Combine address parts
                if address_parts:
                    job_name = ' '.join(address_parts)
                    print(f"  Extracted customer job: {job_name}")
                    return job_name
        
        # Method 2: Enhanced Ship To pattern extraction with multi-line support
        if not job_name:
            print("  Trying Ship To pattern extraction...")
            
            # Find "Ship To:" line and collect subsequent lines
            for i, line in enumerate(lines):
                if re.search(r'ship\s+to\s*:', line, re.IGNORECASE):
                    print(f"  Found Ship To line at {i}: {line}")
                    
                    address_parts = []
                    
                    # Extract address from the same line after "Ship To:"
                    same_line_match = re.search(r'ship\s+to\s*:\s*(.+)', line, re.IGNORECASE)
                    if same_line_match:
                        first_part = same_line_match.group(1).strip()
                        if first_part:
                            address_parts.append(first_part)
                            print(f"    Found same-line address: {first_part}")
                    
                    # Collect continuation lines (look for lines that are part of the address)
                    for j in range(i + 1, min(i + 8, len(lines))):  # Look ahead up to 8 lines
                        if j < len(lines):
                            next_line = lines[j]  # Don't strip to preserve indentation info
                            next_line_stripped = next_line.strip()
                            
                            # Skip empty lines
                            if not next_line_stripped:
                                continue
                            
                            # Stop if we hit another section header
                            stop_keywords = [
                                'bill to', 'p.o.', 'terms', 'invoice', 'quantity', 'item', 'due on receipt',
                                'rep', 'ship', 'via', 'f.o.b.', 'project', 'yybunker', 'hvac', 'llc'
                            ]
                            
                            if any(keyword in next_line_stripped.lower() for keyword in stop_keywords):
                                print(f"    Stopping at continuation line (contains stop keyword): {next_line_stripped}")
                                break
                            
                            # Skip dates
                            if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', next_line_stripped):
                                print(f"    Skipping date line: {next_line_stripped}")
                                continue
                            
                            # Check if this looks like an address line (contains letters/numbers but not just numbers)
                            is_address_like = (
                                re.search(r'[a-zA-Z0-9]', next_line_stripped) and  # Contains letters or numbers
                                len(next_line_stripped) > 1 and  # More than 1 character
                                not re.match(r'^\d+\.\d+$', next_line_stripped) and  # Not a decimal number
                                not re.match(r'^\d+/\d+/\d+$', next_line_stripped) and  # Not a date
                                not re.match(r'^\d+:\d+$', next_line_stripped) and  # Not a time
                                not (next_line_stripped.isdigit() and len(next_line_stripped) > 5)  # Not a long number (like invoice numbers)
                            )
                            
                            if is_address_like:
                                address_parts.append(next_line_stripped)
                                print(f"    Found continuation line: {next_line_stripped}")
                            else:
                                print(f"    Skipping non-address line: {next_line_stripped}")
                    
                    # Combine all address parts
                    if address_parts:
                        job_name = ' '.join(address_parts)
                        print(f"  Extracted multi-line customer job: {job_name}")
                        return job_name
        
        # Method 3: Enhanced Simple Ship To pattern with multi-line support
        if not job_name:
            print("  Trying enhanced Ship To pattern extraction...")
            
            # Find Ship To section and collect all related lines
            for i, line in enumerate(lines):
                # Look for "Ship To" header line
                if 'ship to' in line.lower():
                    print(f"  Found Ship To section at line {i}: {line}")
                    
                    address_parts = []
                    
                    # Extract any address on the same line after "Ship To"
                    if ':' in line:
                        same_line_match = re.search(r'ship\s+to\s*:\s*(.+)', line, re.IGNORECASE)
                        if same_line_match:
                            first_part = same_line_match.group(1).strip()
                            if first_part and first_part.lower() not in ['', 'ship', 'to']:
                                address_parts.append(first_part)
                                print(f"    Found same-line address: {first_part}")
                    
                    # Collect subsequent lines that are part of the Ship To address
                    for j in range(i + 1, min(i + 8, len(lines))):  # Look ahead up to 8 lines
                        if j < len(lines):
                            next_line = lines[j].strip()
                            
                            # Skip empty lines
                            if not next_line:
                                continue
                            
                            # Stop if we hit another section header or table header
                            stop_keywords = [
                                'yybunker', 'hvac', 'llc', 'preston',
                                'p.o.', 'terms', 'due on receipt', 'rep', 'ship', 'via', 'f.o.b.', 'project',
                                'quantity', 'item code', 'description', 'price each', 'amount',
                                'total', 'sales tax', 'bill to'
                            ]
                            
                            # Check if this line contains stop keywords
                            contains_stop_keyword = any(keyword in next_line.lower() for keyword in stop_keywords)
                            
                            if contains_stop_keyword:
                                print(f"    Stopping at line {j} (contains stop keyword): {next_line}")
                                break
                            
                            # Skip dates
                            if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', next_line):
                                print(f"    Skipping date line: {next_line}")
                                continue
                            
                            # Check if this looks like an address line (contains letters/numbers but not just numbers)
                            is_address_like = (
                                re.search(r'[a-zA-Z0-9]', next_line) and  # Contains letters or numbers
                                len(next_line) > 1 and  # More than 1 character
                                not re.match(r'^\d+\.\d+$', next_line) and  # Not a decimal number
                                not re.match(r'^\d+/\d+/\d+$', next_line) and  # Not a date
                                not re.match(r'^\d+:\d+$', next_line) and  # Not a time
                                not (next_line.isdigit() and len(next_line) > 5)  # Not a long number (like invoice numbers)
                            )
                            
                            if is_address_like:
                                address_parts.append(next_line)
                                print(f"    Found address line: {next_line}")
                            else:
                                print(f"    Skipping non-address line: {next_line}")
                    
                    # Combine all address parts
                    if address_parts:
                        job_name = ' '.join(address_parts)
                        print(f"  Extracted multi-line customer job: {job_name}")
                        return job_name
                    
            # Fallback patterns for single-line Ship To
            ship_to_patterns = [
                r'Ship\s+To\s*:?\s*([^\n\r]+)',
                r'Ship\s+To\s*[\n\r]+([^\n\r]+)',
            ]
            
            for pattern in ship_to_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    potential_job = match.group(1).strip()
                    if (potential_job and 
                        not any(keyword in potential_job.lower() for keyword in 
                              ['yybunker', 'preston', 'hvac', 'llc']) and
                        not re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', potential_job)):  # Skip dates
                        job_name = potential_job
                        print(f"  Found customer job with fallback pattern: {job_name}")
                        return job_name
                    
    except Exception as e:
        print(f"  Error during customer job extraction: {e}")
    
    if not job_name:
        print("  No customer job found in text")
    
    return job_name

def extract_invoice_items(filename, raw_text):
    """
    Extract invoice items from YYBUNKER HVAC LLC invoice with improved table extraction
    
    Args:
        filename: Path to the invoice PDF file
        raw_text: Raw text extracted from the PDF
        
    Returns:
        DataFrame containing extracted invoice items
    """
    print("\n==== ENHANCED YYBUNKER HVAC LLC INVOICE EXTRACTION ====\n")
    print(f"Extracting from file: {filename}")
    print(f"Raw text length: {len(raw_text)}\n")
    
    # Initialize result DataFrame
    final_df = pd.DataFrame(columns=["Item", "Description", "Qty", "Cost", "Amount"])
    
    try:
        # Method 1: Direct tabula extraction with proper table area
        print("\n=== Method 1: Direct Tabula Table Extraction ===")
        final_df = extract_items_using_tabula_enhanced(filename, raw_text)
        
        if not final_df.empty:
            print(f"Direct tabula extraction found {len(final_df)} items")
            for idx, row in final_df.iterrows():
                print(f"  Item {idx+1}: Qty={row['Qty']}, Item={row['Item']}, Amount=${row['Amount']}")
        
        # Method 2: Enhanced text-based extraction as fallback
        if final_df.empty:
            print("\n=== Method 2: Enhanced Text-Based Extraction ===")
            extracted_items = extract_items_from_enhanced_text_parsing(raw_text)
            
            if extracted_items:
                final_df = pd.DataFrame(extracted_items, columns=["Item", "Description", "Qty", "Cost", "Amount"])
                print(f"Text extraction found {len(final_df)} items")
        
        # Method 3: Pattern-based extraction as last resort
        if final_df.empty:
            print("\n=== Method 3: Fallback Pattern-Based Extraction ===")
            final_df = extract_items_using_patterns(raw_text)
    
    except Exception as e:
        print(f"Error during extraction: {e}")
        import traceback
        traceback.print_exc()
        final_df = pd.DataFrame(columns=["Item", "Description", "Qty", "Cost", "Amount"])
    
    # Final validation and cleanup
    final_df = validate_and_clean_items(final_df)
    
    # Summary
    print(f"\n=== EXTRACTION SUMMARY ===")
    print(f"Successfully extracted {len(final_df)} line items:")
    if not final_df.empty:
        for idx, row in final_df.iterrows():
            print(f"  {idx+1}. Qty: {row['Qty']}, Item: {row['Item']}, Description: {row['Description'][:50]}{'...' if len(row['Description']) > 50 else ''}")
            print(f"      Cost: ${row['Cost']}, Amount: ${row['Amount']}")
    else:
        print("  No items extracted - this may indicate an issue with the invoice format")
    
    return final_df

def extract_items_from_enhanced_text_parsing(text):
    """
    Enhanced text parsing for YYBUNKER HVAC invoices with support for structured table format
    
    Args:
        text: Raw text from invoice
        
    Returns:
        List of extracted items
    """
    extracted_items = []
    
    try:
        lines = text.split('\n')
        
        # Find the items table section - look for the header line
        table_start = None
        table_end = None
        
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            # Look for the table header
            if ('quantity' in line_lower and 'item code' in line_lower and 
                'description' in line_lower and 'amount' in line_lower):
                table_start = i + 1
                print(f"Found table header at line {i}: {line}")
                break
        
        if table_start is not None:
            # Find table end by looking for sales tax or total
            for i in range(table_start, len(lines)):
                line_lower = lines[i].lower().strip()
                if ('sales tax' in line_lower or 'total' in line_lower or 
                    'subtotal' in line_lower):
                    table_end = i
                    print(f"Found table end at line {i}: {lines[i]}")
                    break
            
            # If no end found, look for a reasonable stopping point
            if table_end is None:
                table_end = min(table_start + 15, len(lines))
            
            print(f"Processing table from line {table_start} to {table_end}")
            
            # Process each line in the table
            for i in range(table_start, table_end):
                line = lines[i].strip()
                if not line:
                    continue
                
                print(f"Processing line {i}: {line}")
                
                # Try to parse this line as a table row
                item_data = parse_structured_line(line)
                if item_data:
                    extracted_items.append(item_data)
                    print(f"  ✓ Extracted: Qty={item_data[2]}, Item={item_data[0]}, Amount=${item_data[4]}")
        
        # If structured parsing didn't work, try fallback approach
        if not extracted_items:
            print("Structured parsing failed, trying fallback line-by-line scanning...")
            for i, line in enumerate(lines):
                # Look for lines that start with a number (quantity)
                line_parts = line.strip().split()
                if (len(line_parts) >= 3 and 
                    line_parts[0].replace('.', '').isdigit() and
                    any(keyword in line.lower() for keyword in ITEM_KEYWORDS)):
                    
                    item_data = parse_structured_line(line)
                    if item_data:
                        extracted_items.append(item_data)
                        print(f"  ✓ Fallback found: {item_data[0]} - ${item_data[4]}")
    
    except Exception as e:
        print(f"Error in enhanced text parsing: {e}")
    
    return extracted_items

def parse_structured_line(line):
    """
    Parse a structured table line to extract item information
    Expected format: Quantity | Item Code | Description | Price Each | Amount
    
    Args:
        line: Line to parse
        
    Returns:
        List with [item, description, qty, cost, amount] or None
    """
    try:
        # Split the line and clean up
        parts = line.strip().split()
        if len(parts) < 3:
            return None
        
        # First part should be quantity
        quantity = parts[0].replace(',', '')
        if not quantity.replace('.', '').isdigit():
            return None
        
        # Find all monetary amounts in the line
        amounts = re.findall(r'\d+\.?\d*', line)
        monetary_amounts = []
        
        for amt in amounts:
            try:
                float_amt = float(amt)
                if float_amt > 0 and float_amt != float(quantity):
                    monetary_amounts.append(amt)
            except ValueError:
                continue
        
        if not monetary_amounts:
            return None
        
        # Extract item code (second element)
        item_code = parts[1] if len(parts) > 1 else 'HVAC Item'
        
        # Extract description by removing quantity, item code, and amounts
        description_parts = []
        for part in parts[2:]:
            # Skip if this part looks like a monetary amount
            clean_part = part.replace('$', '').replace(',', '')
            if not re.match(r'^\d+\.?\d*$', clean_part):
                description_parts.append(part)
        
        description = ' '.join(description_parts)
        if not description:
            description = f"{item_code} services"
        
        # Assign cost and amount
        if len(monetary_amounts) >= 2:
            cost = monetary_amounts[0]
            amount = monetary_amounts[-1]
        else:
            cost = monetary_amounts[0]
            amount = monetary_amounts[0]
        
        return [item_code, description, quantity, cost, amount]
    
    except Exception as e:
        print(f"Error parsing structured line: {e}")
        return None

def extract_items_using_tabula_enhanced(filename, raw_text):
    """
    Enhanced tabula extraction specifically designed for YYBUNKER HVAC table structure
    
    Args:
        filename: PDF file path
        raw_text: Raw text for reference
        
    Returns:
        DataFrame with extracted items
    """
    result_df = pd.DataFrame(columns=["Item", "Description", "Qty", "Cost", "Amount"])
    
    try:
        print("Attempting enhanced tabula extraction for YYBUNKER HVAC table format...")
        
        # Try different extraction approaches
        for i, area in enumerate(TABLE_AREA_COORDS):
            try:
                print(f"Trying area configuration {i+1}: {area}")
                
                # Method 1: Try with specific column positions
                tables = tabula.read_pdf(
                    filename, 
                    pages='all', 
                    area=area,
                    columns=TABLE_COLUMNS,
                    guess=False, 
                    stream=True,
                    pandas_options={'header': None}
                )
                
                if tables and len(tables) > 0:
                    for j, table in enumerate(tables):
                        if not table.empty:
                            print(f"Processing table {j+1} with shape: {table.shape}")
                            print(f"Table data preview:\n{table.head()}")
                            
                            processed_items = process_yybunker_table_enhanced(table, raw_text)
                            if processed_items is not None and not processed_items.empty:
                                result_df = pd.concat([result_df, processed_items], ignore_index=True)
                                print(f"Successfully extracted {len(processed_items)} items from table {j+1}")
                    
                    if not result_df.empty:
                        break
                
                # Method 2: Try without specific columns (auto-detect)
                if result_df.empty:
                    print(f"  Trying auto-detection for area {i+1}")
                    tables = tabula.read_pdf(
                        filename, 
                        pages='all', 
                        area=area,
                        guess=True, 
                        stream=True
                    )
                    
                    if tables and len(tables) > 0:
                        for table in tables:
                            if not table.empty:
                                processed_items = process_yybunker_table_enhanced(table, raw_text)
                                if processed_items is not None and not processed_items.empty:
                                    result_df = pd.concat([result_df, processed_items], ignore_index=True)
                        
                        if not result_df.empty:
                            break
                        
            except Exception as e:
                print(f"Error with area configuration {i+1}: {e}")
                continue
        
        # Method 3: Try full page extraction as last resort
        if result_df.empty:
            print("Trying full page extraction as last resort...")
            try:
                tables = tabula.read_pdf(filename, pages='all', guess=True)
                
                if tables and len(tables) > 0:
                    for table in tables:
                        if not table.empty:
                            processed_items = process_yybunker_table_enhanced(table, raw_text)
                            if processed_items is not None and not processed_items.empty:
                                result_df = pd.concat([result_df, processed_items], ignore_index=True)
                                
            except Exception as e:
                print(f"Full page extraction failed: {e}")
    
    except Exception as e:
        print(f"Enhanced tabula extraction failed: {e}")
    
    return result_df

def process_yybunker_table_enhanced(table, raw_text):
    """
    Enhanced processing for YYBUNKER HVAC table with improved item detection
    
    Args:
        table: DataFrame from tabula
        raw_text: Raw text for context
        
    Returns:
        Cleaned DataFrame with proper column mapping
    """
    result_df = pd.DataFrame(columns=["Item", "Description", "Qty", "Cost", "Amount"])
    
    try:
        print(f"Processing YYBUNKER table with shape: {table.shape}")
        print(f"Table columns: {list(table.columns)}")
        
        if table.empty:
            return result_df
        
        # Convert table to string representation for easier processing
        table_str = table.to_string()
        print(f"Table content:\n{table_str}")
        
        # Process each row
        for idx in range(len(table)):
            try:
                row = table.iloc[idx]
                row_values = []
                
                # Extract non-null values from the row
                for val in row.values:
                    if pd.notna(val) and str(val).strip() and str(val) != 'nan':
                        row_values.append(str(val).strip())
                
                if not row_values:
                    continue
                
                row_text = ' '.join(row_values).lower()
                print(f"Processing row {idx}: {row_text}")
                
                # Skip header, tax, and total rows
                if any(keyword in row_text for keyword in ['quantity', 'item code', 'description', 'price each', 'amount', 'sales tax', 'total', 'subtotal']):
                    print(f"  Skipping header/summary row: {row_text}")
                    continue
                
                # Look for rows that contain valid line item data based on structure rather than keywords
                # This makes the extraction more dynamic and keyword-independent
                if len(row_values) >= 2:
                    first_val = row_values[0].replace(',', '').strip()
                    
                    # Method 1: Check if first value is a quantity (numeric)
                    if first_val.replace('.', '').isdigit():
                        quantity = first_val
                        
                        # Extract other components with improved parsing
                        item_code = ''
                        description_parts = []
                        amounts = []
                        
                        for val in row_values[1:]:
                            val_clean = val.strip()
                            # Check if this is a monetary amount (including T suffix for taxable)
                            amount_match = re.match(r'^(\d+\.?\d*)[tT]?$', val_clean.replace('$', '').replace(',', ''))
                            
                            if amount_match and float(amount_match.group(1)) > 0:
                                amounts.append(amount_match.group(1))
                            else:
                                # This is text content (item code or description)
                                if not item_code and len(val_clean) < 20 and val_clean.isalpha():  # Short alphabetic text is likely item code
                                    item_code = val_clean
                                elif val_clean:  # Add to description if not empty
                                    description_parts.append(val_clean)
                        
                        # Build description from parts, excluding any amounts
                        description = ' '.join(description_parts).strip()
                        
                        # Set defaults if missing
                        if not item_code:
                            item_code = 'Item'
                        if not description:
                            description = f'{item_code} services'
                        
                        # Assign cost and amount properly
                        # In YYBUNKER format: first amount is unit price, second amount is total (if quantity > 1)
                        if len(amounts) >= 2:
                            cost = amounts[0]  # Unit price
                            amount = amounts[1]  # Total amount (quantity * unit price)
                        elif len(amounts) == 1:
                            cost = amounts[0]  # Unit price
                            # Calculate total amount = quantity * unit price
                            try:
                                total_amount = float(quantity) * float(cost)
                                amount = f"{total_amount:.2f}"
                            except:
                                amount = amounts[0]  # Fallback to unit price
                        else:
                            continue  # Skip if no valid amounts found
                        
                        # Create the item entry
                        item_data = {
                            'Item': item_code,
                            'Description': description,
                            'Qty': quantity,
                            'Cost': cost,
                            'Amount': amount
                        }
                        
                        result_df = pd.concat([result_df, pd.DataFrame([item_data])], ignore_index=True)
                        print(f"  ✓ Extracted: Qty={quantity}, Item={item_code}, Amount=${amount}")
                    
                    # Method 2: Check for rows with meaningful text and monetary amounts (no specific keywords)
                    elif contains_item_pattern(row_values, row_text):
                        print(f"  Found item row without leading quantity: {row_text}")
                        
                        # Extract amounts and text parts with improved separation
                        amounts = []
                        item_parts = []
                        
                        for val in row_values:
                            val_clean = val.strip()
                            # More precise amount detection including T suffix
                            amount_match = re.match(r'^(\d+\.?\d*)[tT]?$', val_clean.replace('$', '').replace(',', ''))
                            
                            if amount_match and float(amount_match.group(1)) > 0:
                                amounts.append(amount_match.group(1))
                            elif val_clean and not val_clean.replace('.', '').replace(',', '').isdigit():
                                # Only add non-numeric text parts
                                item_parts.append(val_clean)
                        
                        if amounts and item_parts:
                            # Extract item code and description dynamically with improved filtering
                            item_code = extract_item_code_dynamic(item_parts)
                            description = extract_description_dynamic_improved(item_parts, item_code, amounts)
                            
                            # For single line items without quantity, assign values properly
                            quantity = '1'
                            if len(amounts) >= 2:
                                # First amount is unit cost, second is total (if different due to quantity)
                                cost = amounts[0]
                                amount = amounts[1]
                            else:
                                # Single amount is both cost and total for qty=1
                                cost = amounts[0]
                                amount = amounts[0]
                            
                            # Create the item entry
                            item_data = {
                                'Item': item_code,
                                'Description': description,
                                'Qty': quantity,
                                'Cost': cost,
                                'Amount': amount
                            }
                            
                            result_df = pd.concat([result_df, pd.DataFrame([item_data])], ignore_index=True)
                            print(f"  ✓ Extracted item: Qty={quantity}, Item={item_code}, Amount=${amount}")
            
            except Exception as e:
                print(f"Error processing row {idx}: {e}")
                continue
    
    except Exception as e:
        print(f"Error in enhanced table processing: {e}")
    
    return result_df

def contains_item_pattern(row_values, row_text):
    """
    Dynamic pattern detection for line items without relying on specific keywords
    
    Args:
        row_values: List of cell values in the row
        row_text: Combined text of the row
        
    Returns:
        Boolean indicating if this row contains an item pattern
    """
    # Check if row has both text content and monetary amounts
    has_text = any(len(val) > 2 and not val.replace('$', '').replace(',', '').replace('.', '').isdigit() 
                  for val in row_values)
    has_amounts = any(re.match(r'^\$?\d+\.?\d*[tT]?$', val.replace(',', '').strip()) 
                     for val in row_values)
    
    # Check if it's not a header or summary row
    is_not_header = not any(keyword in row_text.lower() 
                           for keyword in ['quantity', 'item code', 'description', 'price each', 'amount'])
    is_not_summary = not any(keyword in row_text.lower() 
                            for keyword in ['sales tax', 'total', 'subtotal', 'due on receipt'])
    
    # Check for meaningful content length (not just single words)
    has_meaningful_content = len(row_text.split()) >= 3
    
    return has_text and has_amounts and is_not_header and is_not_summary and has_meaningful_content

def extract_item_code_dynamic(item_parts):
    """
    Extract item code dynamically from text parts
    
    Args:
        item_parts: List of text parts from the row
        
    Returns:
        Item code string
    """
    if not item_parts:
        return 'Item'
    
    # First non-empty part is usually the item code
    for part in item_parts:
        clean_part = part.strip()
        if clean_part and len(clean_part) < 20:  # Short text is likely item code
            return clean_part
    
    # Fallback: use first word of first meaningful part
    first_meaningful = next((part for part in item_parts if len(part.strip()) > 2), 'Item')
    return first_meaningful.split()[0] if first_meaningful.split() else 'Item'

def extract_description_dynamic_improved(item_parts, item_code, amounts):
    """
    Extract description dynamically from text parts with improved amount filtering
    
    Args:
        item_parts: List of text parts from the row
        item_code: Already extracted item code
        amounts: List of extracted amounts
        
    Returns:
        Description string
    """
    # Filter out any parts that match extracted amounts
    filtered_parts = []
    amount_strings = [str(amt) for amt in amounts]
    
    for part in item_parts:
        part_clean = part.strip()
        # Skip if this part contains any of the extracted amounts
        contains_amount = False
        for amount_str in amount_strings:
            if amount_str in part_clean or part_clean.replace('$', '').replace(',', '').replace('t', '').replace('T', '') == amount_str:
                contains_amount = True
                break
        
        if not contains_amount and part_clean:
            filtered_parts.append(part_clean)
    
    # Combine all filtered text parts
    full_text = ' '.join(filtered_parts).strip()
    
    # Remove item code from the beginning if it exists there
    if full_text.lower().startswith(item_code.lower()):
        description = full_text[len(item_code):].strip()
    else:
        description = full_text
    
    # Clean up any remaining amount patterns at the end
    description = re.sub(r'\s+\d+\.?\d*[tT]?$', '', description).strip()
    description = re.sub(r'\s+\$?\d+\.?\d*$', '', description).strip()
    
    # If no meaningful description, create a generic one
    if not description or len(description) < 5:
        description = f'{item_code} services/products'
    
    return description

def extract_items_using_patterns(text):
    """
    Fallback pattern-based extraction for edge cases
    
    Args:
        text: Raw text from invoice
        
    Returns:
        DataFrame with extracted items
    """
    result_df = pd.DataFrame(columns=["Item", "Description", "Qty", "Cost", "Amount"])
    
    try:
        print("Using pattern-based fallback extraction...")
        
        # Look for line patterns that match item + amount
        lines = text.split('\n')
        
        for line in lines:
            # Pattern: item keyword followed by amount
            for keyword in ITEM_KEYWORDS:
                if keyword in line.lower():
                    amounts = re.findall(AMOUNT_PATTERN, line)
                    if amounts:
                        clean_amounts = [amt.replace(',', '') for amt in amounts]
                        
                        item_data = {
                            'Item': keyword,
                            'Description': f"{keyword} services",
                            'Qty': '1',
                            'Cost': clean_amounts[0] if clean_amounts else '0',
                            'Amount': clean_amounts[-1] if clean_amounts else '0'
                        }
                        
                        result_df = pd.concat([result_df, pd.DataFrame([item_data])], ignore_index=True)
                        print(f"Pattern extraction found: {keyword} - ${item_data['Amount']}")
                        break
    
    except Exception as e:
        print(f"Error in pattern-based extraction: {e}")
    
    return result_df

def validate_and_clean_items(df):
    """
    Validate and clean extracted items
    
    Args:
        df: DataFrame with extracted items
        
    Returns:
        Cleaned DataFrame
    """
    if df.empty:
        return df
    
    try:
        # Remove duplicates
        df = df.drop_duplicates(subset=['Item', 'Amount'], keep='first')
        
        # Clean numeric columns while preserving formatting
        for col in ['Qty', 'Cost', 'Amount']:
            if col in df.columns:
                # First, clean the strings but preserve comma formatting for display
                df[col] = df[col].astype(str).str.replace('$', '').str.replace('T', '').str.strip()
                
                # For validation, create a numeric version
                numeric_col = f'{col}_numeric'
                try:
                    df[numeric_col] = pd.to_numeric(df[col].str.replace(',', '')).fillna(0)
                except (ValueError, TypeError):
                    df[numeric_col] = 0
                
                # For Qty, we don't need comma formatting
                if col == 'Qty':
                    df[col] = df[numeric_col].astype(int)
                    df = df.drop(columns=[numeric_col])
                else:
                    # For Cost and Amount, keep the original formatting if it looks good
                    # Otherwise, reformat with commas
                    for idx in df.index:
                        original_value = df.loc[idx, col]
                        numeric_value = df.loc[idx, numeric_col]
                        
                        # If the original has proper formatting, keep it
                        if ',' in original_value and numeric_value > 999:
                            # Already properly formatted
                            pass
                        elif numeric_value > 999:
                            # Add comma formatting
                            df.loc[idx, col] = f"{numeric_value:,.2f}"
                        else:
                            # Small amounts, no comma needed
                            df.loc[idx, col] = f"{numeric_value:.2f}"
                    
                    # Drop the temporary numeric column
                    df = df.drop(columns=[numeric_col])
        
        # Remove rows with zero amounts (using numeric check)
        try:
            amount_numeric = pd.to_numeric(df['Amount'].str.replace(',', '')).fillna(0)
        except (ValueError, TypeError):
            amount_numeric = pd.Series([0] * len(df))
        df = df[amount_numeric > 0]
        
        # Clean text columns
        for col in ['Item', 'Description']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        
        # Ensure Qty is at least 1
        df.loc[df['Qty'] <= 0, 'Qty'] = 1
        
        print(f"Validation completed: {len(df)} valid items retained")
    
    except Exception as e:
        print(f"Error during validation: {e}")
    
    return df

def extract_item_from_line(line):
    """
    DEPRECATED: Extract item details from a single line of text
    This function is kept for backward compatibility but not used in the enhanced extraction
    
    Args:
        line: A line of text that might contain item information
        
    Returns:
        List with [item_code, description, qty, cost, amount] or None if extraction fails
    """
    try:
        # For YYBUNKER format, look for any item keyword
        item_found = None
        for keyword in ITEM_KEYWORDS:
            if keyword in line.lower():
                item_found = keyword
                break
        
        if not item_found:
            return None
            
        item_data = {'Item': item_found, 'Description': '', 'Qty': '1', 'Cost': '', 'Amount': ''}
        
        # Extract description
        if 'stainless' in line.lower() and 'fabrication' in line.lower():
            item_data['Description'] = 'stainless duct fabrication / customized see packing slip'
        elif 'fabrication' in line.lower():
            item_data['Description'] = f'{item_found} fabrication services'
        else:
            item_data['Description'] = f'{item_found} services'
        
        # Extract amounts
        amounts = re.findall(AMOUNT_PATTERN, line)
        if amounts:
            clean_amounts = [amt.replace(',', '') for amt in amounts]
            if len(clean_amounts) >= 2:
                item_data['Cost'] = clean_amounts[0]
                item_data['Amount'] = clean_amounts[1]
            elif len(clean_amounts) == 1:
                item_data['Cost'] = clean_amounts[0]
                item_data['Amount'] = clean_amounts[0]
        
        if item_data['Amount']:
            return [item_data['Item'], item_data['Description'], item_data['Qty'], item_data['Cost'], item_data['Amount']]
        
        return None
    except Exception as e:
        print(f"Error extracting item from line: {e}")
        return None

def extract_items_from_text(text):
    """
    DEPRECATED: Extract invoice items from raw text when table extraction fails
    This function is kept for backward compatibility but not used in the enhanced extraction
    
    Args:
        text: Raw text from invoice
        
    Returns:
        List of invoice items with their details
    """
    items = []
    
    try:
        # Look for the invoice items section in the text
        lines = text.split('\n')
        
        # Find the section with items (between Quantity/Item Code headers and Total)
        item_section_start = -1
        item_section_end = -1
        
        for i, line in enumerate(lines):
            if 'Quantity' in line and 'Item Code' in line and 'Description' in line:
                item_section_start = i + 1
            if item_section_start > 0 and ('Total' in line or 'Sales Tax' in line):
                item_section_end = i
                break
        
        # If we found the item section, extract items
        if item_section_start > 0 and item_section_end > item_section_start:
            for i in range(item_section_start, item_section_end):
                line = lines[i].strip()
                if not line:  # Skip empty lines
                    continue
                
                # Extract item details from the line
                item_data = extract_item_from_line(line)
                if item_data:
                    items.append(item_data)
        
        # If we couldn't find the item section, try looking for lines with item keywords
        if not items:
            for line in lines:
                if any(keyword in line.lower() for keyword in ITEM_KEYWORDS):
                    item_data = extract_item_from_line(line)
                    if item_data:
                        items.append(item_data)
    
    except Exception as e:
        print(f"Error during extraction: {e}")
    
    return items

def process_table(table, raw_text):
    """
    DEPRECATED: Process and clean extracted table for YYBUNKER HVAC LLC invoices
    This function is kept for backward compatibility but not used in the enhanced extraction
    Use process_table_enhanced instead.
    
    Args:
        table: DataFrame containing raw table data
        raw_text: Raw text from invoice for reference
        
    Returns:
        Cleaned DataFrame with standardized columns
    """
    print("Warning: Using deprecated process_table function. Consider using process_yybunker_table_enhanced instead.")
    return process_yybunker_table_enhanced(table, raw_text)

    