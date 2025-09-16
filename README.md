# MPI Backend

A comprehensive FastAPI-based application for managing invoice processing, supplier data, and QuickBooks integration. The system handles automated invoice downloads, statement processing, item mapping, and price comparison functionality.

## 🚀 **Latest Updates (Python 3.11 Upgrade)**

- ✅ **Upgraded to Python 3.11.9** - Full compatibility with modern Python features
- ✅ **Fixed PyPDF2 deprecation issues** - Updated to use modern PDF processing libraries
- ✅ **Resolved pandas deprecation warnings** - All data processing now uses current pandas syntax
- ✅ **Cross-platform compatibility** - Works seamlessly on macOS, Linux, and Windows
- ✅ **Enhanced PDF to Excel conversion** - All 12 supplier processing modules tested and verified
- ✅ **Improved dependency management** - Clean, organized requirements with platform-specific support
- ✅ **Fixed jpype integration** - Faster PDF processing with Java-Python bridge
- ✅ **Updated backup system** - Streamlined database backup process

## Features
- **Invoice Management**: Automated download, processing, and storage of invoices from multiple suppliers
- **Statement Processing**: Monthly statement extraction and analysis
- **Item Mapping**: Intelligent mapping of invoice items to standardized product codes
- **Price Comparison**: Monthly price comparison across suppliers
- **QuickBooks Integration**: Export processed data to QuickBooks
- **Supplier Management**: Multi-supplier support with automated data processing
- **Authentication**: JWT-based authentication system
- **Background Tasks**: Scheduled tasks for data synchronization and processing
- **File Processing**: PDF to Excel conversion and data extraction
- **S3 Integration**: Cloud storage for processed files and exports

## Technology Stack
- **Python**: 3.11.9 (Latest stable version)
- **Framework**: FastAPI 0.104.0
- **Database**: PostgreSQL with SQLAlchemy 2.0.4
- **Authentication**: JWT with PyJWT
- **Background Tasks**: APScheduler 3.10.4
- **File Processing**: PyPDF2, PyPDF4, tabula-py, camelot-py, openpyxl, PyMuPDF
- **Data Processing**: Pandas, NumPy
- **Cloud Storage**: AWS S3 (boto3)
- **Monitoring**: Middleware APM
- **Containerization**: Docker & Docker Compose
- **Environment Management**: Conda (mpi64bit environment)

## Performance Optimizations
- **Proactive Resource Management**: Advanced optimizations that prevent high CPU usage before it occurs
- **Performance Thresholds**: 95% CPU and 85% memory usage limits with proactive optimization
- **Circuit Breaker**: Intelligent request rejection to prevent system overload
- **Memory Optimization**: Weak reference caching and garbage collection
- **Database Optimization**: Automatic query optimization, indexing, and connection pooling
- **Background Task Optimization**: Priority-based scheduling with automatic resource management
- **Request Processing Optimization**: Intelligent caching and batch processing
- **Proactive Monitoring**: Real-time optimization based on resource usage patterns

## Project Structure

