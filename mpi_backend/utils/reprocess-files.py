from mpi_backend.database.controllers import SupplierController, InvoiceController, InvoiceItemController
from mpi_backend.database.models import Invoice, InvoiceItem
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers import ItemsMappingController,TempItemsMappingController,UnmappedItemsController
from mpi_backend.utils.invoice_convertor import convert_invoice
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.s3_utils import get_presigned_url
from mpi_backend.database import get_db
from contextlib import contextmanager
import re
from datetime import datetime
import os
import pandas as pd
import uuid
from mpi_backend.utils.item_utils import clean_supplier_suffix


db = contextmanager(get_db)
def find_pdf_files(directory):
    xlsx_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".pdf") or file.endswith(".PDF"):
                # Get the full file path
                full_path = os.path.join(root, file)
                if full_path.count(os.sep) > 3:
                    xlsx_files.append(full_path)

    return xlsx_files

def check_empty_mpi_item_and_description(invoice_items):
    # Check if any object has both mpi_item and mpi_description as empty strings
    return any(item.mpi_item == '' and item.mpi_description == '' for item in invoice_items)

directory_path = "mpi_backend\\storage"
xlsx_files = find_pdf_files(directory_path)
print (f'Found {len(xlsx_files)} invoices.')

invoice_ids = []

def process_extracted_data(converted_files, id):

    db = contextmanager(get_db)

    temp_items = TempItemsMappingController(db).get_temp_items_mappings()
    item_mappings = ItemsMappingController(db).get_items_mappings()

    for file in converted_files:
        extracted_data = pd.read_excel(file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))


        if InvoiceItemController(db).invoice_exists(str(extracted_data['Ref NO'][0]),str(extracted_data['Vendor'][0])) :
            print(f'Invoice with REF-NO-> {str(extracted_data["Ref NO"][0])} already processed and is being skipped!')
            continue

        extracted_data.insert(0, 'Sheet Name', '')
        extracted_data['MpiItem'] = 'No Match'
        extracted_data['MpiDescription'] = 'No Match'
        extracted_data['email_date'] = extract_email_date(file)

        extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings,), axis=1)

        extracted_customer_job = extracted_data['Customer Job'][0]
        extracted_data['Customer Job'] = extracted_customer_job

        extracted_data = extracted_data.fillna({'Qty': 0, 'Cost': 0, 'Class': '', 'Memo': '', 'Ref NO': '',
                                                'PO #': '', 'Customer Job': '', 'Buyer': '',
                                                'Date': datetime.today().strftime('%m/%d/%Y')})

        for index, row in extracted_data.iterrows():  # every item has its own record
            InvoiceItemController(db).insert_invoice_items(row, file.rsplit('/')[-1], id)


def extract_email_date(path):
    date_pattern = re.compile(r'\b\d{1,2}-\d{1,2}-\d{4}\b')
    match = date_pattern.search(path)

    if match:
        extracted_date = match.group()
        date_obj = datetime.strptime(extracted_date, '%m-%d-%Y')
    else:
        date_obj = datetime.today()

    # Convert the date to "year-month-day" format
    formatted_date = date_obj.strftime('%Y-%m-%d')
    return formatted_date


def search_replace(row, temp_items, item_mappings):
    """
    Search for item mappings with supplier-specific suffix cleaning.
    Maps original_item (supplier_item_ids) to mpi_code.
    
    Note: Invoice data is clean, but database mapping data has suffixes that need cleaning.
    """
    original_item = row['Item']  # This is the CLEAN supplier_item_ids from invoice
    supplier_id, _ = extract_supplier_id(row['Vendor'])
    
    # Searching in temp_items (temporary_item_mappings table)
    # First try exact match with clean invoice item
    temp_match = temp_items[temp_items['original_item_number'] == original_item]
    
    # If no exact match and we have supplier_id, clean the DB data and compare with clean invoice item
    if temp_match.empty and supplier_id:
        temp_match = temp_items[
            temp_items['original_item_number'].apply(lambda x: clean_supplier_suffix(x, supplier_id)) == original_item
        ]
    
    if not temp_match.empty:
        row['MpiItem'] = temp_match.iloc[0]['temporary_item_number']  # This is the mpi_code
        row['MpiDescription'] = temp_match.iloc[0]['description']
        row['Sheet Name'] = ''
        return row

    # Searching in item_mappings (supplier_item_mappings table)
    # Only compare against supplier_item_ids column (not all columns)
    if 'supplier_item_ids' in item_mappings.columns:
        # First try exact match with clean invoice item
        mapping_match = item_mappings[item_mappings['supplier_item_ids'] == original_item]
        
        # If no exact match and we have supplier_id, clean the DB mapping data and compare with clean invoice item
        if mapping_match.empty and supplier_id:
            mapping_match = item_mappings[
                item_mappings['supplier_item_ids'].apply(lambda x: clean_supplier_suffix(x, supplier_id)) == original_item
            ]
        
        if not mapping_match.empty:
            row['MpiItem'] = mapping_match.iloc[0]['mpi_code']  # This is the target mpi_code
            row['MpiDescription'] = mapping_match.iloc[0]['description']
            sheet_name = mapping_match.iloc[0]['google_sheet_name']
            row['Sheet Name'] = sheet_name
            return row

    # will only be triggered if no mapping is found
    if not UnmappedItemsController(db).is_item_code_present(row['Item'], supplier_id):
        UnmappedItemsController(db).insert_unmapped_item(row['Item'],row['Description'],supplier_id)

    return row

def extract_supplier_id(file_path):
    company_codes = {
        "BMW Plumbing Supplies": 1,
        "World Wide Plumbing": 2,
        "Y & S Plumbing Supply": 3,
        "Supreme Plumbing Supply": 4,
        "Pyramid Plumbing": 5,
        "ABC Opus Services": 6,
        "Park Plumbing Supply": 7,
        "Gotham Plumbing Supply": 8,
        "FW Webb Plumbing Supply": 9,
        "Flow Mark Plumbing Supply": 10
    }
    for company, code in company_codes.items():
        if company in file_path:
            return code, company
    return 1 # need to return some default supplier


reprocessed = 0
with db() as db:
    for invoice in xlsx_files:
        filename = os.path.basename(invoice)
        matched_invoice = db.query(Invoice).filter_by(filename=filename).first()

        if not matched_invoice: continue
        invoice_id = str(matched_invoice.id)


        invoice_items = InvoiceItemController(db).get_invoice_items(invoice_id=invoice_id)

        if check_empty_mpi_item_and_description(invoice_items): # any one record is empty, process them again
            InvoiceItemController(db).delete_invoice_items(invoice_id, db)  # delete previous ingested invoice items
            contents = pd.read_excel(invoice.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))
            process_extracted_data([invoice.replace("\\", "/")], uuid.UUID(invoice_id))

            reprocessed +=1
            invoice_ids.append(invoice_id)

print(f'reprocessed {reprocessed} invoices.')
print('\n')
print(invoice_ids)
