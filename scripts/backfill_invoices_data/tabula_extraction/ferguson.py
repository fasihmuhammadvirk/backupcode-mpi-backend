import tabula
import pandas as pd
import PyPDF2 as pyPdf  # alternate approach
import fitz
import re
import numpy as np
from .formatting_util import save_final_data

'''
1-Input file name
2.Check number of pages
    1-if the number of pages are 1
        .
    2-if it is more than 1

'''

# Get Number of pages in current file_name
def get_pages(filename):
    reader = pyPdf.PdfReader(filename)  # Updated from PdfFileReader
    num_pages = len(reader.pages)  # Updated from getNumPages()
    return num_pages


# Now extract the Ferguson supply data
def extract_ferguson_invoices_data(filename, output_path):

    if get_pages(filename) > 1:  # have different flow if we have >1 pages in invoice
        # extract_supremePlumbing_data_multiplepages(filename, output_path)

        return

    # Extract the header table of invoice
    ref,total_cost,po = extract_header_table(filename)

    # Extract the customer_job
    customer_job = extract_customer_job(filename)

    invoice_items = get_invoices_items(filename)
    result = process_final_invoices(invoice_items,ref,total_cost,po,customer_job)
    save_final_data(result, "Ferguson", output_path)


def extract_header_table(filename):
    '''
    :param filename:

    :return:
    '''
    tables = tabula.read_pdf(filename, pages=1, area=(33.84, 344.16, 56.88, 599.76), guess=False,
                             columns=[344.16, 413.76, 486.72, 554.56], pandas_options={'dtype': str})

    ref = extract_reference(tables)
    total_cost = extract_total_cost(tables)
    po = extract_po(tables)
    return ref, total_cost, po


def extract_po(tables):
    try:
        po = tables[0]['CUSTOMER'][0]
        return po
    except:
        return ''


def extract_total_cost(tables):
    try:
        total_cost = tables[0]['TOTAL DUE'][0]
        return total_cost
    except:
        return ''


def extract_reference(tables):
    try:
        ref = tables[0]['INVOICE NUMBER'][0]
        return ref
    except:
        return ''


def extract_customer_job(filename):
    customer_job = ''
    try:
        doc = fitz.open(filename)
        text = doc[0].get_text("text")  # "text" specifies the output format

        # Search for 'SHIP TO' and capture the following lines
        ship_to_pattern = r"SHIP TO:\s*([^\n]*)\n([^\n]*)\n(\d{2,3}[^\n]*)"
        match = re.search(ship_to_pattern, text, re.MULTILINE)

        if match:
            # Extract the third line that starts with three digits
            customer_job = match.group(3).strip()

        else:
            pass

    except:
        pass
    return customer_job


# get all invoice items
def get_invoices_items(filename):

    invoice_items = []
    # tables = tabula.read_pdf(filename, pages=1, area=(286.56,25.3 , 707.04, 589.76), guess=False,
    #                          columns=[25.3, 74.88, 119.16,195.08,400.32,471.12, 499.32], pandas_options={'dtype': str}
    tables = tabula.read_pdf(filename, pages='all', stream=True,pandas_options={'dtype': str})

    for table in tables:
        if len(table) > 4:
            clean_table = clean_invoice_items(table)

            clean_table = clean_table.rename(columns={'ITEM NUMBER': 'Item', 'DESCRIPTION': 'Description', 'ORDERED' : 'Qty', 'UNIT PRICE': 'Cost', 'AMOUNT': 'Amount','Invoice Date':'Date'})
            clean_table = clean_table[['Item', 'Description', 'Qty', 'Cost', 'Amount','Date', 'TAX']]

            clean_table['Amount'] = clean_table['Amount'].str.replace(',', '').str.replace('$', '').astype(float)
            clean_table['Cost'] = clean_table['Cost'].str.replace(',', '').str.replace('$', '').astype(float)
            clean_table['Qty'] = clean_table['Qty'].astype(str).str.replace(',', '').astype(float)
            clean_table['Qty'] = clean_table['Qty'].astype(int)
            invoice_items.append(clean_table)

    merged_invoice_items = pd.DataFrame()
    for item in range(len(invoice_items)):

        merged_invoice_items = pd.concat([merged_invoice_items, invoice_items[item]], axis=0)

    merged_invoice_items.reset_index(drop=True, inplace=True)
    return merged_invoice_items

def clean_invoice_items(table):
    # Extract Date of invoice

    # Regular expression to match the date pattern MM/DD/YY
    date_pattern = r'\d{2}/\d{2}/\d{2}'
    # Check if any values in the 'INVOICE DATE' column in the first 5 rows match the date pattern
    matching_rows = table['INVOICE DATE'].head(5).str.contains(date_pattern, na=False)
    matching_indices = matching_rows[matching_rows].index.tolist()
    # Extract the rows where the pattern matches
    invoice_date = table.iloc[matching_indices[0]]['INVOICE DATE']

    # Now reshaped the rest of table to extract items
    start_row = table[table.iloc[:, 0].str.contains("ORDERED", na=False)].index[0]

    # Slice the DataFrame from the located row onward
    subset_df = table.iloc[start_row:]
    subset_df.columns = subset_df.iloc[0]

    # Drop the row that has now become the header
    subset_df = subset_df[1:].reset_index(drop=True)

    #  Extract tax and create new column
    condition = subset_df[['AMOUNT']].isna().all(axis=1)

    # Find the index of the first row that meets this condition
    index_of_tax = subset_df[condition].index.min()
    subset_df['TAX'] = subset_df.iloc[index_of_tax-1]['AMOUNT']
    subset_df['Invoice Date'] = invoice_date
    # Extract the rows where the invoice items are clearly exist
    # Check where columns A, B, and C all have NaN in the same row
    condition = subset_df[['ORDERED', 'SHIPPED ITEM NUMBER', 'DESCRIPTION']].isna().all(axis=1)

    # Find the index of the first row that meets this condition
    first_nan_row_index = subset_df[condition].index.min()

    # Extract the rows above this index
    subset_df = subset_df.iloc[:first_nan_row_index]
    subset_df = subset_df.loc[:, ~subset_df.columns.isna()]

    # Split the 'SHIPPED ITEM NUMBER' column into two columns
    subset_df[['SHIPPED', 'ITEM NUMBER']] =  subset_df['SHIPPED ITEM NUMBER'].str.split(n=1, expand=True)

    # Drop the original 'SHIPPED ITEM NUMBER' column
    subset_df = subset_df.drop(columns=['SHIPPED ITEM NUMBER', 'UM'])

    return subset_df


def process_final_invoices(invoices_items,ref,total_cost,po,customer_job):
    tax = invoices_items['TAX'][0]
    tax = float(tax.replace("$", "").replace(",", ""))
    results = invoices_items.drop(columns=['TAX'])

    tax_row = ["10 Materials", "Tax", "", "", float(tax),'']
    results.loc[len(results)] = tax_row

    results["Ref NO"] = str(ref)
    results["PO #"] = str(po)
    results['Customer Job'] = customer_job
    results["Bill"] = "Bill"
    results["Vendor"] = "Ferguson"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""

    return results
