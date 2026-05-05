from datetime import date, datetime, timedelta
from sqlalchemy import asc, desc, case, cast, Date, Float, func, and_, or_, text, select
from fastapi import HTTPException, BackgroundTasks
from typing import List, Dict, Any, Optional, Tuple
from math import ceil
from mpi_backend.database.models import InvoiceItem, Invoice, InvoiceItemMart, PriceIncreaseMart
from mpi_backend.database.models.InvoiceVoid import InvoiceVoid
from mpi_backend.database.schemas import InvoiceItems as InvoiceItemsResponse
from mpi_backend.database.schemas import PriceHistoryResponse
from mpi_backend.database.schemas.Filters import FilterRequest, ColorFilter, ComparisonFilter, PriceChangeFilter
from mpi_backend.utils.feature_flags import is_enabled
from mpi_backend.utils.export_utils import extract_supplier_id
from mpi_backend.utils.number_formatter import format_currency, parse_number
from mpi_backend.utils.supplier_suffix_manager import (
    get_supplier_suffix,
    get_supplier_id_from_name,
    get_supplier_name_from_id
)
from mpi_backend.database.dao import invoice_item_mart
from mpi_backend.database.dao import analysis_page_dao
from mpi_backend.database.dao.dao_models import DaoAggregateResult
import logging
import sqlalchemy.orm
from sqlalchemy.orm import load_only, Session
import time
from functools import lru_cache
import hashlib
import os
import zipfile
import shutil
import json
from mpi_backend.config import (
    INVOICE_DOWNLOAD_FOLDER,
    S3_PRESIGNED_URL_EXPIRY
)
from mpi_backend.utils.s3_utils import download_s3_file, upload_export_and_get_url
import traceback
import gc


logger = logging.getLogger(__name__)

# ============================================================================
# FEATURE FLAGS: DAO vs ORM Control
# ============================================================================
#
# These MODULE-LEVEL constants are FALLBACK VALUES used when:
# - Controller is instantiated without current_user parameter
# - Used for backward compatibility with endpoints that don't pass user
#
# For user-based feature flags, users must be added to allowlist in:
# mpi_backend/utils/feature_flags.py
#
# TESTING MODES (when using user-based flags):
# --------------
# 1. Production (default for non-allowlisted users):
#    use_dao_with_fallback = False
#    use_dao_only = False
#    -> Uses ORM only (safe default)
#
# 2. DAO Testing (for allowlisted users):
#    use_dao_with_fallback = True
#    use_dao_only = False
#    -> DAO tries first, falls back to ORM on failure
#
# 3. DAO Only (for allowlisted users in strict mode):
#    use_dao_with_fallback = False (ignored when use_dao_only=True)
#    use_dao_only = True
#    -> DAO tries, raises HTTP 500 on failure
#
# ============================================================================

# FALLBACK DEFAULTS: Used only when current_user is not provided
# Set to False so DAO is opt-in via user allowlist (safe default)
USE_DAO_WITH_FALLBACK = False

# FALLBACK DEFAULTS: Used only when current_user is not provided
# Set to False to use ORM as safe default
USE_DAO_ONLY = False


