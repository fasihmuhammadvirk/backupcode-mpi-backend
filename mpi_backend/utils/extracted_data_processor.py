# Responsible for reading converted excel files, mapping items, descriptions
# and customer jobs, then storing them in database.
import re
import pandas as pd
from datetime import datetime
import logging
from contextlib import contextmanager

from mpi_backend.database import get_db
from mpi_backend.database.controllers.TemporaryItemMappingController import (
    TemporaryItemMappingController
)
from mpi_backend.database.controllers.ItemsMappingController import (
    ItemsMappingController
)
from mpi_backend.database.controllers.CustomerJobMappingContorller import (
    CustomerJobMappingController
)
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.controllers.Invoice import InvoiceController
from mpi_backend.database.controllers.UnmappedItems import (
    UnmappedItemsController
)
from mpi_backend.utils.s3_utils import upload_file

logger = logging.getLogger(__name__)

# Database context manager
db = contextmanager(get_db)


def process_extracted_data(converted_files, failed_files,
                           existing_invoice_id=None):
    """Process extracted data with proper database session management"""
    logger.info(f"Starting to process {len(converted_files)} converted files "
                f"and {len(failed_files)} failed files")

    # If reprocessing, log the invoice ID we're preserving
    if existing_invoice_id:
        logger.info(f"Reprocessing mode: Preserving invoice ID "
                    f"{existing_invoice_id}")

    # Use database context manager like the old code
    with db() as database:
        # Get mappings once at the start
        temp_items = TemporaryItemMappingController(database)\
            .get_temp_items_mappings()
        item_mappings = ItemsMappingController(database)\
            .get_items_mappings()
        customer_job_mappings = CustomerJobMappingController(database)\
            .get_customer_job_mappings()
        logger.info(f"Loaded {len(temp_items)} temporary mappings, "
                    f"{len(item_mappings)} permanent mappings, "
                    f"{len(customer_job_mappings)} customer job mappings")

        for file in converted_files:
            try:
                process_single_file(file, temp_items, item_mappings,
                                    customer_job_mappings, database,
                                    existing_invoice_id)
                # Only use existing_invoice_id for the first file
                existing_invoice_id = None
            except Exception as e:
                logger.error(f"Failed to process file {file}: {str(e)}")
                failed_files.append(file)

        # Process failed files
        for file in failed_files:
            try:
                process_failed_file(file, database)
            except Exception as e:
                logger.error(f"Failed to process failed file {file}: "
                             f"{str(e)}")


def process_single_file(file, temp_items, item_mappings, customer_job_mappings,
                        db, existing_invoice_id=None):
    """Process a single converted file"""
    try:
        excel_file = file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx")
        extracted_data = pd.read_excel(excel_file)
        logger.info(f"Processing file: {file} with {len(extracted_data)} "
                    f"items")
    except FileNotFoundError:
        logger.error(f'Invoice ->{file} does not exists')
        raise
    except Exception as e:
        logger.error(f'Error reading Excel file {excel_file}: {str(e)}')
        raise

    try:
        supplier_id = SupplierController(db).get_supplier_name(
            extracted_data['Vendor'][0]
        )

        # Check if invoice already exists (by reference number)
        if InvoiceItemController(db).invoice_exists(
            str(extracted_data['Ref NO'][0]),
            str(extracted_data['Vendor'][0])
        ):
            logger.warning(f'Invoice with REF-NO-> '
                           f'{str(extracted_data["Ref NO"][0])} '
                           f'already processed and is being skipped!')
            return

        # Add required columns
        extracted_data.insert(0, 'Sheet Name', '')
        extracted_data['MpiItem'] = 'No Match'
        extracted_data['MpiDescription'] = 'No Match'
        extracted_data['email_date'] = extract_email_date(file)

        # Apply mappings
        extracted_data = extracted_data.apply(
            search_replace,
            args=(temp_items, item_mappings, db),
            axis=1
        )

        # Update customer job
        extracted_customer_job = extracted_data['Customer Job'][0]
        extracted_data['Customer Job'] = get_updated_customer_job(
            extracted_customer_job, customer_job_mappings
        )

        # Fill NaN values
        extracted_data = extracted_data.fillna({
            'Qty': 0, 'Cost': 0, 'Class': '', 'Memo': '', 'Ref NO': '',
            'PO #': '', 'Customer Job': '', 'Buyer': '',
            'Date': datetime.today().strftime('%m/%d/%Y')
        })

        # Create invoice record using the same pattern as old code
        if existing_invoice_id:
            # For reprocessing, use existing invoice ID (simplified approach)
            invoice_record = InvoiceController(db).insert_invoice(
                extracted_data['Date'][0], file.rsplit('/')[-1],
                supplier_id, 'PROCESSING', file, existing_invoice_id
            )
            logger.info(f"Reprocessing: Created invoice with existing ID "
                        f"{existing_invoice_id}")
        else:
            # For new uploads, let the database generate a new ID
            invoice_record = InvoiceController(db).insert_invoice(
                extracted_data['Date'][0], file.rsplit('/')[-1],
                supplier_id, 'PROCESSING', file
            )

        # Mark invoice as processed (same as old code)
        InvoiceController(db).set_status_to_processed(invoice_record.id)

        # Upload to S3 (same as old code)
        upload_file(file_name=file,
                    file_key=f'{extracted_data["Vendor"][0]}/'
                             f'{invoice_record.id}')

        # Store invoice items (same as old code)
        for index, row in extracted_data.iterrows():
            InvoiceItemController(db).insert_invoice_items(
                row, file.rsplit('/')[-1], invoice_record.id
            )

        logger.info(f'Successfully processed invoice '
                    f'{file.rsplit("/")[-1]} with {len(extracted_data)} items')

    except Exception as e:
        logger.error(f"Error processing file {file}: {str(e)}")
        raise


