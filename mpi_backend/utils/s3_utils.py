import boto3
import logging
from typing import Optional

from mpi_backend.config import (
    AWS_SERVER_PUBLIC_KEY, 
    AWS_SERVER_SECRET_KEY, 
    REGION, 
    BUCKET_NAME
)

# Set up logging
logger = logging.getLogger(__name__)


def upload_file(file_name, file_key, is_invoice=True):
    """Upload a file to S3 bucket"""
    try:
        s3_client = boto3.client(
            's3', 
            aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=AWS_SERVER_SECRET_KEY,
            region_name=REGION
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
                BUCKET_NAME, 
                s3_key,
                ExtraArgs={
                    'ContentDisposition': 'inline',
                    'ContentType': 'application/pdf'
                }
            )
            logger.info(f'Invoice with Key: {s3_key} Uploaded')
        else:
            s3_client.upload_file(file_name, BUCKET_NAME, file_key)
            logger.info(f'File with Key: {file_key} Uploaded')
    except Exception as e:
        err_msg = f'{file_name} -> Failed during upload to S3 Bucket. '
        logger.error(f"{err_msg}Raised Exception-->{e}")


def get_presigned_url(file_key, expiration_time=180, is_invoice=True) -> Optional[str]:
    """Generate a presigned URL for an S3 object"""
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=AWS_SERVER_SECRET_KEY,
            region_name=REGION
        )

        if is_invoice:
            # Smart handling of PDF extension to prevent double .pdf
            file_key_str = str(file_key)
            if not file_key_str.lower().endswith('.pdf'):
                key = file_key_str + '.pdf'
            else:
                key = file_key_str
            
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': BUCKET_NAME, 
                    'Key': key,
                    'ResponseContentDisposition': 'inline',
                    'ResponseContentType': 'application/pdf'
                },
                ExpiresIn=expiration_time
            )
        else:
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': BUCKET_NAME, 'Key': file_key},
                ExpiresIn=expiration_time
            )
        return presigned_url
    except Exception as e:
        logger.error(
            f"Error generating presigned URL for {file_key}: {str(e)}"
        )
        return None
