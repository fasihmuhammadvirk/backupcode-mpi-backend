#!/usr/bin/env python3
"""
Simple runner script for the missing invoice finder tool.

This script provides a simple way to run the missing invoice finder process
with proper error handling and user feedback.
"""

import sys
import os
from pathlib import Path

# Add the current directory to Python path to import our script
sys.path.insert(0, str(Path(__file__).parent))

try:
    from missing_invoice_finder import MissingInvoiceFinder
    
    def main():
        print("🔍 Starting Missing Invoice Finder...")
        print("=" * 60)
        
        # Check if missing invoices file exists
        missing_file = "missing_invoices.xlsx"
        if not Path(missing_file).exists():
            print(f"❌ Error: Missing invoices file '{missing_file}' not found!")
            print("Please ensure the file is in the same directory as this script.")
            return False
        
        # Check if .env file exists
        if not Path(".env").exists():
            print("⚠️  Warning: .env file not found!")
            print("Please ensure your database and email credentials are configured.")
        
        try:
            # Create and run the finder
            finder = MissingInvoiceFinder()
            success = finder.run_complete_process()
            
            if success:
                print("\n" + "=" * 60)
                print("✅ Missing invoice finder completed successfully!")
                print("📊 Files created:")
                print(f"  - {finder.missing_file}")
                print(f"  - {finder.summary_file}")
                print(f"  - Attachments in: {finder.download_dir}")
                print("📝 Check the log file for detailed information")
                return True
            else:
                print("\n" + "=" * 60)
                print("❌ Missing invoice finder failed!")
                print("📝 Check the log file for error details")
                return False
                
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            print("📝 Check the log file for more details")
            return False
    
    if __name__ == "__main__":
        success = main()
        sys.exit(0 if success else 1)
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Please ensure all required packages are installed:")
    print("  pip install pandas openpyxl sqlalchemy psycopg2 python-dotenv")
    sys.exit(1)
