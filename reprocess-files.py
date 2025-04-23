# from mpi_backend.database.controllers import SupplierController, InvoiceController, InvoiceItemController
# from mpi_backend.database.models import Invoice, InvoiceItem
# from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
# from mpi_backend.database.controllers import ItemsMappingController,TempItemsMappingController,UnmappedItemsController
# from mpi_backend.utils.invoice_convertor import convert_invoice
# from mpi_backend.utils.auth.auth_bearer import JWTBearer
# from mpi_backend.utils.s3_utils import get_presigned_url
# from mpi_backend.database import get_db
# from contextlib import contextmanager
# import re
# from datetime import datetime
# import os
# import pandas as pd
# import uuid
#
#
# db = contextmanager(get_db)
# def find_pdf_files(directory):
#     xlsx_files = []
#     for root, dirs, files in os.walk(directory):
#         for file in files:
#             if file.endswith(".pdf") or file.endswith(".PDF"):
#                 # Get the full file path
#                 full_path = os.path.join(root, file)
#                 if full_path.count(os.sep) > 3:
#                     xlsx_files.append(full_path)
#
#     return xlsx_files
#
# def check_empty_mpi_item_and_description(invoice_items):
#     # Check if any object has both mpi_item and mpi_description as empty strings
#     return any(item.mpi_item == '' and item.mpi_description == '' for item in invoice_items)
#
# directory_path = "mpi_backend/storage"
# xlsx_files = find_pdf_files(directory_path)
# print (f'Found {len(xlsx_files)} invoices.')
#
# invoice_ids = []
#
# def process_extracted_data(converted_files, id):
#
#     db = contextmanager(get_db)
#
#     temp_items = TempItemsMappingController(db).get_temp_items_mappings()
#     item_mappings = ItemsMappingController(db).get_items_mappings()
#
#     for file in converted_files:
#         extracted_data = pd.read_excel(file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))
#
#
#         if InvoiceItemController(db).invoice_exists(str(extracted_data['Ref NO'][0])) :
#             print(f'Invoice with REF-NO-> {str(extracted_data["Ref NO"][0])} already processed and is being skipped!')
#             continue
#
#         extracted_data.insert(0, 'Sheet Name', '')
#         extracted_data['MpiItem'] = 'No Match'
#         extracted_data['MpiDescription'] = 'No Match'
#         extracted_data['email_date'] = extract_email_date(file)
#
#         extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings,), axis=1)
#
#         extracted_customer_job = extracted_data['Customer Job'][0]
#         extracted_data['Customer Job'] = extracted_customer_job
#
#         extracted_data = extracted_data.fillna({'Qty': 0, 'Cost': 0, 'Class': '', 'Memo': '', 'Ref NO': '',
#                                                 'PO #': '', 'Customer Job': '', 'Buyer': '',
#                                                 'Date': datetime.today().strftime('%m/%d/%Y')})
#
#         for index, row in extracted_data.iterrows():  # every item has its own record
#             InvoiceItemController(db).insert_invoice_items(row, file.rsplit('/')[-1], id)
#
#
# def extract_email_date(path):
#     date_pattern = re.compile(r'\b\d{1,2}-\d{1,2}-\d{4}\b')
#     match = date_pattern.search(path)
#
#     if match:
#         extracted_date = match.group()
#         date_obj = datetime.strptime(extracted_date, '%m-%d-%Y')
#     else:
#         date_obj = datetime.today()
#
#     # Convert the date to "year-month-day" format
#     formatted_date = date_obj.strftime('%Y-%m-%d')
#     return formatted_date
#
#
# def search_replace(row, temp_items, item_mappings):
#
#     item = row['Item']
#
#     # Searching in temp_items
#     temp_match = temp_items[temp_items['original_item_number'] == item]
#     if not temp_match.empty:
#         row['MpiItem'] = temp_match.iloc[0]['temporary_item_number']
#         row['MpiDescription'] = temp_match.iloc[0]['description']
#         row['Sheet Name'] = ''
#         return row
#
#     # Searching in item_mappings
#     for column in item_mappings.columns:
#         mapping_match = item_mappings[item_mappings[column] == item]
#         if not mapping_match.empty:
#             row['MpiItem'] = mapping_match.iloc[0]['mpi_code']
#             row['MpiDescription'] = mapping_match.iloc[0]['description']
#             sheet_name = mapping_match.iloc[0]['google_sheet_name']
#             row['Sheet Name'] = sheet_name
#             return row
#
#     # will only be triggered if no mapping is found
#     supplier_id, _ = extract_supplier_id(row['Vendor'])
#     if not UnmappedItemsController(db).is_item_code_present(row['Item']):
#         UnmappedItemsController(db).insert_unmapped_item(row['Item'],row['Description'],supplier_id)
#
#     return row
#
# def extract_supplier_id(file_path):
#     company_codes = {
#         "BMW Plumbing Supplies": 1,
#         "World Wide Plumbing": 2,
#         "Y & S Plumbing Supply": 3,
#         "Supreme Plumbing Supply": 4,
#         "Pyramid Plumbing": 5,
#         "ABC Opus Services": 6,
#         "Park Plumbing Supply": 7,
#         "Gotham Plumbing Supply": 8,
#         "FW Webb Plumbing Supply": 9,
#         "Flow Mark Plumbing Supply": 10
#     }
#     for company, code in company_codes.items():
#         if company in file_path:
#             return code, company
#     return 1 # need to return some default supplier
#
#
# reprocessed = 0
# with db() as db:
#     for invoice in xlsx_files:
#         filename = os.path.basename(invoice)
#         matched_invoice = db.query(Invoice).filter_by(filename=filename).first()
#
#         if not matched_invoice: continue
#         invoice_id = str(matched_invoice.id)
#
#
#         invoice_items = InvoiceItemController(db).get_invoice_items(invoice_id=invoice_id)
#
#         if check_empty_mpi_item_and_description(invoice_items): # any one record is empty, process them again
#             InvoiceItemController(db).delete_invoice_items(invoice_id, db)  # delete previous ingested invoice items
#             contents = pd.read_excel(invoice.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))
#             process_extracted_data([invoice.replace("\\", "/")], uuid.UUID(invoice_id))
#
#             reprocessed +=1
#             invoice_ids.append(invoice_id)
#
# print(f'reprocessed {reprocessed} invoices.')
# print('\n')
# print(invoice_ids)

