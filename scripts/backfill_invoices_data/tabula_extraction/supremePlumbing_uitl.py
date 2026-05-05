import tabula
import pandas as pd
import PyPDF2 as pyPdf  # alternate approach
import fitz
import re
import numpy as np
from .formatting_util import save_final_data


def extract_supremePlumbing_data(filename, output_path):
    if get_pages(filename) > 1:  # have different flow if we have >1 pages in invoice
        extract_supremePlumbing_data_multiplepages(filename, output_path)
        return

    tables = tabula.read_pdf(filename, pages='1', stream=True)

    # get tax details
    tax = extract_tax(filename, get_pages(filename))

    tax = float(tax.replace("$", "").replace(",", ""))
    tax_row = ["10 Materials", "Tax", "", "", tax]

    data = fitz.open(filename)
    invoice_data = data[0]
    invoice_data = invoice_data.get_text()

    # generate finalized details
    cleaned_invoice_attributes= pd.DataFrame(columns=['Date', 'Ref NO', 'PO #'], index=range(0,1))
    if not len(tables ) == 1: # date, rep, po# columns exist
        cleaned_invoice_attributes = clean_invoice_attributes(tables[0], filename)
        cleaned_invoice_items = clean_invoice_items(tables[1])

    else: # no invoice attributes available case
        cleaned_invoice_items = clean_invoice_items(tables[0])
        cleaned_invoice_attributes['Date'] = extract_date_from_shipping_slip(filename)

    results = cleaned_invoice_items
    try: # we have invoices in which there is no amount or cost for items - shipping slips
        results['Amount'] = results['Amount'].str.replace(',', '').str.replace('$', '').astype(float)
        results['Cost'] = results['Cost'].str.replace(',', '').str.replace('$', '').astype(float)
        results.loc[len(results)] = tax_row
    except:
        results.loc[len(results)] = ["10 Materials", "Tax", tax]
        cleaned_invoice_attributes['Date'] = extract_date_from_shipping_slip(filename)

    results[list(cleaned_invoice_attributes.columns)] = cleaned_invoice_attributes
    results["Date"] = cleaned_invoice_attributes[
        'Date'].item()  # were getting object instead of string-- so preprocessing
    if not cleaned_invoice_attributes['PO #'].empty:
        results["PO #"] = cleaned_invoice_attributes['PO #'].item()
    else:
        results["PO #"] = " "

    if cleaned_invoice_attributes['Date'].empty:
        results['Date'] = extract_date_from_shipping_slip(filename)

    if not len(tables) == 1:
        results["Ref NO"] = extract_refno(filename)
    elif 'Customer Credit CR-' in invoice_data:
        results["Ref NO"] = extract_refno(filename)

    job_name = get_customer_job(filename)

    memo = ""

    results['Customer Job'] = job_name

    results["Bill"] = "Bill"
    results["Vendor"] = "Supreme Plumbing Supply"
    results["Class"] = ""
    results["Memo"] = memo
    results["Buyer"] = ""

    save_final_data(results, "Supreme Plumbing Supply", output_path)


def merge_rows(table):
    for i in range(len(table) - 1, 0, -1):
        # Merge descriptions split across rows
        if (pd.notnull(table.at[i, 'Description']) and
                pd.isnull(table.at[i, 'Qty']) and
                pd.isnull(table.at[i, 'Cost']) and
                pd.isnull(table.at[i, 'Amount'])):
            # Append the description to the previous row
            table.at[
                i - 1, 'Description'] = f"{table.at[i - 1, 'Description']} {table.at[i, 'Description']}".strip()

            # Clear the current row's description
            table.at[i, 'Description'] = None

        # Move 'Name' value up if the current row is empty except for 'Name'
        if (pd.notnull(table.at[i, 'Item']) and
                pd.isnull(table.at[i, 'Description']) and
                pd.isnull(table.at[i, 'Qty']) and
                pd.isnull(table.at[i, 'Cost']) and
                pd.isnull(table.at[i, 'Amount'])):

            # Check if the row above has no null values in the specified columns
            if (pd.notnull(table.at[i - 1, 'Description']) and
                    pd.notnull(table.at[i - 1, 'Qty']) and
                    pd.notnull(table.at[i - 1, 'Cost']) and
                    pd.notnull(table.at[i - 1, 'Amount'])):
                # Paste the 'Name' value from the current row to the row above
                table.at[i - 1, 'Item'] = table.at[i, 'Item']
    return table


