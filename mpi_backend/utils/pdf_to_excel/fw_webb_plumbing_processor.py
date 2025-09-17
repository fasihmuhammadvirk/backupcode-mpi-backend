import tabula
import fitz
import re
import pandas as pd
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data, save_final_data_for_database


def process_invoice(filename, output_path):
    tables = tabula.read_pdf(filename, pages="all")
    raw_text = fitz.open(filename)
    raw_text=raw_text[0].get_text()

    invoice_items = extract_invoice_items(tables)
    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)
    tax = extract_tax(filename).replace('$','')

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data_for_database(result, "FW Webb Plumbing Supply", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", customer_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = str(invoice_no)  # Ensure reference number is stored as string to preserve leading zeros
    results["PO #"] = ""
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "F.W. Webb Plumbing Supply"
    results["Class"] = ""
    results["Memo"] = customer_no
    results["Buyer"] = ""
    return results


def extract_tax(filename):
    tax = ''
    doc = fitz.open(filename)
    for page in doc:
        text = page.getText()
        if 'Tax' in text:
            tax = text.split('Tax\n',1)[-1].split('\n',2)[1]
            return tax

    return tax


def extract_customer_job(raw_text):
    customer_job =''
    hit = re.search(r'Sold To:\s*\n(.*?)Job#', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()
        customer_job = customer_job.split('\n')[2]
    return customer_job


def extract_date(text):
    date = ''
    hit = re.search(r'Date:\s*(\d{2}/\d{2}/\d{2})', text)
    if hit: date = hit.group(1)
    return date


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'Date Req\s*(\d+)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    # Handle various order formats: 0081212A, 89779-I, I-000987, etc.
    patterns = [
        r"\nOrder:\s*([A-Za-z0-9\-]+)\n",  # General format: I-000987, 0081212A, 89779-I
        r"\nOrder:\s*([0-9]+[A-Za-z]?)\n",  # Numbers with optional letters: 0081212A
        r"\nOrder:\s*([A-Za-z]?[0-9]+)\n",  # Letters with numbers: I000987
        r"\nOrder:\s*([0-9]+-[A-Za-z]+)\n",  # Numbers with dash and letters: 89779-I
        r"\nOrder:\s*([A-Za-z]+-[0-9]+)\n",  # Letters with dash and numbers: I-000987
    ]
    
    for pattern in patterns:
        hit = re.search(pattern, text)
        if hit:
            ref_no = hit.group(1).strip()
            break
    
    return ref_no


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if 'Unnamed: 0' in table.columns : continue

        qty_col = table['Shp'].dropna().astype(int).reset_index(drop=True)
        table[['Exten', 'Ln']] = table['Exten Ln#'].str.split(expand=True)
        table.drop(columns=['Exten Ln#'], inplace=True)
        table['Ln'] = table['Ln'].ffill()
        table['Ln'] = table['Ln'].astype(int)
        table = table.groupby('Ln', as_index=False).agg(lambda x: ' '.join(x.dropna()))
        table.rename(columns={'Location': 'Item', 'B/O Description': 'Description', 'Net Price': 'Cost',
                              'Exten': 'Amount'}, inplace=True)
        table['Qty']= qty_col
        table['Description'] = table['Description'].str.replace('0 ', '')
        table['Item'] = table['Description'].str.extract(r'\s(\w*[/-]*\w*\d\w*)')

        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        table.reset_index(drop=True, inplace=True)
        invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items
