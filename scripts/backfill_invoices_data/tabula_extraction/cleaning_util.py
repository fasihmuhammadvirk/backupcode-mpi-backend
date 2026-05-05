import pandas as pd
import numpy as np
import os
import re
from os import listdir
import fitz
from os.path import isfile, join
from PyPDF2 import PdfReader, PdfWriter
from .extraction_util import extract_invoice_info


def clean_spaces(text):
    if isinstance(text, str):
        return ''.join(text.split())
    return text


def clean_individual_table(table, page, check_row_count=False):
    if len(table) < 2 and check_row_count:  # skip if processed by camelot
        return None

    try:
        cols = [
            'LN', 'QNTY.1', 'QNTY.2', 'PRODUCT',
            'Unnamed: 1', 'NET', 'EXTENSION'
        ]
        table = table[cols]
    except KeyError:
        columns_set = {
            'Unnamed: 0', 'L N', 'Q N T Y', 'Q N T Y.1', 'Q N T Y.2',
            'P R O D U C T', 'Unnamed: 1', 'U O M', 'N E T', 'EXTENSION'
        }
        if columns_set.issubset(table.columns):
            table = table[[
                'L N', 'Q N T Y.1', 'Q N T Y.2', 'P R O D U C T',
                'Unnamed: 1', 'N E T', 'EXTENSION'
            ]]
            table = table.rename(columns={
                'L N': 'LN',
                'Q N T Y.1': 'QNTY.1',
                'Q N T Y.2': 'QNTY.2',
                'P R O D U C T': 'PRODUCT',
                'N E T': 'NET'
            })
            table = table.applymap(clean_spaces)

        elif {'NET', 'EXT'}.issubset(table.columns):
            cols = ['LN', 'QNTY.1', 'QNTY.2', 'PRODUCT', 'Unnamed: 1', 'EXT', 'ENSION']
            table = table[cols]
            table = table.rename(columns={'EXT': 'NET', 'ENSION': 'EXTENSION'})
        else:
            cols = ['LN', 'QNTY.1', 'QNTY.2', 'PRODUCT', 'Unnamed: 1', 'NET', 'ENSION']
            table = table[cols]
            table = table.rename(columns={'ENSION': 'EXTENSION'})

    table = table.rename(
        columns={
            'LN': 'Line', 'PRODUCT': 'Item', 'QNTY.1': 'Qty',
            'QNTY.2': 'Qty BO', 'Unnamed: 1': 'Description',
            'NET': 'Cost', 'EXTENSION': 'Amount'
        })

    if page == 1:
        # Dismiss columns before the first index in line
        starting_position = table.loc[table['Line'] != np.nan].index[0]
        table = table[starting_position:].reset_index(drop=True)

    table['Qty BO'] = table['Qty BO'].fillna(0)

    bo_line_mapping = pd.Series(table['Qty BO'].values, index=table['Line']).to_dict()
    try:
        bo_line_mapping = {
            k: bo_line_mapping[k] for k in bo_line_mapping if not np.isnan(k)
        }
    except TypeError:
        bo_line_mapping = {
            k: v for k, v in bo_line_mapping.items() if not pd.isna(k)
        }

    # Join rows where there is nothing in LN column but value in Description
    table['Line'] = table['Line'].fillna(method="ffill")

    table['Description'] = ' ' + table['Description'].astype(str)

    table = table[["Line", "Item", "Qty", "Description", "Cost", "Amount"]]

    agg_func = {
        'Item': 'first',
        'Qty': 'first',
        'Description': lambda x: ' '.join(x.dropna()),
        'Cost': 'first',
        'Amount': 'first'
    }

    if '-1' not in table["Qty"].values:
        table = table.dropna(subset=['Line'])
        table = table.groupby('Line').agg(agg_func).reset_index()
        # table = table.groupby('Line').sum().reset_index()
    else:
        # table = table.drop(table.index[:, int(list(bo_line_mapping.keys())[0])], inplace=True)
        # table = table.groupby('Line')
        table = table.dropna(subset=['Line'])

    table = table.groupby('Line').agg(agg_func).reset_index()

    # for merging descriptions found on multiple lines
    # indices = list(table.index.values)
    # for row in range(indices[0],len(table)):
    #     if row != indices[0] and table['Line'][row] == table['Line'][row-1] and row in indices:
    #         updated_description = table['Description'][row - 1]+table['Description'][row]
    #         table.loc[row - 1,'Description'] = updated_description
    #         # table.drop(row)
    #         # table = table.dropna(how='all')
    #         updated_description = ""
    if table.empty:
        return table

    table = table[table['Item'].notna()]

    if not table.empty:
        table['Qty BO'] = list(bo_line_mapping.values())

        try:
            table['Qty'] = table['Qty'].astype(int)
        except OverflowError:  # tabula bug reading all entries in a column as a single entry
            table['Qty'] = table['Qty'].astype(np.int64)
        except ValueError:
            table['Qty'] = table['Qty'].astype(float)

        table['Qty BO'].replace([''], 0, inplace=True)
        table['Qty BO'] = table['Qty BO'].astype(float)
        table['Cost'] = table['Cost'].apply(
            lambda cost: float(re.sub(r"[^0-9.]", "", str(cost))))

        if (not isinstance(table['Amount'], np.floating)
                and isinstance(table['Amount'], str)):
            # if not already float only then we need to process as follows {*WWPS Patch}

            # fix for values like $45.2..$65
            table['Amount'] = [
                value.split("..", 1)[0] if ".." in value else value
                for value in table['Amount'].values
            ]
            table['Amount'] = (
                table['Amount'].astype(str)
                .str.replace(',', '')
                .str.replace('$', '')
                .astype(float)
            )

        table['Description'] = table['Description'].str.strip()

        return table
    return None


