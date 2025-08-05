# MPI Backend API Documentation

## Table of Contents
1. [Authentication](#authentication)
2. [Health Check](#health-check)
3. [Invoice Management](#invoice-management)
4. [Invoice Items](#invoice-items)
5. [Filters](#filters)
6. [QuickBooks Integration](#quickbooks-integration)
7. [Item Mappings](#item-mappings)
8. [Sync Mappings](#sync-mappings)
9. [Monthly Comparison](#monthly-comparison)
10. [Statements](#statements)
11. [Supplier Management](#supplier-management)
12. [Customer Job Mapping](#customer-job-mapping)

---

## Authentication

### Sign In
**POST** `/signin`

Authenticates a user and returns a JWT token. The expiry of the JWT token is for a month. All protected endpoints require this token in the Authorization header.

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

**Usage:** Include the returned JWT token in the Authorization header for all subsequent requests:
```
Authorization: Bearer <your_jwt_token>
```

---

## Health Check

### Health Check
**GET** `/health`

Simple health check endpoint to verify the API is running.

**Responses:**
- **200**: Returns `{"res": true}`

---

## Invoice Management

### Get Invoices
**GET** `/invoice`

Retrieves a paginated list of invoices with optional filters. The endpoint queries the `invoices` table.

**Query Parameters:**
- `supplier_id` (List[int]): Filter by supplier IDs, to get invoices from all suppliers set it to 0
- `from_date` (date): Start date filter
- `to_date` (date): End date filter
- `status` (str): Filter by status (all, processed, unprocessed)
- `job_location` (str): Filter by job location / customer job
- `export_status` (str): Filter by export status [Pending, Sent]
- `page` (int): Page number (default: 1)
- `size` (int): Invoice records per page (default: 10, max: 100)

**Responses:**
- **200**: Returns `PaginatedInvoiceResponse`
- **404**: No Records Found

**Note:** All the data being displayed on the dashboard table is populated using this endpoint.

### Get All Invoices
**GET** `/invoice/all`

Retrieves all invoices without pagination.

**Responses:**
- **200**: Returns list of all invoices
- **500**: Error occurred while fetching invoices

**Note:** Currently not used on frontend anywhere, but can be used for debugging.

### Download Invoice
**GET** `/invoice/download`

Downloads/Renders PDF file of specific invoice. Based on provided invoice-id (a unique UUID which serves as primary key to invoices table and is generated during the processing of invoice first time) it runs a query to find out supplier. Then it constructs the S3 bucket path and generates the signed URL to download or render the file.

**Query Parameters:**
- `invoice_id` (str): ID of the invoice to download

**Responses:**
- **200**: Returns download link
- **404**: Couldn't fetch requested file

**Note:** This endpoint is integrated on the dashboard tab to VIEW invoices.

### Upload Invoice
**POST** `/invoice/upload`

The system can ingest invoices through two ways: 1) obtained through email 2) Directly uploaded through upload tab. This endpoint receives the directly uploaded invoice and processes it.

**Form Data:**
- `supplier_id` (int): Supplier ID
- `file` (UploadFile): PDF file only

**Responses:**
- **200**: Invoice processed successfully
- **400**: Only PDF files are allowed

**Note:** Integrated on the upload tab on frontend.

### Process Invoice Again
**POST** `/invoice/process`

If the user wants to reprocess an invoice, this endpoint enables that. It takes in invoice-id (primary identifier of invoice), using that invoice-id it gets its supplier and then constructs the S3 bucket file path where the invoice is stored. Using the URL it downloads the PDF file of the invoice and writes it to local storage. Then deletes the previous invoice items rows and invoice entry from invoice & invoice_items table. Then runs the convert and combine workflow again and inserts new data in the database.

**Query Parameters:**
- `invoice_id` (str): ID of the invoice to reprocess

**Responses:**
- **200**: Invoice reprocessing successful
- **404**: Couldn't fetch requested invoice

**Note:** Integrated on the Dashboard tab on frontend and is triggered by selecting an invoice and clicking on process again.

---

## Invoice Items

### Get Invoice Items
**GET** `/invoice-items/all`

Retrieves a list of all invoice items sorted by id in descending order.

**Responses:**
- **200**: Returns `Page[InvoiceItems]`
- **404**: No Records Found

**Note:** Deprecated, not directly used integrated in web app. But can be used for debugging.

### Get Invoice Items by ID
**GET** `/invoice-items/id`

Retrieves invoice items for a specific invoice. Indirectly used in migrate to quick books endpoint.

**Query Parameters:**
- `invoice_id` (UUID, optional): Filter by invoice ID

**Responses:**
- **200**: Returns `Page[InvoiceItems]`
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

### Export Invoice Items
**POST** `/invoice-items/export`

Exports selected invoice items to Excel. Takes row id (primary keys of invoice_items) table as input and fetches the complete row/record. Formats them in a dataframe and writes that dataframe to Excel. Then it uploads that Excel file to S3 bucket and returns a signed URL to download that file on client's end.

**Request Body:**
```json
{
  "ids": ["int"],
  "columns": ["string"] // names of the column to be exported, only these columns will be exported and rest will be dropped
}
```

**Responses:**
- **200**: Returns download URL for the exported file

---

## Filters

### Get Locations
**GET** `/filter/get-locations`

Retrieves list of unique customer job locations. This endpoint is used as a dropdown on the dashboard tab.

**Responses:**
- **200**: Returns `List[str]` of locations
- **500**: Failed to fetch customer-job address

### Get Column Mappings
**GET** `/filter/column-mapping`

Returns mapping of database columns to frontend display names. Endpoint is used for frontend reference as some functions such as export to Excel depend on specifying names of columns, so this will act as a bridge between frontend names and backend names.

**Responses:**
- **200**: Returns column mapping dictionary

### Filter Data
**POST** `/filter`

Retrieves filtered invoice items based on specified criteria. It supports three types of filters:
1. Value based filtering (e.g., mpi_item = "No Match")
2. Comparison based/quantitative filtering for numerical columns (e.g., Cost > 15, date = "2025-01-20")
3. Order based (sort results based ascending or descending order of column after applying above filter)

**Request Body:**
```json
{
    "filters": {
        "mpi_item": [
            "No Match"
        ],
        "export_status": [
            "Pending",
            "Sent"
        ]
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

**Query Parameters:**
- `page` (int): Page number (default: 1)
- `size` (int): Items per page (default: 10) - use 0 to fetch all records

**Responses:**
- **200**: Returns `PaginatedInvoiceItemsResponse`

### Get Price History
**POST** `/filter/price-history`

Based on item numbers, it provides price history for specified items. It gives insights on all the time that particular item was bought, from which vendor and for what price.

---

## QuickBooks Integration

### Migrate All Invoices to QB
**POST** `/quickbooks/migrate-all`

Migrates all filtered invoices to QuickBooks with ultra-fast processing and guaranteed status updates. This endpoint is optimized for bulk operations and handles large datasets efficiently with priority control over background jobs.

**Request Body:**
```json
{
  "filter_criteria": "object", // same as /filter endpoint
  "excluded_invoice_ids": ["UUID"],
  "order_by": [{"column": "date", "order": "desc"}]
}
```

**Background Tasks:**
- **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing

**Responses:**
- **200**: Returns presigned S3 URL for downloading the QuickBooks Excel file
- **400**: No invoice IDs found for export or unmatched items/sheet names present
- **500**: Processing or upload error

**Process Flow:**
1. Applies filter criteria to get matching invoice IDs
2. Excludes specified invoice IDs if provided
3. Pauses all background jobs for absolute priority
4. Processes invoices with ultra-fast QuickBooks migration
5. Generates Excel file in QuickBooks format with tax distribution
6. Updates export statuses to 'Sent'
7. Resumes background jobs
8. Returns download URL

**Priority Control:**
- **ABSOLUTE PRIORITY**: Pauses ALL background jobs during processing
- Ensures maximum system resources for QuickBooks migration
- Automatic resume of background jobs after completion
- Critical priority context management

**Performance Features:**
- Ultra-fast data processing with vectorized operations
- Optimized database queries for large datasets
- Fast Excel generation and S3 upload
- Immediate status updates for guaranteed consistency

**Status Updates:**
- Invoice-level export status updated to 'Sent'
- Item-level export status updated to 'Sent'
- Immediate updates for guaranteed consistency
- Comprehensive status reporting

### Migrate Selected Invoices to QB
**POST** `/quickbooks/migrate`

Migrates specific invoices to QuickBooks with priority control and guaranteed status updates. Supports both individual invoice selection and bulk operations with flexible request formats.

**Request Body:**
Supports multiple formats:
```json
// Array of UUIDs
["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"]

// Object with invoice_ids
{
  "invoice_ids": ["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"]
}

// Empty/None - exports all invoices
```

**Query Parameters:**
- `order_by` (`list`, optional): Sorting criteria for the export

**Background Tasks:**
- **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing

**Responses:**
- **200**: Returns presigned S3 URL for downloading the QuickBooks Excel file
- **400**: No valid invoice IDs provided
- **500**: Processing or upload error

**Process Flow:**
1. Validates and cleans invoice IDs
2. Pauses background jobs for priority processing
3. Processes invoices with ultra-fast QuickBooks migration
4. Generates Excel file in QuickBooks format with tax distribution
5. Updates export statuses to 'Sent' immediately
6. Resumes background jobs
7. Returns download URL

**Priority Control:**
- Pauses background jobs during processing
- Ensures system resources for QuickBooks migration
- Automatic resume of background jobs after completion
- Safe priority context management

**Performance Features:**
- Ultra-fast data processing with vectorized operations
- Optimized database queries
- Fast Excel generation and S3 upload
- Immediate status updates for guaranteed consistency

**Validation:**
- Removes duplicate and null invoice IDs
- Validates UUID format
- Limits to 5000 invoices for performance
- Comprehensive error handling

**Status Updates:**
- Invoice-level export status updated to 'Sent'
- Item-level export status updated to 'Sent'
- Immediate updates for guaranteed consistency
- Detailed status reporting

---

## Item Mappings

### Update Item Mappings
**POST** `/mapping`

Updates the description, sheet name and MPI codes for an item number. If mapping for item-number does not exist before, a new record is inserted. Basically the endpoint updates or creates mappings for supplier-specific item IDs to MPI codes and descriptions.

**Responses:**
- **200**: Mapping updated/created successfully
- **500**: Failed to update item mapping

### Get Mappings by MPI Type
**GET** `/mapping/mpi_types`

Retrieves all MPI items and MPI descriptions grouped by their type/sheet name. It is used to populate dropdowns in data-review and mappings tabs.

**Responses:**
- **200**: Returns `ItemMappingsByMpiTypeResponse`
- **500**: Failed to fetch item mapping by MPI type

### Get Mappings by Supplier
**GET** `/mapping/{supplier_id}`

Retrieves all MPI items and MPI descriptions for a specific supplier.

**Path Parameters:**
- `supplier_id` (int): Supplier ID

**Responses:**
- **200**: Returns `List[ItemMappingsResponse]`
- **500**: Failed to fetch item mapping by supplier id

---

## Sync Mappings

### Sync Mapping
**POST** `/sync/mapping`

Manually trigger enhanced synchronization of mappings from Google Sheets. This endpoint provides enhanced synchronization with better handling of temporary and permanent mappings. If a sync task is already running, it returns a detailed status message.

**Background Tasks:**
- **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing

**Responses:**
- **200**: Returns `SyncMappingsResponse` with success status, message, and timestamp
- **401**: Unauthorized (invalid or missing token)
- **500**: Database error or sync controller failure

**Response Example - Success:**
```json
{
  "success": true,
  "message": "Sync task started manually",
  "timestamp": "2024-12-19T14:30:25.123456"
}
```

**Response Example - Already Running:**
```json
{
  "success": false,
  "message": "Cannot start sync: Google Sheets Sync is currently running",
  "timestamp": "2024-12-19T14:30:25.123456"
}
```

**Process Flow:**
1. Checks current sync status
2. If sync is running, returns detailed blocking job information
3. If no sync is running, starts enhanced sync in background
4. Returns immediate response with task status

**Sync Operations:**
- **Google Sheets Sync**: Basic synchronization from Google Sheets
- **UIDI Update**: Updates No Match / UIDI mappings (3-step process)
- **Full Update**: Updates all mappings (3-step process)

**Blocking Job Detection:**
- Detects currently running sync operations
- Provides detailed step-by-step progress information
- Prevents multiple sync operations from running simultaneously
- Returns specific blocking job descriptions

**Background Processing:**
- Uses GoogleSheetSyncController for enhanced sync
- Runs in background to prevent API blocking
- Provides detailed operation tracking
- Handles temporary and permanent mapping updates

### Get Sync Status
**GET** `/sync/status`

Retrieves the current status of all synchronization operations including running tasks, completed operations, and timestamps. Provides detailed information about the current operation and its progress through multi-step processes.

**Responses:**
- **200**: Returns current sync status with detailed operation information
- **401**: Unauthorized (invalid or missing token)
- **500**: Database error or sync controller failure

**Response Example - Idle:**
```json
{
  "status": "idle",
  "current_operation": "No operation in progress",
  "last_sync_time": "2024-12-19T14:30:25.123456",
  "last_no_match_uidi_update": "2024-12-19T14:25:10.123456",
  "last_full_update": "2024-12-19T14:20:15.123456"
}
```

**Response Example - Running:**
```json
{
  "status": "running",
  "current_operation": "Updating No Match / UIDI Mappings (Step 2/3: Syncing Temporary Mappings)",
  "last_sync_time": "2024-12-19T14:30:25.123456",
  "last_no_match_uidi_update": "2024-12-19T14:25:10.123456",
  "last_full_update": "2024-12-19T14:20:15.123456"
}
```

**Response Fields:**
- **status** (`str`): "running" or "idle"
- **current_operation** (`str`): Detailed description of current operation
- **last_sync_time** (`str`): Timestamp of last basic sync
- **last_no_match_uidi_update** (`str`): Timestamp of last UIDI update
- **last_full_update** (`str`): Timestamp of last full update

**Operation Types:**
- **Google Sheets Sync**: Basic synchronization from Google Sheets
- **UIDI Update**: 3-step process for No Match / UIDI mappings
- **Full Update**: 3-step process for all mappings

**Step-by-Step Progress:**
- **Step 1**: Syncing Google Sheets
- **Step 2**: Syncing Temporary Mappings
- **Step 3**: Updating Items

**Status Detection:**
- Real-time operation status checking
- Detailed sub-operation tracking
- Progress indication for multi-step processes
- Historical timestamp tracking

### Update No Match UIDI Mappings
**POST** `/sync/update-no-match-uidi-mappings`

Initiates a specialized synchronization process that targets items with "No Match" or UIDI mappings. This 3-step process syncs data from Google Sheets and then updates specific item mappings to improve data quality and mapping accuracy.

**Background Tasks:**
- **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing

**Responses:**
- **200**: Returns response with status, message, and timestamp
- **401**: Unauthorized (invalid or missing token)
- **500**: Database error or sync controller failure

**Response Example - Success:**
```json
{
  "status": "success",
  "message": "No Match / UIDI update task has been started in the background",
  "timestamp": "2024-12-19T14:30:25.123456"
}
```

**Response Example - Already Running:**
```json
{
  "status": "error",
  "message": "Cannot start UIDI update: UIDI Update (Step 2/3: Syncing Temporary Mappings) is currently running",
  "timestamp": "2024-12-19T14:30:25.123456"
}
```

**Target Items:**
- **No Match Items**: Items where mpi_item is "no match" (case insensitive)
- **UIDI Items**: Items where mpi_item starts with "UIDI"
- **Empty Items**: Items where mpi_item is None or empty

**3-Step Process:**
1. **Step 1**: Sync Google Sheets data
2. **Step 2**: Sync temporary mappings
3. **Step 3**: Update UIDI items with new mappings

**Mapping Logic:**
- Searches ItemsMapping table for matches
- Uses org_item (item) and org_description (description) fields
- Applies enhanced mapping algorithms
- Updates both temporary and permanent mappings

**Process Flow:**
1. Checks if any sync operation is currently running
2. If running, returns detailed blocking job information
3. If available, starts UIDI update in background
4. Returns immediate response with task status

**Background Processing:**
- Runs in background to prevent API blocking
- Uses GoogleSheetSyncController for enhanced processing
- Provides detailed operation tracking
- Handles large datasets efficiently

### Update All Mappings
**POST** `/sync/update-all-mappings`

Initiates a comprehensive synchronization process that updates all invoice items with the latest mappings from Google Sheets. This 3-step process is useful for propagating mapping changes across the entire system after bulk updates or data migrations.

**Background Tasks:**
- **background_tasks** (`BackgroundTasks`): FastAPI background tasks for async processing

**Responses:**
- **200**: Returns response with status, message, and timestamp
- **401**: Unauthorized (invalid or missing token)
- **500**: Database error or sync controller failure

**Response Example - Success:**
```json
{
  "status": "success",
  "message": "Full update task has been started in the background",
  "timestamp": "2024-12-19T14:30:25.123456"
}
```

**Response Example - Already Running:**
```json
{
  "status": "error",
  "message": "Cannot start full update: Full Update (Step 2/3: Syncing Temporary Mappings) is currently running",
  "timestamp": "2024-12-19T14:30:25.123456"
}
```

**3-Step Process:**
1. **Step 1**: Sync Google Sheets data
2. **Step 2**: Sync temporary mappings
3. **Step 3**: Update all items with new mappings

**Scope:**
- **All Invoice Items**: Updates every invoice item in the system
- **Comprehensive Coverage**: Ensures all items have latest mappings
- **Bulk Processing**: Handles large datasets efficiently
- **Data Consistency**: Maintains mapping consistency across system

**Use Cases:**
- After bulk mapping table changes
- Data migration completion
- System-wide mapping updates
- Data quality improvement initiatives
- Mapping table restructuring

**Process Flow:**
1. Checks if any sync operation is currently running
2. If running, returns detailed blocking job information
3. If available, starts full update in background
4. Returns immediate response with task status

**Background Processing:**
- Runs in background to prevent API blocking
- Uses GoogleSheetSyncController for enhanced processing
- Provides detailed operation tracking
- Handles large datasets efficiently

**Performance Considerations:**
- May take significant time for large datasets
- Processes all invoice items in the system
- Uses optimized batch processing
- Provides progress tracking for long operations

---

## Monthly Comparison

### Get Dropdown Items
**POST** `/price-comparison/dropdown-items`

Get paginated distinct items that were used within the specified date range. If a query parameter is provided, the endpoint will perform a search and return filtered results.

**Request Body:**
```json
{
  "from_date": "2024-01-01",
  "to_date": "2024-12-31"
}
```

**Query Parameters:**
- `query` (str, optional): Optional search term for filtering items
- `page` (int): Page number (1-based, default: 1)
- `size` (int): Number of items per page (1-100, default: 10)

**Responses:**
- **200**: Returns `PaginatedItemInfoResponse`

### Get Selected Items Prices
**POST** `/price-comparison/selected-items`

Get the most recent prices for the specified items with supplier information. Returns a paginated list of items with their cheapest price and all supplier options.

**Request Body:**
```json
[
  {
    "mpi_item": "string",
    "mpi_description": "string"
  }
]
```

**Query Parameters:**
- `page` (int): Page number (1-based, default: 1)
- `size` (int): Number of items per page (1-100, default: 10)

**Responses:**
- **200**: Returns `PaginatedEnrichedItemResponse`

### Get Items by Date Range
**POST** `/price-comparison/selected-items-by-date-range`

Get items and their prices within a specific date range with exclusion capabilities.

**Request Body:**
```json
{
  "from_date": "2024-01-01",
  "to_date": "2024-12-31",
  "excluded_suppliers": ["supplier1", "supplier2"],
  "excluded_items": ["item1", "item2"]
}
```

**Query Parameters:**
- `page` (int): Page number (1-based, default: 1)
- `size` (int): Number of items per page (1-100, default: 10)

**Responses:**
- **200**: Returns `PaginatedEnrichedItemResponse`

---

## Statements

### Get Statement Invoice Data
**GET** `/statements/invoice-data`

Get statement invoice data with filters and pagination. Returns invoice data from statements including invoice details, statement information, and reconciliation status.

**Query Parameters:**
- `search` (str, optional): Search term to look for in invoice numbers (full or partial match)
- `from_date` (str, optional): Start date filter in DD/MM/YYYY format (filters by invoice_date)
- `to_date` (str, optional): End date filter in DD/MM/YYYY format (filters by invoice_date)
- `supplier_names` (List[str], optional): Filter by list of supplier names (partial match supported), supplier IDs (numeric), ["All"] for all suppliers, or ["0"] for all suppliers
- `status` (str, optional): Filter by reconciliation status ('Processed', 'Failed', 'Unlisted', 'Missing System', 'Missing Statement', 'All')
- `page` (int): Page number for pagination (starts from 1, default: 1)
- `page_size` (int): Number of items per page (1-100, default: 20)

**Responses:**
- **200**: Returns paginated statement invoice data

### Download Statement PDF
**GET** `/statements/download`

Download the PDF file for a specific statement.

**Query Parameters:**
- `statement_id` (int): ID of the statement to download

**Responses:**
- **200**: Returns download URL for the statement PDF
- **404**: Statement not found

### Reprocess Statement
**POST** `/statements/reprocess`

Reprocess a specific statement or bulk reprocess statements for a supplier.

**Query Parameters:**
- `statement_id` (str, optional): ID of the statement to reprocess (optional)
- `supplier_name` (str, optional): Supplier name filter for bulk reprocessing (optional)
- `max_statements` (int): Maximum number of statements to reprocess in bulk (1-1000, default: 100)

**Responses:**
- **200**: Returns reprocessing status and results

### Delete Statement
**DELETE** `/statements/{statement_id}`

Delete a specific statement from the system.

**Path Parameters:**
- `statement_id` (int): ID of the statement to delete

**Responses:**
- **200**: Statement deleted successfully
- **404**: Statement not found

---

## Supplier Management

### Get Supplier List
**GET** `/supplier`

Retrieves a complete list of all suppliers from the database. Returns a dictionary mapping supplier IDs to supplier names for easy lookup and integration with other parts of the system.

**Authentication:**
- **token** (`str`): JWT Bearer token required for access

**Responses:**
- **200**: Returns dictionary mapping supplier IDs to supplier names
- **401**: Unauthorized (invalid or missing token)
- **500**: Database error or server failure

**Response Example:**
```json
{
  "1": "ABC Plumbing Supplies",
  "2": "XYZ Hardware Store",
  "3": "World Wide Plumbing",
  "4": "Gotham Supply Co"
}
```

**Response Format:**
- **Key**: Supplier ID (string)
- **Value**: Supplier name (string)

**Process Flow:**
1. Authenticates user with JWT token
2. Queries database for all suppliers
3. Converts supplier objects to dictionary format
4. Returns supplier ID to name mapping

**Performance Features:**
- Direct database query for all suppliers
- Efficient dictionary conversion
- Minimal data processing
- Fast response time

**Use Cases:**
- Populating supplier dropdown menus
- Supplier selection in forms
- Data validation and lookup
- Integration with other API endpoints

**Notes:**
- Returns all suppliers regardless of status
- Supplier IDs are converted to strings for consistency
- Empty dictionary returned if no suppliers exist
- Logs successful retrieval with count
- Comprehensive error logging for debugging

---

## Customer Job Mapping

### Update Customer Job Mappings
**POST** `/customer-job/update-mappings`

Updates customer job mappings from an Excel file. The Excel file should have two columns:
- `customer_job`: The original customer job name
- `updated_customer_job`: The new customer job name

**Form Data:**
- `file` (UploadFile): Excel file (.xlsx, .xls, .xlsm)

**Responses:**
- **200**: Returns success status and message
- **400**: Only Excel files are allowed
- **422**: Value error in file processing
- **500**: Unexpected error occurred while processing the file

---

## Data Models

### Common Response Models

#### PaginatedInvoiceResponse
```json
{
  "items": [Invoice],
  "total": "int",
  "page": "int",
  "size": "int",
  "pages": "int"
}
```

#### PaginatedInvoiceItemsResponse
```json
{
  "items": [InvoiceItems],
  "total": "int",
  "page": "int",
  "size": "int",
  "pages": "int"
}
```

#### SyncMappingsResponse
```json
{
  "success": "bool",
  "message": "string",
  "timestamp": "datetime"
}
```

#### ItemMappingsByMpiTypeResponse
```json
{
  "mpi_types": {
    "type_name": {
      "mpi_items": ["string"],
      "mpi_descriptions": ["string"]
    }
  }
}
```

#### ItemMappingsResponse
```json
{
  "id": "int",
  "supplier_id": "int",
  "item_number": "string",
  "mpi_item": "string",
  "mpi_description": "string",
  "sheet_name": "string"
}
```

---

## Error Handling

All endpoints follow standard HTTP status codes:

- **200**: Success
- **400**: Bad Request - Invalid input data
- **401**: Unauthorized - Missing or invalid authentication token
- **403**: Forbidden - Wrong login details
- **404**: Not Found - Resource not found
- **422**: Unprocessable Entity - Validation error
- **500**: Internal Server Error - Server-side error

## Authentication

All protected endpoints require a JWT Bearer token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

The JWT token can be obtained through the `/signin` endpoint and is valid for one month.

## Rate Limiting

Currently, no explicit rate limiting is implemented, but it's recommended to implement appropriate rate limiting for production use.

## File Upload Limits

- **PDF Files**: Maximum size depends on server configuration
- **Excel Files**: Maximum size depends on server configuration
- **Supported Formats**: PDF for invoices, Excel (.xlsx, .xls, .xlsm) for mappings

## Notes

1. All date parameters should be in ISO format (YYYY-MM-DD) unless otherwise specified
2. UUID parameters should be valid UUID strings
3. Pagination starts from page 1
4. File uploads should use multipart/form-data encoding
5. All responses are in JSON format
6. The API uses FastAPI framework with automatic OpenAPI documentation generation 