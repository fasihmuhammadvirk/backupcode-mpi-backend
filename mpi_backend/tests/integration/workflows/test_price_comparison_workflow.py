from datetime import date, timedelta
from unittest.mock import patch, Mock


def test_get_dropdown_items(client):
    # Mock the database controller to return test data
    with patch('mpi_backend.database.controllers.InvoiceItems.InvoiceItemController') as mock_controller:
        mock_instance = Mock()
        mock_instance.get_price_comparison_items.return_value = {
            "items": [
                {
                    "mpi_item": "CMPSPM02",
                    "original_item": "COMP 1/4\"",
                    "mpi_description": "1/4\" QUICK COUPLER PLUG FOR AIR COMP",
                }
            ]
        }
        mock_controller.return_value = mock_instance
        
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


def test_get_selected_items_prices(client):
    # Mock the database controller to return test data
    with patch('mpi_backend.database.controllers.InvoiceItems.InvoiceItemController') as mock_controller:
        mock_instance = Mock()
        mock_instance.get_selected_items_prices.return_value = {
            "items": [
                {
                    "mpi_item": "CMPSPM02",
                    "original_item": "COMP 1/4\"",
                    "mpi_description": "1/4\" QUICK COUPLER PLUG FOR AIR COMP",
                    "current_price": 10.50,
                    "previous_price": 9.50,
                    "price_difference": 1.00,
                    "price_difference_percentage": 10.53
                }
            ]
        }
        mock_controller.return_value = mock_instance
        
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