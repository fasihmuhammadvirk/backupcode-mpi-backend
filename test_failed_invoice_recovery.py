#!/usr/bin/env python3
"""
Test script for the new failed invoice recovery utility
"""
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(__file__))

from mpi_backend.utils.failed_invoice_recovery import process_failed_invoice_recovery

if __name__ == "__main__":
    print("Testing failed invoice recovery utility...")
    try:
        process_failed_invoice_recovery()
        print("Test completed successfully!")
    except Exception as e:
        print(f"Test failed: {str(e)}")
        sys.exit(1) 