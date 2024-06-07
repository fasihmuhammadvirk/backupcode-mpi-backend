import tabula
import pandas as pd
import PyPDF2 as pyPdf  # alternate approach
import fitz
import re
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.pdf_to_excel.supremePlumbing_uitl import get_pages

columns = [46,183,371,429,510,589]
items_area = [360,22,360+410, 568+22]
customer_job_area = [142.40,312.55, 142.40+ 92.40, 312.55 + 277.89]


def process_invoice(filename, output_path):
    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()

    tables = tabula.read_pdf(filename, pages='all', guess=True, stream=False, columns=columns)
    invoice_items = extract_invoice_items(tables)

    ref_no = extract_ref_no(raw_text)
    po_no = extract_po_no(raw_text)
    date = extract_date(raw_text)
    customer_job = extract_customer_job(filename)

    tax = extract_tax(filename, get_pages(filename))
    tax = float(tax.replace("$", "").replace(",", ""))

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data(result, "Flow Mark Plumbing Supply", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = invoice_no
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Flow Mark Plumbing Supply"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results


def extract_customer_job(filename):
    customer_job =''
    tables = tabula.read_pdf(filename, pages=1, area= customer_job_area)
    try:
        customer_job = tables[0]['Ship to'][1]
    except:
        pass
    return customer_job


def extract_date(text):
    date = ''
    hit = re.search(r'Date\s*\n(\d{1,2}/\d{1,2}/\d{4})', text)
    if hit: date = hit.group(1)

    if date == '': # no date was found using above pattern
        hit = re.search(r'Terms\s*\n(\d{1,2}/\d{1,2}/\d{4})', text)
        if hit: date = hit.group(1)
    return date


def extract_po_no(text):
    po_no = ''
    hit = re.search(r'Customer PO #\n(\w*\d*)Rep', text)
    if hit: po_no = hit.group(1)
    return po_no


def extract_ref_no(text):
    ref_no = ''
    if 'Sale Order' in text:
        hit = re.search(r"\nSale Order\s*(SO-\d+)\n", text)
        if hit: ref_no = hit.group(1)

    elif 'Customer Credit' in text:
        hit = re.search(r"\nCustomer Credit\s*(CR-\d+)\n", text)
        if hit: ref_no = hit.group(1)

    elif 'Invoice' in text:
        hit = re.search(r"\nInvoice\s*(I-\d+)\n", text)
        if hit: ref_no = hit.group(1)
    return ref_no


def extract_invoice_items(tables):
    invoice_items = []
    for table in tables:
        if {'Date', 'Due Date', 'Rep', 'Customer PO #', 'Terms'}.issubset(table.columns):
            continue # header table- should not be processed

        if {'Unnamed: 0', 'Unnamed: 1', 'Manufact', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 4', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7'}.issubset(table.columns):
            table = table[['Unnamed: 1', 'Unnamed: 2', 'Unnamed: 3', 'Unnamed: 6', 'Unnamed: 7']]
            table = table.rename(
                columns={'Unnamed: 1': 'Item', 'Unnamed: 2': 'Description', 'Unnamed: 3': 'Qty', 'Unnamed: 6': 'Cost', 'Unnamed: 7': 'Amount'})
            #dropping header row
            rows_to_drop = table[(table['Item'] == 'Name') & (table['Description'] == 'Description') & (table['Qty'] == 'Qty') & (
                        table['Cost'] == 'Price') & (table['Amount'] == 'Amount')].index
            table.drop(rows_to_drop, inplace=True)

        elif {'Unnamed: 0','Unnamed: 1'}.issubset(table.columns) and table['Rate'].isna().all():
            table = table[['Item', 'Description', 'Unnamed: 0', 'Unnamed: 1', 'Amount']]
            table = table.rename(
                columns={'Unnamed: 0': 'Qty', 'Unnamed: 1': 'Cost'})

        elif 'Unnamed: 0' in table.columns and table['Unnamed: 0'].isna().all():
            table = table[['Item', 'Description', 'Qty', 'Rate', 'Amount']]
            table = table.rename(
                columns={'Rate': 'Cost'})

        elif 'Unnamed: 0' in table.columns and table['Rate'].isna().all():
            table = table[['Item', 'Description', 'Qty', 'Unnamed: 0', 'Amount']]
            table = table.rename(
                columns={'Unnamed: 0': 'Cost'})

        elif 'Unnamed: 0' in table.columns and table['Qty'].isna().all():
            table = table[['Item', 'Description', 'Unnamed: 0', 'Rate', 'Amount']]
            table = table.rename(
                columns={'Unnamed: 0': 'Qty', 'Rate': 'Cost'})

        elif {'#', 'MPN'}.issubset(table.columns) and len(table.columns) == 5:
            table = table[['Name', 'Description', 'Qty']]
            table['Cost'] = '0'
            table['Amount'] = '0'
            table = table.rename(columns={'Name': 'Item'})

        elif {'#','MPN'}.issubset(table.columns):
            table = table[['Name', 'Description', 'Qty', 'Price', 'Amount']]
            table = table.rename(columns={'Name': 'Item', 'Price': 'Cost'})

        elif {'#', 'Item Name'}.issubset(table.columns):
            table = table[['Item Name', 'Description', 'Return Qty', 'Amount']]
            table['Cost'] = '0'
            table = table.rename(columns={'Item Name': 'Item', 'Return Qty': 'Qty'})

        else:
            table = table[['Item', 'Description', 'Qty', 'Rate', 'Amount']]
            table = table.rename(
                columns={'Rate': 'Cost'})

        table.dropna(subset=['Qty', 'Description', 'Cost', 'Amount'], inplace=True)

        table['Amount'] = table['Amount'].str.replace(',', '').str.replace('$', '').astype(float)
        table['Cost'] = table['Cost'].str.replace(',', '').str.replace('$', '').astype(float)
        table['Qty'] = table['Qty'].astype(str).str.replace(',', '').astype(float)
        table['Qty'] = table['Qty'].astype(int)
        invoice_items.append(table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):
        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    merged_invoice_items.reset_index(drop=True, inplace=True)
    return merged_invoice_items


def extract_tax(filename, page):
    tax = '0'
    data = fitz.open(filename)
    lastPageData = data[page - 1]
    lastPageData = lastPageData.get_text()

    if "NY Sales Tax (8.875%)" in lastPageData:
        return lastPageData.split("NY Sales Tax (8.875%)", 1)[-1].split('\n')[1]
    elif "(8.875%)" in lastPageData:
        return lastPageData.split("(8.875%):", 1)[-1].split('\n')[1]

    try :
        if not "Subtotal" in lastPageData:
            lastPageData = data[page - 2]
            lastPageData = lastPageData.get_text()
            lastPageData = lastPageData.split("NY Sales Tax (8.875%):", 1)
            lastPageData = lastPageData[1].split("\n", 2)
            tax = str(lastPageData[1])
        else:
            lastPageData = lastPageData.split("NY Sales Tax (8.875%):", 1)
            lastPageData = lastPageData[1].split("\n", 2)
            tax = str(lastPageData[1])
    except IndexError: # raised when tax field is not present in file
        print('No Tax field found!')
    return tax
