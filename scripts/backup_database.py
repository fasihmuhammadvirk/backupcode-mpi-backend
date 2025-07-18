#!/usr/bin/env python3
"""
Database Backup Script for MPI Backend (Python-based)

This script creates a complete backup of the PostgreSQL database using Python libraries
instead of PostgreSQL client tools (pg_dump).

Usage:
    python scripts/backup_database_python.py

Requirements:
    - psycopg2 (already in requirements.txt)
    - sqlalchemy (already in requirements.txt)
    - Environment variables must be configured (.env file)
    - Sufficient disk space for the backup

Author: MPI Backend Team
Date: 2025-07-18
"""

import os
import sys
import datetime
import logging
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from sqlalchemy import create_engine, text, MetaData, inspect
from sqlalchemy.schema import CreateTable

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
        logging.FileHandler(project_root / 'logs' / 'backup_python.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PythonDatabaseBackup:
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
        
        # Database connection strings
        self.connection_string = f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        self.psycopg2_params = {
            'host': self.db_host,
            'port': self.db_port,
            'database': self.db_name,
            'user': self.db_user,
            'password': self.db_password
        }
    
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
    
    def test_database_connection(self):
        """Test database connection using psycopg2."""
        try:
            conn = psycopg2.connect(**self.psycopg2_params)
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()
            cursor.close()
            conn.close()
            
            logger.info(f"Database connection successful: {version[0]}")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
    
    def get_table_list(self):
        """Get list of all tables in the database."""
        try:
            engine = create_engine(self.connection_string)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            engine.dispose()
            return tables
        except Exception as e:
            logger.error(f"Error getting table list: {e}")
            return []
    
    def get_table_schema(self, table_name):
        """Get CREATE TABLE statement for a table."""
        try:
            engine = create_engine(self.connection_string)
            metadata = MetaData()
            metadata.reflect(bind=engine, only=[table_name])
            
            if table_name in metadata.tables:
                table = metadata.tables[table_name]
                create_statement = str(CreateTable(table).compile(engine))
                engine.dispose()
                return create_statement
            else:
                engine.dispose()
                return None
        except Exception as e:
            logger.error(f"Error getting schema for table {table_name}: {e}")
            return None
    
    def get_table_data(self, table_name):
        """Get all data from a table as INSERT statements."""
        try:
            conn = psycopg2.connect(**self.psycopg2_params)
            cursor = conn.cursor()
            
            # Get column names
            cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position")
            columns = [row[0] for row in cursor.fetchall()]
            
            # Get data
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            
            insert_statements = []
            for row in rows:
                # Format values properly for SQL
                formatted_values = []
                for value in row:
                    if value is None:
                        formatted_values.append('NULL')
                    elif isinstance(value, (int, float)):
                        formatted_values.append(str(value))
                    elif isinstance(value, bool):
                        formatted_values.append('TRUE' if value else 'FALSE')
                    else:
                        # Escape single quotes and wrap in quotes
                        escaped_value = str(value).replace("'", "''")
                        formatted_values.append(f"'{escaped_value}'")
                
                insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(formatted_values)});"
                insert_statements.append(insert_sql)
            
            cursor.close()
            conn.close()
            
            return insert_statements
        except Exception as e:
            logger.error(f"Error getting data for table {table_name}: {e}")
            return []
    
    def create_backup(self):
        """Create a complete database backup using Python."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"mpi_backend_db_backup_{timestamp}.sql"
        backup_path = self.backup_dir / backup_filename
        
        logger.info(f"Starting database backup: {backup_filename}")
        logger.info(f"Database: {self.db_name} on {self.db_host}:{self.db_port}")
        
        try:
            # Get list of tables
            tables = self.get_table_list()
            if not tables:
                logger.error("No tables found in database")
                return False
            
            logger.info(f"Found {len(tables)} tables to backup")
            
            with open(backup_path, 'w', encoding='utf-8') as backup_file:
                # Write header
                backup_file.write("-- MPI Backend Database Backup\n")
                backup_file.write(f"-- Generated on: {datetime.datetime.now()}\n")
                backup_file.write(f"-- Database: {self.db_name}\n")
                backup_file.write("-- Generated by Python backup script\n\n")
                
                # Write database creation
                backup_file.write(f"CREATE DATABASE {self.db_name};\n")
                backup_file.write(f"\\c {self.db_name};\n\n")
                
                # Process each table
                for i, table_name in enumerate(tables, 1):
                    logger.info(f"Processing table {i}/{len(tables)}: {table_name}")
                    
                    # Get table schema
                    schema = self.get_table_schema(table_name)
                    if schema:
                        backup_file.write(f"-- Table: {table_name}\n")
                        backup_file.write(f"DROP TABLE IF EXISTS {table_name} CASCADE;\n")
                        backup_file.write(schema + ";\n\n")
                        
                        # Get table data
                        data_statements = self.get_table_data(table_name)
                        if data_statements:
                            backup_file.write(f"-- Data for table: {table_name}\n")
                            for statement in data_statements:
                                backup_file.write(statement + "\n")
                            backup_file.write("\n")
                        
                        logger.info(f"Completed table {table_name} ({len(data_statements)} rows)")
                    else:
                        logger.warning(f"Could not get schema for table {table_name}")
                
                # Write footer
                backup_file.write("-- Backup completed\n")
            
            # Get file size
            file_size = backup_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)
            
            logger.info(f"Backup completed successfully!")
            logger.info(f"Backup file: {backup_path}")
            logger.info(f"File size: {file_size_mb:.2f} MB")
            
            # Create a copy to the project root with the standard name
            latest_backup = self.project_root / "mpi_backend_db_copy.sql"
            import shutil
            shutil.copy2(backup_path, latest_backup)
            logger.info(f"Created latest backup copy: {latest_backup}")
            
            return True
            
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
        logger.info("MPI Backend Database Backup Started (Python-based)")
        logger.info("=" * 60)
        
        # Validate environment
        if not self.validate_environment():
            logger.error("Environment validation failed. Exiting.")
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
        backup = PythonDatabaseBackup()
        success = backup.run()
        
        if success:
            print("\n✅ Database backup completed successfully!")
            print("📁 Backup files are saved in the 'backups' directory")
            print("📄 Latest backup is also saved as 'mpi_backend_db_copy.sql'")
            print("🐍 This backup was created using Python libraries (no pg_dump required)")
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