def clean_invoice_items(table):

    # we cannot look for NAN - 6 and 8 columns are returned depending on invoice
    if {'Qty Shipped'}.issubset(table.columns):
        table = table[['Item', 'Description', 'Unnamed: 0']]
        table = table.rename(
            columns={'Unnamed: 0': 'Qty'})

    elif {'Image'}.issubset(table.columns) and not {'Unnamed: 0'}.issubset(table.columns):
        table = table[['Item', 'Description', 'Qty', 'Rate', 'Amount']]
        table = table.rename(
            columns={'Rate': 'Cost'})

    elif {'Image','Name'}.issubset(table.columns):
        table = table[['Name', 'Description', 'Unnamed: 0', 'Price', 'Amount']]
        table = table.rename(
            columns={'Name': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                     'Price': 'Cost', 'Amount': 'Amount'})

    elif {'Image'}.issubset(table.columns):
        table = table[['Item', 'Description', 'Unnamed: 0', 'Rate', 'Amount']]
        table = table.rename(
            columns={'Item': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                     'Rate': 'Cost', 'Amount': 'Amount'})

    elif len(table.columns) == 7 and {'#', 'Name', 'Description', 'Qty', 'Price', 'Unnamed: 0', 'Amount'}.issubset(table.columns):
        if table['Unnamed: 0'].isnull().all() :
            table = table[['Name', 'Description', 'Qty', 'Price', 'Amount']]
            table = table.rename(columns={'Name': 'Item', 'Price': 'Cost'})
        elif not {'Unnamed: 1'}.issubset(table.columns) and not table['Price'].isnull().all():
            table = table[['Name', 'Description', 'Unnamed: 0', 'Price', 'Amount']]
            table = table.rename(columns={'Name': 'Item', 'Unnamed: 0': 'Qty', 'Price': 'Cost'})
            if table['Item'].isnull().any():
                table = merge_rows(table)


        else:
            table = table[['Name', 'Description','Qty', 'Unnamed: 0','Amount']]
            table = table.rename(columns={'Name': 'Item', 'Unnamed: 0': 'Cost', 'Unnamed: 1': 'Cost'})

    elif len(table.columns) == 8 and {'Unnamed: 0','Unnamed: 1'}.issubset(table.columns) \
            and not table[['Unnamed: 0','Unnamed: 1']].isnull().values.any():
        table = table[['Name', 'Description', 'Unnamed: 0', 'Unnamed: 1', 'Amount']]
        table = table.rename(columns={'Name': 'Item', 'Unnamed: 0': 'Qty',   'Unnamed: 1': 'Cost'})

    elif len(table.columns) == 8 and {'Unnamed: 0','Unnamed: 1'}.issubset(table.columns) \
            and not table[['Qty', 'Price']].notnull().values.any():
        table = table[['Name', 'Description', 'Unnamed: 0', 'Unnamed: 1', 'Amount']]
        table = table.rename(columns={'Name': 'Item', 'Unnamed: 0': 'Qty',   'Unnamed: 1': 'Cost'})

    elif len(table.columns) == 8:
        table = table[['Item', 'Description', 'Unnamed: 1', 'Rate', 'Amount']]
        table = table.rename(
            columns={'Item': 'Item', 'Description': 'Description', 'Unnamed: 1': 'Qty',
                     'Rate': 'Cost', 'Amount': 'Amount'})

    elif list(table.columns.values) == ['#', 'Name', 'Description', 'Qty', 'Price', 'Amount']:
        table = table[['Name', 'Description', 'Qty', 'Price', 'Amount']]
        table = table.rename(columns={'Name': 'Item', 'Price': 'Cost'})

    elif not {'Unnamed: 0'}.issubset(table.columns):
        table = table[['Item', 'Description', 'Qty', 'Rate', 'Amount']]
        table = table.rename(
            columns={'Item': 'Item', 'Description': 'Description', 'Qty': 'Qty',
                     'Rate': 'Cost', 'Amount': 'Amount'})

    elif ['#', 'Item', 'Description', 'Qty', 'Rate', 'Unnamed: 0', 'Amount'] == list(table.columns): # pattern in invoices without logo
        table = table[['Item', 'Description', 'Qty', 'Unnamed: 0', 'Amount']]
        table = table.rename(
            columns={'Unnamed: 0': 'Cost'})
    else:
        table = table[['Item', 'Description', 'Unnamed: 0', 'Rate', 'Amount']]
        table = table.rename(
            columns={'Item': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                     'Rate': 'Cost', 'Amount': 'Amount'})
    table.dropna(subset=["Item", "Description", "Qty"], inplace=True)
    table.reset_index(drop=True, inplace=True)
    return table


