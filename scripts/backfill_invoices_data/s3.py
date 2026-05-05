import boto3
from botocore.exceptions import (
    NoCredentialsError,
    PartialCredentialsError
)
import os
from pathlib import Path
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / '.env')

# Use same credentials/bucket as gmail_downloader for queue mode
# Falls back to legacy vars for backwards compatibility with s3/local modes
AWS_ACCESS_KEY_ID = os.getenv("INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY") or os.getenv("PUBLIC_ACCESS_KEY", "")
AWS_SECRET_ACCESS_KEY = os.getenv("INVOICES_PDFS_AWS_SERVER_SECRET_KEY") or os.getenv("SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION = os.getenv("REGION", "us-east-1")

bucket_name = os.getenv("INVOICES_PDFS_BUCKET_NAME") or os.getenv("BUCKET_NAME", "nl-mpi-storage")
local_dir = f"{project_root}/invoices"


def download_file_from_s3(s3_file_key):
    """
    Download a file from an S3 bucket to the local filesystem.
    
    Downloads the specified file from the configured S3 bucket and saves it
    to a local directory (invoices/ in the project root). The local filename
    is extracted from the S3 key, preserving the original filename.
    
    Args:
        s3_file_key: The S3 key (path) of the file in the bucket.
            Format is typically "{supplier_name}/{invoice_id}.pdf"
    
    Returns:
        str or None: Local file path where the file was saved if successful,
            None if download failed (credentials error, network error, etc.).
    
    Environment Variables Used:
        PUBLIC_ACCESS_KEY: AWS access key ID
        SECRET_ACCESS_KEY: AWS secret access key
        REGION: AWS region (default: "us-east-1")
        BUCKET_NAME: S3 bucket name (default: "nl-mpi-storage")
    
    Note:
        The local directory (invoices/) is created if it doesn't exist.
        AWS credential errors are logged with specific error messages.
        All exceptions are caught, logged, and None is returned.
    """
    try:
        logger.info(f"Downloading file from S3: {s3_file_key}")
        # Initialize a session using Amazon S3
        s3 = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        )

        # Extract filename from S3 key
        # Handle paths like "BMW Plumbing Supplies/invoice_id.pdf"
        filename = os.path.basename(s3_file_key)
        if not filename:
            # If no filename in key, use the last part of the path
            filename = (
                s3_file_key.split('/')[-1] or
                f"{s3_file_key.replace('/', '_')}.pdf"
            )

        # Create full local file path
        local_file_path = os.path.join(local_dir, filename)

        # Create directory if it doesn't exist
        Path(local_dir).mkdir(parents=True, exist_ok=True)

        # Download the file
        s3.download_file(bucket_name, s3_file_key, local_file_path)
        logger.info(
            f"File '{s3_file_key}' downloaded successfully to "
            f"'{local_file_path}'"
        )
        return local_file_path

    except NoCredentialsError:
        logger.exception(
            "Error: No AWS credentials found. "
            "Please configure your AWS credentials."
        )
        return None
    except PartialCredentialsError:
        logger.exception(
            "Error: Incomplete AWS credentials found. "
            "Please check your AWS credentials."
        )
        return None
    except Exception as e:
        logger.exception(f"Error downloading file: {e}")
        return None
