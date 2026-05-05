# MPI Backend API Endpoints Documentation

## Authentication
All protected endpoints require a JWT Bearer token which can be obtained through the signin endpoint.

### Sign In
**POST** `/signin`

Authenticates a user and returns a JWT token. The expiry of the JWT token is for a month. All requests will contain this token in the header.

**Request Body:**
```json
{
  "username": "mpi",
  "password": "mpi_password@123"
}
```

**Responses:**
- **200**: Successfully authenticated, returns JWT token
- **400**: Username and password are required
- **403**: Wrong login details

---

## Invoice Management

### Get Invoices
**GET** `/invoice`

Retrieves a paginated list of invoices with optional filters. The endpoint queries the 'invoices' table.

**Query Parameters:**
- **supplier_id**: `List[int]` - Filter by supplier IDs, to get invoices from all suppliers set it to 0
- **from_date**: `date` - Start date filter
- **to_date**: `date` - End date filter
- **status**: `str` - Filter by status (all, processed, unprocessed)
- **job_location**: `str` - Filter by job location / customer job
- **export_status**: `str` - Filter by export status [Pending, Sent]
- **page**: `int` - Page number (default: 1)
- **size**: `int` - Invoice records per page (default: 10, max: 100)

**Responses:**
- **200**: Returns PaginatedInvoiceResponse
- **404**: No Records Found

All the data being displayed on the dashboard table is populated using this endpoint.

### Get All Invoices
**GET** `/invoice/all`

Retrieves all invoices without pagination.

**Responses:**
- **200**: Returns list of all invoices
- **500**: Error occurred while fetching invoices

Currently not used on frontend anywhere, but you can use it for debugging.

### Download Invoice
**GET** `/invoice/download`

Downloads / Renders PDF file of specific invoice. Based on provided invoice-id (a unique uuid which serves as primary key to invoices table and is generated during the processing of invoice first time) it runs a query to find out supplier. Then it constructs the S3 bucket path and generates the signed url to download or render the file. That signed URL is returned as a response.

**Query Parameters:**
- **invoice_id**: `str` - ID of the invoice to download

**Responses:**
- **200**: Returns download link
- **404**: Couldn't fetch requested file

This endpoint is integrated on the dashboard tab to VIEW invoices.

### Upload Invoice
**POST** `/invoice/upload`

The system can ingest invoices through two ways 1) obtained through email 2) Directly uploaded through upload tab. This endpoint receives the directly uploaded invoice and processes it.

**Form Data:**
- **supplier_id**: `int`
- **file**: `UploadFile` (PDF only)

**Responses:**
- **200**: Invoice processed successfully
- **400**: Only PDF files are allowed

Integrated on the upload tab on frontend.

### Process Invoice Again
**POST** `/invoice/process`

If the user wants to reprocess an invoice, this endpoint enables that. It takes in invoice-id (primary identifier of invoice as explained above), using that invoice-id it gets its supplier and then constructs the S3 bucket file path where the invoice is stored. Using the url it downloads the pdf file of the invoice and writes it to local storage. Then deletes the previous invoice items rows and invoice entry from invoice & invoice_items table. Then runs the convert and combine workflow again and inserts new data in the database.

**Query Parameters:**
- **invoice_id**: `str` - ID of the invoice to reprocess

**Responses:**
- **200**: Invoice reprocessing successful
- **404**: Couldn't fetch requested invoice

Integrated on the Dashboard tab on frontend and is triggered by selecting an invoice and clicking on process again.

### Sort Invoices
**GET** `/invoice/sort`

Sorts invoices based on specified criteria.

**Query Parameters:**
- **column_name**: `str` - Column to sort by (Date, File Name, Status, Job Address, Invoice, Supplier)
- **sort_order**: `str` - Sort direction (ascending, descending)

**Responses:**
- **200**: Returns sorted invoices
- **400**: Invalid sort parameters

### Delete Invoice
**DELETE** `/invoice/delete`

Deletes one or more invoices and their associated files from the system.

**Query Parameters:**
- **invoice_id**: `str` - Invoice ID(s) to delete (single ID or comma-separated multiple IDs)

