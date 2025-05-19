from fastapi.testclient import TestClient
from datetime import date, timedelta
from mpi_backend.main import app

client = TestClient(app)

def test_get_dropdown_items():
    # Test data
    today = date.today()
    payload = {
        "from_date": (today - timedelta(days=30)).isoformat(),
        "to_date": today.isoformat()
    }

    # Make request
    response = client.post("/price-comparison/dropdown-items", json=payload)

    # Assert response
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    if len(items) > 0:
        item = items[0]
        assert "mpi_item" in item
        assert "original_item" in item
        assert "mpi_description" in item

def test_get_selected_items_prices():
    # Test data
    items = [
        {
            "mpi_item": "CMPSPM02",
            "original_item": "COMP 1/4\"",
            "mpi_description": "1/4\" QUICK COUPLER PLUG FOR AIR COMP"
        }
    ]

    # Make request
    response = client.post("/price-comparison/selected-items", json=items)

    # Assert response
    assert response.status_code == 200
    price_info = response.json()
    assert isinstance(price_info, list)
    if len(price_info) > 0:
        item = price_info[0]
        assert "mpi_item" in item
        assert "original_item" in item
        assert "mpi_description" in item
        assert "unit_price" in item

def test_invalid_date_range():
    # Test data with invalid date format
    payload = {
        "from_date": "invalid-date",
        "to_date": "invalid-date"
    }

    # Make request
    response = client.post("/price-comparison/dropdown-items", json=payload)

    # Assert response
    assert response.status_code == 422  # Validation error

def test_empty_items_list():
    # Test with empty items list
    response = client.post("/price-comparison/selected-items", json=[])

    # Assert response
    assert response.status_code == 200
    assert response.json() == [] 