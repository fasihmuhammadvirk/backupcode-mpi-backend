import re
import tabula
import fitz
regular_area = (290, 20, 290 + 415, 20 + 570)


def is_wwps_invoice_structure(raw_text):
    """Detect WWPS invoices by their structure"""
    try:
        lines = raw_text.split('\n')
        
        # Look for the characteristic WWPS structure:
        # 1. "Sold To Ship To" header
        # 2. "MPI PLUMBING" line
        # 3. "670 MYRTLE AVE" (MPI's address)
        # 4. Ship-to address starting with "#" or containing street patterns
        
        has_sold_to_ship_to = False
        has_mpi_plumbing = False
        has_mpi_address = False
        has_ship_to_pattern = False
        
        for i, line in enumerate(lines):
            line_upper = line.upper().strip()
            
            # Check for "Sold To" and "Ship To" on same line or consecutive lines
            if "SOLD TO" in line_upper and "SHIP TO" in line_upper:
                has_sold_to_ship_to = True
            elif "SOLD TO" in line_upper and i + 1 < len(lines) and "SHIP TO" in lines[i + 1].upper().strip():
                has_sold_to_ship_to = True
            elif "SHIP TO" in line_upper and i + 1 < len(lines) and "SOLD TO" in lines[i + 1].upper().strip():
                has_sold_to_ship_to = True
                
            if "MPI PLUMBING" in line_upper:
                has_mpi_plumbing = True
            if "670 MYRTLE AVE" in line_upper:
                has_mpi_address = True
            if (line.strip().startswith('#') or 
                re.search(r'\d+.*[A-Z].*[A-Z]', line.strip()) or  # Street patterns
                re.search(r'[A-Z].*\d+.*[A-Z]', line.strip())):  # More street patterns
                has_ship_to_pattern = True
        
        # If we have the characteristic structure, it's likely a WWPS invoice
        return has_sold_to_ship_to and has_mpi_plumbing and has_mpi_address and has_ship_to_pattern
        
    except Exception as e:
        print(f"Error detecting WWPS structure: {e}")
        return False