**Responses:**
- **200**: Invoice(s) deleted successfully
- **400**: Invalid invoice_id parameter
- **404**: Invoice not found

---

## Invoice Items

### Get Invoice Items
**GET** `/invoice-items/all`

Retrieves a list of all invoice items sorted by id in descending order.

**Responses:**
- **200**: Returns Page[InvoiceItems]
- **404**: No Records Found

Deprecated, not directly used integrated in web app. But can be used for debugging.

### Get Invoice Items by ID
**GET** `/invoice-items/id`

Retrieves invoice items for a specific invoice. Indirectly used in migrate to quick books endpoint.

**Query Parameters:**
- **invoice_id** (optional): `UUID` - Filter by invoice ID

**Responses:**
- **200**: Returns Page[InvoiceItems]
- **404**: No Records Found

### Get Invoice Items by Supplier and Date
**GET** `/invoice-items/supplier-date`

Retrieves invoice items filtered by supplier and date range.

**Query Parameters:**
- **supplier_name**: `List[str]` - Supplier names to filter by
- **from_date**: `date` - Start date filter
- **to_date**: `date` - End date filter
- **job_location**: `str` - Job location filter
- **export_status**: `str` - Export status filter
- **page**: `int` - Page number (default: 1)
- **size**: `int` - Items per page (default: 10)

**Responses:**
- **200**: Returns paginated invoice items
- **404**: No Records Found

### Update Invoice Items
**PUT** `/invoice-items/update`

Updates multiple invoice items. Triggers background tasks to update MPI mappings if mpi_item or mpi_description fields are modified.

**Request Body:**
```json
[
  {
    "id": "int", // required, so it knows which row to change
    "mpi_item": "new value"
    // ... other fields
  }
]
```

**Responses:**
- **200**: Invoices updated successfully

### Toggle Item Visibility
**PUT** `/invoice-items/toggle-visibility`

Toggles the visibility status of invoice items.

**Request Body:**
```json
{
  "ids": ["int"],
  "make_visible": true
}
```

**Responses:**
- **200**: Visibility updated successfully

### Get Hidden Invoice Items
**GET** `/invoice-items/hidden-items`

Retrieves hidden (non-visible) invoice items.

**Responses:**
- **200**: Returns paginated hidden invoice items

### Count Invoice Items
**GET** `/invoice-items/count`

Returns count of active invoice items.

**Responses:**
- **200**: Returns count of items

### Sort Invoice Items
**GET** `/invoice-items/sort`

Sorts invoice items based on specified criteria.

**Query Parameters:**
- **column_name**: `str` - Column to sort by
- **sort_order**: `str` - Sort direction (ascending, descending)

**Responses:**
- **200**: Returns sorted invoice items

### Export Invoice Items
**POST** `/invoice-items/export`

Exports selected invoice items to Excel. Takes row id (primary keys of invoice_items) table as input and fetches the complete row/record. Format them in a dataframe and write that dataframe to excel. Then it uploads that excel file to S3 bucket and returns a signed url to download that file on client's end.

**Request Body:**
```json
{
  "ids": ["int"],
  "columns": ["string"], // names of the column to be exported, only these columns will be exported and rest will be dropped
  "order_by": [{"column": "cost", "order": "desc"}]
}
```

**Responses:**
- **200**: Returns download URL for the exported file

### Export All Invoice Items
**POST** `/invoice-items/export-all`

Exports all filtered invoice items to Excel.

**Request Body:**
```json
{
  "supplier_names": ["BMW Plumbing"],
  "date_from": "2024-01-01",
  "date_to": "2024-12-31",
  "columns": ["Item", "Description", "Cost"],
  "order_by": [{"column": "amount", "order": "desc"}],
  "excluded_rows_ids": [1, 2, 3]
}
```

**Responses:**
- **200**: Returns download URL for the exported file

### Export All Unmapped Items
**POST** `/invoice-items/export-unmapped`

Exports all unmapped invoice items to Excel.

**Responses:**
- **200**: Returns download URL for exported file

### Export Selected Unmapped Items
**POST** `/invoice-items/export-selected-unmapped`

Exports selected unmapped invoice items to Excel.

**Request Body:**
```json
{
  "ids": ["int"]
}
```

