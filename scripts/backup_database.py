import os
import sys
import argparse
import subprocess
import hashlib
import json
import resource
import signal
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
import logging
from dotenv import load_dotenv

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import shared Docker utilities
from scripts.postgres_docker_utils import PostgresDockerUtils

# Import GPG encryption utilities
from scripts.gpg_encryption_utils import (
    encrypt_file,
    is_gpg_available,
    validate_passphrase_strength,
    secure_delete,
    GPGEncryptionError
)

# Load environment variables
load_dotenv(project_root / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(project_root / 'logs' / 'backup.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BackupMetadata:
    """Container for backup metadata information."""

    def __init__(self, backup_path: Path, backup_type: str, format_type: str, encrypted: bool):
        self.backup_path = backup_path
        self.backup_type = backup_type
        self.format_type = format_type
        self.encrypted = encrypted
        self.timestamp = datetime.now().isoformat()
        self.size_bytes = 0
        self.checksum = ""  # Checksum of final file (encrypted if encrypted=True)
        self.checksum_plaintext = ""  # Checksum of unencrypted data (for verification after decryption)
        self.pg_version = ""
        self.database_name = ""
        self.duration_seconds = 0.0
        self.verified = False
        # S3 upload tracking
        self.s3_uploaded = False
        self.s3_bucket = ""
        self.s3_key = ""
        self.s3_upload_timestamp = ""
        self.s3_upload_duration_seconds = 0.0

    def to_dict(self) -> Dict:
        """Convert metadata to dictionary."""
        return {
            'backup_file': str(self.backup_path.name),
            'backup_type': self.backup_type,
            'format': self.format_type,
            'encrypted': self.encrypted,
            'timestamp': self.timestamp,
            'size_bytes': self.size_bytes,
            'size_mb': round(self.size_bytes / (1024 * 1024), 2),
            'checksum_sha256': self.checksum,
            'checksum_plaintext_sha256': self.checksum_plaintext,
            'postgresql_version': self.pg_version,
            'database_name': self.database_name,
            'duration_seconds': round(self.duration_seconds, 2),
            'verified': self.verified,
            's3_uploaded': self.s3_uploaded,
            's3_bucket': self.s3_bucket,
            's3_key': self.s3_key,
            's3_upload_timestamp': self.s3_upload_timestamp,
            's3_upload_duration_seconds': round(self.s3_upload_duration_seconds, 2) if self.s3_upload_duration_seconds else 0.0
        }

    def save(self):
        """Save metadata to JSON file alongside backup."""
        metadata_path = self.backup_path.with_suffix(self.backup_path.suffix + '.meta.json')
        with open(metadata_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Metadata saved to {metadata_path}")


class DatabaseBackup:
    """Production-grade database backup manager using pg_dump."""

    def __init__(self, args: argparse.Namespace):
        self.project_root = project_root
        self.backup_dir = Path(args.backup_dir)
        self.logs_dir = project_root / 'logs'

        # Backup configuration
        self.format = args.format
        self.compress_level = args.compress_level
        self.verify = not args.no_verify
        self.parallel_jobs = args.jobs
        self.dump_timeout = args.dump_timeout
        self.force = args.force
        # Encryption is always enabled (mandatory)
        self.encrypt = True

        # Retention policy (in days)
        self.retention_daily = args.retention_daily
        self.retention_weekly = args.retention_weekly * 7
        self.retention_monthly = args.retention_monthly * 30

        # Database configuration from environment
        self.db_host = os.getenv("POSTGRES_HOST")
        self.db_port = os.getenv("POSTGRES_PORT")
        self.db_name = os.getenv("POSTGRES_DB")
        self.db_user = os.getenv("POSTGRES_USERNAME")
        self.db_password = os.getenv("POSTGRES_PASSWORD")
        self.encryption_key = os.getenv("BACKUP_ENCRYPTION_KEY")

        # Docker configuration for fallback mode
        self.execution_mode = 'native'  # Will be set to 'native' or 'docker'
        self.docker_image = 'postgres:16'  # Pinned version to match DO managed DB

        # Initialize shared Docker utilities
        self.docker_utils = PostgresDockerUtils(
            db_host=self.db_host,
            db_port=self.db_port,
            db_name=self.db_name,
            db_user=self.db_user,
            db_password=self.db_password,
            docker_image=self.docker_image
        )

        # S3 configuration
        # Default to enabled if credentials are present, unless explicitly disabled
        self.enable_s3_upload = not args.no_s3_upload if hasattr(args, 'no_s3_upload') else True
        self.s3_cleanup = args.s3_cleanup if hasattr(args, 's3_cleanup') else False
        self.s3_bucket = os.getenv("AWS_DB_BACKUP_BUCKET", "devs-invoice")
        self.s3_access_key = os.getenv("AWS_DB_BACKUP_ACCESS_KEY")
        self.s3_secret_key = os.getenv("AWS_DB_BACKUP_SECRET_KEY")
        self.s3_region = os.getenv("AWS_DB_BACKUP_REGION", "us-east-1")

        # Initialize S3 uploader (lazy initialization)
        self.s3_uploader = None
        if self.enable_s3_upload and self.s3_access_key and self.s3_secret_key:
            from scripts.s3_backup_utils import S3BackupUploader
            self.s3_uploader = S3BackupUploader(
                bucket_name=self.s3_bucket,
                access_key=self.s3_access_key,
                secret_key=self.s3_secret_key,
                region=self.s3_region
            )

        # Create directories if they don't exist
        self.backup_dir.mkdir(exist_ok=True, parents=True)
        self.logs_dir.mkdir(exist_ok=True, parents=True)

        # Initialize execution mode (checks for PostgreSQL tools or Docker)
        self._initialize_execution_mode()

    def _initialize_execution_mode(self):
        """
        Initialize execution mode: native tools or Docker fallback.
        Sets self.execution_mode to 'native' or 'docker'.
        """
        required_tools = ['pg_dump', 'psql', 'pg_restore']
        missing_tools = []

        for tool in required_tools:
            if not shutil.which(tool):
                missing_tools.append(tool)

        # Validate GPG availability and passphrase (encryption is mandatory)
        gpg_available, error_msg = is_gpg_available()
        if not gpg_available:
            logger.error("GPG is required for encrypted backups but is not available.")
            logger.error(f"Error: {error_msg}")
            sys.exit(1)

        # Validate passphrase strength
        is_valid, passphrase_error = validate_passphrase_strength(self.encryption_key)
        if not is_valid:
            logger.error(f"Encryption passphrase validation failed: {passphrase_error}")
            logger.error("Please use a stronger passphrase")
            sys.exit(1)

        logger.info("✓ GPG encryption validated successfully")

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
            logger.info(f"  Docker image: {self.docker_image}, Docker network: {self.docker_utils.docker_network}")
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
            logger.error(f"Invalid database name: '{db_name}'")
            logger.error("Database name can only contain: letters, numbers, underscores, hyphens")
            return False

        # Additional safety: check for SQL keywords or suspicious patterns
        dangerous_patterns = ['drop', 'delete', 'truncate', ';', '--', '/*', '*/', 'select']
        db_name_lower = db_name.lower()
        for pattern in dangerous_patterns:
            if pattern in db_name_lower:
                logger.error(f"Database name contains suspicious pattern: '{pattern}'")
                return False

        return True

    def validate_environment(self) -> bool:
        """Validate that all required environment variables are set."""
        required_vars = [
            "POSTGRES_HOST",
            "POSTGRES_DB",
            "POSTGRES_USERNAME",
            "POSTGRES_PASSWORD",
            "BACKUP_ENCRYPTION_KEY"  # Encryption is mandatory
        ]

        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)

        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            if "BACKUP_ENCRYPTION_KEY" in missing_vars:
                logger.error("BACKUP_ENCRYPTION_KEY is required for encrypted backups.")
            logger.error("=" * 80)
            return False

        # Validate database name to prevent SQL injection
        if not self._validate_database_name(self.db_name):
            return False

        # Validate S3 configuration if enabled
        if not self.validate_s3_configuration():
            return False

        # Log FD limits for diagnosing "Too many open files" in constrained pods
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        logger.info(f"File descriptor limits: soft={soft}, hard={hard}")

        logger.info("Environment validation successful")
        return True

    def validate_s3_configuration(self) -> bool:
        """
        Validate S3 configuration if S3 upload is enabled.

        Returns:
            True if S3 is properly configured or disabled, False otherwise
        """
        if not self.enable_s3_upload:
            logger.info("S3 upload is disabled")
            return True

        # Check if credentials are present
        if not self.s3_access_key or not self.s3_secret_key:
            logger.error("S3 upload is enabled but AWS credentials are missing")
            logger.error("Required environment variables: AWS_DB_BACKUP_ACCESS_KEY, AWS_DB_BACKUP_SECRET_KEY")
            return False

        # Check if S3 uploader was initialized
        if not self.s3_uploader:
            logger.error("S3 uploader failed to initialize")
            return False

        # Test S3 connectivity
        try:
            if not self.s3_uploader.test_connection():
                logger.error(f"S3 connection test failed. Bucket: {self.s3_bucket}, region: {self.s3_region}")
                return False

            logger.info("✓ S3 configuration validated successfully")
            return True

        except Exception as e:
            logger.error(f"S3 validation error: {e}", exc_info=True)
            return False

    def test_database_connection(self) -> Tuple[bool, str]:
        """Test database connection and get PostgreSQL version."""
        try:
            if self.execution_mode == 'native':
                # Use native psql command
                cmd = [
                    'psql',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-t',  # Tuples only (no headers)
                    '-c', 'SELECT version();'
                ]

                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                # Build Docker-wrapped psql command
                psql_args = [
                    '-t',  # Tuples only
                    '-c', 'SELECT version();'
                ]

                cmd = self.docker_utils.build_docker_command(
                    pg_command='psql',
                    pg_args=psql_args,
                    volume_mappings=None  # No file access needed
                )

                env = os.environ.copy()  # Docker handles PGPASSWORD via -e flag

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )

            version = result.stdout.strip()
            logger.info(f"Database connection successful")
            logger.info(f"PostgreSQL version: {version}")
            return True, version

        except subprocess.CalledProcessError as e:
            logger.error(f"Database connection failed: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False, ""
        except subprocess.TimeoutExpired:
            logger.error("Database connection test timed out after 30 seconds")
            return False, ""
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False, ""

    def _generate_backup_filename(self, backup_type: str) -> Path:
        """Generate timestamped backup filename based on type."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.format == 'custom':
            extension = 'dump.gpg'  # Always encrypted
        else:
            extension = 'sql.gpg'  # Always encrypted

        filename = f"{self.db_name}_{backup_type}_{timestamp}.{extension}"
        return self.backup_dir / filename

    def _determine_backup_type(self) -> str:
        """Determine backup type (daily, weekly, or monthly) based on date."""
        now = datetime.now()

        # Monthly: First day of month
        if now.day == 1:
            return 'monthly'

        # Weekly: Sunday (weekday 6)
        if now.weekday() == 6:
            return 'weekly'

        # Daily: All other days
        return 'daily'

    def create_backup(self) -> Optional[BackupMetadata]:
        """
        Create database backup using pg_dump.

        Uses PostgreSQL's native pg_dump utility which provides:
        - Transaction-consistent snapshots
        - Proper handling of all PostgreSQL data types
        - Efficient binary format with compression
        - Parallel dump support for large databases
        """
        backup_type = self._determine_backup_type()
        backup_path = self._generate_backup_filename(backup_type)
        temp_path = backup_path.with_suffix(backup_path.suffix + '.tmp')

        logger.info("=" * 60)
        logger.info(f"Starting {backup_type} database backup")
        logger.info(f"Database: {self.db_name} on {self.db_host}:{self.db_port}")
        logger.info(f"Format: {self.format}")
        logger.info("Encryption: Enabled (GPG AES256)")
        logger.info(f"Target file: {backup_path}")
        logger.info("=" * 60)

        metadata = BackupMetadata(backup_path, backup_type, self.format, encrypted=True)
        metadata.database_name = self.db_name

        try:
            if self.execution_mode == 'native':
                # Build native pg_dump command
                cmd = [
                    'pg_dump',
                    '-h', self.db_host,
                    '-p', str(self.db_port),
                    '-U', self.db_user,
                    '-d', self.db_name,
                    '-f', str(temp_path),
                    '--verbose'  # Verbose output for logging
                ]

                if self.format == 'custom':
                    # Custom format: binary, compressed, restorable with pg_restore
                    cmd.extend([
                        '-Fc',  # Custom format
                        f'-Z{self.compress_level}'  # Compression level
                    ])

                    # Add parallel dump support for better performance on large DBs
                    if self.parallel_jobs > 1:
                        cmd.extend(['-j', str(self.parallel_jobs)])
                        logger.info(f"Using {self.parallel_jobs} parallel jobs")
                else:
                    # Plain SQL format: text-based, human-readable
                    cmd.append('-Fp')  # Plain format

                # Add additional options for comprehensive backup
                cmd.extend([
                    '--no-owner',  # Don't output ownership commands
                    '--no-privileges',  # Don't output privilege commands (ACLs)
                    '--create',  # Include commands to create database
                    '--clean'  # Include commands to clean (drop) database objects
                ])

                # Set PGPASSWORD environment variable for authentication
                env = os.environ.copy()
                env['PGPASSWORD'] = self.db_password

            else:  # Docker mode
                # For Docker, need to map backup directory
                host_dir, container_dir, container_file = self.docker_utils.prepare_path_for_docker(temp_path)

                pg_dump_args = [
                    '-f', container_file,
                    '--verbose'
                ]

                # Add format-specific options
                if self.format == 'custom':
                    pg_dump_args.extend([
                        '-Fc',
                        f'-Z{self.compress_level}'
                    ])
                    if self.parallel_jobs > 1:
                        pg_dump_args.extend(['-j', str(self.parallel_jobs)])
                        logger.info(f"Using {self.parallel_jobs} parallel jobs")
                else:
                    pg_dump_args.append('-Fp')

                pg_dump_args.extend([
                    '--no-owner',
                    '--no-privileges',
                    '--create',
                    '--clean'
                ])

                cmd = self.docker_utils.build_docker_command(
                    pg_command='pg_dump',
                    pg_args=pg_dump_args,
                    volume_mappings=[(host_dir, container_dir)]
                )

                env = os.environ.copy()

            logger.info(f"Executing pg_dump command...")
            start_time = datetime.now()

            # Execute pg_dump with a configurable timeout.
            # start_new_session=True puts pg_dump (and any -j worker children)
            # in their own process group so os.killpg() terminates them all.
            # We use communicate(timeout=...) instead of iterating stderr,
            # because the blocking `for line in process.stderr` loop would
            # prevent the timeout from firing if pg_dump stalls with stderr
            # still open.
            process = subprocess.Popen(
                cmd,
                env=env,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            stderr_output = ""
            try:
                _, stderr_output = process.communicate(timeout=self.dump_timeout)
            except subprocess.TimeoutExpired:
                logger.error(f"pg_dump timed out after {self.dump_timeout} seconds")
                os.killpg(process.pid, signal.SIGKILL)
                _, stderr_output = process.communicate()  # Drain pipes and reap child
                if temp_path.exists():
                    temp_path.unlink()
                return None
            finally:
                if process.stderr:
                    try:
                        process.stderr.close()
                    except OSError:
                        pass

            # Log stderr output after process completes (pg_dump writes
            # progress to stderr with --verbose)
            if stderr_output:
                for line in stderr_output.splitlines():
                    line = line.strip()
                    if line:
                        logger.debug(f"pg_dump: {line}")

            return_code = process.returncode

            if return_code != 0:
                logger.error(f"pg_dump failed with return code {return_code}")
                if temp_path.exists():
                    temp_path.unlink()
                return None

            end_time = datetime.now()
            metadata.duration_seconds = (end_time - start_time).total_seconds()

            # Verify the unencrypted dump file before proceeding
            if self.verify and not self._verify_dump_content(temp_path):
                logger.error("Aborting backup due to content verification failure.")
                if temp_path.exists():
                    temp_path.unlink()
                return None

            # Generate checksum of plaintext backup BEFORE encryption
            logger.info("Generating checksum of unencrypted backup...")
            metadata.checksum_plaintext = self._generate_checksum(temp_path)
            logger.info(f"Plaintext SHA256: {metadata.checksum_plaintext}")

            # Encrypt the backup file (mandatory)
            logger.info("Encrypting backup file with GPG (AES256)...")
            logger.info(f"Temp file size: {temp_path.stat().st_size / (1024 * 1024):.2f} MB")
            try:
                encrypt_file(
                    input_path=temp_path,
                    output_path=backup_path,
                    passphrase=self.encryption_key
                )
                # Securely delete unencrypted temp file after successful encryption
                secure_delete(temp_path)
                logger.info("✓ Encryption successful")
            except GPGEncryptionError as e:
                logger.error(f"Encryption failed: {e}")
                # Cleanup on failure - securely delete unencrypted data
                if temp_path.exists():
                    secure_delete(temp_path)
                if backup_path.exists():
                    backup_path.unlink()  # Encrypted file can use regular delete
                return None

            # Get file size
            metadata.size_bytes = backup_path.stat().st_size
            logger.info(f"Backup created: {metadata.size_bytes / (1024 * 1024):.2f} MB")
            logger.info(f"Duration: {metadata.duration_seconds:.2f} seconds")

            # Generate checksum of encrypted backup file (for detecting storage corruption)
            try:
                logger.info(f"Open FDs before checksum: {len(os.listdir('/proc/self/fd'))}")
            except OSError as exc:
                logger.debug(f"Skipping FD count diagnostic: {exc}")
            metadata.checksum = self._generate_checksum(backup_path)
            logger.info(f"Encrypted file SHA256: {metadata.checksum}")

            return metadata

        except Exception as e:
            logger.error(f"Error during backup creation: {e}", exc_info=True)
            try:
                fd_count = len(os.listdir('/proc/self/fd'))
                logger.error(f"Open FDs at failure: {fd_count}")
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                logger.error(f"FD limits at failure: soft={soft}, hard={hard}")
                # Log disk state for the backup directory
                st = os.statvfs(str(self.backup_dir))
                free_mb = (st.f_bavail * st.f_frsize) / (1024 * 1024)
                free_inodes = st.f_favail
                logger.error(f"Disk free: {free_mb:.0f} MB, free inodes: {free_inodes}")
            except Exception:
                pass  # Don't let diagnostics mask the real error
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            return None

    def _generate_checksum(self, file_path: Path) -> str:
        """Generate SHA256 checksum for backup file."""
        logger.info("Generating SHA256 checksum...")
        sha256_hash = hashlib.sha256()

        # Read file in chunks to handle large files efficiently
        with open(file_path, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    def _verify_dump_content(self, file_path: Path) -> bool:
        """Verify backup content integrity using pg_restore or syntax checks."""
        logger.info(f"Verifying content of dump file: {file_path.name}")

        try:
            # Format-specific verification
            if self.format == 'custom':
                # Use pg_restore --list to verify custom format backup
                if self.execution_mode == 'native':
                    cmd = [
                        'pg_restore',
                        '--list',
                        str(file_path)
                    ]
                else:  # Docker mode
                    host_dir, container_dir, container_file = self.docker_utils.prepare_path_for_docker(file_path)

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

                # Check that we got reasonable output
                lines = result.stdout.strip().split('\n')
                if len(lines) < 5:
                    logger.error("Backup verification failed - insufficient content")
                    return False

                logger.info(f"Backup contains {len(lines)} objects")

            else:
                # For SQL format, do basic syntax verification
                # Check file is readable and contains expected SQL keywords
                with open(file_path, 'r') as f:
                    content = f.read(1000)  # Read first 1KB
                    if not any(keyword in content for keyword in ['CREATE', 'INSERT', 'TABLE']):
                        logger.error("Backup verification failed - no SQL content found")
                        return False

            logger.info("Dump content verification passed")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Backup content verification failed: {e}")
            logger.error(f"Error output: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Backup content verification failed: {e}")
            return False

    def verify_backup(self, backup_path: Path, metadata: BackupMetadata) -> bool:
        """
        Verify backup integrity.

        For custom format: Use pg_restore --list to verify structure
        For SQL format: Basic syntax check
        Also verifies checksum matches.
        """
        logger.info("Verifying backup integrity...")

        try:
            # Verify checksum first
            current_checksum = self._generate_checksum(backup_path)
            if current_checksum != metadata.checksum:
                logger.error("Checksum verification failed - backup may be corrupted")
                return False

            logger.info("Checksum verification passed")

            if metadata.encrypted:
                logger.info("Backup is encrypted, content was verified before encryption.")
                metadata.verified = True
                return True

            # For non-encrypted files, verify content directly
            if not self._verify_dump_content(backup_path):
                return False

            logger.info("Backup integrity verification passed")
            metadata.verified = True
            return True

        except Exception as e:
            logger.error(f"Backup verification failed: {e}")
            return False

    def upload_to_s3(self, metadata: BackupMetadata) -> bool:
        """
        Upload backup and metadata files to S3.

        Args:
            metadata: BackupMetadata object with backup information

        Returns:
            True if upload succeeded, False otherwise
        """
        if not self.enable_s3_upload:
            logger.info("S3 upload is disabled, skipping")
            return True

        if not self.s3_uploader:
            logger.error("S3 uploader not initialized")
            return False

        logger.info(f"Uploading backup to AWS S3. Bucket: {self.s3_bucket}, folder: {datetime.now().strftime('%m-%d-%Y')}")

        start_time = datetime.now()

        try:
            # Upload encrypted backup file
            backup_date = datetime.now()

            def progress_callback(bytes_transferred):
                """Progress callback for large uploads"""
                if metadata.size_bytes > 0:
                    percent = (bytes_transferred / metadata.size_bytes) * 100
                    if percent % 10 < 1:  # Log approximately every 10%
                        logger.debug(f"Upload progress: {percent:.1f}%")

            logger.info(f"Uploading backup file: {metadata.backup_path.name}")
            success, s3_key = self.s3_uploader.upload_backup_file(
                file_path=metadata.backup_path,
                backup_date=backup_date,
                callback=progress_callback
            )

            if not success:
                logger.error("Failed to upload backup file to S3")
                return False

            logger.info(f"✓ Backup uploaded: s3://{self.s3_bucket}/{s3_key}")

            # Verify upload by comparing checksums
            logger.info("Verifying S3 upload integrity...")
            if not self.s3_uploader.verify_upload(s3_key, metadata.checksum):
                logger.error("S3 upload verification failed - checksums don't match")
                logger.error("Backup may be corrupted in S3")
                return False

            logger.info("✓ Upload verified successfully")

            # Upload metadata file
            metadata_path = metadata.backup_path.with_suffix(
                metadata.backup_path.suffix + '.meta.json'
            )

            logger.info(f"Uploading metadata file: {metadata_path.name}")
            success, meta_s3_key = self.s3_uploader.upload_metadata_file(
                metadata_path=metadata_path,
                backup_date=backup_date
            )

            if not success:
                logger.warning("Failed to upload metadata file (backup file uploaded successfully)")
                # Don't fail the entire process if only metadata upload fails
            else:
                logger.info(f"✓ Metadata uploaded: s3://{self.s3_bucket}/{meta_s3_key}")

            # Update metadata with S3 info
            end_time = datetime.now()
            metadata.s3_uploaded = True
            metadata.s3_bucket = self.s3_bucket
            metadata.s3_key = s3_key
            metadata.s3_upload_timestamp = end_time.isoformat()
            metadata.s3_upload_duration_seconds = (end_time - start_time).total_seconds()

            # Re-save metadata with S3 info
            metadata.save()

            logger.info(f"S3 upload completed in {metadata.s3_upload_duration_seconds:.2f}s")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"S3 upload failed: {e}", exc_info=True)
            return False

    def cleanup_old_backups(self):
        """
        Implement backup rotation policy.

        Retention policy:
        - Daily backups: Keep for specified days
        - Weekly backups: Keep for specified weeks
        - Monthly backups: Keep for specified months
        """
        logger.info("Cleaning up old backups...")
        logger.info(f"Retention policy: {self.retention_daily}d daily, "
                   f"{self.retention_weekly // 7}w weekly, "
                   f"{self.retention_monthly // 30}m monthly")

        now = datetime.now()
        deleted_count = 0
        kept_count = 0

        # Get all backup files
        backup_patterns = ['*.dump', '*.sql', '*.dump.gpg', '*.sql.gpg']
        backup_files = []
        for pattern in backup_patterns:
            backup_files.extend(self.backup_dir.glob(pattern))

        for backup_file in backup_files:
            try:
                # Parse filename to determine backup type and date
                # Expected format: dbname_type_YYYYMMDD_HHMMSS.ext
                parts = backup_file.stem.split('_')
                if len(parts) < 4:
                    logger.warning(f"Skipping file with unexpected format: {backup_file.name}")
                    continue

                backup_type = parts[1]
                date_str = parts[2]

                # Parse date
                backup_date = datetime.strptime(date_str, "%Y%m%d")
                age_days = (now - backup_date).days

                # Determine if backup should be deleted based on type and age
                should_delete = False

                if backup_type == 'daily' and age_days > self.retention_daily:
                    should_delete = True
                elif backup_type == 'weekly' and age_days > self.retention_weekly:
                    should_delete = True
                elif backup_type == 'monthly' and age_days > self.retention_monthly:
                    should_delete = True

                if should_delete:
                    # Delete backup file and associated metadata
                    backup_file.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old {backup_type} backup: {backup_file.name} (age: {age_days}d)")

                    # Delete metadata file if exists
                    # For encrypted files (e.g., file.dump.gpg), metadata is file.dump.gpg.meta.json
                    # For unencrypted files (e.g., file.dump), metadata is file.dump.meta.json
                    # Use .name + '.meta.json' to handle both cases correctly
                    meta_file = backup_file.parent / (backup_file.name + '.meta.json')
                    if meta_file.exists():
                        meta_file.unlink()
                        logger.debug(f"Deleted metadata: {meta_file.name}")
                else:
                    kept_count += 1

            except Exception as e:
                logger.warning(f"Error processing backup file {backup_file.name}: {e}")

        logger.info(f"Cleanup complete: {deleted_count} deleted, {kept_count} kept")

    def list_backups(self):
        """List all existing backups with metadata."""
        logger.info("Existing backups:")
        logger.info("-" * 80)

        backup_patterns = ['*.dump', '*.sql', '*.dump.gpg', '*.sql.gpg']
        backup_files = []
        for pattern in backup_patterns:
            backup_files.extend(self.backup_dir.glob(pattern))

        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        if not backup_files:
            logger.info("No backups found")
            return

        for backup_file in backup_files:
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)

            # Try to load metadata if available
            meta_file = backup_file.with_suffix(backup_file.suffix + '.meta.json')
            if meta_file.exists():
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    verified_status = "VERIFIED" if meta.get('verified') else "UNVERIFIED"
                    encrypted_status = "ENCRYPTED" if meta.get('encrypted') else "UNENCRYPTED"
                    logger.info(f"  {backup_file.name}")
                    logger.info(f"    Type: {meta.get('backup_type', 'unknown')}, "
                               f"Size: {size_mb:.2f} MB, "
                               f"Date: {mtime.strftime('%Y-%m-%d %H:%M:%S')}, "
                               f"Status: {verified_status}, Encryption: {encrypted_status}")
                except Exception:
                    logger.info(f"  {backup_file.name} - {size_mb:.2f} MB - {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                logger.info(f"  {backup_file.name} - {size_mb:.2f} MB - {mtime.strftime('%Y-%m-%d %H:%M:%S')}")

        logger.info("-" * 80)

    def cleanup_old_s3_backups(self):
        """
        Remove old backups from S3 based on retention policy.

        This mirrors the local cleanup logic but for S3.
        Only runs if --s3-cleanup flag is provided.
        """
        if not self.enable_s3_upload or not self.s3_uploader:
            return

        if not self.s3_cleanup:
            logger.info("S3 cleanup not requested (use --s3-cleanup to enable)")
            return

        logger.info("Cleaning up old S3 backups...")
        logger.info(f"Retention policy: {self.retention_daily}d daily, "
                   f"{self.retention_weekly // 7}w weekly, "
                   f"{self.retention_monthly // 30}m monthly")

        try:
            deleted_count = self.s3_uploader.delete_old_s3_backups(
                retention_daily=self.retention_daily,
                retention_weekly=self.retention_weekly,
                retention_monthly=self.retention_monthly
            )
            logger.info(f"Deleted {deleted_count} old backups from S3")
            logger.info("=" * 60)
        except Exception as e:
            logger.warning(f"S3 cleanup failed: {e}")

    def run(self) -> bool:
        """Execute the complete backup process."""
        logger.info("=" * 60)
        logger.info("MPI Backend Database Backup")
        logger.info("=" * 60)

        # Validate environment
        if not self.validate_environment():
            logger.error("Environment validation failed")
            return False

        # Test database connection and get version
        connected, pg_version = self.test_database_connection()
        if not connected:
            logger.error("Database connection failed")
            return False

        # List existing backups
        self.list_backups()

        # Create backup
        metadata = self.create_backup()
        if not metadata:
            logger.error("Backup creation failed")
            return False

        metadata.pg_version = pg_version

        # Verify backup
        if self.verify:
            if not self.verify_backup(metadata.backup_path, metadata):
                logger.error("Backup verification failed")
                return False
        else:
            logger.info("Skipping backup verification (--no-verify specified)")

        # Save metadata
        metadata.save()

        # Upload to S3 (if enabled and configured)
        if self.enable_s3_upload:
            if not self.upload_to_s3(metadata):
                logger.error("S3 upload failed. Backup created locally but S3 upload failed")
                logger.error(f"Local backup: {metadata.backup_path}")
                return False

        # Cleanup old backups (local)
        self.cleanup_old_backups()

        # Cleanup old S3 backups (if requested)
        if self.s3_cleanup:
            self.cleanup_old_s3_backups()

        logger.info("Backup process completed successfully")
        logger.info(f"Backup file: {metadata.backup_path}")
        logger.info(f"Backup size: {metadata.size_bytes / (1024 * 1024):.2f} MB")
        logger.info(f"Backup type: {metadata.backup_type}")
        logger.info(f"Duration: {metadata.duration_seconds:.2f} seconds")
        logger.info(f"Checksum: {metadata.checksum}")

        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Production-grade database backup for MPI Backend (GPG encrypted)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
IMPORTANT: All backups are encrypted using GPG (AES256).
           Set BACKUP_ENCRYPTION_KEY environment variable before running.

Examples:
  # Set encryption key (required)
  export BACKUP_ENCRYPTION_KEY='your-strong-passphrase-min-12-chars'

  # Create daily custom format backup with default settings
  python scripts/backup_database.py

  # Create SQL format backup
  python scripts/backup_database.py --format sql

  # Create backup with custom compression and retention
  python scripts/backup_database.py --compress-level 9 --retention-daily 14

  # Create backup with parallel dump (faster for large databases)
  python scripts/backup_database.py --jobs 4

  # Skip verification for faster backups (not recommended)
  python scripts/backup_database.py --no-verify

  # Disable S3 upload (enabled by default if credentials configured)
  python scripts/backup_database.py --no-s3-upload

  # Enable S3 cleanup of old backups
  python scripts/backup_database.py --s3-cleanup
        """
    )

    parser.add_argument(
        '--format',
        choices=['custom', 'sql'],
        default='custom',
        help='Backup format (default: custom). Custom format is compressed binary, SQL is plain text'
    )

    parser.add_argument(
        '--compress-level',
        type=int,
        choices=range(0, 10),
        default=6,
        metavar='N',
        help='Compression level for custom format, 0-9 (default: 6, 0=none, 9=max)'
    )

    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Skip backup verification (not recommended)'
    )

    parser.add_argument(
        '--retention-daily',
        type=int,
        default=7,
        metavar='N',
        help='Number of days to keep daily backups (default: 7)'
    )

    parser.add_argument(
        '--retention-weekly',
        type=int,
        default=4,
        metavar='N',
        help='Number of weeks to keep weekly backups (default: 4)'
    )

    parser.add_argument(
        '--retention-monthly',
        type=int,
        default=12,
        metavar='N',
        help='Number of months to keep monthly backups (default: 12)'
    )

    parser.add_argument(
        '--backup-dir',
        type=str,
        default='database_backups',
        metavar='PATH',
        help='Directory for backups (default: database backups/)'
    )

    parser.add_argument(
        '--jobs',
        type=int,
        default=1,
        metavar='N',
        help='Number of parallel dump jobs (default: 1, only for custom format)'
    )

    parser.add_argument(
        '--dump-timeout',
        type=int,
        default=1800,
        metavar='SECONDS',
        help='pg_dump timeout in seconds (default: 1800 = 30 minutes)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip safety confirmations'
    )

    parser.add_argument(
        '--no-s3-upload',
        action='store_true',
        help='Disable S3 upload (default: enabled if AWS credentials configured)'
    )

    parser.add_argument(
        '--s3-cleanup',
        action='store_true',
        help='Clean up old backups from S3 based on retention policy'
    )

    args = parser.parse_args()

    try:
        backup = DatabaseBackup(args)
        success = backup.run()

        if success:
            logger.info("Database backup completed successfully")
            sys.exit(0)
        else:
            logger.error("Database backup failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Backup process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
