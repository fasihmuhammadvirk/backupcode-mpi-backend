import os
import pandas as pd
import tabula
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
import re

from mpi_backend.utils.statement_extractor.statement_utils import (
    extract_text_from_pdf,
    extract_statement_metadata,
    extract_summary_data,
    identify_supplier
)
from mpi_backend.database import SessionLocal
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement, PlumbingInvoice
)

logger = logging.getLogger(__name__)

# Original area definitions for Y&S Plumbing statements
YS_AREA1 = [233.70, 28.05, 668.95, 582.01]  # Working area coordinates
YS_AREA2 = [233.70, 28.05, 668.95, 20.29]   # Alternative coordinates
YS_AREA3 = [230, 25, 670, 25]               # Slightly expanded area

# Define column positions for Y&S Plumbing statements
YS_COLUMNS = [83.35, 150.81, 264.05, 345.20, 415.89, 495.11, 582.01]


class StatementExtractor:
    """Enhanced Statement Extractor that can save to database and/or Excel"""
    
    def __init__(self, pdf_path, save_to_db=True, save_to_excel=False, 
                 db_session=None):
        """
        Initialize the statement extractor
        
        Args:
            pdf_path: Path to the PDF file
            save_to_db: Whether to save extracted data to database
            save_to_excel: Whether to save extracted data to Excel
            db_session: Optional existing database session
        """
        self.pdf_path = pdf_path
        self.pdf_filename = os.path.basename(pdf_path)
        self.save_to_db = save_to_db
        self.save_to_excel = save_to_excel
        self.db_session = db_session
        self._should_close_session = False
        
        # Initialize data containers
        self.combined_data = pd.DataFrame()
        self.metadata = {}
        self.summary_data = {}
        
        # Database objects (will be set if save_to_db is True)
        self.statement_obj = None
        self.supplier_obj = None
        
        # Set up database session
        if self.save_to_db and not self.db_session:
            self.db_session = SessionLocal()
            self._should_close_session = True
        
        # Extract basic metadata first
        self._extract_metadata()
        
        logger.info(f"Initialized extractor for: {self.pdf_filename}")
        logger.info(
            f"Save to DB: {save_to_db}, Save to Excel: {save_to_excel}"
        )
    
    def __del__(self):
        """Clean up database session if we created it"""
        if self._should_close_session and self.db_session:
            try:
                self.db_session.close()
            except Exception:
                pass
    
    def _extract_metadata(self):
        """Extract metadata from the PDF"""
        try:
            # Extract text from PDF
            full_text, page_count = extract_text_from_pdf(self.pdf_path)
            
            # Extract metadata
            self.metadata = extract_statement_metadata(full_text)
            self.metadata['page_count'] = page_count
            
            # Extract summary data
            self.summary_data = extract_summary_data(full_text)
            
            logger.info(f"Extracted metadata: {self.metadata}")
            
        except Exception as e:
            logger.error(f"Error extracting metadata: {str(e)}")
            self.metadata = {
                'supplier_name': '', 
                'statement_date': '', 
                'account_number': ''
            }
    
    def extract_invoice_data(self):
        """Extract invoice data from all pages of the PDF with improved detection"""
        try:
            # Try multiple extraction strategies for better accuracy
            strategies = [
                # Strategy 1: Auto-detect tables without fixed coordinates
                {"method": "auto", "area": None, "columns": None},
                
                # Strategy 2: Use lattice method for well-structured tables
                {"method": "lattice", "area": None, "columns": None},
                
                # Strategy 3: Updated coordinates based on Y&S format
                {"method": "stream", "area": [200, 25, 700, 580], "columns": None},
                
                # Strategy 4: Original method as fallback
                {"method": "stream", "area": [233.70, 28.05, 668.95, 582.01], 
                 "columns": [83.35, 150.81, 264.05, 345.20, 415.89, 495.11, 582.01]}
            ]
            
            all_data = []
            page_count = self.metadata.get('page_count', 1)
            
            for page_num in range(1, page_count + 1):
                page_extracted = False
                
                for strategy_idx, strategy in enumerate(strategies):
                    try:
                        logger.info(f"Trying strategy {strategy_idx + 1} for page {page_num}")
                        
                        # Configure extraction parameters
                        extraction_params = {
                            'pages': page_num,
                            'pandas_options': {'header': None}
                        }
                        
                        # Add strategy-specific parameters
                        if strategy["area"]:
                            extraction_params['area'] = strategy["area"]
                        if strategy["columns"]:
                            extraction_params['columns'] = strategy["columns"]
                            
                        # Use lattice for well-structured tables
                        if strategy["method"] == "lattice":
                            extraction_params['lattice'] = True
                        elif strategy["method"] == "stream":
                            extraction_params['stream'] = True
                        # auto method uses default tabula settings
                        
                        # Extract data
                        page_tables = tabula.read_pdf(self.pdf_path, **extraction_params)
                        
                        if page_tables and len(page_tables) > 0:
                            page_data = page_tables[0]
                            
                            # Validate extracted data quality
                            if self._validate_extracted_data(page_data):
                                page_data['source_page'] = page_num
                                page_data['extraction_method'] = strategy["method"]
                                all_data.append(page_data)
                                logger.info(
                                    f"Successfully extracted {len(page_data)} rows "
                                    f"from page {page_num} using strategy {strategy_idx + 1}"
                                )
                                page_extracted = True
                                break  # Move to next page
                        
                    except Exception as e:
                        logger.debug(
                            f"Strategy {strategy_idx + 1} failed for page {page_num}: {str(e)}"
                        )
                        continue
                
                if not page_extracted:
                    logger.warning(f"Could not extract data from page {page_num}")
            
            if all_data:
                # Combine all pages
                self.combined_data = pd.concat(all_data, ignore_index=True)
                
                # Detect and set proper column names
                self._detect_and_set_column_names()
                
                # Clean and process the data
                self._clean_extracted_data()
                
                logger.info(
                    f"Successfully extracted {len(self.combined_data)} total rows"
                )
                return True
            else:
                logger.error("No data extracted from any page using any strategy")
                return False
                
        except Exception as e:
            logger.error(f"Error extracting invoice data: {str(e)}")
            return False
    
    def _validate_extracted_data(self, data):
        """Validate if extracted data looks like invoice data"""
        if data.empty or len(data) < 2:
            return False
        
        # Check if we have reasonable number of columns (should be 6-8 for invoice data)
        if len(data.columns) < 5 or len(data.columns) > 10:
            return False
        
        # Check if first few rows contain reasonable data
        # Look for patterns that suggest this is invoice data
        sample_text = ' '.join(str(data.iloc[0:min(3, len(data))].values.flatten()))
        
        # Should contain some numeric patterns and not just headers
        has_numbers = bool(re.search(r'\d+', sample_text))
        has_invoice_indicators = any(word.lower() in sample_text.lower() 
                                   for word in ['invoice', 'amount', 'balance', 'date', 'payment'])
        
        # Should not be mostly headers or empty
        non_empty_ratio = sum(1 for cell in data.iloc[0].values if pd.notna(cell) and str(cell).strip()) / len(data.columns)
        
        return has_numbers and non_empty_ratio > 0.3
    
    def _detect_and_set_column_names(self):
        """Detect and set appropriate column names based on content"""
        if self.combined_data.empty:
            return
        
        # Standard column names for Y&S statements
        standard_columns = [
            'Invoice Number', 'Invoice Date', 'Customer PO', 
            'Original Inv Amount', 'Payment Date', 'Amount Paid', 
            'Invoice Balance'
        ]
        
        # Get the actual number of data columns (excluding metadata columns)
        data_columns = [col for col in self.combined_data.columns 
                       if col not in ['source_page', 'extraction_method']]
        
        num_data_cols = len(data_columns)
        
        # Map columns based on typical Y&S statement structure
        if num_data_cols >= 7:
            # Full 7-column structure
            column_mapping = {
                data_columns[0]: 'Invoice Number',
                data_columns[1]: 'Invoice Date', 
                data_columns[2]: 'Customer PO',
                data_columns[3]: 'Original Inv Amount',
                data_columns[4]: 'Payment Date',
                data_columns[5]: 'Amount Paid',
                data_columns[6]: 'Invoice Balance'
            }
        elif num_data_cols == 6:
            # Missing one column - likely Payment Date
            column_mapping = {
                data_columns[0]: 'Invoice Number',
                data_columns[1]: 'Invoice Date',
                data_columns[2]: 'Customer PO', 
                data_columns[3]: 'Original Inv Amount',
                data_columns[4]: 'Amount Paid',
                data_columns[5]: 'Invoice Balance'
            }
        elif num_data_cols == 5:
            # Missing two columns - likely PO and Payment Date
            column_mapping = {
                data_columns[0]: 'Invoice Number',
                data_columns[1]: 'Invoice Date',
                data_columns[2]: 'Original Inv Amount',
                data_columns[3]: 'Amount Paid', 
                data_columns[4]: 'Invoice Balance'
            }
        else:
            # Less than 5 columns - use generic names
            column_mapping = {
                data_columns[i]: f'Column_{i+1}' for i in range(num_data_cols)
            }
        
        # Apply the mapping
        self.combined_data = self.combined_data.rename(columns=column_mapping)
        
        logger.info(f"Set column names: {list(column_mapping.values())}")
    
    def _clean_extracted_data(self):
        """Clean and process the extracted data with improved filtering"""
        if self.combined_data.empty:
            return
        
        try:
            logger.info(f"Starting data cleaning with {len(self.combined_data)} rows")
            
            # First, remove completely empty rows
            self.combined_data = self.combined_data.dropna(how='all')
            
            # Clean up invoice number column specifically
            if 'Invoice Number' in self.combined_data.columns:
                # Remove rows where Invoice Number is clearly invalid
                invalid_patterns = [
                    r'^(Invoice|Number|umber|nvoice|DATE|AMOUNT|PAYMENT|Customer|P/O|Original|Balance)$',
                    r'^[^\w\d-]+$',  # Only special characters
                    r'^\s*$',        # Only whitespace
                ]
                
                # Combine all invalid patterns
                combined_pattern = '|'.join(invalid_patterns)
                
                # Filter out invalid invoice numbers
                valid_mask = (
                    self.combined_data['Invoice Number'].notna() & 
                    ~self.combined_data['Invoice Number'].astype(str).str.match(
                        combined_pattern, case=False, na=False
                    ) &
                    (self.combined_data['Invoice Number'].astype(str).str.len() > 0)
                )
                
                self.combined_data = self.combined_data[valid_mask].copy()
                
                # Clean up partial invoice numbers (like "umber" -> should be filtered out)
                # Keep only rows where invoice number looks reasonable
                invoice_mask = (
                    self.combined_data['Invoice Number'].astype(str).str.len() >= 3
                ) & (
                    # Should contain at least one digit or be a reasonable invoice pattern
                    self.combined_data['Invoice Number'].astype(str).str.contains(
                        r'\d|^[A-Z]+[-]?\d', case=False, na=False
                    )
                )
                
                self.combined_data = self.combined_data[invoice_mask].copy()
            
            # Clean invoice numbers further - remove common OCR errors
            if 'Invoice Number' in self.combined_data.columns:
                def clean_invoice_number(inv_num):
                    if pd.isna(inv_num):
                        return None
                    
                    inv_str = str(inv_num).strip()
                    
                    # Skip obviously invalid values
                    if len(inv_str) < 2 or inv_str.lower() in [
                        'invoice', 'number', 'umber', 'nvoice', 'customer', 'p/o'
                    ]:
                        return None
                    
                    # Clean up common OCR errors and formatting
                    cleaned = re.sub(r'^[^\w\d]*', '', inv_str)  # Remove leading special chars
                    cleaned = re.sub(r'[^\w\d-]*$', '', cleaned)  # Remove trailing special chars
                    
                    return cleaned if len(cleaned) >= 2 else None
                
                self.combined_data['Invoice Number'] = self.combined_data['Invoice Number'].apply(
                    clean_invoice_number
                )
                
                # Remove rows where cleaning resulted in None
                self.combined_data = self.combined_data[
                    self.combined_data['Invoice Number'].notna()
                ].copy()
            
            # Clean and convert date columns with better error handling
            date_columns = ['Invoice Date', 'Payment Date']
            for col in date_columns:
                if col in self.combined_data.columns:
                    self.combined_data[col] = self._clean_dates_improved(
                        self.combined_data[col]
                    )
            
            # Clean and convert amount columns with better error handling
            amount_columns = [
                'Original Inv Amount', 'Amount Paid', 'Invoice Balance'
            ]
            for col in amount_columns:
                if col in self.combined_data.columns:
                    self.combined_data[col] = self._clean_amounts_improved(
                        self.combined_data[col]
                    )
            
            # Clean Customer PO column
            if 'Customer PO' in self.combined_data.columns:
                def clean_po(po_val):
                    if pd.isna(po_val):
                        return None
                    
                    po_str = str(po_val).strip()
                    
                    # Skip header-like values
                    if po_str.lower() in ['customer', 'p/o', 'po', '#']:
                        return None
                    
                    return po_str if po_str else None
                
                self.combined_data['Customer PO'] = self.combined_data['Customer PO'].apply(clean_po)
            
            # Add metadata columns
            self.combined_data['Statement Date'] = self.metadata.get('statement_date', '')
            self.combined_data['Account Number'] = self.metadata.get('account_number', '')
            self.combined_data['Supplier'] = self.metadata.get('supplier_name', '')
            
            # Calculate missing balances
            self._calculate_missing_balances()
            
            # Final validation - remove rows that still don't look like valid invoices
            if len(self.combined_data) > 0:
                # Keep rows that have either an invoice number OR a reasonable amount
                valid_invoice_mask = (
                    (self.combined_data.get('Invoice Number', pd.Series(dtype=object)).notna()) |
                    (self.combined_data.get('Original Inv Amount', pd.Series(dtype=object)).notna() & 
                     (self.combined_data.get('Original Inv Amount', pd.Series(dtype=object)) != 0))
                )
                
                self.combined_data = self.combined_data[valid_invoice_mask].copy()
            
            logger.info(f"Data cleaning complete: {len(self.combined_data)} rows remaining")
            
            # Log sample of cleaned data for debugging
            if len(self.combined_data) > 0:
                logger.info("Sample of cleaned data:")
                for i in range(min(3, len(self.combined_data))):
                    row = self.combined_data.iloc[i]
                    logger.info(f"  Row {i}: Invoice={row.get('Invoice Number')}, "
                              f"Date={row.get('Invoice Date')}, "
                              f"Amount={row.get('Original Inv Amount')}")
            
        except Exception as e:
            logger.error(f"Error cleaning data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _clean_dates_improved(self, date_series):
        """Clean and standardize date formats with improved error handling"""
        def parse_date(date_str):
            if pd.isna(date_str) or str(date_str).strip() == '':
                return None
            
            date_str = str(date_str).strip()
            
            # Skip obvious non-dates
            if date_str.lower() in ['date', 'payment', 'invoice', 'original', 'amount']:
                return None
            
            try:
                # Try different date formats common in statements
                date_formats = [
                    '%m/%d/%y', '%m/%d/%Y', '%d/%m/%y', '%d/%m/%Y',
                    '%Y-%m-%d', '%m-%d-%Y', '%d-%m-%Y',
                    '%m/%d/%y', '%m.%d.%y', '%m.%d.%Y'
                ]
                
                for fmt in date_formats:
                    try:
                        parsed_date = pd.to_datetime(date_str, format=fmt).date()
                        # Validate reasonable date range (1990-2030)
                        if 1990 <= parsed_date.year <= 2030:
                            return parsed_date
                    except ValueError:
                        continue
                
                # Try pandas auto-parsing as last resort
                parsed_date = pd.to_datetime(date_str, errors='coerce')
                if parsed_date and not pd.isna(parsed_date):
                    date_obj = parsed_date.date()
                    if 1990 <= date_obj.year <= 2030:
                        return date_obj
                
                return None
                
            except Exception:
                return None
        
        return date_series.apply(parse_date)
    
    def _clean_amounts_improved(self, amount_series):
        """Clean and convert amount strings to decimal values with improved error handling"""
        def parse_amount(amount_str):
            if pd.isna(amount_str) or str(amount_str).strip() == '':
                return None
            
            amount_str = str(amount_str).strip()
            
            # Skip obvious non-amounts
            if amount_str.lower() in ['amount', 'payment', 'invoice', 'original', 'balance', 'date']:
                return None
            
            try:
                # Handle various currency and formatting patterns
                # Remove currency symbols, spaces, and common formatting
                clean_str = re.sub(r'[$£€¥₹]', '', amount_str)  # Currency symbols
                clean_str = re.sub(r'[,\s]', '', clean_str)      # Commas and spaces
                clean_str = clean_str.strip()
                
                # Handle negative amounts in parentheses
                if '(' in clean_str and ')' in clean_str:
                    clean_str = '-' + re.sub(r'[()]', '', clean_str)
                
                # Handle negative signs
                clean_str = clean_str.replace('−', '-')  # Replace minus sign with hyphen
                
                # Validate that it looks like a number
                if not re.match(r'^-?\d*\.?\d+$', clean_str):
                    return None
                
                decimal_value = Decimal(clean_str)
                
                # Validate reasonable amount range (-1M to 1M for statements)
                if abs(decimal_value) > 1000000:
                    logger.warning(f"Suspicious amount value: {decimal_value}")
                
                return decimal_value
                
            except (InvalidOperation, ValueError, Exception) as e:
                logger.debug(f"Could not parse amount '{amount_str}': {str(e)}")
                return None
        
        return amount_series.apply(parse_amount)
    
    def _calculate_missing_balances(self):
        """Calculate invoice balances where missing"""
        for idx, row in self.combined_data.iterrows():
            if (pd.isna(row['Invoice Balance']) or 
                    row['Invoice Balance'] is None):
                original = row['Original Inv Amount'] or Decimal('0')
                paid = row['Amount Paid'] or Decimal('0')
                calculated_balance = original - paid
                self.combined_data.at[
                    idx, 'Invoice Balance'
                ] = calculated_balance
    
    def detect_supplier(self) -> Optional[str]:
        """Detect supplier from the PDF using the statement utils"""
        try:
            if (hasattr(self, 'metadata') and 
                    self.metadata.get('supplier_name')):
                return self.metadata['supplier_name']
            
            # If no metadata available, try to identify from filename or content
            full_text, _ = extract_text_from_pdf(self.pdf_path)
            supplier = identify_supplier(full_text)
            return supplier
            
        except Exception as e:
            logger.error(f"Error detecting supplier: {str(e)}")
            return None
    
    def extract_all_pages(self):
        """Alias for extract_invoice_data for backward compatibility"""
        return self.extract_invoice_data()
    
    def get_total_amount(self):
        """Calculate total amount from extracted data"""
        try:
            if self.combined_data is None or self.combined_data.empty:
                return 0.0
            
            if 'Original Inv Amount' in self.combined_data.columns:
                amounts = self.combined_data['Original Inv Amount'].dropna()
                total = sum(
                    float(amt) for amt in amounts 
                    if pd.notna(amt) and str(amt).strip()
                )
                return total
            
            return 0.0
        except Exception as e:
            logger.error(f"Error calculating total amount: {str(e)}")
            return 0.0
    
    def save_to_database(self):
        """Save extracted data to database"""
        try:
            if not self.db_session:
                logger.error("No database session available")
                return False
            
            if self.combined_data is None or self.combined_data.empty:
                logger.warning("No data to save to database")
                return False
            
            logger.info("Saving extracted statement data to database")
            
            # Get or create supplier
            supplier_name = self.detect_supplier()
            if not supplier_name:
                logger.error("Could not detect supplier")
                return False
            
            supplier = self.db_session.query(PlumbingSupplier).filter(
                PlumbingSupplier.name == supplier_name
            ).first()
            
            if not supplier:
                logger.error(f"Supplier {supplier_name} not found in database")
                return False
            
            # Create statement record
            total_amount = self.get_total_amount()
            total_invoices = (
                len(self.combined_data) 
                if not self.combined_data.empty else 0
            )
            
            # Get statement date from metadata or use first invoice date
            statement_date = self.metadata.get('statement_date')
            if not statement_date and not self.combined_data.empty:
                first_date = self.combined_data['Invoice Date'].iloc[0]
                if pd.notna(first_date):
                    statement_date = first_date
            
            if not statement_date:
                statement_date = datetime.now().date()
            
            # Get account number from metadata
            account_number = self.metadata.get('account_number', '')
            
            self.statement_obj = PlumbingStatement(
                supplier_id=supplier.id,
                statement_date=statement_date,
                account_number=account_number,
                total_amount=total_amount,
                total_invoices=total_invoices,
                pdf_filename=Path(self.pdf_filename).name
            )
            
            self.db_session.add(self.statement_obj)
            self.db_session.flush()  # Get the statement ID
            
            # Create invoice records
            invoices_created = 0
            for _, row in self.combined_data.iterrows():
                if (pd.notna(row['Invoice Number']) and 
                        str(row['Invoice Number']).strip()):
                    po_value = None
                    if pd.notna(row.get('Customer PO')):
                        po_value = str(row.get('Customer PO', '')).strip()
                    
                    invoice = PlumbingInvoice(
                        statement_id=self.statement_obj.id,
                        invoice_number=str(row['Invoice Number']).strip(),
                        invoice_date=row.get('Invoice Date'),
                        customer_po=po_value,
                        original_amount=row.get('Original Inv Amount'),
                        payment_date=row.get('Payment Date'),
                        amount_paid=row.get('Amount Paid'),
                        balance=row.get('Invoice Balance')
                    )
                    self.db_session.add(invoice)
                    invoices_created += 1
            
            # Commit all changes
            self.db_session.commit()
            
            logger.info(
                f"Successfully saved {invoices_created} invoices to database"
            )
            return True
            
        except Exception as e:
            logger.error(f"Error saving to database: {str(e)}")
            if self.db_session:
                self.db_session.rollback()
            return False
    
    def save_to_excel_file(self, output_path):
        """Save extracted data to Excel file"""
        if not self.save_to_excel and not output_path:
            return True
            
        try:
            if self.combined_data.empty:
                logger.warning("No data to save to Excel")
                return False
            
            with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
                # Save main data
                self.combined_data.to_excel(
                    writer, sheet_name='Statement Data', index=False
                )
                
                # Create summary sheet
                amount_col = 'Original Inv Amount'
                if amount_col in self.combined_data.columns:
                    total_amount = (
                        f"${sum(self.combined_data[amount_col].dropna()):,.2f}"
                    )
                else:
                    total_amount = '$0.00'
                
                summary_data = {
                    'Metric': [
                        'Supplier Name', 'Statement Date', 'Account Number',
                        'Total Invoices', 'Pages Processed', 'Total Amount',
                        'Current (0-30 days)', '30-60 days', '60-90 days', 
                        '90-120 days', '120+ days'
                    ],
                    'Value': [
                        self.metadata.get('supplier_name', ''),
                        self.metadata.get('statement_date', ''),
                        self.metadata.get('account_number', ''),
                        len(self.combined_data),
                        self.metadata.get('page_count', 1),
                        total_amount,
                        f"${self.summary_data.get('current', 0):,.2f}",
                        f"${self.summary_data.get('30_days', 0):,.2f}",
                        f"${self.summary_data.get('60_days', 0):,.2f}",
                        f"${self.summary_data.get('90_days', 0):,.2f}",
                        f"${self.summary_data.get('120_days_plus', 0):,.2f}"
                    ]
                }
                
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                
                logger.info(f"Successfully saved Excel file: {output_path}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving to Excel: {str(e)}")
            return False
    
    def process_statement(self, excel_output_path=None):
        """
        Main method to process the statement
        
        Args:
            excel_output_path: Optional path to save Excel file
            
        Returns:
            dict: Processing results with success status and details
        """
        results = {
            'success': False,
            'supplier_detected': '',
            'records_extracted': 0,
            'pages_processed': 0,
            'statement_id': None,
            'excel_saved': False,
            'database_saved': False,
            'error_message': ''
        }
        
        try:
            # Extract invoice data
            if not self.extract_invoice_data():
                results['error_message'] = 'Failed to extract invoice data'
                return results
            
            results['supplier_detected'] = self.metadata.get(
                'supplier_name', ''
            )
            results['records_extracted'] = len(self.combined_data)
            results['pages_processed'] = self.metadata.get('page_count', 1)
            
            # Save to database if enabled
            if self.save_to_db:
                if self.save_to_database():
                    results['database_saved'] = True
                    if self.statement_obj:
                        results['statement_id'] = self.statement_obj.id
                else:
                    results['error_message'] = 'Failed to save to database'
            
            # Save to Excel if enabled or path provided
            if self.save_to_excel or excel_output_path:
                if (excel_output_path and 
                        self.save_to_excel_file(excel_output_path)):
                    results['excel_saved'] = True
                elif self.save_to_excel and not excel_output_path:
                    results['error_message'] = (
                        'Excel output enabled but no path provided'
                    )
            
            results['success'] = True
            return results
            
        except Exception as e:
            logger.error(f"Error in process_statement: {str(e)}")
            results['error_message'] = str(e)
            return results


def process_statement(filename, output_path):
    """
    Process a statement PDF and save results to Excel
    
    Args:
        filename: Path to the PDF file
        output_path: Path where the output Excel file will be saved
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Create an extractor instance
    extractor = StatementExtractor(
        filename, save_to_db=False, save_to_excel=True
    )
    
    # Use the new direct approach
    results = extractor.process_statement(output_path)
    return results['success'] 