#!/usr/bin/env python3
"""
Simple test for the unmapped-items endpoint
"""

import requests
import json

def test_endpoint():
    """Test the unmapped-items endpoint"""
    
    # Configuration
    BASE_URL = "http://localhost:8000"
    ENDPOINT = "/filter/unmapped-items"
    
    # Test payload
    payload = {
        "item_type": "unmapped"
    }
    
    print("🧪 Testing /filter/unmapped-items endpoint")
    print(f"📍 URL: {BASE_URL}{ENDPOINT}")
    print(f"📝 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        # Make request
        response = requests.post(
            f"{BASE_URL}{ENDPOINT}",
            json=payload,
            params={"page": 1, "size": 5},
            timeout=30
        )
        
        print(f"\n📊 Status Code: {response.status_code}")
        print(f"⏱️  Response Time: {response.elapsed.total_seconds():.3f}s")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ SUCCESS! Endpoint is working!")
            print(f"📊 Response keys: {list(data.keys())}")
            print(f"📦 Items count: {len(data.get('items', []))}")
            print(f"📄 Total count: {data.get('total_count', 0)}")
            print(f"📄 Pages: {data.get('pages', 0)}")
            
            # Show first item if available
            if data.get('items'):
                first_item = data['items'][0]
                print(f"\n📋 First item:")
                print(f"   ID: {first_item.get('original_item_id')}")
                print(f"   Description: {first_item.get('original_description')}")
                print(f"   Cost: {first_item.get('cost')}")
                print(f"   Amount: {first_item.get('amount')}")
                print(f"   Supplier: {first_item.get('supplier')}")
                
        else:
            print(f"❌ ERROR: {response.status_code}")
            print(f"📝 Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Connection error: Server not running")
        print("💡 Start server with: uvicorn mpi_backend.main:app --reload")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_endpoint()