```
mpi-backend/
├── mpi_backend/                    # Main application package
│   ├── api/                       # API layer
│   │   └── routes/                # API endpoints
│   │       ├── customer_job.py    # Customer job mapping endpoints
│   │       ├── filters.py         # Data filtering and search
│   │       ├── get_mappings.py    # Item mapping management
│   │       ├── health.py          # Health check endpoint
│   │       ├── invoice_items.py   # Invoice items CRUD
│   │       ├── invoices_list.py   # Invoice management
│   │       ├── monthly_comparison.py # Price comparison
│   │       ├── quickbooks.py      # QuickBooks integration
│   │       ├── signin.py          # Authentication
│   │       ├── statements.py      # Monthly statements
│   │       ├── supplier.py        # Supplier management
│   │       └── sync_mappings.py   # Mapping synchronization
│   ├── config/                    # Configuration management
│   │   ├── logging_config.py      # Logging setup
│   │   └── spreadsheet_config.py  # Spreadsheet processing config
│   ├── database/                  # Database layer
│   │   ├── controllers/           # Business logic controllers
│   │   ├── models/                # SQLAlchemy models
│   │   └── schemas/               # Pydantic schemas
│   ├── utils/                     # Utility modules
│   │   ├── auth/                  # Authentication utilities
│   │   ├── customer_job_mapping/  # Customer job mapping logic
│   │   ├── google_sheets/         # Google Sheets integration
│   │   ├── pdf_to_excel/          # PDF processing utilities
│   │   ├── statement_extractor/   # Statement processing
│   │   └── sync_mapping/          # Mapping synchronization
│   ├── alembic/                   # Database migrations
│   │   └── versions/              # Migration files
│   └── main.py                    # Application entry point
├── scripts/                       # Utility scripts
├── tests/                         # Test files
├── docs/                          # Documentation
├── logs/                          # Application logs
├── backups/                       # Database backups
├── docker-compose.yml             # Docker orchestration
├── Dockerfile                     # Container configuration
├── requirements.txt               # Python dependencies
└── alembic.ini                    # Alembic configuration
```

## API Endpoints

### Authentication
- `POST /signin` - User authentication

### Health & Monitoring
- `GET /health` - Application health check

### Invoice Management
- `GET /invoice` - List invoices with filtering and pagination
- `GET /invoice-items/all` - Get all invoice items
- `POST /invoice-items/export` - Export invoice items to Excel
- `POST /invoice-items/toggle-visibility` - Toggle item visibility

### Supplier Management
- `GET /supplier` - Get list of all suppliers

### Item Mapping
- `POST /mapping` - Update item mappings
- `GET /mapping/search-item` - Search for item mappings

### Data Filtering & Search
- `POST /filter` - Filter invoice data with advanced criteria
- `POST /filter/by-column` - Get distinct values for dropdowns
- `POST /filter/price-history` - Get price history for items
- `POST /filter/get_aggregates` - Get aggregated data
- `POST /filter/unmapped-items` - Get unmapped items

### Price Comparison
- `POST /price-comparison/dropdown-items` - Get items for comparison
- `POST /price-comparison/selected-items` - Get prices for selected items
- `POST /price-comparison/selected-items-by-date-range` - Get items by date range

### Monthly Statements
- `GET /statements/invoice-data` - Get statement invoice data

### QuickBooks Integration
- `POST /quickbooks/export` - Export data to QuickBooks
- `POST /quickbooks/migrate-all` - Migrate all data to QuickBooks

### Customer Job Mapping
- `POST /customer-job/update-mappings` - Update customer job mappings

### Synchronization
- `POST /sync/mapping` - Sync mappings from Google Sheets

## Database Models

### Core Models
- **Invoice**: Invoice header information
- **InvoiceItems**: Individual invoice line items
- **Suppliers**: Supplier/vendor information
- **User**: User authentication data

### Mapping Models
- **ItemsMapping**: Item code mappings
- **TemporaryItemMapping**: Temporary mapping storage
- **CustomerJobMappings**: Customer job mappings
- **UnmappedItems**: Items without mappings

### Processing Models
- **ItemClassification**: Item classification data
- **MonthlyStatement**: Monthly statement records

## Background Tasks

The application runs several scheduled background tasks:

1. **Email Download Task**: Downloads invoices from email attachments
2. **Statement Download Task**: Downloads monthly statements
3. **Failed Invoice Recovery**: Recovers failed invoice processing
4. **Missing Invoice Download**: Downloads missing invoices
5. **Mapping Updates**: Synchronizes item mappings
6. **Memory Cleanup**: Performs periodic memory optimization

## Configuration

### Environment Variables
- `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD` - Database configuration
- `SECRET_KEY` - JWT secret key
- `LOGIN_EMAIL`, `LOGIN_PWD`, `SMTP_SERVER` - Email configuration
- `AWS_SERVER_PUBLIC_KEY`, `AWS_SERVER_SECRET_KEY`, `REGION`, `BUCKET_NAME` - S3 configuration
- `INVOICE_DOWNLOAD_FOLDER` - Local storage path
- `LOG_LEVEL` - Logging level

