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
from mpi_backend.database.models.InvoiceItems import InvoiceItem

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
        # Normalize path handling to be cross-platform
        import os
        base_name = os.path.basename(file)
        excel_file = file
        if base_name.lower().endswith('.pdf'):
            excel_file = file[: -4] + '.xlsx'
        # Read Excel file with explicit data types to preserve leading zeros in reference numbers
        extracted_data = pd.read_excel(excel_file, dtype={'Ref NO': str})
        logger.info(f"Processing file: {file} with {len(extracted_data)} "
                    f"items")
        # Ensure DB session is clean before any queries (in case a previous
        # operation in this same session failed and left it in error state)
        try:
            db.rollback()
        except Exception:
            pass
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
        elif duplicate_status['status'] == 'exact_duplicate_with_ref_update':
            logger.warning(duplicate_status['message'])
            # Update the reference number in the existing invoice
            controller = InvoiceItemController(db)
            updated_count = controller.update_invoice_reference_number(
                duplicate_status['existing_invoice_id'], 
                ref_no
            )
            
            return {
                "status": "updated_ref_no",
                "ref_no": ref_no,
                "vendor": vendor,
                "date": str(invoice_date),
                "existing_invoice_id": duplicate_status['existing_invoice_id'],
                "items_updated": updated_count,
                "message": f"Updated reference number for existing invoice: {updated_count} items updated to '{ref_no}'"
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
                existing_invoice_id, extracted_data, os.path.basename(file)
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
                    extracted_data['Date'][0], os.path.basename(file),
                    supplier_id, 'PROCESSING', file, existing_invoice_id
                )
                logger.info(
                    f"Reprocessing: Created invoice with existing ID {existing_invoice_id}")
            else:
                # For new uploads, let the database generate a new ID
                invoice_record = InvoiceController(db).insert_invoice(
                    extracted_data['Date'][0], os.path.basename(file),
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
                    row, os.path.basename(file), invoice_record.id
                )

            logger.info(
                f'Successfully processed invoice {os.path.basename(file)} with {len(extracted_data)} items')
            return {
                "status": "created",
                "invoice_id": invoice_record.id,
                "ref_no": ref_no,
                "vendor": vendor,
                "date": str(invoice_date),
                "message": "Invoice created successfully"
            }
    except Exception as e:
        # Always rollback on error to clear aborted transaction state
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(f"Error processing file {file}: {str(e)}")
        return {"status": "error", "message": str(e), "file": file}


