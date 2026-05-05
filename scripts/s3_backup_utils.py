"""
AWS S3 utilities for database backup uploads.

This module provides S3 upload functionality specifically for database backups,
separate from the main application's S3 utilities (mpi_backend/utils/s3_utils.py).
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


class S3BackupUploader:
    """Handles S3 uploads for database backups with progress reporting and verification."""

    def __init__(self, bucket_name: str, access_key: str, secret_key: str, region: str = 'us-east-1'):
        """
        Initialize S3 backup uploader.

        Args:
            bucket_name: S3 bucket name (e.g., 'devs-invoice')
            access_key: AWS access key ID
            secret_key: AWS secret access key
            region: AWS region (default: us-east-1)
        """
        self.bucket_name = bucket_name
        self.region = region

        # Configure boto3 with retry logic and timeouts
        retry_config = Config(
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'  # Exponential backoff
            },
            connect_timeout=30,
            read_timeout=300,  # 5 minutes for large files
            region_name=region
        )

        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=retry_config
        )

    def test_connection(self) -> bool:
        """
        Test S3 connection and bucket access.

        Returns:
            True if connection successful and bucket accessible, False otherwise
        """
        try:
            # Try to head the bucket to verify access
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"✓ S3 connection successful to bucket: {self.bucket_name}")
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.error(f"S3 bucket '{self.bucket_name}' does not exist")
            elif error_code == '403':
                logger.error(f"Access denied to S3 bucket '{self.bucket_name}'")
            else:
                logger.error(f"S3 connection error: {e}")
            return False
        except NoCredentialsError:
            logger.error("AWS credentials not found or invalid")
            return False
        except Exception as e:
            logger.error(f"S3 connection test failed: {e}")
            return False

    def get_s3_key_for_backup(self, file_name: str, backup_date: datetime) -> str:
        """
        Generate S3 key for backup file using date-based folder structure.

        Args:
            file_name: Backup filename (e.g., 'mpi_db_daily_20251111_163534.dump.gpg')
            backup_date: Backup date for folder naming

        Returns:
            S3 key in format: MM-DD-YYYY/filename
        """
        # Format date as MM-DD-YYYY
        date_folder = backup_date.strftime('%m-%d-%Y')
        return f"{date_folder}/{file_name}"

    def upload_backup_file(
        self,
        file_path: Path,
        backup_date: datetime,
        callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """
        Upload backup file to S3 with progress reporting.

        Args:
            file_path: Path to local backup file
            backup_date: Backup date for folder organization
            callback: Optional progress callback function(bytes_transferred)

        Returns:
            Tuple of (success: bool, s3_key: str)
        """
        if not file_path.exists():
            logger.error(f"Backup file not found: {file_path}")
            return False, ""

        s3_key = self.get_s3_key_for_backup(file_path.name, backup_date)

        try:
            # Get file size for progress reporting
            file_size = file_path.stat().st_size

            # Create progress callback wrapper if provided
            if callback:
                class ProgressPercentage:
                    def __init__(self, filename, filesize, callback_fn):
                        self._filename = filename
                        self._size = filesize
                        self._seen_so_far = 0
                        self._callback = callback_fn
                        self._last_percent = 0

                    def __call__(self, bytes_amount):
                        self._seen_so_far += bytes_amount
                        self._callback(self._seen_so_far)

                        # Log progress every 10%
                        percentage = (self._seen_so_far / self._size) * 100
                        if percentage - self._last_percent >= 10:
                            logger.info(f"Upload progress: {percentage:.0f}% "
                                      f"({self._seen_so_far / (1024*1024):.1f} MB / "
                                      f"{self._size / (1024*1024):.1f} MB)")
                            self._last_percent = percentage

                progress = ProgressPercentage(file_path.name, file_size, callback)
            else:
                progress = None

            # Upload file to S3
            logger.info(f"Uploading to s3://{self.bucket_name}/{s3_key}")

            with open(file_path, 'rb') as f:
                self.s3_client.upload_fileobj(
                    f,
                    self.bucket_name,
                    s3_key,
                    Callback=progress,
                    ExtraArgs={
                        'StorageClass': 'STANDARD_IA',  # Infrequent access - cheaper for backups
                        'ServerSideEncryption': 'AES256'  # Enable server-side encryption
                    }
                )

            logger.info(f"✓ Upload complete: s3://{self.bucket_name}/{s3_key}")
            return True, s3_key

        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            return False, ""
        except Exception as e:
            logger.error(f"Upload error: {e}", exc_info=True)
            return False, ""

    def upload_metadata_file(
        self,
        metadata_path: Path,
        backup_date: datetime
    ) -> Tuple[bool, str]:
        """
        Upload metadata JSON file to S3.

        Args:
            metadata_path: Path to local metadata file (.meta.json)
            backup_date: Backup date for folder organization

        Returns:
            Tuple of (success: bool, s3_key: str)
        """
        if not metadata_path.exists():
            logger.error(f"Metadata file not found: {metadata_path}")
            return False, ""

        s3_key = self.get_s3_key_for_backup(metadata_path.name, backup_date)

        try:
            logger.info(f"Uploading metadata to s3://{self.bucket_name}/{s3_key}")

            with open(metadata_path, 'rb') as f:
                self.s3_client.upload_fileobj(
                    f,
                    self.bucket_name,
                    s3_key,
                    ExtraArgs={
                        'ContentType': 'application/json',
                        'ServerSideEncryption': 'AES256'
                    }
                )

            logger.info(f"✓ Metadata uploaded: s3://{self.bucket_name}/{s3_key}")
            return True, s3_key

        except Exception as e:
            logger.error(f"Metadata upload error: {e}")
            return False, ""

    def verify_upload(self, s3_key: str, expected_checksum: str) -> bool:
        """
        Verify uploaded file by comparing checksums.

        Args:
            s3_key: S3 key of uploaded file
            expected_checksum: SHA256 checksum of local file

        Returns:
            True if checksums match, False otherwise
        """
        try:
            logger.info("Verifying S3 upload...")

            # Download file and compute checksum
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)

            sha256_hash = hashlib.sha256()
            for chunk in response['Body'].iter_chunks(chunk_size=4096):
                sha256_hash.update(chunk)

            s3_checksum = sha256_hash.hexdigest()

            if s3_checksum == expected_checksum:
                logger.info("✓ S3 upload verification successful - checksums match")
                return True
            else:
                logger.error(f"Checksum mismatch: expected {expected_checksum}, got {s3_checksum}")
                return False

        except Exception as e:
            logger.error(f"Upload verification failed: {e}")
            return False

    def list_backups(self, date_folder: Optional[str] = None) -> List[Dict]:
        """
        List backup files in S3 bucket.

        Args:
            date_folder: Optional specific date folder (MM-DD-YYYY format)

        Returns:
            List of backup metadata dictionaries
        """
        try:
            prefix = f"{date_folder}/" if date_folder else ""

            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )

            backups = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    # Skip metadata files in listing
                    if obj['Key'].endswith('.meta.json'):
                        continue

                    backups.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'],
                        'storage_class': obj.get('StorageClass', 'STANDARD')
                    })

            return backups

        except Exception as e:
            logger.error(f"Failed to list S3 backups: {e}")
            return []

    def delete_old_s3_backups(
        self,
        retention_daily: int,
        retention_weekly: int,
        retention_monthly: int
    ) -> int:
        """
        Delete old backups from S3 based on retention policy.

        Args:
            retention_daily: Days to keep daily backups
            retention_weekly: Days to keep weekly backups (weeks * 7)
            retention_monthly: Days to keep monthly backups (months * 30)

        Returns:
            Number of backups deleted
        """
        logger.info("Scanning S3 for old backups to delete...")

        deleted_count = 0
        now = datetime.now()

        try:
            # List all objects in bucket
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name)

            if 'Contents' not in response:
                logger.info("No backups found in S3")
                return 0

            for obj in response['Contents']:
                key = obj['Key']

                # Skip if not a backup file
                if not (key.endswith('.dump.gpg') or key.endswith('.sql.gpg') or key.endswith('.meta.json')):
                    continue

                try:
                    # Parse date from folder structure: MM-DD-YYYY/filename
                    parts = key.split('/')
                    if len(parts) < 2:
                        continue

                    date_folder = parts[0]
                    # Parse MM-DD-YYYY format
                    backup_date = datetime.strptime(date_folder, '%m-%d-%Y')
                    age_days = (now - backup_date).days

                    # Determine backup type from filename
                    filename = parts[1]
                    if '_daily_' in filename:
                        backup_type = 'daily'
                        max_age = retention_daily
                    elif '_weekly_' in filename:
                        backup_type = 'weekly'
                        max_age = retention_weekly
                    elif '_monthly_' in filename:
                        backup_type = 'monthly'
                        max_age = retention_monthly
                    else:
                        continue

                    # Delete if too old
                    if age_days > max_age:
                        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
                        deleted_count += 1
                        logger.info(f"Deleted old {backup_type} backup from S3: {key} (age: {age_days}d)")

                except ValueError as e:
                    logger.warning(f"Could not parse date from S3 key: {key}")
                    continue
                except Exception as e:
                    logger.warning(f"Error processing S3 object {key}: {e}")
                    continue

            logger.info(f"S3 cleanup complete: {deleted_count} backups deleted")
            return deleted_count

        except Exception as e:
            logger.error(f"S3 cleanup failed: {e}")
            return 0

    def delete_backup(self, s3_key: str) -> bool:
        """
        Delete a specific backup file from S3.

        Args:
            s3_key: S3 key of file to delete

        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Deleted from S3: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete {s3_key} from S3: {e}")
            return False

    def list_date_folders(self) -> List[str]:
        """
        List all date folders (MM-DD-YYYY format) in the S3 bucket.

        Returns:
            List of date folder names, sorted newest first
        """
        try:
            logger.info(f"Listing date folders in S3 bucket: {self.bucket_name}")

            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Delimiter='/'
            )

            date_folders = []
            if 'CommonPrefixes' in response:
                for prefix in response['CommonPrefixes']:
                    folder_name = prefix['Prefix'].rstrip('/')
                    # Validate it's in MM-DD-YYYY format
                    try:
                        datetime.strptime(folder_name, '%m-%d-%Y')
                        date_folders.append(folder_name)
                    except ValueError:
                        # Skip folders that don't match date format
                        continue

            # Sort by date (newest first)
            date_folders.sort(reverse=True, key=lambda x: datetime.strptime(x, '%m-%d-%Y'))

            logger.info(f"Found {len(date_folders)} date folders")
            return date_folders

        except Exception as e:
            logger.error(f"Failed to list date folders: {e}")
            return []

    def get_latest_backup_in_folder(self, date_folder: str) -> Optional[Tuple[str, str]]:
        """
        Get the latest backup file in a specific date folder.

        Args:
            date_folder: Date folder name (MM-DD-YYYY format)

        Returns:
            Tuple of (backup_key, metadata_key) or None if no backup found
        """
        try:
            logger.info(f"Searching for latest backup in folder: {date_folder}")

            # List all objects in the date folder
            prefix = f"{date_folder}/"
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )

            if 'Contents' not in response:
                logger.warning(f"No backups found in {date_folder}")
                return None

            # Filter for backup files (not metadata)
            backup_files = []
            for obj in response['Contents']:
                key = obj['Key']
                if key.endswith('.dump.gpg') or key.endswith('.sql.gpg'):
                    backup_files.append({
                        'key': key,
                        'last_modified': obj['LastModified']
                    })

            if not backup_files:
                logger.warning(f"No backup files found in {date_folder}")
                return None

            # Sort by last modified (newest first)
            backup_files.sort(key=lambda x: x['last_modified'], reverse=True)

            latest_backup = backup_files[0]
            backup_key = latest_backup['key']
            metadata_key = backup_key + '.meta.json'

            logger.info(f"Latest backup: {backup_key}")

            return (backup_key, metadata_key)

        except Exception as e:
            logger.error(f"Failed to get latest backup in folder {date_folder}: {e}")
            return None

    def download_file(self, s3_key: str, local_path: Path) -> bool:
        """
        Download a file from S3 to local path with progress reporting.

        Args:
            s3_key: S3 key of file to download
            local_path: Local file path to save to

        Returns:
            True if download successful, False otherwise
        """
        try:
            logger.info(f"Downloading from S3: {s3_key}")
            logger.info(f"Local destination: {local_path}")

            # Get file size for progress reporting
            try:
                head_response = self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
                file_size = head_response['ContentLength']

                class DownloadProgress:
                    def __init__(self, filename, filesize):
                        self._filename = filename
                        self._size = filesize
                        self._seen_so_far = 0
                        self._last_percent = 0

                    def __call__(self, bytes_amount):
                        self._seen_so_far += bytes_amount
                        percentage = (self._seen_so_far / self._size) * 100

                        # Log progress every 10%
                        if percentage - self._last_percent >= 10:
                            logger.info(f"Download progress: {percentage:.0f}% "
                                      f"({self._seen_so_far / (1024*1024):.1f} MB / "
                                      f"{self._size / (1024*1024):.1f} MB)")
                            self._last_percent = percentage

                progress = DownloadProgress(s3_key, file_size)

            except ClientError:
                # If head_object fails, download without progress
                progress = None
                file_size = None

            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # Download file
            with open(local_path, 'wb') as f:
                self.s3_client.download_fileobj(
                    self.bucket_name,
                    s3_key,
                    f,
                    Callback=progress
                )

            downloaded_size = local_path.stat().st_size
            logger.info(f"✓ Download complete: {downloaded_size / (1024*1024):.2f} MB")

            # Verify file size if we had it from head_object
            if file_size and downloaded_size != file_size:
                logger.error(f"File size mismatch: expected {file_size}, got {downloaded_size}")
                return False

            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.error(f"File not found in S3: {s3_key}")
            else:
                logger.error(f"S3 download failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            return False
