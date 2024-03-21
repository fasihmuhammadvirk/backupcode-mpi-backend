import pandas as pd
import numpy as np
import os
import re
import fitz
import tabula
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data

regular_area = (309,34,292+309, 34+540)
columns = [287,383,477.6]


def process_invoice(filename, output_path):

    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()

    tables = tabula.read_pdf(filename, pages='all', area=regular_area, stream=False, columns=columns)

    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(raw_text)
    tax= extract_tax(raw_text)

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data(result, "Y & S Plumbing Supplies", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Y & S Plumbing Supplies"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if table.columns.values.tolist() == ['Description', 'Qty', 'Rate', 'Amount']:
            table.rename(columns={'Rate': 'Cost'}, inplace=True)
            table['Item'] = '' # credit memo doesnot contain items column, but is expected in excel format

        table['Amount'] = table['Amount'].str.replace('T', '')
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        dropna = table.dropna(subset=['Qty'], inplace=True)
        table['Qty'] = table['Qty'].astype(str).str.replace(',', '').astype(float)
        table['Qty'] = table['Qty'].astype(int)
        table.reset_index(drop=True, inplace=True)
        invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    return merged_invoice_items


def extract_tax(text):
    try :
        tax = text.rsplit('$',3)[2]
        tax = re.sub(r'[^0-9.]', '', tax) # keep only digits and decimal
    except:
        tax=0
    return tax


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
    hit = re.search(r'P.O. No.\n(\w*\d*)\n', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    if 'Credit No.' in text:
        hit = re.search(r"\nCredit No.\s*(\d+)\n", text)
        if hit: ref_no = hit.group(1)
    else:
        hit = re.search(r"\nInvoice #\s*(\d+)\n", text)
        if hit : ref_no = hit.group(1)
    return ref_no