def process_failed_file(file, db):
    """Process a failed file"""
    try:
        supplier_id, supplier_name = extract_supplier_id(file_path=file)

        import os
        if InvoiceController(db).is_invoice_present(os.path.basename(file)):
            logger.info(f"Failed file {file} already exists in database, "
                        f"skipping")
            return

        invoice_record = InvoiceController(db).insert_invoice(
            datetime.now().strftime('%m/%d/%Y'), os.path.basename(file),
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
    # Removed unused import - mapping validation is now handled differently

    # Clean supplier_item_ids from invoice and strip spaces
    original_item = row['Item'].strip()

    # FIRST: Search in permanent mappings (supplier_item_mappings table)
    # This ensures permanent mappings override temporary ones
    # Also handles mappings without sheet names
    if 'supplier_item_ids' in item_mappings.columns:
        # Try exact match first
        mapping_match = item_mappings[
            item_mappings['supplier_item_ids'] == original_item
        ]
        
        # If no exact match, try suffix variations for permanent mappings
        if mapping_match.empty:
            mapping_match = _find_permanent_mapping_with_suffix_variations(
                item_mappings, original_item, row['Vendor'])

        if not mapping_match.empty:
            mpi_code = mapping_match.iloc[0]['mpi_code']
            description = mapping_match.iloc[0]['description']

            # Apply the mapping if it exists in the permanent mappings table
            # Only apply if it's a valid permanent mapping (not UIDI or temporary codes)
            # UIDI codes should remain as "No Match" until properly mapped
            if (mpi_code and
                mpi_code.strip() and
                not mpi_code.strip().startswith('UIDI') and
                mpi_code.strip() != "No Match" and
                mpi_code.strip() != "No Match / UIDI" and
                not mpi_code.strip().startswith('Temp') and
                not mpi_code.strip().startswith('TEMP')):

                row['MpiItem'] = mpi_code  # This is the target mpi_code
                row['MpiDescription'] = description or mpi_code
                sheet_name = mapping_match.iloc[0]['google_sheet_name']
                # Handle empty sheet names
                row['Sheet Name'] = sheet_name or ""

                # Log if this is a mapping without sheet name
                if not sheet_name or sheet_name.strip() == "":
                    logger.debug(
                        f"Applied permanent mapping (no sheet): "
                        f"{original_item} -> {mpi_code}")
                else:
                    logger.debug(
                        f"Applied permanent mapping: "
                        f"{original_item} -> {mpi_code}")
                return row
            else:
                logger.debug(
                    f"Skipping temporary/UIDI mapping in permanent table: "
                    f"{mpi_code} - will remain as No Match")

    # SECOND: If no permanent mapping found, check temporary mappings
    # Check for exact match first, then try suffix variations
    temp_match = temp_items[
        temp_items['original_item'] == original_item
    ]

    # If no exact match, try suffix variations for temporary mappings
    if temp_match.empty:
        temp_match = _find_temp_mapping_with_suffix_variations(
            temp_items, original_item, row['Vendor'])

    if not temp_match.empty:
        # For temporary mappings, ONLY assign the sheet name. Do NOT change MPI fields.
        row['Sheet Name'] = temp_match.iloc[0]['sheet_name']
        logger.debug(
            f"Applied temporary mapping: {original_item} -> sheet: "
            f"{temp_match.iloc[0]['sheet_name']} (MPI fields unchanged)")
        return row

    # THIRD: If no mapping found at all, add to unmapped items
    supplier_id, _ = extract_supplier_id(row['Vendor'])
    if not UnmappedItemsController(db).is_item_code_present(
            row['Item'], supplier_id):
        UnmappedItemsController(db).insert_unmapped_item(
            row['Item'], row['Description'], supplier_id
        )
        logger.debug(f"Added unmapped item: {row['Item']}")

    # Return with default "No Match" - this will be set by the calling function
    return row


def _find_temp_mapping_with_suffix_variations(temp_items, original_item, vendor):
    """
    Find temporary mapping by checking suffix variations.
    
    Args:
        temp_items: DataFrame of temporary mappings
        original_item: Item from invoice (clean, no suffix)
        vendor: Vendor name to determine expected suffix
        
    Returns:
        DataFrame with matching temporary mapping or empty DataFrame
    """
    if temp_items.empty:
        return temp_items
    
    # Get expected suffix for this vendor
    supplier_id, _ = extract_supplier_id(vendor)
    expected_suffix = _get_supplier_suffix(supplier_id)
    
    if not expected_suffix:
        return temp_items  # No suffix expected, return empty
    
    # Try to find mapping with suffix
    item_with_suffix = f"{original_item}-{expected_suffix}"
    temp_match = temp_items[temp_items['original_item'] == item_with_suffix]
    
    if not temp_match.empty:
        logger.debug(
            f"Found temporary mapping with suffix variation: "
            f"{original_item} -> {item_with_suffix}")
        return temp_match
    
    # Try other common suffix variations
    common_suffixes = ['B', 'W', 'Y', 'S', 'P', 'A', 'G', 'F']
    for suffix in common_suffixes:
        if suffix != expected_suffix:  # Skip the expected one, already tried
            item_with_suffix = f"{original_item}-{suffix}"
            temp_match = temp_items[temp_items['original_item'] == item_with_suffix]
            if not temp_match.empty:
                logger.debug(
                    f"Found temporary mapping with alternative suffix: "
                    f"{original_item} -> {item_with_suffix}")
                return temp_match
    
    return temp_items  # Return empty if no variations found


def _find_permanent_mapping_with_suffix_variations(item_mappings, original_item, vendor):
    """
    Find permanent mapping by checking suffix variations.
    
    Args:
        item_mappings: DataFrame of permanent mappings
        original_item: Item from invoice (clean, no suffix)
        vendor: Vendor name to determine expected suffix
        
    Returns:
        DataFrame with matching permanent mapping or empty DataFrame
    """
    if item_mappings.empty:
        return item_mappings
    
    # Get expected suffix for this vendor
    supplier_id, _ = extract_supplier_id(vendor)
    expected_suffix = _get_supplier_suffix(supplier_id)
    
    if not expected_suffix:
        return item_mappings  # No suffix expected, return empty
    
    # Try to find mapping with suffix
    item_with_suffix = f"{original_item}-{expected_suffix}"
    mapping_match = item_mappings[item_mappings['supplier_item_ids'] == item_with_suffix]
    
    if not mapping_match.empty:
        logger.debug(
            f"Found permanent mapping with suffix variation: "
            f"{original_item} -> {item_with_suffix}")
        return mapping_match
    
    # Try other common suffix variations
    common_suffixes = ['B', 'W', 'Y', 'S', 'P', 'A', 'G', 'F']
    for suffix in common_suffixes:
        if suffix != expected_suffix:  # Skip the expected one, already tried
            item_with_suffix = f"{original_item}-{suffix}"
            mapping_match = item_mappings[item_mappings['supplier_item_ids'] == item_with_suffix]
            if not mapping_match.empty:
                logger.debug(
                    f"Found permanent mapping with alternative suffix: "
                    f"{original_item} -> {item_with_suffix}")
                return mapping_match
    
    return item_mappings  # Return empty if no variations found


def _get_supplier_suffix(supplier_id):
    """Get suffix for a supplier ID."""
    suffix_map = {
        1: 'B',   # BMW Plumbing Supplies
        2: 'W',   # World Wide Plumbing  
        3: 'Y',   # Y & S Plumbing Supply
        4: 'S',   # Supreme Plumbing Supply
        5: 'P',   # Pyramid Plumbing
        6: 'A',   # ABC Opus Services
        7: 'P',   # Park Plumbing Supply
        8: 'G',   # Gotham Plumbing Supply
        9: 'F',   # FW Webb Plumbing Supply
        10: 'F',  # Flow Mark Plumbing Supply
        11: None, # Plumbing Exchange (no suffix)
        12: 'A',  # AF Supply
        13: None, # Lion Hvac Supplies (no suffix)
        14: 'F',  # Bruce Ferguson
    }
    return suffix_map.get(supplier_id)


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
    # Return a safe default tuple to avoid unpack errors in callers
    return 1, "BMW Plumbing Supplies"


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
