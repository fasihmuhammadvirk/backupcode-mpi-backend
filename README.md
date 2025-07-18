# mpi-backend
Contains Code for MPI Backend

## Overview
MPI Backend is a comprehensive FastAPI-based application designed for managing invoice processing, supplier data, and QuickBooks integration. The system handles automated invoice downloads, statement processing, item mapping, and price comparison functionality.

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
- **Framework**: FastAPI 0.104.0
- **Database**: PostgreSQL with SQLAlchemy 2.0.4
- **Authentication**: JWT with PyJWT
- **Background Tasks**: APScheduler 3.10.4
- **File Processing**: PyPDF2, tabula-py, openpyxl
- **Data Processing**: Pandas, NumPy
- **Cloud Storage**: AWS S3 (boto3)
- **Monitoring**: Middleware APM
- **Containerization**: Docker & Docker Compose

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

## Environment Setup

For this to run you need to have env variable set. We have included a sample .envrc file with this repo
rename it to `.envrc` and set the values correctly

For ease of use, using `direnv` is recommended.
You can follow instructions to install and use it here 
https://direnv.net

## Running the Application

### Production Mode
To start the uvicorn server in PRODUCTION (with monitoring enabled) run below command:

```bash
middleware-apm run uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000
```

### Development Mode
For execution in LOCAL environment (or without monitoring) run below command:
```bash
uvicorn mpi_backend.main:app --port 8080
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

## Development

### Prerequisites
- Python 3.9+
- PostgreSQL
- Java Runtime Environment (for PDF processing)
- Docker & Docker Compose (optional)

### Installation
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables
4. Run database migrations: `alembic upgrade head`
5. Start the application

### Testing
Run tests using the test files in the `tests/` directory.

### Scripts
The `scripts/` directory contains utility scripts for:
- Database backup and restore
- Historical data processing
- Data cleanup and maintenance
- Performance optimization

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