**Responses:**
- **200**: Returns download URL for exported file

---

## Filters

### Get Locations
**GET** `/filter/get-locations`

Retrieves list of unique customer job locations. This endpoint is used as a dropdown on the dashboard tab.

**Responses:**
- **200**: Returns List[str] of locations
- **500**: Failed to fetch customer-job address

### Get Column Mappings
**GET** `/filter/column-mapping`

Returns mapping of database columns to frontend display names. Endpoint is used for frontend reference as some functions such as export to excel depend on specifying names of columns, so this will act as a bridge between frontend names and backend names.

**Responses:**
- **200**: Returns column mapping dictionary

### Get Column Data Paginated
**POST** `/filter/by-column-paginated`

Get paginated and searchable distinct values for a specific column to populate dropdown filters.

**Query Parameters:**
- **column_name**: `str` - Column name to get distinct values from

**Request Body:**
```json
{
  "comparison_filters": [
    {"column": "date", "operator": "gte", "value": "2000-01-01"},
    {"column": "date", "operator": "lte", "value": "2025-08-15"}
  ],
  "page": 1,
  "limit": 20,
  "search": "search term"
}
```

**Responses:**
- **200**: Returns paginated column data

### Filter Invoice Items
**POST** `/filter/invoice-items`

Filter invoice items with resource-aware execution and efficient pagination.

**Query Parameters:**
- **page**: `int` - Page number (default: 1)
- **page_size**: `int` - Items per page (default: 50)

**Request Body:**
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "supplier_id": 1,
  "customer_job": "Project Alpha",
  "item_code": "ABC123",
  "min_cost": 10.0,
  "max_cost": 100.0
}
```

**Responses:**
- **200**: Returns filtered invoice items

### Stream Filtered Items
**POST** `/filter/invoice-items/stream`

Streams filtered invoice items for large datasets.

**Query Parameters:**
- **page_size**: `int` - Items per page (default: 100)

**Request Body:**
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "supplier_id": 1
}
```

**Responses:**
- **200**: Returns streaming response

### Filter Data
**POST** `/filter`

Filter and paginate invoice items with advanced search capabilities.

**Query Parameters:**
- **page**: `int` - Page number (default: 1)
- **size**: `int` - Items per page (default: 10)

**Request Body:**
```json
{
  "filters": {
    "mpi_item": ["No Match"],
    "export_status": ["Pending", "Sent"]
  },
  "comparison_filters": [
    {
      "column": "cost",
      "operator": "gt",
      "value": 10
    },
    {
      "column": "date",
      "operator": "gte",
      "value": "2024-12-01"
    },
    {
      "column": "date",
      "operator": "lte",
      "value": "2025-02-07"
    }
  ],
  "order_by": [
    {
      "column": "cost",
      "order": "desc"
    }
  ]
}
```

**Responses:**
- **200**: Returns PaginatedInvoiceItemsResponse

### Calculate Price Differences
**POST** `/filter/price-difference`

Calculate price differences for filtered invoice items.

**Query Parameters:**
- **page**: `int` - Page number (default: 1)
- **size**: `int` - Items per page (default: 10)

**Request Body:**
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "supplier_id": 1
}
```

**Responses:**
- **200**: Returns price difference calculations

### Get Price History
**POST** `/filter/price-history`

Get price history for a specific item and vendor.

**Request Body:**
```json
{
  "item_number": "ABC123",
  "vendor": "BMW Plumbing",
  "description": "Pipe Fitting"
}
```

**Responses:**
- **200**: Returns price history data

### Download Price History
**POST** `/filter/download-price-history`

Export price history to Excel file and return download URL.

**Request Body:**
```json
{
  "item_number": "ABC123",
  "vendor": "BMW Plumbing",
  "description": "Pipe Fitting"
}
```

**Responses:**
- **200**: Returns download URL for Excel file

### Get Aggregated Statistics
**POST** `/filter/get_aggregates`

Get aggregated statistics for filtered invoice items.

**Request Body:**
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "supplier_id": 1
}
```

**Responses:**
- **200**: Returns aggregated statistics

### Get Unmapped Items
**POST** `/filter/unmapped-items`

Retrieve unique unmapped or temporary items with advanced filtering, search, and ordering.

