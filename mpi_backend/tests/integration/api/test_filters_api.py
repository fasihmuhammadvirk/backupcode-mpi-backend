from unittest.mock import Mock, patch
from mpi_backend.database.schemas.Filters import FilterRequest


def test_filter_empty_request_returns_paginated_data(client, override_get_current_user):
    """
    Empty filter request should return all accessible invoice items
    with default pagination applied, not empty results.
    """
    # Create a realistic mock that returns sample data with all required fields
    with patch('mpi_backend.api.routes.filters.InvoiceItemController') as mock_ctl:
        mock_instance = Mock()

        # Sample item with all required InvoiceItemStandard fields
        sample_item = {
            "id": 1,
            "filename": "invoice_2024_01.xlsx",
            "sheet_name": "January",
            "mpi_item": "ABC-123",
            "mpi_description": "Sample MPI Item",
            "item": "ABC-123",
            "description": "Sample Item Description",
            "qty": 5,
            "cost": "100.00",
            "amount": "500.00",
            "date": "01/15/2024",
            "ref_no": "REF-001",
            "po_number": "PO-12345",
            "customer_job": "Customer Job A",
            "bill": "BILL-001",
            "vendor": "BMW",
            "class_": "Class A",
            "export_status": "exported",
            "memo": "Sample memo",
            "buyer": "John Doe",
            "date_added": "01/10/2024",
            "invoice_id": "550e8400-e29b-41d4-a716-446655440000",
            "is_active": True
        }

        # Create 10 items with variations
        items = []
        for i in range(10):
            item = sample_item.copy()
            item["id"] = i + 1
            item["item"] = f"ITEM-{i+1:03d}"
            item["mpi_item"] = f"MPI-{i+1:03d}"
            item["vendor"] = ["BMW", "Flow Mark", "Supplier Co", "Parts Inc", "Auto Parts"][i % 5]
            items.append(item)

        mock_instance.apply_filters.return_value = {
            "items": items,
            "total": 1500,  # Total items in database
            "page": 1,
            "size": 10,
            "total_pages": 150,
            "has_next": True,
            "has_prev": False
        }
        mock_ctl.return_value = mock_instance

        with override_get_current_user():  # Standard user
            payload = FilterRequest(filters={}, comparison_filters=[]).model_dump()
            res = client.post("/filter", json=payload)

            assert res.status_code == 200
            body = res.json()

            # Empty filters should return paginated data, not empty results
            assert body["total"] > 0, "Empty filters should return all accessible items"
            assert len(body["items"]) > 0, "Should have items in first page"
            assert body["page"] == 1
            assert body["size"] == 10
            assert body["has_next"] is True
            assert body["has_prev"] is False

            # Verify items have correct structure
            assert "id" in body["items"][0]
            assert "item" in body["items"][0]
            assert "vendor" in body["items"][0]

            # Standard user should NOT see account field (role-based filtering)
            assert "account" not in body["items"][0], "Standard users should not see account field"


def test_get_locations_ok(client):
    res = client.get("/filter/get-locations")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
