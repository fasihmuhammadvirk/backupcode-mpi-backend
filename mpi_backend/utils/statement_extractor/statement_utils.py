import fitz
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def extract_text_from_pdf(filename):
    """
    Extract full text from a PDF file
    
    Args:
        filename: Path to the PDF file
        
    Returns:
        tuple: (full_text, page_count)
    """
    try:
        doc = fitz.open(filename)
        page_count = len(doc)
        full_text = ""
        
        for page_num in range(page_count):
            full_text += doc[page_num].get_text()
            
        return full_text, page_count
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        return "", 0

def identify_supplier(text):
    """
    Identify the supplier from the statement text
    
    Args:
        text: Extracted text from the PDF
        
    Returns:
        str: Identified supplier name or None if not recognized
    """
    # Create a comprehensive mapping of search patterns to supplier names
    # Only the 10 valid suppliers
    supplier_patterns = [
        # 1. BMW Plumbing Supplies
        (r"BMW\s*PLUMBING\s*SUPPLIES?", "BMW Plumbing Supplies"),
        (r"BMW\s*PLUMBING", "BMW Plumbing Supplies"),
        
        # 2. World Wide Plumbing
        (r"WORLD\s*WIDE\s*PLUMBING", "World Wide Plumbing"),
        (r"WORLDWIDE\s*PLUMBING", "World Wide Plumbing"),
        
        # 3. Y & S Plumbing Supply
        (r"Y\s*&\s*S\s*PLUMBING\s*SUPPLY", "Y & S Plumbing Supply"),
        (r"Y&S\s*PLUMBING\s*SUPPLY", "Y & S Plumbing Supply"),
        (r"YS\s*PLUMBING\s*SUPPLY", "Y & S Plumbing Supply"),
        (r"Y\s*&\s*S\s*PLUMBING", "Y & S Plumbing Supply"),
        (r"Y&S\s*PLUMBING", "Y & S Plumbing Supply"),
        (r"YS\s*PLUMBING", "Y & S Plumbing Supply"),
        
        # 4. Supreme Plumbing Supply
        (r"SUPREME\s*PLUMBING\s*SUPPLY", "Supreme Plumbing Supply"),
        (r"SUPREME\s*PLUMBING", "Supreme Plumbing Supply"),
        
        # 5. Pyramid Plumbing
        (r"PYRAMID\s*PLUMBING", "Pyramid Plumbing"),
        
        # 6. ABC Opus Services
        (r"ABC\s*OPUS\s*SERVICES?", "ABC Opus Services"),
        (r"ABC\s*OPUS", "ABC Opus Services"),
        
        # 7. Park Plumbing Supply
        (r"PARK\s*PLUMBING\s*SUPPLY", "Park Plumbing Supply"),
        (r"PARK\s*PLUMBING", "Park Plumbing Supply"),
        
        # 8. Gotham Plumbing Supply
        (r"GOTHAM\s*PLUMBING\s*SUPPLY", "Gotham Plumbing Supply"),
        (r"GOTHAM\s*PLUMBING", "Gotham Plumbing Supply"),
        
        # 9. FW Webb Plumbing Supply
        (r"FW\s*WEBB\s*PLUMBING\s*SUPPLY", "FW Webb Plumbing Supply"),
        (r"F\.?\s*W\.?\s*WEBB\s*PLUMBING", "FW Webb Plumbing Supply"),
        (r"WEBB\s*PLUMBING\s*SUPPLY", "FW Webb Plumbing Supply"),
        (r"FW\s*WEBB", "FW Webb Plumbing Supply"),
        
        # 10. Flow Mark Plumbing Supply
        (r"FLOW\s*MARK\s*PLUMBING\s*SUPPLY", "Flow Mark Plumbing Supply"),
        (r"FLOWMARK\s*PLUMBING\s*SUPPLY", "Flow Mark Plumbing Supply"),
        (r"FLOW\s*MARK\s*PLUMBING", "Flow Mark Plumbing Supply"),
        (r"FLOWMARK\s*PLUMBING", "Flow Mark Plumbing Supply"),
        
        # Legacy Y&S patterns for compatibility with old image
        (r"Y&S\s*PLUMBING\s*&\s*HEATING\s*SUPPLY", 
         "Y & S Plumbing Supply"),
        (r"PLUMBING\s*&\s*HEATING\s*SUPPLY", 
         "Y & S Plumbing Supply"),
        
        # Check for the company header structure from the image
        (r"Y\nS\s*PLUMBING", "Y & S Plumbing Supply"),
        (r"Y\s*S\s*PLUMBING", "Y & S Plumbing Supply"),
        
        # More flexible patterns
        (r"STATEMENT.*YS", "Y & S Plumbing Supply"),
        (r"STATEMENT.*Y\s*&\s*S", "Y & S Plumbing Supply"),
    ]
    
    # Check each pattern first
    for pattern, supplier_name in supplier_patterns:
        if re.search(pattern, text.upper()):
            return supplier_name
    
    # Enhanced extraction from document header
    # Look for the company logo/header area which typically appears first
    lines = text.split('\n')
    
    # Define keyword-to-supplier mappings for header analysis
    # Only the 10 valid suppliers
    supplier_keywords = {
        'BMW Plumbing Supplies': ['BMW', 'PLUMBING'],
        'World Wide Plumbing': ['WORLD', 'WIDE', 'PLUMBING'],
        'Y & S Plumbing Supply': ['Y&S', 'YS', 'Y', 'S', 'PLUMBING'],
        'Supreme Plumbing Supply': ['SUPREME', 'PLUMBING'],
        'Pyramid Plumbing': ['PYRAMID', 'PLUMBING'],
        'ABC Opus Services': ['ABC', 'OPUS'],
        'Park Plumbing Supply': ['PARK', 'PLUMBING'],
        'Gotham Plumbing Supply': ['GOTHAM', 'PLUMBING'],
        'FW Webb Plumbing Supply': ['WEBB', 'PLUMBING', 'FW', 'F.W.'],
        'Flow Mark Plumbing Supply': ['FLOW', 'MARK', 'FLOWMARK', 'PLUMBING']
    }
    
    # Look for company names in the first few lines after "STATEMENT"
    for i in range(min(20, len(lines))):  # Check first 20 lines
        line = lines[i].strip()
        if line:
            line_upper = line.upper()
            
            # Check each supplier's keywords
            for supplier_name, keywords in supplier_keywords.items():
                # Check if all required keywords are present in nearby lines
                nearby_text = ' '.join([
                    lines[j].strip().upper() 
                    for j in range(max(0, i-2), min(len(lines), i+3))
                ])
                
                # For suppliers with multiple keywords, check if enough
                # are present
                keyword_matches = sum(1 for keyword in keywords 
                                      if keyword in nearby_text)
                
                # Different thresholds based on supplier complexity
                if supplier_name in ['Y & S Plumbing Supply',
                                     'FW Webb Plumbing Supply']:
                    # Need at least 2 keywords for complex names
                    if keyword_matches >= 2:
                        return supplier_name
                elif supplier_name == 'ABC Opus Services':
                    # Special case: need both ABC and OPUS
                    if 'ABC' in nearby_text and 'OPUS' in nearby_text:
                        return supplier_name
                elif supplier_name == 'World Wide Plumbing':
                    # Need WORLD and either WIDE or PLUMBING
                    if ('WORLD' in nearby_text and 
                            ('WIDE' in nearby_text or 
                             'PLUMBING' in nearby_text)):
                        return supplier_name
                else:
                    # For simpler names, one strong keyword match is enough
                    primary_keyword = keywords[0]
                    if (primary_keyword in line_upper and 
                            'PLUMBING' in nearby_text):
                        return supplier_name
            
            # Generic check for PLUMBING companies in general
            # Only return if it matches one of our known suppliers
            if 'PLUMBING' in line_upper:
                # Check if this looks like a company name
                if ('CORP' in line_upper or 'INC' in line_upper or 
                    'LLC' in line_upper or 'COMPANY' in line_upper or 
                    'CO' in line_upper or 'SUPPLY' in line_upper or
                    'HEATING' in line_upper or 'SERVICES' in line_upper or 
                        len(line.split()) > 1):
                    
                    # Clean up the line and check if it matches suppliers
                    cleaned_name = line.title().replace('.', '').strip()
                    if cleaned_name and len(cleaned_name) > 3:
                        # Check if it contains keywords from valid suppliers
                        cleaned_upper = cleaned_name.upper()
                        for supplier_name, keywords in (
                                supplier_keywords.items()):
                            if any(keyword in cleaned_upper 
                                   for keyword in keywords[:2]):
                                return supplier_name
            
            # Generic check for companies ending in SUPPLY
            if (line_upper.endswith("SUPPLY") and 
                    ('PLUMBING' in line_upper or 
                     'SERVICES' in line_upper)):
                # Check if it matches our valid suppliers
                title_line = line.title()
                for supplier_name in supplier_keywords.keys():
                    if any(word in title_line 
                           for word in supplier_name.split()):
                        return supplier_name
    
    return None

