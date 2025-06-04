import os
import pandas as pd
import tabula
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

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
        """Extract invoice data from all pages of the PDF"""
        try:
            # Define the extraction area and columns
            extraction_area = [233.70, 28.05, 668.95, 582.01]  # coordinates
            column_positions = [
                83.35, 150.81, 264.05, 345.20, 415.89, 495.11, 582.01
            ]
            
            # Read all pages and combine data
            all_data = []
            
            for page_num in range(1, self.metadata.get('page_count', 1) + 1):
                try:
                    # Extract data from this page
                    page_data = tabula.read_pdf(
                        self.pdf_path,
                        pages=page_num,
                        area=extraction_area,
                        columns=column_positions,
                        pandas_options={'header': None}
                    )[0]
                    
                    if not page_data.empty:
                        # Add source page column
                        page_data['source_page'] = page_num
                        all_data.append(page_data)
                        logger.info(
                            f"Extracted {len(page_data)} rows from page "
                            f"{page_num}"
                        )
                        
                except Exception as e:
                    logger.warning(
                        f"Could not extract from page {page_num}: {str(e)}"
                    )
                    continue
            
            if all_data:
                # Combine all pages
                self.combined_data = pd.concat(all_data, ignore_index=True)
                
                # Set column names
                self.combined_data.columns = [
                    'Invoice Number', 'Invoice Date', 'Customer PO', 
                    'Original Inv Amount', 'Payment Date', 'Amount Paid', 
                    'Invoice Balance', 'source_page'
                ]
                
                # Clean and process the data
                self._clean_extracted_data()
                
                logger.info(
                    f"Successfully extracted {len(self.combined_data)} "
                    f"total rows"
                )
                return True
            else:
                logger.error("No data extracted from any page")
                return False
                
        except Exception as e:
            logger.error(f"Error extracting invoice data: {str(e)}")
            return False
    
    def _clean_extracted_data(self):
        """Clean and process the extracted data"""
        if self.combined_data.empty:
            return
        
        try:
            # Remove rows where Invoice Number is empty or contains header text
            self.combined_data = self.combined_data[
                self.combined_data['Invoice Number'].notna() & 
                ~self.combined_data['Invoice Number'].astype(str).str.contains(
                    'Invoice|Number|DATE|AMOUNT|PAYMENT', case=False, na=False
                )
            ].copy()
            
            # Clean and convert date columns
            date_columns = ['Invoice Date', 'Payment Date']
            for col in date_columns:
                if col in self.combined_data.columns:
                    self.combined_data[col] = self._clean_dates(
                        self.combined_data[col]
                    )
            
            # Clean and convert amount columns
            amount_columns = [
                'Original Inv Amount', 'Amount Paid', 'Invoice Balance'
            ]
            for col in amount_columns:
                if col in self.combined_data.columns:
                    self.combined_data[col] = self._clean_amounts(
                        self.combined_data[col]
                    )
            
            # Add metadata columns
            self.combined_data['Statement Date'] = self.metadata.get(
                'statement_date', ''
            )
            self.combined_data['Account Number'] = self.metadata.get(
                'account_number', ''
            )
            self.combined_data['Supplier'] = self.metadata.get(
                'supplier_name', ''
            )
            
            # Calculate missing balances
            self._calculate_missing_balances()
            
            logger.info(
                f"Cleaned data: {len(self.combined_data)} rows remaining"
            )
            
        except Exception as e:
            logger.error(f"Error cleaning data: {str(e)}")
    
    def _clean_dates(self, date_series):
        """Clean and standardize date formats"""
        def parse_date(date_str):
            if pd.isna(date_str) or str(date_str).strip() == '':
                return None
            
            try:
                # Try different date formats
                for fmt in ('%m/%d/%y', '%m/%d/%Y', '%d/%m/%y', '%d/%m/%Y'):
                    try:
                        return pd.to_datetime(
                            str(date_str).strip(), format=fmt
                        ).date()
                    except ValueError:
                        continue
                
                # Try pandas auto-parsing as last resort
                return pd.to_datetime(str(date_str)).date()
                
            except Exception:
                return None
        
        return date_series.apply(parse_date)
    
    def _clean_amounts(self, amount_series):
        """Clean and convert amount strings to decimal values"""
        def parse_amount(amount_str):
            if pd.isna(amount_str) or str(amount_str).strip() == '':
                return None
            
            try:
                # Remove currency symbols, commas, and spaces
                clean_str = str(amount_str).replace(
                    '$', ''
                ).replace(',', '').strip()
                
                # Handle parentheses for negative amounts
                if '(' in clean_str and ')' in clean_str:
                    clean_str = '-' + clean_str.replace(
                        '(', ''
                    ).replace(')', '')
                
                return Decimal(clean_str)
            except (InvalidOperation, ValueError):
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