import logging
from typing import Optional, List
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, asc, desc
from sqlalchemy.orm import Session

from mpi_backend.database import get_db
from mpi_backend.database.models.User import User
from mpi_backend.database.models.InvoiceItems import InvoiceItem
from mpi_backend.utils.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/search",  # This prefix will be added after invoice-items
    tags=["Invoice Items"],
)


# Request/Response Schemas
class InvoiceSearchRequest(BaseModel):
    """Request model for searching invoice items by vendor pricing"""
    item: Optional[str] = Field(
        None,
        max_length=100,
        description="Item code to search for (partial match supported)"
    )
    mpi_item: Optional[str] = Field(
        None,
        max_length=100,
        description="MPI Item code to search for (partial match supported)"
    )
    vendor: Optional[str] = Field(
        None,
        max_length=200,
        description="Vendor/supplier name to filter by (partial match supported)"
    )
    date_from: Optional[date] = Field(
        None,
        description="Start date filter (YYYY-MM-DD)"
    )
    date_to: Optional[date] = Field(
        None,
        description="End date filter (YYYY-MM-DD)"
    )

    class Config:
        schema_extra = {
            "example": {
                "item": "PIPE-123",
                "vendor": "ABC Supplies",
                "date_from": "2024-01-01",
                "date_to": "2024-12-31"
            }
        }


class SupplierQuotedPriceDetails(BaseModel):
    """Supplier quoted price details showing cheapest unit price and most recent total price"""
    unit_price: float = Field(..., description="Cheapest unit price for this vendor-item combination")
    total_price: float = Field(..., description="Total price from the most recent purchase (within date range)")
    difference: Optional[float] = Field(None, description="Price difference (reserved for future use)")

    class Config:
        from_attributes = True


class VendorMinCostResponse(BaseModel):
    """Response model for vendor pricing data"""
    vendor: str = Field(..., description="Vendor/supplier name")
    mpi_item: Optional[str] = Field(None, description="MPI Item code")
    unit_price: float = Field(..., description="Unit price (cost per unit from the cheapest invoice item)")
    total_price: float = Field(..., description="Total price (amount) from the cheapest invoice item")

    class Config:
        from_attributes = True


class PaginatedSearchResponse(BaseModel):
    """Paginated response for vendor search results"""
    items: List[VendorMinCostResponse]
    supplier_quoted_price_details: SupplierQuotedPriceDetails = Field(
        ...,
        description="Supplier's quoted price details including cheapest unit price and most recent total price"
    )
    total_count: int = Field(..., description="Total number of vendors found")
    page: int = Field(..., description="Current page number")
    size: int = Field(..., description="Number of items per page")
    pages: int = Field(..., description="Total number of pages")

    class Config:
        from_attributes = True


