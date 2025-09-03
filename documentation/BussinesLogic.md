# Complete MPI Backend Business Logic Documentation

## Table of Contents
1. [Application Overview](#application-overview)
2. [Database Architecture](#database-architecture)
3. [File Processing Workflow](#file-processing-workflow)
4. [MPI Item Mapping & Classification](#mpi-item-mapping--classification)
5. [Duplication Detection & Handling](#duplication-detection--handling)
6. [API Endpoints & Business Logic](#api-endpoints--business-logic)
7. [Background Tasks & Scheduling](#background-tasks--scheduling)
8. [QuickBooks Integration](#quickbooks-integration)
9. [Data Flow & Processing Logic](#data-flow--processing-logic)
10. [Error Handling & Recovery](#error-handling--recovery)

---

## Application Overview

The MPI Backend is a comprehensive invoice processing system designed to:
- Convert PDF invoices to Excel format
- Extract and process invoice data
- Map supplier items to MPI (Master Product Index) codes
- Handle duplicate detection and prevention
- Export data to QuickBooks format
- Manage monthly statements and reconciliation

### Core Components
- **FastAPI Application**: RESTful API with comprehensive endpoints
- **Database Layer**: PostgreSQL with SQLAlchemy ORM
- **File Processing**: PDF to Excel conversion with supplier-specific logic
- **Background Tasks**: Automated processing and synchronization
- **S3 Integration**: File storage and retrieval
- **QuickBooks Export**: Data export in QuickBooks-compatible format

---

## Database Architecture

### Core Models

#### 1. Invoice Model
```python
class Invoice(Base):
    __tablename__ = 'invoices'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    date = Column(Date)
    filename = Column(String)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
    status = Column(String)  # PROCESSING, PROCESSED, FAILED
    storage_path = Column(String)
    is_exported = Column(String, default="Pending")
    
    # Relationships
    items = relationship("InvoiceItem", back_populates="invoice")
    supplier_fk = relationship("Supplier", back_populates="supplier")
```

#### 2. InvoiceItem Model
```python
class InvoiceItem(Base):
    __tablename__ = 'invoice_items'
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    sheet_name = Column(String)  # Google Sheet name for mapping
    mpi_item = Column(String, default='No Match')  # MPI code
    mpi_description = Column(String, default='No Match')
    item = Column(String)  # Original supplier item code
    description = Column(String)
    qty = Column(Integer)
    cost = Column(Float)
    amount = Column(String)
    date = Column(Date)
    ref_no = Column(String)  # Invoice reference number
    po_number = Column(String)
    customer_job = Column(String)
    bill = Column(String)
    vendor = Column(String)
    class_ = Column(String)  # Item class
    account = Column(String, default='')  # QuickBooks account
    memo = Column(String)
    buyer = Column(String)
    date_added = Column(Date)
    export_status = Column(String, default="Pending")
    invoice_id = Column(UUID, ForeignKey('invoices.id'))
    is_active = Column(Boolean, default=True)  # Soft delete flag
```

#### 3. Supplier Model
```python
class Supplier(Base):
    __tablename__ = 'suppliers'
    
    id = Column(Integer, primary_key=True)
    supplier_name = Column(String)
    
    # Relationships
    supplier = relationship("Invoice", back_populates="supplier_fk")
    mpi_mapping = relationship("ItemsMapping", back_populates="mpi_mapping_fk")
    unmapped_items = relationship("UnmappedItems", back_populates="unmapped_items_fk")
```

#### 4. ItemsMapping Model
```python
class ItemsMapping(Base):
    __tablename__ = 'supplier_item_mappings'
    
    id = Column(Integer, primary_key=True)
    google_sheet_name = Column(String)  # Source Google Sheet
    mpi_code = Column(String)  # Target MPI code
    description = Column(String)  # MPI description
    supplier_item_ids = Column(String)  # Original supplier item code
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
```

#### 5. ItemClassification Model
```python
class ItemClassification(Base):
    __tablename__ = 'item_classification'
    
    id = Column(Integer, primary_key=True)
    item = Column(String)  # Item name/description
    category = Column(String)  # M, E, A, L categories
```

#### 6. TemporaryItemMapping Model
```python
class TempItemMapping(Base):
    __tablename__ = 'temporary_item_mappings'
    
    id = Column(Integer, primary_key=True)
    original_item = Column(String)
    original_description = Column(String)
    sheet_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### 7. UnmappedItems Model
```python
class UnmappedItems(Base):
    __tablename__ = 'unmapped_items'
    
    id = Column(Integer, primary_key=True)
    google_sheet_name = Column(String)
    mpi_code = Column(String)
    description = Column(String)
    supplier_item_ids = Column(String)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
```

#### 8. CustomerJobMapping Model
```python
class CustomerJobMapping(Base):
    __tablename__ = 'customer_job_mappings'
    
    id = Column(Integer, primary_key=True)
    customer_job = Column(String)  # Original job name
    updated_customer_job = Column(String)  # Standardized job name
```

#### 9. Monthly Statement Models
```python
class PlumbingSupplier(Base):
    __tablename__ = "plumbing_suppliers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    is_active = Column(String, default="Active")

class PlumbingStatement(Base):
    __tablename__ = "plumbing_statements"
    
    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("plumbing_suppliers.id"))
    statement_date = Column(Date)
    account_number = Column(String(50))
    total_amount = Column(Numeric(12, 2), default=0)
    total_invoices = Column(Integer, default=0)
    pdf_filename = Column(String(255))

class PlumbingInvoice(Base):
    __tablename__ = "plumbing_invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("plumbing_statements.id"))
    invoice_number = Column(String(50))
    invoice_date = Column(Date)
    customer_po = Column(String(100))
    original_amount = Column(Numeric(10, 2))
    payment_date = Column(Date)
    amount_paid = Column(Numeric(10, 2))
    balance = Column(Numeric(10, 2))
```

---

## File Processing Workflow

### 1. PDF to Excel Conversion Process

#### Main Extractor Logic (`main_extractor.py`)
The system uses a sophisticated PDF extraction process with supplier-specific handling:

```python
def extract_data(filename, output_path, supplier):
    # 1. Check for multiple invoices in single file
    if get_pages(filename) > 1 and supplier not in single_invoice_supplier:
        if check_for_unique_invoices(filename, supplier):
            splited_filepath = split_multiple_invoices(filename, supplier)
            return splited_filepath
    
    # 2. Supplier-specific processing
    if supplier == 'World Wide Plumbing':
        tables = tabula.read_pdf(filename, pages='all', area=regular_area, 
                               guess=False, stream=True, columns=wwps_columns)
    elif supplier == "BMW Plumbing Supplies" and 'Project' in read_invoice(filename):
        bmw_old.process_invoice(filename, output_path)
        return
    # ... more supplier-specific logic
```

#### Supplier-Specific Processing
Each supplier has unique PDF formats requiring custom extraction:

1. **World Wide Plumbing**: Uses `wwps_columns` configuration
2. **BMW Plumbing Supplies**: Special handling for project invoices
3. **Y & S Plumbing Supply**: Credit memo processing
4. **Supreme Plumbing Supply**: Custom extraction logic
5. **Gotham Plumbing Supply**: Specialized processing
6. **FW Webb Plumbing Supply**: Custom extraction
7. **Flow Mark Plumbing Supply**: Specialized handling
8. **Plumbing Exchange**: Custom processing
9. **AF Supply**: Specialized extraction
10. **Lion Hvac Supplies**: Custom handling

#### Data Extraction Process
1. **Table Extraction**: Uses Tabula-py for PDF table extraction
2. **Data Cleaning**: Removes empty rows, standardizes formats
3. **Invoice Information**: Extracts invoice number, date, PO number
4. **Customer Job**: Extracts job address/location
5. **Financial Data**: Extracts tax, fees, and other charges
6. **Item Data**: Extracts item codes, descriptions, quantities, costs

#### Excel Output Format
The system generates Excel files with standardized columns:
- Item, Description, Qty, Cost, Amount
- Date, Ref NO, PO #, Customer Job
- Bill, Vendor, Class, Memo, Buyer
- Sheet Name, MpiItem, MpiDescription (added during processing)

### 2. Data Processing Pipeline

#### Extracted Data Processor (`extracted_data_processor.py`)
```python
def process_extracted_data(converted_files, failed_files, existing_invoice_id=None):
    # 1. Load mappings
    temp_items = TemporaryItemMappingController(db).get_temp_items_mappings()
    item_mappings = ItemsMappingController(db).get_items_mappings()
    customer_job_mappings = CustomerJobMappingController(db).get_customer_job_mappings()
    
    # 2. Process each file
    for file in converted_files:
        result = process_single_file(file, temp_items, item_mappings, 
                                   customer_job_mappings, db, existing_invoice_id)
        results.append(result)
```

#### Single File Processing
```python
def process_single_file(file, temp_items, item_mappings, customer_job_mappings, db, existing_invoice_id=None):
    # 1. Read Excel file
    extracted_data = pd.read_excel(excel_file)
    
    # 2. Duplicate detection
    duplicate_status = InvoiceItemController(db).check_invoice_duplicate_status(
        ref_no, vendor, invoice_date, invoice_amount
    )
    
    # 3. Apply mappings
    extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings, db), axis=1)
    
    # 4. Update customer job
    extracted_data['Customer Job'] = get_updated_customer_job(extracted_customer_job, customer_job_mappings)
    
    # 5. Create/update invoice record
    if duplicate_status['status'] == 'updated_invoice':
        success = InvoiceItemController(db).update_existing_invoice_items(existing_invoice_id, extracted_data, filename)
    else:
        invoice_record = InvoiceController(db).insert_invoice(...)
        # Store invoice items
        for index, row in extracted_data.iterrows():
            InvoiceItemController(db).insert_invoice_items(row, filename, invoice_record.id)
```

---

## MPI Item Mapping & Classification

### 1. Mapping Hierarchy

The system uses a three-tier mapping approach:

#### Tier 1: Permanent Mappings (ItemsMapping)
- Stored in `supplier_item_mappings` table
- Maps supplier item codes to MPI codes
- Includes Google Sheet source information
- Highest priority in mapping resolution

#### Tier 2: Temporary Mappings (TempItemMapping)
- Stored in `temporary_item_mappings` table
- Used for items being processed
- Only assigns sheet names, doesn't change MPI fields
- Lower priority than permanent mappings

#### Tier 3: Unmapped Items (UnmappedItems)
- Items that couldn't be mapped
- Stored for future mapping creation
- Used for reporting and analysis

### 2. Mapping Resolution Logic

```python
def search_replace(row, temp_items, item_mappings, db):
    original_item = row['Item'].strip()
    
    # FIRST: Check permanent mappings
    mapping_match = item_mappings[item_mappings['supplier_item_ids'] == original_item]
    if not mapping_match.empty:
        mpi_code = mapping_match.iloc[0]['mpi_code']
        description = mapping_match.iloc[0]['description']
        if not is_temporary_mapping(mpi_code, description):
            row['MpiItem'] = mpi_code
            row['MpiDescription'] = description
            row['Sheet Name'] = mapping_match.iloc[0]['google_sheet_name']
            return row
    
    # SECOND: Check temporary mappings
    temp_match = temp_items[temp_items['original_item'] == original_item]
    if not temp_match.empty:
        row['Sheet Name'] = temp_match.iloc[0]['sheet_name']
        return row
    
    # THIRD: Add to unmapped items
    if not UnmappedItemsController(db).is_item_code_present(row['Item'], supplier_id):
        UnmappedItemsController(db).insert_unmapped_item(row['Item'], row['Description'], supplier_id)
    
    return row
```

### 3. Item Classification System

#### Classification Categories
- **M**: Materials - Maps to "UnInvoiced JIP:Cost Of Materials:Job Materials Purchased"
- **E**: Equipment - Maps to "UnInvoiced JIP:Cost Of Materials:Job Equipment"
- **A**: Additional Material - Maps to "UnInvoiced JIP:Subcontractors Expense:Labor & Material:Additional Material"
- **L**: Labor - No automatic account assignment

#### Classification Logic
```python
def get_classification(self, item):
    # 1. Try exact match
    query = self.db_context.query(ItemClassification).filter(ItemClassification.item == item).first()
    if query:
        return self._get_account_from_category(query.category)
    
    # 2. Try fuzzy matching with 90% threshold
    fuzzy_match = self._find_fuzzy_match(item, threshold=90)
    if fuzzy_match:
        return self._get_account_from_category(fuzzy_match.category)
    
    return ''
```

#### Fuzzy Matching Algorithms
The system uses multiple fuzzy matching algorithms:
1. **partial_ratio**: For cases like "(PVC) Williams" matching "(PVC)"
2. **token_set_ratio**: For token-based similarity
3. **ratio**: For general similarity

### 4. Account Assignment Logic

```python
def _auto_assign_account(self, sheet_name, current_account, mpi_item=None):
    # 1. Preserve explicit 'A' if provided
    if current_account and current_account.strip().upper() == 'A':
        return current_account
    
    # 2. UIDI-specific mapping by mpi_item
    if mpi_item:
        uidi_to_letter = {
            'UIDI-JOB MATERIALS PURCHASED': 'M',
            'UIDI JOB MATERIAL': 'M',
            'UIDI-JOB EQUIPMENT': 'E',
            'UIDI-SPRINKLER SPECIALTY ITEM': 'M',
            'UIDI-DRAINAGE MATERIAL': 'M',
        }
        if mpi_item.upper() in uidi_to_letter:
            return uidi_to_letter[mpi_item.upper()]
    
    # 3. Exact classification by sheet_name
    if sheet_name:
        row = self.db.query(ItemClassification).filter(ItemClassification.item == sheet_name).first()
        if row:
            category = row.category.strip().upper()
            if category in ('M', 'E'):
                return category
    
    # 4. Fuzzy fallback
    qb_account = ItemClassificationController(self.db).get_classification(sheet_name)
    return _map_qb_account_to_letter(qb_account)
```

---

## Duplication Detection & Handling

### 1. Duplicate Detection Logic

The system implements a sophisticated three-tier duplicate detection system:

```python
def check_invoice_duplicate_status(self, reference_no, vendor, date, amount):
    """
    Enhanced duplicate detection with comprehensive logic:
    1. Exact Duplicate: Same ref_no, vendor, date, and total amount (within tolerance) -> Skip
    2. Updated Invoice: Same ref_no, vendor, and date, different total amount -> Refresh
    3. New Invoice: Same ref_no and vendor but different date/total amount -> Add as New
    """
```

#### Duplicate Detection Scenarios

1. **Exact Duplicate**
   - Same reference number, vendor, date, and total amount (within 0.01 tolerance)
   - Status: `exact_duplicate`
   - Action: Skip processing

2. **Updated Invoice**
   - Same reference number, vendor, and date, but different total amount
   - Status: `updated_invoice`
   - Action: Update existing invoice items

3. **New Invoice**
   - Same reference number and vendor, but different date or total amount
   - Status: `new_invoice`
   - Action: Create new invoice record

4. **Not Found**
   - No existing invoice found
   - Status: `not_found`
   - Action: Create new invoice record

### 2. Duplicate Handling Process

#### For New Invoices
```python
# Create new invoice record
invoice_record = InvoiceController(db).insert_invoice(
    extracted_data['Date'][0], filename, supplier_id, 'PROCESSING', file
)

# Mark as processed
InvoiceController(db).set_status_to_processed(invoice_record.id)

# Upload to S3
upload_file(file_name=file, file_key=f'{vendor}/{invoice_record.id}')

# Store invoice items
for index, row in extracted_data.iterrows():
    InvoiceItemController(db).insert_invoice_items(row, filename, invoice_record.id)
```

#### For Updated Invoices
```python
# Update existing invoice items
success = InvoiceItemController(db).update_existing_invoice_items(
    existing_invoice_id, extracted_data, filename
)
```

### 3. Duplicate Cleanup

The system includes comprehensive duplicate cleanup functionality:

```python
def delete_duplicate_invoices(self, reference_no, vendor, date, amount, keep_most_recent=True):
    """
    Delete duplicate invoices based on reference number, vendor, date, and amount.
    Keeps the most recent invoice by default.
    """
```

#### Cleanup Process
1. Find all duplicate invoice IDs
2. Group by reference number, vendor, date, and amount
3. Keep the most recent invoice (by date_added)
4. Delete older duplicates
5. Update related records

---

## API Endpoints & Business Logic

### 1. Invoice Management Endpoints

#### GET /invoice
- **Purpose**: Get paginated list of invoices with filtering
- **Filters**: supplier_id, date range, status, job_location, export_status
- **Pagination**: page, size parameters
- **Authentication**: JWT Bearer token required

#### POST /invoice/upload
- **Purpose**: Upload and process invoice PDF file
- **Process**:
  1. Validate file type (PDF only)
  2. Verify supplier exists
  3. Save file to temporary storage
  4. Convert PDF to Excel
  5. Extract and process data
  6. Create/update invoice records
  7. Upload to S3
  8. Clean up temporary files

#### POST /invoice/process
- **Purpose**: Reprocess existing invoice
- **Process**:
  1. Download PDF from S3
  2. Save to temporary storage
  3. Convert PDF to Excel
  4. Reprocess with existing invoice ID
  5. Update invoice items
  6. Clean up temporary files

#### DELETE /invoice/delete
- **Purpose**: Delete one or more invoices
- **Supports**: Single ID or comma-separated multiple IDs
- **Process**: Deletes invoice records and associated files

### 2. Invoice Items Endpoints

#### GET /invoice-items/all
- **Purpose**: Get all invoice items with pagination
- **Returns**: Paginated invoice item objects

#### GET /invoice-items/supplier-date
- **Purpose**: Get invoice items with advanced filtering
- **Filters**: supplier_name, date range, job_location, export_status
- **Pagination**: page, size parameters

#### PUT /invoice-items/update
- **Purpose**: Update multiple invoice items in batch
- **Process**: Background task processing for performance

#### PUT /invoice-items/toggle-visibility
- **Purpose**: Toggle visibility of invoice items
- **Process**: Soft delete/restore functionality

#### POST /invoice-items/export
- **Purpose**: Export selected invoice items to Excel
- **Features**: Automatic performance optimization based on record count
- **Methods**: Standard, optimized, batch processing

### 3. Filtering Endpoints

#### GET /filter/get-locations
- **Purpose**: Get unique customer job locations
- **Features**: Aggressive caching, ultra-fast response
- **Returns**: Sorted list of unique job names

#### GET /filter/column-mapping
- **Purpose**: Get column mapping definitions
- **Returns**: Database column names to display names mapping

#### POST /filter/by-column
- **Purpose**: Get distinct values for specific column
- **Features**: Caching, filter context support
- **Returns**: Unique values from specified column

#### POST /filter/by-column-paginated
- **Purpose**: Get paginated distinct values with search
- **Features**: Search functionality, date range filtering
- **Search**: Supports "starts with" and exact match (with quotes)

#### POST /filter/invoice-items
- **Purpose**: Filter invoice items with complex queries
- **Features**: Multiple filter types, comparison filters, pagination
- **Performance**: Ultra-fast database queries with optimization

#### POST /filter/price-difference
- **Purpose**: Calculate price differences for filtered items
- **Process**: Compares current prices with historical data
- **Returns**: Percentage increase/decrease for each item

#### POST /filter/price-history
- **Purpose**: Get price history for specific item and vendor
- **Returns**: Historical price data sorted by date

### 4. Statements Endpoints

#### GET /statements/invoice-data
- **Purpose**: Get statement invoice data with filters
- **Filters**: search, date range, supplier_names, status
- **Status Types**: Processed, Failed, Unlisted, Missing System, Missing Statement
- **Returns**: Invoice data with reconciliation status

#### GET /statements/download
- **Purpose**: Download statement PDF by ID
- **Returns**: Presigned S3 URL for PDF download
- **Security**: URL expires after 3 minutes

#### POST /statements/reprocess
- **Purpose**: Reprocess monthly statements
- **Supports**: Single statement or bulk reprocessing
- **Bulk Options**: By supplier or all statements with limits

#### DELETE /statements/{statement_id}
- **Purpose**: Delete statement and associated invoice items
- **Process**: Permanently removes statement and related data

### 5. QuickBooks Integration Endpoints

#### POST /quickbooks/migrate
- **Purpose**: Migrate specific invoices to QuickBooks format
- **Features**: Priority control, guaranteed status updates
- **Process**: Ultra-fast processing with vectorized operations

#### POST /quickbooks/migrate-all
- **Purpose**: Migrate all invoices to QuickBooks format
- **Features**: Background processing, progress tracking
- **Priority**: Absolute priority over background tasks

### 6. Mapping Management Endpoints

#### POST /sync-mappings
- **Purpose**: Synchronize mappings from Google Sheets
- **Process**: Background task for mapping updates
- **Features**: Progress tracking, error handling

#### GET /get-mappings
- **Purpose**: Get current mapping status and statistics
- **Returns**: Mapping counts, sync status, last update times

---

## Background Tasks & Scheduling

### 1. Scheduler Configuration

The system uses APScheduler with comprehensive background task management:

```python
def init_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone=pytz.utc,
        jobstores={'default': {'type': 'memory'}},
    )
```

#### Job Defaults
- **coalesce**: True (combine missed executions)
- **max_instances**: 10 (allow multiple instances)
- **misfire_grace_time**: 1800 seconds (30 minutes grace period)
- **timeout**: None (no timeout restrictions)

### 2. Scheduled Tasks

#### Email Downloads (Every 5 minutes)
```python
scheduler.add_job(
    async_email_download_wrapper,
    "interval",
    minutes=5,
    id="email_download",
    name="Email Download Task (Every 5 Minutes)"
)
```

#### Statement Downloads (Every 12 hours)
```python
scheduler.add_job(
    async_statement_download_wrapper,
    "interval",
    hours=12,
    id="statement_download",
    name="Statement Download Task (Every 12 Hours)"
)
```

#### Failed Invoice Recovery (Every 1 hour)
```python
scheduler.add_job(
    async_failed_invoice_recovery_wrapper,
    "interval",
    hours=1,
    id="failed_invoice_recovery",
    name="Failed Invoice Recovery Task (Every 1 Hour)"
)
```

#### Missing Invoice Downloads (Every 5 hours)
```python
scheduler.add_job(
    async_missing_invoice_download_wrapper,
    "interval",
    hours=5,
    id="missing_invoice_download",
    name="Missing Invoice Download Task (Every 5 Hours)"
)
```

#### UIDI/NO Match Updates (Daily at 6 AM PKT)
```python
scheduler.add_job(
    scheduled_uidi_no_match_update,
    CronTrigger(hour=1, minute=0, timezone=pytz.utc),
    id="daily_uidi_no_match_update",
    name="Daily UIDI/NO Match Update (6 AM PKT)"
)
```

#### All Mappings Update (Saturday at 8 AM PKT)
```python
scheduler.add_job(
    scheduled_all_mappings_update,
    CronTrigger(hour=3, minute=0, timezone=pytz.utc, day_of_week=5),
    id="weekly_all_mappings_update",
    name="Weekly All Mappings Update (Saturday 8 AM PKT)"
)
```

#### Google Sheet Sync (Every 2 hours)
```python
scheduler.add_job(
    scheduled_google_sheet_sync,
    "interval",
    hours=2,
    id="google_sheet_sync",
    name="Google Sheet Sync (Every 2 Hours)"
)
```

#### Memory Cleanup (Every 6 hours)
```python
scheduler.add_job(
    scheduled_memory_cleanup,
    "interval",
    hours=6,
    id="memory_cleanup",
    name="Memory Cleanup (Every 6 Hours)"
)
```

### 3. Priority Control System

The system implements a sophisticated priority control system for QuickBooks operations:

```python
def pause_background_jobs():
    """Pause background jobs during QuickBooks operations"""
    
def resume_background_jobs():
    """Resume background jobs after QuickBooks operations"""
    
def pause_all_background_jobs_for_migrate_all():
    """Pause all background jobs for migrate-all operations"""
    
def resume_all_background_jobs_from_migrate_all():
    """Resume all background jobs after migrate-all operations"""
```

#### Priority Levels
1. **Migrate-All Operations**: Absolute priority, pauses all background jobs
2. **Regular Migrate Operations**: High priority, pauses specific background jobs
3. **Background Tasks**: Normal priority, can be paused by higher priority operations

---

## QuickBooks Integration

### 1. Export Process

The QuickBooks integration provides ultra-fast data export with guaranteed status updates:

```python
def migrate_invoice_to_QB_ultra_fast(invoice_ids, db, operation_id, background_tasks, update_mode="background"):
    """
    ULTRA-FAST QuickBooks migration with GUARANTEED status updates
    update_mode: "immediate" for synchronous updates, "background" for async updates
    """
```

#### Export Features
- **Ultra-fast processing**: Vectorized operations for maximum performance
- **Priority control**: Pauses background jobs during processing
- **Guaranteed status updates**: Immediate or background status updates
- **Tax distribution**: Proportional tax distribution to each item
- **Class-based splitting**: Multiple lines per invoice based on equipment/materials

### 2. Tax Distribution Logic

#### Previous Logic
- Tax was added once per invoice as a single line

#### New Logic
- Tax is distributed proportionally to each item based on tax percentage

#### Tax Calculation Formula
```
Tax Percentage = (Tax Amount / Item Total) × 100
Item Amount with Tax = Item Amount × (1 + Tax Percentage / 100)
```

#### Example
- Invoice total: $1000 (items: $900, tax: $100)
- Tax percentage: (100/900) × 100 = 11.1111%
- Item E1 ($100): $100 × (1 + 11.1111/100) = $111.11
- Item E2 ($200): $200 × (1 + 11.1111/100) = $222.22
- Item M1 ($600): $600 × (1 + 11.1111/100) = $666.67

### 3. Class-Based Account Mapping

#### Priority Order
1. **Class-based mapping** (highest priority)
   - Class 'A' → `UnInvoiced JIP:Material:Additional Material`
   - Class 'L' → `UnInvoiced JIP:Subcontractors Expense:Labor`

2. **Sheet name classification** (fallback)
   - Uses ItemClassification table for fuzzy matching
   - Maps to appropriate QuickBooks accounts

### 4. Export Performance Optimization

#### Method Selection
- **Standard Method**: For small exports (< 100 records)
- **Optimized Method**: For medium exports (100+ records)
- **Batch Method**: For large exports with configurable batch processing

#### Performance Features
- Vectorized data processing
- Optimized database queries
- Fast Excel generation and S3 upload
- Immediate status updates for guaranteed consistency

---

## Data Flow & Processing Logic

### 1. Complete Invoice Processing Flow

```
1. PDF Upload/Download
   ↓
2. Supplier Detection
   ↓
3. PDF to Excel Conversion
   ↓
4. Data Extraction & Cleaning
   ↓
5. Duplicate Detection
   ↓
6. Mapping Application
   ↓
7. Database Storage
   ↓
8. S3 Upload
   ↓
9. Status Updates
```

### 2. Mapping Resolution Flow

```
1. Original Item Code
   ↓
2. Check Permanent Mappings
   ↓ (if found)
3. Apply MPI Code & Description
   ↓ (if not found)
4. Check Temporary Mappings
   ↓ (if found)
5. Apply Sheet Name Only
   ↓ (if not found)
6. Add to Unmapped Items
   ↓
7. Default "No Match" Values
```

### 3. Duplicate Detection Flow

```
1. Extract Invoice Metadata
   (ref_no, vendor, date, amount)
   ↓
2. Query Existing Invoices
   ↓
3. Compare with Tolerance
   ↓
4. Determine Duplicate Status
   ↓
5. Execute Appropriate Action
   (Skip/Update/Create)
```

### 4. QuickBooks Export Flow

```
1. Select Invoices
   ↓
2. Pause Background Jobs
   ↓
3. Retrieve Invoice Data
   ↓
4. Apply Classifications
   ↓
5. Calculate Tax Distribution
   ↓
6. Generate Excel File
   ↓
7. Upload to S3
   ↓
8. Update Export Status
   ↓
9. Resume Background Jobs
```

---

## Error Handling & Recovery

### 1. File Processing Errors

#### PDF Conversion Failures
- **Detection**: Failed file tracking in conversion process
- **Recovery**: Automatic retry with different extraction methods
- **Fallback**: Basic Excel file creation for framework validation

#### Data Extraction Errors
- **Detection**: Exception handling in extraction process
- **Recovery**: Fallback extraction methods
- **Logging**: Comprehensive error logging for debugging

### 2. Database Errors

#### Transaction Failures
- **Detection**: SQLAlchemy exception handling
- **Recovery**: Automatic rollback and retry
- **Logging**: Detailed error logging with context

#### Duplicate Key Errors
- **Detection**: Database constraint violations
- **Recovery**: Duplicate detection and handling
- **Prevention**: Pre-insertion duplicate checking

### 3. S3 Integration Errors

#### Upload Failures
- **Detection**: Boto3 exception handling
- **Recovery**: Retry with exponential backoff
- **Fallback**: Local file storage with retry queue

#### Download Failures
- **Detection**: Presigned URL validation
- **Recovery**: URL regeneration and retry
- **Fallback**: Direct S3 access with credentials

### 4. Background Task Errors

#### Task Failures
- **Detection**: Exception handling in task wrappers
- **Recovery**: Automatic retry with backoff
- **Logging**: Comprehensive error logging

#### Scheduler Errors
- **Detection**: Scheduler exception handling
- **Recovery**: Automatic scheduler restart
- **Monitoring**: Health check endpoints

### 5. API Error Handling

#### Validation Errors
- **Detection**: Pydantic model validation
- **Response**: Structured error responses with details
- **Logging**: Request validation logging

#### Authentication Errors
- **Detection**: JWT token validation
- **Response**: 401 Unauthorized with details
- **Security**: Token blacklisting for invalid tokens

#### Rate Limiting
- **Detection**: Request counting and timing
- **Response**: 429 Too Many Requests
- **Recovery**: Automatic retry after delay

---

## Performance Optimization

### 1. Database Optimization

#### Query Optimization
- **Indexing**: Strategic indexes on frequently queried columns
- **Query Caching**: Aggressive caching for repeated queries
- **Connection Pooling**: Efficient database connection management

#### Pagination
- **Offset-based**: Standard pagination for small datasets
- **Cursor-based**: Efficient pagination for large datasets
- **Streaming**: Memory-efficient processing for very large datasets

### 2. Caching Strategy

#### Multi-level Caching
- **Application Cache**: In-memory caching for frequently accessed data
- **Query Cache**: Database query result caching
- **Response Cache**: API response caching with TTL

#### Cache Management
- **TTL**: 5-minute time-to-live for most cached data
- **Invalidation**: Automatic cache invalidation on data updates
- **Cleanup**: Automatic cleanup of expired cache entries

### 3. File Processing Optimization

#### Parallel Processing
- **Multi-threading**: Parallel processing of multiple files
- **Batch Processing**: Efficient batch operations
- **Memory Management**: Optimized memory usage for large files

#### Supplier-specific Optimization
- **Custom Extractors**: Optimized extraction for each supplier
- **Caching**: Cached extraction parameters
- **Fallback Methods**: Multiple extraction methods for reliability

### 4. API Performance

#### Response Optimization
- **Compression**: Gzip compression for large responses
- **Streaming**: Streaming responses for large datasets
- **Pagination**: Efficient pagination to limit response size

#### Background Processing
- **Async Operations**: Non-blocking operations for better performance
- **Task Queues**: Background task processing
- **Priority Control**: Intelligent task prioritization

---

## Security & Authentication

### 1. Authentication System

#### JWT Token Authentication
- **Token Generation**: Secure JWT token generation
- **Token Validation**: Comprehensive token validation
- **Token Expiration**: Configurable token expiration
- **Token Refresh**: Automatic token refresh mechanism

#### Bearer Token Implementation
```python
class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super(JWTBearer, self).__init__(auto_error=auto_error)
    
    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super(JWTBearer, self).__call__(request)
        if credentials:
            if not credentials.scheme == "Bearer":
                raise HTTPException(status_code=403, detail="Invalid authentication scheme.")
            if not self.verify_jwt(credentials.credentials):
                raise HTTPException(status_code=403, detail="Invalid token or expired token.")
            return credentials.credentials
        else:
            raise HTTPException(status_code=403, detail="Invalid authorization code.")
```

### 2. Authorization

#### Role-based Access Control
- **Admin Access**: Full system access
- **User Access**: Limited access to specific functions
- **Read-only Access**: View-only access for reporting

#### Endpoint Protection
- **Authentication Required**: Most endpoints require valid JWT token
- **Role Validation**: Role-based access control for sensitive operations
- **Rate Limiting**: Protection against abuse and DoS attacks

### 3. Data Security

#### S3 Security
- **Presigned URLs**: Time-limited access to files
- **Access Control**: Proper S3 bucket permissions
- **Encryption**: Data encryption in transit and at rest

#### Database Security
- **Connection Security**: Encrypted database connections
- **Query Sanitization**: Protection against SQL injection
- **Access Control**: Database user permissions

### 4. Input Validation

#### File Upload Security
- **File Type Validation**: Only PDF files allowed
- **File Size Limits**: Reasonable file size restrictions
- **Path Sanitization**: Protection against path traversal attacks

#### API Input Validation
- **Pydantic Models**: Comprehensive input validation
- **Type Checking**: Strict type validation
- **Range Validation**: Numeric range validation

---

## Monitoring & Logging

### 1. Logging System

#### Log Levels
- **DEBUG**: Detailed debugging information
- **INFO**: General information about system operation
- **WARNING**: Warning messages for potential issues
- **ERROR**: Error messages for failed operations
- **CRITICAL**: Critical errors that require immediate attention

#### Log Categories
- **Application Logs**: General application operation
- **Access Logs**: HTTP request/response logging
- **Error Logs**: Error and exception logging
- **Missing Logs**: Items that couldn't be processed

#### Log Rotation
- **Size-based**: Rotate logs when they reach a certain size
- **Time-based**: Rotate logs daily
- **Retention**: Keep logs for a specified period

### 2. Performance Monitoring

#### System Metrics
- **CPU Usage**: CPU utilization monitoring
- **Memory Usage**: Memory consumption tracking
- **Disk Usage**: Disk space monitoring
- **Network Usage**: Network traffic monitoring

#### Application Metrics
- **Request Count**: Total number of requests
- **Error Count**: Number of failed requests
- **Response Time**: Average response time
- **Success Rate**: Percentage of successful requests

#### Database Metrics
- **Query Performance**: Slow query identification
- **Connection Pool**: Database connection monitoring
- **Transaction Count**: Database transaction tracking

### 3. Health Checks

#### System Health
- **Database Connectivity**: Database connection health
- **S3 Connectivity**: S3 service health
- **Background Tasks**: Scheduler and task health
- **Memory Usage**: Memory consumption health

#### Application Health
- **API Endpoints**: Endpoint availability
- **File Processing**: Processing pipeline health
- **Mapping System**: Mapping service health
- **Export System**: QuickBooks export health

---

## Configuration & Environment

### 1. Environment Variables

#### Database Configuration
- **DATABASE_URL**: PostgreSQL connection string
- **DB_POOL_SIZE**: Database connection pool size
- **DB_MAX_OVERFLOW**: Maximum database connections

#### S3 Configuration
- **AWS_SERVER_PUBLIC_KEY**: AWS access key
- **AWS_SERVER_SECRET_KEY**: AWS secret key
- **BUCKET_NAME**: S3 bucket name
- **REGION**: AWS region

#### Application Configuration
- **INVOICE_DOWNLOAD_FOLDER**: Local file storage path
- **JWT_SECRET_KEY**: JWT token secret
- **JWT_ALGORITHM**: JWT algorithm
- **JWT_ACCESS_TOKEN_EXPIRE_MINUTES**: Token expiration time

#### Performance Configuration
- **EXPORT_MAX_RECORDS_BEFORE_BATCH**: Batch processing threshold
- **EXPORT_USE_OPTIMIZED**: Enable optimized export
- **EXPORT_BATCH_SIZE**: Batch size for large exports
- **MAX_CPU_USAGE**: CPU usage threshold
- **MAX_MEMORY_USAGE**: Memory usage threshold

### 2. Configuration Files

#### Logging Configuration
- **Log Level**: Configurable log levels
- **Log Format**: Customizable log formats
- **Log Handlers**: Multiple log handlers (file, console)

#### Performance Configuration
- **Cache Settings**: Cache TTL and size limits
- **Background Task Settings**: Task scheduling and limits
- **API Rate Limits**: Request rate limiting

### 3. Deployment Configuration

#### Docker Configuration
- **Dockerfile**: Container configuration
- **docker-compose.yml**: Multi-container setup
- **Environment Variables**: Container environment setup

#### Service Configuration
- **systemd Service**: Linux service configuration
- **Startup Scripts**: Application startup scripts
- **Health Check Scripts**: System health monitoring

---

## Troubleshooting Guide

### 1. Common Issues

#### PDF Conversion Failures
- **Issue**: PDF files not converting to Excel
- **Causes**: Corrupted PDFs, unsupported formats, extraction errors
- **Solutions**: 
  - Check PDF file integrity
  - Verify supplier-specific extraction logic
  - Review extraction logs for errors
  - Try alternative extraction methods

#### Duplicate Invoice Issues
- **Issue**: Same invoice processed multiple times
- **Causes**: Duplicate detection logic failures, data inconsistencies
- **Solutions**:
  - Review duplicate detection logs
  - Check invoice metadata consistency
  - Use duplicate cleanup scripts
  - Verify reference number formats

#### Mapping Issues
- **Issue**: Items not mapping to correct MPI codes
- **Causes**: Missing mappings, incorrect mapping logic, data inconsistencies
- **Solutions**:
  - Check mapping tables for missing entries
  - Verify mapping resolution logic
  - Review temporary vs permanent mappings
  - Check Google Sheet sync status

#### Performance Issues
- **Issue**: Slow API responses or processing
- **Causes**: Large datasets, inefficient queries, resource constraints
- **Solutions**:
  - Check database query performance
  - Review caching configuration
  - Monitor system resources
  - Optimize pagination and filtering

### 2. Debugging Tools

#### Log Analysis
- **Application Logs**: Review application.log for errors
- **Access Logs**: Check access.log for request patterns
- **Error Logs**: Analyze error.log for specific failures
- **Missing Logs**: Review missing.log for unprocessed items

#### Database Queries
- **Slow Query Log**: Identify performance bottlenecks
- **Query Execution Plans**: Analyze query optimization
- **Index Usage**: Check index utilization
- **Connection Monitoring**: Monitor database connections

#### System Monitoring
- **Resource Usage**: Monitor CPU, memory, disk usage
- **Network Monitoring**: Check network connectivity
- **Process Monitoring**: Monitor application processes
- **Service Health**: Check service status and health

### 3. Recovery Procedures

#### Data Recovery
- **Database Backups**: Restore from recent backups
- **File Recovery**: Recover files from S3 or local storage
- **Mapping Recovery**: Restore mapping configurations
- **Configuration Recovery**: Restore system configurations

#### Service Recovery
- **Service Restart**: Restart failed services
- **Container Restart**: Restart Docker containers
- **Database Restart**: Restart database services
- **Scheduler Restart**: Restart background scheduler

#### Data Consistency
- **Duplicate Cleanup**: Remove duplicate records
- **Mapping Synchronization**: Sync mappings from Google Sheets
- **Status Updates**: Update processing statuses
- **Data Validation**: Validate data integrity

---

## Conclusion

This comprehensive documentation covers all aspects of the MPI Backend system, including:

1. **Complete Database Architecture** with all models and relationships
2. **Detailed File Processing Workflow** from PDF upload to database storage
3. **Sophisticated MPI Mapping System** with three-tier resolution logic
4. **Advanced Duplicate Detection** with multiple scenarios and handling
5. **Comprehensive API Endpoints** with full business logic documentation
6. **Background Task Management** with scheduling and priority control
7. **QuickBooks Integration** with ultra-fast processing and tax distribution
8. **Performance Optimization** strategies and caching mechanisms
9. **Security and Authentication** implementation details
10. **Monitoring and Logging** systems for operational excellence
11. **Configuration Management** for different environments
12. **Troubleshooting Guide** for common issues and recovery procedures

The system is designed for high performance, reliability, and scalability, with comprehensive error handling, monitoring, and recovery mechanisms. The business logic is sophisticated yet maintainable, with clear separation of concerns and modular architecture.

This documentation serves as a complete reference for understanding, maintaining, and extending the MPI Backend system.

