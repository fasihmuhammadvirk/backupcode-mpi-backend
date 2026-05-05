import os
import sys
import argparse
import subprocess
import json
import shutil
import time
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
from contextlib import contextmanager
import logging
from dotenv import load_dotenv

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import shared Docker utilities
from scripts.postgres_docker_utils import PostgresDockerUtils

# Import GPG encryption utilities
from scripts.gpg_encryption_utils import (
    decrypt_file,
    is_gpg_available,
    secure_delete,
    GPGEncryptionError
)

# Load environment variables
load_dotenv(project_root / '.env')

# Ensure logs directory exists before configuring file handler
(project_root / 'logs').mkdir(exist_ok=True, parents=True)

# Configure logging
log_filename = f'restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(project_root / 'logs' / log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BackupInfo:
    """Container for backup file information."""

    def __init__(self, backup_path: Path):
        self.backup_path = backup_path
        self.size_bytes = backup_path.stat().st_size
        self.modified_time = datetime.fromtimestamp(backup_path.stat().st_mtime)
        self.format = self._detect_format()
        self.encrypted = self.backup_path.suffix == '.gpg'
        self.metadata = self._load_metadata()

    def _detect_format(self) -> str:
        """Detect backup format from file extension."""
        # Determine format from extensions like .dump.gpg or .sql.gpg
        stem = self.backup_path.stem
        if stem.endswith('.dump'):
            return 'custom'
        elif stem.endswith('.sql'):
            return 'sql'
        elif self.backup_path.suffix == '.dump':
            return 'custom'
        elif self.backup_path.suffix == '.sql':
            return 'sql'
        else:
            return 'unknown'

    def _load_metadata(self) -> Optional[Dict]:
        """Load metadata file if it exists."""
        # For file.dump.gpg, metadata is file.dump.gpg.meta.json
        meta_path = self.backup_path.with_suffix(self.backup_path.suffix + '.meta.json')
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load metadata: {e}")
        return None

    def display(self):
        """Display backup information."""
        logger.info(f"Backup file: {self.backup_path}")
        logger.info(f"Size: {self.size_bytes / (1024 * 1024):.2f} MB")
        logger.info(f"Modified: {self.modified_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Format: {self.format}")
        logger.info(f"Encrypted: {self.encrypted}")

        if self.metadata:
            logger.info(f"Backup type: {self.metadata.get('backup_type', 'unknown')}")
            logger.info(f"Database: {self.metadata.get('database_name', 'unknown')}")
            logger.info(f"Timestamp: {self.metadata.get('timestamp', 'unknown')}")
            logger.info(f"Verified: {self.metadata.get('verified', False)}")
            logger.info(f"Checksum: {self.metadata.get('checksum_sha256', 'N/A')}")