def extract_statement_metadata(text):
    """
    Extract common statement metadata from the text
    
    Args:
        text: The raw text extracted from the PDF
        
    Returns:
        dict: Metadata including statement_date, account_number, etc.
    """
    metadata = {
        "statement_date": "",
        "account_number": "",
        "supplier_name": "",
    }
    
    # Extract supplier name FIRST (before other patterns)
    metadata["supplier_name"] = identify_supplier(text) or ""
    
    # Extract statement date (try multiple patterns)
    date_patterns = [
        # Y&S specific format: "Statement Date 04/30/25"
        r'Statement\s+Date\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        # Other common formats
        r'Statement Date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})',
        r'Statement Date[^\d]*(\d{1,2}/\d{1,2}/\d{2,4})',
        r'Date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})',
        r'Statement\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})',
        # More flexible patterns for statement headers
        r'STATEMENT[^\n]*?(\d{1,2}/\d{1,2}/\d{2,4})',
        r'Statement[^\n]*?(\d{1,2}/\d{1,2}/\d{2,4})'
    ]
    
    for pattern in date_patterns:
        date_match = re.search(pattern, text, re.IGNORECASE)
        if date_match:
            metadata["statement_date"] = date_match.group(1)
            break
    
    # If no match was found, try finding any date in the header area
    if not metadata["statement_date"]:
        # Look for date in the first few lines (header area)
        lines = text.split('\n')
        for i, line in enumerate(lines[:10]):  # Check first 10 lines
            if 'STATEMENT' in line.upper() or 'Statement' in line:
                # Look for date pattern in this line and surrounding lines
                surrounding_text = ' '.join(lines[max(0, i-1):i+3])
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', surrounding_text)
                if date_match:
                    metadata["statement_date"] = date_match.group(1)
                    break
    
    # Extract account number (try multiple patterns)
    acct_patterns = [
        r'Customer Account\s*[:\-]?\s*(\d+)',
        r'Account #\s*[:\-]?\s*(\d+)',
        r'Account Number\s*[:\-]?\s*(\d+)',
        r'Customer #\s*[:\-]?\s*(\d+)',
        r'Customer\s*Account[^\d]*(\d+)'
    ]
    
    for pattern in acct_patterns:
        acct_match = re.search(pattern, text, re.IGNORECASE)
        if acct_match:
            metadata["account_number"] = acct_match.group(1)
            break
    
    # If no match was found, try finding any sequence of digits near "Account"
    if not metadata["account_number"]:
        account_section = re.search(
            r'Account(.*?)(?=\n|\Z)', text, 
            re.IGNORECASE | re.DOTALL)
        if account_section:
            account_match = re.search(
                r'(\d{5,})', account_section.group(1))
            if account_match:
                metadata["account_number"] = account_match.group(1)
    
    # Only look for supplier name in customer info if we haven't found it yet
    if not metadata["supplier_name"]:
        # Check for common supplier/customer info format
        customer_info = re.search(
            r'(?:CUSTOMER|SOLD TO|BILL TO)[^\n]*\n(.*?)\n(.*?)\n(.*?)\n',
            text, re.IGNORECASE | re.DOTALL)
        if customer_info:
            potential_name = customer_info.group(1).strip()
            # Only use this if it looks like a company name (not an address)
            if (potential_name and len(potential_name) > 3 and 
                    not re.search(r'\d{5}', potential_name)):
                metadata["supplier_name"] = potential_name
    
    return metadata

