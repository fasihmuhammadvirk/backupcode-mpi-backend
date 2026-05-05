"""
ONE-TIME SETUP: FORCE UPDATE ALL SHEET NAMES TO CANONICAL NAMES

This is a ONE-TIME setup script that:
1. Syncs all 64 sheets from Google Sheets
2. Uses 100% DYNAMIC fuzzy matching to match database variations to canonical names
3. Assigns sheet_id to ALL records
4. Updates ALL records to use canonical sheet names

After running this ONCE:
- All records will have sheet_id
- All records will have consistent canonical names
- Future extractions will just use sheet_id (no more name matching needed)

NO HARDCODED SHEET NAMES - fully dynamic based on what's in Google Sheets.

Usage:
    cd mpi-backend
    conda activate mpi-backend
    python scripts/force_update_all_sheet_names.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mpi_backend.database import SessionLocal
from mpi_backend.database.models.ItemsMapping import ItemsMapping
from mpi_backend.database.models.TemporaryItemMapping import TempItemMapping
from mpi_backend.utils.sheet_name_manager import SheetNameManager
from mpi_backend.config.spreadsheet_config import DEFAULT_SHEET_ID, GOOGLE_API_KEY
from sqlalchemy import func
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("\n" + "=" * 100)
    logger.info("ONE-TIME SETUP - MAKING ALL SHEET NAMES CONSISTENT")
    logger.info("=" * 100)
    logger.info("\nWORKFLOW:")
    logger.info("1. Sync from Google Sheets → get 64 canonical sheet names")
    logger.info("2. Find ALL variations in database (NO-HUB, COPPER, etc.)")
    logger.info("3. Use 100% DYNAMIC fuzzy matching → match variations to canonical")
    logger.info("4. Assign sheet_id to ALL records")
    logger.info("5. Update ALL names to canonical")
    logger.info("6. After this, ONLY sheet_id will be used (no more name matching)")
    logger.info("=" * 100)
    
    db = SessionLocal()
    
    try:
        # Step 1: Sync metadata from Google
        logger.info("\n📥 STEP 1: Syncing from Google Sheets...")
        sheet_manager = SheetNameManager(db, DEFAULT_SHEET_ID, GOOGLE_API_KEY)
        sync_result = sheet_manager.sync_sheet_metadata_from_google()
        
        if not sync_result['success']:
            logger.error(f"❌ Failed to sync: {sync_result['message']}")
            return False
        
        logger.info(f"✅ Synced {sync_result['synced_count']} sheets from Google")
        
        # Get canonical mappings
        from mpi_backend.database.controllers.google_sheet_metadata_controller import (
            GoogleSheetMetadataController
        )
        controller = GoogleSheetMetadataController(db)
        sheet_id_to_name = controller.get_all_sheet_mappings(DEFAULT_SHEET_ID)
        name_to_id = {name: sid for sid, name in sheet_id_to_name.items()}
        
        logger.info(f"📋 Got {len(sheet_id_to_name)} canonical sheet names")
        
        # Step 2: Build ALL variations mapping
        logger.info("\n🔍 STEP 2: Finding ALL sheet name variations...")
        
        # Import InvoiceItem here
        from mpi_backend.database.models.InvoiceItems import InvoiceItem
        
        all_supplier_names = db.query(ItemsMapping.google_sheet_name).distinct().all()
        all_supplier_names = [n[0] for n in all_supplier_names if n[0]]
        
        all_temp_names = db.query(TempItemMapping.sheet_name).distinct().all()
        all_temp_names = [n[0] for n in all_temp_names if n[0]]
        
        # IMPORTANT: Include invoice_items sheet names!
        all_invoice_names = db.query(InvoiceItem.sheet_name).execution_options(include_all=True).distinct().all()
        all_invoice_names = [n[0] for n in all_invoice_names if n[0]]
        
        all_unique_names = set(all_supplier_names + all_temp_names + all_invoice_names)
        logger.info(f"Found {len(all_supplier_names)} from supplier_item_mappings")
        logger.info(f"Found {len(all_temp_names)} from temporary_item_mappings")
        logger.info(f"Found {len(all_invoice_names)} from invoice_items")
        logger.info(f"Total unique sheet name variations: {len(all_unique_names)}")
        
        # Fuzzy match ALL variations
        logger.info("\n🎯 STEP 3: Matching variations to canonical names...")
        variation_to_canonical_id = {}
        matched = 0
        
        for variation in sorted(all_unique_names):
            # Try exact match first
            if variation in name_to_id:
                canonical_id = name_to_id[variation]
                variation_to_canonical_id[variation] = canonical_id
                matched += 1
            else:
                # Fuzzy match
                canonical_id = sheet_manager._fuzzy_match_sheet_name(variation, name_to_id)
                if canonical_id:
                    canonical_name = sheet_id_to_name[canonical_id]
                    variation_to_canonical_id[variation] = canonical_id
                    logger.info(f"  📍 '{variation}' → '{canonical_name}'")
                    matched += 1
                else:
                    logger.warning(f"  ⚠️  Could not match: '{variation}'")
        
        logger.info(f"\n✅ Matched {matched} / {len(all_unique_names)} variations")
        
        # Step 4: UPDATE EVERYTHING
        logger.info("\n💾 STEP 4: FORCE UPDATING ALL RECORDS...")
        
        # Update supplier_item_mappings
        logger.info("\nUpdating supplier_item_mappings...")
        supplier_records = db.query(ItemsMapping).all()
        supplier_updated = 0
        supplier_assigned_id = 0
        
        for record in supplier_records:
            old_name = record.google_sheet_name
            if old_name in variation_to_canonical_id:
                canonical_id = variation_to_canonical_id[old_name]
                canonical_name = sheet_id_to_name[canonical_id]
                
                # Update sheet_id if needed
                if record.sheet_id != canonical_id:
                    record.sheet_id = canonical_id
                    supplier_assigned_id += 1
                
                # FORCE update name to canonical
                if record.google_sheet_name != canonical_name:
                    record.google_sheet_name = canonical_name
                    supplier_updated += 1
        
        # Update temporary_item_mappings
        logger.info("\nUpdating temporary_item_mappings...")
        temp_records = db.query(TempItemMapping).all()
        temp_updated = 0
        temp_assigned_id = 0
        
        for record in temp_records:
            old_name = record.sheet_name
            if old_name in variation_to_canonical_id:
                canonical_id = variation_to_canonical_id[old_name]
                canonical_name = sheet_id_to_name[canonical_id]
                
                # Update sheet_id if needed
                if record.sheet_id != canonical_id:
                    record.sheet_id = canonical_id
                    temp_assigned_id += 1
                
                # FORCE update name to canonical
                if record.sheet_name != canonical_name:
                    record.sheet_name = canonical_name
                    temp_updated += 1
        
        # Update invoice_items (THIS IS THE BIG ONE - 217K+ records!)
        logger.info("\nUpdating invoice_items...")
        
        invoice_records = db.query(InvoiceItem).execution_options(include_all=True).all()
        invoice_updated = 0
        
        logger.info(f"Processing {len(invoice_records):,} invoice items...")
        
        for i, record in enumerate(invoice_records, 1):
            old_name = record.sheet_name
            if old_name and old_name in variation_to_canonical_id:
                canonical_id = variation_to_canonical_id[old_name]
                canonical_name = sheet_id_to_name[canonical_id]
                
                # FORCE update name to canonical
                if record.sheet_name != canonical_name:
                    record.sheet_name = canonical_name
                    invoice_updated += 1
            
            # Progress indicator
            if i % 50000 == 0:
                logger.info(f"  Processed {i:,} / {len(invoice_records):,} invoice items...")
        
        # COMMIT
        db.commit()
        logger.info(f"\n✅ COMMITTED ALL CHANGES TO DATABASE")
        
        # Step 5: Verify
        logger.info("\n🔍 STEP 5: VERIFICATION...")
        
        # Check NO-HUB in supplier_item_mappings
        logger.info("\nSupplier Item Mappings:")
        nohub_variations = db.query(
            ItemsMapping.google_sheet_name,
            func.count(ItemsMapping.id)
        ).filter(
            ItemsMapping.google_sheet_name.ilike('%NO-HUB%')
        ).group_by(
            ItemsMapping.google_sheet_name
        ).all()
        
        logger.info(f"  NO-HUB variations: {len(nohub_variations)}")
        for name, count in nohub_variations:
            logger.info(f"    {count:5} records | '{name}'")
        
        # Check COPPER in supplier_item_mappings
        copper_variations = db.query(
            ItemsMapping.google_sheet_name,
            func.count(ItemsMapping.id)
        ).filter(
            ItemsMapping.google_sheet_name.ilike('%COPPER%')
        ).group_by(
            ItemsMapping.google_sheet_name
        ).all()
        
        logger.info(f"  COPPER variations: {len(copper_variations)}")
        for name, count in copper_variations:
            logger.info(f"    {count:5} records | '{name}'")
        
        # Check records without sheet_id
        no_id = db.query(ItemsMapping).filter(ItemsMapping.sheet_id.is_(None)).count()
        total = db.query(ItemsMapping).count()
        logger.info(f"  Records without sheet_id: {no_id:,} / {total:,}")
        
        # Check INVOICE_ITEMS (THE IMPORTANT ONE!)
        logger.info("\nInvoice Items:")
        nohub_invoice = db.query(
            InvoiceItem.sheet_name,
            func.count(InvoiceItem.id)
        ).execution_options(include_all=True).filter(
            InvoiceItem.sheet_name.ilike('%NO-HUB%')
        ).group_by(
            InvoiceItem.sheet_name
        ).all()
        
        logger.info(f"  NO-HUB variations: {len(nohub_invoice)}")
        for name, count in nohub_invoice:
            logger.info(f"    {count:6} records | '{name}'")
        
        copper_invoice = db.query(
            InvoiceItem.sheet_name,
            func.count(InvoiceItem.id)
        ).execution_options(include_all=True).filter(
            InvoiceItem.sheet_name.ilike('%COPPER%')
        ).group_by(
            InvoiceItem.sheet_name
        ).all()
        
        logger.info(f"  COPPER variations: {len(copper_invoice)}")
        for name, count in copper_invoice:
            logger.info(f"    {count:6} records | '{name}'")
        
        # Summary
        logger.info("\n" + "=" * 100)
        logger.info("✅ FORCE UPDATE COMPLETE!")
        logger.info("=" * 100)
        logger.info(f"Supplier mappings: {supplier_assigned_id:,} sheet_ids assigned, {supplier_updated:,} names updated")
        logger.info(f"Temp mappings:     {temp_assigned_id:,} sheet_ids assigned, {temp_updated:,} names updated")
        logger.info(f"Invoice items:     {invoice_updated:,} names updated")
        
        if len(nohub_invoice) == 1 and len(copper_invoice) <= 2:
            logger.info("\n🎉 SUCCESS! ALL sheet names are now consistent!")
        else:
            logger.warning("\n⚠️  Some variations still exist - check the output above")
        
        logger.info("=" * 100 + "\n")
        
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

