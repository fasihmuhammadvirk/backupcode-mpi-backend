#!/usr/bin/env python3
"""
Database Backup Script for MPI Backend

This script creates a complete backup of the PostgreSQL database and saves it
in the project repository with a timestamp.

Usage:
    python scripts/backup_database.py

Requirements:
    - PostgreSQL client tools (pg_dump) must be installed
    - Environment variables must be configured (.env file)
    - Sufficient disk space for the backup

Author: MPI Backend Team
Date: 2025-07-18
"""

import os
import sys
import subprocess
import datetime
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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

class DatabaseBackup:
    def __init__(self):
        self.project_root = project_root
        self.backup_dir = project_root / 'backups'
        self.logs_dir = project_root / 'logs'
        
        # Database configuration from environment
        self.db_host = os.getenv("POSTGRES_HOST", "localhost")
        self.db_port = os.getenv("POSTGRES_PORT", "5432")
        self.db_name = os.getenv("POSTGRES_DB", "mpi_backend")
        self.db_user = os.getenv("POSTGRES_USERNAME", "postgres")
        self.db_password = os.getenv("POSTGRES_PASSWORD", "")
        
        # Create directories if they don't exist
        self.backup_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
    
    def validate_environment(self):
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
        
        return True
    
    def check_pg_dump(self):
        """Check if pg_dump is available."""
        try:
            result = subprocess.run(['pg_dump', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"pg_dump found: {result.stdout.strip()}")
                return True
            else:
                logger.error("pg_dump not found or not working")
                return False
        except FileNotFoundError:
            logger.error("pg_dump not found. Please install PostgreSQL client tools.")
            return False
        except subprocess.TimeoutExpired:
            logger.error("pg_dump command timed out")
            return False
    
    def test_database_connection(self):
        """Test database connection."""
        try:
            # Use psql to test connection
            env = os.environ.copy()
            env['PGPASSWORD'] = self.db_password
            
            cmd = [
                'psql',
                '-h', self.db_host,
                '-p', self.db_port,
                '-U', self.db_user,
                '-d', self.db_name,
                '-c', 'SELECT version();'
            ]
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info("Database connection successful")
                return True
            else:
                logger.error(f"Database connection failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error testing database connection: {e}")
            return False
    
    def create_backup(self):
        """Create a complete database backup."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"mpi_backend_db_backup_{timestamp}.sql"
        backup_path = self.backup_dir / backup_filename
        
        logger.info(f"Starting database backup: {backup_filename}")
        logger.info(f"Database: {self.db_name} on {self.db_host}:{self.db_port}")
        
        # Set up environment for pg_dump
        env = os.environ.copy()
        env['PGPASSWORD'] = self.db_password
        
        # Build pg_dump command
        cmd = [
            'pg_dump',
            '-h', self.db_host,
            '-p', self.db_port,
            '-U', self.db_user,
            '-d', self.db_name,
            '--verbose',
            '--clean',
            '--create',
            '--if-exists',
            '--no-owner',
            '--no-privileges',
            '--format=plain',
            '--file', str(backup_path)
        ]
        
        try:
            logger.info("Executing pg_dump...")
            start_time = datetime.datetime.now()
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)  # 1 hour timeout
            
            end_time = datetime.datetime.now()
            duration = end_time - start_time
            
            if result.returncode == 0:
                # Get file size
                file_size = backup_path.stat().st_size
                file_size_mb = file_size / (1024 * 1024)
                
                logger.info(f"Backup completed successfully!")
                logger.info(f"Backup file: {backup_path}")
                logger.info(f"File size: {file_size_mb:.2f} MB")
                logger.info(f"Duration: {duration}")
                
                # Create a symlink to the latest backup
                latest_backup = self.project_root / "mpi_backend_db_copy.sql"
                if latest_backup.exists():
                    latest_backup.unlink()  # Remove existing symlink
                
                # Copy the backup to the project root with the standard name
                import shutil
                shutil.copy2(backup_path, latest_backup)
                logger.info(f"Created latest backup copy: {latest_backup}")
                
                return True
            else:
                logger.error(f"Backup failed with return code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Backup timed out after 1 hour")
            return False
        except Exception as e:
            logger.error(f"Error during backup: {e}")
            return False
    
    def cleanup_old_backups(self, keep_days=7):
        """Clean up old backup files, keeping only recent ones."""
        logger.info(f"Cleaning up backups older than {keep_days} days...")
        
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=keep_days)
        deleted_count = 0
        
        for backup_file in self.backup_dir.glob("mpi_backend_db_backup_*.sql"):
            try:
                file_time = datetime.datetime.fromtimestamp(backup_file.stat().st_mtime)
                if file_time < cutoff_date:
                    backup_file.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old backup: {backup_file.name}")
            except Exception as e:
                logger.warning(f"Could not delete {backup_file.name}: {e}")
        
        logger.info(f"Cleanup completed. Deleted {deleted_count} old backup files.")
    
    def run(self):
        """Main backup process."""
        logger.info("=" * 60)
        logger.info("MPI Backend Database Backup Started")
        logger.info("=" * 60)
        
        # Validate environment
        if not self.validate_environment():
            logger.error("Environment validation failed. Exiting.")
            return False
        
        # Check pg_dump availability
        if not self.check_pg_dump():
            logger.error("pg_dump check failed. Exiting.")
            return False
        
        # Test database connection
        if not self.test_database_connection():
            logger.error("Database connection test failed. Exiting.")
            return False
        
        # Create backup
        if not self.create_backup():
            logger.error("Backup creation failed. Exiting.")
            return False
        
        # Cleanup old backups
        self.cleanup_old_backups()
        
        logger.info("=" * 60)
        logger.info("Database backup process completed successfully!")
        logger.info("=" * 60)
        
        return True

def main():
    """Main entry point."""
    try:
        backup = DatabaseBackup()
        success = backup.run()
        
        if success:
            print("\n✅ Database backup completed successfully!")
            print("📁 Backup files are saved in the 'backups' directory")
            print("📄 Latest backup is also saved as 'mpi_backend_db_copy.sql'")
            sys.exit(0)
        else:
            print("\n❌ Database backup failed!")
            print("📋 Check the logs for detailed error information")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Backup process interrupted by user")
        print("\n⚠️  Backup process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 