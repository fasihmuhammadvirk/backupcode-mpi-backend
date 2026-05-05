import tabula
import pandas as pd
import fitz
import re
import numpy as np
from .formatting_util import save_opus_services
from datetime import datetime
# from formatting_util import save_opus_services


def process_invoice(filename, output_path):
    tables = tabula.read_pdf(filename, pages="all", stream=True)
    cleaned_desc = clean_descriptions(tables)
    cleaned_desc = merge_descriptions(cleaned_desc)
    desc_with_header = generate_headers(cleaned_desc)
    extracted_data = extract_overtime(desc_with_header)
    extracted_data = extract_date_invoicenum(tables[0],extracted_data)
    extracted_data = extract_total_amount(filename,extracted_data)
    extracted_data = add_adress_section(extracted_data)

    extracted_data.insert(0, 'Blank', "") # new column at start for better formatting
    # extracted_data = cast_numerals_in_strings(extracted_data)

    save_opus_services(extracted_data,output_path)
    pass


def add_adress_section(descriptions):
    descriptions = descriptions.assign(**{'1':'','2':'','3':'','4':'','5':'','6':'','7':'','8':'','9':'','10':''
                                          ,'11':'','12':''}) # 13 cols required are required for address details

    address_header_indices = descriptions[
        descriptions.Description.map(
            lambda x: True if isinstance(x, str) and 'name' in x.lower() or x.lower() == '' else False)].index.to_list()

    for index in address_header_indices:
        descriptions['2'][index] = "Address 1"
        descriptions['3'][index] = "Date / Section"
        descriptions['4'][index] = "Amount"

        descriptions['6'][index] = "Address 2"
        descriptions['7'][index] = "Date / "
        descriptions['8'][index] = "Amount"

        descriptions['10'][index] = "Address 3"
        descriptions['11'][index] = "Date / "
        descriptions['12'][index] = "Amount"

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
    overtime =[]
    for row_index,description in descriptions['Description'].iteritems():
        splits = ["", "", ""]
        if description != 'Name' and description!= 'OVERTIME' and '/' not in description and description != "": # verifying it's not header/empty row
            splits = re.split(r'(\d+)', description,maxsplit=1)
            descriptions['Description'][row_index] = splits[0]
        elif description == 'Name':
            splits[1] = 'Timetable'

        if "Bonus" in description: # some columns have bonus instead of overtime
            descriptions['Description'][row_index] = re.split(r'Bonus', description, maxsplit=1)[0]
            overtime.append("Bonus Check")
            continue

        overtime.append(splits[-2] + splits[-1])

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
        descriptions.loc[index,'Description'] = f"{billing_months[counter]}/{date}/{str(datetime.now().year)}"
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
            if 'Unnamed: 0' in table.columns and table['Unnamed: 0'].isnull().all() and 'Unnamed: 1' not in table.columns:
                qty_column = 'Due Date'
            elif 'Unnamed: 0' in table.columns and table['Unnamed: 0'].isnull().all() and table['Unnamed: 1'].isnull().all():
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


# if __name__ == '__main__':
#     process_invoice(r"C:\Users\lenovo\Desktop\Neural Lines\invoices_pdf_to_excel\PDF's\Junk Workspace\template.pdf",
#                     r"C:\Users\lenovo\Desktop\Neural Lines\invoices_pdf_to_excel\PDF's\Junk Workspace\extracted.xlsx")