def extract_wwps_customer_job(raw_text):
    """Extract customer job (ship-to address) from WWPS invoices"""
    try:
        lines = raw_text.split('\n')
        
        # Check if this is a CREDIT memo - handle differently
        is_credit_memo = any("CREDIT" in line.upper() for line in lines[:5])
        
        if is_credit_memo:
            # For CREDIT memos, extract customer job from ship-to section only
            # Look for the "Sold To Ship To" header pattern
            sold_to_ship_to_line = None
            for i, line in enumerate(lines):
                line_upper = line.upper().strip()
                # Check for "Sold To" and "Ship To" on same line or consecutive lines
                if "SOLD TO" in line_upper and "SHIP TO" in line_upper:
                    sold_to_ship_to_line = i
                    break
                elif "SOLD TO" in line_upper and i + 1 < len(lines) and "SHIP TO" in lines[i + 1].upper().strip():
                    sold_to_ship_to_line = i
                    break
                elif "SHIP TO" in line_upper and i + 1 < len(lines) and "SOLD TO" in lines[i + 1].upper().strip():
                    sold_to_ship_to_line = i
                    break
            
            if sold_to_ship_to_line is not None:
                # Find the ship-to section by looking for "Ship To" specifically
                ship_to_start = None
                for i in range(sold_to_ship_to_line, min(sold_to_ship_to_line + 10, len(lines))):
                    if "SHIP TO" in lines[i].upper():
                        ship_to_start = i
                        break
                
                if ship_to_start is not None:
                    # Look for customer job in the ship-to section
                    # Collect all potential addresses and job numbers
                    potential_addresses = []
                    job_numbers = []
                    
                    for i in range(ship_to_start + 1, min(ship_to_start + 50, len(lines))):
                        line = lines[i].strip()
                        
                        # Skip empty lines and basic filtering
                        if (line and 
                            len(line) > 3 and
                            not line.isdigit() and
                            not re.match(r'^\d{2}/\d{2}/\d{4}', line) and  # Skip dates
                            not re.match(r'^[A-Z]{2,}\s*\d+$', line) and  # Skip codes like "NET 120"
                            not re.match(r'^[A-Z]{1,2}\d+$', line) and  # Skip codes like "M9291012"
                            not line.startswith("ATT:") and  # Skip phone numbers
                            any(char.isalpha() for char in line)):  # Must have letters
                            
                            # Check if this looks like a street address (has numbers and letters)
                            if (re.search(r'\d+.*[A-Z]', line) or  # Street patterns like "80 Pine St"
                                re.search(r'[A-Z].*\d+.*[A-Z]', line)):  # More street patterns
                                
                                potential_addresses.append(line)
                            
                            # Also collect job numbers as fallback
                            elif line.startswith('#'):
                                job_numbers.append(line)
                    
                    # For CREDIT memos, return the first address found
                    if potential_addresses:
                        return potential_addresses[0]
                    elif job_numbers:
                        return job_numbers[0]
            
            # Fallback: look for job numbers (#234) as the customer job anywhere in the document
            for i, line in enumerate(lines):
                line = line.strip()
                if (line and 
                    line.startswith('#') and 
                    len(line) > 1 and
                    line[1:].isdigit()):  # Job number like "#234"
                    return line
            return ""
        
        # For regular invoices, extract customer job from ship-to section only
        # Look for the "Sold To Ship To" header pattern
        sold_to_ship_to_line = None
        for i, line in enumerate(lines):
            line_upper = line.upper().strip()
            # Check for "Sold To" and "Ship To" on same line or consecutive lines
            if "SOLD TO" in line_upper and "SHIP TO" in line_upper:
                sold_to_ship_to_line = i
                break
            elif "SOLD TO" in line_upper and i + 1 < len(lines) and "SHIP TO" in lines[i + 1].upper().strip():
                sold_to_ship_to_line = i
                break
            elif "SHIP TO" in line_upper and i + 1 < len(lines) and "SOLD TO" in lines[i + 1].upper().strip():
                sold_to_ship_to_line = i
                break
        
        if sold_to_ship_to_line is not None:
            # Find the ship-to section by looking for "Ship To" specifically
            ship_to_start = None
            for i in range(sold_to_ship_to_line, min(sold_to_ship_to_line + 10, len(lines))):
                if "SHIP TO" in lines[i].upper():
                    ship_to_start = i
                    break
            
            if ship_to_start is not None:
                # Look for customer job in the ship-to section
                # Collect all potential addresses and job numbers
                potential_addresses = []
                job_numbers = []
                
                for i in range(ship_to_start + 1, min(ship_to_start + 50, len(lines))):
                    line = lines[i].strip()
                    
                    # Skip empty lines and basic filtering
                    if (line and 
                        len(line) > 3 and
                        not line.isdigit() and
                        not re.match(r'^\d{2}/\d{2}/\d{4}', line) and  # Skip dates
                        not re.match(r'^[A-Z]{2,}\s*\d+$', line) and  # Skip codes like "NET 120"
                        not re.match(r'^[A-Z]{1,2}\d+$', line) and  # Skip codes like "M9291012"
                        not line.startswith("ATT:") and  # Skip phone numbers
                        any(char.isalpha() for char in line)):  # Must have letters
                        
                        # Check if this looks like a street address (has numbers and letters)
                        if (re.search(r'\d+.*[A-Z]', line) or  # Street patterns like "80 Pine St"
                            re.search(r'[A-Z].*\d+.*[A-Z]', line)):  # More street patterns
                            
                            potential_addresses.append(line)
                        
                        # Also collect job numbers as fallback
                        elif line.startswith('#'):
                            job_numbers.append(line)
                
                # For regular invoices, skip the first address (usually company address) and return the second
                if potential_addresses:
                    if len(potential_addresses) > 1:
                        return potential_addresses[1]  # Return second address (customer)
                    else:
                        return potential_addresses[0]  # Fallback to first if only one found
                elif job_numbers:
                    return job_numbers[0]
        
        # Fallback: look for patterns that indicate addresses
        # Collect all potential addresses and job numbers
        street_addresses = []
        job_numbers = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if (line and 
                len(line) > 3 and
                not line.isdigit() and
                not re.match(r'^\d{2}/\d{2}/\d{4}', line) and
                any(char.isalpha() for char in line)):
                
                if line.startswith('#'):
                    job_numbers.append((i, line))
                elif (re.search(r'\d+.*[A-Z]', line) or  # Street patterns like "123 STREET"
                      re.search(r'[A-Z].*\d+.*[A-Z]', line)):  # Patterns like "STREET 123 NAME"
                    # Basic validation: should look like a real address
                    if (len(line.split()) >= 2 and  # At least 2 words
                        not re.match(r'^[A-Z]{2,}\s*\d+$', line) and  # Not codes like "NET 120"
                        not re.match(r'^\d{2}/\d{2}/\d{4}', line) and  # Not dates
                        not '$' in line and  # Not lines with dollar amounts
                        not '%' in line):  # Not lines with percentages
                        street_addresses.append((i, line))
        
        # Return the first street address found, or empty string if no street address
        if street_addresses:
            return street_addresses[0][1]
        
        return ""
        
    except Exception as e:
        return ""


