from datetime import date, timedelta


def test_get_dropdown_items(client):
    # Test data
    today = date.today()
    payload = {
        "from_date": (today - timedelta(days=30)).isoformat(),
        "to_date": today.isoformat(),
    }

    # Make request
    response = client.post("/price-comparison/dropdown-items", json=payload)

    # Assert response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data and isinstance(data["items"], list)
    if len(data["items"]) > 0:
        item = data["items"][0]
        # ItemInfo fields
        assert "mpi_item" in item
        assert "item" in item or "original_item" in item or "description" in item


def test_get_selected_items_prices(client):
    # Test data
    items = [
        {
            "mpi_item": "CMPSPM02",
            "original_item": "COMP 1/4\"",
            "mpi_description": "1/4\" QUICK COUPLER PLUG FOR AIR COMP",
        }
    ]

    # Make request
    response = client.post("/price-comparison/selected-items", json=items)

    # Assert response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data and isinstance(data["items"], list)


def test_invalid_date_range(client):
    # Test data with invalid date format
    payload = {
        "from_date": "invalid-date",
        "to_date": "invalid-date",
    }

    # Make request
    response = client.post("/price-comparison/dropdown-items", json=payload)

    # Assert response
    assert response.status_code == 422  # Validation error


def test_empty_items_list(client):
    # Test with empty items list
    response = client.post("/price-comparison/selected-items", json=[])

    # Assert response
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data and data["items"] == [] 