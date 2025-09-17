import pandas as pd
import tabula
import re
import fitz
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any
import logging

from mpi_backend.utils.statement_processing.statement_utils import (
    extract_text_from_pdf,
    identify_supplier,
    extract_statement_metadata,
    extract_summary_data
)

logger = logging.getLogger(__name__)

class StatementExtractor:
    """
    Unified Statement Extractor for all suppliers (Y&S, WWPS, and others)
    Uses robust table extraction and cleaning logic.
    """
    def __init__(self, pdf_path: str, supplier_name: Optional[str] = None):
        self.pdf_path = pdf_path
        self.supplier_name = supplier_name
        self.extracted_data = pd.DataFrame()
        self.metadata = {}

    def extract_statement_metadata(self) -> Dict[str, str]:
        try:
            full_text, _ = extract_text_from_pdf(self.pdf_path)
            metadata = extract_statement_metadata(full_text)
            if self.supplier_name:
                metadata["supplier_name"] = self.supplier_name
            self.metadata = metadata
            return metadata
        except Exception as e:
            logger.error(f"Error extracting metadata: {str(e)}")
            return {"statement_date": "", "account_number": "", "supplier_name": self.supplier_name or ""}

    def extract_invoice_data(self) -> pd.DataFrame:
        """
        Extract invoice data using multiple strategies optimized for all formats
        """
        # Extraction strategies (Y&S/WWPS and generic)
        strategies = [
            {
                "name": "Y&S/WWPS Optimized",
                "params": {
                    "pages": "all",
                    "area": [230, 20, 680, 580],
                    "columns": [83, 151, 264, 345, 416, 495, 582],
                    "stream": True,
                    "pandas_options": {"header": None}
                }
            },
            {
                "name": "Generic Lattice",
                "params": {
                    "pages": "all",
                    "lattice": True,
                    "pandas_options": {"header": None}
                }
            },
            {
                "name": "Generic Stream",
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
                    if self._validate_data(df):
                        logger.info(f"Extracted {len(df)} rows using {strategy['name']}")
                        all_data.append(df)
                        break
            except Exception as e:
                logger.debug(f"Strategy {strategy['name']} failed: {str(e)}")
                continue
        if all_data:
            raw_data = all_data[0]
            cleaned_data = self._process_data(raw_data)
            self.extracted_data = cleaned_data
            return cleaned_data
        else:
            logger.error("No extraction strategy succeeded for statement")
            return pd.DataFrame()

    def _validate_data(self, df: pd.DataFrame) -> bool:
        if df.empty or len(df) < 2:
            return False
        if len(df.columns) < 5 or len(df.columns) > 8:
            return False
        # Look for numeric or date-like values
        for col in df.columns:
            sample = df[col].dropna().head(5)
            for val in sample:
                if self._looks_like_amount(str(val)) or self._looks_like_date(str(val)):
                    return True
        return False

    def _looks_like_amount(self, value: str) -> bool:
        clean_val = re.sub(r'[$£€¥₹,\s]', '', value.strip())
        return bool(re.match(r'^-?\d*\.?\d+$', clean_val))

    def _looks_like_date(self, value: str) -> bool:
        date_patterns = [
            r'^\d{1,2}/\d{1,2}/\d{2,4}$',
            r'^\d{1,2}-\d{1,2}-\d{2,4}$',
            r'^\d{2,4}-\d{1,2}-\d{1,2}$'
        ]
        return any(re.match(pattern, value.strip()) for pattern in date_patterns)

    def _process_data(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        # Standard column mapping (7, 6, or fallback)
        if len(raw_df.columns) == 7:
            column_names = [
                'Invoice Number', 'Invoice Date', 'Customer PO',
                'Original Inv Amount', 'Payment Date', 'Amount Paid',
                'Invoice Balance'
            ]
        elif len(raw_df.columns) == 6:
            column_names = [
                'Invoice Number', 'Invoice Date', 'Customer PO',
                'Original Inv Amount', 'Amount Paid', 'Invoice Balance'
            ]
        else:
            column_names = [f'Column_{i+1}' for i in range(len(raw_df.columns))]
        df = raw_df.copy()
        df.columns = column_names[:len(df.columns)]
        df = self._clean_header_rows(df)
        df = self._clean_columns(df)
        df['Statement Date'] = self.metadata.get('statement_date', '')
        df['Account Number'] = self.metadata.get('account_number', '')
        df['Supplier'] = self.metadata.get('supplier_name', self.supplier_name or '')
        return df

    def _clean_header_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        header_keywords = [
            'invoice', 'number', 'date', 'customer', 'original',
            'payment', 'amount', 'balance', 'p/o', 'po'
        ]
        mask = df['Invoice Number'].astype(str).str.lower().isin(header_keywords)
        df = df[~mask].copy()
        df = df.dropna(how='all')
        invalid_invoice_pattern = r'^[^\w\d]*$|^(date|amount|payment|balance)$'
        mask = df['Invoice Number'].astype(str).str.match(invalid_invoice_pattern, case=False, na=False)
        df = df[~mask].copy()
        return df

    def _clean_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'Invoice Number' in df.columns:
            df['Invoice Number'] = df['Invoice Number'].apply(self._clean_invoice_number)
        date_columns = ['Invoice Date', 'Payment Date']
        for col in date_columns:
            if col in df.columns:
                df[col] = df[col].apply(self._clean_date)
        amount_columns = ['Original Inv Amount', 'Amount Paid', 'Invoice Balance']
        for col in amount_columns:
            if col in df.columns:
                df[col] = df[col].apply(self._clean_amount)
        if 'Customer PO' in df.columns:
            df['Customer PO'] = df['Customer PO'].apply(self._clean_po)
        if 'Invoice Number' in df.columns:
            df = df[df['Invoice Number'].notna()].copy()
        return df

    def _clean_invoice_number(self, value) -> Optional[str]:
        if pd.isna(value) or not str(value).strip():
            return None
        inv_str = str(value).strip()
        if inv_str.lower() in ['invoice', 'number', 'date', 'customer', 'p/o']:
            return None
        cleaned = re.sub(r'^[^\w\d]+', '', inv_str)
        cleaned = re.sub(r'[^\w\d-]+$', '', cleaned)
        if len(cleaned) < 2:
            return None
        return cleaned

    def _clean_date(self, value) -> Optional[datetime]:
        if pd.isna(value) or not str(value).strip():
            return None
        date_str = str(value).strip()
        if date_str.lower() in ['date', 'payment', 'invoice']:
            return None
        try:
            date_formats = [
                '%m/%d/%y', '%m/%d/%Y', '%d/%m/%y', '%d/%m/%Y',
                '%Y-%m-%d', '%m-%d-%Y', '%m-%d-%y'
            ]
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    if parsed_date.year < 1950:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 100)
                    if 1990 <= parsed_date.year <= 2030:
                        return parsed_date.date()
                except ValueError:
                    continue
            return None
        except Exception:
            return None

    def _clean_amount(self, value) -> Optional[Decimal]:
        if pd.isna(value) or not str(value).strip():
            return None
        amount_str = str(value).strip()
        if amount_str.lower() in ['amount', 'payment', 'original', 'balance']:
            return None
        try:
            clean_str = re.sub(r'[$£€¥₹]', '', amount_str)
            clean_str = re.sub(r'[,\s]', '', clean_str)
            if '(' in clean_str and ')' in clean_str:
                clean_str = '-' + re.sub(r'[()]', '', clean_str)
            clean_str = clean_str.replace('−', '-').replace('–', '-')
            if not re.match(r'^-?\d*\.?\d+$', clean_str):
                return None
            decimal_value = Decimal(clean_str)
            if abs(decimal_value) > 1000000:
                logger.warning(f"Suspicious amount: {decimal_value}")
            return decimal_value
        except (InvalidOperation, ValueError):
            return None

    def _clean_po(self, value) -> Optional[str]:
        if pd.isna(value) or not str(value).strip():
            return None
        po_str = str(value).strip()
        if po_str.lower() in ['customer', 'p/o', 'po', '#']:
            return None
        return po_str if po_str else None

    def extract_full_statement(self) -> Dict[str, Any]:
        metadata = self.extract_statement_metadata()
        invoice_data = self.extract_invoice_data()
        return {
            'metadata': metadata,
            'invoice_data': invoice_data,
            'total_invoices': len(invoice_data) if not invoice_data.empty else 0,
            'total_amount': float(invoice_data['Original Inv Amount'].sum()) if not invoice_data.empty and 'Original Inv Amount' in invoice_data.columns else 0.0
        }

def process_statement(filename, output_path, supplier_name=None):
    extractor = StatementExtractor(filename, supplier_name=supplier_name)
    result = extractor.extract_full_statement()
    if not result['invoice_data'].empty:
        result['invoice_data'].to_excel(output_path, index=False)
        return True
    return False 