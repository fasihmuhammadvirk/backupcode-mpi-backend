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
from mpi_backend.utils.supplier_suffix_manager import (
    get_supplier_suffix,
    get_unknown_supplier,
    get_supplier_id_from_name,
    get_supplier_name_from_id,
    get_all_supplier_names
)
from mpi_backend.utils.mapping_validators import is_empty_or_unassigned_sheet_name
# Freight extraction is already handled in PDF to Excel conversion

logger = logging.getLogger(__name__)

# Constants
TAX_SHEET_NAME = '(TAX)'

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
        # Read Excel file with explicit data types to preserve leading zeros in reference numbers and customer jobs
        extracted_data = pd.read_excel(excel_file, dtype={'Ref NO': str, 'Customer Job': str})
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
            
            # Check if this is a credit memo (CR- prefixed reference number)
            if ref_no.startswith('CR-'):
                # For credit memos, make all amounts negative
                amounts = -abs(amounts)
                logger.info(f"Credit memo detected (ref_no: {ref_no}), converting amounts to negative")
            
            total_invoice_amount = amounts.sum()
            invoice_amount = str(total_invoice_amount)
            logger.info(
                f"Calculated total invoice amount: {invoice_amount} from {len(amounts)} items")
        except Exception as e:
            logger.error(f"Error calculating total invoice amount: {str(e)}")
            # Fallback to first row amount if calculation fails
            invoice_amount = str(extracted_data['Amount'][0]) if len(
                extracted_data) > 0 else "0"

        # For reprocessing, check for duplicates first, then handle accordingly
        if existing_invoice_id:
            logger.info(
                f"Reprocessing mode: Checking duplicates for existing invoice {existing_invoice_id}")
            
            # Extract customer job for comparison
            extracted_customer_job = extracted_data['Customer Job'][0] if len(extracted_data) > 0 else ""
            
            # Check for duplicates even during reprocessing to handle edge cases
            duplicate_status = InvoiceItemController(db).check_invoice_duplicate_status(
                ref_no, vendor, invoice_date, invoice_amount, extracted_customer_job
            )
            
            # For reprocessing, always check if content has changed even if basic fields match
            if duplicate_status['status'] == 'exact_duplicate':
                # Check if content has actually changed by comparing line counts
                existing_item_count = InvoiceItemController(db).count_items_for_invoice(existing_invoice_id)
                new_item_count = len(extracted_data)
                
                logger.info(f"Reprocessing: Found exact duplicate with existing {existing_item_count} items, new {new_item_count} items")
                
                if existing_item_count != new_item_count:
                    # Content has changed (different number of items), force refresh
                    logger.info(f"Reprocessing: Content changed (item count: {existing_item_count} -> {new_item_count}), forcing refresh")
                    controller = InvoiceItemController(db)
                    deleted_count = controller.delete_previous_invoice_for_update(existing_invoice_id)
                    duplicate_status = {
                        'status': 'updated_invoice',
                        'existing_invoice_id': existing_invoice_id,
                        'deleted_previous_items': deleted_count,
                        'message': f'Reprocessing: Content changed (item count: {existing_item_count} -> {new_item_count}). Deleted {deleted_count} previous items, will add new ones.'
                    }
                else:
                    # Content appears unchanged, clean up inactive items and skip
                    logger.info("Reprocessing: Content unchanged, cleaning up inactive items")
                    controller = InvoiceItemController(db)
                    cleaned_count = controller.cleanup_exact_duplicate_inactive_items(existing_invoice_id)
                    duplicate_status['cleaned_inactive_items'] = cleaned_count
                    duplicate_status['message'] = f'Reprocessing: Content unchanged for {existing_invoice_id}. Cleaned up {cleaned_count} inactive items.'
            elif duplicate_status['status'] == 'updated_invoice':
                # For updated invoice, delete previous items and add new ones
                logger.info(f"Reprocessing: Found updated invoice, replacing items for {existing_invoice_id}")
                controller = InvoiceItemController(db)
                deleted_count = controller.delete_previous_invoice_for_update(existing_invoice_id)
                duplicate_status['deleted_previous_items'] = deleted_count
                duplicate_status['message'] = f'Reprocessing: Found updated invoice for {existing_invoice_id}. Deleted {deleted_count} previous items, will add new ones.'
            else:
                # For new invoice or not found, proceed with reprocessing
                duplicate_status = {
                    'status': 'updated_invoice',
                    'existing_invoice_id': existing_invoice_id,
                    'message': f'Reprocessing existing invoice {existing_invoice_id}'
                }
        else:
            # Normal processing - check for duplicates
            # Extract customer job for comparison
            extracted_customer_job = extracted_data['Customer Job'][0] if len(extracted_data) > 0 else ""
            
            duplicate_status = InvoiceItemController(db).check_invoice_duplicate_status(
                ref_no, vendor, invoice_date, invoice_amount, extracted_customer_job
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
                    InvoiceItem.is_active.isnot(False)  # Include True and NULL values
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
            cleaned_count = duplicate_status.get('cleaned_inactive_items', 0)
            return {
                "status": "skipped",
                "ref_no": ref_no,
                "vendor": vendor,
                "date": str(invoice_date),
                "cleaned_inactive_items": cleaned_count,
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
            # Continue processing to add new items to the existing invoice (previous items already deleted)
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
            # Check if freight already exists in extracted data and update format if needed
            freight_rows = extracted_data[
                (extracted_data['MpiItem'] == '10 Materials') & 
                (extracted_data['MpiDescription'] == 'Freight')
            ]
            
            if len(freight_rows) > 0:
                logger.info(f"Found {len(freight_rows)} existing freight rows in updated invoice")
                
                # Update existing freight rows to use correct format
                for idx in freight_rows.index:
                    extracted_data.loc[idx, 'MpiItem'] = '10 Material'  # Update to correct format
                    extracted_data.loc[idx, 'Item'] = '10 Material'  # Update to correct format
                    extracted_data.loc[idx, 'Qty'] = ''  # Remove qty (like tax)
                    extracted_data.loc[idx, 'Memo'] = ''  # Remove memo (like tax)
                    
                    # Handle CR- reference numbers for freight (make negative)
                    if ref_no.startswith('CR-'):
                        current_amount = extracted_data.loc[idx, 'Amount']
                        current_cost = extracted_data.loc[idx, 'Cost']
                        
                        # Make amounts negative
                        extracted_data.loc[idx, 'Amount'] = str(-abs(float(current_amount)))
                        extracted_data.loc[idx, 'Cost'] = -abs(float(current_cost))
                        logger.info(f"Credit memo detected, making freight amount negative: {extracted_data.loc[idx, 'Amount']}")
                
                logger.info(f"Updated {len(freight_rows)} freight rows to correct format")
            else:
                logger.info("No existing freight rows found in updated invoice")
            
            # Update existing invoice with new data (previous items already deleted if needed)
            success = InvoiceItemController(db).update_existing_invoice_items(
                existing_invoice_id, extracted_data, os.path.basename(file)
            )
            if success:
                deleted_count = duplicate_status.get('deleted_previous_items', 0)
                cleaned_count = duplicate_status.get('cleaned_inactive_items', 0)
                logger.info(
                    f'Successfully added {len(extracted_data)} new items to invoice {existing_invoice_id} (deleted {deleted_count} previous items, cleaned {cleaned_count} inactive items)')
                return {
                    "status": "updated",
                    "invoice_id": existing_invoice_id,
                    "ref_no": ref_no,
                    "vendor": vendor,
                    "date": str(invoice_date),
                    "deleted_previous_items": deleted_count,
                    "cleaned_inactive_items": cleaned_count,
                    "added_new_items": len(extracted_data),
                    "message": duplicate_status['message']
                }
            else:
                logger.error(f'Failed to add new items to invoice {existing_invoice_id}')
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

            # Check if freight already exists in extracted data and update format if needed
            freight_rows = extracted_data[
                (extracted_data['MpiItem'] == '10 Materials') & 
                (extracted_data['MpiDescription'] == 'Freight')
            ]
            
            if len(freight_rows) > 0:
                logger.info(f"Found {len(freight_rows)} existing freight rows in new invoice")
                
                # Update existing freight rows to use correct format
                for idx in freight_rows.index:
                    extracted_data.loc[idx, 'MpiItem'] = '10 Material'  # Update to correct format
                    extracted_data.loc[idx, 'Item'] = '10 Material'  # Update to correct format
                    extracted_data.loc[idx, 'Qty'] = ''  # Remove qty (like tax)
                    extracted_data.loc[idx, 'Memo'] = ''  # Remove memo (like tax)
                    
                    # Handle CR- reference numbers for freight (make negative)
                    if ref_no.startswith('CR-'):
                        current_amount = extracted_data.loc[idx, 'Amount']
                        current_cost = extracted_data.loc[idx, 'Cost']
                        
                        # Make amounts negative
                        extracted_data.loc[idx, 'Amount'] = str(-abs(float(current_amount)))
                        extracted_data.loc[idx, 'Cost'] = -abs(float(current_cost))
                        logger.info(f"Credit memo detected, making freight amount negative: {extracted_data.loc[idx, 'Amount']}")
                
                logger.info(f"Updated {len(freight_rows)} freight rows to correct format")
            else:
                logger.info("No existing freight rows found in new invoice")

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

    except Exception as _:
        logger.exception(f'Error processing failed file {file}')
        raise


def _has_original_item_and_description(row):
    """
    Check if an invoice item has both Original Item Number and Original Description
    AND the description is NOT "Tax" (which indicates an actual tax item from PDF processor).
    
    Args:
        row: pandas Series representing an invoice item row
        
    Returns:
        bool: True if both 'Item' and 'Description' are present, non-empty,
              AND description is NOT "Tax"
    """
    item = row.get('Item', '')
    description = row.get('Description', '')

    has_item = item and str(item).strip()
    has_description = description and str(description).strip()

    description_str = str(description).strip() if description else ''
    is_actual_tax = description_str.upper().strip() == 'TAX'

    return has_item and has_description and not is_actual_tax


def search_replace(row, temp_items, item_mappings, db):
    """
    Search for item mappings with exact comparison.
    Maps original_item (supplier_item_ids) to mpi_code.

    Prioritizes permanent mappings over temporary ones to ensure valid
    mappings override UIDI.
    Uses exact matching only to avoid business logic issues.
    Also handles mappings without sheet names.
    
    Items with both Original Item Number and Original Description should
    never be classified as Tax. If no mapping is found, they should
    display "No Match" instead of Tax.
    """
    # Removed unused import - mapping validation is now handled differently

    has_original_fields = _has_original_item_and_description(row)

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
            sheet_name = mapping_match.iloc[0]['google_sheet_name']

            # CRITICAL: Items with both Original Item Number and Original Description
            # should NEVER be classified as Tax, even if a mapping exists
            if has_original_fields and sheet_name and str(sheet_name).strip().upper() == TAX_SHEET_NAME:
                logger.debug(
                    f"Rejecting Tax mapping for item with Original Item Number and Description: "
                    f"{original_item} -> {mpi_code} (sheet: {sheet_name})")
                # Skip this mapping and continue to look for other mappings or return as "No Match"
            # Apply the mapping if it exists in the permanent mappings table
            # Only apply if it's a valid permanent mapping (not UIDI or temporary codes)
            # UIDI codes should remain as "No Match" until properly mapped
            elif (mpi_code and
                mpi_code.strip() and
                not mpi_code.strip().startswith('UIDI') and
                mpi_code.strip() != "No Match" and
                mpi_code.strip() != "No Match / UIDI" and
                not mpi_code.strip().startswith('Temp') and
                not mpi_code.strip().startswith('TEMP')):

                row['MpiItem'] = mpi_code  # This is the target mpi_code
                row['MpiDescription'] = description or mpi_code
                # Handle empty sheet names
                row['Sheet Name'] = sheet_name or ""

                # Log if this is a mapping without sheet name
                if is_empty_or_unassigned_sheet_name(sheet_name):
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
        temp_sheet_name = temp_match.iloc[0]['sheet_name']
        
        # CRITICAL: Items with both Original Item Number and Original Description
        # should NEVER be classified as Tax, even if a temporary mapping exists
        if has_original_fields and temp_sheet_name and str(temp_sheet_name).strip().upper() == TAX_SHEET_NAME:
            logger.debug(
                f"Rejecting Tax temporary mapping for item with Original Item Number and Description: "
                f"{original_item} -> sheet: {temp_sheet_name}")
            # Skip this mapping and continue to return as "No Match"
        else:
            # For temporary mappings, ONLY assign the sheet name. Do NOT change MPI fields.
            row['Sheet Name'] = temp_sheet_name
            logger.debug(
                f"Applied temporary mapping: {original_item} -> sheet: "
                f"{temp_sheet_name} (MPI fields unchanged)")
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
        # No suffix expected for this supplier; signal "no match"
        return temp_items.iloc[0:0]
    
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
    
    # No suffix-based variations found; return empty
    return temp_items.iloc[0:0]


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
        # No suffix expected for this supplier; signal "no match"
        return item_mappings.iloc[0:0]
    
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
    
    # No suffix-based variations found; return empty
    return item_mappings.iloc[0:0]


def _get_supplier_suffix(supplier_id):
    """
    Get suffix for a supplier ID.
    Uses centralized supplier_suffix_manager.
    
    Note: This function is called from DataFrame processing utilities that don't
    have database access. It uses the in-memory fallback mapping, which is
    acceptable since suffix mappings are static and rarely change. For database-
    backed lookups, use get_supplier_suffix(supplier_id, db=session) directly.
    """
    return get_supplier_suffix(supplier_id=supplier_id)


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
    """Extract supplier ID and name from file path.

    Uses centralized supplier_suffix_manager for name-to-ID lookups.
    """
    for supplier_name in get_all_supplier_names():
        if supplier_name in file_path:
            supplier_id = get_supplier_id_from_name(supplier_name)
            return supplier_id, supplier_name

    # Return Unknown Supplier if no match found
    return get_unknown_supplier()


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
