import os
import boto3
from pathlib import Path
from dotenv import load_dotenv
import pytz

dotenv_path = Path('.env')
load_dotenv(dotenv_path=dotenv_path)

TIMEZONE = pytz.timezone('America/New_York')
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
INVOICE_DOWNLOAD_FOLDER = os.getenv("INVOICE_DOWNLOAD_FOLDER", "mpi_backend/storage")

SUPPLIERS = ['BMW Plumbing Supplies', 'World Wide Plumbing', 'Y & S Plumbing Supply', 'Supreme Plumbing Supply',
             'Pyramid Plumbing', 'ABC Opus Services', 'Park Plumbing Supply', 'Gotham Plumbing Supply',
             'FW Webb Plumbing Supply', 'Flow Mark Plumbing Supply', 'AF Supply','Lion Hvac Supplies']

PROCESSABLE_SUPPLIERS = ['BMW Plumbing Supplies', 'World Wide Plumbing', 'Y & S Plumbing Supply',
                         'Supreme Plumbing Supply', 'Pyramid Plumbing', 'ABC Opus Services', 'Park Plumbing Supply',
                         'Gotham Plumbing Supply', 'FW Webb Plumbing Supply', 'Flow Mark Plumbing Supply', 'Plumbing Exchange',
                         'AF Supply', 'Lion Hvac Supplies']

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost/dbname")

# JWT Configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# File Upload Configuration
BASE_DIR = Path(__file__).resolve().parent.parent.parent
INVOICE_DOWNLOAD_FOLDER = os.getenv("INVOICE_DOWNLOAD_FOLDER", str(BASE_DIR / "mpi_backend" / "storage"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Export Optimization Configuration
EXPORT_BATCH_SIZE = int(os.getenv("EXPORT_BATCH_SIZE", "1000"))  # Records per batch for large exports
EXPORT_USE_OPTIMIZED = os.getenv("EXPORT_USE_OPTIMIZED", "true").lower() == "true"  # Enable optimized exports by default
EXPORT_MAX_RECORDS_BEFORE_BATCH = int(os.getenv("EXPORT_MAX_RECORDS_BEFORE_BATCH", "5000"))  # When to use batch processing
EXPORT_ENABLE_PROGRESS_LOGGING = os.getenv("EXPORT_ENABLE_PROGRESS_LOGGING", "true").lower() == "true"  # Show progress for large exports

# S3 Configuration (if applicable)
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
