import tabula
import pandas as pd
import fitz
import re
import os
import numpy as np
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data, save_final_data_for_database
from PyPDF4 import PdfFileReader, PdfFileWriter
from PyPDF4.pdf import ContentStream
from PyPDF4.generic import TextStringObject, NameObject
from PyPDF4.utils import b_
from datetime import datetime

gotham_plumbing_columns = [32, 54, 154.5, 384, 419, 460.5, 527.8, 592, 683]
regular_area = (247, 32, 247 + 275, 32 + 651)
customer_job_area = (148, 362, 148 + 26, 362 + 140)
# tax_area = (535.88, 516.76, 535.88 + 162, 516.76 + 23.11)
tax_area = (535.88, 516.76,535.88 + 23.11, 516.76+ 162)

def process_invoice(filename, output_path):
    processed_file_path = generate_converted_filename(filename)
    remove_watermark(filename, processed_file_path)
    tables = tabula.read_pdf(processed_file_path, pages="all", stream=True)  # to extract date, tax and invoice no

    # early cleaning of read tables - finding which dataframe to keep, which to discard
    cleaned_pages = [table for table in tables if False in (table == 'NOTICE').any().unique()]  # dropping NOTICE page

    invoice_items = extract_and_clean_invoice_items(processed_file_path)
    invoice_items = merge_invoice_items(invoice_items)

    date = extract_date(tables[0])
    invoice_no = extract_invoice_no(tables[0])
    tax = extract_tax(cleaned_pages[-1],processed_file_path)
    freight = extract_freight(processed_file_path)
    customer_job = get_customer_job(processed_file_path)
    customer_no = extract_customer_no(tables[0])

    result = process_results(invoice_items, date, invoice_no, tax, customer_job,customer_no, freight)
    save_final_data_for_database(result, "Gotham Pipe Supply", output_path)
    os.remove(processed_file_path)  # deleting intermediary file [one without watermark]
    pass


def process_results(invoice_items, date, invoice_no, tax, job_name="", customer_no="", freight=0.0):
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
    results["PO #"] = ""
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Gotham Pipe Supply, LLC"
    results["Class"] = ""
    results["Memo"] = customer_no
    results["Buyer"] = ""
    return results


def extract_tax(table, filename):
    for value in table[table.columns[-1]].values:
        match = re.search("([0-9]+.[0-9]+)", str(value))
        if match and len(match.string) < 6:
            return match.string

        tax_table = tabula.read_pdf(filename, pages='all', area=tax_area, stream=True)
        if len(tax_table) >=1 and 'TAX 8.875' in tax_table[0].columns.to_list():
            return tax_table[0].columns.to_list()[-1]

    return ''  # fallback if tax amount is not found


def extract_freight(filename):
    """
    Extract freight amount from Gotham invoices.
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


def extract_date(table):
    for value in table[table.columns[-1]].values:
        match = re.search("([0-9]+/[0-9]+/[0-9]{2})", value)
        if match:
            date_obj = datetime.strptime(match.string, '%m/%d/%y')
            formatted_date = date_obj.strftime('%m/%d/%Y')
            return formatted_date
    return ''  # fallback if date is not found


def extract_invoice_no(table):
    for value in table[table.columns[-1]].values:
        match = re.search("([0-9]{7})", value)
        if match:
            return match.string
    return ''  # if invoice num in not found


def extract_customer_no(table):
    for value in table[table.columns[-1]].values:
        if value is None or value is np.nan:
            continue
        match = re.search(r"^\d{6}$", value)
        if match:
            return match.string
    return ''  # if customer num in not found


def merge_invoice_items(invoice_items):
    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items


def extract_and_clean_invoice_items(filename):
    invoice_items = tabula.read_pdf(filename, pages='all', area=regular_area, stream=True,
                                    columns=gotham_plumbing_columns)

    invoice_items = [invoice_items[index] for index in range(0, len(invoice_items)) if index % 2 == 0]

    for index, table in enumerate(invoice_items):
        table.dropna(subset=['LINE', ], how='any', inplace=True)
        table.rename(columns={'Unnamed: 1': 'Item', 'PRODUCT NO./ DESCRIPTION': 'Description',
                              'UNIT PRICE': 'Cost', 'EXTENDED AMOUNT': 'Amount', 'QTY': 'Qty'}, inplace=True)

        table['Amount'] = table['Amount'].astype(str).str.replace(',', '').str.replace('$', '')

        table['Cost'] = (table['Amount'].astype(float) / table['Qty']).apply(lambda x: round(x, 2))
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        table['Description'] = table['Description'].apply(lambda x: re.sub(r'(\d)([A-Z])', r'\1 \2', x)) # add space after number which is followed by capital letter

        invoice_items[index] = table
    return invoice_items


def get_customer_job(filename):
    job_table = tabula.read_pdf(filename, area=customer_job_area, stream=True)
    try:
        return job_table[0]['MPI PLUMBING CORP'][0]
    except:  # shipping address was not specified
        return ''


def remove_watermark(filename,output_file):
    wm_text = 'INVOICE'
    with open(filename, "rb") as f:
        source = PdfFileReader(f, "rb")
        output = PdfFileWriter()

        for page in range(source.getNumPages()):
            page = source.getPage(page)
            content_object = page["/Contents"].getObject()
            content = ContentStream(content_object, source)

            for operands, operator in content.operations:
                if operator == b_("Tj"):
                    text = operands[0]

                    if isinstance(text, str) and text.startswith(wm_text):
                        operands[0] = TextStringObject('')

            page.__setitem__(NameObject('/Contents'), content)
            output.addPage(page)

        with open(output_file, "wb") as outputStream:
            output.write(outputStream)


def generate_converted_filename(filename):
    # path to store intermediary pdf file (generated file without watermark)
    return filename.rsplit("/",1)[0] + "output.pdf"


# if __name__ == '__main__':
#     process_invoice(r"C:\Users\lenovo\Desktop\Neural Lines\invoices_pdf_to_excel\PDF's\Junk Workspace\template.pdf",
#                     r"C:\Users\lenovo\Desktop\Neural Lines\invoices_pdf_to_excel\PDF's\Junk Workspace\extracted.xlsx")
