from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pyodbc
import pandas as pd
from mpi_backend.database import get_db
from mpi_backend.database.controllers import InvoiceItemController,InvoiceController, ItemClassificationController
from mpi_backend.database.schemas import SendtoQBFilterRequest
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os

router = APIRouter(prefix="/quickbooks",tags=["QuickBooks"])

@router.post("/migrate-all")
def migrate_all_invoice_to_QB(request: SendtoQBFilterRequest, db: Session = Depends(get_db)):
    filtered_data = InvoiceItemController(db).apply_filters(request,page=1, size=0)
    invoice_ids = [item.invoice_id for item in filtered_data['items']]

    if request.excluded_invoice_ids:  # un selected items from frontend
        invoice_ids = [
            invoice_id for invoice_id in invoice_ids 
            if invoice_id not in request.excluded_invoice_ids
        ]

    invoice_ids = list(set(invoice_ids))  # make invoice-ids in list to be unique

    return migrate_invoice_to_QB(invoice_ids, db=db)


@router.post("/migrate")
def migrate_invoice_to_QB(
        invoice_ids: List[UUID], db: Session = Depends(get_db)):

    all_batch_entries = []

    for invoice_id in invoice_ids:
        # Use raw SQLAlchemy objects to avoid Pydantic conversion issues
        line_items_raw = InvoiceItemController(db).get_invoice_items_raw(invoice_id)
        line_items = InvoiceItemController(db).get_invoice_items(invoice_id)
        line_item_copy = line_items

        tax = 0
        for item in line_items_raw:
            if item.sheet_name == '(TAX)':
                tax = float(item.amount.replace(',', ''))

        line_items_raw = [item for item in line_items_raw if item.sheet_name != '(TAX)']

        # Create DataFrame and handle possible missing fields
        try:
            # First get reference numbers before creating DataFrame
            ref_numbers = [getattr(item, 'ref_no', 'unknown') for item in line_items_raw]
            
            # Debug: Check what we actually got from the database
            print(f"Number of raw items retrieved: {len(line_items_raw)}")
            if line_items_raw:
                sample_item = line_items_raw[0]
                print(f"Sample item type: {type(sample_item)}")
                print(f"Sample sheet_name value: {getattr(sample_item, 'sheet_name', 'NO SHEET_NAME ATTR')}")
                print(f"Sample ref_no value: {getattr(sample_item, 'ref_no', 'NO REF_NO ATTR')}")
            
            # Convert SQLAlchemy objects to dictionaries (this works reliably)
            line_items_data = []
            for i, item in enumerate(line_items_raw):
                try:
                    item_dict = item.__dict__.copy()
                    
                    # Remove SQLAlchemy internal fields
                    item_dict.pop('_sa_instance_state', None)
                    
                    # Apply suffix transformation for display
                    if hasattr(item, 'item_code_with_suffix'):
                        item_dict['item'] = item.item_code_with_suffix
                        
                    line_items_data.append(item_dict)
                        
                except Exception as item_error:
                    print(f"Error processing item {i}: {str(item_error)}")
                    print(f"Item type: {type(item)}")
                    raise
            
            print(f"Number of processed item dictionaries: {len(line_items_data)}")
            if line_items_data:
                print(f"Sample processed dict keys: {list(line_items_data[0].keys())}")
                print(f"Sample sheet_name from dict: {line_items_data[0].get('sheet_name', 'MISSING FROM DICT')}")
            
            line_item_df = pd.DataFrame(line_items_data)
            
            # Debug: DataFrame info
            print(f"DataFrame shape: {line_item_df.shape}")
            print(f"DataFrame columns: {list(line_item_df.columns)}")
            
            # Verify that sheet_name column exists
            if 'sheet_name' not in line_item_df.columns:
                print("CRITICAL: sheet_name column missing!")
                print(f"Available columns: {list(line_item_df.columns)}")
                print(f"Raw data sample: {line_items_data[0] if line_items_data else 'No data'}")
                raise KeyError("sheet_name column missing from DataFrame")
            
            # Debug: Log the available columns for troubleshooting
            print(f"SUCCESS: Available columns in DataFrame: {list(line_item_df.columns)}")
            print(f"Number of items processed: {len(line_item_df)}")
            
            # Check for items with null/empty sheet_name
            items_without_sheet_name = line_item_df[
                (line_item_df['sheet_name'].isna()) | 
                (line_item_df['sheet_name'] == '') | 
                (line_item_df['sheet_name'] == 'None')
            ]
            
            if not items_without_sheet_name.empty:
                problematic_refs = items_without_sheet_name['ref_no'].tolist()
                problematic_items = items_without_sheet_name[['ref_no', 'item', 'mpi_item']].to_dict('records')
                raise ValueError(f"Items with missing sheet_name found: {problematic_items}")
            
        except KeyError as e:
            # Sheet name column is missing entirely
            raise HTTPException(
                status_code=400,
                detail=f"Missing sheet_name data in DataFrame. Reference numbers: {ref_numbers}. Error: {str(e)}"
            )
        except ValueError as e:
            # Items have null/empty sheet_name values
            raise HTTPException(
                status_code=400,
                detail=f"Items with null/empty sheet_name found. {str(e)}"
            )
        except Exception as e:
            # For any other exception, also return reference numbers
            print(f"Unexpected error in QB export: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=400,
                detail=f"Error processing data: {str(e)}. Reference numbers: {ref_numbers}"
            )
            
        # Apply classification with error handling
        def get_classification_safe(sheet_name):
            if not sheet_name or sheet_name in ['None', '', None]:
                return ''
            return ItemClassificationController(db).get_classification(sheet_name)
        
        # Initialize the account column
        line_item_df['account'] = ''
        
        # Identify invoices (by ref_no) that have ANY class 'A' or 'L' items
        invoices_with_class_a = line_item_df[line_item_df['class_'] == 'A']['ref_no'].unique()
        invoices_with_class_l = line_item_df[line_item_df['class_'] == 'L']['ref_no'].unique()
        
        # For invoices with ANY class 'A' item, assign ALL items to Additional Material
        if len(invoices_with_class_a) > 0:
            class_a_invoice_mask = line_item_df['ref_no'].isin(invoices_with_class_a)
            line_item_df.loc[class_a_invoice_mask, 'account'] = 'UnInvoiced JIP:Material:Additional Material'
        
        # For invoices with ANY class 'L' item, assign ALL items to Labor (only if not already assigned to class A)
        if len(invoices_with_class_l) > 0:
            class_l_invoice_mask = line_item_df['ref_no'].isin(invoices_with_class_l) & (line_item_df['account'] == '')
            line_item_df.loc[class_l_invoice_mask, 'account'] = 'UnInvoiced JIP:Subcontractors Expense:Labor'
        
        # For all remaining items (invoices with no class A or L), apply normal logic
        unassigned_mask = line_item_df['account'] == ''
        
        # Apply sheet_name classification to unassigned items
        if unassigned_mask.any():
            line_item_df.loc[unassigned_mask, 'account'] = line_item_df.loc[unassigned_mask, 'sheet_name'].apply(get_classification_safe)

        # Map specific items to accounts (only for items still unassigned after class logic)
        # This ensures class A and L invoices don't get overridden
        unassigned_mask = line_item_df['account'] == ''
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Job Materials Purchased') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Job Equipment') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Equipments Purchased'
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Sprinkler specialty item') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'
        
        line_item_df.loc[
            (line_item_df['mpi_item'] == 'UIDI-Drainage Material') & unassigned_mask, 'account'
        ] = 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased'

        line_item_df['account'] = line_item_df['account'].replace([None, 'None'], '')

        # Identify missing accounts and log invoice details
        unmatched_items = line_item_df[line_item_df['account'] == '']
        if not unmatched_items.empty:
            unmatched_references = unmatched_items[['mpi_item', 'ref_no']].drop_duplicates()
            unmatched_references_list = unmatched_references.to_dict(orient='records')

            raise HTTPException(
                status_code=400,
                detail=f"Unmatched items or sheet names are present, 'unmatched_references': {unmatched_references_list}"
            )

        line_item_df = line_item_df.astype(str)
        float_columns = ['qty', 'cost', 'amount']
        line_item_df[float_columns] = line_item_df[float_columns].astype(float)

        batch_entry = line_item_df.groupby(['account', 'ref_no', 'customer_job']).agg({
            'amount': 'sum',
            'date': 'first',
            'vendor': 'first',
            'memo': 'first',
            'class_': 'first'
        }).reset_index()

        batch_entry['date'] = pd.to_datetime(batch_entry['date']).dt.strftime('%m/%d/%Y')
        batch_entry['amount'] = batch_entry['amount'].apply(lambda x: x+tax)
        batch_entry['terms'] = ''
        batch_entry['bill due'] = ''

        batch_entry.rename(columns = {
            'date': 'Date', 
            'ref_no': 'Ref', 
            'amount': 'Amount', 
            'customer_job': 'Customer Job', 
            'class_': 'Class', 
            'memo': 'Memo'
        }, inplace=True)
        
        batch_entry = batch_entry[[
            'Date', 'Ref', 'vendor', 'terms', 'bill due', 
            'account', 'Amount', 'Memo', 'Customer Job', 'Class'
        ]]
        all_batch_entries.append(batch_entry)

        # track & manage invoice export status
        invoice_item_ids = [item.id for item in line_item_copy if item.id]
        InvoiceItemController(db).set_export_status_to_sent(invoice_item_ids)

        if InvoiceItemController(db).is_exported(str(invoice_id)):
            InvoiceController(db).set_invoice_is_exported(str(invoice_id))

    final_batch_entry = pd.concat(all_batch_entries, ignore_index=True)
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    
    # Upload to S3 and get download URL
    upload_file(
        exported_file_path, 
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )
    download_url = get_presigned_url(
        file_key=f'Exports/{file_name}', 
        is_invoice=False
    )

    return download_url