**Query Parameters:**
- **page**: `int` - Page number (default: 1)
- **size**: `int` - Items per page (default: 10)

**Request Body:**
```json
{
  "item_type": "unmapped",
  "date_from": "2024-01-01",
  "date_to": "2024-12-31",
  "supplier_names": ["BMW Plumbing Supplies"],
  "search": "006-ST4",
  "order_by": [
    {"column": "amount", "order": "desc"},
    {"column": "supplier", "order": "asc"}
  ]
}
```

**Responses:**
- **200**: Returns paginated unmapped items

### Export All Unmapped Items
**POST** `/filter/unmapped-items/export-all`

Export unmapped items to Excel file with optional filters and exclusions.

**Request Body:**
```json
{
  "item_type": "unmapped",
  "date_from": "2024-01-01",
  "date_to": "2024-12-31",
  "supplier_names": ["BMW Plumbing Supplies"],
  "excluded_items": ["ABC123-B", "XYZ789-F"],
  "order_by": [{"column": "amount", "order": "desc"}]
}
```

**Responses:**
- **200**: Returns download URL for exported file

### Export Selected Unmapped Items
**POST** `/filter/unmapped-items/export-selected`

Export specific unmapped items by their IDs to Excel file.

**Request Body:**
```json
{
  "item_ids": ["ABC123-B", "XYZ789-F", "DEF456-G"],
  "order_by": [{"column": "amount", "order": "desc"}]
}
```

**Responses:**
- **200**: Returns download URL for exported file

---

## QuickBooks Integration

### Migrate All Invoices to QB
**POST** `/quickbooks/migrate-all`

Migrate all filtered invoices to QuickBooks with ultra-fast processing.

**Request Body:**
```json
{
  "supplier_ids": [1, 2, 3],
  "date_from": "2024-07-01",
  "date_to": "2024-07-31",
  "customer_jobs": ["ABC123", "DEF456"],
  "mpi_types": ["pipe", "fitting"],
  "priority": "high",
  "tax_distribution": true,
  "class_based_splitting": true,
  "excluded_invoice_ids": ["uuid1", "uuid2"],
  "order_by": [{"column": "date", "order": "desc"}]
}
```

**Responses:**
- **200**: Returns download URL for batch entry file
- **400**: Unmatched items or sheet names are present

### Migrate Selected Invoices to QB
**POST** `/quickbooks/migrate`

Migrate specific invoices to QuickBooks with priority control.

**Request Body:**
```json
{
  "invoice_ids": ["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"]
}
```

**Responses:**
- **200**: Returns download URL for batch entry file
- **400**: Unmatched items or sheet names are present

---

## Item Mappings

### Update Item Mappings
**POST** `/mapping`

Updates the description, sheet name and mpi codes for an item number. If mapping for item-number does not exist before, a new record is inserted. Basically the endpoint updates or creates mappings for supplier-specific item IDs to MPI codes and descriptions.

**Request Body:**
```json
{
  "supplier_id": 1,
  "mapping": [
    {
      "supplier_item_ids": "ABC123",
      "supplier_description": "PVC Pipe 2 inch",
      "mpi_type": "pipe",
      "customer_job": "ABC123",
      "is_temporary": false
    }
  ]
}
```

**Responses:**
- **200**: Mapping updated/created successfully
- **500**: Failed to update item mapping

### Search Item Across Suppliers
**GET** `/mapping/search-item`

Search for item mappings by clean item code across all suppliers.

**Query Parameters:**
- **item**: `str` - Clean item code from invoice to search for

**Responses:**
- **200**: Returns search results across suppliers

### Get Mappings by MPI Type
**GET** `/mapping/mpi_types`

Retrieves all mpi items and mpi descriptions grouped by their type/sheet name. It used to populate drop downs in data-review and mappings tabs.

**Responses:**
- **200**: Returns ItemMappingsByMpiTypeResponse
- **500**: Failed to fetch item mapping by MPI type

### Get Mappings by Supplier
**GET** `/mapping/{supplier_id}`

Retrieves all mpi items and mpi descriptions for a specific supplier.

**Path Parameters:**
- **supplier_id**: `int`

