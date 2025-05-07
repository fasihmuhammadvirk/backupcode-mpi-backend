# the file will be responsible to read all the converted excel files, map their items, descriptions and customer jobs
# and store them in database.
import pandas as pd
from datetime import datetime
import re
import logging
logger = logging.getLogger(__name__)

from mpi_backend.database import get_db
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
from mpi_backend.database.controllers import InvoiceController,InvoiceItemController,SupplierController,ItemsMappingController,TempItemsMappingController,CustomerJobMappingController,UnmappedItemsController
from contextlib import contextmanager
from mpi_backend.utils.s3_utils import upload_file,get_presigned_url

db = contextmanager(get_db)


def validate_invoice_data(data):
    """
    Validates if the invoice has all the required critical fields.
    Returns: True if all critical fields are present, False otherwise
    """
    validation_errors = []
    
    # Check for reference number
    if 'Ref NO' not in data.columns:
        validation_errors.append("Missing 'Ref NO' column")
    elif data.empty or len(data) == 0:
        validation_errors.append("Invoice data is empty")
    elif pd.isna(data['Ref NO'][0]) or str(data['Ref NO'][0]).strip() == '':
        validation_errors.append("Missing reference number value")
    
    # Check for total amount (using the sum of all line item amounts)
    if 'Amount' not in data.columns:
        validation_errors.append("Missing 'Amount' column")
    elif data['Amount'].isnull().all():
        validation_errors.append("All amount values are null")
    elif len(data['Amount']) == 0:
        validation_errors.append("No amount values found")
    
    # Check for date
    if 'Date' not in data.columns:
        validation_errors.append("Missing 'Date' column")
    elif pd.isna(data['Date'][0]) or str(data['Date'][0]).strip() == '':
        validation_errors.append("Missing date value")
    
    if validation_errors:
        for error in validation_errors:
            logger.error(f'Invoice validation failed: {error}')
        return False
    
    return True


def process_extracted_data(converted_files, failed_files):

    temp_items = TempItemsMappingController(db).get_temp_items_mappings()
    item_mappings = ItemsMappingController(db).get_items_mappings()
    customer_job_mappings = CustomerJobMappingController(db).get_customer_job_mappings()

    for file in converted_files:
        try:
            extracted_data = pd.read_excel(file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx"))
        except FileNotFoundError:
            logger.error(f'Invoice ->{file} does not exists')
            failed_files.append(file)  # Add to failed files if Excel not found
            continue

        supplier_id = SupplierController(db).get_supplier_name(extracted_data['Vendor'][0])

        if InvoiceItemController(db).invoice_exists(str(extracted_data['Ref NO'][0]),str(extracted_data['Vendor'][0])) :
            logger.warning(f'Invoice with REF-NO-> {str(extracted_data["Ref NO"][0])} already processed and is being skipped!')
            continue

        extracted_data.insert(0, 'Sheet Name', '')
        extracted_data['MpiItem'] = 'No Match'
        extracted_data['MpiDescription'] = 'No Match'
        extracted_data['email_date'] = extract_email_date(file)

        extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings,), axis=1)

        extracted_customer_job = extracted_data['Customer Job'][0]
        extracted_data['Customer Job'] = get_updated_customer_job(extracted_customer_job, customer_job_mappings)

        extracted_data = extracted_data.fillna({'Qty': 0, 'Cost': 0, 'Class': '', 'Memo': '', 'Ref NO': '',
                                                'PO #': '', 'Customer Job': '', 'Buyer': '',
                                                'Date': datetime.today().strftime('%m/%d/%Y')})

        # Create invoice record initially with PROCESSING status
        invoice_record = InvoiceController(db).insert_invoice(extracted_data['Date'][0], file.rsplit('/')[-1],
                                                              supplier_id, 'PROCESSING',
                                                              file)  # one record for every file in invoices table

        # Validate the invoice has all critical fields
        if validate_invoice_data(extracted_data):
            # Invoice valid - mark as processed
            InvoiceController(db).set_status_to_processed(invoice_record.id)
            logger.info(f'Invoice {file.rsplit("/")[-1]} marked as processed successfully')
        else:
            # Invoice invalid - mark as failed
            invoice_record.status = 'FAILED'
            with db() as session:
                invoice = session.query(InvoiceController(session).db_context.query).filter_by(id=invoice_record.id).first()
                if invoice:
                    invoice.status = 'FAILED'
                    session.commit()
            logger.warning(f'Invoice {file.rsplit("/")[-1]} marked as failed due to missing critical data')
        
        # Upload to S3 regardless of status
        upload_file(file_name=file, file_key=f'{extracted_data["Vendor"][0]}/{invoice_record.id}')

        # Store invoice items regardless of status
        for index, row in extracted_data.iterrows():  # every item has its own record
            InvoiceItemController(db).insert_invoice_items(row, file.rsplit('/')[-1], invoice_record.id)

    for file in failed_files:
        supplier_id, supplier_name = extract_supplier_id(file_path=file)
        if InvoiceController(db).is_invoice_present(file.split("/")[-1]):
            continue
        invoice_record = InvoiceController(db).insert_invoice(datetime.now().strftime('%m/%d/%Y'), file.rsplit('/')[-1], supplier_id, 'FAILED', file)
        upload_file(file_name=file, file_key=f'{supplier_name}/{invoice_record.id}')


def search_replace(row, temp_items, item_mappings):

    item = row['Item']

    # Searching in temp_items
    temp_match = temp_items[temp_items['original_item_number'] == item]
    if not temp_match.empty:
        row['MpiItem'] = temp_match.iloc[0]['temporary_item_number']
        row['MpiDescription'] = temp_match.iloc[0]['description']
        row['Sheet Name'] = ''
        return row

    # Searching in item_mappings
    for column in item_mappings.columns:
        mapping_match = item_mappings[item_mappings[column] == item]
        if not mapping_match.empty:
            row['MpiItem'] = mapping_match.iloc[0]['mpi_code']
            row['MpiDescription'] = mapping_match.iloc[0]['description']
            sheet_name = mapping_match.iloc[0]['google_sheet_name']
            row['Sheet Name'] = sheet_name
            return row

    # will only be triggered if no mapping is found
    supplier_id, _ = extract_supplier_id(row['Vendor'])
    if not UnmappedItemsController(db).is_item_code_present(row['Item']):
        UnmappedItemsController(db).insert_unmapped_item(row['Item'],row['Description'],supplier_id)

    return row


def get_updated_customer_job(customer_job, customer_job_mappings):
    updated_job = customer_job  # if no mapping is found return the extracted customer job
    filtered_df = customer_job_mappings[customer_job_mappings['customer_job'] == customer_job]

    if not filtered_df.empty:
        updated_job = filtered_df.iloc[0]['updated_customer_job']

    return updated_job


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
        "Flow Mark Plumbing Supply": 10,
        "Plumbing Exchange": 11,
        "AF Supply":12,
        "Lion Hvac Supplies":13
    }
    for company, code in company_codes.items():
        if company in file_path:
            return code, company
    return 1 # need to return some default supplier


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
