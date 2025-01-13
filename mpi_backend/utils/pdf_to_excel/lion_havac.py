import tabula
import pandas as pd
import PyPDF2 as pyPdf  # alternate approach
import fitz
import re
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.pdf_to_excel.extraction_util import read_invoice
import os

# area1 = [205.5, 16.67, 205.5+140.85, 16.67+562.99]
area1 = [205.5, 16.67, 205.5+390, 16.67+573]
area2 = [227, 21.18, 227+196.56, 21.18+550.99] # for credit invoices

def process_invoice(filename, output_path):
    raw_text = read_invoice(filename)
    invoice_items = extract_invoice_items(filename,raw_text)
    customer_job = extract_customer_job(raw_text)
    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    tax = extract_tax(raw_text)
    buyer = extract_buyer(raw_text)

    results = process_results(invoice_items, date, ref_no, tax, customer_job, po_no, buyer)
    save_final_data(results, "Lion Hvac Supplies", output_path)

def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no="", buyer=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Lion Hvac Supplies"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = buyer
    return results

def extract_buyer(text):
    buyer = ''
    if 'Ordered By:' in text:
        hit = re.search(r'\n\s*(.*?)\s*Ordered By:', text)
        if hit: buyer = hit.group(1).strip()

    return buyer

def extract_tax(text):
    tax = ''
    if 'Sales Tax: 8.8750 %' in text:
        tax = text.split('Sales Tax: 8.8750 %\n',1)[1].split('\n',2)[0]
        return tax.replace('$','').replace(',','')
    elif 'Sales Tax:' in text:
        tax = text.split('Sales Tax:\n', 1)[1].split('\n', 2)[0]
        return tax.replace('$', '').replace(',','')
    return tax

def extract_date(text):
    date = ''
    hit = re.search(r'Date:\s*(\d{2}/\d{2}/\d{4})', text)
    if hit: date = hit.group(1)
    elif 'Credit Issued:' in text:
        hit = re.search(r'Credit Issued: \s*(\d{2}/\d{2}/\d{4})', text)
        if hit: date = hit.group(1)
    elif hit is None:
        hit = re.search(r'Date:\s*(\d{1}/\d{1}/\d{4})', text)
        if hit: date = hit.group(1)
    return date

def extract_po_no(text):
    po_no = ''
    hit = re.search(r'SO#: (\d+)', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    hit = re.search(r"#:(\d+)", text)
    if hit : ref_no = hit.group(1)
    else :
        hit = re.search(r"Credit # (\d+)", text)
        if hit: ref_no = hit.group(1).strip()
    return ref_no


def extract_customer_job(raw_text):
    customer_job = ''
    hit = re.search(r'Ship To:\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()

    if 'Credit To:' in raw_text:
        hit = re.search(r'Customer\sReturn\d+\s+([^\n]+)', raw_text, re.DOTALL)
        if hit: customer_job = hit.group(1).strip()

    return customer_job


def extract_invoice_items(filename, raw_text):
    table = tabula.read_pdf(filename, pages='all', guess=True, stream=False, area=[area1], columns= [42.58, 126.13,355.81,409.3,449.36,495,536])[0]
    table = table[~table.iloc[:, 0].astype(str).str.startswith('$')] # drop rows in df which start with $

    if 'Page 1 of 2' in raw_text and 'Order' in str(table.columns[0]): # a different flow for multi page invoices
        tables = tabula.read_pdf(filename, pages='all')
        table = pd.DataFrame() # will hold cleaned, combined lne items
        for tab in tables:
            tab = tab[tab.iloc[:, 0].astype(str).str.match(r'^\d{1,2}$')]
            tab = tab.iloc[:, :8] # keep first eight columns only
            tab.columns = [  # rename columns
                tab.columns[0], 'Item', 'Description', 'Qty', tab.columns[4], 'Cost', tab.columns[6], 'Amount']
            tab = tab[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
            table = pd.concat([table, tab], ignore_index=True)

    if 'Customer Credit' in raw_text:
        table = tabula.read_pdf(filename, pages='all', guess=True, stream=False, area=[area2])[0]
        table = table[table.iloc[:, 0].astype(str).str[0].str.isdigit()] # drop row if it doesnot start with digit```
        table.columns = [  # rename columns
            table.columns[0], 'Item', 'Description', 'Qty',
            table.columns[4], 'Cost', table.columns[6], 'Amount']
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]

    elif len(table.columns) == 10 and 'Order Date' in str(table.columns[0]):
        table = tabula.read_pdf(filename, pages='all', guess=False, stream=False, area=[[210, 21.18, 210+196.56, 21.18+550.99]])[0]
        table.columns = [  # rename columns
            table.columns[0], 'Item', 'Description', 'Qty',
            table.columns[4], 'Cost', table.columns[6], 'Amount']
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]

    elif{'LineItem NumberDescriptionInvoicedUOMUnit PriceUOMItem Tota', 'Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6'}.issubset(table.columns)\
            or len(table.columns[0]) > 20:
        table.columns = [ # rename columns
            table.columns[0], 'Item', 'Description', 'Qty',
            table.columns[4], 'Cost', table.columns[6], 'Amount']
        table = table[[ 'Item', 'Description', 'Qty','Cost', 'Amount']]
    elif {'Line', 'Item Number', 'Description', 'Invoiced', 'UOM', 'Unit Price UOM', 'Unnamed: 0', 'Item Tota'}.issubset(table.columns):
        table.rename(columns={'Item Number':'Item', 'Invoiced':'Qty', 'Unit Price UOM':'Cost', 'Item Tota': 'Amount'}, inplace=True)
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]

    elif 'Order' in str(table.columns[0]) or len(table.columns.to_list()) == 8:
        table.columns = [  # rename columns
            table.columns[0], 'Item', 'Description', 'Qty',
            table.columns[4], 'Cost', table.columns[6], 'Amount']
        table = table[['Item', 'Description', 'Qty', 'Cost', 'Amount']]
        if table['Item'][0] == 'Item Number': table = table.drop(index=0).reset_index(drop=True)

    table = table[~table.iloc[:, 0].astype(str).str.startswith('$')]  # drop rows in df which start with $
    table = table[~table.iloc[:, 0].astype(str).str.startswith('nan')]  # drop rows in df which start with $
    table.dropna(how='all', inplace=True)
    table.dropna(subset=['Qty', 'Cost', 'Amount'], inplace=True)
    table.reset_index(drop=True, inplace=True)

    table['Amount'] = table['Amount'].str.replace(',', '').str.replace('$', '').replace('.00', '').astype(float)
    table['Cost'] = table['Cost'].str.replace(',', '').str.replace('$', '').replace('.00', '').astype(float)
    table['Qty'] = table['Qty'].astype(str).str.replace(',', '').replace('.00', '').astype(float)
    table['Qty'] = table['Qty'].astype(int)
    return table

