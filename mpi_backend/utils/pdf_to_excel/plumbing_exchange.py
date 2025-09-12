import tabula
import pandas as pd
import fitz
import re
from datetime import datetime
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data, save_final_data_for_database


invoice_items_area = (218.27,34.83,218.27+502.48,34.83+539.13)
customer_job_area = (118.41,418.90,118.41+39.32,418.90+97.23)
tax_area = (750,430,750+16.56,430+140.28)
columns = [63.28,105.22,147.65,190.14,392.59,434.35,477.57,516.70,574.17]


def process_invoice(filename, output_path):
    tables = tabula.read_pdf(filename, pages='all', area=invoice_items_area, guess=True, stream=False)
    invoice_items = clean_invoice_items(tables,filename)

    raw_text = fitz.open(filename)
    raw_text = raw_text[0].get_text()

    customer_job = extract_customer_job(filename)
    ref_no = extract_invoice_num(raw_text)
    date = extract_date(raw_text)
    po_no = extract_po(filename)
    tax = extract_tax(filename)

    tax = float(tax.replace("$", "").replace(",", "").replace("-",""))

    result = process_results(invoice_items, date, ref_no, tax, customer_job, po_no)
    save_final_data_for_database(result, "Plumbing Exchange", output_path)


def process_results(invoice_items, date, invoice_no, tax, job_name="", po_no=""):
    results = invoice_items
    tax_row = ["10 Materials", "Tax", "", "", float(tax)]
    results.loc[len(results)] = tax_row
    results["Date"] = date
    results["Ref NO"] = str(invoice_no)  # Ensure reference number is stored as string to preserve leading zeros
    results["PO #"] = po_no
    results['Customer Job'] = job_name
    results["Bill"] = "Bill"
    results["Vendor"] = "Plumbing Exchange"
    results["Class"] = ""
    results["Memo"] = ""
    results["Buyer"] = ""
    return results




def extract_tax(filename):
    table = tabula.read_pdf(filename, pages='all', area=tax_area, guess=True, stream=False)
    return table[0].columns.values[-1]


def extract_po(filename):
    table =  tabula.read_pdf(filename, guess=True, stream=False)
    po_num = str(table[0]['P O  #'][0])
    if po_num =='nan': po_num = ''
    return po_num


def extract_date(text):
    date = text.split('mpip01',1)[-1].split('\n \n',3)[2].strip()
    date = datetime.strptime(date, '%b %d %Y').strftime('%m/%d/%Y')
    return date


def extract_invoice_num(text):
    invoice_num = text.split('mpip01',1)[-1].split('\n \n',2)[1].strip() # splitting by account name, which is unlikely to change
    return invoice_num



def extract_customer_job(filename):
    table= tabula.read_pdf(filename, area=customer_job_area, guess=True, stream=False)
    return table[0].columns.values[0]

def clean_invoice_items(tables,filename):
    invoice_items = []
    for table in tables:

        if {'Unnamed: 0', 'Unnamed: 1', 'Unnamed: 2'}.issubset(table.columns.values):
            table.columns = table.iloc[0]
            table = table[1:].reset_index(drop=True) # making first row header

            description_index = table.columns.get_loc('DESCRIPTION')  # get col after description and if its not null name it to Item
            column_after_description = table.columns[description_index + 1]
            try:
                if table[column_after_description].notna().any():
                    table.rename(columns={column_after_description: 'Item'}, inplace=True)
            except:
                table = tabula.read_pdf(filename, pages='all', area=invoice_items_area, columns=columns, guess=True,
                                        stream=False)[0]
                table.columns = table.iloc[0]
                table = table[1:].reset_index(drop=True)

        if {'DISCOUNT UNIT'}.issubset(table.columns.values):
            table = tabula.read_pdf(filename, pages='all', area=invoice_items_area,columns=columns, guess=True, stream=False)[0]
            table.columns = table.iloc[0]
            table = table[1:].reset_index(drop=True)  # making first row header

        if not {'Item'}.issubset(table.columns.values):
            table['Item'] = table['DESCRIPTION'].str.split().str[-1]

        if {'SHIP', 'ORDER'}.issubset(table.columns.values) and table['SHIP'].isnull().all():
            table.drop('SHIP', axis=1,inplace=True)
            table.rename(columns={'ORDER':'SHIP'},inplace=True)  # ship column could not be picked up using order col instead

        table = table[['Item','DESCRIPTION', 'SHIP','UNIT','AMOUNT']]
        table = table.rename(columns={'DESCRIPTION':'Description', 'SHIP':'Qty', 'UNIT':'Cost', 'AMOUNT':'Amount'})
        table['Description'] = table['Description'].str.split(r'\s{4,}').str[0] # remove everything after multiple spaces

        table.dropna(subset=['Qty', 'Description', 'Cost', 'Amount'], inplace=True)
        table['Amount'] = table['Amount'].astype(str).str.replace(',', '').str.replace('-', '').str.replace('$', '').astype(float)
        table['Cost'] = table['Cost'].astype(str).str.replace(',', '').str.replace('-', '').str.replace('$', '').astype(float)
        table['Qty'] = table['Qty'].astype(str).str.replace(',', '').str.replace('-', '').astype(float)
        table['Qty'] = table['Qty'].astype(int)

        invoice_items.append(table)

        combined_invoice_items = pd.DataFrame()
        for item in range(len(invoice_items)):
            combined_invoice_items = pd.concat([combined_invoice_items, invoice_items[item]], axis=0)
        combined_invoice_items.reset_index(drop=True, inplace=True)

        return combined_invoice_items