def extract_job_info(filename):
    """Extract customer job (ship-to address) from invoice"""
    try:
        raw_text = read_invoice(filename)
        
        # Check if this is a WWPS invoice and use specialized extraction
        if ("World Wide Plumbing" in raw_text or "WWPS" in raw_text or is_wwps_invoice_structure(raw_text)):
            return extract_wwps_customer_job(raw_text)
        
        # Look for ship-to address patterns
        lines = raw_text.split('\n')
        
        # Enhanced Ship To detection with multiple patterns
        ship_to_patterns = ['Ship To', 'SHIP TO', 'Ship-to', 'SHIP-TO']
        
        for i, line in enumerate(lines):
            if any(pattern in line for pattern in ship_to_patterns):
                print(f"Found Ship To pattern at line {i}: '{line.strip()}'")
                
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
                            print(f"Extracted customer job: '{address_line}' from line {j}")
                            return address_line
        
        # Fallback: look for address patterns near company names
        company_patterns = ['MPI PLUMBING', 'BMW PLUMBING', 'Y&S PLUMBING', 'PARK PLUMBING', 'WWPS']
        
        for i, line in enumerate(lines):
            if any(company in line.upper() for company in company_patterns):
                print(f"Found company pattern at line {i}: '{line.strip()}'")
                
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
                        
                        print(f"Fallback extracted customer job: '{address_line}' from line {j}")
                        return address_line
        
        # Enhanced regex fallback for Ship To patterns
        # FIX: Capture multiple lines to find actual street address instead of just company name
        ship_to_regex_patterns = [
            r'Ship\s*To\s*\n((?:[^\n]*\n){0,4}[^\n]*)',  # Ship To followed by up to 5 lines
            r'SHIP\s*TO\s*\n((?:[^\n]*\n){0,4}[^\n]*)',  # SHIP TO followed by up to 5 lines
            r'Ship\s*To\s*:\s*(.*?)\n',  # Ship To: followed by content
            r'SHIP\s*TO\s*:\s*(.*?)\n',  # SHIP TO: followed by content
        ]
        
        for pattern in ship_to_regex_patterns:
            match = re.search(pattern, raw_text, re.DOTALL | re.IGNORECASE)
            if match:
                captured_text = match.group(1).strip()

                # Split into lines and find the actual street address
                lines = [line.strip() for line in captured_text.split('\n') if line.strip()]

                customer_job = None

                # Look for a line that looks like a street address (contains numbers + street indicators)
                for line in lines:
                    has_number = any(char.isdigit() for char in line)
                    has_letters = any(char.isalpha() for char in line)

                    # Common street indicators
                    street_indicators = ['AVE', 'AVENUE', 'ST', 'STREET', 'ROAD', 'RD',
                                       'BLVD', 'BOULEVARD', 'LANE', 'LN', 'DRIVE', 'DR',
                                       'WAY', 'PLACE', 'PL', 'COURT', 'CT', 'PARKWAY', 'PKY']

                    has_street_indicator = any(indicator in line.upper() for indicator in street_indicators)

                    # Prioritize lines with street indicators
                    if has_number and has_letters:
                        if has_street_indicator:
                            customer_job = line
                            break
                        elif not customer_job:
                            customer_job = line  # Backup if no street indicator found

                # Fallback to first line if no address-like line found
                if not customer_job:
                    # Try to find any line with both numbers and letters as a last resort
                    for line in lines:
                        if any(char.isdigit() for char in line) and any(char.isalpha() for char in line):
                            customer_job = line
                            break

                # Validate that the result actually looks like an address
                if (customer_job and 
                     len(customer_job) > 3 and 
                     any(char.isalpha() for char in customer_job) and
                     any(char.isdigit() for char in customer_job)):
                    print(f"Regex extracted customer job: '{customer_job}'")
                    return customer_job
        
        # Original fallback method for non-BMW invoices
        try:
            tables = tabula.read_pdf(filename, pages=1, area=(129, 317, 143 + 55, 317 + 274), guess=False)
            job_name = ""
            potential_job_names = [tables[0].columns[0]]
            job_name = potential_job_names[0]
            potential_job_names += list(tables[0][tables[0].columns[0]])
            for pjb in potential_job_names:
                if re.split(r'\W+', pjb)[0].isdigit():
                    job_name = pjb
                    break

            if job_name.count(" ") > 4: # threshold to identify if there are extra spaces
                job_name = job_name.replace(" ", "")
                job_name = re.sub(r'(?<!^)([A-Z])', r' \1', job_name)  # add space before capital letters

            print(f"Tabula fallback extracted customer job: '{job_name}'")
            return job_name
        except:
            pass
            
        print("No customer job found with any method")
        return ""
        
    except Exception as e:
        print(f"Error extracting customer job: {e}")
        return ""


