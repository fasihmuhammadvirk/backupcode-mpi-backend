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


def process_extracted_data(converted_files, failed_files, existing_invoice_id=None):
    """Process extracted data with proper database session management"""
    logger.info(f"Starting to process {len(converted_files)} converted files "
                f"and {len(failed_files)} failed files")

    results = []

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
                result = process_single_file(file, temp_items, item_mappings,
                                             customer_job_mappings, database,
                                             existing_invoice_id)
                results.append(result)
                # Only use existing_invoice_id for the first file
                existing_invoice_id = None
            except Exception as e:
                logger.error(f"Failed to process file {file}: {str(e)}")
                failed_files.append(file)
                results.append({
                    "status": "error",
                    "message": str(e),
                    "file": file
                })

        # Process failed files
        for file in failed_files:
            try:
                process_failed_file(file, database)
            except Exception as e:
                logger.error(f"Failed to process failed file {file}: "
                             f"{str(e)}")
    return results


def process_single_file(file, temp_items, item_mappings, customer_job_mappings,
                        db, existing_invoice_id=None):
    """Process a single converted file and return status/result dict"""
    try:
        excel_file = file.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx")
        extracted_data = pd.read_excel(excel_file)
        logger.info(f"Processing file: {file} with {len(extracted_data)} "
                    f"items")
    except FileNotFoundError:
        logger.error(f'Invoice ->{file} does not exists')
        return {"status": "error", "message": f"File not found: {file}", "file": file}
    except Exception as e:
        logger.error(f'Error reading Excel file {excel_file}: {str(e)}')
        return {"status": "error", "message": str(e), "file": file}

    try:
        supplier_id = SupplierController(db).get_supplier_name(
            extracted_data['Vendor'][0]
        )

        # Enhanced duplicate detection with three-tiered logic
        ref_no = str(extracted_data['Ref NO'][0])
        vendor = str(extracted_data['Vendor'][0])
        date_str = str(extracted_data['Date'][0])
        try:
            invoice_date = datetime.strptime(date_str, '%m/%d/%Y').date()
        except ValueError:
            try:
                invoice_date = datetime.strptime(date_str, '%m/%d/%y').date()
            except ValueError:
                logger.error(f"Could not parse date: {date_str}")
                return {"status": "error", "message": f"Could not parse date: {date_str}", "file": file}

        # Calculate total invoice amount by summing all items
        try:
            # Convert Amount column to numeric, handling any non-numeric values
            amounts = pd.to_numeric(
                extracted_data['Amount'], errors='coerce').fillna(0)
            total_invoice_amount = amounts.sum()
            invoice_amount = str(total_invoice_amount)
            logger.info(
                f"Calculated total invoice amount: {invoice_amount} from {len(amounts)} items")
        except Exception as e:
            logger.error(f"Error calculating total invoice amount: {str(e)}")
            # Fallback to first row amount if calculation fails
            invoice_amount = str(extracted_data['Amount'][0]) if len(
                extracted_data) > 0 else "0"

        # For reprocessing, skip duplicate detection and directly update existing invoice
        if existing_invoice_id:
            logger.info(
                f"Reprocessing mode: Updating existing invoice {existing_invoice_id}")
            duplicate_status = {
                'status': 'updated_invoice',
                'existing_invoice_id': existing_invoice_id,
                'message': f'Reprocessing existing invoice {existing_invoice_id}'
            }
        else:
            # Normal processing - check for duplicates
            duplicate_status = InvoiceItemController(db).check_invoice_duplicate_status(
                ref_no, vendor, invoice_date, invoice_amount
            )

            # Additional check: Look for any existing invoice with same ref_no and vendor
            # This catches cases where the same invoice might be processed multiple times
            existing_invoice_check = InvoiceItemController(
                db).invoice_exists(ref_no, vendor)
            if existing_invoice_check:
                logger.warning(
                    f"Found existing invoice with ref_no: {ref_no}, vendor: {vendor}. This might be a duplicate processing attempt.")
                # Log additional details for debugging
                existing_items = db.query(InvoiceItem).filter(
                    InvoiceItem.ref_no == ref_no,
                    InvoiceItem.vendor == vendor,
                    InvoiceItem.is_active == True
                ).all()
                if existing_items:
                    logger.warning(
                        f"Found {len(existing_items)} existing items for ref_no: {ref_no}, vendor: {vendor}")
                    for item in existing_items[:3]:  # Log first 3 items
                        logger.warning(
                            f"  - Item ID: {item.id}, Invoice ID: {item.invoice_id}, Date: {item.date}, Amount: {item.amount}")

        # Handle different duplicate scenarios
        if duplicate_status['status'] == 'exact_duplicate':
            logger.warning(duplicate_status['message'])
            return {
                "status": "skipped",
                "ref_no": ref_no,
                "vendor": vendor,
                "date": str(invoice_date),
                "message": duplicate_status['message']
            }
        elif duplicate_status['status'] == 'updated_invoice':
            logger.info(duplicate_status['message'])
            # Continue processing to update the existing invoice
            existing_invoice_id = duplicate_status['existing_invoice_id']
        elif duplicate_status['status'] == 'new_invoice':
            logger.info(duplicate_status['message'])
            # Continue processing to add as new invoice
            existing_invoice_id = None
        elif duplicate_status['status'] == 'not_found':
            logger.info(duplicate_status['message'])
            # Continue processing to add as new invoice
            existing_invoice_id = None
        else:
            logger.error(
                f"Error in duplicate detection: {duplicate_status['message']}")
            return {
                "status": "error",
                "ref_no": ref_no,
                "vendor": vendor,
                "date": str(invoice_date),
                "message": duplicate_status['message']
            }

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

        # Handle different processing scenarios
        if duplicate_status['status'] == 'updated_invoice':
            # Update existing invoice with new data
            success = InvoiceItemController(db).update_existing_invoice_items(
                existing_invoice_id, extracted_data, file.rsplit('/')[-1]
            )
            if success:
                logger.info(
                    f'Successfully updated invoice {existing_invoice_id} with {len(extracted_data)} items')
                return {
                    "status": "updated",
                    "invoice_id": existing_invoice_id,
                    "ref_no": ref_no,
                    "vendor": vendor,
                    "date": str(invoice_date),
                    "message": duplicate_status['message']
                }
            else:
                logger.error(f'Failed to update invoice {existing_invoice_id}')
                return {
                    "status": "error",
                    "invoice_id": existing_invoice_id,
                    "ref_no": ref_no,
                    "vendor": vendor,
                    "date": str(invoice_date),
                    "message": f'Failed to update invoice {existing_invoice_id}'
                }
        else:
            # Create new invoice record
            if existing_invoice_id:
                # For reprocessing, use existing invoice ID
                invoice_record = InvoiceController(db).insert_invoice(
                    extracted_data['Date'][0], file.rsplit('/')[-1],
                    supplier_id, 'PROCESSING', file, existing_invoice_id
                )
                logger.info(
                    f"Reprocessing: Created invoice with existing ID {existing_invoice_id}")
            else:
                # For new uploads, let the database generate a new ID
                invoice_record = InvoiceController(db).insert_invoice(
                    extracted_data['Date'][0], file.rsplit('/')[-1],
                    supplier_id, 'PROCESSING', file
                )

            # Mark invoice as processed
            InvoiceController(db).set_status_to_processed(invoice_record.id)

            # Upload to S3
            upload_file(file_name=file,
                        file_key=f'{extracted_data["Vendor"][0]}/{invoice_record.id}')

            # Store invoice items
            for index, row in extracted_data.iterrows():
                InvoiceItemController(db).insert_invoice_items(
                    row, file.rsplit('/')[-1], invoice_record.id
                )

            logger.info(
                f'Successfully processed invoice {file.rsplit("/")[-1]} with {len(extracted_data)} items')
            return {
                "status": "created",
                "invoice_id": invoice_record.id,
                "ref_no": ref_no,
                "vendor": vendor,
                "date": str(invoice_date),
                "message": "Invoice created successfully"
            }
    except Exception as e:
        logger.error(f"Error processing file {file}: {str(e)}")
        return {"status": "error", "message": str(e), "file": file}


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
    Search for item mappings with exact comparison.
    Maps original_item (supplier_item_ids) to mpi_code.

    Prioritizes permanent mappings over temporary ones to ensure valid
    mappings override UIDI.
    Uses exact matching only to avoid business logic issues.
    Also handles mappings without sheet names.
    """
    from mpi_backend.utils.mapping_validators import is_temporary_mapping

    # Clean supplier_item_ids from invoice and strip spaces
    original_item = row['Item'].strip()

    # FIRST: Search in permanent mappings (supplier_item_mappings table)
    # This ensures permanent mappings override temporary ones
    # Also handles mappings without sheet names
    if 'supplier_item_ids' in item_mappings.columns:
        # Exact match only - no suffix variations to avoid business logic issues
        mapping_match = item_mappings[
            item_mappings['supplier_item_ids'] == original_item
        ]

        if not mapping_match.empty:
            mpi_code = mapping_match.iloc[0]['mpi_code']
            description = mapping_match.iloc[0]['description']

            # Validate that this is not a temporary mapping that slipped through
            if not is_temporary_mapping(mpi_code, description):
                row['MpiItem'] = mpi_code  # This is the target mpi_code
                row['MpiDescription'] = description
                sheet_name = mapping_match.iloc[0]['google_sheet_name']
                # Handle empty sheet names
                row['Sheet Name'] = sheet_name or ""

                # Log if this is a mapping without sheet name
                if not sheet_name or sheet_name.strip() == "":
                    logger.debug(
                        f"Applied permanent mapping (no sheet): {original_item} -> {mpi_code}")
                else:
                    logger.debug(
                        f"Applied permanent mapping: {original_item} -> {mpi_code}")
                return row
            else:
                logger.warning(
                    f"Found temporary mapping in permanent table, skipping: {mpi_code}")

    # SECOND: If no permanent mapping found, check temporary mappings
    # Exact match only - no suffix variations to avoid business logic issues
    temp_match = temp_items[
        temp_items['original_item'] == original_item
    ]

    if not temp_match.empty:
        # For temporary mappings, we assign the sheet name but preserve existing MPI item and description
        # The temporary mapping system assigns items to sheets for later processing
        # Preserve existing values - temporary mappings don't change MPI codes
        # Only update if current values are "No Match" or empty
        if row.get('MpiItem') in ['No Match', '', None]:
            row['MpiItem'] = 'No Match'
        if row.get('MpiDescription') in ['No Match', '', None]:
            row['MpiDescription'] = temp_match.iloc[0]['original_description'] or 'No Match'
        row['Sheet Name'] = temp_match.iloc[0]['sheet_name']
        logger.debug(
            f"Applied temporary mapping: {original_item} -> sheet: {temp_match.iloc[0]['sheet_name']} (preserved existing MPI values)")
        return row

    # THIRD: If no mapping found at all, add to unmapped items
    supplier_id, _ = extract_supplier_id(row['Vendor'])
    if not UnmappedItemsController(db).is_item_code_present(row['Item'], supplier_id):
        UnmappedItemsController(db).insert_unmapped_item(
            row['Item'], row['Description'], supplier_id
        )
        logger.debug(f"Added unmapped item: {row['Item']}")

    # Return with default "No Match" - this will be set by the calling function
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
