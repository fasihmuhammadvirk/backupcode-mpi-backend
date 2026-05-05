"""
QuickBooks Controller - Business logic for QuickBooks export operations
"""
from typing import List, Dict, Optional
from fastapi import HTTPException
import pandas as pd
import logging
from mpi_backend.database.models import InvoiceItemMart
from mpi_backend.utils.quickbooks_export_utils import convert_quickbooks_items_to_dataframe, save_quickbooks_excel
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER
import os
import uuid
from mpi_backend.utils.s3_utils import upload_export_and_get_url
from datetime import datetime, date
import json
from mpi_backend.database.schemas import QuickBooksPreviewItem
from mpi_backend.database.dao import quickbooks_dao
from mpi_backend.database import SessionLocal
from mpi_backend.utils.dbt_scheduler import get_dbt_runner

logger = logging.getLogger(__name__)


class QuickBooksController:
    """Controller for QuickBooks export business logic"""
    
    def __init__(self, db):
        self.db_context = db
        self.FIXED_TAX_RATE = 0.08875
    
    @staticmethod
    def is_tax_item(item) -> bool:
        """
        Check if an item is a tax line item.
        Tax items have "tax" in memo, item, or description fields.
        
        Args:
            item: InvoiceItem object or dict-like object with memo, item, description fields
            
        Returns:
            True if item is a tax item, False otherwise
        """
        item_memo = getattr(item, 'memo', '') or ''
        item_item = getattr(item, 'item', '') or ''
        item_description = getattr(item, 'description', '') or ''
        
        return ('tax' in item_memo.lower() or 
                'tax' in item_item.lower() or 
                'tax' in item_description.lower())
    
    def get_account_full_path(self, account_code: str) -> str:
        """
        Convert account code to full QuickBooks path.
        
        Args:
            account_code: Short code (M, E, A, UNMAPPED) or already full path
            
        Returns:
            Full QuickBooks GL path
        """
        # If already a full path, return as-is
        if ':' in account_code:
            return account_code
        
        # Map short codes to full paths
        mapping = {
            'M': 'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased',
            'E': 'UnInvoiced JIP:Cost Of Materials:Job Equipment',
            'A': 'UnInvoiced JIP:Subcontractors Expense:Labor & Material:Additional Material',
            'UNMAPPED': 'UNMAPPED ITEMS'
        }
        
        return mapping.get(account_code.upper(), mapping['M'])

    def get_account_short_form(self, account_full_path: str) -> str:
        """
        Convert full QuickBooks path back to short code.

        Args:
            account_full_path: Full QuickBooks GL path

        Returns:
            Short code (M, E, A, or UNMAPPED)
        """
        # If it's already a short code or empty, return as-is
        if account_full_path in ['M', 'E', 'A', 'UNMAPPED', '']:
            return account_full_path

        # Reverse mapping from full paths to short codes
        reverse_mapping = {
            'UnInvoiced JIP:Cost Of Materials:Job Materials Purchased': 'M',
            'UnInvoiced JIP:Cost Of Materials:Job Equipment': 'E',
            'UnInvoiced JIP:Subcontractors Expense:Labor & Material:Additional Material': 'A',
            'UNMAPPED ITEMS': 'UNMAPPED'
        }

        return reverse_mapping.get(account_full_path)
    
    
    def get_preview_export(
        self,
        start_date,
        end_date,
        invoice_filter: str
    ) -> List[QuickBooksPreviewItem]:
        """
        Get QuickBooks preview items for a date range.

        Uses the pre-computed mart__quickbooks_preview table for performance.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            invoice_filter: "unprocessed" or "all"

        Returns:
            List of QuickBooksPreviewItem objects
        """
        only_unprocessed = (invoice_filter == "unprocessed")

        mart_items = quickbooks_dao.get_preview_from_mart(
            self.db_context,
            start_date,
            end_date,
            only_unprocessed
        )

        if not mart_items:
            logger.info("No preview items found in mart for the given date range")
            return []

        # Convert the dicts (from JSONB) into QuickBooksPreviewItem pydantic models
        preview_items = [
            QuickBooksPreviewItem(**item)
            for item in mart_items
        ]

        logger.info(
            f"QB Preview (mart): Returning {len(preview_items)} preview items "
            f"for {start_date} to {end_date} (filter={invoice_filter})"
        )
        return preview_items
    
    def _process_single_invoice(
        self,
        invoice_items_df: pd.DataFrame,
        total_row_for_all_invoice: bool
    ) -> List[QuickBooksPreviewItem]:
        """
        Process a single invoice and return preview items.
        
        Args:
            invoice_items_df: DataFrame of items for this invoice
            
        Returns:
            List of QuickBooksPreviewItem objects for this invoice
        """

        # Create explicit copy to avoid SettingWithCopyWarning
        invoice_items_df = invoice_items_df.copy()

        ref_no = invoice_items_df['ref_no'].iloc[0]
        date = invoice_items_df['date'].iloc[0]
        vendor = invoice_items_df['vendor'].iloc[0]
        customer_job = invoice_items_df['customer_job'].iloc[0]
        invoice_id = invoice_items_df['invoice_id'].iloc[0]
        filename = invoice_items_df['filename'].iloc[0] if 'filename' in invoice_items_df.columns else None

        # Calculate total with OUR fixed tax rate
        items_pretax_total = invoice_items_df['amount'].sum()
        authoritative_total = items_pretax_total * (1 + self.FIXED_TAX_RATE)

        invoice_items_df['account'] = invoice_items_df['account'].apply(self.get_account_short_form)
        invoice_items_df['class_'] = invoice_items_df['class_'].fillna('').astype(str).str.strip()
        
        # Handle items with empty accounts (unmapped items)
        # Instead of excluding them, group them together as 'UNMAPPED'
        empty_accounts = invoice_items_df[(invoice_items_df['account'] == '') | invoice_items_df['account'].isna()]
        if not empty_accounts.empty:
            logger.info(
                f"Invoice {ref_no}: Found {len(empty_accounts)} unmapped items. "
                f"These will be grouped together as 'UNMAPPED'. "
                f"Item IDs: {empty_accounts['id'].tolist()}"
            )
            invoice_items_df.loc[invoice_items_df['account'] == '', 'account'] = 'UNMAPPED'

        finishings_mask = invoice_items_df['class_'].str.lower().str.startswith('finishing', na=False)
        invoice_items_df.loc[finishings_mask, 'account'] = 'M'

        # Sort items: Finishing first, then Account M
        invoice_items_df['sort_priority'] = 2
        invoice_items_df.loc[finishings_mask, 'sort_priority'] = 0
        invoice_items_df.loc[~finishings_mask & (invoice_items_df['account'] == 'M'), 'sort_priority'] = 1
        invoice_items_df = invoice_items_df.sort_values('sort_priority', kind='stable').drop(columns=['sort_priority'])

        invoice_items_df['grouping_key'] = invoice_items_df.apply(
            lambda row: f"{row['account']}_FINISHINGS" if (row['class_'] and row['class_'].lower().startswith('finishing')) 
            else row['account'],
            axis=1
        )

        # group_key = np.where(invoice_items_df['grouping_key'] == "UNMAPPED", invoice_items_df.index.astype(str), invoice_items_df['grouping_key'])
        # grouped = invoice_items_df.groupby(group_key, sort=False)
        grouped = invoice_items_df.groupby('grouping_key', sort=False)
        
        # Calculate splits with fixed tax rate
        split_totals = []
        for grouping_key, group in grouped:
            # Determine if this is a finishings group   
            is_finishings = '_FINISHINGS' in grouping_key

            account = group['account'].iloc[0]
            
            group_amount = group['amount'].sum()
            group_total_with_tax = group_amount * (1 + self.FIXED_TAX_RATE)

            split_totals.append({
                'account': account,
                'class': group['class_'].iloc[0],
                'amount': group_amount,
                'total_with_tax': group_total_with_tax,
                'items': group,
                'is_finishings': is_finishings
            })
        
        # Build preview items for each split
        preview_items = []
        running_sum = 0
        
        for i, split in enumerate(split_totals):
            if i < len(split_totals) - 1:
                rounded_total = round(split['total_with_tax'], 2)
                running_sum += rounded_total
            else:
                # Last split: ensure exact match to authoritative total
                rounded_total = round(authoritative_total - running_sum, 2)

            account_full_path = self.get_account_full_path(split['account'])
            group_tax = round(rounded_total / (1 + self.FIXED_TAX_RATE) * self.FIXED_TAX_RATE, 2)

            items_list = split['items'].to_dict('records')
            for item in items_list:
                item['id'] = str(item['id'])
            
            # Create single aggregated row for this account group
            preview_items.append(QuickBooksPreviewItem(
                id=str(split['items'].iloc[0]['id']),  # Use first item's ID for tracking
                items= items_list,
                invoice_id=str(invoice_id),
                date=pd.to_datetime(date, errors='coerce').strftime('%m/%d/%Y') if pd.notnull(date) else '',
                ref_no=ref_no,
                vendor=vendor,
                account=account_full_path,
                customer_job=customer_job,
                class_field=split['class'] or '',
                tax=group_tax,
                amount=rounded_total,  # Tax-inclusive amount for this group
                memo='',
                is_total_row=False,
                filename=filename
            ))

        unique_keys = set(f"{split.get('account','')}|{split.get('class','') or ''}" for split in split_totals)
        if (total_row_for_all_invoice) or (len(unique_keys) > 1 or (len(unique_keys) == 1 and unique_keys.pop() == 'UNMAPPED|')):
            # Prioritize material account for total row
            material_split = next(
                (s for s in split_totals if s['account'] == 'M'),
                split_totals[0]
            )
            
            material_account_path = self.get_account_full_path(material_split['account'])
            
            # Calculate total tax for the invoice
            total_tax = round(authoritative_total / (1 + self.FIXED_TAX_RATE) * self.FIXED_TAX_RATE, 2)
            
            preview_items.append(QuickBooksPreviewItem(
                id=None,
                invoice_id=str(invoice_id),
                date=pd.to_datetime(date, errors='coerce').strftime('%m/%d/%Y') if pd.notnull(date) else '',
                ref_no=ref_no,
                vendor=vendor,
                account=material_account_path,
                customer_job=customer_job,
                class_field='',
                tax=total_tax,
                amount=round(authoritative_total, 2),
                memo='',
                is_total_row=True,
                filename=filename
            ))
        
        return preview_items


    @staticmethod
    def filter_redundant_total_rows(items: List[QuickBooksPreviewItem]) -> List[QuickBooksPreviewItem]:
        """
        Efficiently remove total rows for export if an invoice has only one group.
        
        A total row is redundant in Excel if the invoice only has one account/class
        group (and it's not a standalone UNMAPPED group).
        """
        # Group items by logical invoice identity
        invoice_map = {}
        for item in items:
            key = (item.ref_no, item.vendor, item.date)
            if key not in invoice_map:
                invoice_map[key] = []
            invoice_map[key].append(item)

        filtered_results = []
        for key, group_items in invoice_map.items():
            non_totals = [it for it in group_items if not it.is_total_row]
            totals = [it for it in group_items if it.is_total_row]

            # Determine distinct account+class splits
            unique_groups = set()
            for it in non_totals:
                unique_groups.add((it.account or '', it.class_field or ''))
            
            # Rule: Keep total row if (splits > 1)
            should_keep_total = (len(unique_groups) > 1)

            filtered_results.extend(non_totals)
            if should_keep_total:
                filtered_results.extend(totals)

        return filtered_results

    def update_items_group(
            self,
            preview_items: List[QuickBooksPreviewItem],
            total_row_for_all_invoice: bool
    ) -> List[QuickBooksPreviewItem]:

        all_items = [item for preview_item in preview_items for item in (preview_item.items or [])]

        if not all_items:
            raise HTTPException(status_code=400, detail="No preview item details provided")

        df = pd.DataFrame(all_items)
        preview_items = []

        for _, invoice_group_df in df.groupby(['ref_no', 'vendor', 'date'], sort=False):
            preview_items.extend(
                self._process_single_invoice(
                    invoice_group_df,
                    total_row_for_all_invoice
                )
            )

        return preview_items

    
    def export_from_preview(
        self,
        items: List[QuickBooksPreviewItem],
        background_tasks=None
    ):
        """
        Export edited QuickBooks items to formatted Excel.
        
        Uses export_items_generic from export_utils for sync/async handling.
        Updates export_status to 'Sent' for all items.
        
        Args:
            items: List of edited preview items from frontend
            background_tasks: FastAPI BackgroundTasks for async processing
            
        Returns:
            - Sync: Presigned S3 URL
            - Async: Dict with export_id and status endpoint
        """
        
        if not items:
            raise HTTPException(status_code=400, detail="No items provided for export")

        # LIGHTWEIGHT: Just filter the redundant totals instead of full re-processing
        updated_items = self.filter_redundant_total_rows(items)

        items_dict = [item.model_dump(by_alias=True) for item in updated_items]

        df = convert_quickbooks_items_to_dataframe(items_dict)

        if df.empty:
            raise HTTPException(status_code=400, detail="No valid data to export")

        unmapped = df[df['Account'].isin(['', 'UNMAPPED ITEMS', 'UNMAPPED'])]
        if not unmapped.empty:
            unmapped_refs = unmapped[['Ref', 'Vendor']].drop_duplicates()
            unmapped_list = unmapped_refs.to_dict(orient='records')
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot export to QuickBooks: Found {len(unmapped)} items with unmapped accounts. "
                    f"Please add classifications for these items: {unmapped_list[:5]}"
                )
            )
        
        logger.info(f"Controller: Converted {len(df)} items to DataFrame for export")

        threshold = 1000
        record_count = len(df)
        export_id = str(uuid.uuid4())
        
        if record_count < threshold or background_tasks is None:
            # SYNC PROCESSING - Use custom QuickBooks Excel formatter
            logger.info(f"Controller: Processing QuickBooks export synchronously for {record_count} records")
            
            # Prepare file paths
            upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
            filename = f'QuickBooks_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_{export_id}.xlsx'
            file_path = f'{upload_folder}{filename}'
            
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)

            save_quickbooks_excel(df, file_path)

            download_url = upload_export_and_get_url(file_path)

            if updated_items and download_url is not None:
                logger.info("Controller: Inserting QuickBooks export records for items")
                # Build row dicts from updated_items — data already in memory,
                # so no second DB fetch is needed.
                rows_for_insert = []
                seen_ids = set()
                for preview_item in updated_items:
                    for raw in (preview_item.items or []):
                        raw_id = raw.get('id')
                        if raw_id and raw_id not in seen_ids:
                            seen_ids.add(raw_id)
                            rows_for_insert.append({
                                'id': raw_id,
                                'invoice_id': raw.get('invoice_id') or preview_item.invoice_id,
                                'ref_no': raw.get('ref_no', '') or '',
                                'vendor': raw.get('vendor', '') or '',
                                'date': raw.get('date'),
                            })
                inserted_count = quickbooks_dao.insert_quickbooks_export_records_from_rows(
                    self.db_context,
                    rows_for_insert
                )
                logger.info(f"Controller: Inserted {inserted_count} QuickBooks export records")

                # Trigger real-time mart refresh so 'Unprocessed' filter stays up to date
                if inserted_count > 0:
                    logger.info("Triggering targeted mart refresh for QuickBooks preview...")
                    runner = get_dbt_runner()
                    if background_tasks:
                        background_tasks.add_task(runner.try_refresh_materialized_views, models=["mart__quickbooks_preview"])
                    else:
                        # Fallback to sync call if no background_tasks (though usually provided via API)
                        runner.try_refresh_materialized_views(models=["mart__quickbooks_preview"])
            
            return download_url
        
        else:
            # ASYNC PROCESSING - Use background task
            logger.info(f"Controller: Processing QuickBooks export asynchronously for {record_count} records")

            upload_folder = f'{INVOICE_DOWNLOAD_FOLDER}/Exports/'
            export_status_file = f'{upload_folder}status_{export_id}.json'

            os.makedirs(upload_folder, exist_ok=True)
            with open(export_status_file, 'w') as f:
                json.dump({
                    'status': 'processing',
                    'export_id': export_id,
                    'record_count': record_count,
                    'started_at': datetime.now().isoformat(),
                    'message': 'QuickBooks export is being processed in the background'
                }, f)

            background_tasks.add_task(
                self._process_export_background,
                export_id=export_id,
                df=df,
                items_dict=items_dict,
                upload_folder=upload_folder
            )

            return {
                "export_id": export_id,
                "status": "processing",
                "record_count": record_count,
                "message": "Export is being processed. Use the export_id to check status.",
                "status_endpoint": f"/quickbooks/export-status/{export_id}"
            }
    
    @staticmethod
    def _process_export_background(
        export_id: str,
        df: pd.DataFrame,
        items_dict: List[Dict],
        upload_folder: str
    ):
        """
        Background task to process QuickBooks export.
        
        Args:
            export_id: Unique export ID
            df: DataFrame with QuickBooks data
            items_dict: List of dicts with QuickBooks data
            upload_folder: Folder for export files
        """
        export_status_file = f'{upload_folder}status_{export_id}.json'
        db = SessionLocal()
        inserted_count = 0
        try:
            logger.info(f"Controller: Background QuickBooks export {export_id} starting")

            filename = f'QuickBooks_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_{export_id}.xlsx'
            file_path = f'{upload_folder}{filename}'

            save_quickbooks_excel(df, file_path)

            download_url = upload_export_and_get_url(file_path)

            if items_dict:
                logger.info(f"Controller: Inserting QuickBooks export records for {len(items_dict)} preview groups (background)")

                # Convert items_dict back to flat rows for insertion
                rows_for_insert = []
                seen_ids = set()
                for preview_item in items_dict:
                    # Each preview_item contains a list of original raw items
                    for raw in (preview_item.get('items') or []):
                        raw_id = raw.get('id')
                        if raw_id and raw_id not in seen_ids:
                            seen_ids.add(raw_id)
                            rows_for_insert.append({
                                'id': raw_id,
                                'invoice_id': raw.get('invoice_id') or preview_item.get('invoice_id'),
                                'ref_no': raw.get('ref_no', '') or '',
                                'vendor': raw.get('vendor', '') or '',
                                'date': raw.get('date'),
                            })

                inserted_count = quickbooks_dao.insert_quickbooks_export_records_from_rows(db, rows_for_insert)
                logger.info(f"Controller: Inserted {inserted_count} QuickBooks export records")

            db.commit()

            # Trigger real-time mart refresh from background thread
            if inserted_count > 0:
                logger.info("Triggering mart refresh from background export task...")
                runner = get_dbt_runner()
                runner.try_refresh_materialized_views(models=["mart__quickbooks_preview"])

            with open(export_status_file, 'w') as f:
                json.dump({
                    'status': 'completed',
                    'export_id': export_id,
                    'download_url': download_url,
                    'completed_at': datetime.now().isoformat(),
                    'message': 'QuickBooks export completed successfully'
                }, f)
            logger.info(f"Controller: Background QuickBooks export {export_id} completed")
        except Exception as e:
            logger.error(f"Controller: Background QuickBooks export {export_id} failed - {str(e)}")
            if db:
                db.rollback()
            # Update status file with error
            try:
                with open(export_status_file, 'w') as f:
                    json.dump({
                        'status': 'failed',
                        'export_id': export_id,
                        'error': str(e),
                        'failed_at': datetime.now().isoformat(),
                        'message': 'QuickBooks export failed'
                    }, f)
            except Exception as status_error:
                logger.error(f"Controller: Failed to update status file: {status_error}")
        finally:
            if db:
                db.close()

    def get_unprocessed_date_range(self) -> Dict[str, Optional[date]]:
        """
        Get the oldest and latest invoice date for unprocessed items.
        
        Returns:
            Dictionary with oldest_date and latest_date
        """
        return quickbooks_dao.get_unprocessed_invoice_date_range(self.db_context)
