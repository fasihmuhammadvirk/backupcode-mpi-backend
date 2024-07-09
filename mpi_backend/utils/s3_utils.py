import boto3
import os
import requests

from mpi_backend.config import AWS_SERVER_PUBLIC_KEY,AWS_SERVER_SECRET_KEY,REGION, BUCKET_NAME


def upload_file(file_name, file_key, is_invoice=True):
    try:
        s3_client = boto3.client('s3', aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
                                 aws_secret_access_key=AWS_SERVER_SECRET_KEY,
                                 region_name=REGION)

        if is_invoice:
            s3_client.upload_file(file_name, BUCKET_NAME, str(file_key) + '.pdf')
            print(f'Invoice with Key: {file_key} Uploaded')
        else:
            s3_client.upload_file(file_name, BUCKET_NAME, file_key)
            print(f'File with Key: {file_key} Uploaded')
    except Exception as e:
        print(f'{file_name} -> Failed during upload to S3 Bucket. Raised Exception-->{e}')


def get_presigned_url(file_key, expiration_time = 180, is_invoice=True):

    s3_client = boto3.client('s3', aws_access_key_id=AWS_SERVER_PUBLIC_KEY,
                             aws_secret_access_key=AWS_SERVER_SECRET_KEY,
                             region_name=REGION)

    if is_invoice:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': str(file_key)+'.pdf'},
            ExpiresIn=expiration_time # set to expire after 10 minutes
        )
    else:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': file_key},
            ExpiresIn=expiration_time
        )
    return presigned_url