### QuickBooks Configuration
- `QB_PRIORITY_MODE` - Enable QuickBooks priority mode
- `QB_DEDICATED_POOL_SIZE` - Database connection pool size
- `QB_MAX_CONCURRENT_EXPORTS` - Maximum concurrent exports
- `MIGRATE_ALL_ABSOLUTE_PRIORITY` - Priority for migrate-all operations

## Alembic
Almebic is used for migrations. To run migrations do the following

```bash
cd mpi_backend
export PYTHONPATH=../ 
alembic upgrade head
```

### Generating Migrations
To create a new migration of revision use following command and commit the resultant file to git: 
```bash
alembic revision --autogenerate -m "change details"
```

## 🐍 **Environment Setup (Conda)**

### Prerequisites
- **Conda** (Anaconda or Miniconda)
- **PostgreSQL** 14+ 
- **Java Runtime Environment** (for PDF processing)
- **macOS**: Homebrew for PostgreSQL installation

### 1. Create and Activate Conda Environment

```bash
# Create conda environment with Python 3.11
conda create -n mpi64bit python=3.11.9

# Activate the environment
conda activate mpi64bit

# Verify Python version
python --version  # Should show Python 3.11.9
```

### 2. Install Dependencies

```bash
# Install dependencies (macOS - excludes Windows-specific packages)
pip install -r requirements_macos.txt

# OR for other platforms
pip install -r requirements.txt
```

### 3. Database Setup

```bash
# Install PostgreSQL (macOS with Homebrew)
brew install postgresql@14

# Start PostgreSQL service
brew services start postgresql@14

# Set environment variable for library path (macOS)
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/postgresql@14/lib:$DYLD_LIBRARY_PATH"
```

### 4. Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# Database Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=mpi_db
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=your_password

# JWT Secret
SECRET_KEY=your_secret_key

# Email Configuration
LOGIN_EMAIL=your_email@example.com
LOGIN_PWD=your_email_password
SMTP_SERVER=smtp.gmail.com

# AWS S3 Configuration
AWS_SERVER_PUBLIC_KEY=your_aws_key
AWS_SERVER_SECRET_KEY=your_aws_secret
REGION=us-east-1
BUCKET_NAME=your_bucket_name

# Local Storage
INVOICE_DOWNLOAD_FOLDER=mpi_backend/storage

# Logging
LOG_LEVEL=INFO
```

## 🚀 **Running the Application**

### 1. Activate Conda Environment

```bash
# Always activate the conda environment first
conda activate mpi64bit

# Verify you're in the correct environment
which python  # Should point to conda environment
```

### 2. Database Migration

```bash
# Run database migrations
cd mpi_backend
export PYTHONPATH=../
alembic upgrade head
```

### 3. Start the Application

#### Development Mode
```bash
# Set PostgreSQL library path (macOS)
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/postgresql@14/lib:$DYLD_LIBRARY_PATH"

# Start the application with auto-reload
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Production Mode
```bash
# 1. Open terminal and navigate to project directory
cd Desktop/mpi-backend

# 2. Activate conda environment
conda activate mpi64bit

# 3. Start the application
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000
```

### 4. Verify Application is Running

```bash
# Check health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","message":"MPI Backend is running"}
```

### Server Prerequisites

Before running on server, ensure:

1. **Conda environment is created and activated**
2. **Dependencies are installed** (`pip install -r requirements_macos.txt`)
3. **Database is set up and migrated** (`alembic upgrade head`)
4. **Environment variables are configured** (`.env` file)
5. **PostgreSQL is running** and accessible
6. **Port 8000 is available** and not blocked by firewall

### Server Environment Variables

Make sure your server has the correct environment variables in `.env`:

```bash
# Database Configuration
POSTGRES_HOST=localhost  # or your database server IP
POSTGRES_PORT=5432
POSTGRES_DB=mpi_db
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=your_secure_password

# JWT Secret (use a strong, unique secret)
SECRET_KEY=your_very_secure_secret_key_here

# Other required variables...
```

