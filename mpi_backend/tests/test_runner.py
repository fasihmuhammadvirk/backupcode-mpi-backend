"""
Test runner for mapping functionality tests.

This script provides a simple way to run all mapping-related tests
and generate a test report.
"""

import pytest
import sys
import os

def run_mapping_tests():
    """Run all mapping-related tests"""
    print("Running Google Sheets mapping tests...")
    print("=" * 50)
    
    # Get the directory containing this file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Test files to run
    test_files = [
        "test_google_sheets_extraction.py",
        "test_mapping_sync_endpoint.py"
    ]
    
    # Build full paths
    test_paths = [os.path.join(test_dir, test_file) for test_file in test_files]
    
    # Run tests with verbose output
    args = [
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "--disable-warnings",  # Disable pytest warnings
        *test_paths
    ]
    
    print(f"Running tests: {', '.join(test_files)}")
    print("-" * 50)
    
    # Run pytest
    exit_code = pytest.main(args)
    
    print("-" * 50)
    if exit_code == 0:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
    
    print("=" * 50)
    return exit_code

def run_specific_test(test_name):
    """Run a specific test by name"""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    
    if not test_name.endswith('.py'):
        test_name += '.py'
    
    test_path = os.path.join(test_dir, test_name)
    
    if not os.path.exists(test_path):
        print(f"❌ Test file not found: {test_path}")
        return 1
    
    print(f"Running specific test: {test_name}")
    print("-" * 30)
    
    args = ["-v", "--tb=short", "--disable-warnings", test_path]
    exit_code = pytest.main(args)
    
    return exit_code

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run specific test
        test_name = sys.argv[1]
        exit_code = run_specific_test(test_name)
    else:
        # Run all mapping tests
        exit_code = run_mapping_tests()
    
    sys.exit(exit_code) 