def process_failed_file(file, db):
    """Process a failed file"""
    try:
        supplier_id, supplier_name = extract_supplier_id(file_path=file)

        if InvoiceController(db).is_invoice_present(file.split("/")[-1]):
            logger.info(f"Failed file {file} already exists in database, "
                        f"skipping")
            return

        invoice_record = InvoiceController(db).insert_invoice(
            datetime.now().strftime('%m/%d/%Y'), file.rsplit('/')[-1],
            supplier_id, 'FAILED', file
        )
        upload_file(file_name=file,
                    file_key=f'{supplier_name}/{invoice_record.id}')
        logger.info(f'Processed failed file: {file}')

    except Exception as e:
        logger.error(f'Error processing failed file {file}: {str(e)}')
        raise


def search_replace(row, temp_items, item_mappings, db):
    """
    Search for item mappings with direct comparison (no suffix cleaning).
    Maps original_item (supplier_item_ids) to mpi_code.

    Prioritizes permanent mappings over temporary ones to ensure valid
    mappings override UIDI.
    Note: With suffix standardization, we use direct comparisons.
    """
    from mpi_backend.utils.mapping_validators import is_temporary_mapping

    original_item = row['Item'].strip()  # Clean supplier_item_ids from invoice and strip spaces
    supplier_id, _ = extract_supplier_id(row['Vendor'])

    # FIRST: Search in permanent mappings (supplier_item_mappings table)
    # This ensures permanent mappings override temporary ones
    if 'supplier_item_ids' in item_mappings.columns:
        # With suffix standardization, we only do exact matches
        mapping_match = item_mappings[
            item_mappings['supplier_item_ids'] == original_item
        ]

        if not mapping_match.empty:
            mpi_code = mapping_match.iloc[0]['mpi_code']
            description = mapping_match.iloc[0]['description']

            # Validate that this is not a temporary mapping that slipped
            # through
            if not is_temporary_mapping(mpi_code, description):
                row['MpiItem'] = mpi_code  # This is the target mpi_code
                row['MpiDescription'] = description
                sheet_name = mapping_match.iloc[0]['google_sheet_name']
                row['Sheet Name'] = sheet_name
                logger.debug(f"Applied permanent mapping: {original_item} "
                             f"-> {mpi_code}")
                return row
            else:
                logger.warning(f"Found temporary mapping in permanent table, "
                               f"skipping: {mpi_code}")

    # SECOND: If no permanent mapping found, check temporary mappings
    # With suffix standardization, we only do exact matches
    temp_match = temp_items[
        temp_items['original_item'] == original_item
    ]

    if not temp_match.empty:
        # For temporary mappings, we assign the sheet name but keep "No Match" for the MPI item
        # The temporary mapping system assigns items to sheets for later processing
        row['MpiItem'] = 'No Match'  # Keep as No Match - temporary mappings don't provide MPI codes
        row['MpiDescription'] = temp_match.iloc[0]['original_description'] or 'No Match'
        row['Sheet Name'] = temp_match.iloc[0]['sheet_name']
        logger.debug(f"Applied temporary mapping: {original_item} -> "
                     f"sheet: {temp_match.iloc[0]['sheet_name']}")
        return row

    # THIRD: If no mapping found at all, add to unmapped items
    if not UnmappedItemsController(db).is_item_code_present(row['Item'],
                                                            supplier_id):
        UnmappedItemsController(db).insert_unmapped_item(
            row['Item'], row['Description'], supplier_id
        )
        logger.debug(f"Added unmapped item: {row['Item']}")

    # Return with default "No Match" - this will be set by the calling
    # function
    return row


def get_updated_customer_job(customer_job, customer_job_mappings):
    """Get updated customer job based on mappings"""
    updated_job = customer_job  # Return extracted job if no mapping found
    filtered_df = customer_job_mappings[
        customer_job_mappings['customer_job'] == customer_job
    ]

    if not filtered_df.empty:
        updated_job = filtered_df.iloc[0]['updated_customer_job']

    return updated_job


def extract_supplier_id(file_path):
    """Extract supplier ID and name from file path"""
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
        "AF Supply": 12,
        "Lion Hvac Supplies": 13
    }
    for company, code in company_codes.items():
        if company in file_path:
            return code, company
    return 1  # Need to return some default supplier


def extract_email_date(path):
    """Extract email date from file path"""
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