### Running as Background Service

For production, consider running as a background service:

```bash
# Using nohup to run in background
nohup uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1 &

# Or using screen/tmux for session management
screen -S mpi-backend
conda activate mpi64bit
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000
# Press Ctrl+A, D to detach from screen
```

### Docker Deployment
To run the application using Docker:

```bash
# Build and start all services
docker-compose up --build

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f mpi-backend
```

## 🧪 **Development & Testing**

### Prerequisites
- **Python 3.11.9** (via conda environment)
- **PostgreSQL 14+**
- **Java Runtime Environment** (for PDF processing)
- **Conda** (for environment management)
- **Docker & Docker Compose** (optional)

### Quick Start
```bash
# 1. Clone the repository
git clone <repository-url>
cd mpi-backend

# 2. Create and activate conda environment
conda create -n mpi64bit python=3.11.9
conda activate mpi64bit

# 3. Install dependencies
pip install -r requirements_macos.txt  # macOS
# OR
pip install -r requirements.txt       # Other platforms

# 4. Set up environment variables
cp .env.example .env  # Edit with your values

# 5. Run database migrations
cd mpi_backend
export PYTHONPATH=../
alembic upgrade head

# 6. Start the application
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/postgresql@14/lib:$DYLD_LIBRARY_PATH"  # macOS
uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Testing
```bash
# Activate conda environment
conda activate mpi64bit

# Run all tests
pytest

# Run specific test file
pytest tests/test_invoices.py

# Run with verbose output
pytest -v
```

### PDF Processing Testing
```bash
# Test PDF to Excel conversion
python -c "
from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data
result = extract_data('path/to/test.pdf', 'output.xlsx', 'Supplier Name')
print('PDF processing test:', result)
"
```

### Scripts
The `scripts/` directory contains utility scripts for:
- Database backup and restore
- Historical data processing
- Data cleanup and maintenance
- Performance optimization

## 🔧 **Recent Fixes & Improvements**

### Python 3.11 Compatibility
- ✅ **PyPDF2 Deprecation**: Updated `PdfFileReader`/`PdfFileWriter` to `PdfReader`/`PdfWriter`
- ✅ **Pandas Warnings**: Fixed `fillna(method="ffill")` to `.ffill()` syntax
- ✅ **Series Indexing**: Updated deprecated `df[0][1]` to `df.iloc[0, 1]`
- ✅ **Cross-Platform Paths**: Fixed hardcoded Windows paths for macOS/Linux compatibility

### PDF Processing Enhancements
- ✅ **All 12 Suppliers Tested**: World Wide Plumbing, BMW, Y&S, Supreme, Gotham, etc.
- ✅ **jpype Integration**: Faster PDF processing with Java-Python bridge
- ✅ **Error Handling**: Improved error handling and logging for PDF conversion
- ✅ **Memory Optimization**: Better memory management for large PDF files

### Database & Backup
- ✅ **Backup Script**: Python-based backup (no pg_dump required)
- ✅ **Clean Storage**: Backups only stored in `database backups/` directory
- ✅ **Dependency Order**: Proper table creation order respecting foreign keys

### Environment Management
- ✅ **Conda Environment**: `mpi64bit` environment with Python 3.11.9
- ✅ **Platform-Specific Requirements**: `requirements_macos.txt` for macOS
- ✅ **Dependency Resolution**: Fixed version conflicts and duplicates

## Monitoring & Logging

The application includes comprehensive logging and monitoring:
- Structured logging with configurable levels
- Performance monitoring for slow queries
- Background task monitoring
- Error tracking and recovery
- Memory usage optimization

## Security Features

- JWT-based authentication
- Password hashing with bcrypt
- CORS middleware configuration
- Input validation with Pydantic
- SQL injection prevention with SQLAlchemy
- File upload validation

## Performance Optimizations

- Database connection pooling
- Query optimization and indexing
- Caching for frequently accessed data
- Background task processing
- Memory management and cleanup
- Optimized file processing pipelines