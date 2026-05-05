import boto3
from botocore.config import Config
import logging
import os
from os import PathLike
from typing import Optional, Union

from mpi_backend.config import (
    AWS_SERVER_PUBLIC_KEY,
    AWS_SERVER_SECRET_KEY,
    REGION,
    BUCKET_NAME,
    INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
    INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
    INVOICES_PDFS_BUCKET_NAME,
    INVOICES_PDFS_REGION,
    S3_PRESIGNED_URL_EXPIRY,
)

# Set up logging
logger = logging.getLogger(__name__)


def upload_file(file_name, file_key, is_invoice=True) -> bool:
    """Upload a file to S3 bucket.

    Returns:
        bool: True if upload succeeded, False otherwise.
    """
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
            region_name=INVOICES_PDFS_REGION
        )

        if is_invoice:
            # Smart handling of PDF extension to prevent double .pdf
            file_key_str = str(file_key)
            if not file_key_str.lower().endswith('.pdf'):
                s3_key = file_key_str + '.pdf'
            else:
                s3_key = file_key_str

            s3_client.upload_file(
                file_name,
                INVOICES_PDFS_BUCKET_NAME,
                s3_key,
                ExtraArgs={
                    'ContentDisposition': 'inline',
                    'ContentType': 'application/pdf'
                }
            )
            logger.info("Invoice with Key uploaded: %s", s3_key)
        else:
            s3_client.upload_file(file_name, INVOICES_PDFS_BUCKET_NAME, file_key)
            logger.info("File uploaded: %s", file_key)
        return True
    except Exception as e:
        err_msg = f"{file_name} -> Failed during upload to S3 Bucket. "
        logger.error("%s Raised Exception-->%s", err_msg, str(e))
        return False


def upload_export_and_get_url(
    file_path: Union[str, PathLike[str]],
    file_key: Optional[str] = None,
    expiration_time: int = S3_PRESIGNED_URL_EXPIRY,
) -> str:
    """Upload an export file and return its presigned URL.

    Args:
        file_path: Local export file path. Deleted after upload is attempted.
        file_key: Optional S3 key. Defaults to ``Exports/<filename>``.
        expiration_time: Presigned URL expiry in seconds.
    """
    file_path_str = os.fspath(file_path)
    export_key = file_key or f"Exports/{os.path.basename(file_path_str)}"

    try:
        if not upload_file(file_path_str, file_key=export_key, is_invoice=False):
            raise RuntimeError("Failed to upload export file to S3")

        download_url = get_presigned_url(
            file_key=export_key,
            expiration_time=expiration_time,
            is_invoice=False,
        )
        if not download_url:
            raise RuntimeError("Failed to generate download URL")

        return download_url
    finally:
        try:
            if os.path.exists(file_path_str):
                os.remove(file_path_str)
        except OSError as cleanup_error:
            logger.warning(
                "Failed to clean up local export file %s: %s",
                file_path_str,
                cleanup_error,
            )


def download_s3_file(file_key: str, local_path: str, is_invoice: bool = True) -> bool:
    """Download a file from S3 bucket.

    Returns:
        bool: True if download succeeded, False otherwise.
    """
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
            region_name=INVOICES_PDFS_REGION
        )

        # Smart handling of PDF extension
        s3_key = str(file_key)
        if is_invoice and not s3_key.lower().endswith('.pdf'):
            s3_key += '.pdf'

        s3_client.download_file(INVOICES_PDFS_BUCKET_NAME, s3_key, local_path)
        logger.info("File downloaded: %s -> %s", s3_key, local_path)
        return True
    except Exception as e:
        logger.error("Failed to download %s from S3: %s", file_key, str(e))
        return False