def clean_invoice_attributes(table, filename):

    if len(table.columns) == 5 and 'Customer PO #' in table.columns:
        # a new pattern, with CUSTOMER PO# in table columns
        table = table[['Date', 'Rep', 'Customer PO #']]
        table = table.rename(
            columns={'Date': 'Date', 'Rep': 'Ref NO', 'Customer PO #': 'PO #'})
    elif len(table.columns) == 5:  # we have 'rep' column so just dropping & renaming
        table = table[['Date', 'Rep', 'PO #']]
        table = table.rename(
            columns={'Date': 'Date', 'Rep': 'Ref NO', 'PO #': 'PO #'})
    else:  # triggered when we don't have 'rep' column so inserting & dropping
        table = table[['Date', 'PO #']]
        table.insert(1, "Ref NO", " ")
        table = table.rename(
            {'Date': 'Date', 'Ref NO': 'Ref NO', 'PO #': 'PO #'})

    return table


def extract_refno(filename):
    data = fitz.open(filename)
    invoice_data = data[0]
    invoice_data = invoice_data.get_text()

    if 'Customer Credit CR-' in invoice_data:
        invoice_data = invoice_data.split("Customer Credit CR-", 1)
        invoice_data = invoice_data[1].split("\n", 1)
        invoice_data = invoice_data[0]
        return 'CR-' + str(invoice_data)

    invoice_data = invoice_data.split("Invoice", 1)
    invoice_data = invoice_data[1].split("\n", 1)
    invoice_data = invoice_data[0]

    return str(invoice_data)


def extract_date_from_shipping_slip(filename):
    date = ''
    data = fitz.open(filename)
    invoice_data = data[0]
    invoice_data = invoice_data.get_text()
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", invoice_data)
    if not date_match : date_match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", invoice_data)

    if date_match : date = date_match.group()
    return date


def extract_tax(filename, page):
    tax = '0'
    data = fitz.open(filename)
    lastPageData = data[page - 1]
    lastPageData = lastPageData.get_text()

    if "NYS (8.875%)" in lastPageData:
        return lastPageData.split("NYS (8.875%)", 1)[-1].split('\n')[1]
    elif "Tax:" in lastPageData:
        return lastPageData.split("(8.875%)", 1)[-1].split('$')[1].split()[0]
    elif "(8.875%)" in lastPageData:
        return lastPageData.split("(8.875%):", 1)[-1].split('\n')[1]


    if not "NJS (6.625%)" in lastPageData:
        if lastPageData != 0 and not "NJS (6.625%):" in data[page - 2].get_text():
            # will be triggered if last and second page don't contain Tax [BUG FIX: File not containing tax]
            return tax
        elif lastPageData == 0: # it is already the last page and tax is not given
            return tax

    if "NJS (6.625%)" in data[page - 2].get_text():
        lastPageData = data[page - 2].get_text()
        lastPageData = lastPageData.split("Subtotal:", 1)
        lastPageData = lastPageData[1].split("\n", 3)
        tax = str(lastPageData[2])
        if 'NJS (6.625%):' in tax:  # patch 11th Nov
            lastPageData = lastPageData[3].split("\n", 1)
            tax = str(lastPageData[0])
            return tax

    if not "Subtotal" in lastPageData:
        lastPageData = data[page - 2]
        lastPageData = lastPageData.get_text()
        lastPageData = lastPageData.split("Subtotal:", 1)
        lastPageData = lastPageData[1].split("\n", 3)
        tax = str(lastPageData[2])
    else:
        lastPageData = lastPageData.split("Subtotal:", 1)
        lastPageData = lastPageData[1].split("\n", 3)
        tax = str(lastPageData[2])
        if 'NJS (6.625%):' in tax: # patch 11th Nov
            lastPageData = lastPageData[3].split("\n", 1)
            tax =  str(lastPageData[0])

    return tax


def get_pages(filename):
    reader = pyPdf.PdfReader(filename)
    numPages = len(reader.pages)
    return numPages


