# MPI Backend

A comprehensive FastAPI-based application for managing invoice processing, supplier data, and QuickBooks integration. The system handles automated invoice downloads, statement processing, item mapping, and price comparison functionality.


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
- **AI Chatbot**: Natural language database queries with conversational intelligence and multi-agent support
- **User Management**: Multi-user support with role-based access control (admin, bookkeeping, standard)
- **Company Management**: Multi-tenant support with company-based data isolation

## Performance Optimizations
- **Proactive Resource Management**: Advanced optimizations that prevent high CPU usage before it occurs
- **Performance Thresholds**: 95% CPU and 85% memory usage limits with proactive optimization
- **Circuit Breaker**: Intelligent request rejection to prevent system overload
- **Memory Optimization**: Weak reference caching and garbage collection
- **Database Optimization**: Automatic query optimization, indexing, and connection pooling
- **Background Task Optimization**: Priority-based scheduling with automatic resource management
- **Request Processing Optimization**: Intelligent caching and batch processing
- **Proactive Monitoring**: Real-time optimization based on resource usage patterns

## API Endpoints

### Authentication
- `POST /signin` - User authentication

### Health & Monitoring
- `GET /health` - Application health check

### Chatbot (AI Assistant)
- `POST /qa/query` - Natural language database queries via AI chatbot
- `GET /qa/agents` - Get information about registered AI agents

### User Management
- `GET /users` - Get all users (admin only)
- `GET /users/{user_id}` - Get user by ID
- `POST /users` - Create new user (admin only)
- `PUT /users/{user_id}` - Update user (admin only)

### Company Management
- `GET /companies` - Get all companies
- `POST /companies` - Create new company

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
- `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` - Database configuration
- `ENVIRONMENT` - Environment mode (dev, staging, production)
- `PYTHONBUFFERED` - Python output buffering setting
- `SECRET_KEY` - JWT secret key
- `LOGIN_EMAIL`, `LOGIN_PWD`, `SMTP_SERVER` - Email configuration
- `PUBLIC_ACCESS_KEY`, `SECRET_ACCESS_KEY`, `REGION`, `BUCKET_NAME` - AWS S3 configuration
- `INVOICE_DOWNLOAD_FOLDER` - Local storage path
- `GOOGLE_CHATBOT_API_KEY` - Google Chatbot API key for AI assistant

### QuickBooks Configuration
- `QB_PRIORITY_MODE` - Enable QuickBooks priority mode
- `QB_DEDICATED_POOL_SIZE` - Database connection pool size
- `QB_MAX_CONCURRENT_EXPORTS` - Maximum concurrent exports
- `MIGRATE_ALL_ABSOLUTE_PRIORITY` - Priority for migrate-all operations

## Alembic
Alembic is used for migrations. To run migrations do the following

```bash
cd mpi_backend
export PYTHONPATH=../ 
uv run alembic upgrade head
```

### Generating Migrations
To create a new migration of revision use following command and commit the resultant file to git: 
```bash
uv run alembic revision --autogenerate -m "change details"
```

## 🚀 **Quick Setup with uv**

### Prerequisites
- **PostgreSQL** 14+ 
- **Java Runtime Environment** (for PDF processing)

### 1. Automated Setup

```bash
# Windows
.\setup.ps1

# Linux/Mac
chmod +x setup.sh
./setup.sh
```

The setup script will automatically:
- Install uv if not present
- Create virtual environment
- Install all dependencies from lockfile
- Set up environment file

### 2. Manual Setup (Alternative)

```bash
# Install uv (if not already installed)
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux/Mac: curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync --frozen

# Copy environment template
cp .env.example .env
```

### 3. Environment Variables

Edit the `.env` file with your configuration:

```bash
# Database Configuration
POSTGRES_HOST=localhost
POSTGRES_DB=mpi_db
POSTGRES_USERNAME=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_PORT=5432

# Application Configuration
ENVIRONMENT=dev
LOG_LEVEL=INFO
SECRET_KEY=your_secret_key

# Email Configuration
SMTP_SERVER=imap.gmail.com
LOGIN_EMAIL=your_email@example.com
LOGIN_PWD=your_email_password

# Local Storage
INVOICE_DOWNLOAD_FOLDER=mpi_backend/storage

# AWS S3 Configuration
PUBLIC_ACCESS_KEY=your_aws_public_key
SECRET_ACCESS_KEY=your_aws_secret_key
BUCKET_NAME=your_bucket_name
REGION=us-east-1

# Google Chatbot API
GOOGLE_CHATBOT_API_KEY=your_google_chatbot_api_key
```