**Responses:**
- **200**: Returns List[ItemMappingsResponse]
- **500**: Failed to fetch item mapping by supplier id

---

## Google Sheets Synchronization

### Sync All Mappings
**POST** `/sync/mapping`

Manually trigger enhanced synchronization of mappings from Google Sheets.

**Responses:**
- **200**: Synchronization started successfully
- **400**: Cannot start sync: Another operation is running

### Check Sync Status
**GET** `/sync/status`

Check the status of synchronization tasks.

**Responses:**
- **200**: Returns synchronization status

### Sync No Match Mappings
**POST** `/sync/update-no-match-uidi-mappings`

Updates "No Match" mappings from Google Sheets.

**Responses:**
- **200**: No Match / UIDI update task started
- **400**: Cannot start UIDI update: Another operation is running

### Sync All Mappings (3-Step Process)
**POST** `/sync/update-all-mappings`

Updates all mappings with a 3-step process.

**Responses:**
- **200**: Full update task started
- **400**: Cannot start full update: Another operation is running

---

## Monthly Comparison

### Get Dropdown Items
**POST** `/price-comparison/dropdown-items`

Get paginated distinct items for dropdown population within a date range.

**Request Body:**
```json
{
  "from_date": "2024-07-01",
  "to_date": "2024-07-31"
}
```

**Query Parameters:**
- **query**: `str` (optional) - Search term for filtering items
- **page**: `int` - Page number (1-based)
- **size**: `int` - Number of items per page

**Responses:**
- **200**: Returns PaginatedItemInfoResponse

### Get Prices for Selected Items
**POST** `/price-comparison/selected-items`

Get price comparison data for selected items with supplier information.

**Request Body:**
```json
[
  {
    "item": "ABC123",
    "description": "Pipe Fitting 3/4 inch",
    "mpi_item": "MPI001",
    "mpi_description": "Pipe Fittings"
  }
]
```

**Query Parameters:**
- **page**: `int` - Page number (1-based)
- **size**: `int` - Number of items per page

**Responses:**
- **200**: Returns price comparison data

### Get Items by Date Range
**POST** `/price-comparison/selected-items-by-date-range`

Retrieve items by date range with exclusions.

**Request Body:**
```json
{
  "from_date": "2024-07-01",
  "to_date": "2024-07-31",
  "unselected_items": ["ITEM001", "ITEM002"]
}
```

**Query Parameters:**
- **page**: `int` - Page number (1-based)
- **size**: `int` - Number of items per page

**Responses:**
- **200**: Returns items within date range

---

## Statement Management

### Get Statement Invoice Data
**GET** `/statements/invoice-data`

Get statement invoice data with filters and pagination.

**Query Parameters:**
- **search**: `str` (optional) - Search term for invoice numbers
- **from_date**: `str` (optional) - Start date in DD/MM/YYYY format
- **to_date**: `str` (optional) - End date in DD/MM/YYYY format
- **supplier_names**: `List[str]` (optional) - List of supplier names or IDs
- **status**: `str` (optional) - Filter by status
- **page**: `int` - Page number (default: 1)
- **page_size**: `int` - Items per page (default: 20)

**Responses:**
- **200**: Returns paginated statement invoice data
- **400**: Invalid date format or parameters

### Download Statement PDF
**GET** `/statements/download`

Download statement PDF for a specific month.

**Query Parameters:**
- **statement_id**: `int` - ID of the statement to download

**Responses:**
- **200**: Returns download URL for statement PDF
- **404**: Statement not found

### Reprocess Statement
**POST** `/statements/reprocess`

Reprocess a statement for a specific month or bulk reprocess multiple statements.

**Query Parameters:**
- **statement_id**: `str` (optional) - ID of the statement to reprocess
- **supplier_name**: `str` (optional) - Supplier name filter for bulk reprocessing
- **max_statements**: `int` - Maximum number of statements to reprocess in bulk (1-1000, default: 100)

**Responses:**
- **200**: Statement reprocessing started
- **400**: Invalid parameters

### Get Aggregated Monthly Statistics
**GET** `/statements/aggregate-monthly`

Get aggregated statistics for statement invoices.