def extract_tax_etc(filename):
    # Enhanced tax extraction for all suppliers with improved detection
    try:
        raw_text = read_invoice(filename)
        
        # Check for supplier-specific patterns and use appropriate extraction
        supplier_detected = None
        
        if ("BMW Plumbing Supplies" in raw_text or 
            "BMW" in raw_text or 
            "bmw" in raw_text):
            supplier_detected = "BMW"
        elif ("Y&S Plumbing" in raw_text or 
              "Y & S Plumbing" in raw_text):
            supplier_detected = "Y&S"
        elif ("World Wide Plumbing" in raw_text or 
              "WWPS" in raw_text):
            supplier_detected = "WWPS"
        
        # Use enhanced extraction for detected suppliers
        if supplier_detected == "BMW":
            from mpi_backend.utils.pdf_to_excel.bmw_plumbing_processor import extract_tax, extract_freight
            bmw_tax = extract_tax(filename)
            bmw_freight = extract_freight(filename)
            
            result = {}
            try:
                bmw_tax_float = float(bmw_tax)
                result['tax'] = bmw_tax_float
            except:
                result['tax'] = 0.0
                
            try:
                freight_value = float(bmw_freight)
                if freight_value > 0:
                    result['freight'] = freight_value
            except:
                pass
                
            return result
            
        elif supplier_detected == "Y&S":
            from mpi_backend.utils.pdf_to_excel.ys_plumbing_processor import extract_tax
            ys_tax = extract_tax(raw_text)
            
            result = {}
            try:
                ys_tax_float = float(ys_tax)
                result['tax'] = ys_tax_float
            except:
                result['tax'] = 0.0
                
            return result
        
        # For WWPS and other suppliers, try enhanced raw text extraction first
        elif supplier_detected == "WWPS" or "Tax (" in raw_text:
            # Enhanced raw text tax extraction for all suppliers
            import re
            
            # Look for various tax patterns
            tax_patterns = [
                r'Tax\s*\([0-9]+\)\s*([0-9,]+\.?[0-9]*)',  # Tax (XXX) with amount
                r'Tax\s*\([0-9]+\)\s*\$?([0-9,]+\.?[0-9]*)',  # Tax (XXX) with $ and amount
                r'Tax\s*([0-9,]+\.?[0-9]*)',  # Just Tax with amount
                r'Tax\s*\$?([0-9,]+\.?[0-9]*)',  # Tax with $ and amount
                r'NY Sales Tax.*?([0-9,]+\.?[0-9]*)',  # NY Sales Tax
                r'NYS.*?([0-9,]+\.?[0-9]*)',  # NYS tax
            ]
            
            for pattern in tax_patterns:
                match = re.search(pattern, raw_text, re.IGNORECASE)
                if match:
                    tax_value = match.group(1)
                    tax_value = tax_value.replace(',', '').replace('$', '').strip()
                    if tax_value and tax_value != '0':
                        try:
                            tax_float = float(tax_value)
                            return {'tax': tax_float}
                        except:
                            continue
            
            # If patterns don't work, try line-by-line search
            lines = raw_text.split('\n')
            for i, line in enumerate(lines):
                if re.search(r'Tax\s*\([0-9]+\)', line, re.IGNORECASE):
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        amount_match = re.search(r'([0-9,]+\.?[0-9]*)', next_line)
                        if amount_match:
                            tax_value = amount_match.group(1)
                            tax_value = tax_value.replace(',', '').replace('$', '').strip()
                            if tax_value and tax_value != '0':
                                try:
                                    tax_float = float(tax_value)
                                    return {'tax': tax_float}
                                except:
                                    continue
                                    
    except:
        # If enhanced extraction fails, continue with normal extraction
        pass
    
    # Normal tax extraction for non-BMW invoices
    tables = tabula.read_pdf(filename, pages="all", area=regular_area)
    financial_details_table = tabula.read_pdf(filename, pages=len(tables), area=(658, 425, 658 + 84, 425 + 165),
                                              guess=False)

    if 'M e rc h a n d is e' in str(financial_details_table[0].columns.values):
        financial_details_table = tabula.read_pdf(filename, pages=len(tables), area=(650.95, 410.77, 650+84, 430+164.67),
                                              guess=False)

        tax = str(financial_details_table[0]).split('T a x ( 00 4 )')[-1]
        tax = ''.join(tax.split())

        try:
            raw_text = read_invoice(filename)
            if 'Freight\n' in raw_text:
                freight = raw_text.split('Freight\n')[1].split('\n',1)[0].replace(',','').replace(' ','')
                freight = float(freight)
                if freight > 0:
                    return {'tax' : float(tax) , "freight": freight}
                else:
                    return {'tax': tax}
            else: return {'tax': tax}
        except:
            return {'tax': tax}

    if financial_details_table[0].shape[1] == 1:
        first_item = financial_details_table[0].columns[0]
        first_col = " ".join(first_item.split(" ")[:-1])
        second_col = first_item.split(" ")[-1]
        financial_details_table[0][first_col] = financial_details_table[0][first_item].str.split().str[:-1].str.join(
            " ")
        financial_details_table[0][second_col] = financial_details_table[0][first_item].str.split().str[-1]
        financial_details_table[0] = financial_details_table[0].reindex(columns=[first_col, second_col])

    financial_data = {}

    for i in range(len(financial_details_table[0])):
        fin_key = financial_details_table[0].iloc[i].iloc[0].lower()
        if not "taxable" in fin_key and not "total" in fin_key:
            try:
                value = float(financial_details_table[0].iloc[i].iloc[1].replace("$", "").replace(",", ""))
            except:
                value = 0
            # if "sub total" in fin_key:
            #     financial_data["sub total"] = value
            #     continue
            # elif "total" in fin_key:
            #     financial_data["total"] = value
            #     continue
            if "freight" in fin_key.lower() and value > 0:
                financial_data["freight"] = value
            if "tax" in fin_key:
                financial_data["tax"] = value
                continue
            if value != 0:
                financial_data[fin_key] = value

    return financial_data