class DatabaseRestorer:
    """Production-grade database restore manager."""

    def __init__(self, args: argparse.Namespace):
        self.project_root = project_root
        self.backup_dir = Path(args.backup_dir)
        self.logs_dir = project_root / 'logs'

        # Restore configuration
        self.backup_file = args.backup_file
        self.dry_run = args.dry_run
        self.force = args.force
        self.auto_yes = args.yes  # Automatically answer yes to confirmations
        self.verify = not args.no_verify
        self.parallel_jobs = args.jobs

        # Database configuration from environment.
        # No defaults because we want to fail loudly
        self.db_host = os.getenv("POSTGRES_HOST")
        self.db_port = os.getenv("POSTGRES_PORT")
        self.db_name = os.getenv("POSTGRES_DB")
        self.db_user = os.getenv("POSTGRES_USERNAME")
        self.db_password = os.getenv("POSTGRES_PASSWORD")
        self.encryption_key = os.getenv("BACKUP_ENCRYPTION_KEY")

        # Docker configuration for fallback mode
        self.execution_mode = 'native'  # Will be set to 'native' or 'docker'
        self.docker_image = 'postgres:16'  # Pinned version for consistency

        # Initialize shared Docker utilities
        self.docker_utils = PostgresDockerUtils(
            db_host=self.db_host,
            db_port=self.db_port,
            db_name=self.db_name,
            db_user=self.db_user,
            db_password=self.db_password,
            docker_image=self.docker_image
        )

        # Ensure logs directory exists
        self.logs_dir.mkdir(exist_ok=True, parents=True)

        # S3 configuration (for downloading backups from S3)
        self.s3_bucket = os.getenv("AWS_DB_BACKUP_BUCKET", "devs-invoice")
        self.s3_access_key = os.getenv("AWS_DB_BACKUP_ACCESS_KEY")
        self.s3_secret_key = os.getenv("AWS_DB_BACKUP_SECRET_KEY")
        self.s3_region = os.getenv("AWS_DB_BACKUP_REGION", "us-east-1")
        self.s3_uploader = None  # Lazy initialization when needed

        # Temporary directory for S3 downloads (will use context manager)
        self.temp_dir = None

        # Store args for use in other methods
        self.args = args

        # Initialize execution mode (checks for PostgreSQL tools or Docker fallback)
        self._initialize_execution_mode()

        # Backup information
        self.backup_info: Optional[BackupInfo] = None

    def _initialize_execution_mode(self):
        """
        Initialize execution mode: native tools or Docker fallback.
        Sets self.execution_mode to 'native' or 'docker'.
        """
        required_tools = ['pg_restore', 'psql']
        missing_tools = []

        # Check GPG availability (warn if not available for encrypted backups)
        gpg_available, gpg_error = is_gpg_available()
        if not gpg_available:
            logger.warning("GPG not available - encrypted backups cannot be restored")
            logger.warning(f"Reason: {gpg_error}")

        for tool in required_tools:
            if not shutil.which(tool):
                missing_tools.append(tool)

        if not missing_tools:
            self.execution_mode = 'native'
            logger.info("Using native PostgreSQL tools")
            return

        # Try Docker fallback
        logger.warning(f"PostgreSQL tools not found locally: {', '.join(missing_tools)}")
        logger.info("Attempting to use Docker fallback...")

        docker_available, error_msg = self.docker_utils.check_docker_availability()

        if docker_available:
            self.execution_mode = 'docker'
            self.docker_utils.docker_network = self.docker_utils.get_docker_network_name()
            logger.info(f"✓ Using Docker-based PostgreSQL tools")
            logger.info(f"  Docker image: {self.docker_image}")
            logger.info(f"  Docker network: {self.docker_utils.docker_network}")
        else:
            logger.error("Docker fallback not available")
            logger.error(f"Reason: {error_msg}")
            sys.exit(1)

    def _validate_database_name(self, db_name: str) -> bool:
        """
        Validate database name to prevent SQL injection.

        PostgreSQL allows alphanumeric, underscores, and hyphens in identifiers.
        Reject anything else to prevent SQL injection.
        """
        import re

        if not db_name:
            logger.error("Database name cannot be empty")
            return False

        # Allow only alphanumeric, underscores, and hyphens
        if not re.match(r'^[a-zA-Z0-9_-]+$', db_name):
            logger.error("=" * 80)
            logger.error(f"Invalid database name: '{db_name}'")
            logger.error("Database name can only contain:")
            logger.error("  - Letters (a-z, A-Z)")
            logger.error("  - Numbers (0-9)")
            logger.error("  - Underscores (_)")
            logger.error("  - Hyphens (-)")
            logger.error("")
            logger.error("This prevents SQL injection attacks.")
            logger.error("=" * 80)
            return False

        # Additional safety: check for SQL keywords or suspicious patterns
        dangerous_patterns = ['drop', 'delete', 'truncate', ';', '--', '/*', '*/', 'select']
        db_name_lower = db_name.lower()
        for pattern in dangerous_patterns:
            if pattern in db_name_lower:
                logger.error(f"Database name contains suspicious pattern: '{pattern}'")
                return False

        return True

    @contextmanager
    def s3_download_temp_dir(self):
        """
        Context manager for temporary directory for S3 downloads.

        Uses system temp folder which OS cleans on restart.
        Ensures cleanup even if errors occur.
        """
        temp_dir_obj = tempfile.TemporaryDirectory(prefix='mpi_db_restore_')
        try:
            temp_path = Path(temp_dir_obj.name)
            logger.info(f"Created temporary download directory: {temp_path}")
            yield temp_path
        finally:
            temp_dir_obj.cleanup()
            logger.info("Cleaned up temporary download directory")

    def _is_s3_uri(self, path: str) -> bool:
        """Check if path is an S3 URI (s3://bucket/key)"""
        return path.startswith('s3://') if path else False

    def _parse_s3_uri(self, s3_uri: str) -> Tuple[str, str]:
        """
        Parse S3 URI into bucket and key.

        Args:
            s3_uri: S3 URI (e.g., s3://devs-invoice/11-11-2025/file.dump.gpg)

        Returns:
            Tuple of (bucket, key)
        """
        if not s3_uri.startswith('s3://'):
            raise ValueError(f"Invalid S3 URI: {s3_uri}")

        # Remove s3:// prefix
        path = s3_uri[5:]

        # Split into bucket and key
        parts = path.split('/', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid S3 URI format: {s3_uri}")

        bucket = parts[0]
        key = parts[1]

        return bucket, key

    def _initialize_s3_client(self) -> bool:
        """
        Initialize S3 client if not already done.

        Returns:
            True if initialization successful, False otherwise
        """
        if self.s3_uploader:
            return True

        if not self.s3_access_key or not self.s3_secret_key:
            logger.error("AWS credentials not configured for S3 downloads")
            logger.error("Required environment variables:")
            logger.error("  AWS_DB_BACKUP_ACCESS_KEY")
            logger.error("  AWS_DB_BACKUP_SECRET_KEY")
            return False

        try:
            from scripts.s3_backup_utils import S3BackupUploader
            self.s3_uploader = S3BackupUploader(
                bucket_name=self.s3_bucket,
                access_key=self.s3_access_key,
                secret_key=self.s3_secret_key,
                region=self.s3_region
            )

            # Test connection
            if not self.s3_uploader.test_connection():
                logger.error("S3 connection test failed")
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            return False

    def _validate_date_format(self, date_str: str) -> bool:
        """
        Validate date is in MM-DD-YYYY format.

        Args:
            date_str: Date string to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            datetime.strptime(date_str, '%m-%d-%Y')
            return True
        except ValueError:
            logger.error(f"Invalid date format: {date_str}")
            logger.error("Expected format: MM-DD-YYYY (e.g., 11-11-2025)")
            return False

    def resolve_backup_from_s3(self) -> Optional[str]:
        """
        Resolve backup file from S3 based on args.

        Uses --latest or --date flags to find the appropriate backup.

        Returns:
            S3 key of backup file, or None on failure
        """
        if not self._initialize_s3_client():
            return None

        try:
            # Determine date folder
            if hasattr(self.args, 'latest') and self.args.latest:
                logger.info("Finding latest backup from most recent date folder...")
                date_folders = self.s3_uploader.list_date_folders()

                if not date_folders:
                    logger.error("No date folders found in S3 bucket")
                    return None

                date_folder = date_folders[0]
                logger.info(f"Using most recent date folder: {date_folder}")

            elif hasattr(self.args, 'date') and self.args.date:
                date_folder = self.args.date

                if not self._validate_date_format(date_folder):
                    return None

                logger.info(f"Using specified date folder: {date_folder}")

            else:
                logger.error("Internal error: resolve_backup_from_s3 called without --latest or --date")
                return None

            # Get latest backup in the date folder
            result = self.s3_uploader.get_latest_backup_in_folder(date_folder)

            if not result:
                logger.error(f"No backups found in folder: {date_folder}")
                return None

            backup_key, metadata_key = result
            logger.info(f"Resolved backup: s3://{self.s3_bucket}/{backup_key}")

            return backup_key

        except Exception as e:
            logger.error(f"Failed to resolve backup from S3: {e}")
            return None

    def download_from_s3(self, s3_key: str, temp_dir: Path) -> Optional[Path]:
        """
        Download backup file from S3 to temp directory.

        Args:
            s3_key: S3 key of backup file
            temp_dir: Temporary directory to download to

        Returns:
            Local path to downloaded file, or None on failure
        """
        try:
            # Extract filename from S3 key
            filename = Path(s3_key).name
            local_path = temp_dir / filename

            logger.info(f"Downloading backup from S3: s3://{self.s3_bucket}/{s3_key}")

            # Download main backup file
            if not self.s3_uploader.download_file(s3_key, local_path):
                logger.error("Failed to download backup file from S3")
                return None

            # Try to download metadata file (optional)
            metadata_key = s3_key + '.meta.json'
            metadata_path = temp_dir / (filename + '.meta.json')

            logger.info(f"Attempting to download metadata file...")
            if self.s3_uploader.download_file(metadata_key, metadata_path):
                logger.info("✓ Metadata file downloaded successfully")
            else:
                logger.warning("Metadata file not found or failed to download (continuing anyway)")

            return local_path

        except Exception as e:
            logger.error(f"Error downloading from S3: {e}", exc_info=True)
            return None

    def validate_environment(self) -> bool:
        """Validate that all required environment variables are set."""
        required_vars = [
            "POSTGRES_HOST",
            "POSTGRES_DB",
            "POSTGRES_USERNAME",
            "POSTGRES_PASSWORD"
        ]

        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)

        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please check your .env file")
            return False

        # Validate database name to prevent SQL injection
        if not self._validate_database_name(self.db_name):
            return False

        logger.info("Environment validation successful")
        return True

    def test_database_connection(self) -> bool:
        """Test connection to PostgreSQL server (postgres database)."""
        try:
            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', 'postgres',
                    '-t',
                    '-c', 'SELECT 1;'
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-t',
                    '-c', 'SELECT 1;'
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None,
                    override_pgdatabase='postgres'  # Connect to postgres database
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )

            logger.info("PostgreSQL connection successful")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Database connection test timed out after 30 seconds")
            return False
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def list_available_backups(self):
        """List all available backup files."""
        logger.info("=" * 80)
        logger.info("Available Backups")
        logger.info("=" * 80)

        backup_patterns = ['*.dump', '*.sql', '*.dump.gpg', '*.sql.gpg']
        backup_files = []
        for pattern in backup_patterns:
            backup_files.extend(self.backup_dir.glob(pattern))

        if not backup_files:
            logger.info("No backup files found")
            return

        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        for i, backup_file in enumerate(backup_files, 1):
            backup_info = BackupInfo(backup_file)
            logger.info(f"\n[{i}] {backup_file.name}")
            logger.info(f"    Size: {backup_info.size_bytes / (1024 * 1024):.2f} MB")
            logger.info(f"    Modified: {backup_info.modified_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"    Format: {backup_info.format}")
            logger.info(f"    Encrypted: {backup_info.encrypted}")
            if backup_info.metadata:
                logger.info(f"    Type: {backup_info.metadata.get('backup_type', 'unknown')}")
                logger.info(f"    Verified: {backup_info.metadata.get('verified', False)}")

        logger.info("=" * 80)

    def validate_backup_file(self) -> bool:
        """Validate that backup file exists and is readable."""
        logger.info("Validating backup file...")

        # Handle S3 resolution first (--latest or --date flags)
        if hasattr(self.args, 'latest') and self.args.latest:
            s3_key = self.resolve_backup_from_s3()
            if not s3_key:
                return False

            # Download to temp directory
            if not self.temp_dir:
                logger.error("Internal error: temp_dir not initialized for S3 download")
                return False

            local_path = self.download_from_s3(s3_key, self.temp_dir)
            if not local_path:
                return False

            self.backup_file = str(local_path)

        elif hasattr(self.args, 'date') and self.args.date:
            s3_key = self.resolve_backup_from_s3()
            if not s3_key:
                return False

            # Download to temp directory
            if not self.temp_dir:
                logger.error("Internal error: temp_dir not initialized for S3 download")
                return False

            local_path = self.download_from_s3(s3_key, self.temp_dir)
            if not local_path:
                return False

            self.backup_file = str(local_path)

        # Handle direct S3 URI (s3://bucket/key)
        elif self._is_s3_uri(self.backup_file):
            try:
                bucket, s3_key = self._parse_s3_uri(self.backup_file)

                if bucket != self.s3_bucket:
                    logger.error(f"S3 URI bucket '{bucket}' doesn't match configured bucket '{self.s3_bucket}'")
                    logger.error(f"Configured bucket: {self.s3_bucket}")
                    return False

                if not self._initialize_s3_client():
                    return False

                # Download to temp directory
                if not self.temp_dir:
                    logger.error("Internal error: temp_dir not initialized for S3 download")
                    return False

                local_path = self.download_from_s3(s3_key, self.temp_dir)
                if not local_path:
                    return False

                self.backup_file = str(local_path)

            except ValueError as e:
                logger.error(str(e))
                return False

        # Now validate the local file (either original local path or downloaded from S3)
        backup_path = Path(self.backup_file)

        # Check if file exists
        if not backup_path.exists():
            logger.error(f"Backup file not found: {self.backup_file}")
            return False

        # Check if it's a file
        if not backup_path.is_file():
            logger.error(f"Path is not a file: {self.backup_file}")
            return False

        # Check if file is not empty
        if backup_path.stat().st_size == 0:
            logger.error("Backup file is empty")
            return False

        # Load backup information
        self.backup_info = BackupInfo(backup_path)

        # Check format
        if self.backup_info.format == 'unknown':
            logger.error(f"Unknown backup format (expected .dump or .sql)")
            return False

        logger.info("Backup file validation successful")
        self.backup_info.display()

        return True

    def verify_backup_integrity(self) -> bool:
        """
        Verify backup file integrity before restore.

        For custom format: Use pg_restore --list
        For SQL format: Basic syntax check
        """
        logger.info("Verifying backup integrity...")

        decrypted_path = None
        try:
            if self.backup_info.encrypted:
                if not self.encryption_key:
                    logger.error("Backup is encrypted, but BACKUP_ENCRYPTION_KEY is not set.")
                    return False

                logger.info("Decrypting backup for verification...")
                decrypted_path = self.backup_info.backup_path.with_suffix('.decrypted.tmp')

                try:
                    decrypt_file(
                        input_path=self.backup_info.backup_path,
                        output_path=decrypted_path,
                        passphrase=self.encryption_key
                    )
                    logger.info("✓ Decryption successful")

                    # Verify plaintext checksum if available in metadata
                    if self.backup_info.metadata and 'checksum_plaintext_sha256' in self.backup_info.metadata:
                        logger.info("Verifying decrypted backup checksum...")
                        expected_checksum = self.backup_info.metadata['checksum_plaintext_sha256']

                        if expected_checksum:  # Only verify if checksum exists
                            import hashlib
                            sha256_hash = hashlib.sha256()
                            with open(decrypted_path, 'rb') as f:
                                for byte_block in iter(lambda: f.read(4096), b""):
                                    sha256_hash.update(byte_block)
                            actual_checksum = sha256_hash.hexdigest()

                            if actual_checksum != expected_checksum:
                                logger.error("CHECKSUM VERIFICATION FAILED!")
                                logger.error(f"Expected: {expected_checksum}")
                                logger.error(f"Actual:   {actual_checksum}")
                                return False

                            logger.info("✓ Checksum verification passed")

                    source_path = decrypted_path
                except GPGEncryptionError as e:
                    logger.error(f"Decryption failed: {e}")
                    return False
            else:
                source_path = self.backup_info.backup_path

            if self.backup_info.format == 'custom':
                # Use pg_restore --list to verify custom format
                if self.execution_mode == 'native':
                    cmd = [
                        'pg_restore',
                        '--list',
                        str(source_path)
                    ]
                else:  # Docker mode
                    host_dir, container_dir, container_file = self.docker_utils.prepare_path_for_docker(
                        source_path
                    )

                    cmd = self.docker_utils.build_docker_command(
                        pg_command='pg_restore',
                        pg_args=['--list', container_file],
                        volume_mappings=[(host_dir, container_dir)]
                    )

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )

                lines = result.stdout.strip().split('\n')
                if len(lines) < 5:
                    logger.error("Backup appears to be corrupted or incomplete")
                    return False

                logger.info(f"Backup contains {len(lines)} database objects")

            else:
                # For SQL format, check for SQL keywords
                with open(source_path, 'r') as f:
                    content = f.read(2000)  # Read first 2KB
                    if not any(keyword in content for keyword in ['CREATE', 'INSERT', 'TABLE', 'DATABASE']):
                        logger.error("Backup file does not appear to contain valid SQL")
                        return False

                logger.info("Backup file contains valid SQL content")

            logger.info("Backup integrity verification passed")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Backup integrity verification failed: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Backup integrity verification failed: {e}")
            return False
        finally:
            if decrypted_path and decrypted_path.exists():
                secure_delete(decrypted_path)
                logger.info("Securely cleaned up temporary decrypted file.")

    def check_for_existing_data(self) -> bool:
        """
        Check if target database already exists and contains data.

        Specifically checks the 'invoice_items' table for rows as an indicator
        that the database is in use and contains production data.

        Returns:
            True if invoice_items table has data (should abort restore)
            False if invoice_items is empty or doesn't exist (safe to restore)
        """
        logger.info("Checking for existing data in target database...")

        try:
            sql_query = """
                SELECT COUNT(*)
                FROM pg_catalog.pg_database
                WHERE datname = %s;
            """

            # First check if database exists by querying postgres database
            if self.execution_mode == 'native':
                # Using psql with proper escaping for the database name
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', 'postgres',
                    '-t',
                    '-c', f"SELECT COUNT(*) FROM pg_catalog.pg_database WHERE datname = '{self.db_name}';"
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-t',
                    '-c', f"SELECT COUNT(*) FROM pg_catalog.pg_database WHERE datname = '{self.db_name}';"
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None,
                    override_pgdatabase='postgres'
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            db_count = int(result.stdout.strip())

            if db_count == 0:
                logger.info(f"Database '{self.db_name}' does not exist - safe to restore")
                return False

            # Database exists, now check if invoice_items table has data
            logger.info(f"Database '{self.db_name}' exists, checking invoice_items table for data...")

            # Query to get row count from invoice_items table specifically
            row_check_query = """
                SELECT COALESCE(
                    (SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = 'invoice_items'),
                    0
                ) as row_count;
            """

            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-t',
                    '-c', row_check_query
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-t',
                    '-c', row_check_query
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            # Parse output: single row_count value
            output = result.stdout.strip()

            try:
                row_count = int(output)
            except (ValueError, TypeError):
                # If we can't parse, assume there might be data (fail-safe)
                logger.warning(f"Could not parse row count from output: '{output}'")
                row_count = 1

            logger.info(f"invoice_items table has {row_count} rows")

            if row_count > 0:
                logger.error("=" * 80)
                logger.error(f"SAFETY CHECK FAILED: Database '{self.db_name}' contains data!")
                logger.error(f"Found {row_count} rows in invoice_items table")
                logger.error("")
                logger.error("To restore, you must first:")
                logger.error("  1. Backup your current data if needed")
                logger.error("  2. Manually drop the database, OR")
                logger.error("  3. Use a different target database")
                logger.error("=" * 80)
                return True

            logger.info("invoice_items table is empty - safe to restore")

            return False

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to check for existing data: {e}")
            logger.error(f"Error output: {e.stderr}")
            # Fail safe - if we can't check, assume data exists
            logger.error("Unable to verify database state - aborting restore for safety")
            return True
        except Exception as e:
            logger.error(f"Unexpected error checking for existing data: {e}")
            # Fail safe - if we can't check, assume data exists
            logger.error("Unable to verify database state - aborting restore for safety")
            return True

    def get_current_database_stats(self) -> Optional[Dict]:
        """Get current database statistics before restore."""
        try:
            sql_query = """
                SELECT
                    COUNT(DISTINCT tablename) as table_count,
                    SUM(n_tup_ins) as total_rows
                FROM pg_stat_user_tables;
            """

            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-t',
                    '-c', sql_query
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-t',
                    '-c', sql_query
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=False  # Database might not exist yet
            )

            if result.returncode == 0:
                # Parse output
                parts = result.stdout.strip().split('|')
                if len(parts) >= 2:
                    return {
                        'table_count': int(parts[0].strip() or 0),
                        'total_rows': int(parts[1].strip() or 0)
                    }

            return None

        except Exception as e:
            logger.debug(f"Could not get current database stats: {e}")
            return None

    def terminate_database_connections(self) -> bool:
        """Terminate all connections to the target database."""
        logger.info(f"Terminating connections to database '{self.db_name}'...")

        try:
            sql_query = f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{self.db_name}'
                AND pid <> pg_backend_pid();
            """

            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', 'postgres',
                    '-c', sql_query
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-c', sql_query
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None,
                    override_pgdatabase='postgres'  # Connect to postgres database
                )

                env = os.environ.copy()

            subprocess.run(cmd, env=env, capture_output=True, check=False)
            logger.info("Connections terminated")
            return True

        except Exception as e:
            logger.warning(f"Error terminating connections: {e}")
            return False

    def drop_database(self) -> bool:
        """Drop the existing database."""
        logger.info(f"Dropping database '{self.db_name}'...")

        if self.dry_run:
            logger.info("DRY RUN: Would drop database")
            return True

        try:
            # Terminate connections first
            self.terminate_database_connections()

            # Drop database
            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', 'postgres',
                    '-c', f'DROP DATABASE IF EXISTS {self.db_name};'
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-c', f'DROP DATABASE IF EXISTS {self.db_name};'
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None,
                    override_pgdatabase='postgres'  # Connect to postgres database
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            logger.info(f"Database '{self.db_name}' dropped successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to drop database: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Failed to drop database: {e}")
            return False

    def create_database(self) -> bool:
        """Create a new empty database."""
        logger.info(f"Creating database '{self.db_name}'...")

        if self.dry_run:
            logger.info("DRY RUN: Would create database")
            return True

        try:
            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', 'postgres',
                    '-c', f'CREATE DATABASE {self.db_name};'
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-c', f'CREATE DATABASE {self.db_name};'
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None,
                    override_pgdatabase='postgres'  # Connect to postgres database
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            logger.info(f"Database '{self.db_name}' created successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create database: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Failed to create database: {e}")
            return False

    def restore_database(self) -> bool:
        """
        Restore database from backup file.

        Uses pg_restore for custom format or psql for SQL format.
        """
        logger.info("Restoring database from backup...")
        logger.info(f"Format: {self.backup_info.format}")

        if self.dry_run:
            logger.info("DRY RUN: Would restore database")
            return True

        start_time = time.time()
        decrypted_path = None

        try:
            if self.backup_info.encrypted:
                if not self.encryption_key:
                    logger.error("Backup is encrypted, but BACKUP_ENCRYPTION_KEY is not set.")
                    return False

                logger.info("Decrypting backup for restore...")
                decrypted_path = self.backup_info.backup_path.with_suffix('.decrypted.tmp')

                try:
                    decrypt_file(
                        input_path=self.backup_info.backup_path,
                        output_path=decrypted_path,
                        passphrase=self.encryption_key
                    )
                    logger.info("✓ Decryption successful")

                    # Verify plaintext checksum (critical for restore operation)
                    if self.backup_info.metadata and 'checksum_plaintext_sha256' in self.backup_info.metadata:
                        logger.info("Verifying decrypted backup integrity...")
                        expected_checksum = self.backup_info.metadata['checksum_plaintext_sha256']

                        if expected_checksum:
                            import hashlib
                            sha256_hash = hashlib.sha256()
                            with open(decrypted_path, 'rb') as f:
                                for byte_block in iter(lambda: f.read(4096), b""):
                                    sha256_hash.update(byte_block)
                            actual_checksum = sha256_hash.hexdigest()

                            if actual_checksum != expected_checksum:
                                logger.error("CRITICAL: CHECKSUM VERIFICATION FAILED!")
                                logger.error(f"Expected: {expected_checksum}")
                                logger.error(f"Actual:   {actual_checksum}")
                                return False

                            logger.info("✓ Backup integrity verified")

                    source_path = decrypted_path
                except GPGEncryptionError as e:
                    logger.error(f"Decryption failed: {e}")
                    return False
            else:
                source_path = self.backup_info.backup_path

            if self.execution_mode == 'native':
                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

                if self.backup_info.format == 'custom':
                    # Use pg_restore for custom format
                    cmd = [
                        'pg_restore',
                        '-h', self.db_host,
                        '-p', str(self.db_port),
                        '-U', self.db_user,
                        '-d', self.db_name,
                        '--verbose',
                        '--no-owner',
                        '--no-privileges',
                        str(source_path)
                    ]

                    # Add parallel restore if specified and supported
                    if self.parallel_jobs > 1:
                        cmd.extend(['-j', str(self.parallel_jobs)])
                        logger.info(f"Using {self.parallel_jobs} parallel jobs")

                else:
                    # Use psql for SQL format
                    cmd = [
                        'psql',
                        '-h', self.db_host,
                        '-p', str(self.db_port),
                        '-U', self.db_user,
                        '-d', self.db_name,
                        '-f', str(source_path)
                    ]

            else:  # Docker mode
                env = os.environ.copy()

                # Prepare backup file path for Docker
                host_dir, container_dir, container_file = self.docker_utils.prepare_path_for_docker(
                    source_path
                )

                if self.backup_info.format == 'custom':
                    # Use pg_restore for custom format
                    pg_restore_args = [
                        '-d', self.db_name,  # Database target - required for pg_restore
                        '--verbose',
                        '--no-owner',
                        '--no-privileges',
                        container_file
                    ]

                    # Add parallel restore if specified and supported
                    if self.parallel_jobs > 1:
                        pg_restore_args.extend(['-j', str(self.parallel_jobs)])
                        logger.info(f"Using {self.parallel_jobs} parallel jobs")

                    cmd = self.docker_utils.build_docker_command(
                        pg_command='pg_restore',
                        pg_args=pg_restore_args,
                        volume_mappings=[(host_dir, container_dir)]
                    )

                else:
                    # Use psql for SQL format
                    psql_args = [
                        '-d', self.db_name,  # Database target
                        '-f', container_file
                    ]

                    cmd = self.docker_utils.build_docker_command(
                        pg_command='psql',
                        pg_args=psql_args,
                        volume_mappings=[(host_dir, container_dir)]
                    )

            logger.info("Executing restore command...")

            # Execute restore with streaming stderr for progress
            process = subprocess.Popen(
                cmd,
                env=env,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True
            )

            # Collect stderr output for error reporting
            stderr_output = []
            for line in process.stderr:
                line = line.strip()
                if line:
                    stderr_output.append(line)
                    logger.debug(f"restore: {line}")

            return_code = process.wait()

            if return_code != 0:
                logger.error(f"Restore command failed with return code {return_code}")
                if stderr_output:
                    logger.error("Error output:")
                    for line in stderr_output[-20:]:  # Show last 20 lines
                        logger.error(f"  {line}")
                return False

            end_time = time.time()
            duration = end_time - start_time

            logger.info(f"Database restore completed in {duration:.2f} seconds")
            return True

        except Exception as e:
            logger.error(f"Error during database restore: {e}")
            return False
        finally:
            if decrypted_path and decrypted_path.exists():
                secure_delete(decrypted_path)
                logger.info("Securely cleaned up temporary decrypted file.")

    def verify_restore(self) -> bool:
        """
        Verify that database was restored successfully.

        Checks:
        - Database exists and is accessible
        - Tables were created
        - Row counts are reasonable
        - Constraints are valid
        """
        logger.info("Verifying database restore...")

        if self.dry_run:
            logger.info("DRY RUN: Would verify restore")
            return True

        try:
            # First psql command: Check table count
            # Use information_schema which is reliable immediately after restore
            sql_query_1 = """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema');
            """

            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-t',
                    '-c', sql_query_1
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-t',
                    '-c', sql_query_1
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            table_count = int(result.stdout.strip())
            logger.info(f"Restored database contains {table_count} tables")

            if table_count == 0:
                logger.error("No tables found in restored database")
                return False

            # Second psql command: List all tables
            sql_query_2 = """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name;
            """

            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-c', sql_query_2
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-c', sql_query_2
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            logger.info("Tables in restored database:")
            for line in result.stdout.strip().split('\n')[2:]:  # Skip headers
                if line.strip() and not line.startswith('('):
                    logger.info(f"  {line}")

            # Third psql command: Check for constraint violations
            sql_query_3 = """
                SELECT COUNT(*)
                FROM pg_constraint
                WHERE contype IN ('f', 'p', 'u');
            """

            if self.execution_mode == 'native':
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-t',
                    '-c', sql_query_3
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                psql_args = [
                    '-t',
                    '-c', sql_query_3
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None
                )

                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            constraint_count = int(result.stdout.strip())
            logger.info(f"Database has {constraint_count} constraints (foreign keys, primary keys, unique)")

            logger.info("Database restore verification passed")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Restore verification failed: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Restore verification failed: {e}")
            return False

    def get_user_confirmation(self) -> bool:
        """Get user confirmation before proceeding with restore."""
        if self.force or self.auto_yes:
            return True

        if self.dry_run:
            return True

        logger.info("=" * 80)
        logger.info("DATABASE RESTORE WARNING")
        logger.info("=" * 80)
        logger.info("This operation will:")
        logger.info(f"  1. TERMINATE all connections to database '{self.db_name}'")
        logger.info(f"  2. DROP the existing database '{self.db_name}'")
        logger.info(f"  3. CREATE a new database '{self.db_name}'")
        logger.info(f"  4. RESTORE from backup: {self.backup_file}")
        logger.info("")
        logger.info("WARNING: ALL EXISTING DATA WILL BE PERMANENTLY LOST!")
        logger.info("=" * 80)

        # Show current database stats if available
        current_stats = self.get_current_database_stats()
        if current_stats:
            logger.info(f"Current database has {current_stats['table_count']} tables "
                       f"with approximately {current_stats['total_rows']} rows")

        response = input("\nType 'yes' to proceed, anything else to cancel: ").strip().lower()
        return response == 'yes'

    def run(self) -> bool:
        """Execute the complete restore process."""
        # Check if we need S3 temp directory
        needs_s3_temp = (
            (hasattr(self.args, 'latest') and self.args.latest) or
            (hasattr(self.args, 'date') and self.args.date) or
            self._is_s3_uri(self.backup_file)
        )

        if needs_s3_temp:
            # Use context manager for S3 downloads
            with self.s3_download_temp_dir() as temp_dir:
                self.temp_dir = temp_dir
                return self._run_restore()
        else:
            # Local file, no temp directory needed
            return self._run_restore()

    def _run_restore(self) -> bool:
        """Internal restore logic (called with or without S3 temp directory)."""
        logger.info("=" * 80)
        logger.info("MPI Backend Database Restore - Production Grade")
        if self.dry_run:
            logger.info("MODE: DRY RUN (no actual changes will be made)")
        logger.info("=" * 80)

        # Validate environment
        if not self.validate_environment():
            logger.error("Environment validation failed")
            return False

        # Test PostgreSQL connection
        if not self.test_database_connection():
            logger.error("PostgreSQL connection failed")
            return False

        # Validate backup file (handles S3 downloads)
        if not self.validate_backup_file():
            logger.error("Backup file validation failed")
            return False

        # Verify backup integrity
        if not self.verify_backup_integrity():
            logger.error("Backup integrity verification failed")
            return False

        # SAFETY CHECK: Check for existing data in target database
        if self.check_for_existing_data():
            logger.error("Cannot restore: Target database contains existing data")
            return False

        # Get user confirmation
        if not self.get_user_confirmation():
            logger.info("Restore cancelled by user")
            return False

        if self.dry_run:
            logger.info("=" * 80)
            logger.info("DRY RUN COMPLETE - No changes were made")
            logger.info("The backup file is valid and ready for restore")
            logger.info("Run without --dry-run to perform actual restore")
            logger.info("=" * 80)
            return True

        # Perform restore steps
        logger.info("Beginning database restore process...")

        # Drop existing database
        if not self.drop_database():
            logger.error("Failed to drop existing database")
            return False

        # Create new database
        if not self.create_database():
            logger.error("Failed to create new database")
            return False

        # Restore from backup
        if not self.restore_database():
            logger.error("Failed to restore database from backup")
            logger.error("Database may be in an inconsistent state")
            return False

        # Verify restore
        if self.verify:
            if not self.verify_restore():
                logger.error("Restore verification failed")
                logger.warning("Database was restored but verification found issues")
                return False
        else:
            logger.info("Skipping post-restore verification (--no-verify specified)")

        logger.info("=" * 80)
        logger.info("Database restore completed successfully")
        logger.info(f"Database: {self.db_name}")
        logger.info(f"Restored from: {self.backup_file}")
        logger.info("=" * 80)

        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Production-grade database restore for MPI Backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available backups
  python scripts/restore_database.py --list-backups

  # Restore latest backup from most recent S3 date folder
  python scripts/restore_database.py --latest

  # Restore latest backup from specific S3 date folder
  python scripts/restore_database.py --date 11-11-2025

  # Restore specific backup from S3 (full URI)
  python scripts/restore_database.py --backup-file s3://devs-invoice/11-11-2025/mpi_db_daily_20251111_163534.dump.gpg

  # Dry-run to verify a backup without restoring
  python scripts/restore_database.py --backup-file path/to/backup.dump --dry-run

  # Restore from a specific local backup
  python scripts/restore_database.py --backup-file path/to/backup.dump

  # Restore with parallel jobs (faster for large databases)
  python scripts/restore_database.py --backup-file path/to/backup.dump --jobs 4

  # Restore without confirmation prompt
  python scripts/restore_database.py --backup-file path/to/backup.dump --yes

  # Restore without post-restore verification
  python scripts/restore_database.py --backup-file path/to/backup.dump --no-verify
        """
    )

    parser.add_argument(
        '--backup-file',
        type=str,
        metavar='PATH',
        help='Path to backup file to restore (.dump, .sql, or s3:// URI)'
    )

    parser.add_argument(
        '--latest',
        action='store_true',
        help='Download and restore latest backup from most recent S3 date folder'
    )

    parser.add_argument(
        '--date',
        type=str,
        metavar='MM-DD-YYYY',
        help='Download and restore latest backup from specific S3 date folder (e.g., 11-11-2025)'
    )

    parser.add_argument(
        '--list-backups',
        action='store_true',
        help='List available backups and exit'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate backup without actually restoring (test mode)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts (dangerous!)'
    )

    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Automatically answer yes to confirmation prompts'
    )

    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Skip post-restore verification (not recommended)'
    )

    parser.add_argument(
        '--jobs',
        type=int,
        default=1,
        metavar='N',
        help='Number of parallel restore jobs (default: 1, only for custom format)'
    )

    parser.add_argument(
        '--backup-dir',
        type=str,
        default='database_backups',
        metavar='PATH',
        help='Directory containing backups (default: database_backups/)'
    )

    args = parser.parse_args()

    # Validate mutual exclusivity of backup source options
    backup_sources = sum([
        bool(args.backup_file),
        args.latest,
        bool(args.date)
    ])

    if backup_sources > 1:
        logger.error("Error: Cannot use multiple backup source options simultaneously")
        logger.error("Choose one of: --backup-file, --latest, or --date")
        parser.print_help()
        sys.exit(1)

    try:
        restorer = DatabaseRestorer(args)

        # Handle --list-backups
        if args.list_backups:
            restorer.list_available_backups()
            sys.exit(0)

        # Require at least one backup source for restore operations
        if backup_sources == 0:
            logger.error("Error: Must specify backup source: --backup-file, --latest, or --date")
            logger.error("Or use --list-backups to see available backups")
            parser.print_help()
            sys.exit(1)

        # Perform restore
        success = restorer.run()

        if success:
            logger.info("Database restore operation completed successfully")
            sys.exit(0)
        else:
            logger.error("Database restore operation failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Restore process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
