import os
from pathlib import Path
from dotenv import load_dotenv
import pytz

# Determine the project root directory by finding the location of `pyproject.toml`
# This makes the .env file loading robust, regardless of where the script is run from
project_root = Path(__file__).resolve().parent.parent.parent
dotenv_path = project_root / '.env'
load_dotenv(dotenv_path=dotenv_path)

TIMEZONE = pytz.timezone('America/New_York')
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
LOG_LEVEL = os.getenv("LOG_LEVEL")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USERNAME = os.getenv("POSTGRES_USERNAME")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
SECRET_KEY = os.getenv("SECRET_KEY")

AWS_SERVER_PUBLIC_KEY = os.getenv("PUBLIC_ACCESS_KEY")
AWS_SERVER_SECRET_KEY = os.getenv("SECRET_ACCESS_KEY")
REGION = os.getenv("REGION")
BUCKET_NAME = os.getenv("BUCKET_NAME")
INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY=os.getenv("INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY")
INVOICES_PDFS_AWS_SERVER_SECRET_KEY=os.getenv("INVOICES_PDFS_AWS_SERVER_SECRET_KEY")
INVOICES_PDFS_BUCKET_NAME=os.getenv("INVOICES_PDFS_BUCKET_NAME")
INVOICES_PDFS_REGION=os.getenv("INVOICES_PDFS_REGION", "us-east-2")

# Handle the port safely for different environments
def get_db_port():
    port = POSTGRES_PORT
    if port is None or (isinstance(port, str) and (port.strip() == '' or port.lower() == 'none')):
        return 5432
    try:
        return int(port)
    except (ValueError, TypeError):
        return 5432

SQLALCHEMY_DATABASE_URI = f"postgresql://{POSTGRES_USERNAME}:" \
                          f"{POSTGRES_PASSWORD}@" \
                          f"{POSTGRES_HOST}:" \
                          f"{get_db_port()}/" \
                          f"{POSTGRES_DB}"

SMTP_SERVER = os.getenv("SMTP_SERVER")
LOGIN_EMAIL = os.getenv("LOGIN_EMAIL")
LOGIN_PWD = os.getenv("LOGIN_PWD")

# Gmail API Configuration (Service Account)
GOOGLE_SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64")
GOOGLE_SERVICE_ACCOUNT_PATH = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_PATH",
    str(Path(__file__).parent.parent.parent / "service-account.json")
)
GMAIL_USER_EMAIL = os.getenv("GMAIL_USER_EMAIL")  # Email inbox to access (required for Gmail API)
INVOICE_DOWNLOAD_FOLDER = os.getenv("INVOICE_DOWNLOAD_FOLDER", "mpi_backend/storage")

# Email Scan & Download Configuration
EMAIL_SCAN_HOURS = int(os.getenv("EMAIL_SCAN_HOURS", "24"))
EMAIL_BATCH_SIZE = int(os.getenv("EMAIL_BATCH_SIZE", "50"))
EMAIL_MAX_BATCHES = int(os.getenv("EMAIL_MAX_BATCHES", "1"))
EMAIL_MAX_RETRIES = int(os.getenv("EMAIL_MAX_RETRIES", "3"))

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost/dbname")

# JWT Configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # Fallback for legacy code
ACCESS_TOKEN_REMEMBER_ME_DAYS = 7  # Token expiration for "Remember Me" enabled (7 days)
ACCESS_TOKEN_SESSION_HOURS = 8  # Token expiration for session-only login (8 hours)