def extract_summary_data(text):
    """
    Extract summary data from a statement text (e.g., total due, aging details)
    
    Args:
        text: Full text extracted from the PDF
        
    Returns:
        dict: Summary data with keys like 'total_due', 'current', '30_days'
    """
    summary = {}
    
    try:
        # Pattern for balance due line
        balance_patterns = [
            r"Balance Due[^\d]*[\$]?([\d,]+\.\d{2})",
            r"Total Due[^\d]*[\$]?([\d,]+\.\d{2})",
            r"Amount Due[^\d]*[\$]?([\d,]+\.\d{2})",
            r"Balance Due[\s:]*[\$]?([\d,]+\.\d{2})"
        ]
        
        for pattern in balance_patterns:
            balance_match = re.search(pattern, text, re.IGNORECASE)
            if balance_match:
                summary['total_due'] = float(
                    balance_match.group(1).replace(',', ''))
                break
        
        # Pattern for aging details
        aging_patterns = [
            ('current', [r"Current[^\d]*[\$]?([\d,]+\.\d{2})"]),
            ('30_days', [r"30 Days[^\d]*[\$]?([\d,]+\.\d{2})", 
                         r"1-30 Days[^\d]*[\$]?([\d,]+\.\d{2})"]),
            ('60_days', [r"60 Days[^\d]*[\$]?([\d,]+\.\d{2})", 
                         r"31-60 Days[^\d]*[\$]?([\d,]+\.\d{2})"]),
            ('90_days', [r"90 Days[^\d]*[\$]?([\d,]+\.\d{2})", 
                         r"61-90 Days[^\d]*[\$]?([\d,]+\.\d{2})"]),
            ('120_days_plus', [r"120 & Over[^\d]*[\$]?([\d,]+\.\d{2})", 
                               r"120\+ Days[^\d]*[\$]?([\d,]+\.\d{2})", 
                               r"Over 90 Days[^\d]*[\$]?([\d,]+\.\d{2})"])
        ]
        
        for key, patterns in aging_patterns:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    summary[key] = float(match.group(1).replace(',', ''))
                    break
        
        # If we couldn't find aging data with regex, try to extract from
        # a more structured approach
        if not summary:
            # Look for a section with all the aging columns
            aging_section = re.search(
                r'(Current\s+30 Days\s+60 Days\s+90 Days\s+120.*?)'
                r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+'
                r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})', 
                text, re.IGNORECASE | re.DOTALL)
            if aging_section:
                summary['current'] = float(
                    aging_section.group(2).replace(',', ''))
                summary['30_days'] = float(
                    aging_section.group(3).replace(',', ''))
                summary['60_days'] = float(
                    aging_section.group(4).replace(',', ''))
                summary['90_days'] = float(
                    aging_section.group(5).replace(',', ''))
                summary['120_days_plus'] = float(
                    aging_section.group(6).replace(',', ''))
                
                # Calculate total due if not already set
                if 'total_due' not in summary:
                    summary['total_due'] = sum([
                        summary.get('current', 0),
                        summary.get('30_days', 0),
                        summary.get('60_days', 0),
                        summary.get('90_days', 0),
                        summary.get('120_days_plus', 0)
                    ])
    
    except Exception as e:
        logger.error(f"Error extracting summary data: {str(e)}")
    
    return summary

def format_date(date_str):
    """
    Standardize date format
    
    Args:
        date_str: Date string in various formats
        
    Returns:
        str: Standardized date string (MM/DD/YYYY)
    """
    if not date_str:
        return ""
    
    try:
        # Try different date formats
        formats = ('%m/%d/%y', '%m/%d/%Y', '%d/%m/%y', 
                   '%d/%m/%Y', '%Y-%m-%d')
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime('%m/%d/%Y')
            except ValueError:
                continue
    except Exception:
        pass
    
    return date_str  # Return original if parsing fails 