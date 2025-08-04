#!/usr/bin/env python3
"""
Script to identify and clean up duplicate invoices in the database.
This script finds invoices with the same ref_no, vendor, date, and amount,
and provides options to clean them up by keeping only the most recent one.
"""
from mpi_backend.database.controllers.InvoiceItems import InvoiceItemController
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.database import get_db
from sqlalchemy import func
from datetime import datetime
import sys
import os
import logging
from pathlib import Path

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_all_duplicate_invoices(db):
    """
    Find all duplicate invoices in the database.

    Returns:
        List of duplicate groups with details
    """
    try:
        # Query to find invoices with the same ref_no, vendor, date, and amount
        duplicate_query = db.query(
            InvoiceItem.ref_no,
            InvoiceItem.vendor,
            InvoiceItem.date,
            func.sum(InvoiceItem.amount).label('total_amount'),
            func.count(InvoiceItem.invoice_id.distinct()
                       ).label('invoice_count')
        ).filter(
            InvoiceItem.is_active == True,
            InvoiceItem.ref_no.isnot(None),
            InvoiceItem.ref_no != '',
            InvoiceItem.vendor.isnot(None),
            InvoiceItem.vendor != ''
        ).group_by(
            InvoiceItem.ref_no,
            InvoiceItem.vendor,
            InvoiceItem.date
        ).having(
            func.count(InvoiceItem.invoice_id.distinct()) > 1
        ).all()

        duplicate_groups = []

        for ref_no, vendor, date, total_amount, invoice_count in duplicate_query:
            # Get all invoice IDs for this duplicate group
            invoice_ids = db.query(InvoiceItem.invoice_id.distinct()).filter(
                InvoiceItem.ref_no == ref_no,
                InvoiceItem.vendor == vendor,
                InvoiceItem.date == date,
                InvoiceItem.is_active == True
            ).all()

            invoice_id_list = [str(id[0]) for id in invoice_ids]

            duplicate_groups.append({
                'ref_no': ref_no,
                'vendor': vendor,
                'date': date,
                'total_amount': total_amount,
                'invoice_count': invoice_count,
                'invoice_ids': invoice_id_list
            })

        return duplicate_groups

    except Exception as e:
        logger.error(f"Error finding duplicate invoices: {str(e)}")
        return []


def cleanup_duplicate_group(db, ref_no, vendor, date, amount, keep_most_recent=True, delete_duplicates=False):
    """
    Clean up a specific duplicate group.

    Args:
        db: Database session
        ref_no: Reference number
        vendor: Vendor name
        date: Invoice date
        amount: Total amount
        keep_most_recent: If True, keep the most recent invoice
        delete_duplicates: If True, delete duplicates instead of marking as inactive

    Returns:
        Dict with cleanup results
    """
    try:
        if delete_duplicates:
            # Use the new delete method
            result = delete_duplicate_invoices(
                db, ref_no, vendor, date, amount, keep_most_recent)
        else:
            # Use the existing cleanup method (mark as inactive)
            controller = InvoiceItemController(db)
            result = controller.cleanup_duplicate_invoices(
                ref_no, vendor, date, amount, keep_most_recent
            )
        return result
    except Exception as e:
        logger.error(f"Error cleaning up duplicate group: {str(e)}")
        return {
            'status': 'error',
            'message': f'Error cleaning up duplicates: {str(e)}',
            'kept_invoice_id': None,
            'removed_count': 0
        }