# File Upload Configuration
BASE_DIR = Path(__file__).resolve().parent.parent.parent
INVOICE_DOWNLOAD_FOLDER = os.getenv("INVOICE_DOWNLOAD_FOLDER", str(BASE_DIR / "mpi_backend" / "storage"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Export Optimization Configuration - Optimized for sub-100s processing
EXPORT_BATCH_SIZE = int(os.getenv("EXPORT_BATCH_SIZE", "500"))  # Records per batch for large exports (reduced for faster processing)
EXPORT_USE_OPTIMIZED = os.getenv("EXPORT_USE_OPTIMIZED", "true").lower() == "true"  # Enable optimized exports by default
EXPORT_MAX_RECORDS_BEFORE_BATCH = int(os.getenv("EXPORT_MAX_RECORDS_BEFORE_BATCH", "2000"))  # Lower threshold for earlier batch processing

# ENHANCED QuickBooks Priority Configuration with MIGRATE-ALL absolute priority
QB_PRIORITY_MODE = os.getenv("QB_PRIORITY_MODE", "true").lower() == "true"  # Priority mode for QB exports
QB_DEDICATED_POOL_SIZE = int(os.getenv("QB_DEDICATED_POOL_SIZE", "15"))  # Dedicated DB connections for QB
QB_MAX_CONCURRENT_EXPORTS = int(os.getenv("QB_MAX_CONCURRENT_EXPORTS", "3"))  # Max concurrent QB exports
QB_PAUSE_BACKGROUND_JOBS = os.getenv("QB_PAUSE_BACKGROUND_JOBS", "true").lower() == "true"  # Pause non-critical jobs during QB export

# NEW: MIGRATE-ALL absolute priority settings
MIGRATE_ALL_ABSOLUTE_PRIORITY = os.getenv("MIGRATE_ALL_ABSOLUTE_PRIORITY", "true").lower() == "true"  # MIGRATE-ALL gets absolute priority
MIGRATE_ALL_TIMEOUT = int(os.getenv("MIGRATE_ALL_TIMEOUT", "900"))  # 15 minutes for migrate-all operations
MIGRATE_ALL_PAUSE_ALL_JOBS = os.getenv("MIGRATE_ALL_PAUSE_ALL_JOBS", "true").lower() == "true"  # Pause ALL jobs during migrate-all

# CRITICAL: Timeout Configuration for QuickBooks Operations
# These settings prevent operations from getting stuck and ensure reliable processing
QB_OPERATION_TIMEOUT = int(os.getenv("QB_OPERATION_TIMEOUT", "600"))  # 10 minutes max for QB operations
QB_CHUNK_SIZE = int(os.getenv("QB_CHUNK_SIZE", "500"))  # Process large datasets in chunks of 500 invoices
QB_CHUNK_DELAY = float(os.getenv("QB_CHUNK_DELAY", "1.0"))  # 1 second delay between chunks
QB_PROGRESS_UPDATE_INTERVAL = int(os.getenv("QB_PROGRESS_UPDATE_INTERVAL", "10"))  # Update progress every 10%

# HTTP Request Timeout Configuration
REQUEST_TIMEOUT_DEFAULT = int(os.getenv("REQUEST_TIMEOUT_DEFAULT", "30"))  # 30 seconds
REQUEST_TIMEOUT_MIGRATE_ALL = int(os.getenv("REQUEST_TIMEOUT_MIGRATE_ALL", "900"))  # 15 minutes
REQUEST_TIMEOUT_QUICKBOOKS = int(os.getenv("REQUEST_TIMEOUT_QUICKBOOKS", "600"))  # 10 minutes
REQUEST_TIMEOUT_EXPORT = int(os.getenv("REQUEST_TIMEOUT_EXPORT", "1800"))  # 30 minutes

# Database Connection Timeout Configuration
DB_CONNECTION_TIMEOUT = int(os.getenv("DB_CONNECTION_TIMEOUT", "30"))  # 30 seconds
DB_QUERY_TIMEOUT = int(os.getenv("DB_QUERY_TIMEOUT", "300"))  # 5 minutes
DB_BULK_OPERATION_TIMEOUT = int(os.getenv("DB_BULK_OPERATION_TIMEOUT", "1800"))  # 30 minutes

# S3 Upload Timeout Configuration - UNLIMITED PERFORMANCE
S3_UPLOAD_TIMEOUT = int(os.getenv("S3_UPLOAD_TIMEOUT", "0"))  # NO TIMEOUT
S3_PRESIGNED_URL_EXPIRY = int(os.getenv("S3_PRESIGNED_URL_EXPIRY", "86400"))  # 24 hours

# Performance Monitoring Configuration
PERFORMANCE_LOGGING_ENABLED = os.getenv("PERFORMANCE_LOGGING_ENABLED", "true").lower() == "true"
PERFORMANCE_LOG_SLOW_QUERIES = int(os.getenv("PERFORMANCE_LOG_SLOW_QUERIES", "5"))  # Log queries slower than 5 seconds

# S3 Configuration (if applicable)
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
# File Upload Safety Limits
MAX_BULK_UPLOAD_COUNT = int(os.getenv("MAX_BULK_UPLOAD_COUNT", "50"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
MAX_TOTAL_BULK_UPLOAD_SIZE_MB = int(os.getenv("MAX_TOTAL_BULK_UPLOAD_SIZE_MB", "50"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Elementary Report Configuration
ELEMENTARY_S3_BUCKET_NAME = os.getenv("ELEMENTARY_S3_BUCKET_NAME", "")
ELEMENTARY_S3_REGION = os.getenv("ELEMENTARY_S3_REGION", "us-east-2")
ELEMENTARY_REPORT_ENABLED = os.getenv("ELEMENTARY_REPORT_ENABLED", "false").lower() == "true"
