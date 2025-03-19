import tabula
import pandas as pd
import fitz
import re
import warnings
import numpy as np
from mpi_backend.utils.pdf_to_excel.formatting_util import save_opus_services

# Suppress FutureWarnings
warnings.simplefilter(action='ignore', category=FutureWarning)

def process_invoice(filename, output_path):
    try:
        tables = tabula.read_pdf(filename, pages="all", stream=True)
        cleaned_desc = clean_descriptions(tables)

        if not cleaned_desc:
            raise ValueError("No valid tables found in PDF")

        cleaned_desc = merge_descriptions(cleaned_desc)
        desc_with_header = generate_headers(cleaned_desc)
        extracted_data = extract_overtime(desc_with_header)
        extracted_data = extract_date_invoicenum(tables[0], extracted_data)
        extracted_data = extract_total_amount(filename, extracted_data)
        extracted_data = add_adress_section(extracted_data)
        extracted_data.insert(0, 'Blank', "")

        save_opus_services(extracted_data, output_path)
        return extracted_data

    except Exception as e:
        raise RuntimeError(f"PDF processing failed: {str(e)}") from e


def add_adress_section(descriptions):
    address_cols = {str(i): '' for i in range(1, 13)}
    descriptions = descriptions.assign(**address_cols)

    address_header_indices = descriptions[
        descriptions.Description.map(
            lambda x: isinstance(x, str) and ('name' in x.lower() or x.lower() == '')
        )
    ].index.tolist()

    for index in address_header_indices:
        descriptions.loc[index, '2'] = "Address 1"
        descriptions.loc[index, '3'] = "Date / Section"
        descriptions.loc[index, '4'] = "Amount"
        descriptions.loc[index, '6'] = "Address 2"
        descriptions.loc[index, '7'] = "Date / "
        descriptions.loc[index, '8'] = "Amount"
        descriptions.loc[index, '10'] = "Address 3"
        descriptions.loc[index, '11'] = "Date / "
        descriptions.loc[index, '12'] = "Amount"

    return descriptions


def cast_numerals_in_strings(description):
    description['Qty']= description['Qty'].astype(str)
    description['Rate']= description['Rate'].astype(str)
    description['Amount']= description['Amount'].astype(str)
    return description


def extract_total_amount(filename, descriptions):
    data = fitz.open(filename)
    invoice_data = data[len(data)-1] # extracting total from last page
    invoice_data = invoice_data.get_text()
    invoice_data = invoice_data.split("$", 1)
    total_amount = invoice_data[1].split("\n", 1)[0]

    descriptions.loc[len(descriptions)] = ["", "", "", "", ""]
    descriptions.loc[len(descriptions)] = ["", "", "", "Total", "$" +str(total_amount)]
    return descriptions


def extract_date_invoicenum(table, descriptions):
    descriptions.loc[-1] = ["","", "", "", ""]
    descriptions.index = descriptions.index + 1

    descriptions.loc[-1] = [table['Date'][0], table['Invoice #'][0], "", "", ""]
    descriptions.index = descriptions.index + 1

    descriptions.loc[-1] = ["Date", "Invoice #", "", "", ""]
    descriptions.index = descriptions.index + 1

    descriptions.loc[-1] = ["", "", "", "", ""]
    descriptions.index = descriptions.index + 1

    descriptions.sort_index(inplace=True)

    return descriptions


def extract_overtime(descriptions):
    overtime = []
    for row_index, description in descriptions['Description'].items():
        splits = ["", "", ""]
        if description not in ('Name', 'OVERTIME') and '/' not in str(description) and description != "":
            splits = re.split(r'(\d+)', str(description), maxsplit=1)
            descriptions.loc[row_index, 'Description'] = splits[0]
        elif description == 'Name':
            splits[1] = 'Timetable'

        if "Bonus" in str(description):
            descriptions.loc[row_index, 'Description'] = re.split(r'Bonus', str(description), maxsplit=1)[0]
            overtime.append("Bonus Check")
            continue

        overtime.append(splits[-2] + splits[-1] if len(splits) > 2 else "")

    descriptions.insert(1, "Timetable", overtime)
    return descriptions


def generate_headers(descriptions):
    # getting mapped months from project description
    billing_months = descriptions['Description'].apply(map_dates)
    billing_months = billing_months[billing_months.apply(len)>0].tolist()
    billing_months = [month for month_list in billing_months for month in month_list]

    # getting row indices where header needs to be places
    header_indices = descriptions.index[descriptions['Qty'].isnull().values].tolist()

    counter=0
    header = ['Name','Qty','Rate','Amount']
    empty_row = ['','','','']
    for index,_ in zip(header_indices,billing_months):
        if not "Mid- " in descriptions['Description'][index]:
            billing_months.append(0)
            continue
        date = re.search(r'\d+',str(descriptions['Description'][index])).group()
        descriptions.loc[index,'Description'] = f"{billing_months[counter]}/{date}/2022"
        descriptions.loc[index, 'Qty'] = ''
        descriptions.loc[index, 'Rate'] = ''
        descriptions.loc[index, 'Amount'] = ''
        descriptions.loc[index + 0.5] = header  # :)
        if counter >= 1:
            # add empty rows except the first occurrence of header
            descriptions.loc[index - 0.8] = empty_row
            descriptions.loc[index - 0.9] = empty_row
        counter += 1
    descriptions = descriptions.sort_index().reset_index(drop=True)

    # adding two empty rows before header

    return descriptions


def map_dates(col):
    months_dict = {'01': 'January',
                   '02': 'February',
                   '03': 'March',
                   '04': 'April',
                   '05': 'May',
                   '06': 'June',
                   '07': 'July',
                   '08': 'August',
                   '09': 'September',
                   '10': 'October',
                   '11': 'November',
                   '12': 'December'	}
    mapped_months = [keys for keys, values in months_dict.items() if values in col]
    return mapped_months


def merge_descriptions(descriptions):
    return pd.concat(descriptions, axis=0).reset_index(drop=True)


def clean_descriptions(tables):
    cleaned_tables = []

    for index, table in enumerate(tables):
        if index % 2 == 0:
            continue

        if {'P.O. No.','Terms','Due Date','Account #','Project'}.issubset(table.columns):
            table = table[['P.O. No.', 'Due Date', 'Account #', 'Project']]
            table = table.rename(
                columns={'P.O. No.': 'Description', 'Due Date': 'Qty',
                         'Account #': 'Rate', 'Project': 'Amount'
                         })
            table = table.iloc[2:]
            cleaned_tables.append(table)
            continue

        if index == len(tables) - 1 or ('Unnamed: 1' in table.columns and not table['Unnamed: 1'].isnull().all()):  # different pattern for last table
            if 'Unnamed: 0' in table.columns and table['Unnamed: 0'].isnull().all():
                qty_column = 'Due Date'
            else:
                qty_column = 'Unnamed: 1'

            table = table[['P.O. No. Terms', qty_column, 'Account #', 'Project']]
            table = table.rename(
                columns={'P.O. No. Terms': 'Description', qty_column: 'Qty',
                         'Account #': 'Rate', 'Project': 'Amount'
                         })
            table = table.iloc[2:]
            cleaned_tables.append(table)

        elif index % 2 != 0:  # descriptions are at odd table indices
            table = table[['P.O. No. Terms', 'Due Date', 'Account #', 'Project']]
            table = table.rename(
                columns={'P.O. No. Terms': 'Description', 'Due Date': 'Qty',
                         'Account #': 'Rate', 'Project': 'Amount'
                         })
            table = table.iloc[2:]
            cleaned_tables.append(table)

    return cleaned_tables