def get_customer_job(filename):
    data = fitz.open(filename)
    uncleaned_data = data[0]
    uncleaned_data = uncleaned_data.get_text()
    if "Shipping Address"in uncleaned_data:
        uncleaned_data = uncleaned_data.split("Shipping Address", 1)
        uncleaned_data = uncleaned_data[1].split("\n", 4)
        pattern = re.compile(r'\d\d\d')
    else:
        uncleaned_data = uncleaned_data.split("Ship to", 1)
        uncleaned_data = uncleaned_data[1].split("\n", 4)
        pattern = re.compile(r'\d\d\d')

    customer_job = " "
    for string in uncleaned_data:
        hit = pattern.search(string)
        if not hit == None:
            customer_job = string
            if len(customer_job) > 50 and len(list(filter(re.compile(r'\d\d').match, uncleaned_data))) > 0:  # adding additional check, were getting false positive (2 digit street no)
                customer_job = list(filter(re.compile(r'\d\d').match, uncleaned_data))[0]
            break

    if len(customer_job) > 120:  # still customer job has not been found
        job_table = tabula.read_pdf(filename, area=(152, 312.5, 152 + 68, 312.5 + 278), stream=True)
        try:
            return job_table[0]['Ship to'].str.cat(sep=' ')
        except:  # customer job was not specified
            pass

    if len(customer_job) > 120:  # credit invoice
        job_table = tabula.read_pdf(filename, area=(152, 300.5, 152 + 68, 300.5 + 278), stream=True)
        try:
            return job_table[0]['Shipping Address'][1]
        except:  # customer job was not specified
            customer_job = ''

    return customer_job


def merge_and_clean_invoice_items(tables):

    finalized_tables = []

    if len(tables) > 1:  # has to be true in all cases
        for i in range(len(tables)):

            if i == 0 and {'Image'}.issubset(tables[0].columns) and not {'Unnamed: 0'}.issubset(tables[0].columns):

                if {'Name','Price'}.issubset(tables[0].columns) :
                    tables[i].rename(
                        columns={'Name': 'Item', 'Description': 'Description', 'Qty': 'Qty',
                                 'Price': 'Rate', 'Amount': 'Amount'}, inplace=True)

                individual_table = tables[i][['Item', 'Description', 'Qty', 'Rate', 'Amount']]

                individual_table = individual_table.rename(
                    columns={'Rate': 'Cost'})
                individual_table.dropna(subset=["Item", "Description"], inplace=True)
                individual_table.reset_index(drop=True, inplace=True)
                finalized_tables.append(individual_table)

            elif {'Name'}.issubset(tables[i].columns):
                if {'Unnamed: 0'}.issubset(tables[i].columns):
                    individual_table = tables[i][['Name', 'Description', 'Unnamed: 0', 'Price', 'Amount']]
                    individual_table = individual_table.rename(
                        columns={'Name': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                                 'Price': 'Cost'})
                    individual_table.dropna(subset=["Item", "Description"], inplace=True)
                    individual_table.reset_index(drop=True, inplace=True)
                else:
                    individual_table = tables[i][['Name', 'Description', 'Qty','Price', 'Amount']]
                    individual_table = individual_table.rename(
                        columns={'Name': 'Item', 'Description': 'Description', 'Price': 'Cost'})
                    individual_table.dropna(subset=["Cost", "Description","Qty","Amount"], inplace=True)
                finalized_tables.append(individual_table)

            elif i == 0 and 'Unnamed: 0' in tables[i].columns:
                individual_table = tables[i][['Item', 'Description', 'Unnamed: 0', 'Rate', 'Amount']]
                individual_table = individual_table.rename(
                    columns={'Item': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                             'Rate': 'Cost', 'Amount': 'Amount'})
                individual_table.dropna(subset=["Item", "Description"], inplace=True)
                individual_table.reset_index(drop=True, inplace=True)
                finalized_tables.append(individual_table)
            else:
                individual_table = tables[i][['Item', 'Description', 'Qty', 'Rate', 'Amount']]
                individual_table = individual_table.rename(
                    columns={'Item': 'Item', 'Description': 'Description', 'Qty': 'Qty',
                             'Rate': 'Cost', 'Amount': 'Amount'})
                individual_table.dropna(subset=["Item", "Description"], inplace=True)
                individual_table.reset_index(drop=True, inplace=True)
                finalized_tables.append(individual_table)

    else:  # ideally should not be triggered at all, but adding for fun/agility

        if {'Image'}.issubset(tables[0].columns) and not {'Unnamed: 0'}.issubset(tables[0].columns):
            tables = tables[0][['Item', 'Description', 'Qty', 'Rate', 'Amount']]
            tables = tables.rename(
                columns={'Rate': 'Cost'})

        elif {'Image', 'Name'}.issubset(tables[0].columns):
            tables = tables[0][['Name', 'Description', 'Unnamed: 0', 'Price', 'Amount']]
            tables = tables.rename(
                columns={'Name': 'Item', 'Unnamed: 0': 'Qty', 'Price' : 'Cost'})

        elif {'Image'}.issubset(tables[0].columns):
            tables = tables[0][['Item', 'Description', 'Unnamed: 0', 'Rate', 'Amount']]
            tables = tables.rename(
                columns={'Item': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                         'Rate': 'Cost', 'Amount': 'Amount'})

        elif {'Name','Unnamed: 0'}.issubset(tables[0].columns):
            tables = tables[0][['Name', 'Description', 'Qty','Unnamed: 0', 'Amount']]
            tables = tables.rename(
                columns={'Name': 'Item', 'Unnamed: 0': 'Cost'})

        elif len(tables[0].columns) == 8 and {'Name', 'Price','Unnamed: 0', 'Unnamed: 1'}.issubset(tables[0].columns):
            tables = tables[0][['Name', 'Description', 'Unnamed: 0', 'Price', 'Amount']]
            tables = tables.rename(columns={'Name': 'Item', 'Unnamed: 0': 'Qty', 'Price': 'Cost'})

        elif {'#', 'Name', 'Description', 'Qty', 'Price', 'Amount'}.issubset(tables[0].columns):
            tables = tables[0][['Name', 'Description', 'Qty', 'Price', 'Amount']]
            tables = tables.rename(
                columns={'Name': 'Item', 'Price': 'Cost'})

        elif not {'Unnamed: 0'}.issubset(tables[0].columns):
            tables = tables[0][['Item', 'Description', 'Qty', 'Rate', 'Amount']]
            tables = tables.rename(
                columns={'Item': 'Item', 'Description': 'Description', 'Qty': 'Qty',
                         'Rate': 'Cost', 'Amount': 'Amount'})

        else:
            tables = tables[0][['Item', 'Description', 'Unnamed: 0', 'Rate', 'Amount']]
            tables = tables.rename(
                columns={'Item': 'Item', 'Description': 'Description', 'Unnamed: 0': 'Qty',
                         'Rate': 'Cost', 'Amount': 'Amount'})
        tables.dropna(subset=["Item", "Description"], inplace=True)
        tables.reset_index(drop=True, inplace=True)
        finalized_tables.append(tables)
        # finalized_tables.append(clean_invoice_items(tables))
    return finalized_tables