def extract_invoice_info(filename, pages =1, check = False ,supplier = "default"):
    invoice_num = ''
    invoice_date = ''
    tables = None

    if supplier == "default":
        # in case we need it in the future
        # tables = tabula.read_pdf(filename, pages=pages, area=(245, 21, 245 + 30, 21 + 160), guess=False,
        #                          columns=[20,98], pandas_options={'dtype': str})
        tables = tabula.read_pdf(
            filename,
            pages=pages,
            area=(245, 21, 300 + 30 , 21 + 160),  # Adjusted the area with the provided dimensions
            guess=False,
            columns=[20, 98],  # Adjust column positions (can tweak these as needed)
            pandas_options={'dtype': str}
        )

        try :
            if {'Unnamed: 0', 'Inv oi ce #', 'Inv oi ce D at e'}.issubset(tables[0].columns.values):
                if len(tables[0])==0: # if dataframe is empty - fix for misprinting / misplacement
                    tables = tabula.read_pdf(filename, pages=pages, area=(245, 21, 245 + 50, 21 + 160), guess=False,
                                             columns=[20, 98], pandas_options={'dtype': str})
                    tables[0].dropna(how='all', inplace=True)
                    tables[0].reset_index(inplace=True)
                invoice_num = str(tables[0]['Inv oi ce #'][0])
                invoice_date = tables[0]['Inv oi ce D at e'][0]
                invoice_num = ''.join(invoice_num.split()) # remove extra spaces
                invoice_date = ''.join(invoice_date.split())
            else:
                invoice_num = str(tables[0]['Invoice #'][0])
                invoice_date = tables[0]['Invoice Date'][0]
        except:
            return '', ''  # triggered in case no invoice num or date present

    elif supplier == "Ferguson":

        tables = tabula.read_pdf(filename, pages=pages, area=(33.84, 344.16, 56.88, 599.76), guess=False,
                                 columns=[344.16, 413.76,486.72,554.56], pandas_options={'dtype': str})

    # check will ensure that this file fulfills all criteria to be splited i.e is not supreme, page > 1 etc
    if check:
        # separate case for extraction of invoice num for all pages
        invoice_num = []

        for invoice_id in range(len(tables)):
            if supplier == "Ferguson":
                invoice_num.append(tables[invoice_id]['INVOICE NUMBER'][0])
            else:
                try:
                    invoice_num.append(tables[invoice_id]['Invoice #'][0])
                except:  invoice_num.append(tables[invoice_id]['Inv oi ce #'][0])
        return invoice_num

    return invoice_num, invoice_date