def split_multiple_invoices(filename, supplier):
    # will contain paths for newly generated pdf's after splitting
    splited_file_paths = []

    unique_invoices = []
    if supplier == 'Supreme Plumbing Supply':
        with fitz.open(filename) as doc:
            for page in doc:
                text = page.get_text()
                invoice_data = text.split("Invoice", 1)
                invoice_data = invoice_data[1].split("\n", 1)
                invoice_data = invoice_data[0]
                if 8 < len(invoice_data) < 14:
                    unique_invoices.append(invoice_data)

    elif supplier == 'AF Supply':
        with fitz.open(filename) as doc:
            for page in doc:
                text = page.get_text()
                invoice_data = text.split("INVOICE NO.", 1)
                invoice_data = invoice_data[1].split("\n", 2)
                invoice_data = invoice_data[1]
                if 8 < len(invoice_data) < 14:
                    unique_invoices.append(invoice_data)

    elif supplier == 'Plumbing Exchange':
        with fitz.open(filename) as doc:
            for page in doc:
                try:
                    text = page.get_text()
                    invoice_num = text.split('mpip01', 1)[-1].split('\n \n', 2)[1].strip()
                except:  # noqa: E722
                    continue
                if len(invoice_num) >= 5:
                    unique_invoices.append(invoice_num)

    elif supplier == 'Lion Hvac Supplies':
        with fitz.open(filename) as doc:
            for page in doc:
                try:
                    text = page.get_text()
                    invoice_num = (
                        text.split('Invoice #:', 1)[-1]
                        .split('\n', 2)[0]
                        .strip()
                    )
                except:  # noqa: E722
                    continue
                if len(invoice_num) >= 5:
                    unique_invoices.append(invoice_num)

    elif supplier == "Ferguson":
        unique_invoices = extract_invoice_info(filename, 'all', True, "Ferguson")
    else:
        unique_invoices = extract_invoice_info(filename, 'all', True)

    # adding break statement here
    if len(set(unique_invoices)) == 1:
        return  # dont do anything if there is only one unique invoice id

    input_pdf = PdfReader(open(filename, "rb"))
    output = PdfWriter()
    for index in range(len(input_pdf.pages)):

        if index == 0:  # its first page, so always add it
            output.add_page(input_pdf.pages[index])
        # multiple pages of same invoice
        elif unique_invoices[index] == unique_invoices[index - 1]:
            output.add_page(input_pdf.pages[index])
        # new invoice is found
        elif unique_invoices[index] != unique_invoices[index - 1]:
            # generate pdf for previous invoice
            splited_file_paths.append(save_splited_invoice(output, index - 1, filename))
            # start preparing new invoice
            output = PdfWriter()
            output.add_page(input_pdf.pages[index])
        # if its the last page add it to pdf anyways
        if index == (len(unique_invoices) - 1):
            splited_file_paths.append(save_splited_invoice(output, index, filename))
    return splited_file_paths


def save_splited_invoice(output, index, filename):
    # output will contain the page/s of same invoice
    if '.pdf' in filename:
        filename = filename.split('.pdf', 1)
    elif '.PDF' in filename:
        filename = filename.split('.PDF', 1)

    output_filename = filename[0] + "split-invoice %s.pdf" % index
    with open(output_filename, "wb") as outputStream:
        output.write(outputStream)
    return str(output_filename)


def concatenate_splited_files(input_splitFile_path, output_splited_filepath):
    # Read the Excel file
    try:
        concatenated_df = pd.read_excel(output_splited_filepath)
        # Drop the header row safely
        if not concatenated_df.empty:
            concatenated_df = concatenated_df.iloc[1:]
        # Clean up files
        if os.path.exists(output_splited_filepath):
            # os.remove(output_splited_filepath)  # delete splited excel file
            if os.path.exists(input_splitFile_path):
                # Delete splited pdf file
                os.remove(input_splitFile_path)
        return concatenated_df
    except Exception as e:
        err_msg = (
            f"Error processing split file {output_splited_filepath}: "
            f"{str(e)}"
        )
        print(err_msg)
        # Return empty DataFrame on error
        return pd.DataFrame()


def get_files_from_folder(folderPath):
    # function to return all files present within a directory
    # utilized in folder flow V2
    file_paths = [
        join(folderPath, file) for file in listdir(folderPath)
        if isfile(join(folderPath, file)) and ".xlsx" not in file
    ]
    file_paths = [path.replace('\\', '/') for path in file_paths]
    return file_paths
