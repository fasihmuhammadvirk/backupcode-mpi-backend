# the file will be responsible to read all the converted excel files, map their items, descriptions and customer jobs
# and store them in database.
import pandas as pd
from datetime import datetime

from mpi_backend.database import get_db
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers import InvoiceController,InvoiceItemController,SupplierController,ItemsMappingController,TempItemsMappingController,CustomerJobMappingController
from contextlib import contextmanager
from mpi_backend.utils.s3_utils import upload_file,get_presigned_url

db = contextmanager(get_db)


def process_extracted_data(converted_files, failed_files):

    temp_items = TempItemsMappingController(db).get_temp_items_mappings()
    item_mappings = ItemsMappingController(db).get_items_mappings()
    customer_job_mappings = CustomerJobMappingController(db).get_customer_job_mappings()

    for file in converted_files:
        extracted_data = pd.read_excel(file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))

        supplier_id = SupplierController(db).get_supplier_id(extracted_data['Vendor'][0])
        invoice_record = InvoiceController(db).insert_invoice(extracted_data['Date'][0], file.rsplit('/')[-1],
                                                              supplier_id, 'PROCESSING',
                                                              file)  # one record for every file in invoices table

        extracted_data.insert(0, 'Sheet Name', '')
        extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings,), axis=1)

        extracted_customer_job = extracted_data['Customer Job'][0]
        extracted_data['Customer Job'] = get_updated_customer_job(extracted_customer_job, customer_job_mappings)

        extracted_data = extracted_data.fillna({'Qty': 0, 'Cost': 0, 'Class': '', 'Memo': '', 'Ref NO': '',
                                                'PO #': '', 'Customer Job': '', 'Buyer': ''})

        InvoiceController(db).set_status_to_processed(invoice_record.id) # invoice has processed, change its status accordingly
        upload_file(file_name=file, file_key=f'{extracted_data["Vendor"][0]}/{invoice_record.id}')

        for index, row in extracted_data.iterrows():  # every item has its own record
            InvoiceItemController(db).insert_invoice_items(row, file.rsplit('/')[-1], invoice_record.id)

    for file in failed_files:
        invoice_record = InvoiceController(db).insert_invoice(datetime.now().strftime('%m/%d/%Y'), file.rsplit('/')[-1], '', 'FAILED', file)
        upload_file(file_name=file, file_key=invoice_record.id)


def search_replace(row, temp_items, item_mappings):
    item = row['Item']
    description = row['Description']

    # Searching in temp_items
    temp_match = temp_items[temp_items['original_item_number'] == item]
    if not temp_match.empty:
        row['Item'] = temp_match.iloc[0]['temporary_item_number']
        row['Description'] = temp_match.iloc[0]['description']
        row['Sheet Name'] = ''
        return row

    # Searching in item_mappings
    for column in item_mappings.columns:
        mapping_match = item_mappings[item_mappings[column] == item]
        if not mapping_match.empty:
            row['Item'] = mapping_match.iloc[0]['mpi_code']
            row['Description'] = mapping_match.iloc[0]['description']
            sheet_name = mapping_match.iloc[0]['google_sheet_name']
            row['Sheet Name'] = sheet_name
            return row
    return row


def get_updated_customer_job(customer_job, customer_job_mappings):
    updated_job = ''
    filtered_df = customer_job_mappings[customer_job_mappings['customer_job'] == customer_job]

    if not filtered_df.empty:
        updated_job = filtered_df.iloc[0]['updated_customer_job']

    return updated_job
