#!/usr/bin/env python3
"""
Test script for the /filter/unmapped-items endpoint
"""

import requests
import json
import time
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000"  # Adjust if your server runs on different port
TEST_TOKEN = "your_test_token_here"  # Replace with actual test token

def test_unmapped_items_endpoint():
    """Test the unmapped-items endpoint with various scenarios"""
    
    print("🧪 Testing /filter/unmapped-items endpoint")
    print("=" * 50)
    
    # Test 1: Basic unmapped items request
    print("\n1️⃣ Testing basic unmapped items request...")
    test_basic_unmapped()
    
    # Test 2: Temporary items request
    print("\n2️⃣ Testing temporary items request...")
    test_temporary_items()
    
    # Test 3: No temporary items request
    print("\n3️⃣ Testing no temporary items request...")
    test_no_temporary_items()
    
    # Test 4: With date filters
    print("\n4️⃣ Testing with date filters...")
    test_with_date_filters()
    
    # Test 5: With supplier filters
    print("\n5️⃣ Testing with supplier filters...")
    test_with_supplier_filters()
    
    # Test 6: With search
    print("\n6️⃣ Testing with search...")
    test_with_search()
    
    # Test 7: With ordering
    print("\n7️⃣ Testing with ordering...")
    test_with_ordering()
    
    # Test 8: Pagination
    print("\n8️⃣ Testing pagination...")
    test_pagination()
    
    print("\n✅ All tests completed!")

def test_basic_unmapped():
    """Test basic unmapped items request"""
    payload = {
        "item_type": "unmapped"
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ Basic unmapped items: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")
        print(f"   📄 Pages: {response.get('pages', 0)}")

def test_temporary_items():
    """Test temporary items request"""
    payload = {
        "item_type": "temporary"
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ Temporary items: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")

def test_no_temporary_items():
    """Test no temporary items request"""
    payload = {
        "item_type": "no_temporary"
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ No temporary items: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")

def test_with_date_filters():
    """Test with date filters"""
    payload = {
        "item_type": "unmapped",
        "date_from": "2024-01-01",
        "date_to": "2024-12-31"
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ Date filtered: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")

def test_with_supplier_filters():
    """Test with supplier filters"""
    payload = {
        "item_type": "unmapped",
        "supplier_names": ["BMW Plumbing Supplies"]
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ Supplier filtered: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")

def test_with_search():
    """Test with search"""
    payload = {
        "item_type": "unmapped",
        "search": "pipe"
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ Search filtered: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")

def test_with_ordering():
    """Test with ordering"""
    payload = {
        "item_type": "unmapped",
        "order_by": [
            {"column": "amount", "order": "desc"},
            {"column": "supplier", "order": "asc"}
        ]
    }
    
    response = make_request("/filter/unmapped-items", payload)
    if response:
        print(f"   ✅ Ordered results: {len(response.get('items', []))} items found")
        print(f"   📊 Total count: {response.get('total_count', 0)}")

def test_pagination():
    """Test pagination"""
    payload = {
        "item_type": "unmapped"
    }
    
    # Test first page
    response1 = make_request("/filter/unmapped-items", payload, page=1, size=5)
    if response1:
        print(f"   ✅ Page 1: {len(response1.get('items', []))} items")
        print(f"   📊 Total count: {response1.get('total_count', 0)}")
        print(f"   📄 Current page: {response1.get('page', 1)}")
        print(f"   📄 Total pages: {response1.get('pages', 0)}")
    
    # Test second page if available
    if response1 and response1.get('pages', 0) > 1:
        response2 = make_request("/filter/unmapped-items", payload, page=2, size=5)
        if response2:
            print(f"   ✅ Page 2: {len(response2.get('items', []))} items")
            print(f"   📄 Current page: {response2.get('page', 2)}")

def make_request(endpoint, payload, page=1, size=10):
    """Make a request to the endpoint"""
    try:
        url = f"{BASE_URL}{endpoint}"
        params = {"page": page, "size": size}
        
        headers = {
            "Authorization": f"Bearer {TEST_TOKEN}",
            "Content-Type": "application/json"
        }
        
        print(f"   🌐 Making request to: {endpoint}")
        print(f"   📝 Payload: {json.dumps(payload, indent=2)}")
        print(f"   📄 Params: page={page}, size={size}")
        
        start_time = time.time()
        response = requests.post(url, json=payload, params=params, headers=headers)
        end_time = time.time()
        
        print(f"   ⏱️  Response time: {(end_time - start_time):.3f}s")
        print(f"   📊 Status code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Response keys: {list(data.keys())}")
            return data
        else:
            print(f"   ❌ Error: {response.status_code}")
            print(f"   📝 Response: {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print(f"   ❌ Connection error: Could not connect to {BASE_URL}")
        print(f"   💡 Make sure your server is running on {BASE_URL}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Request error: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"   ❌ JSON decode error: {e}")
        print(f"   📝 Raw response: {response.text}")
        return None
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        return None

def test_health_endpoint():
    """Test if the server is running"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running and healthy!")
            return True
        else:
            print(f"⚠️  Server responded with status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server")
        print("💡 Make sure your server is running with: uvicorn mpi_backend.main:app --reload")
        return False
    except Exception as e:
        print(f"❌ Error checking server health: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting unmapped items endpoint tests...")
    print(f"📍 Server URL: {BASE_URL}")
    print(f"🕐 Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # First check if server is running
    if test_health_endpoint():
        test_unmapped_items_endpoint()
    else:
        print("\n❌ Cannot proceed with tests - server is not available")
        print("\n💡 To start the server:")
        print("   1. Make sure you're in the project directory")
        print("   2. Run: uvicorn mpi_backend.main:app --reload")
        print("   3. Or restart your service: sudo systemctl restart mpi-backend")
        print("   4. Then run this test script again")