def extract_po(filename):
    tables = tabula.read_pdf(filename, pages=1, area=(215, 337, 215 + 30, 337 + 115), guess=False,
                             pandas_options={'dtype': str})
    po = ""
    if len(tables[0]):
        if {'C us tom e r P /O  #'}.issubset(tables[0].columns):
            po = tables[0]['C us tom e r P /O  #'][0]
            po = ''.join(po.split())
        else :
            po = tables[0]['Customer P/O #'][0]
    return po


def extract_buyer(filename):
    try:
        tables = tabula.read_pdf(filename, pages=1, area=(210, 243, 290, 243 + 94), guess=False,
                                 pandas_options={'dtype': str})

        if not tables or tables[0].empty:
            print("No table data found.")
            return ""

        df = tables[0]

        # Handle the specific case where buyer is split across two columns
        if 'Buyer' in df.columns and 'Unnamed: 0' in df.columns:
            first = str(df['Buyer'].iloc[0]).strip()
            last = str(df['Unnamed: 0'].iloc[0]).strip()
            return f"{first} {last}"

        elif 'Buyer' in df.columns:
            buyer_text = str(df['Buyer'].iloc[0]).strip()
            return buyer_text

        elif 'Bu ye r' in df.columns and 'Unnamed: 0' in df.columns:
            s = str(df['Bu ye r'].iloc[0]).strip()

            # First, check if it's a simple number or float
            try:
                # If it's a simple number or float, return as is
                float_val = float(s.replace(',', ''))
                return str(float_val) if float_val != int(float_val) else str(int(float_val))
            except ValueError:
                # Not a simple number, proceed with text processing
                pass

            # Try to extract phone number with various formats
            phone_patterns = [
                r'(\d[\s\(\)\-\d]{9,})',  # Matches phone numbers with various separators
                r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})',  # Standard US/Canada format
                r'(\(\d{3}\)\s*\d{3}[-.]?\d{4})',  # (123) 456-7890 format
                r'(\d{1}\s*\(\d{3}\)\s*\d{3}[-.]?\d{4})'  # 1 (123) 456-7890 format
            ]

            # Preserve original for fallback
            original_s = s
            # Remove any commas that might interfere with parsing
            s = s.replace(',', '')

            # Find the first matching phone number pattern
            phone_number = None
            for pattern in phone_patterns:
                match = re.search(pattern, s)
                if match:
                    phone_number = match.group(1).strip()
                    # Only use if we have a name before the number
                    if s.split(phone_number)[0].strip():
                        name = s.split(phone_number)[0].strip()
                        return f"{name} {phone_number}"

            # If no phone number found or no name before number, try to split by last space
            parts = re.match(r"([a-zA-Z\s]*)([\d\s\-\.]*)", original_s.replace(" ", ""))
            if parts:
                name, number = parts.group(1).strip(), re.sub(r"[^\d\.]", "", parts.group(2))
                if name and number:
                    # Format the number if it's long enough and looks like a phone number
                    if len(number) == 10 and '.' not in number:
                        number = re.sub(r"(\d{3})(\d{3})(\d{4})", r"(\1) \2-\3", number)
                    return f"{name} {number}"
                elif name:
                    return name
                elif number:
                    # If it's just a number, return it as is (could be a simple number or float)
                    try:
                        float_val = float(number)
                        return str(float_val) if float_val != int(float_val) else str(int(float_val))
                    except ValueError:
                        return number

        return s if 's' in locals() else ""

    except Exception as e:
        print("Error during PDF parsing:", e)
        return ""