def get_presigned_url(
    file_key,
    expiration_time: int = 180,
    is_invoice: bool = True,
) -> Optional[str]:
    """Generate a presigned URL for an S3 object"""
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
            region_name=INVOICES_PDFS_REGION
        )

        if is_invoice:
            # Smart handling of PDF extension to prevent double .pdf
            file_key_str = str(file_key)
            if not file_key_str.lower().endswith('.pdf'):
                key = file_key_str + '.pdf'
            else:
                key = file_key_str
            
            # Try multiple key patterns to handle case differences and
            # double extensions
            possible_keys = [key]
            
            # If key ends with .pdf, try with .PDF
            if key.lower().endswith('.pdf'):
                base_name = key[:-4]  # Remove .pdf
                possible_keys.extend([
                    base_name + '.PDF',
                    base_name + '.PDF.pdf',  # Handle double extension case
                ])
            
            # If key ends with .PDF, try with .pdf
            elif key.upper().endswith('.PDF'):
                base_name = key[:-4]  # Remove .PDF
                possible_keys.extend([
                    base_name + '.pdf',
                    base_name + '.PDF.pdf',  # Handle double extension case
                ])
            
            # Also try the original key with .pdf added (double extension case)
            if not key.lower().endswith('.pdf.pdf'):
                possible_keys.append(key + '.pdf')
            
            # CRITICAL FIX: Try the exact pattern that exists in S3
            # If the key ends with .PDF, also try .PDF.pdf (double extension)
            if key.upper().endswith('.PDF'):
                possible_keys.append(key + '.pdf')
            
            logger.info("Trying possible keys: %s", possible_keys)
            
            # Try each possible key
            for try_key in possible_keys:
                try:
                    presigned_url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={
                            'Bucket': INVOICES_PDFS_BUCKET_NAME,
                            'Key': try_key,
                            'ResponseContentDisposition': 'inline',
                            'ResponseContentType': 'application/pdf'
                        },
                        ExpiresIn=expiration_time
                    )
                    logger.info("Generated presigned URL: %s", try_key)
                    return presigned_url
                except s3_client.exceptions.NoSuchKey:
                    logger.warning("Key not found: %s", try_key)
                    continue
                except Exception as e:
                    logger.warning("Error with key %s: %s", try_key, str(e))
                    continue
            
            # If we get here, none of the keys worked
            logger.error(
                "Failed to generate presigned URL for any of the keys: %s",
                possible_keys,
            )
            return None
        else:
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': INVOICES_PDFS_BUCKET_NAME, 'Key': file_key},
                ExpiresIn=expiration_time
            )
            return presigned_url
    except Exception as e:
        logger.error(
            "Error generating presigned URL for %s: %s",
            file_key,
            str(e),
        )
        return None


def get_invoice_pdf_presigned_url(
    file_key: str,
    expiration_time: int = 180,
) -> Optional[str]:
    """
    Generate a presigned URL for invoice PDFs from the dedicated bucket.

    Args:
        file_key: The full S3 path to the PDF file
                  (e.g., 'invoices/bmwpsupply_at_gmail.com/2026-01/19bb4e4f85460b3f_doc00076757.pdf')
        expiration_time: URL expiration time in seconds (default: 180)

    Returns:
        Presigned URL string or None if generation fails
    """
    try:
        # Configure for path-style addressing (required for buckets with dots)
        s3_config = Config(
            s3={'addressing_style': 'path'},
            signature_version='s3v4'
        )

        s3_client = boto3.client(
            's3',
            aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
            region_name=INVOICES_PDFS_REGION,
            config=s3_config
        )

        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': INVOICES_PDFS_BUCKET_NAME,
                'Key': file_key,
                'ResponseContentDisposition': 'inline',
                'ResponseContentType': 'application/pdf'
            },
            ExpiresIn=expiration_time
        )
        logger.info("Generated presigned URL for invoice PDF: %s", file_key)
        return presigned_url
    except Exception as e:
        logger.error(
            "Error generating presigned URL for invoice PDF %s: %s",
            file_key,
            str(e),
        )
        return None


def delete_file_from_s3(file_key: str, is_invoice: bool = True) -> bool:
    """
    Delete a file from S3. Returns True if any variant was deleted.
    For invoices, tries multiple key variants to account for .pdf/.PDF and
    double extensions.
    """
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=AWS_SERVER_SECRET_KEY,
            region_name=REGION
        )

        keys_to_try = []
        if is_invoice:
            key = str(file_key)
            # Normalize to include .pdf if missing
            if not key.lower().endswith('.pdf'):
                key_pdf = key + '.pdf'
            else:
                key_pdf = key

            keys_to_try.append(key_pdf)

            # Try variations similar to get_presigned_url
            base = key_pdf[:-4] if key_pdf.lower().endswith('.pdf') else key_pdf
            keys_to_try.extend(
                [base + '.PDF', base + '.PDF.pdf', base + '.pdf.pdf']
            )
        else:
            keys_to_try.append(str(file_key))

        deleted_any = False
        for try_key in dict.fromkeys(keys_to_try):
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=try_key)
                logger.info("Deleted S3 object: %s", try_key)
                deleted_any = True
            except s3_client.exceptions.NoSuchKey:
                logger.debug("S3 key not found for deletion: %s", try_key)
                continue
            except Exception as e:
                logger.debug("Error deleting S3 key %s: %s", try_key, str(e))
                continue

        if not deleted_any:
            logger.warning("No matching S3 key deleted for base key: %s", file_key)
        return deleted_any
    except Exception as e:
        logger.error("Failed to delete from S3 for key %s: %s", file_key, str(e))
        return False