def delete_duplicate_invoices(db, ref_no, vendor, date, amount, keep_most_recent=True):
    """
    Delete duplicate invoices with the same ref_no, vendor, date, and amount.
    This method permanently deletes the duplicate records from the database.

    Args:
        db: Database session
        ref_no: Reference number
        vendor: Vendor name
        date: Invoice date
        amount: Total amount
        keep_most_recent: If True, keep the most recent invoice; if False, keep the oldest

    Returns:
        Dict with deletion results
    """
    try:
        # Find duplicate invoice IDs
        duplicate_ids = find_duplicate_invoice_ids(
            db, ref_no, vendor, date, amount)

        if len(duplicate_ids) <= 1:
            return {
                'status': 'no_duplicates',
                'message': f'No duplicates found for RefNo: {ref_no}, Vendor: {vendor}',
                'kept_invoice_id': duplicate_ids[0] if duplicate_ids else None,
                'removed_count': 0
            }

        # Get the invoice to keep (most recent or oldest)
        if keep_most_recent:
            # Find the most recent invoice by date_added
            most_recent_item = db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id.in_(duplicate_ids)
            ).order_by(InvoiceItem.date_added.desc(), InvoiceItem.id.desc()).first()

            keep_invoice_id = most_recent_item.invoice_id if most_recent_item else duplicate_ids[
                0]
        else:
            # Find the oldest invoice by date_added
            oldest_item = db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id.in_(duplicate_ids)
            ).order_by(InvoiceItem.date_added.asc(), InvoiceItem.id.asc()).first()

            keep_invoice_id = oldest_item.invoice_id if oldest_item else duplicate_ids[0]

        # Delete other duplicates permanently
        deleted_count = db.query(InvoiceItem).filter(
            InvoiceItem.invoice_id.in_(duplicate_ids),
            InvoiceItem.invoice_id != keep_invoice_id
        ).delete(synchronize_session=False)

        db.commit()

        logger.info(
            f'Deleted {deleted_count} duplicate invoices for RefNo: {ref_no}, Vendor: {vendor}. Kept invoice: {keep_invoice_id}')

        return {
            'status': 'deleted',
            'message': f'Deleted {deleted_count} duplicate invoices',
            'kept_invoice_id': keep_invoice_id,
            'removed_count': deleted_count,
            'total_duplicates': len(duplicate_ids)
        }

    except Exception as e:
        logger.error(f"Error deleting duplicate invoices: {str(e)}")
        db.rollback()
        return {
            'status': 'error',
            'message': f'Error deleting duplicates: {str(e)}',
            'kept_invoice_id': None,
            'removed_count': 0
        }


def find_duplicate_invoice_ids(db, ref_no, vendor, date, amount):
    """
    Find all duplicate invoice IDs with the same ref_no, vendor, date, and amount.

    Args:
        db: Database session
        ref_no: Reference number
        vendor: Vendor name
        date: Invoice date
        amount: Total amount

    Returns:
        List of duplicate invoice IDs
    """
    try:
        # Normalize inputs
        ref_no = str(ref_no).strip() if ref_no else ""
        vendor_str = str(vendor).strip() if vendor else ""
        date_obj = date if hasattr(date, 'date') else date
        amount_str = str(amount).strip() if amount else ""

        # Convert amounts to float for comparison with tolerance
        try:
            target_amount_float = float(amount_str) if amount_str else 0.0
        except (ValueError, TypeError):
            target_amount_float = 0.0

        if not ref_no or not vendor_str:
            return []

        # Query for existing invoices with same ref_no and vendor
        existing_items = db.query(InvoiceItem).filter(
            InvoiceItem.ref_no == ref_no,
            InvoiceItem.vendor == vendor_str,
            InvoiceItem.is_active == True
        ).all()

        if not existing_items:
            return []

        # Group items by invoice_id to calculate total amounts per invoice
        invoice_totals = {}
        invoice_dates = {}

        for item in existing_items:
            invoice_id = item.invoice_id
            if invoice_id not in invoice_totals:
                invoice_totals[invoice_id] = 0
                invoice_dates[invoice_id] = item.date

            # Add item amount to invoice total
            try:
                item_amount = float(item.amount) if item.amount else 0
                invoice_totals[invoice_id] += item_amount
            except (ValueError, TypeError):
                continue

        # Define tolerance for floating-point comparison (0.01 cents)
        tolerance = 0.01

        # Find duplicates with same date and amount
        duplicate_invoice_ids = []
        for invoice_id, total_amount in invoice_totals.items():
            existing_amount_float = float(total_amount)
            existing_date = invoice_dates[invoice_id]

            # Check if amounts are within tolerance and dates match
            amount_difference = abs(
                target_amount_float - existing_amount_float)
            amounts_equal = amount_difference <= tolerance
            dates_equal = existing_date == date_obj

            if dates_equal and amounts_equal:
                duplicate_invoice_ids.append(invoice_id)

        return duplicate_invoice_ids

    except Exception as e:
        logger.error(f"Error finding duplicate invoice IDs: {str(e)}")
        return []