class InvoiceItemController:
    def __init__(self, db: Session, current_user: Optional[Any] = None):
        self.db = db
        self.current_user = current_user
        # Pre-compile frequently used queries for better performance
        self._compiled_queries = {}
        self._setup_query_cache()
        # Allowed columns whitelist for dynamic operations
        self._allowed_distinct_columns = {
            'filename', 'sheet_name', 'item', 'description', 'qty', 'cost',
            'amount', 'date', 'ref_no', 'po_number', 'customer_job', 'bill',
            'vendor', 'class_', 'account', 'memo', 'buyer', 'date_added',
            'mpi_item', 'mpi_description', 'export_status'
        }
        # ADDED: Resource monitoring
        self._query_start_time = None
        self._memory_before = None

    def _validate_filter_request(
        self,
        request: FilterRequest,
        col_param: Optional[str]= None,
    ) -> FilterRequest:
        """
        Validate and clean all inputs before processing.

        The controller is the gatekeeper: validate, normalize, and clean data before
        passing to DAO. Invalid data is removed or raises errors - DAO receives only clean data.

        NOTE: Currently only support InvoiceItemMart
        """
        # Validate col_param if provided
        if col_param:
            if not hasattr(InvoiceItemMart, col_param):
                raise HTTPException(status_code=400, detail=f"Invalid column name: {col_param}")

        # Clean filter columns - remove invalid columns from filters dict
        # Validate and clean filter columns (don't mutate original request)
        # TODO: Should we raise an exception if the frontend sent an invalid column?
        cleaned_filters = {}
        if request.filters:
            for col, values in request.filters.items():
                if not hasattr(InvoiceItemMart, col):
                    logger.warning(f"Removing invalid filter column '{col}' from request")
                else:
                    cleaned_filters[col] = values

        # Validate and collect valid comparison filters
        # Valid operators for comparison filters
        # TODO: Should be a dataclass that is shared accross the app?
        # TODO: Double check which are valid operators
        VALID_OPERATORS = {'gte', 'lte', 'gt', 'lt', 'eq', 'neq', '=', '>', '<', '>=', '<=', '=='}

        cleaned_comparison_filters = []
        if request.comparison_filters:
            for comp_filter in request.comparison_filters:
                # Check operator validity
                if comp_filter.operator not in VALID_OPERATORS:
                    logger.warning(
                        f"Skipping comparison filter with invalid operator '{comp_filter.operator}' "
                        f"for column '{comp_filter.column}'"
                    )
                    continue

                # Check column validity
                if not hasattr(InvoiceItemMart, comp_filter.column):
                    logger.warning(f"Skipping comparison filter with invalid column '{comp_filter.column}'")
                    continue

                # Check value conversion
                column = getattr(InvoiceItemMart, comp_filter.column)
                try:
                    # Test that the value can be converted
                    self._convert_filter_value(comp_filter.__dict__, column)
                    # If valid, keep this filter
                    cleaned_comparison_filters.append(comp_filter)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping for '{comp_filter.column}' with invalid value: {e}")
                    continue

        # Validate order_by columns
        cleaned_order_by = []
        if request.order_by:
            # Also include computed/aliased columns used in DAO queries
            column_mapping = {'percentage_increase', 'previous_cost', 'price_difference', 'best_price'}
            for order_filter in request.order_by:
                if not hasattr(InvoiceItemMart, order_filter.column) and order_filter.column not in column_mapping:
                    logger.warning(f"Invalid order_by column '{order_filter.column}', will be skipped by DAO")
                    continue

                if order_filter.order and order_filter.order.lower() not in ['asc', 'desc']:
                    logger.warning(f"Invalid order_by column '{order_filter.order}', will not be passed to DAO")
                    continue
                cleaned_order_by.append(order_filter)

        # Validate and clean color_filters
        cleaned_color_filters = None
        if request.color_filters and request.color_filters.colors:
            # Validate that all colors are valid
            # TODO: We want this to be in a central location and reused across the app
            VALID_COLORS = {'green', 'orange', 'both'}
            
            valid_colors = []
            for color in request.color_filters.colors:
                normalized_color = color.lower()
                if normalized_color not in VALID_COLORS:
                    logger.warning(f"Invalid color {color}")
                    continue
                valid_colors.append(normalized_color)
    
            cleaned_color_filters = ColorFilter(colors=valid_colors) if valid_colors else None

        # Validate and clean price_change_filter
        cleaned_price_change_filter = None
        if request.price_change_filter:
            VALID_CHANGE_TYPES = {'all', 'increase', 'decrease'}
            change_type = request.price_change_filter.change_type
            if change_type and change_type.lower() in VALID_CHANGE_TYPES:
                cleaned_price_change_filter = PriceChangeFilter(
                    change_type=change_type.lower(),
                    min_percent=request.price_change_filter.min_percent,
                    max_percent=request.price_change_filter.max_percent
                )
            else:
                logger.warning(f"Invalid price_change_filter change_type: {change_type}")

        # Business rule: Exclude "Z, ADDITIONAL FEES" sheet for price-change
        if cleaned_price_change_filter:
            cleaned_comparison_filters.append(
                ComparisonFilter(column='sheet_name', operator='neq', value='Z, ADDITIONAL FEES'),
            )

        cleaned_request = FilterRequest(
            filters=cleaned_filters,
            comparison_filters=cleaned_comparison_filters,
            order_by=cleaned_order_by if cleaned_order_by else None,
            color_filters=cleaned_color_filters,
            price_change_filter=cleaned_price_change_filter,
            compare_all_supplier=request.compare_all_supplier,
            search=request.search,
            substring_search=request.substring_search,
            include_voided=request.include_voided
        )

        return cleaned_request


    def _get_feature_flags(self) -> Dict[str, bool]:
        """
        Get feature flags for the current user.
        Falls back to module-level constants if user not provided.

        TODO: Feature flags should be consistent. Right now we are using strings but we should use a dataclass
        or something similar to avoid typos and improve readability

        Returns:
            Dict with feature flag values
        """
        if self.current_user:
            return {
                'use_dao_with_fallback': is_enabled('use_dao_with_fallback', self.current_user),
                'use_dao_only': is_enabled('use_dao_only', self.current_user),
            }
        else:
            # Fallback to module-level constants for backward compatibility
            return {
                'use_dao_with_fallback': USE_DAO_WITH_FALLBACK,
                'use_dao_only': USE_DAO_ONLY,
            }

    def _normalize_ref_no_for_comparison(self, ref_no):
        """
        Normalize reference number for duplicate comparison while preserving original format.
        This handles cases where the same invoice might be stored with different leading zero formats.
        
        Examples:
        - "066617" -> "66617" (for comparison)
        - "I-000987" -> "I-987" (for comparison)
        - "0081212A" -> "81212A" (for comparison)
        - "89779-I" -> "89779-I" (unchanged)
        
        Args:
            ref_no: Reference number string
            
        Returns:
            Normalized reference number for comparison
        """
        if not ref_no:
            return ""
        
        ref_no = str(ref_no).strip()
        
        # Handle patterns like "066617", "I-000987", "0081212A"
        # Remove leading zeros from numeric parts while preserving letters and dashes
        
        import re
        
        # Pattern 1: Pure numbers with leading zeros (e.g., "066617" -> "66617")
        if ref_no.isdigit():
            return ref_no.lstrip('0') or '0'  # Handle "0000" -> "0"
        
        # Pattern 2: Letter-dash-number with leading zeros (e.g., "I-000987" -> "I-987")
        match = re.match(r'^([A-Za-z]+)-0+(\d+)$', ref_no)
        if match:
            letter_part = match.group(1)
            number_part = match.group(2).lstrip('0') or '0'
            return f"{letter_part}-{number_part}"
        
        # Pattern 3: Number-letter with leading zeros (e.g., "0081212A" -> "81212A")
        match = re.match(r'^0+(\d+[A-Za-z]+)$', ref_no)
        if match:
            return match.group(1)
        
        # Pattern 4: Letter-number with leading zeros (e.g., "I000987" -> "I987")
        match = re.match(r'^([A-Za-z]+)0+(\d+)$', ref_no)
        if match:
            letter_part = match.group(1)
            number_part = match.group(2).lstrip('0') or '0'
            return f"{letter_part}{number_part}"
        
        # Pattern 5: Complex patterns with multiple leading zeros
        # Split by common delimiters and normalize each part
        parts = re.split(r'([-])', ref_no)
        normalized_parts = []
        
        for part in parts:
            if part in ['-']:
                normalized_parts.append(part)
            elif part.isdigit():
                normalized_parts.append(part.lstrip('0') or '0')
            elif re.match(r'^[A-Za-z]+0+\d+$', part):
                # Handle cases like "I000987"
                match = re.match(r'^([A-Za-z]+)0+(\d+)$', part)
                if match:
                    letter_part = match.group(1)
                    number_part = match.group(2).lstrip('0') or '0'
                    normalized_parts.append(f"{letter_part}{number_part}")
                else:
                    normalized_parts.append(part)
            else:
                normalized_parts.append(part)
        
        return ''.join(normalized_parts)

    def update_invoice_reference_number(self, invoice_id, new_ref_no):
        """
        Update the reference number for all items in an invoice.
        
        Args:
            invoice_id: UUID of the invoice to update
            new_ref_no: New reference number to set
            
        Returns:
            Number of items updated
        """
        try:
            # Update all items with the given invoice_id
            updated_count = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id == invoice_id,
                InvoiceItem.is_active == True
            ).update({
                'ref_no': new_ref_no
            })
            
            self.db.commit()
            logger.info(f"Updated reference number for invoice {invoice_id}: {updated_count} items updated to '{new_ref_no}'")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error updating reference number for invoice {invoice_id}: {str(e)}")
            self.db.rollback()
            return 0

    def _monitor_resource_usage(self, operation: str):
        """Monitor resource usage for operations"""
        try:
            self._query_start_time = time.time()
            self._memory_before = 0  # Resource monitoring disabled
        except Exception as e:
            logger.debug(f"Could not monitor resources: {e}")

    def _log_resource_usage(self, operation: str):
        """Log resource usage after operations"""
        try:
            if self._query_start_time:
                duration = time.time() - self._query_start_time
                memory_after = 0  # Resource monitoring disabled
                memory_diff = memory_after - self._memory_before if self._memory_before else 0
                
                if duration > 1.0:  # Log slow queries
                    logger.warning(f"Slow query detected: {operation} took {duration:.2f}s")
                
                if memory_diff > 5.0:  # Log high memory usage
                    logger.warning(f"High memory usage: {operation} used {memory_diff:.1f}% RAM")
                    
        except Exception as e:
            logger.debug(f"Could not log resource usage: {e}")

    def _validate_safe_column(self, column_name: str) -> str:
        """Validate provided column name against whitelist and model attributes."""
        if not isinstance(column_name, str):
            raise ValueError("Invalid column name type")
        normalized = column_name.strip()
        if normalized not in self._allowed_distinct_columns:
            raise ValueError(f"Invalid or unsafe column: {column_name}")
        if not hasattr(InvoiceItem, normalized):
            raise ValueError(f"Column not found: {column_name}")
        return normalized

    def _safe_numeric_cast(self, text_column):
        """Safely cast a textual numeric column to Float.

        - Removes commas
        - Validates with a regex so bad rows don't crash the query
        - Returns NULL when non-numeric so comparisons behave as expected
        """
        cleaned = func.replace(text_column, ',', '')
        is_numeric = cleaned.op('~')('^-?[0-9]*\\.?[0-9]+$')
        return case(
            (
                and_(
                    text_column.isnot(None),
                    text_column != '',
                    func.length(text_column) < 100,
                    is_numeric,
                ),
                cast(cleaned, Float),
            ),
            else_=None,
        )

    def _setup_query_cache(self):
        """Pre-compile frequently used queries for ultra-fast execution."""
        try:
            # Cache base query patterns with optimized field selection
            self._compiled_queries['base_select'] = (
                select(InvoiceItem)
                .options(load_only(
                    InvoiceItem.id, InvoiceItem.item, InvoiceItem.vendor,
                    InvoiceItem.customer_job, InvoiceItem.cost, InvoiceItem.qty,
                    InvoiceItem.date, InvoiceItem.is_active, InvoiceItem.class_,
                    InvoiceItem.account, InvoiceItem.export_status
                ))
                .where(InvoiceItem.is_active.is_(True))
            )

            # Cache count query
            self._compiled_queries['count_active'] = (
                select(func.count(InvoiceItem.id))
                .where(InvoiceItem.is_active.is_(True))
            )

            # ADDED: Cache optimized filter queries
            self._compiled_queries['filter_base'] = (
                select(InvoiceItem)
                .options(load_only(
                    InvoiceItem.id, InvoiceItem.item, InvoiceItem.vendor,
                    InvoiceItem.cost, InvoiceItem.qty, InvoiceItem.date,
                    InvoiceItem.customer_job, InvoiceItem.is_active
                ))
                .where(InvoiceItem.is_active.is_(True))
            )

            logger.info("Query cache initialized successfully")
        except Exception as e:
            logger.error(f"Failed to setup query cache: {e}")

    def _apply_priority_ordering(self, query, order_by_filters):
        """Ordering policy:
        - If no order_by or it contains only one entry with column=id and order=desc,
          apply default: date desc, then id desc.
        - Otherwise, honor the provided order_by sequence exactly; append id desc
          at the end as a stable tiebreaker if not already present.
        """
        # Normalize incoming order_by
        normalized: List[tuple] = []
        if order_by_filters:
            for ob in order_by_filters:
                try:
                    col = (ob.column or '').strip()
                    ord_dir = (ob.order or '').strip().lower()
                except Exception:
                    continue
                if not hasattr(InvoiceItem, col):
                    continue
                if ord_dir not in ('asc', 'desc'):
                    ord_dir = 'asc'
                normalized.append((col, ord_dir))

        # Case 1: default ordering trigger (none or only id desc)
        if not normalized or (len(normalized) == 1 and normalized[0][0] == 'id' and normalized[0][1] == 'desc'):
            query = query.order_by(InvoiceItem.date.desc(), InvoiceItem.id.desc())
            return query

        # Case 2: honor user-provided ordering; append id desc as tiebreaker if missing
        for col, ord_dir in normalized:
            order_col = getattr(InvoiceItem, col)
            query = query.order_by(order_col.asc() if ord_dir == 'asc' else order_col.desc())

        if not any(col == 'id' for col, _ in normalized):
            query = query.order_by(InvoiceItem.id.desc())

        return query

    @lru_cache(maxsize=256)
    def _get_distinct_values_ultra_optimized(
        self,
        column: str,
        filter_hash: str
    ) -> List[str]:
        """
        Ultra-optimized distinct values with aggressive caching and streaming.
        Handles 50,000+ records in milliseconds.
        """
        start_time = time.time()

        try:
            # Use raw SQL for maximum performance
            if column == 'item':
                # Special handling for item column with suffix calculation
                raw_query = text("""
                    SELECT DISTINCT 
                        CASE 
                            WHEN vendor LIKE '%BMW%' THEN CONCAT(item, '-B')
                            WHEN vendor LIKE '%Y&S%' OR vendor LIKE '%Y & S%' 
                                THEN CONCAT(item, '-Y')
                            ELSE item 
                        END as display_item
                    FROM invoice_items 
                    WHERE is_active = true 
                        AND item IS NOT NULL 
                        AND item != ''
                    ORDER BY display_item
                    LIMIT 5000
                """)
            else:
                # Safe ORM-based distinct query (validated column)
                try:
                    safe_column = self._validate_safe_column(column)
                except ValueError as e:
                    logger.warning(f"Rejected unsafe column in distinct: {e}")
                    return []

                column_attr = getattr(InvoiceItem, safe_column)
                query = (
                    self.db.query(column_attr)
                    .filter(InvoiceItem.is_active.is_(True))
                    .filter(column_attr.isnot(None))
                    .distinct()
                    .order_by(column_attr.asc())
                    .limit(2000)
                )
                rows = query.all()
                values = [row[0] for row in rows]

                # Force garbage collection for large datasets
                if len(values) > 500:
                    gc.collect()

                logger.info(f"Ultra-optimized distinct values for '{column}' "
                            f"took {time.time() - start_time:.3f}s, "
                            f"returned {len(values)} values")

                return values

        except Exception as e:
            logger.error(f"Error in ultra-optimized distinct values: {e}")
            # Fallback to simple query
            return self._fallback_distinct_query(column)

    def _fallback_distinct_query(self, column: str) -> List[str]:
        """Fallback method for distinct queries if optimization fails."""
        try:
            query = (
                self.db.query(getattr(InvoiceItem, column))
                .filter(InvoiceItem.is_active == True)
                .filter(getattr(InvoiceItem, column).isnot(None))
                .distinct()
                .limit(1000)
            )

            return [str(row[0]) for row in query.all()]
        except Exception as e:
            logger.error(f"Fallback query failed: {e}")
            return []

    def _build_ultra_optimized_query(self, request: FilterRequest):
        """Build ultra-optimized base query with minimal overhead."""
        try:
            # Start with optimized base query
            query = (
                self.db.query(InvoiceItem)
                .filter(InvoiceItem.is_active == True)
                .options(load_only(
                    InvoiceItem.id, InvoiceItem.item, InvoiceItem.vendor,
                    InvoiceItem.customer_job, InvoiceItem.cost, InvoiceItem.qty,
                    InvoiceItem.date, InvoiceItem.amount, InvoiceItem.description,
                    InvoiceItem.mpi_item, InvoiceItem.class_, InvoiceItem.account, InvoiceItem.export_status
                ))
            )

            # Apply filters efficiently
            if request.filters:
                for column, values in request.filters.items():
                    if values and len(values) > 0:
                        attr = getattr(InvoiceItem, column, None)
                        if attr is not None:
                            # Strip spaces from filter values for consistent comparison
                            cleaned_values = []
                            for value in values:
                                if isinstance(value, str):
                                    cleaned_values.append(value.strip())
                                else:
                                    cleaned_values.append(value)

                            # For string columns, use case-insensitive and trimmed comparison
                            if column in ['ref_no', 'vendor', 'item', 'description', 'customer_job', 'po_number', 'bill', 'buyer', 'memo', 'class_', 'account']:
                                # Use func.trim() and ilike for case-insensitive, trimmed comparison
                                conditions = []
                                for cleaned_value in cleaned_values:
                                    if isinstance(cleaned_value, str):
                                        # Trim both database value and filter value, then do case-insensitive comparison
                                        conditions.append(func.trim(attr).ilike(
                                            func.trim(cleaned_value)))
                                    else:
                                        conditions.append(
                                            attr == cleaned_value)
                                if conditions:
                                    query = query.filter(or_(*conditions))
                            else:
                                # For non-string columns, use exact match
                                query = query.filter(attr.in_(cleaned_values))

            # Apply comparison filters
            if request.comparison_filters:
                for comp_filter in request.comparison_filters:
                    attr = getattr(InvoiceItem, comp_filter.column, None)
                    if attr is not None:
                        # Ensure numeric comparison for 'amount' which is stored as String
                        if comp_filter.column == 'amount':
                            # Robust cast that ignores non-numeric rows
                            attr = self._safe_numeric_cast(attr)
                            try:
                                comp_value = float(
                                    str(comp_filter.value).replace(',', '')
                                )
                            except (TypeError, ValueError):
                                # Skip invalid numeric filters gracefully
                                continue
                        else:
                            comp_value = comp_filter.value

                        if comp_filter.operator == 'gt':
                            query = query.filter(attr > comp_value)
                        elif comp_filter.operator == 'lt':
                            query = query.filter(attr < comp_value)
                        elif comp_filter.operator == 'gte':
                            query = query.filter(attr >= comp_value)
                        elif comp_filter.operator == 'lte':
                            query = query.filter(attr <= comp_value)
                        elif comp_filter.operator == 'eq':
                            query = query.filter(attr == comp_value)

            # Add ordering for consistent results
            query = query.order_by(
                InvoiceItem.date.desc(), InvoiceItem.id.desc())

            return query

        except Exception as e:
            logger.error(f"Error building ultra-optimized query: {e}")
            # Fallback to simple query
            return self.db.query(InvoiceItem).filter(InvoiceItem.is_active == True)

    def _execute_ultra_fast_filter_query(
        self,
        request: FilterRequest,
        page: int,
        size: int
    ) -> Tuple[List[InvoiceItem], int]:
        """
        Ultra-fast filter execution with aggressive optimizations.
        Handles massive datasets with streaming and memory management.
        """
        start_time = time.time()

        try:
            # Build optimized base query
            base_query = self._build_ultra_optimized_query(request)

            # Get total count with optimized counting
            count_start = time.time()
            total_count = self._get_optimized_count(base_query)
            logger.info(f"Count query took {time.time() - count_start:.3f}s")

            # Apply pagination with offset optimization
            offset = (page - 1) * size

            # Use raw SQL for maximum performance on large datasets
            if total_count > 5000:
                paginated_query = self._build_raw_paginated_query(
                    request, offset, size
                )
                result = self.db.execute(paginated_query)
                items = [self._row_to_invoice_item(row) for row in result]
            else:
                # Use SQLAlchemy for smaller datasets
                paginated_query = (
                    base_query
                    .offset(offset)
                    .limit(size)
                    .options(load_only(
                        InvoiceItem.id, InvoiceItem.item, InvoiceItem.vendor,
                        InvoiceItem.customer_job, InvoiceItem.cost,
                        InvoiceItem.qty, InvoiceItem.date, InvoiceItem.amount,
                        InvoiceItem.description, InvoiceItem.mpi_item,
                        InvoiceItem.class_, InvoiceItem.export_status
                    ))
                )
                items = paginated_query.all()

            # Apply item suffix transformation efficiently
            for item in items:
                if hasattr(item, 'vendor') and hasattr(item, 'item'):
                    item.display_item = self._calculate_item_suffix_fast(
                        item.item, item.vendor
                    )

            # Memory cleanup for large results
            if len(items) > 100:
                gc.collect()

            logger.info(f"Ultra-fast filter query took "
                        f"{time.time() - start_time:.3f}s, "
                        f"returned {len(items)}/{total_count} items")

            return items, total_count

        except Exception as e:
            logger.error(f"Ultra-fast filter query failed: {e}")
            traceback.print_exc()
            # Fallback to standard method
            return self._fallback_filter_query(request, page, size)

    def _build_raw_paginated_query(
        self,
        request: FilterRequest,
        offset: int,
        size: int
    ) -> text:
        """Build raw SQL query for maximum performance on large datasets."""

        # Base SELECT with essential columns only
        select_clause = """
            SELECT id, item, vendor, customer_job, cost, qty, date, amount,
                   description, mpi_item, class_, export_status,
                   CASE 
                       WHEN vendor LIKE '%BMW%' THEN CONCAT(item, '-B')
                       WHEN vendor LIKE '%Y&S%' OR vendor LIKE '%Y & S%' 
                           THEN CONCAT(item, '-Y')
                       ELSE item 
                   END as display_item
            FROM invoice_items 
            WHERE is_active = true
        """

        # Build WHERE conditions
        where_conditions = []

        if request.filters:
            for column, values in request.filters.items():
                if values and len(values) > 0:
                    # Strip spaces from filter values for consistent comparison
                    cleaned_values = []
                    for value in values:
                        if isinstance(value, str):
                            cleaned_values.append(value.strip())
                        else:
                            cleaned_values.append(value)
                    # Use ANY for better performance with indexes
                    placeholders = ','.join([f"'{v}'" for v in cleaned_values])
                    where_conditions.append(
                        f"{column} = ANY(ARRAY[{placeholders}])")

        if request.comparison_filters:
            for comp_filter in request.comparison_filters:
                # Handle amount (stored as text) by casting after removing commas
                if getattr(comp_filter, 'column', None) == 'amount':
                    column_sql = (
                        "CASE WHEN amount IS NOT NULL AND amount <> '' "
                        "AND length(amount) < 100 "
                        "AND REPLACE(amount, ',', '') ~ '^-?[0-9]*\\.?[0-9]+$' "
                        "THEN CAST(REPLACE(amount, ',', '') AS DOUBLE PRECISION) "
                        "ELSE NULL END"
                    )
                    try:
                        value_num = float(
                            str(comp_filter.value).replace(',', '')
                        )
                    except (TypeError, ValueError):
                        # Skip invalid numeric filters
                        continue
                else:
                    column_sql = comp_filter.column
                    value_num = comp_filter.value

                if comp_filter.operator == 'gt':
                    where_conditions.append(f"{column_sql} > {value_num}")
                elif comp_filter.operator == 'lt':
                    where_conditions.append(f"{column_sql} < {value_num}")
                elif comp_filter.operator == 'gte':
                    where_conditions.append(f"{column_sql} >= {value_num}")
                elif comp_filter.operator == 'lte':
                    where_conditions.append(f"{column_sql} <= {value_num}")

        # Combine conditions
        if where_conditions:
            select_clause += " AND " + " AND ".join(where_conditions)

        # Add ordering and pagination
        select_clause += f"""
            ORDER BY date DESC, id DESC
            LIMIT {size} OFFSET {offset}
        """

        return text(select_clause)

    @staticmethod
    def _calculate_item_suffix_fast(item: str, vendor: str) -> str:
        """Ultra-fast item suffix calculation with minimal string operations."""
        if not item or not vendor:
            return item or ""

        vendor_upper = vendor.upper()
        if 'BMW' in vendor_upper:
            return f"{item}-B"
        elif 'Y&S' in vendor_upper or 'Y & S' in vendor_upper:
            return f"{item}-Y"
        return item

    def _row_to_invoice_item(self, row) -> InvoiceItem:
        """Convert raw SQL row to InvoiceItem object efficiently."""
        item = InvoiceItem()

        # Map only essential fields for performance
        field_mapping = {
            'id': 0, 'item': 1, 'vendor': 2, 'customer_job': 3,
            'cost': 4, 'qty': 5, 'date': 6, 'amount': 7,
            'description': 8, 'mpi_item': 9, 'class_': 10,
            'export_status': 11, 'display_item': 12
        }

        for field, index in field_mapping.items():
            try:
                setattr(item, field, row[index] if len(row) > index else None)
            except (IndexError, AttributeError):
                setattr(item, field, None)

        return item

    def _get_optimized_count(self, query) -> int:
        """Get count with performance optimizations."""
        try:
            # Strip ordering for accurate counts on some backends
            count_query = select(func.count()).select_from(query.order_by(None).subquery())
            result = self.db.execute(count_query).scalar()
            return int(result or 0)
        except Exception:
            # Safe fallback: use ORM count (accurate, may be slower but correct)
            try:
                return int(query.order_by(None).count())
            except Exception:
                return 0

    def _fallback_filter_query(
        self,
        request: FilterRequest,
        page: int,
        size: int
    ) -> Tuple[List[InvoiceItem], int]:
        """Fallback method if ultra-optimizations fail."""
        try:
            query = self.db.query(InvoiceItem).filter(
                InvoiceItem.is_active == True)

            if request.filters:
                for column, values in request.filters.items():
                    if values:
                        attr = getattr(InvoiceItem, column)
                        # Strip spaces from filter values for consistent comparison
                        cleaned_values = []
                        for value in values:
                            if isinstance(value, str):
                                cleaned_values.append(value.strip())
                            else:
                                cleaned_values.append(value)
                        query = query.filter(attr.in_(cleaned_values))

            total = query.count()
            items = query.offset((page - 1) * size).limit(size).all()

            return items, total
        except Exception as e:
            logger.error(f"Fallback filter query failed: {e}")
            return [], 0

    def get_data_by_column_name(
        self,
        column_name: str,
        filter_context: Optional[Dict] = None,
        comparison_filters: Optional[List] = None
    ) -> List[str]:
        """
        Optimized version of get_data_by_column_name with caching and better performance.
        Now handles 10,000+ records efficiently while preserving ALL business logic.
        """
        # Validate column for safety (prevents SQL injection via dynamic columns)
        try:
            column_name = self._validate_safe_column(column_name)
        except ValueError as e:
            logger.warning(f"Rejected unsafe column in get_data_by_column_name: {e}")
            return []

        start_time = time.time()

        # Create cache keys for filter context and comparison filters
        filter_hash, comparison_hash = self._create_filter_hash(
            filter_context, comparison_filters or [])

        # For frequently accessed columns, use caching
        cacheable_columns = [
            'vendor', 'customer_job', 'class_', 'export_status']
        if column_name in cacheable_columns and not filter_context and not comparison_filters:
            try:
                return self._get_cached_distinct_values(column_name, filter_hash, comparison_hash)
            except:
                pass  # Fall back to non-cached version if caching fails

        # Use the optimized implementation
        result = self._get_distinct_values_optimized(
            column_name, filter_context, comparison_filters or [])

        logging.info(
            f"get_data_by_column_name for '{column_name}' took {time.time() - start_time:.2f}s")
        return result

    def get_data_by_column_name_paginated(
        self,
        column_name: str,
        page: int = 1,
        limit: int = 20,
        search: str = "",
        filter_context: Optional[Dict] = None,
        comparison_filters: Optional[List] = None,
        color_filters: Optional[Any] = None,
        price_change_filter: Optional[Any] = None,
        substring_search: bool = False,
        compare_all_supplier: bool = False
    ) -> Dict[str, Any]:
        """
        ULTRA-FAST paginated version with raw SQL optimization for production.

        Features:
        - Uses dbt-managed materialized view for simple queries (10-100x faster)
        - Falls back to raw SQL on invoice_items for complex filters
        - SQL injection safe with parameterized queries
        - Optimized search with database-level pattern matching
        - Efficient pagination using window functions
        - Aggressive caching for repeated queries
        - Supports three search modes: onword (default), substring (toggle), exact (quotes)

        Search Modes:
        - Default (onword): Match only when a word begins with the search text
        - Substring (toggle): Match anywhere inside the string (case-insensitive)
        - Exact (quotes): Full text exact match (case-sensitive)
        """
        start_time = time.time()
        
        # Validate column for safety (prevents SQL injection)

        try:
            column_name = self._validate_safe_column(column_name)
        except ValueError as e:
            logger.warning(f"Rejected unsafe column in get_data_by_column_name_paginated: {e}")
            return {
                "data": [],
                "page": page,
                "total_records": 0,
                "total_pages": 0
            }

        # Try to use dbt materialized view for simple queries
        # Create FilterRequest for the new unified DAO signature
        # Convert dict comparison_filters to Pydantic objects if needed
        pydantic_comparison_filters = []
        if comparison_filters:
            for cf in comparison_filters:
                if isinstance(cf, dict):
                    # Only add if it has the required fields and value is not None
                    if cf.get('column') and cf.get('operator') and 'value' in cf and cf['value'] is not None:
                        pydantic_comparison_filters.append(
                            ComparisonFilter(
                                column=cf['column'],
                                operator=cf['operator'],
                                value=cf['value']
                            )
                        )
                else:
                    # Already a Pydantic object
                    pydantic_comparison_filters.append(cf)

        filter_request = FilterRequest(
            filters=filter_context or {},
            comparison_filters=pydantic_comparison_filters,
            order_by=None,
            color_filters=color_filters,
            price_change_filter=price_change_filter,
            compare_all_supplier=compare_all_supplier
        )
        cleaned_request = self._validate_filter_request(filter_request)

        try:
            analytics_result = invoice_item_mart.get_paginated_unique_values(
                self.db, column_name, cleaned_request, page, limit, search, substring_search
            )
            
            if analytics_result is None:
                logger.error(f"DAO returned None for {column_name}")
                raise RuntimeError("Query failed. Check logs for details.")
            
            logger.info(f"Returning {len(analytics_result.data)} unique values for {column_name} page: {page}")
            logger.info(f"Execution time:{time.time() - start_time:.3f}s")

            return analytics_result.to_dict()

        except Exception as e:
            logger.error(f"DAO query failed for {column_name}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Query failed. Check logs for details.")

    def apply_filters(
        self,
        request: FilterRequest,
        page: Optional[int] = None,
        size: Optional[int] = None,
        col_param: Optional[str] = None,
        columns: Optional[List[str]] = None,
        total_hint: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Optimized version of apply_filters for handling 10,000+ records efficiently.
        Preserves ALL business logic including BMW/Y&S suffixes and proper pagination.
        Supports col_param for getting specific column values (used by export).

        Args:
            request: FilterRequest with filter criteria
            page: Page number (1-indexed), None for all records
            size: Items per page, None for all records
            col_param: Optional column parameter
            columns: Optional list of specific columns to select (instead of SELECT *)
            total_hint: Optional hint for total count so that we can skip the count query

        Note:
            If page or size is None, returns ALL matching records without pagination.
            Callers requiring pagination must explicitly pass page and size values.
        """
        start_time = time.time()
        logger.info(f"Request: {request}")

        dao_result = None
        # Create a new FilterRequest with cleaned and validated data
        cleaned_request = self._validate_filter_request(request, col_param)

        start_time = time.time()
        try:
            dao_result = invoice_item_mart.apply_filters(
                db=self.db,
                request=cleaned_request,
                page=page,
                size=size,
                columns=columns,
                total_hint=total_hint
            )
        except Exception as _:
            logger.exception("Failed to apply filters and get result")

        execution_time = time.time() - start_time

        # Handle DAO result based on feature flags
        if not dao_result:
            raise ValueError(f"Expected to have some result after {execution_time:.3f}s. Got none")


        logger.info(f"Returned {len(dao_result.items)} items in {execution_time:.3f}s")
        return dao_result.to_dict()

    def process_pdf_export_in_background(self, export_id: str, request: FilterRequest, export_status_file:str):
        """
        Background task to process PDF export.
        Moves logic from route to controller for better organization.
        Optimized to only fetch essential columns from DB.
        """
        
        temp_dir = os.path.join(INVOICE_DOWNLOAD_FOLDER, f'temp_{export_id}')
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            # 1. Get ONLY filename (which is the S3 key) to maximize DB optimization
            result = self.apply_filters(request, page=None, size=None, columns=['filename'])
            
            # Extract unique S3 keys (filenames) and deduplicate
            available_items = result.get('items', [])
            s3_keys = list(set([item.get('filename') for item in available_items if item.get('filename')]))

            if not s3_keys:
                logger.warning(f"No matching files found for export {export_id}")
                with open(export_status_file, 'w') as f:
                    json.dump({'status': 'failed', 'error': 'No matching invoice files found'}, f)
                return

            # Update status
            with open(export_status_file, 'w') as f:
                json.dump({
                    'status': 'processing',
                    'export_id': export_id,
                    'record_count': len(s3_keys),
                    'started_at': datetime.now().isoformat(),
                    'message': f'Found {len(s3_keys)} unique invoices. Starting download...'
                }, f)

            # 2. Download PDFs from S3
            downloaded_files = []
            total = len(s3_keys)
            for file_key in s3_keys:
                local_filename = os.path.basename(file_key)
                if not local_filename.lower().endswith('.pdf'):
                    local_filename += ".pdf"
                    
                local_path = os.path.join(temp_dir, local_filename)

                if download_s3_file(file_key, local_path):
                    downloaded_files.append(local_path)

            if not downloaded_files:
                logger.error(f"Failed to download any of the {total} files for export {export_id}")
                with open(export_status_file, 'w') as f:
                    json.dump({'status': 'failed', 'error': 'Failed to download any PDFs from S3. Keys might be missing.'}, f)
                return

            # 3. Create ZIP archive
            zip_filename = f"invoices_export_{export_id}.zip"
            zip_path = os.path.join(INVOICE_DOWNLOAD_FOLDER, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file_path in downloaded_files:
                    zipf.write(file_path, os.path.basename(file_path))

            s3_zip_key = f"Exports/PDFs/{zip_filename}"
            download_url = upload_export_and_get_url(
                zip_path,
                s3_zip_key,
            )
            with open(export_status_file, 'w') as f:
                json.dump({
                    'status': 'completed',
                    'download_url': download_url,
                    'message': 'Export completed successfully'
                }, f)

        except Exception as e:
            logger.exception("Error in PDF export background task")
            with open(export_status_file, 'w') as f:
                json.dump({'status': 'failed', 'error': str(e)}, f)
        finally:
            # Cleanup temp directory
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as cleanup_err:
                    logger.warning(f"Failed to cleanup temp dir {temp_dir}: {cleanup_err}")

    def _ensure_accounts_assigned(self, items: List[InvoiceItem]) -> None:
        """
        Assign accounts to items in-memory and persist if missing.
        Does not overwrite any non-empty account values.
        """
        updated = False
        for item in items:
            try:
                current = (item.account or '').strip()
                if current:
                    continue
                new_letter = self._auto_assign_account(
                    sheet_name=getattr(item, 'sheet_name', ''),
                    current_account=current,
                    mpi_item=getattr(item, 'mpi_item', '')
                )
                if new_letter and new_letter != current:
                    item.account = new_letter
                    updated = True
            except Exception:
                continue

        if updated:
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

    def insert_invoice_items(self, row, filename, invoice_id):
        """
        Insert invoice item with duplicate checking.
        Checks if an item with the same invoice_id, ref_no, vendor, date, and amount already exists.
        """
        # Add proper suffix to item code based on vendor
        item_with_suffix = self._add_suffix_to_item(row['Item'], row['Vendor'])

        # Robust date parsing
        date_str = str(row['Date'])
        try:
            parsed_dt = datetime.strptime(date_str, '%m/%d/%Y')
        except ValueError:
            try:
                parsed_dt = datetime.strptime(date_str, '%m/%d/%y')
            except ValueError:
                logger.error(f"Could not parse date: {date_str}")
                parsed_dt = None
        parsed_date = parsed_dt.date() if parsed_dt else None

        # Check for existing item with same invoice_id, ref_no, vendor, date, and amount
        # Normalize types to match DB schema (ref_no and amount are stored as strings)
        ref_no_val = str(row['Ref NO']).strip() if row.get('Ref NO') is not None else ""
        vendor_val = str(row['Vendor']).strip() if row.get('Vendor') is not None else ""
        amount_val = str(row['Amount']).strip() if row.get('Amount') is not None else ""
        
        # Handle CR- reference numbers by making amounts negative
        if ref_no_val.startswith('CR-'):
            try:
                # Parse the amount and make it negative
                parsed_amount = parse_number(amount_val)
                if parsed_amount is not None:
                    amount_val = str(-abs(parsed_amount))
                    logger.info(f"Credit memo item detected (ref_no: {ref_no_val}), converting amount from {row['Amount']} to {amount_val}")
            except Exception as e:
                logger.warning(f"Could not parse amount for credit memo {ref_no_val}: {str(e)}")
                # Keep original amount if parsing fails

        existing_item = (
            self.db.query(InvoiceItem)
            .filter(
                InvoiceItem.invoice_id == invoice_id,
                InvoiceItem.ref_no == ref_no_val,
                InvoiceItem.vendor == vendor_val,
                InvoiceItem.date == parsed_date,
                InvoiceItem.amount == amount_val,
                InvoiceItem.is_active == True,
            )
            .first()
        )

        if existing_item:
            logger.warning(
                f"Item already exists for invoice_id: {invoice_id}, ref_no: {row['Ref NO']}, vendor: {row['Vendor']}, date: {parsed_date}, amount: {row['Amount']}. Skipping insertion.")
            return

        # Determine account assignment based on item classification
        auto_account = self._auto_assign_account(
            sheet_name=row.get('Sheet Name', ''),
            current_account=row.get('Account', ''),
            mpi_item=row.get('MpiItem', '')
        )

        new_item = InvoiceItem(
            filename=filename,
            sheet_name=row['Sheet Name'],
            invoice_id=invoice_id,
            mpi_item=row['MpiItem'],
            mpi_description=row['MpiDescription'],
            item=item_with_suffix,  # Use item with proper suffix
            description=row['Description'],
            qty=row['Qty'],
            cost=row['Cost'],
            amount=amount_val,
            date=parsed_date,
            ref_no=ref_no_val,
            po_number=row['PO #'],
            customer_job=row['Customer Job'],
            bill=row['Bill'],
            vendor=vendor_val,
            class_=row['Class'],
            account=auto_account,
            memo=row['Memo'],
            buyer=row['Buyer'],
            date_added=row['email_date'],
            export_status="Pending"
        )
        self.db.add(new_item)
        self.db.commit()
        # Normalize long QB account paths to letters after commit, if needed
        try:
            if new_item.account and isinstance(new_item.account, str):
                low = new_item.account.lower()
                if 'job materials purchased' in low:
                    if new_item.account != 'M':
                        new_item.account = 'M'
                        self.db.commit()
                elif 'job equipment' in low:
                    if new_item.account != 'E':
                        new_item.account = 'E'
                        self.db.commit()
        except Exception:
            self.db.rollback()

    def _auto_assign_account(self, sheet_name: Optional[str], current_account: Optional[str], mpi_item: Optional[str] = None) -> str:
        """
        Decide account value for a new item based on ItemClassification table.
        Rules:
        - Preserve explicit 'A' if provided
        - If UIDI mpi_item category implies M/E, use that letter
        - Else if classification category is 'M' or 'E' (exact match), use that letter
        - Else try fuzzy classification (like QuickBooks) and map to M/E only
        - If category is 'L' or unknown, keep current
        - Return empty string if nothing applicable and current is falsy
        """
        try:
            current = (current_account or '').strip()
            if current.upper() == 'A':
                return current

            # UIDI-specific mapping by mpi_item (case-insensitive exacts)
            mpi = (mpi_item or '').strip()
            if mpi:
                mpi_upper = mpi.upper()
                uidi_to_letter = {
                    'UIDI-JOB MATERIALS PURCHASED': 'M',
                    'UIDI JOB MATERIAL': 'M',
                    'UIDI-JOB EQUIPMENT': 'E',
                    'UIDI-SPRINKLER SPECIALTY ITEM': 'M',
                    'UIDI-DRAINAGE MATERIAL': 'M',
                }
                if mpi_upper in uidi_to_letter and not current:
                    return uidi_to_letter[mpi_upper]

            sheet = (sheet_name or '').strip()
            if not sheet:
                return current

            # Lazy import to avoid circulars
            from mpi_backend.database.models.ItemClassification import ItemClassification as IC

            # First try exact match on classification table
            row = self.db.query(IC).filter(IC.item == sheet).first()
            if row:
                category = (row.category or '').strip().upper()
                if category == 'L':
                    return current
                if category in ('M', 'E'):
                    return category

            # Fuzzy fallback via ItemClassificationController (maps similar to QuickBooks logic)
            try:
                from mpi_backend.database.controllers.ItemClassification import (
                    ItemClassificationController,
                )
                icc = ItemClassificationController(self.db)
                qb_account = icc.get_classification(sheet)
                # Map QB account string to our letter codes; only accept M/E
                qb_lower = (qb_account or '').lower()
                if 'job materials purchased' in qb_lower:
                    return 'M'
                if 'job equipment' in qb_lower:
                    return 'E'
                # Do not auto-set 'A' here; A is user-chosen
            except Exception:
                pass

            return current
        except Exception:
            return (current_account or '').strip()

    def invoice_exists(self, reference_no, vendor):
        """
        Check if an invoice exists with the given reference number and vendor.
        This is a simple check that doesn't consider date and amount.
        For comprehensive duplicate detection, use check_invoice_duplicate_status().
        Uses normalized reference number comparison to handle leading zero differences.
        """
        # Normalize the reference number for comparison
        normalized_ref_no = self._normalize_ref_no_for_comparison(reference_no)
        
        # Query for existing invoices with same vendor
        all_existing_items = self.db.query(InvoiceItem).filter(
            InvoiceItem.vendor == vendor,
            InvoiceItem.is_active == True
        ).all()
        
        # Check if any item has matching normalized reference number
        for item in all_existing_items:
            item_normalized_ref = self._normalize_ref_no_for_comparison(item.ref_no)
            if item_normalized_ref == normalized_ref_no:
                return True
        
        return False

    def find_duplicate_invoices(self, reference_no, vendor, date, amount):
        """
        Find all duplicate invoices with the same ref_no, vendor, date, and amount.
        This method helps identify existing duplicates that need to be cleaned up.

        Args:
            reference_no: Invoice reference number
            vendor: Vendor name
            date: Invoice date
            amount: Total invoice amount

        Returns:
            List of duplicate invoice IDs
        """
        try:
            # Normalize inputs
            ref_no = str(reference_no).strip() if reference_no else ""
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
            existing_items = self.db.query(InvoiceItem).filter(
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
            logger.error(f"Error finding duplicate invoices: {str(e)}")
            return []

    def cleanup_duplicate_invoices(self, reference_no, vendor, date, amount, keep_most_recent=True):
        """
        Clean up duplicate invoices by keeping only the most recent one and marking others as inactive.

        Args:
            reference_no: Invoice reference number
            vendor: Vendor name
            date: Invoice date
            amount: Total invoice amount
            keep_most_recent: If True, keep the most recent invoice; if False, keep the oldest

        Returns:
            Dict with cleanup results
        """
        try:
            duplicate_ids = self.find_duplicate_invoices(
                reference_no, vendor, date, amount)

            if len(duplicate_ids) <= 1:
                return {
                    'status': 'no_duplicates',
                    'message': f'No duplicates found for RefNo: {reference_no}, Vendor: {vendor}',
                    'kept_invoice_id': duplicate_ids[0] if duplicate_ids else None,
                    'removed_count': 0
                }

            # Get the invoice to keep (most recent or oldest)
            if keep_most_recent:
                # Find the most recent invoice by date_added
                most_recent_item = self.db.query(InvoiceItem).filter(
                    InvoiceItem.invoice_id.in_(duplicate_ids)
                ).order_by(InvoiceItem.date_added.desc(), InvoiceItem.id.desc()).first()

                keep_invoice_id = most_recent_item.invoice_id if most_recent_item else duplicate_ids[
                    0]
            else:
                # Find the oldest invoice by date_added
                oldest_item = self.db.query(InvoiceItem).filter(
                    InvoiceItem.invoice_id.in_(duplicate_ids)
                ).order_by(InvoiceItem.date_added.asc(), InvoiceItem.id.asc()).first()

                keep_invoice_id = oldest_item.invoice_id if oldest_item else duplicate_ids[0]

            # Mark other duplicates as inactive
            removed_count = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id.in_(duplicate_ids),
                InvoiceItem.invoice_id != keep_invoice_id
            ).update({'is_active': False})

            self.db.commit()

            logger.info(
                f'Cleaned up {removed_count} duplicate invoices for RefNo: {reference_no}, Vendor: {vendor}. Kept invoice: {keep_invoice_id}')

            return {
                'status': 'cleaned',
                'message': f'Cleaned up {removed_count} duplicate invoices',
                'kept_invoice_id': keep_invoice_id,
                'removed_count': removed_count,
                'total_duplicates': len(duplicate_ids)
            }

        except Exception as e:
            logger.error(f"Error cleaning up duplicate invoices: {str(e)}")
            self.db.rollback()
            return {
                'status': 'error',
                'message': f'Error cleaning up duplicates: {str(e)}',
                'kept_invoice_id': None,
                'removed_count': 0
            }

    def delete_duplicate_invoices(self, reference_no, vendor, date, amount, keep_most_recent=True):
        """
        Delete duplicate invoices with the same ref_no, vendor, date, and amount.
        This method permanently deletes the duplicate records from the database.

        Args:
            reference_no: Invoice reference number
            vendor: Vendor name
            date: Invoice date
            amount: Total invoice amount
            keep_most_recent: If True, keep the most recent invoice; if False, keep the oldest

        Returns:
            Dict with deletion results
        """
        try:
            duplicate_ids = self.find_duplicate_invoices(
                reference_no, vendor, date, amount)

            if len(duplicate_ids) <= 1:
                return {
                    'status': 'no_duplicates',
                    'message': f'No duplicates found for RefNo: {reference_no}, Vendor: {vendor}',
                    'kept_invoice_id': duplicate_ids[0] if duplicate_ids else None,
                    'removed_count': 0
                }

            # Get the invoice to keep (most recent or oldest)
            if keep_most_recent:
                # Find the most recent invoice by date_added
                most_recent_item = self.db.query(InvoiceItem).filter(
                    InvoiceItem.invoice_id.in_(duplicate_ids)
                ).order_by(InvoiceItem.date_added.desc(), InvoiceItem.id.desc()).first()

                keep_invoice_id = most_recent_item.invoice_id if most_recent_item else duplicate_ids[
                    0]
            else:
                # Find the oldest invoice by date_added
                oldest_item = self.db.query(InvoiceItem).filter(
                    InvoiceItem.invoice_id.in_(duplicate_ids)
                ).order_by(InvoiceItem.date_added.asc(), InvoiceItem.id.asc()).first()

                keep_invoice_id = oldest_item.invoice_id if oldest_item else duplicate_ids[0]

            # Delete other duplicates permanently
            deleted_count = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id.in_(duplicate_ids),
                InvoiceItem.invoice_id != keep_invoice_id
            ).delete(synchronize_session=False)

            self.db.commit()

            logger.info(
                f'Deleted {deleted_count} duplicate invoices for RefNo: {reference_no}, Vendor: {vendor}. Kept invoice: {keep_invoice_id}')

            return {
                'status': 'deleted',
                'message': f'Deleted {deleted_count} duplicate invoices',
                'kept_invoice_id': keep_invoice_id,
                'removed_count': deleted_count,
                'total_duplicates': len(duplicate_ids)
            }

        except Exception as e:
            logger.error(f"Error deleting duplicate invoices: {str(e)}")
            self.db.rollback()
            return {
                'status': 'error',
                'message': f'Error deleting duplicates: {str(e)}',
                'kept_invoice_id': None,
                'removed_count': 0
            }

    def cleanup_exact_duplicate_inactive_items(self, invoice_id):
        """
        Clean up any inactive items (is_active = false) from an exact duplicate invoice.
        This is called when we have an exact duplicate to ensure only active items remain.
        
        Args:
            invoice_id: The invoice ID to clean up
            
        Returns:
            int: Number of inactive items deleted
        """
        try:
            # Find and delete any inactive items for this invoice
            deleted_count = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id == invoice_id,
                InvoiceItem.is_active == False
            ).delete(synchronize_session=False)
            
            if deleted_count > 0:
                self.db.commit()
                logger.info(f"Cleaned up {deleted_count} inactive items from invoice {invoice_id}")
            
            return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up inactive items for invoice {invoice_id}: {str(e)}")
            self.db.rollback()
            return 0

    def delete_previous_invoice_for_update(self, invoice_id):
        """
        Delete the previous invoice when we have same ref_no but different items.
        This is called when we need to replace an existing invoice with updated items.
        
        Args:
            invoice_id: The invoice ID to delete
            
        Returns:
            int: Number of items deleted
        """
        try:
            # Delete all items for this invoice
            deleted_count = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id == invoice_id
            ).delete(synchronize_session=False)
            
            if deleted_count > 0:
                self.db.commit()
                logger.info(f"Deleted {deleted_count} items from previous invoice {invoice_id} for update")
            
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting previous invoice {invoice_id}: {str(e)}")
            self.db.rollback()
            return 0

    def check_invoice_duplicate_status(self, reference_no, vendor, date, amount, customer_job=None):
        """
        Enhanced duplicate detection with comprehensive logic to prevent multiple invoices:
        1. Exact Duplicate: Same ref_no, vendor, date, total amount (within tolerance), and customer_job -> Skip
        2. Updated Invoice: Same ref_no, vendor, and date, different total amount or customer_job -> Refresh
        3. New Invoice: Same ref_no and vendor but different date/total amount/customer_job -> Add as New

        Args:
            reference_no: Invoice reference number
            vendor: Vendor name
            date: Invoice date
            amount: Total invoice amount (sum of all items)
            customer_job: Customer job (ship-to address) - NEW PARAMETER

        Returns:
            Dict with status and details:
            {
                'status': 'exact_duplicate' | 'updated_invoice' | 'new_invoice' | 'not_found',
                'existing_invoice_id': UUID or None,
                'existing_amount': str or None,
                'existing_date': date or None,
                'existing_customer_job': str or None,
                'message': str
            }
        """
        try:
            # Normalize inputs
            ref_no = str(reference_no).strip() if reference_no else ""
            vendor_str = str(vendor).strip() if vendor else ""
            date_obj = date if hasattr(date, 'date') else date
            amount_str = str(amount).strip() if amount else ""
            customer_job_str = str(customer_job).strip() if customer_job else ""

            # Convert amounts to float for comparison with tolerance
            try:
                new_amount_float = float(amount_str) if amount_str else 0.0
            except (ValueError, TypeError):
                new_amount_float = 0.0
                logger.warning(
                    f"Could not convert new amount '{amount_str}' to float, using 0.0")

            if not ref_no or not vendor_str:
                return {
                    'status': 'not_found',
                    'existing_invoice_id': None,
                    'existing_amount': None,
                    'existing_date': None,
                    'existing_customer_job': None,
                    'message': 'Missing reference number or vendor'
                }

            # Normalize the reference number for comparison
            normalized_ref_no = self._normalize_ref_no_for_comparison(ref_no)
            
            # Query for existing invoices with same vendor
            # We'll filter by normalized ref_no in Python to handle leading zero differences
            # Only check active items (is_active is not false)
            all_existing_items = self.db.query(InvoiceItem).filter(
                InvoiceItem.vendor == vendor_str,
                InvoiceItem.is_active != False  # Include True and NULL values
            ).all()
            
            # Filter by normalized reference number comparison
            existing_items = []
            for item in all_existing_items:
                item_normalized_ref = self._normalize_ref_no_for_comparison(item.ref_no)
                if item_normalized_ref == normalized_ref_no:
                    existing_items.append(item)

            if not existing_items:
                return {
                    'status': 'not_found',
                    'existing_invoice_id': None,
                    'existing_amount': None,
                    'existing_date': None,
                    'message': f'No existing invoice found for RefNo: {ref_no}, Vendor: {vendor_str}'
                }

            # Group items by invoice_id to calculate total amounts per invoice
            invoice_totals = {}
            invoice_dates = {}
            invoice_date_added = {}
            invoice_customer_jobs = {}

            for item in existing_items:
                invoice_id = item.invoice_id
                if invoice_id not in invoice_totals:
                    invoice_totals[invoice_id] = 0
                    invoice_dates[invoice_id] = item.date
                    invoice_date_added[invoice_id] = item.date_added
                    invoice_customer_jobs[invoice_id] = item.customer_job

                # Add item amount to invoice total
                try:
                    item_amount = float(item.amount) if item.amount else 0
                    invoice_totals[invoice_id] += item_amount
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid amount value for item {item.id}: {item.amount}")
                    continue

            # Define tolerance for floating-point comparison (0.01 cents)
            tolerance = 0.01

            # Check for EXACT duplicates first (same ref_no, vendor, date, amount, and customer_job)
            exact_duplicates = []
            for invoice_id, total_amount in invoice_totals.items():
                existing_amount_float = float(total_amount)
                existing_date = invoice_dates[invoice_id]
                existing_customer_job = invoice_customer_jobs[invoice_id]

                # Check if amounts are within tolerance
                amount_difference = abs(
                    new_amount_float - existing_amount_float)
                amounts_equal = amount_difference <= tolerance

                # Check if dates match
                dates_equal = existing_date == date_obj

                # Check if customer jobs match (normalize for comparison)
                existing_customer_job_normalized = str(existing_customer_job).strip().lower() if existing_customer_job else ""
                new_customer_job_normalized = customer_job_str.strip().lower()
                customer_jobs_equal = existing_customer_job_normalized == new_customer_job_normalized

                if dates_equal and amounts_equal and customer_jobs_equal:
                    exact_duplicates.append({
                        'invoice_id': invoice_id,
                        'amount': existing_amount_float,
                        'date': existing_date,
                        'date_added': invoice_date_added[invoice_id],
                        'customer_job': existing_customer_job
                    })

            # If we found exact duplicates, check if we need to update reference number
            if exact_duplicates:
                # Sort by date_added (most recent first), then by invoice_id
                exact_duplicates.sort(key=lambda x: (
                    x['date_added'] or date.min, x['invoice_id']), reverse=True)
                most_recent_duplicate = exact_duplicates[0]

                # Check if the reference number format needs to be updated
                # Get the existing reference number from the most recent duplicate
                existing_ref_no = None
                for item in existing_items:
                    if item.invoice_id == most_recent_duplicate['invoice_id']:
                        existing_ref_no = item.ref_no
                        break
                
                # If the new reference number has leading zeros and the existing one doesn't,
                # or vice versa, we should update the reference number
                needs_ref_update = False
                if existing_ref_no and existing_ref_no != ref_no:
                    # Check if one has leading zeros and the other doesn't
                    existing_normalized = self._normalize_ref_no_for_comparison(existing_ref_no)
                    new_normalized = self._normalize_ref_no_for_comparison(ref_no)
                    
                    if existing_normalized == new_normalized and existing_ref_no != ref_no:
                        needs_ref_update = True
                        logger.info(f"Reference number format update needed: '{existing_ref_no}' -> '{ref_no}'")

                if needs_ref_update:
                    logger.warning(
                        f"Found {len(exact_duplicates)} exact duplicate(s) for RefNo: {ref_no}, Vendor: {vendor_str}, Date: {date_obj}, Amount: {new_amount_float}. Updating reference number format: '{existing_ref_no}' -> '{ref_no}'")
                    
                    return {
                        'status': 'exact_duplicate_with_ref_update',
                        'existing_invoice_id': most_recent_duplicate['invoice_id'],
                        'existing_amount': str(most_recent_duplicate['amount']),
                        'existing_date': most_recent_duplicate['date'],
                        'existing_ref_no': existing_ref_no,
                        'new_ref_no': ref_no,
                        'message': f'Found {len(exact_duplicates)} exact duplicate(s) for RefNo: {ref_no}, Vendor: {vendor_str}, Date: {date_obj}, Amount: {new_amount_float}. Updating reference number format: "{existing_ref_no}" -> "{ref_no}".'
                    }
                else:
                    logger.warning(
                        f"Found {len(exact_duplicates)} exact duplicate(s) for RefNo: {ref_no}, Vendor: {vendor_str}, Date: {date_obj}, Amount: {new_amount_float}. Using most recent: {most_recent_duplicate['invoice_id']}")
                    
                    # Clean up any inactive items from the exact duplicate
                    cleaned_count = self.cleanup_exact_duplicate_inactive_items(most_recent_duplicate['invoice_id'])

                    return {
                        'status': 'exact_duplicate',
                        'existing_invoice_id': most_recent_duplicate['invoice_id'],
                        'existing_amount': str(most_recent_duplicate['amount']),
                        'existing_date': most_recent_duplicate['date'],
                        'existing_customer_job': most_recent_duplicate['customer_job'],
                        'cleaned_inactive_items': cleaned_count,
                        'message': f'Found {len(exact_duplicates)} exact duplicate(s) for RefNo: {ref_no}, Vendor: {vendor_str}, Date: {date_obj}, Amount: {new_amount_float}, CustomerJob: {customer_job_str}. Using most recent invoice {most_recent_duplicate["invoice_id"]}. Cleaned up {cleaned_count} inactive items.'
                    }

            # Check for updated invoice (same ref_no, vendor, and date, different total amount or customer_job)
            updated_invoices = []
            for invoice_id, total_amount in invoice_totals.items():
                existing_amount_float = float(total_amount)
                existing_date = invoice_dates[invoice_id]
                existing_customer_job = invoice_customer_jobs[invoice_id]

                # Check if dates match but amounts or customer jobs differ
                dates_equal = existing_date == date_obj
                amount_difference = abs(
                    new_amount_float - existing_amount_float)
                amounts_different = amount_difference > tolerance

                # Check if customer jobs differ (normalize for comparison)
                existing_customer_job_normalized = str(existing_customer_job).strip().lower() if existing_customer_job else ""
                new_customer_job_normalized = customer_job_str.strip().lower()
                customer_jobs_different = existing_customer_job_normalized != new_customer_job_normalized

                if dates_equal and (amounts_different or customer_jobs_different):
                    updated_invoices.append({
                        'invoice_id': invoice_id,
                        'amount': existing_amount_float,
                        'date': existing_date,
                        'date_added': invoice_date_added[invoice_id],
                        'customer_job': existing_customer_job,
                        'difference': amount_difference,
                        'customer_job_changed': customer_jobs_different
                    })

            # If we found updated invoices, delete the previous and add new one
            if updated_invoices:
                # Sort by date_added (most recent first), then by invoice_id
                updated_invoices.sort(key=lambda x: (
                    x['date_added'] or date.min, x['invoice_id']), reverse=True)
                most_recent_updated = updated_invoices[0]

                logger.info(
                    f"Found {len(updated_invoices)} updated invoice(s) for RefNo: {ref_no}, Vendor: {vendor_str}, Date: {date_obj}, CustomerJob: {customer_job_str}. Deleting previous and adding new: {most_recent_updated['invoice_id']}")

                # Delete the previous invoice items
                deleted_count = self.delete_previous_invoice_for_update(most_recent_updated['invoice_id'])

                # Determine what changed
                change_reason = []
                if most_recent_updated.get('customer_job_changed', False):
                    change_reason.append(f"customer job changed from '{most_recent_updated['customer_job']}' to '{customer_job_str}'")
                if most_recent_updated['difference'] > tolerance:
                    change_reason.append(f"amount difference: {most_recent_updated['difference']:.2f}")
                
                change_description = " and ".join(change_reason) if change_reason else "unknown changes"

                return {
                    'status': 'updated_invoice',
                    'existing_invoice_id': most_recent_updated['invoice_id'],
                    'existing_amount': str(most_recent_updated['amount']),
                    'existing_date': most_recent_updated['date'],
                    'existing_customer_job': most_recent_updated['customer_job'],
                    'deleted_previous_items': deleted_count,
                    'message': f'Found {len(updated_invoices)} updated invoice(s) for RefNo: {ref_no}, Vendor: {vendor_str}, Date: {date_obj}, CustomerJob: {customer_job_str}. Deleted {deleted_count} previous items from invoice {most_recent_updated["invoice_id"]} due to {change_description}. Will add new items.'
                }

            # New invoice with same ref_no and vendor but different date/total amount
            # Find the most recent invoice for reference
            most_recent_item = max(existing_items, key=lambda item: (
                item.date_added or date.min, item.id))
            most_recent_invoice_id = most_recent_item.invoice_id
            existing_total_amount = invoice_totals.get(
                most_recent_invoice_id, 0)
            existing_date = invoice_dates.get(most_recent_invoice_id)

            return {
                'status': 'new_invoice',
                'existing_invoice_id': None,
                'existing_amount': str(existing_total_amount),
                'existing_date': existing_date,
                'message': f'New invoice with existing RefNo: {ref_no} and Vendor: {vendor_str} but different Date/Total Amount. Treating as a new invoice.'
            }

        except Exception as e:
            logger.error(f"Error in check_invoice_duplicate_status: {str(e)}")
            return {
                'status': 'error',
                'existing_invoice_id': None,
                'existing_amount': None,
                'existing_date': None,
                'existing_customer_job': None,
                'message': f'Error checking duplicate status: {str(e)}'
            }

    def get_invoice_items(self, invoice_id=None):
        query = self.db.query(InvoiceItem)
        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)

        # Apply empty item filter
        query = self._apply_empty_item_filter(query)
        query = query.order_by(InvoiceItem.id.desc())
        items = query.all()

        invoices_items = []
        for item in items:
            item_dict = item.__dict__.copy()
            # Use the full item code as stored in database
            item_dict['item'] = item.item
            # Format cost and amount with commas for better readability
            if 'cost' in item_dict and item_dict['cost'] is not None:
                item_dict['cost'] = format_currency(item_dict['cost'])
            if 'amount' in item_dict and item_dict['amount'] is not None:
                item_dict['amount'] = format_currency(item_dict['amount'])
            invoices_items.append(InvoiceItemsResponse(**item_dict))

        return invoices_items

    def get_invoice_items_by_filters(self, supplier=None, from_date=None, to_date=None, job_location=None,
                                     export_status=None,
                                     page: int = 1, page_size: int = 10):
        query = self.db.query(InvoiceItem)

        # only apply supplier filter if it's provided.
        if supplier is not None and 'All' not in supplier:
            query = query.filter(InvoiceItem.vendor.in_(supplier))

        if job_location:
            query = query.filter(InvoiceItem.customer_job == job_location)

        if export_status:
            query = query.filter(InvoiceItem.export_status == export_status)

        query = query.filter(InvoiceItem.date >= from_date)
        query = query.filter(InvoiceItem.date <= to_date)
        query = query.order_by(InvoiceItem.id.desc())
        total = query.count()
        if page_size == 0:
            items = query.all()
            page_size = 1
            total = len(items)
        else:
            query = query.limit(page_size).offset((page - 1) * page_size)
            items = query.all()

        invoices_items = []
        for item in items:
            item_dict = item.__dict__.copy()
            # Use the full item code as stored in database
            item_dict['item'] = item.item
            # Format cost and amount with commas for better readability
            if 'cost' in item_dict and item_dict['cost'] is not None:
                item_dict['cost'] = format_currency(item_dict['cost'])
            if 'amount' in item_dict and item_dict['amount'] is not None:
                item_dict['amount'] = format_currency(item_dict['amount'])
            invoices_items.append(InvoiceItemsResponse(**item_dict))

        return {
            "items": invoices_items,
            "total": total,
            "page": page,
            "size": page_size,
            "pages": ceil(total / page_size)
        }

    def count_line_items(self):
        query = self.db.query(InvoiceItem)
        total = query.count()
        return total

    def count_items_for_invoice(self, invoice_id):
        """
        Count the number of active items for a specific invoice.
        
        Args:
            invoice_id: UUID of the invoice
            
        Returns:
            int: Number of active items for the invoice
        """
        try:
            count = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id == invoice_id,
                InvoiceItem.is_active.isnot(False)  # Include True and NULL values
            ).count()
            return count
        except Exception as e:
            logger.error(f"Error counting items for invoice {invoice_id}: {str(e)}")
            return 0

    def get_invoice_items_by_ids(self, ids, order_by=None):
        query = self.db.query(InvoiceItem)

        # if ids:
        #     case_statement = case({id_: idx for idx, id_ in enumerate(ids)}, value=InvoiceItem.id) #order the results based on the order of the IDs
        #     query = query.filter(InvoiceItem.id.in_(ids)).order_by(case_statement) # commenting out because of slow performance

        if ids:
            query = query.filter(InvoiceItem.id.in_(ids))

        # Apply ordering if provided
        if order_by:
            for order_filter in order_by:
                if not hasattr(InvoiceItem, order_filter.column):
                    raise HTTPException(status_code=400,
                                        detail=f"Invalid column name for ordering: {order_filter.column}")

                column = getattr(InvoiceItem, order_filter.column)

                if order_filter.order == "asc":
                    query = query.order_by(column.asc())
                elif order_filter.order == "desc":
                    query = query.order_by(column.desc())

        items = query.all()

        # Apply duplication filtering to remove exact duplicates (consistent with filter endpoint)
        from mpi_backend.utils.duplication_filter import filter_exact_duplicates
        items = filter_exact_duplicates(items)

        invoices_items = []
        for item in items:
            item_dict = item.__dict__.copy()
            # Use the full item code as stored in database
            item_dict['item'] = item.item
            # Format cost and amount with commas for better readability
            if 'cost' in item_dict and item_dict['cost'] is not None:
                item_dict['cost'] = format_currency(item_dict['cost'])
            if 'amount' in item_dict and item_dict['amount'] is not None:
                item_dict['amount'] = format_currency(item_dict['amount'])
            invoices_items.append(InvoiceItemsResponse(**item_dict))
        return invoices_items

    def get_invoice_items_for_export_optimized(self, ids, columns=None, order_by=None):
        """
        Optimized method for exporting invoice items with minimal memory overhead.
        Returns raw database tuples instead of full objects for better performance.

        Args:
            ids: List of invoice item IDs
            columns: List of column names to include (optional)
            order_by: List of OrderByFilter objects (optional)

        Returns:
            List of tuples with selected data
        """
        if not ids:
            return []

        # Define columns mapping
        available_columns = {
            'item': InvoiceItem.item,
            'description': InvoiceItem.description,
            'qty': InvoiceItem.qty,
            'cost': InvoiceItem.cost,
            'amount': InvoiceItem.amount,
            'date': InvoiceItem.date,
            'ref_no': InvoiceItem.ref_no,
            'po_number': InvoiceItem.po_number,
            'customer_job': InvoiceItem.customer_job,
            'bill': InvoiceItem.bill,
            'vendor': InvoiceItem.vendor,
            'class_': InvoiceItem.class_,
            'account': InvoiceItem.account,
            'memo': InvoiceItem.memo,
            'buyer': InvoiceItem.buyer,
            'filename': InvoiceItem.filename,
            'sheet_name': InvoiceItem.sheet_name,
            'mpi_item': InvoiceItem.mpi_item,
            'mpi_description': InvoiceItem.mpi_description,
            'date_added': InvoiceItem.date_added
        }

        # Determine which columns to select
        if columns:
            # Map display column names back to database columns
            column_mapping = {
                'Item': 'item',
                'Description': 'description',
                'Qty': 'qty',
                'Cost': 'cost',
                'Amount': 'amount',
                'Date': 'date',
                'Ref NO': 'ref_no',
                'PO #': 'po_number',
                'Customer Job': 'customer_job',
                'Bill': 'bill',
                'Vendor': 'vendor',
                'Class': 'class_',
                'Account': 'account',
                'Memo': 'memo',
                'Buyer': 'buyer',
                'Filename': 'filename',
                'Sheet Name': 'sheet_name',
                'MPI Item Code': 'mpi_item',
                'MPI Description': 'mpi_description',
                'Date Added': 'date_added'
            }

            selected_columns = []
            column_names = []
            for col in columns:
                db_col = column_mapping.get(col, col.lower().replace(' ', '_'))
                if db_col in available_columns:
                    selected_columns.append(available_columns[db_col])
                    column_names.append(db_col)
        else:
            # Default columns for export - match the original convert_items_to_dataframe output
            default_cols = ['item', 'description', 'qty', 'cost', 'amount', 'date',
                            'ref_no', 'po_number', 'customer_job', 'bill', 'vendor', 'class_', 'account', 'memo',
                            'buyer', 'filename', 'sheet_name', 'mpi_item', 'mpi_description', 'date_added']
            selected_columns = [available_columns[col] for col in default_cols]
            column_names = default_cols

        # Always include vendor for suffix calculation
        if 'vendor' not in column_names:
            selected_columns.append(InvoiceItem.vendor)
            column_names.append('vendor')

        # Build and execute query
        query = self.db.query(
            *selected_columns).filter(InvoiceItem.id.in_(ids))

        # Apply ordering if provided
        if order_by:
            for order_filter in order_by:
                if order_filter.column in available_columns:
                    column = available_columns[order_filter.column]
                    if order_filter.order == "asc":
                        query = query.order_by(column.asc())
                    elif order_filter.order == "desc":
                        query = query.order_by(column.desc())

        return query.all(), column_names

    def set_export_status_to_sent(self, ids):
        """
        Updates the export_status of the InvoiceItems with the given IDs to 'Sent'.
        Optimized for large batches by processing in chunks.

        Args:
            ids (list): A list of InvoiceItem IDs to update.

        Returns:
            int: The number of records updated.
        """
        if not ids:
            logger.warning('Invoice Item Row IDs not provided')
            return 0

        # Process in batches to avoid memory issues and improve performance
        batch_size = 1000
        total_updated = 0

        try:
            # Process IDs in batches
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i+batch_size]
                logger.debug(
                    f"Processing batch {i//batch_size + 1} with {len(batch_ids)} items")

                # Use direct SQL for better performance with large batches
                query = self.db.query(InvoiceItem).filter(
                    InvoiceItem.id.in_(batch_ids))
                updated_count = query.update(
                    {"export_status": "Sent"}, synchronize_session='fetch')
                total_updated += updated_count

                # Commit after each batch to avoid large transactions
                self.db.commit()

            logger.info(
                f"Updated export status for {total_updated} invoice items")
            return total_updated

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating export status: {str(e)}")
            raise

    def is_exported(self, invoice_id):
        """
        Checks if all invoice items for the given invoice_id have export_status as 'Sent'.
        Optimized to use a count query instead of loading all items into memory.

        Args:
            invoice_id (str): The ID of the invoice to check.

        Returns:
            bool: True if all items are 'Sent', False if any item is 'Pending'.
        """
        try:
            # Count total items for this invoice
            total_count = self.db.query(func.count(InvoiceItem.id))\
                .filter(InvoiceItem.invoice_id == invoice_id)\
                .scalar()

            if total_count == 0:
                return False

            # Count items with 'Sent' status
            sent_count = self.db.query(func.count(InvoiceItem.id))\
                .filter(InvoiceItem.invoice_id == invoice_id)\
                .filter(InvoiceItem.export_status == "Sent")\
                .scalar()

            # All items are exported if counts match
            return sent_count == total_count

        except Exception as e:
            logger.error(
                f"Error checking export status for invoice {invoice_id}: {str(e)}")
            return False

    def delete_invoice_items(self, invoice_id, db):
        items = db.query(InvoiceItem).filter_by(invoice_id=invoice_id).all()
        for item in items:
            db.delete(item)
        db.commit()

    def toggle_visibility(self, ids: List[int], make_visible: bool) -> int:
        """Update visibility for given invoice items."""
        try:
            updated_count = self.db.query(InvoiceItem).filter(
                InvoiceItem.id.in_(ids)
            ).update({InvoiceItem.is_active: make_visible}, synchronize_session=False)

            self.db.commit()
            return updated_count
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    def get_hidden_items(self):
        """Fetch all hidden invoice items."""
        try:
            items = self.db.query(InvoiceItem).execution_options(include_all=True) \
                .filter(InvoiceItem.is_active.is_(False)) \
                .all()
            hidden_items = [item for item in items if not item.is_active]
            invoices_items = []
            for item in hidden_items:
                item_dict = item.__dict__.copy()
                # Use the full item code as stored in database
                item_dict['item'] = item.item
                # Format cost and amount with commas for better readability
                if 'cost' in item_dict and item_dict['cost'] is not None:
                    item_dict['cost'] = format_currency(item_dict['cost'])
                if 'amount' in item_dict and item_dict['amount'] is not None:
                    item_dict['amount'] = format_currency(item_dict['amount'])
                invoices_items.append(InvoiceItemsResponse(**item_dict))
            return invoices_items
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def update_invoice_items(self, items: List[Dict], background_tasks: BackgroundTasks):
        for item_data in items:
            item_id = item_data.get('id')
            if not item_id:
                raise HTTPException(
                    status_code=400, detail="ID is required for updating invoice item")

            item = self.db.query(InvoiceItem).filter(
                InvoiceItem.id == item_id).first()
            if not item:
                raise HTTPException(
                    status_code=404, detail=f"Invoice item with ID {item_id} not found")

            # Get the new MPI item value, defaulting to current value if not in request
            new_mpi_item = item_data.get('mpi_item', item.mpi_item)

            # Disallow updating mpi_item to empty/whitespace or None if it was previously non-empty
            if 'mpi_item' in item_data:
                incoming_mpi_item = item_data.get('mpi_item')
                was_non_empty = bool(item.mpi_item) and str(item.mpi_item).strip() != ""
                becomes_empty = (incoming_mpi_item is None) or (
                    isinstance(incoming_mpi_item, str) and incoming_mpi_item.strip() == ""
                )
                if was_non_empty and becomes_empty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot set mpi_item to empty for invoice item ID {item_id}")

            # Check if it's a valid MPI item (not "No Match" and not starting with "UIDI")
            is_valid_mpi = (new_mpi_item and
                            new_mpi_item.lower() != "no match" and
                            not new_mpi_item.startswith("UIDI"))

            # Get sheet_name from request, defaulting to current value if not provided
            new_sheet_name = item_data.get('sheet_name', item.sheet_name)

            # Only validate sheet_name for valid MPI items
            if is_valid_mpi and not new_sheet_name and new_mpi_item != item.mpi_item:
                # Debug logging to see what's causing the issue
                logger.error(
                    f"Validation failed: mpi_item={new_mpi_item}, sheet_name={new_sheet_name}, data={item_data}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Sheet name is required when updating to a valid MPI item '{new_mpi_item}'. Please provide a sheet name for item {item_data.get('item')}."
                )

            # Rest of the method remains the same
            # Process MPI item updates if changed
            if 'mpi_item' in item_data and item_data['mpi_item'] != item.mpi_item:
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'mpi_item',
                                          item_data['mpi_item'])

            # Process MPI description updates if changed
            if 'mpi_description' in item_data and item_data['mpi_description'] != item.mpi_description:
                # Do NOT change mpi_description when mpi_item is No Match or UIDI
                effective_mpi_item = new_mpi_item if 'mpi_item' in item_data else item.mpi_item
                if not effective_mpi_item or effective_mpi_item == 'No Match' or str(effective_mpi_item).upper().startswith('UIDI'):
                    logger.debug(
                        f"Skipping mpi_description update for item {item.id} because mpi_item is '{effective_mpi_item}'")
                else:
                    background_tasks.add_task(
                        self.update_mpi_field,
                        item_data['item'],
                        'mpi_description',
                        item_data['mpi_description']
                    )

            # Process sheet_name updates if changed
            if 'sheet_name' in item_data and item_data['sheet_name'] != item.sheet_name:
                background_tasks.add_task(self.update_mpi_field, item_data['item'], 'sheet_name',
                                          item_data['sheet_name'])

            # Update mappings table with all the data
            if ('mpi_item' in item_data and item_data['mpi_item'] != item.mpi_item) or \
               ('sheet_name' in item_data and item_data['sheet_name'] != item.sheet_name):
                # Ensure item_data has the sheet_name from either the request or the current item
                if 'sheet_name' not in item_data:
                    item_data['sheet_name'] = item.sheet_name

                background_tasks.add_task(
                    self.update_mappings_table, item_data)

            # Process customer job updates
            if 'customer_job' in item_data and item_data['customer_job'] != item.customer_job:
                background_tasks.add_task(self.update_customer_job, item.customer_job, 'customer_job',
                                          item_data['customer_job'])
                CustomerJobMappingController(self.db).update_mappings_table(
                    old_customer_job=item.customer_job,
                    new_customer_job=item_data['customer_job']
                )

            # Update the item with all provided fields
            for key, value in item_data.items():
                if hasattr(item, key):  # Only update fields that exist on the model
                    # Parse numeric fields to handle comma-separated values
                    if key in ['cost']:  # cost is double precision in database
                        parsed_value = self._parse_numeric_value(value)
                        setattr(item, key, parsed_value)
                    elif key in ['amount']:  # amount is string but parse for consistency
                        # Parse and format amount consistently (remove commas, currency symbols)
                        parsed_value = self._parse_amount_value(value)
                        setattr(item, key, parsed_value)
                    else:
                        setattr(item, key, value)

            self.db.add(item)
        self.db.commit()

    def _parse_numeric_value(self, value):
        """
        Parse a numeric value, removing commas and converting to float.
        Used for database storage where numeric values are expected.
        
        Args:
            value: The value to parse (can be string with commas, number, or None)
            
        Returns:
            Parsed float value or None if parsing fails
        """
        return parse_number(value)

    def _parse_amount_value(self, value):
        """
        Parse an amount value, removing commas and currency symbols but keeping as string.
        Used for amount field which is stored as string in database.
        
        Args:
            value: The value to parse (can be string with commas, currency symbols, or None)
            
        Returns:
            Cleaned string value or None if parsing fails
        """
        if value is None:
            return None
        
        try:
            if isinstance(value, str):
                # Remove commas, currency symbols, and extra whitespace
                cleaned_value = value.replace(',', '').replace('$', '').replace('£', '') \
                                   .replace('€', '').strip()
                # Try to convert to float to validate it's a number, then back to string
                float(cleaned_value)
                return cleaned_value
            else:
                # Convert number to string
                return str(value)
        except (ValueError, TypeError):
            # If it's not a valid number, return the original value
            return str(value) if value is not None else None

    def update_mpi_field(self, item_value: str, field_name: str, new_value: str):
        # If updating mpi_description, enforce that we never change it for No Match or UIDI items
        if field_name == 'mpi_description':
            (self.db.query(InvoiceItem)
             .filter(InvoiceItem.item == item_value)
             .filter(InvoiceItem.mpi_item != 'No Match')
             .filter(~InvoiceItem.mpi_item.ilike('UIDI%'))
             .update({InvoiceItem.mpi_description: new_value}, synchronize_session=False))
            self.db.commit()
            return

        self.db.query(InvoiceItem).filter(InvoiceItem.item == item_value).update({field_name: new_value})
        self.db.commit()

    def update_customer_job(self, item_value: str, field_name: str, new_value: str):
        self.db.query(InvoiceItem).filter(InvoiceItem.customer_job == item_value).update(
            {field_name: new_value})
        self.db.commit()

    def update_mappings_table(self, updated_values: dict):
        try:
            supplier_id, _ = extract_supplier_id(
                updated_values.get('vendor', ''))

            # Get the MPI item code
            mpi_item = updated_values.get('mpi_item', '')

            # Check if it's a valid MPI item
            is_valid_mpi = (mpi_item and
                            mpi_item.lower() != "no match" and
                            not mpi_item.startswith("UIDI"))

            # For valid MPI items, ensure sheet_name is provided
            if is_valid_mpi and not updated_values.get('sheet_name'):
                logger.error(
                    f"Cannot update mapping - sheet_name missing for valid MPI item: {updated_values}")
                return  # Skip the mapping update

            # Create mapping data with all available fields
            mapping_data = {
                "supplier_item_ids": updated_values.get('item', ''),
                "description": updated_values.get('mpi_description', ''),
                "mpi_code": updated_values.get('mpi_item', ''),
                "google_sheet_name": updated_values.get('sheet_name', '')
            }

            # Log what we're about to do
            logger.info(f"Updating mapping with data: {mapping_data}")

            # Only update the mapping if we have a supplier_id and supplier_item_ids
            if supplier_id is not None and mapping_data["supplier_item_ids"]:
                # Lazy import to avoid circular imports
                from mpi_backend.database.controllers.ItemsMappingController import ItemsMappingController
                ItemsMappingController(self.db).update_mapping(
                    supplier_id, mapping_data)
            else:
                logger.error(
                    f"Missing required data for mapping update: supplier_id={supplier_id}, item={mapping_data['supplier_item_ids']}")

        except Exception as e:
            # Log any errors that occur
            logger.error(f"Error in update_mappings_table: {str(e)}")

    def sort(self, db, column, sort_order):
        if sort_order == 'ascending':
            order = asc(column)
        elif sort_order == 'descending':
            order = desc(column)
        else:
            raise HTTPException(status_code=400, detail="Invalid sort order")

        invoice_items = self.db.query(InvoiceItem).order_by(order).all()
        invoices_items = []
        for item in invoice_items:
            item_dict = item.__dict__.copy()
            # Use the full item code as stored in database
            item_dict['item'] = item.item
            # Format cost and amount with commas for better readability
            if 'cost' in item_dict and item_dict['cost'] is not None:
                item_dict['cost'] = format_currency(item_dict['cost'])
            if 'amount' in item_dict and item_dict['amount'] is not None:
                item_dict['amount'] = format_currency(item_dict['amount'])
            invoices_items.append(InvoiceItemsResponse(**item_dict))
        return invoices_items

    def get_customer_jobs(self, db):
        customer_jobs = db.query(InvoiceItem.customer_job).distinct().all()
        return customer_jobs

    @lru_cache(maxsize=128)
    def _get_cached_distinct_values(self, column_name: str, filter_context_hash: str, comparison_filters_hash: str):
        """
        Cached version of distinct value fetching for better performance.
        Uses hashed filter context to enable caching while maintaining filter functionality.
        """
        # Parse the hashes back to original data (in production, you might want a more sophisticated cache)
        # For now, we'll implement the core optimization without relying on the hash parsing
        return self._get_distinct_values_ultra_optimized(column_name, filter_context_hash)

    def _create_filter_hash(self, filter_context: Dict, comparison_filters: List) -> tuple:
        """Create a hash from filter context and comparison filters for caching."""
        filter_str = json.dumps(filter_context or {}, sort_keys=True)
        comparison_str = json.dumps([
            {k: v for k, v in f.items() if k in [
                'column', 'operator', 'value']}
            for f in (comparison_filters or [])
        ], sort_keys=True)

        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()
        comparison_hash = hashlib.md5(comparison_str.encode()).hexdigest()
        return filter_hash, comparison_hash

    def _get_distinct_values_optimized(self, column_name: str, filter_context: Dict, comparison_filters: List):
        """
        Optimized version of distinct value fetching with better query performance.
        """
        start_time = time.time()

        # Special handling for 'item' column to return suffixed values efficiently
        if column_name == "item":
            # Use a more efficient query that only selects needed columns
            query = self.db.query(InvoiceItem.item, InvoiceItem.vendor)

            # Apply filters more efficiently
            query = self._apply_comparison_filters_optimized(
                query, comparison_filters)
            query = self._apply_context_filters_optimized(
                query, filter_context)

            # Execute query and process results in batches to reduce memory usage
            batch_size = 5000
            all_suffixed_items = set()
            offset = 0

            while True:
                batch_query = query.limit(batch_size).offset(offset)
                batch_results = batch_query.all()

                if not batch_results:
                    break

                # Process batch to get items (with suffix standardization, use items as-is)
                for item, vendor in batch_results:
                    if item:
                        # With suffix standardization, use the item as stored in database
                        all_suffixed_items.add(item)

                offset += batch_size

                # Break if we got fewer results than batch size (last batch)
                if len(batch_results) < batch_size:
                    break

            result = sorted(list(all_suffixed_items))
            logging.info(
                f"Item column distinct values query took {time.time() - start_time:.2f}s, returned {len(result)} items")
            return result

        # Optimized query for other columns
        column_attr = getattr(InvoiceItem, column_name)

        # Use a more efficient distinct query with only the required column
        query = self.db.query(column_attr).distinct()

        # Apply filters efficiently
        query = self._apply_comparison_filters_optimized(
            query, comparison_filters)
        query = self._apply_context_filters_optimized(query, filter_context)

        # Use database-level ordering for better performance
        query = query.order_by(column_attr.asc())

        # Execute query
        distinct_values = query.all()
        result = [value[0]
                  for value in distinct_values if value[0] is not None]

        logging.info(
            f"Column '{column_name}' distinct values query took {time.time() - start_time:.2f}s, returned {len(result)} values")
        return result

    def _apply_comparison_filters_optimized(self, query, comparison_filters: List):
        """
        Optimized version of comparison filter application.
        """
        if not comparison_filters:
            return query

        for comp_filter in comparison_filters:
            if not hasattr(InvoiceItem, comp_filter['column']):
                continue  # Skip invalid columns instead of raising exception for better performance

            column = getattr(InvoiceItem, comp_filter['column'])

            # Special handling for 'amount' column (string to float conversion with comma removal)
            if comp_filter['column'] == "amount":
                column = self._safe_numeric_cast(column)

            # Handle type casting for comparison filters with better error handling
            try:
                value = self._convert_filter_value(comp_filter, column)
                query = self._apply_operator_filter(
                    query, column, comp_filter['operator'], value)
            except (ValueError, TypeError):
                continue  # Skip invalid values instead of raising exception

        return query

    def _apply_context_filters_optimized(self, query, filter_context: Dict):
        """
        Optimized version of context filter application with date range support.
        """
        if not filter_context:
            return query

        for filter_col_name, values in filter_context.items():
            if not hasattr(InvoiceItem, filter_col_name):
                continue  # Skip invalid columns

            filter_column = getattr(InvoiceItem, filter_col_name)

            # Special handling for date range filters
            if filter_col_name == "date" and isinstance(values, list) and len(values) == 2:
                try:
                    start_date = values[0]
                    end_date = values[1]
                    
                    # Convert string dates to date objects if needed
                    if isinstance(start_date, str):
                        start_date = date.fromisoformat(start_date)
                    if isinstance(end_date, str):
                        end_date = date.fromisoformat(end_date)
                    
                    # Apply date range filter
                    query = query.filter(
                        and_(
                            filter_column >= start_date,
                            filter_column <= end_date
                        )
                    )
                    continue
                except (ValueError, TypeError):
                    # If date parsing fails, fall back to regular filtering
                    pass

            # Strip spaces from filter values for consistent comparison
            cleaned_values = []
            for value in values:
                if isinstance(value, str):
                    cleaned_values.append(value.strip())
                else:
                    cleaned_values.append(value)

            # For string columns, use case-insensitive and trimmed comparison
            if filter_col_name in ['ref_no', 'vendor', 'item', 'description',
                                   'customer_job', 'po_number', 'bill', 'buyer',
                                   'memo', 'class_']:
                # Use func.trim() and ilike for case-insensitive, trimmed comparison
                conditions = []
                for cleaned_value in cleaned_values:
                    if isinstance(cleaned_value, str):
                        # Trim both database value and filter value, then do case-insensitive comparison
                        conditions.append(func.trim(filter_column).ilike(
                            func.trim(cleaned_value)))
                    else:
                        conditions.append(filter_column == cleaned_value)
                if conditions:
                    # Use more efficient batch processing for large value lists
                    if len(conditions) > 1000:
                        # Split into smaller batches to avoid SQL query limits
                        batch_conditions = []
                        batch_size = 1000
                        for i in range(0, len(conditions), batch_size):
                            batch_conditions.append(
                                or_(*conditions[i:i + batch_size]))
                        query = query.filter(or_(*batch_conditions))
                    else:
                        query = query.filter(or_(*conditions))
            else:
                # For non-string columns, use exact match
                # Use more efficient IN clause with batch processing for large value lists
                if len(cleaned_values) > 1000:  # For very large filter lists, use batch processing
                    # Split into smaller batches to avoid SQL query limits
                    batch_conditions = []
                    batch_size = 1000
                    for i in range(0, len(cleaned_values), batch_size):
                        batch_values = cleaned_values[i:i + batch_size]
                        batch_conditions.append(
                            filter_column.in_(batch_values))
                    query = query.filter(or_(*batch_conditions))
                else:
                    query = query.filter(filter_column.in_(cleaned_values))

        return query

    def _convert_filter_value(self, comp_filter: Dict, column):
        """
        Optimized value conversion with better error handling.
        """
        if comp_filter['column'] == "amount":
            # Remove thousand separators before casting to float
            return float(str(comp_filter['value']).replace(',', ''))
        elif hasattr(column.type, 'python_type'):
            if column.type.python_type == int:
                return int(comp_filter['value'])
            elif column.type.python_type == float:
                return float(comp_filter['value'])
            elif column.type.python_type == date:
                # Accept ISO date or ISO datetime; use the date portion
                raw = comp_filter['value']
                if isinstance(raw, date):
                    return raw
                if isinstance(raw, str):
                    try:
                        # Support 'YYYY-MM-DD' and 'YYYY-MM-DDTHH:MM:SS'
                        return date.fromisoformat(raw[:10])
                    except Exception:
                        # As a fallback, try parsing common formats MM/DD/YYYY
                        try:
                            return datetime.strptime(raw, "%m/%d/%Y").date()
                        except Exception:
                            pass
                return raw
        return comp_filter['value']

    def _apply_operator_filter(self, query, column, operator: str, value):
        """
        Optimized operator filter application.
        """
        op = (operator or '').strip().lower()
        operator_map = {
            "gt": column > value,
            "lt": column < value,
            "gte": column >= value,
            "lte": column <= value,
            "eq": column == value
        }

        if op in operator_map:
            return query.filter(operator_map[op])
        return query

    def get_price_history(self, request: 'PriceHistoryRequest') -> List['PriceHistoryResponse']:
        """
        Get price history for a specific item and vendor with price comparison.
        
        The 'cost' field is the unit price, and is compared directly between purchases
        to determine if there was a price increase (chronologically).

        Args:
            request (PriceHistoryRequest): Request containing item_number, vendor, 
                and description for price history lookup.

        Returns:
            List[PriceHistoryResponse]: Price history records sorted by date (newest first),
                each with an 'is_price_increase' flag indicating if the unit price increased
                compared to the chronologically previous purchase.
        """
        try:
            # Resolve which item field to search on
            # item_number takes priority; fall back to mpi_item
            if request.item_number and request.item_number.strip():
                item_search_value = request.item_number.strip()
                item_column = InvoiceItemMart.item
                logger.info(f"Getting price history by item_number: {item_search_value}, "
                            f"vendor: {request.vendor}")
            else:
                item_search_value = request.mpi_item.strip()
                item_column = InvoiceItemMart.mpi_item
                logger.info(f"Getting price history by mpi_item: {item_search_value}, "
                            f"vendor: {request.vendor}")

            original_vendor = request.vendor.strip()

            # Build query using InvoiceItemMart (mart table has filename directly)
            query = self.db.query(InvoiceItemMart).options(
                load_only(
                    InvoiceItemMart.id,
                    InvoiceItemMart.ref_no,
                    InvoiceItemMart.date,
                    InvoiceItemMart.rerated_cost,
                    InvoiceItemMart.cost,
                    InvoiceItemMart.qty,
                    InvoiceItemMart.rerated_qty,
                    InvoiceItemMart.is_price_rerated,
                    InvoiceItemMart.amount,
                    InvoiceItemMart.invoice_id,
                    InvoiceItemMart.memo,
                    InvoiceItemMart.filename,
                    InvoiceItemMart.item,
                    InvoiceItemMart.description,
                    InvoiceItemMart.mpi_item,
                    InvoiceItemMart.vendor
                )
            )

            # Apply item filter on correct column
            query = query.filter(item_column == item_search_value)

            # Vendor filtering — skip entirely when "all"
            if original_vendor.lower() != "all":
                query = query.filter(InvoiceItemMart.vendor == original_vendor)

            # Date range filters. Default: filter by invoice date (m.date).
            # When filter_by_date_added is set, filter by COALESCE(date_added::date,
            # m.date) instead, so the Mappings page's "Date History" (a date_added
            # filter) stays consistent with the invoices shown in the Price History /
            # "Invoices for Item" modal. date_added is timestamptz (UTC) in the DB,
            # so we convert it to a calendar date in America/New_York (the business
            # timezone) for day-level comparison; otherwise a row recorded at e.g.
            # 2026-04-28 00:19 UTC (= 2026-04-27 20:19 ET) would land on the wrong
            # day relative to what the user picked. Legacy rows with NULL
            # date_added fall back to invoice date — same behaviour as the DAO's
            # date_history filter (see get_unmapped_items.py).
            if request.filter_by_date_added:
                date_col = func.coalesce(
                    cast(
                        func.timezone("America/New_York", InvoiceItemMart.date_added),
                        Date,
                    ),
                    InvoiceItemMart.date,
                )
            else:
                date_col = InvoiceItemMart.date
            if request.from_date:
                query = query.filter(date_col >= request.from_date)
            if request.to_date:
                query = query.filter(date_col <= request.to_date)

            # Filter out empty items/vendors
            query = query.filter(item_column != "")

            # Filter out invalid costs if requested (default behavior)
            if request.filter_zero_cost:
                query = query.filter(InvoiceItemMart.rerated_cost > 0)

            # Order by date descending (newest first)
            query = query.order_by(InvoiceItemMart.date.desc())

            matched_items = query.all()

            logger.info(f"Found {len(matched_items)} price history records")

            if not matched_items:
                logger.warning(
                    f"No price history found for item: {item_search_value}, vendor: {request.vendor}"
                )

                # Additional debugging - try to find similar items using the same column that was queried
                debug_query = self.db.query(
                    item_column,
                    InvoiceItemMart.vendor,
                    func.count().label('count')
                ).filter(
                    or_(
                        item_column.ilike(f"%{item_search_value}%"),
                        InvoiceItemMart.vendor.ilike(f"%{original_vendor}%")
                    )
                ).group_by(item_column, InvoiceItemMart.vendor).limit(5).all()

                logger.info(
                    f"Similar items found in database: "
                    f"{[(item, vendor, count) for item, vendor, count in debug_query]}"
                )
                return []

            # Sort items by date (newest first) for display
            # Handle None dates by putting them at the end
            def get_sort_key(item: InvoiceItemMart) -> date:
                """
                Generate sort key for invoice items based on date.

                Returns a far past date (1900-01-01) for items with None dates so they
                appear at the end when sorting in reverse (newest first).

                Args:
                    item (InvoiceItemMart): Invoice item mart to extract sort key from

                Returns:
                    date: Item's date if present, otherwise date(1900, 1, 1)
                """
                if item.date is None:
                    # Use a far past date for None values to sort them last when reversed
                    return datetime(1900, 1, 1).date()
                return item.date
            
            matched_items_sorted = sorted(matched_items, key=get_sort_key, reverse=True)
            
            # First pass: create all records
            records_with_costs = []
            
            for item in matched_items_sorted:
                try:
                    # Validate ref_no (we'll allow missing dates now)
                    if not item.ref_no:
                        logger.warning(f"Skipping item with missing ref_no: {item.id}")
                        continue

                    # Cost is already the unit price, no need to divide by quantity
                    rerated_cost = float(item.rerated_cost) if item.rerated_cost else 0.0
                    
                    # Format date, handling None values
                    if item.date:
                        formatted_date = item.date.strftime("%m-%d-%Y")
                    else:
                        formatted_date = "Invalid date"
                        logger.warning(f"Item {item.id} has no date, using 'Invalid date'")
                    
                    records_with_costs.append({
                        'id': item.id,
                        'ref_no': item.ref_no,
                        'date': formatted_date,
                        'item_code': item.item if item.item else "",
                        'item_description': item.description if item.description else "",
                        'cost': format_currency(item.rerated_cost) if item.rerated_cost else format_currency(0.0),
                        'original_cost': format_currency(item.cost) if item.cost else format_currency(0.0),
                        'original_quantity': float(item.qty) if item.qty else 0,
                        'qty': float(item.rerated_qty) if item.rerated_qty else 0,
                        'amount': format_currency(item.amount) if item.amount else format_currency(0.0),
                        'invoice_id': str(item.invoice_id) if item.invoice_id else "",
                        'price': rerated_cost,  # Cost is the unit price
                        'memo': item.memo if item.memo else "",
                        'vendor': item.vendor if item.vendor else "",
                        'filename': item.filename if item.filename else "",
                        'is_price_rerated': item.is_price_rerated,
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing price history item {item.id}: {str(e)}")
                    continue
            
            # Second pass: compare each entry with the chronologically PREVIOUS purchase
            # (the next entry in the list since we're sorted newest first)
            response = []
            for i, record in enumerate(records_with_costs):
                is_price_increase = None
                
                # Compare with the next entry (chronologically older purchase)
                # Cost is already the unit price, compare directly
                if i + 1 < len(records_with_costs):
                    previous_price = records_with_costs[i + 1]['price']
                    is_price_increase = record['price'] > previous_price
                
                price_record = PriceHistoryResponse(
                    id=record['id'],
                    ref_no=record['ref_no'],
                    date=record['date'],
                    item_code=record['item_code'],
                    item_description=record['item_description'],
                    cost=record['cost'],
                    original_cost=record['original_cost'],
                    qty=record['qty'],
                    original_quantity=record['original_quantity'],
                    amount=record['amount'],
                    invoice_id=record['invoice_id'],
                    is_price_increase=is_price_increase,
                    memo=record['memo'],
                    vendor=record['vendor'],
                    filename=record['filename'],
                    is_price_rerated=record['is_price_rerated']
                )
                response.append(price_record)

            logger.info(f"Successfully processed {len(response)} "
                        f"price history records")
            return response

        except Exception as e:
            logger.error(f"Error in get_price_history: {str(e)}")
            # Return empty list instead of raising exception
            return []

    def get_aggregates(self, request: FilterRequest):
        """
        Returns the aggregates (quantity, average, total) for the current filtered items

        TODO: Have a class for the return value (add typing hint)
        """
        start_time = time.time()
        cleaned_request = self._validate_filter_request(request)
        try:
            dao_result = invoice_item_mart.get_aggregates(db=self.db, request=cleaned_request)

            dao_formatted = {
                "total_qty": float(dao_result.total_qty) if dao_result.total_qty is not None else 0,
                "total_amount": format_currency(dao_result.total_amount) if dao_result.total_amount is not None else format_currency(0.0),
                "average_cost": format_currency(dao_result.average_cost) if dao_result.average_cost is not None else format_currency(0.0)
            }

            execution_time = time.time() - start_time
            execution_time = time.time() - execution_time
            logger.info(f"Execution time: {execution_time:.3f}s. Returned {dao_formatted}")
            return dao_result
        except ValueError:
            logger.error("Error while calculating averages")
            return {
                "total_qty": 0,
                "total_amount": format_currency(0.0),
                "average_cost": format_currency(0.0),
            }


    def _format_category(self, category_info: dict) -> dict:
        """Format a single category with currency values and difference handling."""
        difference = category_info["difference_from_average"]
        difference_str = format_currency(abs(difference))
        if difference < 0:
            difference_str = f"-{difference_str}"

        return {
            "sheet_name": category_info["sheet_name"],
            "total_amount": format_currency(category_info["total_amount"]),
            "category_average": format_currency(category_info["category_average"]),
            "difference_from_average": difference_str,
            "percentage_difference": category_info["percentage_difference"]
        }

    def _format_address_data(self, data: dict) -> dict:
        """Format nested address data structure with currency values."""
        formatted = {}
        for addr, address_info in data.items():
            formatted[addr] = {
                "address": address_info["address"],
                "address_total": format_currency(address_info["address_total"]),
                "categories": {
                    sheet_name: self._format_category(category_info)
                    for sheet_name, category_info in address_info["categories"].items()
                }
            }
        return formatted


    def _format_aggregate_result(self, dao_result: DaoAggregateResult) -> Dict:
        """Format DAO aggregate result into the format expected by the frontend"""
        formatted_category_averages = {
            k: format_currency(v) for k, v in dao_result.category_averages.items()
        }
        formatted_category_totals = {
            k: format_currency(v) for k, v in dao_result.category_totals.items()
        }

        result = {
            "category_averages": formatted_category_averages,
            "category_totals": formatted_category_totals,
            "grand_total": format_currency(dao_result.grand_total)
        }

        if dao_result.data:
            result["data"] = self._format_address_data(dao_result.data)

        return result

    def get_aggregates_by_address_and_sheet(self, address: Optional[str] = None):
        """
        Get aggregated costs grouped by customer_job (address) and sheet_name category.

        - Calls address-sheet aggregate table
        - TODO: Validate that the address exists

        Args:
            request: FilterRequest with optional filters (date ranges, vendors, etc.)
            address: Optional customer_job address to filter by.

        Returns:
            When address is None: the category averages, category totals, and grand total
            When address is provided: The above AND the provided address':
                - sheet name
                - total amount
                - category average
                - difference from average
                - percentage difference
            }
        """
        try:
            # Try optimized mart table first
            dao_result = analysis_page_dao.get_aggregates_by_address_and_sheet(db=self.db, address=address)

            if dao_result is None:
                raise ValueError(f"Expected DAO to return something, instead it returned None: {dao_result}")

            # DAO succeeded - format currency values and return
            logger.info(f"Using optimized mart for aggregates by address+sheet (source: {dao_result.source})")
            return self._format_aggregate_result(dao_result)

        except Exception as e:
            # Log detailed error internally
            logger.error(f"Error calculating aggregates: {e}", exc_info=True)
            raise # re-raise the exception to pass it up

    def get_monthly_aggregates(self, month, year, status_filters=None):
        """
        Get aggregated statistics for a specific month and year.
        
        Args:
            month: Month (1-12)
            year: Year (e.g., 2024)
            status_filters: List of statuses to include (processed, failed, unlisted, missing)
            
        Returns:
            Dict containing monthly aggregates
        """
        from sqlalchemy import func, extract, case, and_, or_
        import math
        
        if status_filters is None:
            status_filters = ["processed", "failed", "unlisted", "missing"]
        
        # Build base query with month/year filter
        query = self.db.query(InvoiceItem).filter(
            and_(
                InvoiceItem.is_active.is_(True),
                extract('month', InvoiceItem.date) == month,
                extract('year', InvoiceItem.date) == year
            )
        )
        
        # Apply status filters based on invoice status
        if status_filters:
            status_conditions = []
            for status in status_filters:
                if status == "processed":
                    status_conditions.append(Invoice.status == "processed")
                elif status == "failed":
                    status_conditions.append(Invoice.status == "failed")
                elif status == "unlisted":
                    status_conditions.append(Invoice.status == "unlisted")
                elif status == "missing":
                    status_conditions.append(Invoice.status == "missing")
            
            if status_conditions:
                query = query.join(Invoice).filter(or_(*status_conditions))
        
        # Calculate amount with proper validation (same as get_aggregates)
        calculated_amount_case = case(
            (
                and_(
                    InvoiceItem.amount.isnot(None),
                    InvoiceItem.amount != '',
                    func.length(InvoiceItem.amount) < 100,
                    func.length(InvoiceItem.amount) > 0,
                    ~InvoiceItem.amount.like('%Merchandise%'),
                    ~InvoiceItem.amount.like('%Freight%'),
                    ~InvoiceItem.amount.like('%MiscCharges%'),
                    ~InvoiceItem.amount.like('%SubTotal%'),
                    ~InvoiceItem.amount.like('%Taxable%'),
                    ~InvoiceItem.amount.like('%Tax(%'),
                    ~InvoiceItem.amount.like('%Tax)%'),
                    func.replace(InvoiceItem.amount, ',', '').regexp_match(
                        '^-?[0-9]*\.?[0-9]+$')
                ),
                cast(func.replace(InvoiceItem.amount, ',', ''), Float)
            ),
            else_=0.0
        )
        
        # Execute query with aggregation
        try:
            aggregates = query.with_entities(
                func.sum(InvoiceItem.qty).label('total_qty'),
                func.sum(calculated_amount_case).label('total_amount'),
                func.avg(InvoiceItem.cost).label('average_cost'),
                func.count(InvoiceItem.id).label('item_count'),
                func.count(func.distinct(InvoiceItem.invoice_id)).label('invoice_count'),
                func.count(func.distinct(InvoiceItem.vendor)).label('supplier_count')
            ).first()
        except Exception as e:
            logger.error(f"Database error in get_monthly_aggregates: {str(e)}")
            return {
                "total_qty": 0,
                "total_amount": 0.0,
                "average_cost": 0.0,
                "item_count": 0,
                "invoice_count": 0,
                "supplier_count": 0,
                "month": month,
                "year": year,
                "status_filters": status_filters
            }
        
        # Handle null values and type conversion
        total_qty = 0 if aggregates.total_qty is None else float(aggregates.total_qty)
        
        if aggregates.total_amount is None:
            total_amount = 0.0
        else:
            try:
                total_amount = float(aggregates.total_amount)
                if math.isnan(total_amount) or math.isinf(total_amount):
                    total_amount = 0.0
            except (TypeError, ValueError):
                total_amount = 0.0
        
        if aggregates.average_cost is None:
            average_cost = 0.0
        else:
            try:
                average_cost = float(aggregates.average_cost)
            except (TypeError, ValueError):
                average_cost = 0.0
        
        def sanitize_float(value: float) -> float:
            if math.isinf(value) or math.isnan(value):
                return 0.0
            return round(value, 2)
        
        result = {
            "total_qty": total_qty,
            "total_amount": format_currency(sanitize_float(total_amount)),
            "average_cost": format_currency(sanitize_float(average_cost)),
            "item_count": aggregates.item_count or 0,
            "invoice_count": aggregates.invoice_count or 0,
            "supplier_count": aggregates.supplier_count or 0,
            "month": month,
            "year": year,
            "status_filters": status_filters
        }
        
        logger.info(f"Monthly aggregates calculated for {month}/{year} - "
                   f"Qty: {total_qty}, Amount: {result['total_amount']}, "
                   f"Items: {result['item_count']}, Invoices: {result['invoice_count']}")
        
        return result

    def calculate_price_increase(
        self,
        item_numbers: Optional[List[str]] = None,
        item_vendor_pairs: Optional[List[Tuple[str, str, int]]] = None
    ) -> List[Tuple[str, str]]:
        """
        Calculate percentage price increase by comparing current price with previous purchase.
        
        The 'cost' field is the unit price, so we compare it directly without dividing by quantity.
        Uses efficient SQL queries and database-level aggregations for better performance.
        Compares each purchase with the immediately preceding purchase chronologically.

        Performance improvements:
        - Uses SQL window functions for efficient date-based aggregations
        - Processes items in batches to reduce memory usage
        - Eliminates redundant database queries
        - Uses database-level filtering instead of Python loops
        - SUPPLIER-SPECIFIC: Compares prices within the same supplier only

        Args:
            item_numbers (Optional[List[str]]): List of item numbers for backward compatibility.
            item_vendor_pairs (Optional[List[Tuple[str, str, int]]]): List of tuples 
                (item, vendor, item_id) for supplier-specific price comparison.

        Returns:
            List[Tuple[str, str]]: List of tuples with item numbers and their percentage 
                increases (formatted as "X.X%" or "N/A"), preserving original order.
        """
        import time
        start_time = time.time()

        result = []

        if not item_numbers and not item_vendor_pairs:
            return result

        unique_items = []
        if item_numbers:
            unique_items = list(dict.fromkeys(item_numbers))
            logger.info(f"Calculating price increase for {len(unique_items)} unique "
                        f"items (total: {len(item_numbers)})")
        elif item_vendor_pairs:
            logger.info(
                f"Calculating supplier-specific price increase for {len(item_vendor_pairs)} item-vendor pairs")

        try:
            if item_vendor_pairs:
                price_increase_query = text("""
                    WITH unique_item_vendor_pairs AS (
                        SELECT DISTINCT item, vendor FROM (
                            SELECT unnest(:items) as item, unnest(:vendors) as vendor
                        ) as pairs
                    ),
                    item_price_data AS (
                        SELECT 
                            ii.id,
                            ii.item,
                            ii.vendor,
                            ii.date,
                            ii.cost,
                            ii.qty
                        FROM invoice_items ii
                        JOIN unique_item_vendor_pairs uivp ON ii.item = uivp.item AND ii.vendor = uivp.vendor
                        WHERE ii.cost IS NOT NULL 
                        AND ii.cost > 0
                        ORDER BY ii.item, ii.vendor, ii.date ASC
                    ),
                    price_comparison AS (
                        SELECT 
                            ipd.id as item_id,
                            ipd.item,
                            ipd.vendor,
                            ipd.date as item_date,
                            ipd.cost as current_price,
                            LAG(ipd.cost) OVER (PARTITION BY ipd.item, ipd.vendor ORDER BY ipd.date ASC) as previous_price,
                            LAG(ipd.date) OVER (PARTITION BY ipd.item, ipd.vendor ORDER BY ipd.date ASC) as previous_date
                        FROM item_price_data ipd
                    ),
                    requested_items AS (
                        SELECT unnest(:item_ids) as item_id
                    )
                    SELECT 
                        pc.item_id,
                        pc.item,
                        pc.vendor,
                        pc.current_price,
                        pc.previous_price,
                        CASE 
                            WHEN pc.previous_price IS NULL THEN NULL
                            WHEN pc.previous_price = 0 THEN NULL
                            ELSE ROUND(((pc.current_price - pc.previous_price) / pc.previous_price * 100)::numeric, 1)
                        END as percentage_increase
                    FROM price_comparison pc
                    JOIN requested_items ri ON pc.item_id = ri.item_id
                    ORDER BY pc.item_date
                """)

                items_list = [pair[0] for pair in item_vendor_pairs]
                vendors_list = [pair[1] for pair in item_vendor_pairs]
                item_ids_list = [pair[2] if len(pair) > 2 else 0 for pair in item_vendor_pairs]
                query_result = self.db.execute(price_increase_query, {
                    "items": items_list,
                    "vendors": vendors_list,
                    "item_ids": item_ids_list
                }).fetchall()

            else:
                price_increase_query = text("""
                    WITH item_price_data AS (
                        SELECT 
                            ii.item,
                            ii.date,
                            ii.cost
                        FROM invoice_items ii
                        WHERE item = ANY(:items)
                        AND ii.cost IS NOT NULL 
                        AND ii.cost > 0
                        ORDER BY ii.item, ii.date ASC
                    ),
                    price_comparison AS (
                        SELECT 
                            item,
                            cost as current_price,
                            LAG(cost) OVER (PARTITION BY item ORDER BY date ASC) as previous_price
                        FROM item_price_data
                    )
                    SELECT 
                        item,
                        current_price,
                        previous_price,
                        CASE 
                            WHEN previous_price IS NULL THEN NULL
                            WHEN previous_price = 0 THEN NULL
                            ELSE ROUND(((current_price - previous_price) / previous_price * 100)::numeric, 1)
                        END as percentage_increase
                    FROM price_comparison
                """)

                query_result = self.db.execute(
                    price_increase_query, {"items": unique_items}).fetchall()

            price_lookup = {}

            if item_vendor_pairs:
                for row in query_result:
                    item_id, item, vendor, current_price, previous_price, percentage_increase = row

                    if percentage_increase is not None:
                        price_lookup[item_id] = f"{percentage_increase}%"
                    else:
                        price_lookup[item_id] = "N/A"

                for item_vendor_pair in item_vendor_pairs:
                    item_id = item_vendor_pair[2] if len(item_vendor_pair) > 2 else 0
                    percentage_increase = price_lookup.get(item_id, "N/A")
                    result.append((item_vendor_pair[0], percentage_increase))
            else:
                for row in query_result:
                    item, current_price, previous_price, percentage_increase = row

                    if percentage_increase is not None:
                        price_lookup[item] = f"{percentage_increase}%"
                    else:
                        price_lookup[item] = "N/A"

                for item_number in item_numbers:
                    percentage_increase = price_lookup.get(item_number, "N/A")
                    result.append((item_number, percentage_increase))

            processing_time = time.time() - start_time

            if item_vendor_pairs:
                logger.info(
                    f"Price increase calculation completed in {processing_time:.2f}s for {len(item_vendor_pairs)} item-vendor pairs")
            else:
                logger.info(
                    f"Price increase calculation completed in {processing_time:.2f}s for {len(item_numbers or [])} items")

            return result

        except Exception as e:
            logger.error(
                f"Error in optimized price increase calculation: {str(e)}")
            logger.info("Falling back to legacy method...")

            return self._calculate_price_increase_legacy(item_numbers)

    def _calculate_price_increase_legacy(self, item_numbers):
        """
        Legacy implementation as fallback for calculate_price_increase.
        Kept for backward compatibility in case the optimized version fails.
        """
        result = []

        if not item_numbers:
            return result

        base_query = self.db.query(InvoiceItem)
        items_filter = InvoiceItem.item.in_(set(item_numbers))
        all_items = base_query.filter(items_filter).all()

        # Group same item numbers together
        grouped_items = {}
        for item in all_items:
            if item.item not in grouped_items:
                grouped_items[item.item] = []
            grouped_items[item.item].append(item)

        # Process each item number in the original order- to preserve duplicates
        for item_number in item_numbers:
            percentage_increase = "N/A"  # Default value

            if item_number in grouped_items:
                items = grouped_items[item_number]
                if items:
                    # Filter valid items with cost > 0
                    valid_items = [
                        item for item in items if item.cost is not None and item.cost > 0]

                    if len(valid_items) >= 1:
                        # Sort by date to get chronological order
                        valid_items.sort(key=lambda x: x.date)

                        # Find this item's most recent date
                        most_recent_date = valid_items[-1].date

                        # Calculate 1 year back from the most recent date
                        one_year_back = most_recent_date - timedelta(days=365)

                        # Filter items to only include those within the last year
                        items_within_year = [
                            item for item in valid_items if item.date >= one_year_back]

                        if len(items_within_year) >= 1:
                            # Use earliest price within the year as baseline
                            # Earliest in the year window
                            baseline_price = items_within_year[0].cost
                            # Use highest price within the year as peak
                            # Highest in year
                            peak_price = max(
                                item.cost for item in items_within_year)

                            # Calculate percentage increase using baseline vs peak
                            if baseline_price is None or baseline_price == 0:
                                percentage_increase = "∞%"
                            else:
                                percentage_value = (
                                    (peak_price - baseline_price) / baseline_price) * 100

                                # Show percentage increase (can be positive or negative)
                                percentage_increase = f"{round(percentage_value, 1)}%"
                        else:
                            # No items within the year window
                            percentage_increase = "N/A"
                    else:
                        # No valid items with positive cost
                        percentage_increase = "N/A"

            result.append((item_number, percentage_increase))

        return result

    def get_price_increase_details(
        self,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get detailed price increase information for invoice items.
        
        Uses mart__price_increases and mart__invoice_items tables for efficient querying.
        These mart tables contain pre-computed price increase data.
        
        Returns invoice items with positive price differences, including:
        - Invoice item ID
        - Invoice number (ref_no)
        - Item code
        - Current price (cost)
        - Previous price
        - Price difference (current - previous)
        - Percentage increase
        - Quantity
        - Supplier name
        - Invoice date
        
        Args:
            filters: Optional filter dictionary (e.g., date range, supplier)
            
        Returns:
            List of dictionaries with price increase details
        """
        from mpi_backend.database.models.Suppliers import Supplier
        
        try:
            # Build query using mart tables
            # Join mart__price_increases with mart__invoice_items to get item details
            # Use vendor from mart__invoice_items directly (no need to join with Invoice/Supplier)
            try:
                base_query = (
                    self.db.query(
                        PriceIncreaseMart.invoice_items_id,
                        InvoiceItemMart.item,
                        InvoiceItemMart.vendor,
                        InvoiceItemMart.ref_no,
                        PriceIncreaseMart.current_price,
                        PriceIncreaseMart.previous_price,
                        PriceIncreaseMart.percentage_increase,
                        PriceIncreaseMart.price_change,
                        PriceIncreaseMart.current_qty,
                        PriceIncreaseMart.purchase_date
                    )
                    .join(
                        InvoiceItemMart,
                        PriceIncreaseMart.invoice_items_id == InvoiceItemMart.id
                    )
                    .outerjoin(
                        InvoiceVoid,
                        (InvoiceItemMart.ref_no == InvoiceVoid.ref_no) &
                        (InvoiceItemMart.date == InvoiceVoid.date) &
                        (InvoiceItemMart.vendor == InvoiceVoid.vendor)
                    )
                    .filter(
                        InvoiceVoid.ref_no.is_(None),
                        PriceIncreaseMart.percentage_increase.isnot(None),
                        PriceIncreaseMart.percentage_increase > 0,
                        PriceIncreaseMart.has_previous_price == True
                    )
                )
            except Exception as query_build_error:
                logger.error(f"Error building price increase query (mart tables may not exist): {query_build_error}", exc_info=True)
                # Rollback and return empty list
                try:
                    self.db.rollback()
                except Exception as rollback_error:
                    logger.error(f"Error during rollback: {rollback_error}")
                return []
            
            # Apply date filters if provided
            if filters:
                if 'start_date' in filters:
                    start_date = filters['start_date']
                    if isinstance(start_date, str):
                        from datetime import datetime
                        start_date = datetime.fromisoformat(start_date).date()
                    base_query = base_query.filter(PriceIncreaseMart.purchase_date >= start_date)
                
                if 'end_date' in filters:
                    end_date = filters['end_date']
                    if isinstance(end_date, str):
                        from datetime import datetime
                        end_date = datetime.fromisoformat(end_date).date()
                    base_query = base_query.filter(PriceIncreaseMart.purchase_date <= end_date)
            
            # Apply supplier filter directly in query using vendor column
            # This is more efficient and accurate than filtering after the query
            supplier_filters = []
            if filters and 'supplier_names' in filters:
                supplier_filters = filters['supplier_names']
            elif filters and 'supplier_name' in filters:
                supplier_filters = [filters['supplier_name']]
            
            if supplier_filters:
                # Build vendor filter conditions
                vendor_conditions = []
                for supplier_filter in supplier_filters:
                    supplier_lower = supplier_filter.lower().strip()
                    # Try exact match first, then case-insensitive match
                    vendor_conditions.append(func.lower(InvoiceItemMart.vendor) == supplier_lower)
                    # Also try if vendor contains the supplier name (for partial matches)
                    vendor_conditions.append(func.lower(InvoiceItemMart.vendor).contains(supplier_lower))
                
                if vendor_conditions:
                    # Use OR to match any of the supplier filters
                    from sqlalchemy import or_
                    base_query = base_query.filter(or_(*vendor_conditions))
            
            # Execute query
            results = base_query.all()
            
            if not results:
                logger.info("No price increases found with specified filters")
                return []
            
            logger.info(f"Found {len(results)} items with price increases from mart tables")
            
            # Convert to dictionary format matching the expected structure
            result = []
            for row in results:
                # Use vendor as supplier_name (they should match)
                supplier_name = row.vendor
                # Try to get supplier_id from database if needed, but use vendor for matching
                supplier_id = None
                try:
                    supplier = self.db.query(Supplier).filter(
                        func.lower(Supplier.supplier_name) == func.lower(supplier_name)
                    ).first()
                    if supplier:
                        supplier_id = supplier.id
                        supplier_name = supplier.supplier_name  # Use canonical supplier name
                except Exception:
                    pass  # If we can't find supplier, just use vendor name
                
                result.append({
                    "item_id": row.invoice_items_id,
                    "item": row.item,
                    "vendor": row.vendor,
                    "invoice_number": row.ref_no,
                    "current_price": float(row.current_price) if row.current_price else None,
                    "previous_price": float(row.previous_price) if row.previous_price else None,
                    "price_difference": float(row.price_change) if row.price_change else None,
                    "percentage_increase": float(row.percentage_increase) if row.percentage_increase else None,
                    "quantity": int(row.current_qty) if row.current_qty else 1,
                    "supplier_name": supplier_name,
                    "supplier_id": supplier_id,
                    "invoice_date": row.purchase_date.isoformat() if row.purchase_date else None,
                    "date": row.purchase_date
                })
            
            # Step 4: Apply supplier filter if provided
            # Handle multiple suppliers (supplier_names array) or single supplier (supplier_name)
            supplier_filters = []
            if filters and 'supplier_names' in filters:
                supplier_filters = filters['supplier_names']
            elif filters and 'supplier_name' in filters:
                supplier_filters = [filters['supplier_name']]
            
            if supplier_filters:
                # Normalize supplier filters to lowercase for matching
                supplier_filters_lower = [s.lower().strip() for s in supplier_filters if s]
                filtered_result = []
                
                # Track which suppliers were found
                found_suppliers = set()
                
                for r in result:
                    supplier_name = (r.get('supplier_name') or '').lower()
                    vendor = (r.get('vendor') or '').lower()
                    
                    # Check if this item matches any of the requested suppliers
                    matches = False
                    for supplier_filter in supplier_filters_lower:
                        # More flexible matching - try multiple strategies
                        # 1. Exact match
                        if supplier_filter == supplier_name or supplier_filter == vendor:
                            matches = True
                            found_suppliers.add(r.get('supplier_name') or r.get('vendor'))
                            break
                        # 2. Contains match (requested in supplier/vendor)
                        elif supplier_filter in supplier_name or supplier_filter in vendor:
                            matches = True
                            found_suppliers.add(r.get('supplier_name') or r.get('vendor'))
                            break
                        # 3. Supplier/vendor contains requested
                        elif supplier_name in supplier_filter or vendor in supplier_filter:
                            matches = True
                            found_suppliers.add(r.get('supplier_name') or r.get('vendor'))
                            break
                        # 4. Word-based matching
                        else:
                            supplier_filter_words = set(supplier_filter.split())
                            supplier_words = set(supplier_name.split())
                            vendor_words = set(vendor.split())
                            
                            # Check if significant words match
                            common_supplier_words = supplier_filter_words.intersection(supplier_words)
                            common_vendor_words = supplier_filter_words.intersection(vendor_words)
                            
                            # If we have at least 2 common words or one long word (>4 chars), consider it a match
                            if (len(common_supplier_words) >= 2 or 
                                any(len(w) > 4 for w in common_supplier_words) or
                                len(common_vendor_words) >= 2 or
                                any(len(w) > 4 for w in common_vendor_words)):
                                matches = True
                                found_suppliers.add(r.get('supplier_name') or r.get('vendor'))
                                break
                    
                    if matches:
                        filtered_result.append(r)
                
                result = filtered_result
                logger.info(f"After supplier filter(s) '{supplier_filters}': {len(result)} items remaining")
                logger.info(f"Found suppliers in results: {list(found_suppliers)}")
                
                # Log if some requested suppliers weren't found
                requested_set = set(s.lower() for s in supplier_filters)
                found_set = set(s.lower() for s in found_suppliers if s)
                missing = requested_set - found_set
                if missing:
                    logger.warning(f"Requested suppliers not found in filtered results: {missing}")
            
            if filters and 'supplier_id' in filters:
                supplier_id = filters['supplier_id']
                result = [r for r in result if r['supplier_id'] == supplier_id]
            
            logger.info(
                f"Found {len(result)} items with price increases. "
                f"Filters applied: {filters if filters else 'none'}"
            )
            
            # Log sample of results for debugging
            if result and len(result) > 0:
                sample = result[0]
                logger.info(
                    f"Sample result: item={sample.get('item')}, "
                    f"supplier={sample.get('supplier_name')}, "
                    f"date={sample.get('date')}, "
                    f"current_price={sample.get('current_price')}, "
                    f"previous_price={sample.get('previous_price')}, "
                    f"percentage={sample.get('percentage_increase')}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting price increase details: {str(e)}", exc_info=True)
            # Rollback transaction to ensure clean state
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback in get_price_increase_details: {rollback_error}")
            return []

    def get_invoice_items_raw(self, invoice_id=None, batch_size=1000):
        """
        Get invoice items as raw SQLAlchemy objects for QuickBooks export.
        This avoids Pydantic conversion issues that can cause missing fields in DataFrames.

        Args:
            invoice_id: Optional invoice ID to filter by
            batch_size: Number of records to fetch in each batch

        Returns:
            List of SQLAlchemy objects
        """
        logger.debug(f"Getting raw invoice items for invoice_id: {invoice_id}")

        # Explicitly query all columns to avoid any lazy loading issues
        query = self.db.query(InvoiceItem)

        if invoice_id:
            query = query.filter(InvoiceItem.invoice_id == invoice_id)

        # Apply empty item filter
        query = self._apply_empty_item_filter(query)

        # Use only the columns we need for better performance
        query = query.options(
            # Load only the columns we need for QuickBooks export
            # This reduces memory usage and improves performance
            sqlalchemy.orm.load_only(
                InvoiceItem.id,
                InvoiceItem.invoice_id,
                InvoiceItem.sheet_name,
                InvoiceItem.mpi_item,
                InvoiceItem.item,
                InvoiceItem.description,
                InvoiceItem.qty,
                InvoiceItem.cost,
                InvoiceItem.amount,
                InvoiceItem.date,
                InvoiceItem.ref_no,
                InvoiceItem.customer_job,
                InvoiceItem.vendor,
                InvoiceItem.class_,
                InvoiceItem.memo
            )
        )

        # Order by ID for consistent results
        query = query.order_by(InvoiceItem.id.desc())

        # For large datasets, use batched loading to reduce memory usage
        if batch_size and batch_size > 0:
            items = []
            offset = 0
            while True:
                batch = query.limit(batch_size).offset(offset).all()
                if not batch:
                    break
                items.extend(batch)
                offset += batch_size
                if len(batch) < batch_size:  # Last batch
                    break
        else:
            items = query.all()

        logger.debug(
            f"Retrieved {len(items)} items for invoice_id: {invoice_id}")

        return items

    def get_invoice_items_by_invoice_ids(self, invoice_ids, batch_size=1000):
        """
        Get invoice items by a list of invoice IDs for QuickBooks export.
        This method gets all invoice items that belong to the specified invoices.

        Args:
            invoice_ids: List of invoice IDs (can be UUID objects or strings)
            batch_size: Number of records to fetch in each batch for large datasets

        Returns:
            List of InvoiceItem objects with necessary attributes loaded
        """
        logger.debug(
            f"Getting invoice items for {len(invoice_ids) if invoice_ids else 0} invoices")

        if not invoice_ids:
            return []

        # Convert UUID objects to strings if needed for database query
        processed_invoice_ids = []
        for invoice_id in invoice_ids:
            if hasattr(invoice_id, '__str__'):
                processed_invoice_ids.append(str(invoice_id))
            else:
                processed_invoice_ids.append(invoice_id)

        # Build query to get all invoice items for the specified invoices
        query = self.db.query(InvoiceItem).filter(
            InvoiceItem.invoice_id.in_(processed_invoice_ids)
        )

        # Apply empty item filter
        query = self._apply_empty_item_filter(query)

        # Use optimized loading for QuickBooks export - only load necessary columns
        query = query.options(
            sqlalchemy.orm.load_only(
                InvoiceItem.id,
                InvoiceItem.invoice_id,
                InvoiceItem.sheet_name,  # CRITICAL: Added for QuickBooks business logic
                InvoiceItem.mpi_item,    # CRITICAL: Added for QuickBooks business logic
                InvoiceItem.item,
                InvoiceItem.description,
                InvoiceItem.qty,
                InvoiceItem.cost,
                InvoiceItem.amount,
                InvoiceItem.date,
                InvoiceItem.ref_no,
                InvoiceItem.customer_job,
                InvoiceItem.vendor,
                InvoiceItem.class_,
                InvoiceItem.memo,
                InvoiceItem.export_status
            )
        )

        # Order by invoice_id and then by id for consistent results
        query = query.order_by(InvoiceItem.invoice_id, InvoiceItem.id)

        # For large datasets, use batched loading to reduce memory usage
        if batch_size and batch_size > 0 and len(processed_invoice_ids) > 10:
            items = []
            offset = 0
            while True:
                batch = query.limit(batch_size).offset(offset).all()
                if not batch:
                    break
                items.extend(batch)
                offset += batch_size
                if len(batch) < batch_size:  # Last batch
                    break
        else:
            items = query.all()

        logger.debug(
            f"Retrieved {len(items)} invoice items for {len(processed_invoice_ids)} invoices")
        return items

    def get_suppliers_by_ids(self, supplier_ids):
        """
        Get suppliers by a list of supplier IDs for QuickBooks export.

        Args:
            supplier_ids: List of supplier IDs

        Returns:
            List of simple objects with id and supplier_name attributes
        """
        if not supplier_ids:
            return []

        from mpi_backend.database.models.Suppliers import Supplier

        # Query only id and supplier_name columns to avoid suffix column error
        suppliers = self.db.query(Supplier.id, Supplier.supplier_name).filter(
            Supplier.id.in_(supplier_ids)
        ).all()

        # Create simple objects with id and supplier_name attributes
        class SupplierInfo:
            def __init__(self, id, supplier_name):
                self.id = id
                self.supplier_name = supplier_name

        result = [SupplierInfo(id=sid, supplier_name=sname) for sid, sname in suppliers]

        logger.debug(
            f"Retrieved {len(result)} suppliers for {len(supplier_ids)} supplier IDs")
        return result

    def _apply_empty_item_filter(self, query):
        """
        Apply filter to exclude items with empty or invalid item codes.
        Items with empty item codes, dots, or whitespace-only codes are excluded.
        """
        from mpi_backend.database.models.InvoiceItems import InvoiceItem

        # Filter out empty, null, or just dot item codes
        query = query.filter(
            InvoiceItem.item.isnot(None),
            InvoiceItem.item != "",
            InvoiceItem.item != ".",
            func.trim(InvoiceItem.item) != "",
            func.trim(InvoiceItem.item) != "."
        )

        return query

    def _add_suffix_to_item(self, item_code: str, vendor: str) -> str:
        """
        Add the correct suffix to an item code based on vendor information.

        Args:
            item_code: The original item code from the invoice
            vendor: The vendor/supplier name

        Returns:
            Item code with proper suffix added
        """
        if not item_code or not vendor:
            return item_code

        # Extract supplier ID from vendor name
        supplier_id, _ = self._extract_supplier_id(vendor)
        if supplier_id is None:
            return item_code

        # Get suffix for this supplier
        suffix = self._get_supplier_suffix(supplier_id)
        if not suffix:
            return item_code

        # Check if item should be skipped from suffix processing
        if self._should_skip_item(item_code):
            return item_code

        # Clean any existing suffixes first
        clean_item = self._clean_existing_suffixes(item_code)

        # Add the correct suffix
        return f"{clean_item}-{suffix}"

    def _extract_supplier_id(self, vendor_name: str) -> tuple:
        """Extract supplier ID and name from vendor string.

        Uses centralized supplier_suffix_manager for lookups.
        """
        if not vendor_name:
            return None, None

        supplier_id = get_supplier_id_from_name(vendor_name)
        if supplier_id is not None:
            supplier_name = get_supplier_name_from_id(supplier_id)
            return supplier_id, supplier_name

        return None, None

    def _get_supplier_suffix(self, supplier_id: int) -> str:
        """
        Get suffix for a supplier ID.
        Uses centralized supplier_suffix_manager.
        """
        return get_supplier_suffix(supplier_id=supplier_id, db=self.db)

    def _should_skip_item(self, item_code: str) -> bool:
        """Check if item should be skipped from suffix processing."""
        if not item_code:
            return True

        item_str = str(item_code).strip()

        # Exclude tax and administrative items from getting suffixes
        excluded_items = [
            "tax", "freight", "shipping", "handling", "subtotal", "total"
        ]

        if (item_str.lower().startswith("tax") or
                item_str.startswith("10 Materials") or
                item_str.lower() in excluded_items):
            return True

        return False

    def _clean_existing_suffixes(self, item_code: str) -> str:
        """Remove all existing suffixes from item code."""
        if not item_code:
            return item_code

        clean_item = str(item_code).strip()

        # Remove ALL existing suffixes first (including double suffixes)
        all_suffixes = ['B', 'W', 'Y', 'S', 'P', 'A', 'G', 'F']

        # Keep removing suffixes until none are found
        while True:
            found_suffix = False
            for existing_suffix in all_suffixes:
                if clean_item.endswith(f"-{existing_suffix}"):
                    clean_item = clean_item[:-len(f"-{existing_suffix}")]
                    found_suffix = True
                    break
            if not found_suffix:
                break

        return clean_item

    def update_existing_invoice_items(self, invoice_id, new_data_rows, filename):
        """
        Update existing invoice items for an updated invoice

        Args:
            invoice_id: UUID of the existing invoice to update
            new_data_rows: DataFrame rows with new invoice data
            filename: New filename for the updated invoice

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # First, mark all existing items as inactive
            existing_items = self.db.query(InvoiceItem).filter(
                InvoiceItem.invoice_id == invoice_id
            ).all()

            for item in existing_items:
                item.is_active = False

            # Add new items with the updated data
            for index, row in new_data_rows.iterrows():
                # Add proper suffix to item code based on vendor
                item_with_suffix = self._add_suffix_to_item(
                    row['Item'], row['Vendor'])

                # Robust date parsing
                date_str = str(row['Date'])
                try:
                    parsed_date = datetime.strptime(date_str, '%m/%d/%Y')
                except ValueError:
                    try:
                        parsed_date = datetime.strptime(date_str, '%m/%d/%y')
                    except ValueError:
                        logger.error(f"Could not parse date: {date_str}")
                        parsed_date = None

                new_item = InvoiceItem(
                    filename=filename,
                    sheet_name=row['Sheet Name'],
                    invoice_id=invoice_id,
                    mpi_item=row['MpiItem'],
                    mpi_description=row['MpiDescription'],
                    item=item_with_suffix,
                    description=row['Description'],
                    qty=row['Qty'],
                    cost=row['Cost'],
                    amount=row['Amount'],
                    date=parsed_date,
                    ref_no=row['Ref NO'],
                    po_number=row['PO #'],
                    customer_job=row['Customer Job'],
                    bill=row['Bill'],
                    vendor=row['Vendor'],
                    class_=row['Class'],
                    account=row.get('Account', ''),  # New account field with default empty string
                    memo=row['Memo'],
                    buyer=row['Buyer'],
                    date_added=row['email_date'],
                    export_status="Pending",
                    is_active=True
                )
                self.db.add(new_item)

            self.db.commit()
            logger.info(
                f'Successfully updated invoice {invoice_id} with {len(new_data_rows)} new items')
            return True

        except Exception as e:
            logger.error(f"Error updating existing invoice items: {str(e)}")
            self.db.rollback()
            return False

    def get_filtered_items_paginated(self, filter_request: FilterRequest, page_size: int, offset: int = 0):
        """
        OPTIMIZED: Get filtered invoice items with efficient pagination
        """
        try:
            self._monitor_resource_usage("get_filtered_items_paginated")
            
            # Build base query from cache
            query = self._compiled_queries['filter_base'].execution_options(
                enable_eagerloads=False  # Disable eager loading for performance
            )
            
            # Apply filters efficiently
            query = self._apply_filters_to_query(query, filter_request)
            
            # Get total count first (optimized)
            count_query = query.with_entities(func.count(InvoiceItem.id))
            total_count = self.db.execute(count_query).scalar()
            
            # Apply pagination and ordering
            query = query.offset(offset).limit(page_size)
            
            # Execute query with optimized loading
            results = self.db.execute(query).scalars().all()
            
            self._log_resource_usage("get_filtered_items_paginated")
            
            return results, total_count
            
        except Exception as e:
            logger.error(f"Error in get_filtered_items_paginated: {e}")
            raise

    def _apply_filters_to_query(self, query, filter_request: FilterRequest):
        """Apply filters to query efficiently"""
        try:
            # Apply date range filter if provided
            if filter_request.start_date and filter_request.end_date:
                query = query.filter(
                    InvoiceItem.date >= filter_request.start_date,
                    InvoiceItem.date <= filter_request.end_date
                )
            
            # Apply supplier filter if provided
            if filter_request.supplier_id:
                query = query.filter(InvoiceItem.supplier_id == filter_request.supplier_id)
            
            # Apply customer job filter if provided
            if filter_request.customer_job:
                query = query.filter(InvoiceItem.customer_job == filter_request.customer_job)
            
            # Apply item code filter if provided
            if filter_request.item_code:
                query = query.filter(InvoiceItem.item == filter_request.item_code)
            
            # Apply cost range filter if provided
            if filter_request.min_cost is not None:
                query = query.filter(InvoiceItem.cost >= filter_request.min_cost)
            if filter_request.max_cost is not None:
                query = query.filter(InvoiceItem.cost <= filter_request.max_cost)
            
            return query
            
        except Exception as e:
            logger.error(f"Error applying filters: {e}")
            return query

    def update_invoice_items_sync(self, items: List[Dict]) -> int:
        """
        Synchronously update multiple invoice items without background tasks or mapping restrictions.
        
        This method bypasses the normal validation that prevents updating to UIDI items
        and processes updates immediately without background tasks.
        
        Args:
            items: List of dictionaries containing item updates
            
        Returns:
            int: Number of items successfully updated
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"update_invoice_items_sync: Processing {len(items)} items")
        total_updated = 0
        batch_size = 100  # Process in smaller batches to avoid memory issues
        
        try:
            for batch_start in range(0, len(items), batch_size):
                batch_end = min(batch_start + batch_size, len(items))
                batch_items = items[batch_start:batch_end]
                
                batch_num = batch_start//batch_size + 1
                total_batches = (len(items) + batch_size - 1) // batch_size
                logger.info(f"Processing batch {batch_num}/{total_batches}: items {batch_start+1}-{batch_end}")
                batch_updated = 0
                
                for i, item_data in enumerate(batch_items):
                    global_index = batch_start + i
                    item_id = item_data.get('id')
                    if not item_id:
                        logger.warning(f"Item {global_index}: Missing ID, skipping")
                        continue
                        
                    item = self.db.query(InvoiceItem).filter(InvoiceItem.id == item_id).first()
                    if not item:
                        logger.warning(f"Item {global_index}: ID {item_id} not found in database")
                        continue
                    
                    # Schema handles null values automatically for account and is_active
                    
                    # Handle null values for UUID fields - don't update if empty
                    uuid_fields = ['invoice_id']
                    for field in uuid_fields:
                        if field in item_data:
                            value = item_data[field]
                            if value is None or value == "null" or value == "None" or value == "":
                                # Don't update UUID fields if they're empty/null
                                item_data.pop(field, None)
                                logger.debug(f"Item {global_index}: Skipping empty UUID field '{field}'")
                    
                    # Handle null values for date fields - don't update if empty
                    date_fields = ['date', 'date_added']
                    for field in date_fields:
                        if field in item_data:
                            value = item_data[field]
                            if value is None or value == "null" or value == "None" or value == "":
                                # Don't update date fields if they're empty/null
                                item_data.pop(field, None)
                                logger.debug(f"Item {global_index}: Skipping empty date field '{field}'")
                    
                    # Update the item with all provided fields
                    updated_fields = []
                    for key, value in item_data.items():
                        if hasattr(item, key) and key != 'id':
                            old_value = getattr(item, key)
                            
                            # Parse numeric fields to handle comma-separated values
                            if key in ['cost']:  # cost is double precision in database
                                parsed_value = self._parse_numeric_value(value)
                                setattr(item, key, parsed_value)
                                if old_value != parsed_value:
                                    updated_fields.append(f"{key}: {old_value} -> {parsed_value}")
                            elif key in ['amount']:  # amount is string but parse for consistency
                                parsed_value = self._parse_amount_value(value)
                                setattr(item, key, parsed_value)
                                if old_value != parsed_value:
                                    updated_fields.append(f"{key}: {old_value} -> {parsed_value}")
                            else:
                                setattr(item, key, value)
                                if old_value != value:
                                    updated_fields.append(f"{key}: {old_value} -> {value}")
                    
                    if updated_fields:
                        logger.info(f"Item {global_index}: Updated fields: {', '.join(updated_fields)}")
                        batch_updated += 1
                        self.db.add(item)
                    else:
                        logger.debug(f"Item {global_index}: No fields changed")
                
                if batch_updated > 0:
                    self.db.commit()
                    logger.info(f"Batch {batch_num}/{total_batches}: Successfully committed {batch_updated} item updates")
                    total_updated += batch_updated
                else:
                    logger.info(f"Batch {batch_num}/{total_batches}: No updates needed")
            
            logger.info(f"Successfully completed bulk update: {total_updated} total items updated")
            return total_updated
            
        except Exception as e:
            logger.error(f"Error in update_invoice_items_sync: {str(e)}")
            logger.exception("Full traceback:")
            self.db.rollback()
            raise e

    def filter_by_price_color(self, items_data: List[Dict[str, Any]], color_filters: Optional[ColorFilter]) -> List[Dict[str, Any]]:
        """
        Filter items based on color-coded price increase percentages.
        
        Args:
            items_data: List of invoice items with their data
            color_filters: ColorFilter object containing colors to filter by
            
        Returns:
            List of items with percentage_increase field added, filtered by color criteria
        """
        if not color_filters or not color_filters.colors:
            return items_data
            
        logger.info(f"Applying color filter: {color_filters.colors}")
        
        # Extract item-vendor pairs for price calculation
        item_vendor_pairs = []
        for item in items_data:
            item_vendor_pairs.append((item['item'], item['vendor'], item['id']))
        
        if not item_vendor_pairs:
            return items_data
            
        # Calculate price increases using existing method
        price_increases = self.calculate_price_increase(
            item_numbers=None, 
            item_vendor_pairs=item_vendor_pairs
        )
        
        # Create a mapping of item_id to percentage_increase
        price_map = {}
        for i, (item_code, percentage) in enumerate(price_increases):
            if i < len(item_vendor_pairs):
                item_id = item_vendor_pairs[i][2]
                price_map[item_id] = percentage
        
        # Filter items based on color criteria
        filtered_items = []
        for item in items_data:
            percentage_str = price_map.get(item['id'])
            
            # Convert percentage string to float for comparison
            percentage = None
            if percentage_str and percentage_str != "N/A":
                try:
                    # Remove % symbol and convert to float
                    percentage = float(percentage_str.replace('%', ''))
                except (ValueError, AttributeError):
                    percentage = None
            
            # Add percentage_increase to item data
            item_dict = item.copy()
            item_dict['percentage_increase'] = percentage
            
            # Apply color filtering
            should_include = False
            
            if "green" in color_filters.colors and percentage is not None and percentage > 10:
                should_include = True
            elif "orange" in color_filters.colors and percentage is not None and 4 <= percentage <= 9:
                should_include = True
            elif "both" in color_filters.colors and percentage is not None and percentage > 4:
                should_include = True
            
            if should_include:
                filtered_items.append(item_dict)
        
        logger.info(f"Color filter applied: {len(filtered_items)} items match criteria out of {len(items_data)} total")
        return filtered_items

    def get_filtered_items_for_color(self, filter_context: Dict[str, Any], comparison_filters: List[Dict[str, Any]], search: str = "") -> List[InvoiceItem]:
        """
        Get filtered invoice items for color-based filtering.
        This method applies standard filters (date, search) and returns items
        that can then be processed for color-based price filtering.
        
        Args:
            filter_context: Standard filter context
            comparison_filters: Date range filters
            search: Search term
            
        Returns:
            List of invoice items matching the standard filters
        """
        try:
            # Build base query for filtered items
            base_query = self.db.query(InvoiceItem).filter(InvoiceItem.is_active == True)
            
            # Apply comparison filters (date ranges)
            for cf in comparison_filters:
                if cf.get("column") == "date":
                    if cf.get("operator") == "gte":
                        base_query = base_query.filter(InvoiceItem.date >= cf.get("value"))
                    elif cf.get("operator") == "lte":
                        base_query = base_query.filter(InvoiceItem.date <= cf.get("value"))
            
            # Apply search filter if provided
            if search:
                search_term = f"%{search}%"
                base_query = base_query.filter(
                    or_(
                        InvoiceItem.item.ilike(search_term),
                        InvoiceItem.description.ilike(search_term),
                        InvoiceItem.vendor.ilike(search_term)
                    )
                )
            
            # Apply filter context
            for column, values in filter_context.items():
                if hasattr(InvoiceItem, column) and values:
                    if isinstance(values, list):
                        base_query = base_query.filter(getattr(InvoiceItem, column).in_(values))
                    else:
                        base_query = base_query.filter(getattr(InvoiceItem, column) == values)
            
            # Execute query and return results
            items = base_query.all()
            logger.info(f"Retrieved {len(items)} items for color filtering")
            return items
            
        except Exception as e:
            logger.error(f"Error getting filtered items for color: {e}")
            return []

    def update_invoice_item_columns(
        self,
        item_id: int,
        updates: Dict[str, Any],
        restricted_columns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Update columns of a single invoice item.
        
        Args:
            item_id: ID of the invoice item to update
            updates: Dictionary of column updates
            restricted_columns: List of columns to reject (for permission enforcement)
            
        Returns:
            Dict containing:
                - updated_count: Number of successfully updated items (always 1)
                - updated_fields: List of updated field names
                
        Raises:
            HTTPException: For validation errors, not found, or permission issues
        """
        from sqlalchemy.inspection import inspect
        
        try:
            # Get valid columns from the model
            mapper = inspect(InvoiceItem)
            valid_columns = {col.key for col in mapper.columns}
            # Remove id and invoice_id from updatable columns
            valid_columns.discard('id')
            valid_columns.discard('invoice_id')
            
            # Get the specific invoice item
            invoice_item = self.db.query(InvoiceItem).execution_options(
                include_all=True
            ).filter(
                InvoiceItem.id == item_id
            ).first()

            if not invoice_item:
                raise HTTPException(
                    status_code=404,
                    detail=f"Invoice item with id {item_id} not found"
                )

            updated_fields = []
            
            # Validate columns and update
            for column_name, new_value in updates.items():
                # Validate column exists
                if column_name not in valid_columns:
                    valid_cols_str = ', '.join(sorted(valid_columns))
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Invalid column: {column_name}. "
                            f"Valid: {valid_cols_str}"
                        )
                    )
                
                # Check if column is restricted (permission check done in route)
                if restricted_columns and column_name in restricted_columns:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Insufficient permissions to update column: {column_name}"
                    )
                
                # Update the column
                setattr(invoice_item, column_name, new_value)
                if column_name not in updated_fields:
                    updated_fields.append(column_name)

            self.db.commit()
            self.db.refresh(invoice_item)

            logger.info(
                f"Updated invoice item {item_id}, "
                f"fields: {updated_fields}"
            )
            
            return {
                "updated_count": 1,
                "updated_fields": updated_fields
            }
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating columns: {str(e)}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
