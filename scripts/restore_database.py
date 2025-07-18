#!/usr/bin/env python3
"""
Database Restore Script for MPI Backend

This script will:
1. Drop the existing database (if it exists)
2. Create a new database
3. Restore data from the backup SQL file
4. Verify the restoration

Usage:
    python scripts/restore_database.py [--backup-file path/to/backup.sql] [--force]

Options:
    --backup-file: Path to the backup SQL file (default: backups/mpi_backend_db_backup.sql)
    --force: Skip confirmation prompts
"""

import os
import sys
import argparse
import subprocess
import time
from pathlib import Path
import logging
from datetime import datetime

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mpi_backend.config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, 
    POSTGRES_USERNAME, POSTGRES_PASSWORD
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'logs/restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)


class DatabaseRestorer:
    def __init__(self, backup_file=None, force=False):
        self.backup_file = backup_file or "backups/mpi_backend_db_backup.sql"
        self.force = force
        
        # Database connection parameters
        self.host = POSTGRES_HOST or "localhost"
        self.port = POSTGRES_PORT or 5432
        self.database = POSTGRES_DB or "mpi_db"
        self.username = POSTGRES_USERNAME or "woodpecker"
        self.password = POSTGRES_PASSWORD or "woodpecker"
        
        # Ensure logs directory exists
        Path("logs").mkdir(exist_ok=True)
        
    def _run_command(self, command, check=True, capture_output=True):
        """Run a shell command and return the result"""
        try:
            logger.info(f"Running command: {' '.join(command)}")
            result = subprocess.run(
                command,
                check=check,
                capture_output=capture_output,
                text=True,
                env={**os.environ, 'PGPASSWORD': self.password}
            )
            if result.stdout:
                logger.info(f"Command output: {result.stdout}")
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e}")
            if e.stderr:
                logger.error(f"Error output: {e.stderr}")
            if check:
                raise
            return e
    
    def _check_backup_file(self):
        """Check if the backup file exists and is readable"""
        backup_path = Path(self.backup_file)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {self.backup_file}")
        
        if not backup_path.is_file():
            raise ValueError(f"Backup path is not a file: {self.backup_file}")
        
        file_size = backup_path.stat().st_size
        logger.info(f"Backup file found: {self.backup_file} ({file_size:,} bytes)")
        
        if file_size == 0:
            raise ValueError("Backup file is empty")
        
        return backup_path
    
    def _check_postgres_connection(self):
        """Check if PostgreSQL is accessible"""
        logger.info("Checking PostgreSQL connection...")
        
        # Try to connect to postgres database (default database)
        command = [
            "psql",
            "-h", self.host,
            "-p", str(self.port),
            "-U", self.username,
            "-d", "postgres",
            "-c", "SELECT version();"
        ]
        
        result = self._run_command(command, check=False)
        if result.returncode != 0:
            raise ConnectionError(f"Cannot connect to PostgreSQL at {self.host}:{self.port}")
        
        logger.info("PostgreSQL connection successful")
    
    def _drop_database(self):
        """Drop the existing database if it exists"""
        logger.info(f"Dropping database '{self.database}' if it exists...")
        
        # First, terminate all connections to the database
        terminate_command = [
            "psql",
            "-h", self.host,
            "-p", str(self.port),
            "-U", self.username,
            "-d", "postgres",
            "-c", f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '{self.database}'
            AND pid <> pg_backend_pid();
            """
        ]
        
        self._run_command(terminate_command, check=False)
        
        # Drop the database
        drop_command = [
            "psql",
            "-h", self.host,
            "-p", str(self.port),
            "-U", self.username,
            "-d", "postgres",
            "-c", f"DROP DATABASE IF EXISTS {self.database};"
        ]
        
        self._run_command(drop_command)
        logger.info(f"Database '{self.database}' dropped successfully")
    
    def _create_database(self):
        """Create a new database"""
        logger.info(f"Creating new database '{self.database}'...")
        
        create_command = [
            "psql",
            "-h", self.host,
            "-p", str(self.port),
            "-U", self.username,
            "-d", "postgres",
            "-c", f"CREATE DATABASE {self.database};"
        ]
        
        self._run_command(create_command)
        logger.info(f"Database '{self.database}' created successfully")
    
    def _restore_database(self):
        """Restore the database from the backup file"""
        logger.info(f"Restoring database from backup: {self.backup_file}")
        
        restore_command = [
            "psql",
            "-h", self.host,
            "-p", str(self.port),
            "-U", self.username,
            "-d", self.database,
            "-f", self.backup_file
        ]
        
        start_time = time.time()
        self._run_command(restore_command)
        end_time = time.time()
        
        duration = end_time - start_time
        logger.info(f"Database restoration completed in {duration:.2f} seconds")
    
    def _verify_restoration(self):
        """Verify that the restoration was successful"""
        logger.info("Verifying database restoration...")
        
        # Check if database exists and has tables
        verify_command = [
            "psql",
            "-h", self.host,
            "-p", str(self.port),
            "-U", self.username,
            "-d", self.database,
            "-c", """
            SELECT 
                schemaname,
                relname as tablename,
                n_tup_ins as rows
            FROM pg_stat_user_tables 
            ORDER BY schemaname, relname;
            """
        ]
        
        result = self._run_command(verify_command)
        
        if "0 rows" in result.stdout:
            logger.warning("No tables found in the restored database")
        else:
            logger.info("Database restoration verification successful")
            logger.info("Tables found in the restored database:")
            # Print the table information
            lines = result.stdout.strip().split('\n')
            for line in lines[2:]:  # Skip header lines
                if line.strip():
                    logger.info(f"  {line}")
    
    def _get_confirmation(self):
        """Get user confirmation before proceeding"""
        if self.force:
            return True
        
        print("\n" + "="*60)
        print("DATABASE RESTORE WARNING")
        print("="*60)
        print(f"This will:")
        print(f"  1. DROP the existing database '{self.database}'")
        print(f"  2. CREATE a new database '{self.database}'")
        print(f"  3. RESTORE from backup: {self.backup_file}")
        print(f"  4. ALL EXISTING DATA WILL BE LOST!")
        print("="*60)
        
        response = input("\nAre you sure you want to proceed? (yes/no): ").lower().strip()
        return response in ['yes', 'y']
    
    def restore(self):
        """Main restore method"""
        try:
            logger.info("Starting database restoration process...")
            
            # Check backup file
            self._check_backup_file()
            
            # Check PostgreSQL connection
            self._check_postgres_connection()
            
            # Get user confirmation
            if not self._get_confirmation():
                logger.info("Restoration cancelled by user")
                return False
            
            # Perform restoration steps
            self._drop_database()
            self._create_database()
            self._restore_database()
            self._verify_restoration()
            
            logger.info("Database restoration completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Database restoration failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Restore MPI Backend database from backup")
    parser.add_argument(
        "--backup-file",
        default="backups/mpi_backend_db_backup.sql",
        help="Path to the backup SQL file (default: backups/mpi_backend_db_backup.sql)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts"
    )
    
    args = parser.parse_args()
    
    # Create restorer instance
    restorer = DatabaseRestorer(
        backup_file=args.backup_file,
        force=args.force
    )
    
    # Perform restoration
    success = restorer.restore()
    
    if success:
        print("\n✅ Database restoration completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Database restoration failed!")
        sys.exit(1)


if __name__ == "__main__":
    main() 