def main():
    """Main function to run the duplicate cleanup script."""
    print("=== Duplicate Invoice Cleanup Script ===\n")

    # Get database session
    db = next(get_db())

    try:
        # Find all duplicate invoices
        print("Scanning database for duplicate invoices...")
        duplicate_groups = find_all_duplicate_invoices(db)

        if not duplicate_groups:
            print("✅ No duplicate invoices found in the database.")
            return

        print(f"Found {len(duplicate_groups)} duplicate groups:\n")

        # Display duplicate groups
        for i, group in enumerate(duplicate_groups, 1):
            print(f"{i}. Ref No: {group['ref_no']}")
            print(f"   Vendor: {group['vendor']}")
            print(f"   Date: {group['date']}")
            print(f"   Amount: {group['total_amount']}")
            print(f"   Invoice Count: {group['invoice_count']}")
            print(f"   Invoice IDs: {', '.join(group['invoice_ids'])}")
            print()

        # Ask user what to do
        print("Options:")
        print("1. Mark duplicates as inactive (keep most recent)")
        print("2. Mark duplicates as inactive (keep oldest)")
        print("3. DELETE duplicates permanently (keep most recent)")
        print("4. DELETE duplicates permanently (keep oldest)")
        print("5. Clean up specific duplicate group")
        print("6. Exit without making changes")

        choice = input("\nEnter your choice (1-6): ").strip()

        if choice == '1':
            # Mark duplicates as inactive, keep most recent
            print("\nMarking duplicates as inactive (keeping most recent)...")
            cleaned_count = 0

            for group in duplicate_groups:
                result = cleanup_duplicate_group(
                    db, group['ref_no'], group['vendor'],
                    group['date'], group['total_amount'],
                    keep_most_recent=True, delete_duplicates=False
                )

                if result['status'] == 'cleaned':
                    cleaned_count += 1
                    print(
                        f"✅ Marked duplicates as inactive for Ref No: {group['ref_no']}, Vendor: {group['vendor']}")
                else:
                    print(
                        f"❌ Failed to mark duplicates as inactive for Ref No: {group['ref_no']}, Vendor: {group['vendor']}: {result['message']}")

            print(
                f"\n🎉 Cleanup completed! Marked {cleaned_count} duplicate groups as inactive.")

        elif choice == '2':
            # Mark duplicates as inactive, keep oldest
            print("\nMarking duplicates as inactive (keeping oldest)...")
            cleaned_count = 0

            for group in duplicate_groups:
                result = cleanup_duplicate_group(
                    db, group['ref_no'], group['vendor'],
                    group['date'], group['total_amount'],
                    keep_most_recent=False, delete_duplicates=False
                )

                if result['status'] == 'cleaned':
                    cleaned_count += 1
                    print(
                        f"✅ Marked duplicates as inactive for Ref No: {group['ref_no']}, Vendor: {group['vendor']}")
                else:
                    print(
                        f"❌ Failed to mark duplicates as inactive for Ref No: {group['ref_no']}, Vendor: {group['vendor']}: {result['message']}")

            print(
                f"\n🎉 Cleanup completed! Marked {cleaned_count} duplicate groups as inactive.")

        elif choice == '3':
            # DELETE duplicates permanently, keep most recent
            print("\n⚠️  WARNING: This will PERMANENTLY DELETE duplicate invoices!")
            confirm = input(
                "Are you sure you want to continue? (yes/no): ").strip().lower()

            if confirm == 'yes':
                print("\nDeleting duplicates permanently (keeping most recent)...")
                deleted_count = 0

                for group in duplicate_groups:
                    result = cleanup_duplicate_group(
                        db, group['ref_no'], group['vendor'],
                        group['date'], group['total_amount'],
                        keep_most_recent=True, delete_duplicates=True
                    )

                    if result['status'] == 'deleted':
                        deleted_count += 1
                        print(
                            f"✅ Deleted duplicates for Ref No: {group['ref_no']}, Vendor: {group['vendor']}")
                    else:
                        print(
                            f"❌ Failed to delete duplicates for Ref No: {group['ref_no']}, Vendor: {group['vendor']}: {result['message']}")

                print(
                    f"\n🎉 Deletion completed! Deleted {deleted_count} duplicate groups permanently.")
            else:
                print("Deletion cancelled.")

        elif choice == '4':
            # DELETE duplicates permanently, keep oldest
            print("\n⚠️  WARNING: This will PERMANENTLY DELETE duplicate invoices!")
            confirm = input(
                "Are you sure you want to continue? (yes/no): ").strip().lower()

            if confirm == 'yes':
                print("\nDeleting duplicates permanently (keeping oldest)...")
                deleted_count = 0

                for group in duplicate_groups:
                    result = cleanup_duplicate_group(
                        db, group['ref_no'], group['vendor'],
                        group['date'], group['total_amount'],
                        keep_most_recent=False, delete_duplicates=True
                    )

                    if result['status'] == 'deleted':
                        deleted_count += 1
                        print(
                            f"✅ Deleted duplicates for Ref No: {group['ref_no']}, Vendor: {group['vendor']}")
                    else:
                        print(
                            f"❌ Failed to delete duplicates for Ref No: {group['ref_no']}, Vendor: {group['vendor']}: {result['message']}")

                print(
                    f"\n🎉 Deletion completed! Deleted {deleted_count} duplicate groups permanently.")
            else:
                print("Deletion cancelled.")

        elif choice == '5':
            # Clean up specific duplicate group
            try:
                group_num = int(
                    input("Enter the group number to clean up: ")) - 1
                if 0 <= group_num < len(duplicate_groups):
                    group = duplicate_groups[group_num]

                    print("\nOptions for this group:")
                    print("1. Mark duplicates as inactive (keep most recent)")
                    print("2. Mark duplicates as inactive (keep oldest)")
                    print("3. DELETE duplicates permanently (keep most recent)")
                    print("4. DELETE duplicates permanently (keep oldest)")

                    action_choice = input("Enter your choice (1-4): ").strip()

                    if action_choice == '1':
                        keep_most_recent = True
                        delete_duplicates = False
                        action_desc = "marking as inactive (keeping most recent)"
                    elif action_choice == '2':
                        keep_most_recent = False
                        delete_duplicates = False
                        action_desc = "marking as inactive (keeping oldest)"
                    elif action_choice == '3':
                        keep_most_recent = True
                        delete_duplicates = True
                        action_desc = "deleting permanently (keeping most recent)"
                    elif action_choice == '4':
                        keep_most_recent = False
                        delete_duplicates = True
                        action_desc = "deleting permanently (keeping oldest)"
                    else:
                        print("Invalid choice.")
                        return

                    if delete_duplicates:
                        print(
                            f"\n⚠️  WARNING: This will PERMANENTLY DELETE duplicate invoices!")
                        confirm = input(
                            "Are you sure you want to continue? (yes/no): ").strip().lower()
                        if confirm != 'yes':
                            print("Deletion cancelled.")
                            return

                    print(f"\n{action_desc.capitalize()}...")

                    result = cleanup_duplicate_group(
                        db, group['ref_no'], group['vendor'],
                        group['date'], group['total_amount'],
                        keep_most_recent, delete_duplicates
                    )

                    if result['status'] in ['cleaned', 'deleted']:
                        action_verb = "Cleaned up" if result['status'] == 'cleaned' else "Deleted"
                        print(
                            f"✅ {action_verb} duplicates for Ref No: {group['ref_no']}, Vendor: {group['vendor']}")
                        print(f"   Kept invoice: {result['kept_invoice_id']}")
                        print(
                            f"   Removed {result['removed_count']} duplicate invoices")
                    else:
                        print(
                            f"❌ Failed to process duplicates: {result['message']}")
                else:
                    print("Invalid group number.")
            except ValueError:
                print("Invalid input. Please enter a valid number.")

        elif choice == '6':
            print("Exiting without making changes.")

        else:
            print("Invalid choice. Exiting.")

    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
        print(f"❌ Error: {str(e)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
