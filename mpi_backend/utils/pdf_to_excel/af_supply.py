import tabula
import pandas as pd
import fitz
import re
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data

line_items_area = (263, 0, 263+418.40, 591)
line_items_columns = [62.56,125.63,186.62,421.49,520.33,590.72]

def process_invoice(filename, output_path):
    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()

    tables = tabula.read_pdf(filename,pages='all', area=line_items_area, guess=False, stream=True,
                                columns=line_items_columns)
    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)

    tax = extract_tax(raw_text)
    tax = float(tax.replace(",", ""))

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data(result, "AF Supply", output_path)
    pass


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "AF Supply"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_tax(raw_text):
    tax = ''
    hit = re.search(r'TAX\s*([\d,]+(?:\.\d{1,2})?)', raw_text)
    if hit:
        tax = hit.group(1).strip()
    return tax


def extract_customer_job(raw_text):
    customer_job = ''
    # capture line after SHIP TO: that starts with a street pattern --> number and name
    hit = re.search(r'SHIP TO:\s*\n(.*?)\n\s*(.*?)\n', raw_text, re.IGNORECASE)
    if hit:
        customer_job = hit.group(2).strip()
    return customer_job


def extract_date(text):
    date = ''
    dates = re.findall('.*?(\d{1,2}/\d{1,2}/\d{4})', text)  # capture all dates following the "INVOICE DATE" label
    return dates[-1] if dates else ''


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'JOB NO.\n*(\d+)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    hit = re.search(r"\nINVOICE NO.\n*(\d+)\n", text)
    if hit : ref_no = hit.group(1)
    return ref_no


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if table.columns.values.tolist() == ['LN NO.', 'QUANTITY', 'ITEM CODE', 'ITEM DESCRIPTION', 'UNIT PRICE', 'EXT-PRICE']:
            table.rename(columns={'QUANTITY': 'Qty','ITEM CODE': 'Item','ITEM DESCRIPTION': 'Description','UNIT PRICE': 'Cost','EXT-PRICE': 'Amount'}, inplace=True)
            table= table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]

            table['Amount'] = table['Amount'].astype(str).str.replace(',', '').str.replace('$', '').astype(float)
            table['Cost'] = table['Cost'].astype(str).str.replace(',', '').str.replace('$', '').astype(float)
            invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items