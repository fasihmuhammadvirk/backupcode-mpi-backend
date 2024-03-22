# the file will be responsible to read all the converted excel files, map their items, descriptions and customer jobs
# and store them in database.
import pandas as pd
from datetime import datetime

from mpi_backend.database import get_db
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers import InvoiceController,InvoiceItemController,SupplierController
from contextlib import contextmanager

db = contextmanager(get_db)


def process_extracted_data(event):
    converted_files, failed_files = event.retval
    lookup_file = pd.read_excel(f'{INVOICE_DOWNLOAD_FOLDER}/Lookup Sheet.xlsx',
                                sheet_name=[0, 1, 2])
    temp_items = lookup_file[0]
    item_mappings = lookup_file[1]
    customer_job_mappings = lookup_file[2]

    for file in converted_files:
        extracted_data = pd.read_excel(file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))
        extracted_data.insert(0, 'Sheet Name', '')
        extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings,), axis=1)

        extracted_customer_job = extracted_data['Customer Job'][0]
        extracted_data['Customer Job'] = get_updated_customer_job(extracted_customer_job, customer_job_mappings)

        extracted_data = extracted_data.fillna({'Qty': 0, 'Cost': 0, 'Class': '', 'Memo': '', 'Ref NO': '',
                                                'PO #': '', 'Customer Job': '', 'Buyer': ''})

        supplier_id = SupplierController(db).get_supplier_id(extracted_data['Vendor'][0])

        invoice_record = InvoiceController(db).insert_invoice(extracted_data['Date'][0], file.rsplit('/')[-1],
                                             supplier_id, 'PROCESSED',
                                             file)  # one record for every file in invoices table

        for index, row in extracted_data.iterrows():  # every item has its own record
            InvoiceItemController(db).insert_invoice_items(row, file.rsplit('/')[-1], invoice_record.id)

    for file in failed_files:
        InvoiceController(db).insert_invoice(datetime.now().strftime('%m/%d/%Y'), file.rsplit('/')[-1], '', 'FAILED', file)


def search_replace(row, temp_items, item_mappings):
    item = row['Item']
    description = row['Description']

    # Searching in temp_items
    temp_match = temp_items[temp_items['Original Item Number'] == item]
    if not temp_match.empty:
        row['Item'] = temp_match.iloc[0]['Temporary Item Number']
        row['Description'] = temp_match.iloc[0]['Description']
        row['Sheet Name'] = ''
        return row

    # Searching in item_mappings
    for column in item_mappings.columns:
        mapping_match = item_mappings[item_mappings[column] == item]
        if not mapping_match.empty:
            row['Item'] = mapping_match.iloc[0]['MPI']
            row['Description'] = mapping_match.iloc[0]['Description']
            sheet_name = mapping_match.iloc[0]['Google Sheet Name']
            row['Sheet Name'] = sheet_name
            return row
    return row


def get_updated_customer_job(customer_job, customer_job_mappings):
    updated_job = ''
    filtered_df = customer_job_mappings[customer_job_mappings['Customer Job'] == customer_job]

    if not filtered_df.empty:
        updated_job = filtered_df.iloc[0]['Updated Customer Job']

    return updated_job