**Query Parameters:**
- **from_date**: `str` (optional) - Start date in DD/MM/YYYY format
- **to_date**: `str` (optional) - End date in DD/MM/YYYY format
- **supplier_names**: `List[str]` (optional) - List of supplier names or IDs
- **status**: `str` (optional) - Filter by status

**Responses:**
- **200**: Returns aggregated statistics
- **400**: Invalid date format or parameters

### Delete Statement
**DELETE** `/statements/{statement_id}`

Delete a specific statement.

**Path Parameters:**
- **statement_id**: `int` - ID of the statement to delete

**Responses:**
- **200**: Statement deleted successfully
- **404**: Statement not found

---

## Supplier Management

### Get Supplier List
**GET** `/supplier`

Get all suppliers in the system.

**Responses:**
- **200**: Returns list of suppliers with ID and name mapping

---

## Customer Job Management

### Update Customer Job Mappings
**POST** `/customer-job/update-mappings`

Update customer job mappings from an Excel file.

**Form Data:**
- **file**: `UploadFile` (Excel file)

**Responses:**
- **200**: Customer job mappings updated successfully
- **400**: Only Excel files are allowed
- **422**: Value error in file processing
- **500**: Unexpected error occurred while processing the file

---

## Natural Language Q/A System

### Process Natural Language Query
**POST** `/qa/query`

Process a natural language question about the MPI backend database using AI-powered query processing.

**Request Body:**
```json
{
  "question": "Show me all invoices from BMW Plumbing Supplies in July 2024"
}
```

**Responses:**
- **200**: Returns natural language answer
- **400**: Invalid question format or length
- **500**: Internal server error during processing

**Features:**
- Converts natural language to SQL
- Executes query safely (SELECT only)
- Returns natural language answer only
- SQL injection protection
- Query result limiting (max 50 rows)
- Input validation and sanitization
- Timeout protection for long-running queries

---

## Health Check Endpoints

### Basic Health Check
**GET** `/health`

Basic API health check endpoint.

**Responses:**
- **200**: Returns health status

### Database Pool Health
**GET** `/health/db-pool`

Database connection pool health check.

**Responses:**
- **200**: Returns database pool status

### System Health
**GET** `/health/system`

System resources health check.

**Responses:**
- **200**: Returns system resource status

### Jobs Health
**GET** `/health/jobs`

Background jobs health check.

**Responses:**
- **200**: Returns background jobs status

### Cache Health
**GET** `/health/cache`

Cache system health check.

**Responses:**
- **200**: Returns cache status

### Performance Health
**GET** `/health/performance`

Performance metrics health check.

**Responses:**
- **200**: Returns performance metrics

### Reset Job
**POST** `/health/jobs/{job_id}/reset`

Reset a specific background job.

**Path Parameters:**
- **job_id**: `str` - ID of the job to reset

**Responses:**
- **200**: Job reset successfully
- **404**: Job not found

---

## Error Handling

### HTTP Status Codes
The API uses standard HTTP status codes:
- **200 OK**: Request successful
- **201 Created**: Resource created successfully
- **400 Bad Request**: Invalid request data
- **401 Unauthorized**: Authentication required
- **403 Forbidden**: Insufficient permissions
- **404 Not Found**: Resource not found
- **422 Unprocessable Entity**: Validation error
- **500 Internal Server Error**: Server error

### Error Response Format
All error responses follow a consistent format:
```json
{
  "detail": "Error message describing what went wrong",
  "error_code": "ERROR_TYPE",
  "timestamp": "2024-07-15T10:30:00Z"
}
```

---

## Rate Limiting

The API implements rate limiting:
- **General endpoints**: 100 requests per minute per user
- **File upload endpoints**: 10 requests per minute per user
- **Background task endpoints**: 5 requests per minute per user
- **Chatbot endpoints**: 20 requests per minute per user
- **QuickBooks endpoints**: 5 requests per minute per user

Rate limit headers are included in responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Time when the rate limit resets

---

## Authentication

All protected endpoints require a JWT Bearer token:
- **Authorization Header**: `Authorization: Bearer <token>`
- **Token Expiry**: 1 month
- **Token Format**: JWT (JSON Web Token)

---

*This documentation is automatically updated with each API change. Last updated: January 15, 2025*