@router.post("", response_model=PaginatedSearchResponse)
def search_invoices(
    request: InvoiceSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page")
):
    """
    Search invoice items and return minimum cost per MPI item grouped by vendor.

    ## Frontend Integration Guide

    **Endpoint:** `POST /invoice-items/search/?page=1&size=10`

    **Authentication:** Required (Bearer token in Authorization header)

    **Purpose:** Find the best vendor pricing for MPI items. Returns minimum cost for each
    MPI item from each vendor, grouped by vendor-MPI item combinations.

    ### Quick Start Example

    ```javascript
    // Example: Search for best pricing on a specific MPI item
    const response = await fetch('/invoice-items/search/?page=1&size=20', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        mpi_item: 'MPI-001'  // Find all vendors selling MPI-001
      })
    });

    const data = await response.json();
    // data.items will contain vendor-MPI item combinations with min costs
    ```

    ### Request Body Parameters (All Optional)

    - **mpi_item** (`string`, optional): MPI Item code to search for. Supports partial matching.
      - Example: `"MPI-001"` finds exact match
      - Example: `"MPI"` finds all MPI items containing "MPI"

    - **item** (`string`, optional): Original item code to search for. Supports partial matching.
      - Example: `"PIPE-123"` finds items with "PIPE-123" in the item code

    - **vendor** (`string`, optional): Vendor/supplier name to filter by. Supports partial matching.
      - Example: `"ABC"` matches "ABC Supplies", "ABC Corporation", etc.

    - **date_from** (`string`, optional): Start date filter in YYYY-MM-DD format.
      - Example: `"2024-01-01"` includes items from Jan 1, 2024 onwards

    - **date_to** (`string`, optional): End date filter in YYYY-MM-DD format.
      - Example: `"2024-12-31"` includes items up to Dec 31, 2024

    ### Query Parameters

    - **page** (`integer`, default=1, min=1): Page number (1-based indexing)
    - **size** (`integer`, default=10, min=1, max=100): Results per page

    ### Request Examples

    **Example 1: Find all vendors selling a specific MPI item**
    ```json
    POST /invoice-items/search/?page=1&size=20
    {
      "mpi_item": "MPI-001"
    }
    ```

    **Example 2: Compare pricing from a specific vendor**
    ```json
    POST /invoice-items/search/?page=1&size=50
    {
      "vendor": "ABC Supplies"
    }
    ```

    **Example 3: Find best pricing in a date range**
    ```json
    POST /invoice-items/search/?page=1&size=10
    {
      "mpi_item": "MPI-001",
      "date_from": "2024-01-01",
      "date_to": "2024-12-31"
    }
    ```

    **Example 4: Combined filters**
    ```json
    POST /invoice-items/search/?page=1&size=10
    {
      "mpi_item": "MPI",
      "vendor": "ABC",
      "date_from": "2024-06-01"
    }
    ```

    **Example 5: Get all vendor-item combinations (no filters)**
    ```json
    POST /invoice-items/search/?page=1&size=50
    {}
    ```

    **Response Example:**

    ```json
    {
      "items": [
        {
          "vendor": "ABC Supplies",
          "mpi_item": "MPI-001",
          "unit_price": 15.50,
          "total_price": 155.00
        },
        {
          "vendor": "ABC Supplies",
          "mpi_item": "MPI-002",
          "unit_price": 22.00,
          "total_price": 220.00
        },
        {
          "vendor": "XYZ Corporation",
          "mpi_item": "MPI-001",
          "unit_price": 17.25,
          "total_price": 172.50
        }
      ],
      "supplier_quoted_price_details": {
        "unit_price": 15.50,
        "total_price": 155.00,
        "difference": null
      },
      "total_count": 3,
      "page": 1,
      "size": 10,
      "pages": 1
    }
    ```

    **Response Fields:**

    - **items** (`List[object]`): List of vendor-MPI item combinations with their pricing information
        - **vendor** (`str`): Vendor/supplier name from invoice items
        - **mpi_item** (`str`, optional): MPI Item code from invoice items
        - **unit_price** (`float`): Unit price (cost per unit) from the cheapest invoice item for this vendor-MPI item combination. Among items with the same cheapest price, the most recent one is used.
        - **total_price** (`float`): Total price (amount) from the cheapest invoice item for this vendor-MPI item combination
    - **supplier_quoted_price_details** (`object`): Pricing details for the overall cheapest vendor across all results
        - **unit_price** (`float`): Cheapest unit price found across all vendor-item combinations in the search results
        - **total_price** (`float`): Total price (amount) corresponding to the cheapest unit price
        - **difference** (`float`, optional): Reserved for future use (price difference calculation)
    - **total_count** (`int`): Total number of unique vendor-MPI item combinations found across all pages
    - **page** (`int`): Current page number (1-based)
    - **size** (`int`): Number of items requested per page
    - **pages** (`int`): Total number of pages available

    ### Search Behavior & Filtering

    - **Case-Insensitive Matching**: All text searches (item, mpi_item, vendor) are case-insensitive
      and support partial matching. "ABC" will match "ABC Supplies", "abc corp", etc.

    - **Date Range Filtering**: When `date_from` and/or `date_to` are provided, only invoice items
      within that date range (inclusive) are included in the results.

    - **Automatic Exclusions**:
      - Inactive items (`is_active = false`) are automatically excluded
      - Items with cost ≤ 0 or NULL cost are automatically excluded (only valid pricing data)

    - **Result Selection**:
      - Results show one row per unique vendor-MPI item combination
      - For each combination, the row with the cheapest `cost` (unit price) is selected
      - If multiple rows have the same cheapest cost, the most recent one (by date) is returned
      - The database's `cost` field represents the unit price (no calculation needed)

    - **Ordering**: Results are sorted alphabetically by vendor name, then by MPI item code

    ### Common Use Cases

    1. **Find Best Vendor for an MPI Item**
       - Search by `mpi_item` to compare which vendor has the lowest price
       - Sort results by `min_cost` on frontend to find cheapest option

    2. **Vendor Price Comparison**
       - Filter by `vendor` to see all items and pricing from that vendor
       - Useful for vendor performance analysis

    3. **Historical Price Analysis**
       - Use `date_from` and `date_to` to compare pricing across time periods
       - Track price trends for specific items

    4. **Bulk Pricing Overview**
       - Send empty filter `{}` to get all vendor-item combinations
       - Useful for generating price sheets or cost analysis reports

    ### Frontend Implementation Tips

    ```javascript
    // Tip 1: Sort results by min_cost to find cheapest vendor
    const sortedByPrice = data.items.sort((a, b) => a.min_cost - b.min_cost);
    const cheapestVendor = sortedByPrice[0];

    // Tip 2: Handle pagination for large result sets
    const totalPages = data.pages;
    const hasMore = data.page < totalPages;

    // Tip 3: Display unit price vs total cost appropriately
    // unit_price is better for per-unit comparisons
    // min_cost shows the actual minimum cost found

    // Tip 4: Group results by MPI item for comparison tables
    const byMpiItem = data.items.reduce((acc, item) => {
      if (!acc[item.mpi_item]) acc[item.mpi_item] = [];
      acc[item.mpi_item].push(item);
      return acc;
    }, {});
    ```

    **Extensibility:**

    This endpoint is designed to be flexible and extensible. Future enhancements may include:
    - Additional filter parameters (e.g., customer_job, po_number, export_status)
    - Comparison operators for cost filtering (e.g., cost less than X)
    - Sorting options (e.g., order by min_cost ascending/descending)
    - Statistical aggregations (e.g., average cost, max cost, std deviation)

    ### Error Handling

    **Status Codes:**

    - **200 OK**: Successful search (even if no results found - returns empty array)
    - **401 Unauthorized**: Missing or invalid authentication token
    - **422 Unprocessable Entity**: Invalid request parameters (e.g., bad date format, page < 1, size > 100)
    - **500 Internal Server Error**: Database error or unexpected server error

    **Error Response Example:**
    ```json
    {
      "detail": "An error occurred while searching invoice items: [error message]"
    }
    ```

    **Frontend Error Handling:**
    ```javascript
    try {
      const response = await fetch('/invoice-items/search/?page=1&size=10', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ mpi_item: 'MPI-001' })
      });

      if (!response.ok) {
        if (response.status === 401) {
          // Handle authentication error - redirect to login
        } else if (response.status === 422) {
          // Handle validation error - show error message to user
          const error = await response.json();
          console.error('Validation error:', error.detail);
        }
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      // Handle empty results
      if (data.total_count === 0) {
        console.log('No results found for search criteria');
      }
    } catch (error) {
      console.error('Search failed:', error);
    }
    ```

    ### Important Notes

    - All string comparisons are case-insensitive
    - Partial matching is supported for item, mpi_item, and vendor parameters
    - Results are ordered by vendor name, then MPI item code (alphabetically)
    - Only active items with valid costs (> 0) are included
    - Empty result sets return `{"items": [], "total_count": 0, ...}`
    - Each result represents a unique vendor-MPI item combination
    - Date filters use YYYY-MM-DD format and are inclusive
    """
    try:
        # Calculate pagination offset
        offset = (page - 1) * size

        # Build base query with filters
        base_query = db.query(
            InvoiceItem.vendor,
            InvoiceItem.mpi_item,
            InvoiceItem.cost.label('unit_price'),
            InvoiceItem.amount.label('total_price'),
            InvoiceItem.date,
        ).filter(
            InvoiceItem.is_active == True,
            InvoiceItem.cost.isnot(None),
            InvoiceItem.cost > 0
        )

        # Apply dynamic filters using ORM (secure from SQL injection)
        if request.item:
            base_query = base_query.filter(
                func.lower(InvoiceItem.item).like(func.lower(f"%{request.item}%"))
            )

        if request.mpi_item:
            base_query = base_query.filter(
                func.lower(InvoiceItem.mpi_item).like(func.lower(f"%{request.mpi_item}%"))
            )

        if request.vendor:
            base_query = base_query.filter(
                func.lower(InvoiceItem.vendor).like(func.lower(f"%{request.vendor}%"))
            )

        if request.date_from:
            base_query = base_query.filter(InvoiceItem.date >= request.date_from)

        if request.date_to:
            base_query = base_query.filter(InvoiceItem.date <= request.date_to)

        # This finds the cheapest item per (vendor, mpi_item) combination
        # Note: DISTINCT ON requires the same columns in ORDER BY
        # Get count and data in ONE query using window function
        # Add COUNT(*) OVER() to get total count alongside results
        distinct_query = base_query.add_columns(
            func.count().over().label('total_count')
        ).order_by(
            InvoiceItem.vendor,
            InvoiceItem.mpi_item,
            asc(InvoiceItem.cost),
            desc(InvoiceItem.date)
        ).distinct(
            InvoiceItem.vendor,
            InvoiceItem.mpi_item
        )

        # Apply pagination and execute - single query for both count and data
        rows = distinct_query.limit(size).offset(offset).all()

        # Extract total_count from first row (all rows have same count due to window function)
        total_count = rows[0].total_count if rows else 0

        # Format results and track cheapest vendor
        items = []
        cheapest_unit_price = None
        cheapest_total_price = None

        for row in rows:
            # Extract values with defaults (row now includes total_count from window function)
            unit_price = float(row.unit_price) if row.unit_price is not None else 0.0
            total_price = float(row.total_price) if row.total_price is not None else 0.0

            vendor_data = VendorMinCostResponse(
                vendor=row.vendor if row.vendor else "Unknown Vendor",
                mpi_item=row.mpi_item,
                unit_price=unit_price,
                total_price=total_price,
            )
            items.append(vendor_data)

            # Track the overall cheapest unit price (for supplier_quoted_price_details)
            # When we find the cheapest unit price, also capture its total_price
            if cheapest_unit_price is None or (unit_price > 0 and unit_price < cheapest_unit_price):
                cheapest_unit_price = unit_price
                cheapest_total_price = total_price

        # Calculate total pages
        total_pages = (total_count + size - 1) // size if total_count > 0 else 0

        # Log successful search
        logger.info(
            f"Search completed: user={current_user.email}, "
            f"filters={request.model_dump()}, "
            f"results={total_count} vendor-item combinations"
        )

        # Handle empty results case
        if cheapest_unit_price is None:
            cheapest_unit_price = 0.0
            cheapest_total_price = 0.0

        return PaginatedSearchResponse(
            items=items,
            total_count=total_count,
            page=page,
            size=size,
            pages=total_pages,
            supplier_quoted_price_details=SupplierQuotedPriceDetails(
                unit_price=cheapest_unit_price,
                total_price=cheapest_total_price,
                difference=None
            )
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log the error with full context (including stack trace)
        logger.error(
            f"Error searching invoice items: {str(e)}, "
            f"user={current_user.email}, "
            f"filters={request.model_dump()}",
            exc_info=True  # Include full stack trace in logs
        )
        # Return generic error message to client (don't expose internal details)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while searching invoice items. Please try again or contact support."
        )
