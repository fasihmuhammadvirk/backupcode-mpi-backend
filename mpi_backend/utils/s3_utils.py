import boto3
import os
import requests

from mpi_backend.config import S3_CLIENT, BUCKET_NAME


def upload_file(file_name, file_key):
    try:
        S3_CLIENT.upload_file(file_name, BUCKET_NAME, str(file_key)+'.pdf')
        print(f'Invoice with Key: {file_key} Uploaded')
    except Exception as e:
        print(f'{file_name} -> Failed during upload to S3 Bucket. Raised Exception-->{e}')


def get_presigned_url(file_key, expiration_time = 600):
    presigned_url = S3_CLIENT.generate_presigned_url(
        'get_object',
        Params={'Bucket': BUCKET_NAME, 'Key': str(file_key)+'.pdf'},
        ExpiresIn=expiration_time # set to expire after 10 minutes
    )
    return presigned_url