@router.get("/debug-invoice/{invoice_id}")
def debug_invoice_items(invoice_id: UUID, db: Session = Depends(get_db)):
    """
    Debug endpoint to test invoice item retrieval and conversion.
    This helps isolate the issue with missing sheet_name.
    """
    try:
        print(f"\n=== DEBUG INVOICE {invoice_id} ===")
        
        # Test both methods
        controller = InvoiceItemController(db)
        
        # Test raw method
        print("1. Testing get_invoice_items_raw...")
        raw_items = controller.get_invoice_items_raw(invoice_id)
        print(f"Raw items count: {len(raw_items)}")
        
        # Test regular method  
        print("2. Testing get_invoice_items...")
        regular_items = controller.get_invoice_items(invoice_id)
        print(f"Regular items count: {len(regular_items)}")
        
        if raw_items:
            sample_raw = raw_items[0]
            print(f"Raw item sample:")
            print(f"  - Type: {type(sample_raw)}")
            print(f"  - Has sheet_name: {hasattr(sample_raw, 'sheet_name')}")
            print(f"  - sheet_name value: {getattr(sample_raw, 'sheet_name', 'MISSING')}")
            print(f"  - __dict__ keys: {list(sample_raw.__dict__.keys())}")
            
            # Test conversion
            print("3. Testing conversion to dict...")
            item_dict = sample_raw.__dict__.copy()
            item_dict.pop('_sa_instance_state', None)
            print(f"  - Dict keys: {list(item_dict.keys())}")
            print(f"  - sheet_name in dict: {'sheet_name' in item_dict}")
            print(f"  - sheet_name value: {item_dict.get('sheet_name', 'MISSING FROM DICT')}")
            
            # Test DataFrame creation
            print("4. Testing DataFrame creation...")
            import pandas as pd
            df = pd.DataFrame([item_dict])
            print(f"  - DataFrame columns: {list(df.columns)}")
            print(f"  - sheet_name in DataFrame: {'sheet_name' in df.columns}")
            
        return {
            "status": "debug_complete",
            "raw_items_count": len(raw_items),
            "regular_items_count": len(regular_items),
            "sample_raw_sheet_name": getattr(raw_items[0], 'sheet_name', None) if raw_items else None,
            "sample_raw_ref_no": getattr(raw_items[0], 'ref_no', None) if raw_items else None
        }
        
    except Exception as e:
        import traceback
        print(f"Debug error: {str(e)}")
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }