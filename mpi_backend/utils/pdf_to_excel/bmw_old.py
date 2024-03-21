import pandas as pd
import numpy as np
import os
import re
import fitz
import tabula
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data

regular_area = (300, 44, 300+341, 44+531)
credit_memo_area = (268,35.5, 268 + 342, 35.5 +540)
bmw_old_columns = [44, 84.2, 165.5, 445.5, 508]
credit_memo_columns = [35.5, 80.5, 138.6, 412.5, 494.8]


def process_invoice(filename, output_path):
    is_credit_memo = False
    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()
    if 'Credit Memo' in raw_text:
        tables = tabula.read_pdf(filename, pages='all', area=credit_memo_area, guess=False, stream=True,
                                columns=credit_memo_columns)
        is_credit_memo = True
    else:
        tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True, columns=bmw_old_columns)
    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)
    tax = extract_tax(filename)

    if is_credit_memo:
        hit = re.search(r'Credit No.\s*(\d+)\n', raw_text)
        if hit: ref_no = hit.group(1)
        try:
            tax = '-' + raw_text.rsplit('-',1)[-1].replace('$','').replace(',','')
            tax= float(tax)
        except:
            tax = 0

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data(result, "BMW Plumbing Supplies", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "BMW Plumbing Supplies"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if table.columns.values.tolist() == ['Unnamed: 0', 'Qty', 'Item', 'Description', 'Rate', 'Amount']: # credit memo type
            table.rename(columns={'Rate': 'Cost'}, inplace=True)
        else:
            table.rename(columns={'Price each': 'Cost'}, inplace=True)
        table['Amount'] = table['Amount'].str.replace('T', '')
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        table.dropna(subset=['Qty'],inplace=True)
        table['Qty'] = table['Qty'].astype(str).str.replace(',', '').astype(float)
        table['Qty'] = table['Qty'].astype(int)
        table.reset_index(drop=True, inplace=True)
        invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items


def extract_tax(filename):
    tables = tabula.read_pdf(filename, pages='all')
    return tables[-1].columns.values[-1].replace('$','').replace(',','')


def extract_customer_job(raw_text):
    customer_job =''
    hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()
    return customer_job


def extract_date(text):
    date = ''
    hit = re.search(r'Date\s*\n(\d{1,2}/\d{1,2}/\d{4})', text)
    if hit: date = hit.group(1)
    return date


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'P.O. No.\s*(\d+)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    hit = re.search(r"\nInvoice #\s*(\d+)\n", text)
    if hit : ref_no = hit.group(1)
    return ref_no