---

## 🚀 Development Setup

### 1. Database Setup

```bash
# Install PostgreSQL 14+
# Windows: Download from postgresql.org
# Mac: brew install postgresql@14
# Linux: sudo apt-get install postgresql-14

# Start PostgreSQL service
# Mac: brew services start postgresql@14
# Linux: sudo systemctl start postgresql

# Create database
createdb mpi_db
```

### 2. Install dbt Packages

The `dbt_packages/` directory is gitignored, so you need to install dbt
packages after cloning (or after `git clean`). The `setup.sh` / `setup.ps1`
scripts above already run this step — run it manually only if you skipped
those scripts or cleaned the directory:

```bash
(cd mpi_analytics && uv run python run_dbt.py deps)
```

### 3. Run Database Migrations

```bash
# From project root
uv run alembic upgrade head
```

### 4. Start Development Server

```bash
# Start server with hot-reload (uv will automatically use the virtual environment)
uv run uvicorn mpi_backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Verify Application

```bash
# Check health endpoint
curl http://localhost:8000/health

# Access API documentation
# Open browser: http://localhost:8000/docs
```
# Expected response:
```json
{"status":"healthy","message":"MPI Backend is running"}
```

---

## 🛠️ Optional: Makefile Shortcuts

A `Makefile` is included with convenience targets that wrap the commands
above. Using it is optional — all commands work without it.

**Prerequisite:** `make` must be installed.
- **macOS / Linux:** usually pre-installed (otherwise `brew install make` or `sudo apt-get install build-essential`).
- **Windows:** install via Chocolatey (`choco install make`) or use WSL.

```bash
make setup      # install dbt packages + run migrations
make dbt-deps   # install dbt packages only
make migrate    # run alembic migrations
make dev        # start dev server with hot-reload
make test       # run pytest
```

---

## 🔧 Common Development Tasks

### Adding Dependencies

```bash
# Add a new package
uv add package-name

# Add development dependency
uv add --dev package-name

# This automatically:
# - Updates pyproject.toml
# - Updates uv.lock
# - Installs the package

# Commit both files
git add pyproject.toml uv.lock
git commit -m "Add package-name dependency"
```

### Removing Dependencies

```bash
# Remove a package
uv remove package-name

# Remove development dependency
uv remove --dev package-name
```

### Updating Dependencies

```bash
# Update all packages to latest compatible versions
uv lock --upgrade

# Or update specific package
uv lock --upgrade-package pandas

# Install updated versions
uv sync

# Commit changes
git add uv.lock
git commit -m "Update dependencies"
```

### After Pulling Changes

```bash
# If pyproject.toml or uv.lock changed
uv sync --frozen

# If packages.yml changed or dbt_packages/ is missing
(cd mpi_analytics && uv run python run_dbt.py deps)
```

### Running the Application

```bash
# Start development server (uv automatically uses virtual environment)
uv run uvicorn mpi_backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Creating Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "description of changes"

# Apply migrations
uv run alembic upgrade head

# Rollback migration
uv run alembic downgrade -1
```

---

## 🧪 Testing

### Prerequisites
- Dependencies installed (via `uv sync`)
- PostgreSQL running
- Test database configured

### Test Structure

```
mpi_backend/tests/
├── unit/                      # Unit tests (isolated, mocked)
│   ├── business_logic/       # Core business logic tests
│   ├── controllers/          # Controller unit tests
│   ├── utils/                # Utility function tests
│   └── models/               # Model tests
├── integration/              # Integration tests (real DB)
│   ├── api/                  # API endpoint integration tests
│   ├── workflows/            # End-to-end workflow tests
│   └── database/             # Database integration tests
├── functional/               # Functional/acceptance tests
├── fixtures/                 # Shared test data factories
└── pdf_to_excel_test_files/  # PDF conversion test data
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test categories
uv run pytest -m unit              # Unit tests only
uv run pytest -m integration       # Integration tests only
uv run pytest -m functional        # Functional tests only

# Run specific test file
uv run pytest mpi_backend/tests/unit/business_logic/test_invoice_duplicate_detection.py

# Run with verbose output
uv run pytest -v