import os
import pandas as pd
import uuid
import requests
from datetime import datetime
import logging
from mpi_backend.database import get_db
from mpi_backend.database.controllers import InvoiceItemController, InvoiceController, SupplierController
from mpi_backend.database.models import Invoice
from mpi_backend.utils.invoice_convertor import convert_invoice
from mpi_backend.utils.extracted_data_processor import process_extracted_data
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.utils.s3_utils import get_presigned_url
from contextlib import contextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def reprocess_556_jobs():
    """Reprocess all invoices that have job address containing '556'."""
    db_context = contextmanager(get_db)
    reprocessed_ids = []
    error_invoices = []
    skipped_invoices = []

    with db_context() as db:
        # Get all invoices from database
        all_invoices = db.query(Invoice).all()
        logger.info(f"Found {len(all_invoices)} total invoices in database")

        for invoice in all_invoices:
            try:
                # Get the invoice items to check job address
                invoice_items = InvoiceItemController(db).get_invoice_items(
                    invoice_id=str(invoice.id)
                )
                
                if not invoice_items:
                    logger.warning(f"No items found for invoice {invoice.id}")
                    skipped_invoices.append(str(invoice.id))
                    continue

                # Check if any item has job address 556
                has_556_job = False
                for item in invoice_items:
                    if item.customer_job and '556' in str(item.customer_job):
                        has_556_job = True
                        break

                if not has_556_job:
                    continue

                # If we found a 556 job, reprocess the entire invoice
                invoice_id = str(invoice.id)
                supplier = SupplierController(db).get_supplier_by_id(invoice.supplier_id)
                
                # Get the invoice file from S3
                invoice_url = get_presigned_url(file_key=f'{supplier}/{invoice_id}')
                
                if not invoice_url:
                    logger.error(f"Couldn't fetch invoice {invoice_id} from S3")
                    error_invoices.append(invoice_id)
                    continue
                
                # Create supplier folder if it doesn't exist
                upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/{supplier}'
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                
                # Download the invoice file
                try:
                    response = requests.get(invoice_url)
                    if response.status_code != 200:
                        logger.error(f"Failed to download invoice {invoice_id}: Status {response.status_code}")
                        error_invoices.append(invoice_id)
                        continue
                        
                    with open(os.path.join(upload_folder, invoice.filename), 'wb') as file:
                        file.write(response.content)
                except Exception as e:
                    logger.error(f"Failed to download invoice {invoice_id}: {str(e)}")
                    error_invoices.append(invoice_id)
                    continue
                
                # Delete existing invoice and items
                logger.info(f"Deleting existing invoice and items for {invoice_id}")
                InvoiceItemController(db).delete_invoice_items(invoice_id, db)
                InvoiceController(db).delete_invoice(invoice_id, db)
                
                # Convert and process the invoice
                logger.info(f"Converting and processing invoice {invoice_id}")
                converted_files, failed_files = convert_invoice(supplier)
                process_extracted_data(converted_files, failed_files)
                
                # Clean up temporary files
                files_to_remove = [f for f in os.listdir(upload_folder)]
                for filename in files_to_remove:
                    try:
                        os.remove(os.path.join(upload_folder, filename))
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {filename}: {str(e)}")
                
                reprocessed_ids.append(invoice_id)
                logger.info(f"Successfully reprocessed invoice ID: {invoice_id}")

            except Exception as e:
                logger.error(f"Error processing invoice {invoice.id}: {str(e)}")
                error_invoices.append(str(invoice.id))

    # Print summary
    logger.info("\n=== Processing Summary ===")
    logger.info(f"✅ Successfully reprocessed: {len(reprocessed_ids)} invoices")
    logger.info(f"📋 Reprocessed Invoice IDs: {reprocessed_ids}")
    
    if skipped_invoices:
        logger.info(f"⏭️  Skipped invoices: {len(skipped_invoices)}")
        logger.debug(f"Skipped invoice IDs: {skipped_invoices}")
    
    if error_invoices:
        logger.warning(f"❌ Invoices with errors: {len(error_invoices)}")
        logger.debug(f"Error invoice IDs: {error_invoices}")


if __name__ == "__main__":
    reprocess_556_jobs()