# the idea behind this function is to use bars/ seperators in invoice file
# to get all required information i.e use existing natural dividers in file
def extract_supremePlumbing_data_multiplepages(filename, output_path):

    tables = tabula.read_pdf(filename, pages='all', stream=False, guess=True)

    extraction_start_index = 0

    for index,table in enumerate(tables):
        # had to rewrite the multiple page extraction logic
        # because of unique pattern occurred
        if {'Date', 'PO #'}.issubset(table.columns) or {'Date', 'Customer PO #'}.issubset(table.columns):
            extraction_start_index = index
            break

    cleaned_invoice_attributes = clean_invoice_attributes(tables[extraction_start_index],filename)
    # invoice items will always be after the Invoice Attributes(Date, PO# etc.)
    cleaned_invoice_items = merge_and_clean_invoice_items(tables[extraction_start_index + 1:])

    # get tax details
    tax = extract_tax(filename, get_pages(filename))
    tax = float(tax.replace("$", "").replace(",", ""))
    tax_row = ["10 Materials", "Tax", "", "", tax]

    # generate finalized details
    results = pd.DataFrame()
    for item in range(len(cleaned_invoice_items)):
        results = pd.concat([results, cleaned_invoice_items[item]], axis=0)
    # results =  pd.concat([cleaned_invoice_items[0], cleaned_invoice_items[1]], axis=0)

    results['Amount'] = results['Amount'].str.replace(',', '').str.replace('$', '').astype(float)
    results['Cost'] = results['Cost'].str.replace(',', '').str.replace('$', '').astype(float)

    results.loc[len(results)] = tax_row
    results[list(cleaned_invoice_attributes.columns)] = cleaned_invoice_attributes
    results["Date"] = cleaned_invoice_attributes[
        'Date'].item()  # were getting object instead of string-- so preprocessing
    if not cleaned_invoice_attributes['PO #'].empty:
        results["PO #"] = cleaned_invoice_attributes['PO #'].item()
    else:
        results["PO #"] = " "

    results["Ref NO"] = extract_refno(filename)

    job_name = get_customer_job(filename)

    memo = ""

    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Supreme Plumbing Supply"
    results["Class"] = ""
    results["Memo"] = memo
    results["Buyer"] = ""

    save_final_data(results, "Supreme Plumbing Supply", output_path)
    return
