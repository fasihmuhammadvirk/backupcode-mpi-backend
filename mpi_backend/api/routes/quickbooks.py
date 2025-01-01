from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
import pyodbc
import pandas as pd
from mpi_backend.database import get_db
from mpi_backend.database.controllers import InvoiceItemController,InvoiceController, ItemClassificationController
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.utils.pdf_to_excel.formatting_util import export_batch_entry_to_excel
from mpi_backend.utils.s3_utils import upload_file, get_presigned_url
import os

router = APIRouter(prefix="/quickbooks")


@router.post("/migrate")
def migrate_invoice_to_QB(
        invoice_ids: List[UUID], db: Session = Depends(get_db)):
    all_batch_entries = []

    for invoice_id in invoice_ids:
        line_items = InvoiceItemController(db).get_invoice_items(invoice_id)
        line_item_copy = line_items

        tax = 0
        for item in line_items:
            if item.sheet_name == '(TAX)': tax = float(item.amount.replace(',',''))

        line_items = [item for item in line_items if item.sheet_name != '(TAX)']

        line_item_df = pd.DataFrame([vars(item) for item in line_items])
        line_item_df['account'] = line_item_df['sheet_name'].apply(lambda sheet_name: ItemClassificationController(db).get_classification(sheet_name))
        line_item_df['account'] = line_item_df['account'].replace([None, 'None'], '')

        line_item_df = line_item_df.astype(str)
        float_columns = ['qty', 'cost','amount']
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

        batch_entry.rename(columns = {'date':'Date', 'ref_no':'Ref', 'amount':'Amount', 'customer_job':'Customer Job', 'class_':'Class', 'memo':'Memo'}, inplace=True)
        batch_entry = batch_entry[['Date','Ref','vendor','terms','bill due','account','Amount','Memo','Customer Job','Class']]
        all_batch_entries.append(batch_entry)

        # track & manage invoice export status
        invoice_item_ids = [item.id for item in line_item_copy if item.id] # get all line item row ids
        InvoiceItemController(db).set_export_status_to_sent(invoice_item_ids)  # update line item export status to sent

        if InvoiceItemController(db).is_exported(str(invoice_id)):
            InvoiceController(db).set_invoice_is_exported(str(invoice_id))

    final_batch_entry = pd.concat(all_batch_entries, ignore_index=True)
    exported_file_path = export_batch_entry_to_excel(final_batch_entry)
    file_name = os.path.basename(exported_file_path)
    upload_file(exported_file_path, file_key=f'Exports/{file_name}', is_invoice=False)  # upload to s3 to be exported
    download_url = get_presigned_url(file_key=f'Exports/{file_name}', is_invoice=False)

    return download_url