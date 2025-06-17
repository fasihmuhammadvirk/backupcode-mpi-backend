import pandas as pd
import tabula
import re
import fitz
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class YSStatementExtractor:
    """
    Specialized extractor for Y&S Plumbing Supply statements
    Addresses specific formatting issues with dates and amounts
    """
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.extracted_data = pd.DataFrame()
        self.metadata = {}
        
    def extract_statement_metadata(self) -> Dict[str, str]:
        """Extract metadata specifically for Y&S statements"""
        try:
            doc = fitz.open(self.pdf_path)
            full_text = doc[0].get_text()
            doc.close()
            
            metadata = {
                "statement_date": "",
                "account_number": "",
                "supplier_name": "Y & S Plumbing Supply",
                "customer_name": "",
                "terms": ""
            }
            
            # Extract statement date - Y&S specific patterns
            date_patterns = [
                r'Statement\s+Date\s+(\d{1,2}/\d{1,2}/\d{2,4})',
                r'Statement Date\s+(\d{1,2}/\d{1,2}/\d{2,4})', 
                r'STATEMENT.*?(\d{1,2}/\d{1,2}/\d{2,4})',
                # More flexible pattern for Y&S
                r'Statement[^\n]*?(\d{1,2}/\d{1,2}/\d{2,4})'
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    metadata["statement_date"] = match.group(1)
                    logger.info(f"Found statement date: {metadata['statement_date']}")
                    break
            
            # Extract customer account number
            account_patterns = [
                r'Customer Account\s+(\d+)',
                r'Account[:\s]+(\d+)',
                r'Customer Account[:\s]+(\d+)'
            ]
            
            for pattern in account_patterns:
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    metadata["account_number"] = match.group(1)
                    logger.info(f"Found account number: {metadata['account_number']}")
                    break
            
            # Extract terms
            terms_match = re.search(r'Terms\s+Net\s+(\d+)', full_text, re.IGNORECASE)
            if terms_match:
                metadata["terms"] = f"Net {terms_match.group(1)}"
            
            # Extract customer name (MPI PLUMBING CORP.)
            customer_match = re.search(r'(MPI PLUMBING CORP\.?)', full_text, re.IGNORECASE)
            if customer_match:
                metadata["customer_name"] = customer_match.group(1)
            
            self.metadata = metadata
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting Y&S metadata: {str(e)}")
            return {
                "statement_date": "",
                "account_number": "", 
                "supplier_name": "Y & S Plumbing Supply",
                "customer_name": "",
                "terms": ""
            }
    
    def extract_invoice_data(self) -> pd.DataFrame:
        """Extract invoice data using multiple strategies optimized for Y&S format"""
        
        # Multiple extraction strategies for Y&S statements
        strategies = [
            {
                "name": "Y&S Optimized",
                "params": {
                    "pages": "all",
                    "area": [230, 25, 680, 580],  # Adjusted area for Y&S
                    "columns": [83, 151, 264, 345, 416, 495, 582],  # Refined column positions
                    "stream": True,
                    "pandas_options": {"header": None}
                }
            },
            {
                "name": "WWPS Compatible", 
                "params": {
                    "pages": "all",
                    "area": [290, 20, 705, 590],
                    "stream": True,
                    "pandas_options": {"header": None}
                }
            },
            {
                "name": "Auto Detect",
                "params": {
                    "pages": "all",
                    "lattice": True,
                    "pandas_options": {"header": None}
                }
            },
            {
                "name": "Stream Only",
                "params": {
                    "pages": "all", 
                    "stream": True,
                    "pandas_options": {"header": None}
                }
            }
        ]
        
        all_data = []
        
        for strategy in strategies:
            try:
                logger.info(f"Trying extraction strategy: {strategy['name']}")
                
                tables = tabula.read_pdf(self.pdf_path, **strategy['params'])
                
                if tables and len(tables) > 0:
                    df = tables[0]
                    
                    # Validate the extracted data
                    if self._validate_ys_data(df):
                        logger.info(f"✅ Successfully extracted {len(df)} rows using {strategy['name']}")
                        all_data.append(df)
                        break  # Use first successful extraction
                    else:
                        logger.debug(f"Data validation failed for {strategy['name']}")
                        
            except Exception as e:
                logger.debug(f"Strategy {strategy['name']} failed: {str(e)}")
                continue
        
        if all_data:
            # Use the best extraction result
            raw_data = all_data[0]
            
            # Process and clean the data
            cleaned_data = self._process_ys_data(raw_data)
            
            self.extracted_data = cleaned_data
            return cleaned_data
        else:
            logger.error("No extraction strategy succeeded for Y&S statement")
            return pd.DataFrame()
    
    def _validate_ys_data(self, df: pd.DataFrame) -> bool:
        """Validate if extracted data looks like Y&S invoice data"""
        if df.empty or len(df) < 3:
            return False
        
        # Should have 6-7 columns for Y&S format
        if len(df.columns) < 6 or len(df.columns) > 8:
            return False
        
        # Check if we have some numeric data (amounts)
        numeric_found = False
        for col in df.columns:
            sample_values = df[col].dropna().head(5)
            for val in sample_values:
                if self._looks_like_amount(str(val)):
                    numeric_found = True
                    break
            if numeric_found:
                break
        
        # Check if we have date-like values
        date_found = False
        for col in df.columns:
            sample_values = df[col].dropna().head(5)
            for val in sample_values:
                if self._looks_like_date(str(val)):
                    date_found = True
                    break
            if date_found:
                break
        
        return numeric_found or date_found
    
    def _looks_like_amount(self, value: str) -> bool:
        """Check if a value looks like a monetary amount"""
        if not value or len(value.strip()) == 0:
            return False
        
        # Remove common currency symbols and formatting
        clean_val = re.sub(r'[$£€¥₹,\s]', '', value.strip())
        
        # Check if it matches number pattern
        return bool(re.match(r'^\d*\.?\d+$', clean_val))
    
    def _looks_like_date(self, value: str) -> bool:
        """Check if a value looks like a date"""
        if not value or len(value.strip()) == 0:
            return False
        
        # Check for date patterns
        date_patterns = [
            r'^\d{1,2}/\d{1,2}/\d{2,4}$',
            r'^\d{1,2}-\d{1,2}-\d{2,4}$',
            r'^\d{2,4}-\d{1,2}-\d{1,2}$'
        ]
        
        return any(re.match(pattern, value.strip()) for pattern in date_patterns)
    
    def _process_ys_data(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """Process and clean Y&S statement data"""
        
        # Standard Y&S column mapping
        if len(raw_df.columns) == 7:
            column_names = [
                'Invoice Number', 'Invoice Date', 'Customer PO', 
                'Original Inv Amount', 'Payment Date', 'Amount Paid', 
                'Invoice Balance'
            ]
        elif len(raw_df.columns) == 6:
            # Missing payment date column
            column_names = [
                'Invoice Number', 'Invoice Date', 'Customer PO',
                'Original Inv Amount', 'Amount Paid', 'Invoice Balance'
            ]
        else:
            # Generic naming
            column_names = [f'Column_{i+1}' for i in range(len(raw_df.columns))]
        
        # Assign column names
        df = raw_df.copy()
        df.columns = column_names[:len(df.columns)]
        
        # Remove header rows and invalid data
        df = self._clean_header_rows(df)
        
        # Clean individual columns
        df = self._clean_ys_columns(df)
        
        # Add metadata
        df['Statement Date'] = self.metadata.get('statement_date', '')
        df['Account Number'] = self.metadata.get('account_number', '')
        df['Supplier'] = 'Y & S Plumbing Supply'
        
        return df
    
    def _clean_header_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove header rows and invalid entries"""
        
        # Remove rows that look like headers
        header_keywords = [
            'invoice', 'number', 'date', 'customer', 'original', 
            'payment', 'amount', 'balance', 'p/o', 'po'
        ]
        
        mask = df['Invoice Number'].astype(str).str.lower().isin(header_keywords)
        df = df[~mask].copy()
        
        # Remove completely empty rows
        df = df.dropna(how='all')
        
        # Remove rows where invoice number is clearly invalid
        invalid_invoice_pattern = r'^[^\w\d]*$|^(date|amount|payment|balance)$'
        mask = df['Invoice Number'].astype(str).str.match(invalid_invoice_pattern, case=False, na=False)
        df = df[~mask].copy()
        
        return df
    
    def _clean_ys_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean individual columns with Y&S specific logic"""
        
        # Clean Invoice Number
        if 'Invoice Number' in df.columns:
            df['Invoice Number'] = df['Invoice Number'].apply(self._clean_invoice_number)
        
        # Clean Date columns  
        date_columns = ['Invoice Date', 'Payment Date']
        for col in date_columns:
            if col in df.columns:
                df[col] = df[col].apply(self._clean_ys_date)
        
        # Clean Amount columns
        amount_columns = ['Original Inv Amount', 'Amount Paid', 'Invoice Balance']
        for col in amount_columns:
            if col in df.columns:
                df[col] = df[col].apply(self._clean_ys_amount)
        
        # Clean Customer PO
        if 'Customer PO' in df.columns:
            df['Customer PO'] = df['Customer PO'].apply(self._clean_po)
        
        # Remove rows where invoice number is None after cleaning
        if 'Invoice Number' in df.columns:
            df = df[df['Invoice Number'].notna()].copy()
        
        return df
    
    def _clean_invoice_number(self, value) -> Optional[str]:
        """Clean invoice number with Y&S specific rules"""
        if pd.isna(value) or not str(value).strip():
            return None
        
        inv_str = str(value).strip()
        
        # Skip obvious non-invoice values
        if inv_str.lower() in ['invoice', 'number', 'date', 'customer', 'p/o']:
            return None
        
        # Remove leading/trailing special characters
        cleaned = re.sub(r'^[^\w\d]+', '', inv_str)
        cleaned = re.sub(r'[^\w\d-]+$', '', cleaned)
        
        # Must have reasonable length
        if len(cleaned) < 2:
            return None
        
        return cleaned
    
    def _clean_ys_date(self, value) -> Optional[datetime]:
        """Clean date values with Y&S specific formatting"""
        if pd.isna(value) or not str(value).strip():
            return None
        
        date_str = str(value).strip()
        
        # Skip header values
        if date_str.lower() in ['date', 'payment', 'invoice']:
            return None
        
        try:
            # Y&S specific date formats (MM/DD/YY format)
            date_formats = [
                '%m/%d/%y',   # 04/21/25
                '%m/%d/%Y',   # 04/21/2025
                '%d/%m/%y',   # 21/04/25
                '%d/%m/%Y',   # 21/04/2025
                '%Y-%m-%d',   # 2025-04-21
                '%m-%d-%Y',   # 04-21-2025
                '%m-%d-%y'    # 04-21-25
            ]
            
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    
                    # Handle 2-digit years properly
                    if parsed_date.year < 1950:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 100)
                    
                    # Validate reasonable date range
                    if 2020 <= parsed_date.year <= 2030:
                        return parsed_date.date()
                        
                except ValueError:
                    continue
            
            logger.debug(f"Could not parse Y&S date: '{date_str}'")
            return None
            
        except Exception as e:
            logger.debug(f"Error parsing Y&S date '{date_str}': {str(e)}")
            return None
    
    def _clean_ys_amount(self, value) -> Optional[Decimal]:
        """Clean amount values with Y&S specific formatting"""
        if pd.isna(value) or not str(value).strip():
            return None
        
        amount_str = str(value).strip()
        
        # Skip header values
        if amount_str.lower() in ['amount', 'payment', 'original', 'balance']:
            return None
        
        try:
            # Remove currency symbols and formatting
            clean_str = re.sub(r'[$£€¥₹]', '', amount_str)
            clean_str = re.sub(r'[,\s]', '', clean_str)
            
            # Handle negative amounts in parentheses
            if '(' in clean_str and ')' in clean_str:
                clean_str = '-' + re.sub(r'[()]', '', clean_str)
            
            # Replace various minus signs
            clean_str = clean_str.replace('−', '-').replace('–', '-')
            
            # Validate format
            if not re.match(r'^-?\d*\.?\d+$', clean_str):
                logger.debug(f"Invalid Y&S amount format: '{amount_str}' -> '{clean_str}'")
                return None
            
            decimal_value = Decimal(clean_str)
            
            # Validate reasonable range
            if abs(decimal_value) > 1000000:
                logger.warning(f"Suspicious Y&S amount: {decimal_value}")
            
            return decimal_value
            
        except (InvalidOperation, ValueError) as e:
            logger.debug(f"Could not parse Y&S amount '{amount_str}': {str(e)}")
            return None
    
    def _clean_po(self, value) -> Optional[str]:
        """Clean Customer PO values"""
        if pd.isna(value) or not str(value).strip():
            return None
        
        po_str = str(value).strip()
        
        # Skip header values
        if po_str.lower() in ['customer', 'p/o', 'po', '#']:
            return None
        
        return po_str if po_str else None
    
    def extract_full_statement(self) -> Dict[str, Any]:
        """Extract complete statement data"""
        
        # Extract metadata first
        metadata = self.extract_statement_metadata()
        
        # Extract invoice data
        invoice_data = self.extract_invoice_data()
        
        return {
            'metadata': metadata,
            'invoice_data': invoice_data,
            'total_invoices': len(invoice_data) if not invoice_data.empty else 0,
            'total_amount': float(invoice_data['Original Inv Amount'].sum()) if not invoice_data.empty and 'Original Inv Amount' in invoice_data.columns else 0.0
        }


def extract_ys_statement(pdf_path: str) -> Dict[str, Any]:
    """
    Main function to extract Y&S statement data
    
    Args:
        pdf_path: Path to the Y&S statement PDF
        
    Returns:
        Dictionary containing metadata and invoice data
    """
    try:
        extractor = YSStatementExtractor(pdf_path)
        result = extractor.extract_full_statement()
        
        logger.info(f"Y&S extraction complete: {result['total_invoices']} invoices, total: ${result['total_amount']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Y&S statement extraction failed: {str(e)}")
        return {
            'metadata': {},
            'invoice_data': pd.DataFrame(),
            'total_invoices': 0,
            'total_amount': 0.0,
            'error': str(e)
        } 