# Run with coverage report
uv run pytest --cov=mpi_backend --cov-report=html
```

### Test Markers

The project uses pytest markers for test organization:
- `unit`: Unit tests (isolated, mocked dependencies)
- `integration`: Integration tests (real database)
- `functional`: Functional/acceptance tests
- `business_logic`: Critical business rule tests
- `slow`: Long-running tests
- `requires_db`: Tests needing database connection

---

## Docker

### Build

```bash
docker build -t mpi-backend .
```

### Run (with host Postgres)

The container needs your `.env` for database credentials and API keys.
Use `--network host` so `POSTGRES_HOST=localhost` in `.env` resolves to
your (Linux) host machine's Postgres, not the container's loopback.

```bash
docker run --rm \
    --env-file .env \
    --network host \
    mpi-backend
```

This will:
1. Run `alembic upgrade head` (migrations)
2. Start uvicorn on port 8000
3. Start the background scheduler (dbt refresh, Google Sheet sync, etc.)

### Run (skip migrations, just the server)

```bash
docker run --rm \
    --env-file .env \
    --network host \
    mpi-backend \
    uvicorn mpi_backend.main:app --host 0.0.0.0 --port 8000
```

### Verify

```bash
curl http://localhost:8000/health
# {"status":"healthy","message":"MPI Backend is running"}
```

### Notes

- The image is a multi-stage build using `uv`. Dependencies are installed at build time; `uv` is included in the runtime image because the dbt
  scheduler shells out to `uv run python run_dbt.py`.
- `dbt deps` runs at build time so dbt packages are baked into the image.
- `UV_PROJECT_ENVIRONMENT=/app/.venv` and `UV_NO_SYNC=1` are set so
  runtime `uv run` calls reuse the pre-built venv without syncing.
- `.dockerignore` excludes `.git`, `docs/`, `database_backups/`, `app-specs/`, etc. It includes `scripts/` and `mpi_analytics/` because the scheduler needs them at runtime.

### Docker Compose

```bash
# Build and start all services
docker-compose up --build

# Access API at http://localhost:8000

# View logs
docker-compose logs -f mpi-backend

# Stop services
docker-compose down
```

---

## Troubleshooting

### "uv: command not found"
```bash
# Run the setup script - it will install uv
.\setup.ps1  # Windows
./setup.sh   # Linux/Mac
```

### "Cannot activate virtual environment" (Windows)
```powershell
# Note: You don't need to activate the environment when using uv run
# But if you want to activate manually:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "Module not found" errors
```bash
# Reinstall dependencies
uv sync --frozen
```

### dbt fails with missing packages (dbt-utils, elementary, etc.)
```bash
# Install dbt packages (gitignored, not included in the repo)
(cd mpi_analytics && uv run python run_dbt.py deps)
```

### NumPy/OpenCV compatibility issues
**Why numpy<2.0?** NumPy 2.0 (released June 2024) introduced breaking changes:
- C API incompatibility - packages like OpenCV compiled with NumPy 1.x may not work
- Type promotion rules changed, affecting pandas and other libraries
- Default integer type changed on Windows (32-bit → 64-bit)

We pin to `numpy==1.26.4` to ensure compatibility with OpenCV 4.8.1.78 and pandas 2.3.2.

```bash
# numpy is pinned to 1.26.4 in pyproject.toml for compatibility
# To update numpy (with caution), update the pin in pyproject.toml then:
uv lock
uv sync --frozen
```

### Database connection errors
```bash
# Check PostgreSQL is running
# Check .env has correct database credentials
# Try creating database manually:
createdb mpi_db
```

### Starting fresh
```bash
# Delete virtual environment
rm -rf .venv

# Run setup again
.\setup.ps1  # Windows
./setup.sh   # Linux/Mac
```

---

## 📚 Additional Documentation

- **[API Documentation](http://localhost:8000/docs)** - Interactive API docs (when running)
- **[Redoc](http://localhost:8000/redoc)** - Alternative API documentation (when running)
- **[API_Endpoints.md](docs/API_Endpoints.md)** - Detailed API endpoint documentation
- **[QA_SYSTEM_ENHANCEMENTS.md](docs/QA_SYSTEM_ENHANCEMENTS.md)** - AI chatbot system documentation
- **[QUICKBOOKS_BUSINESS_LOGIC_UPDATE.md](docs/QUICKBOOKS_BUSINESS_LOGIC_UPDATE.md)** - QuickBooks integration details
- **[Feature Flags](docs/FEATURE_FLAGS.md)** - Feature flag usage instructions
- **[Testing Guidelines](docs/TESTING_GUIDELINES.md)** - Testing Guidelines

---

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

## Scripts

The `scripts/` directory contains utility scripts for:
- Database backup and restore
- Historical data processing
- Data cleanup and maintenance
- Performance optimization

---


