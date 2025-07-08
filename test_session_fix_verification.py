#!/usr/bin/env python3
"""
Test script to verify the session binding fix for invoice processing.
Tests that the 'Instance is not bound to a Session' error is resolved.
"""

import requests
import json
import os
import sys

def test_upload_endpoint():
    """Test the /invoice/upload endpoint to verify session fix"""
    
    # Test configuration
    base_url = "http://localhost:8000"  # Adjust if your server runs on different port
    endpoint = f"{base_url}/invoice/upload"
    
    # Check if test PDF file exists
    test_file = "mpi_backend/storage/BMW Plumbing Supplies/doc00043403.pdf"
    if not os.path.exists(test_file):
        print(f"❌ Test file not found: {test_file}")
        print("Please ensure the file exists or adjust the path")
        return False
    
    try:
        # Test file upload
        print(f"🔄 Testing upload endpoint with file: {test_file}")
        
        with open(test_file, 'rb') as f:
            files = {'file': (os.path.basename(test_file), f, 'application/pdf')}
            
            response = requests.post(endpoint, files=files, timeout=60)
            
        print(f"📊 Response Status: {response.status_code}")
        print(f"📊 Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"✅ Success Response: {json.dumps(result, indent=2)}")
                return True
            except json.JSONDecodeError:
                print(f"✅ Success Response (non-JSON): {response.text}")
                return True
        else:
            print(f"❌ Error Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False

def test_health_check():
    """Test if the server is running"""
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
            return True
        else:
            print(f"❌ Server health check failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException:
        print("❌ Server is not running or not accessible")
        return False

def main():
    """Run the test suite"""
    print("🧪 Testing Invoice Upload Session Fix")
    print("=" * 50)
    
    # Test 1: Health check
    if not test_health_check():
        print("\n💡 Please start the server first:")
        print("   uvicorn mpi_backend.main:app --reload --host 0.0.0.0 --port 8000")
        return 1
    
    # Test 2: Upload endpoint
    print("\n🔄 Testing upload endpoint...")
    success = test_upload_endpoint()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ All tests passed! Session binding issue appears to be fixed.")
        return 0
    else:
        print("❌ Tests failed. Please check the server logs for errors.")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 