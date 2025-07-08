from mpi_backend.database.models import UnmappedItems
from mpi_backend.database.models.InvoiceItems import InvoiceItem
import pandas as pd
from mpi_backend.utils.item_utils import (
    clean_supplier_suffix, clean_suffix
)
from sqlalchemy import and_, or_
from typing import Dict, Any, Optional, List
from datetime import date
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class UnmappedItemsController:
    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """Get a database session object, whether db_context is a factory or session."""
        # Check if it's already a session instance (has query, add, commit methods)
        if hasattr(self.db_context, 'query') and hasattr(self.db_context, 'commit'):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    def get_items_mappings(self):
        db = self._get_db_session()
        query_result = db.query(UnmappedItems).all()
        data = [(item.google_sheet_name, item.mpi_code, item.description,
                 item.supplier_item_ids, item.supplier_id) for item in query_result]
        columns = ['google_sheet_name', 'mpi_code', 'description',
                   'supplier_item_ids', 'supplier_id']
        items_mappings = pd.DataFrame(data, columns=columns)
        return items_mappings

    def insert_unmapped_item(self, item_code, description, supplier_id):
        db = self._get_db_session()
        new_item = UnmappedItems(
            google_sheet_name='',
            mpi_code='',
            description=description,
            supplier_item_ids=item_code,
            supplier_id=supplier_id
        )
        db.add(new_item)
        db.commit()

    def is_item_code_present(self, item_code, supplier_id=None):
        """
        Check if an item code is present in unmapped items with 
        supplier-specific suffix cleaning support.
        
        Args:
            item_code (str): Clean item code from invoice to check
            supplier_id (int, optional): Supplier ID for targeted suffix cleaning
            
        Returns:
            bool: True if item is present (with or without suffix), 
                  False otherwise
        """
        try:
            db = self._get_db_session()
            # Get all unmapped items
            all_unmapped = db.query(UnmappedItems).all()
            
            # Check clean invoice item against both original and cleaned DB data
            for unmapped_item in all_unmapped:
                # First try exact match (clean invoice vs DB item)
                if unmapped_item.supplier_item_ids == item_code:
                    return True
                # Then try clean invoice vs cleaned DB item
                elif (supplier_id and 
                      clean_supplier_suffix(
                          unmapped_item.supplier_item_ids, 
                          supplier_id
                      ) == item_code):
                    return True
                    
            return False
            
        except Exception as e:
            print(f'Unmapped item-{item_code} could not be looked up in db ->{e}')
            return False

    def get_unmapped_items(
        self,
        item_type: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        supplier_names: Optional[List[str]] = None,
        search: Optional[str] = None,
        order_by: Optional[List[dict]] = None,
        page: int = 1,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Get unmapped items with pagination and filtering.
        
        Args:
            item_type (str): 'temporary' or 'unmapped'
            date_from (date, optional): Start date filter
            date_to (date, optional): End date filter
            supplier_names (List[str], optional): Supplier names to filter by
            page (int): Page number (1-based)
            size (int): Number of items per page
            
        Returns:
            Dict with items, pagination metadata
        """
        try:
            db = self._get_db_session()
            return self._get_unmapped_items_query(
                db, item_type, date_from, date_to, supplier_names, 
                search, order_by, page, size
            )
        except Exception as e:
            logger.error(f"Error retrieving unmapped items: {e}")
            return {
                "items": [],
                "total_count": 0,
                "page": page,
                "size": size,
                "pages": 0
            }

    def _get_unmapped_items_query(
        self,
        db,
        item_type: str,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Internal method to execute the unmapped items query"""
        
        if item_type == "temporary":
            return self._get_temporary_items(db, date_from, date_to, supplier_names, search, order_by, page, size)
        elif item_type == "unmapped":
            return self._get_all_unmapped_items(db, date_from, date_to, supplier_names, search, order_by, page, size)
        elif item_type == "no_temporary":
            return self._get_unmapped_items_logic(db, date_from, date_to, supplier_names, search, order_by, page, size)
        else:
            raise ValueError(f"Invalid item_type: {item_type}. Must be 'temporary', 'unmapped', or 'no_temporary'")

    def _get_temporary_items(
        self,
        db,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Get items that have a sheet_name but are 'No Match' or start with 'UIDI'"""
        
        # Base query for temporary items
        query = db.query(InvoiceItem).filter(
            and_(
                InvoiceItem.sheet_name.isnot(None),
                InvoiceItem.sheet_name != '',
                or_(
                    InvoiceItem.mpi_item == 'No Match',
                    InvoiceItem.mpi_item.like('UIDI%'),
                    InvoiceItem.mpi_description == 'No Match',
                    InvoiceItem.mpi_description.like('UIDI%')
                )
            )
        )
        
        # Apply filters (date and supplier filters)
        query = self._apply_common_filters(query, date_from, date_to, supplier_names)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _get_all_unmapped_items(
        self,
        db,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Get ALL items with No Match or UIDI regardless of sheet_name"""
        
        # Base query for all unmapped items (No Match or UIDI)
        query = db.query(InvoiceItem).filter(
            or_(
                InvoiceItem.mpi_item == 'No Match',
                InvoiceItem.mpi_item.like('UIDI%'),
                InvoiceItem.mpi_description == 'No Match',
                InvoiceItem.mpi_description.like('UIDI%')
            )
        )
        
        # Apply filters (date and supplier filters)
        query = self._apply_common_filters(query, date_from, date_to, supplier_names)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _get_unmapped_items_logic(
        self,
        db,
        date_from: Optional[date],
        date_to: Optional[date],
        supplier_names: Optional[List[str]],
        search: Optional[str],
        order_by: Optional[List[dict]],
        page: int,
        size: int
    ) -> Dict[str, Any]:
        """Get items that do not have a sheet_name and have no valid mapping"""
        
        # Base query for unmapped items
        query = db.query(InvoiceItem).filter(
            or_(
                InvoiceItem.sheet_name.is_(None),
                InvoiceItem.sheet_name == ''
            )
        )
        
        # Apply filters (date and supplier filters)
        query = self._apply_common_filters(query, date_from, date_to, supplier_names)
        
        # Get unique items based on cleaned original item ID (without search filter first)
        return self._get_unique_items_with_pagination(db, query, page, size, order_by, search)

    def _apply_common_filters(self, query, date_from, date_to, supplier_names):
        """Apply common date and supplier filters"""
        
        # Apply date filters
        if date_from:
            query = query.filter(InvoiceItem.date >= date_from)
        if date_to:
            query = query.filter(InvoiceItem.date <= date_to)
        
        # Apply supplier filter
        if supplier_names and len(supplier_names) > 0:
            # Skip if 'All' is in the list
            if not (len(supplier_names) == 1 and supplier_names[0].lower() == 'all'):
                query = query.filter(InvoiceItem.vendor.in_(supplier_names))
        
        return query

    def _get_unique_items_with_pagination(self, db, query, page, size, order_by=None, search=None):
        """Get unique items per supplier with supplier suffixes for distinction"""
        
        # Execute query to get all matching items (within date range and supplier filters)
        all_items = query.all()
        
        # Group by supplier + cleaned item code to get unique items per supplier
        unique_items_map = {}
        for item in all_items:
            # Clean the item code (remove any existing suffixes first)
            cleaned_item = clean_suffix(item.item or "")
            if not cleaned_item:
                continue
                
            # Create a unique key combining supplier and cleaned item
            supplier = item.vendor or ""
            unique_key = f"{supplier}|{cleaned_item}"
            
            if unique_key not in unique_items_map:
                # Add supplier suffix to the item code for display
                item_with_suffix = self._add_supplier_suffix(cleaned_item, supplier)
                
                # Calculate amount based on cost and quantity
                cost = item.cost or 0.0
                quantity = item.qty or 0
                amount = round(cost * quantity, 3)
                
                unique_items_map[unique_key] = {
                    "original_item_id": item_with_suffix,  # Return with supplier suffix
                    "original_description": item.description or "",
                    "cost": cost,
                    "amount": amount,  # Calculated as cost * quantity
                    "quantity": quantity,
                    "sheet_name": item.sheet_name or "",
                    "supplier": supplier
                }
        
        # Convert to list
        unique_items = list(unique_items_map.values())
        
        # Apply search filter AFTER deduplication (search on original_item_id that users see)
        if search and search.strip():
            clean_search = search.strip().lower()
            unique_items = [
                item for item in unique_items
                if (clean_search in item["original_item_id"].lower() or
                    clean_search in (item["mpi_description"] or "").lower())
            ]
        
        # Apply ordering
        if order_by and len(order_by) > 0:
            for order_item in reversed(order_by):  # Apply in reverse to handle multiple sorts
                column = order_item.get("column", "amount")
                order = order_item.get("order", "desc")
                reverse = (order.lower() == "desc")
                
                # Map column names to actual fields
                sort_key = column
                if column == "id":
                    sort_key = "original_item_id"
                elif column == "date":
                    sort_key = "amount"  # Default fallback
                
                unique_items.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
        else:
            # Default sort by amount in descending order (highest amounts first)
            unique_items.sort(key=lambda x: x.get("amount", 0), reverse=True)
        
        # Calculate pagination
        total_count = len(unique_items)
        if total_count == 0:
            total_pages = 0
        else:
            total_pages = (total_count + size - 1) // size if size > 0 else 1
        
        # Apply pagination
        if size > 0:
            # Normal pagination
            start_index = (page - 1) * size
            end_index = start_index + size
            paginated_items = unique_items[start_index:end_index]
        else:
            # size=0 means get all items (used by export endpoints)
            paginated_items = unique_items
        
        return {
            "items": paginated_items,
            "total_count": total_count,
            "page": page,
            "size": size,
            "pages": total_pages
        }

    def _add_supplier_suffix(self, item_code: str, supplier_name: str) -> str:
        """
        Add supplier-specific suffix to item code for display purposes.
        
        Args:
            item_code (str): Clean item code without suffix
            supplier_name (str): Supplier name to determine appropriate suffix
            
        Returns:
            str: Item code with suffix appended (e.g., "ABC123-B")
        """
        if not item_code or not supplier_name:
            return item_code
        
        # Clean whitespace from item code
        clean_item = str(item_code).strip()
        if not clean_item:
            return clean_item
        
        # Exclude tax and administrative items from getting suffixes
        excluded_items = [
            "tax", "freight", "shipping", "handling", "subtotal", "total"
        ]
        if (clean_item.startswith("10 Materials") or 
                clean_item.lower() in excluded_items):
            return clean_item
        
        # Clean whitespace from supplier name
        clean_supplier_name = supplier_name.strip()
        
        # Get suffix for supplier name
        suffix = self._get_supplier_suffix(clean_supplier_name)
        if not suffix:
            return clean_item
        
        # Remove ALL existing suffixes first (including double suffixes)
        all_suffixes = self._get_all_suffixes()
        
        # Keep removing suffixes until none are found
        while True:
            found_suffix = False
            for existing_suffix in all_suffixes:
                if existing_suffix and clean_item.endswith(f"-{existing_suffix}"):
                    clean_item = clean_item[:-len(f"-{existing_suffix}")]
                    found_suffix = True
                    break
            if not found_suffix:
                break
        
        # Add the correct suffix
        return f"{clean_item}-{suffix}"

    def _get_supplier_suffix(self, supplier_name: str) -> Optional[str]:
        """
        Get the suffix letter for a specific supplier name.
        
        Args:
            supplier_name (str): Supplier name
            
        Returns:
            Optional[str]: Suffix letter or None if no suffix
        """
        supplier_suffix_map = {
            "BMW Plumbing Supplies": "B",
            "World Wide Plumbing": "W",
            "Y & S Plumbing Supply": "Y",
            "Supreme Plumbing Supply": "S",
            "Pyramid Plumbing": "P",
            "ABC Opus Services": "A",
            "Park Plumbing Supply": "P",
            "Gotham Plumbing Supply": "G",
            "FW Webb Plumbing Supply": "F",
            "Flow Mark Plumbing Supply": "F",
            "Plumbing Exchange": None,  # No suffix
            "AF Supply": "A",
            "Lion Hvac Supplies": None,  # No suffix
            "Bruce Ferguson": "F",
        }
        
        # Check for exact match first
        if supplier_name in supplier_suffix_map:
            return supplier_suffix_map[supplier_name]
        
        # Check for partial matches (in case supplier name has variations)
        for known_supplier, suffix in supplier_suffix_map.items():
            if known_supplier in supplier_name or supplier_name in known_supplier:
                return suffix
        
        return None

    def _get_all_suffixes(self) -> List[str]:
        """
        Get all known supplier suffixes.
        
        Returns:
            List[str]: List of all known suffix letters
        """
        return ["B", "W", "Y", "S", "P", "A", "G", "F"]