def check_for_unique_invoices(filename, supplier):
    # file may have single invoice spanning over multiple pages
    unique_invoices = []

    if supplier == 'Supreme Plumbing Supply':
        with fitz.open(filename) as doc:
            for page in doc:
                text = page.get_text()
                invoice_data = text.split("Invoice", 1)
                invoice_data = invoice_data[1].split("\n", 1)
                invoice_data = invoice_data[0]
                if 8 < len(invoice_data) < 14:unique_invoices.append(invoice_data)

    elif supplier == 'AF Supply':
        with fitz.open(filename) as doc:
            for page in doc:
                text = page.get_text()
                invoice_data = text.split("INVOICE NO.", 1)
                invoice_data = invoice_data[1].split("\n", 2)
                invoice_data = invoice_data[1]
                if 8 < len(invoice_data) < 14:unique_invoices.append(invoice_data)

    elif supplier == 'Plumbing Exchange':
        with fitz.open(filename) as doc:
            for page in doc:
                try:
                    text = page.get_text()
                    invoice_num = text.split('mpip01', 1)[-1].split('\n \n', 2)[1].strip()
                except: continue
                if len(invoice_num) >= 5:unique_invoices.append(invoice_num)
    elif supplier == 'Lion Hvac Supplies':
        with fitz.open(filename) as doc:
            for page in doc:
                try:
                    text = page.get_text()
                    invoice_num = text.split('Invoice #:',1)[-1].split('\n',2)[0].strip()
                except: continue
                if len(invoice_num) >= 5: unique_invoices.append(invoice_num)

    elif supplier == "Ferguson":
        unique_invoices = extract_invoice_info(filename,'all',True,"Ferguson")

    else:

        unique_invoices = extract_invoice_info(filename, 'all', True)

    # adding break statement here
    if len(set(unique_invoices)) == 1:
        return False  # dont do anything if there is only one unique invoice id
    else:
        return True


def read_invoice(filename):
    text = ''
    with fitz.open(filename) as doc:
        for page in doc:
            text += page.get_text() +'\n'
    return text
