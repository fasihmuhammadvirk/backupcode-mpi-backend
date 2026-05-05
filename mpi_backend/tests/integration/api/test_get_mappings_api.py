from unittest.mock import patch
import mpi_backend.api.routes.mapping_updates as gm


def test_update_item_mappings_happy_path(client):
    # Provide minimal valid body per schema: supplier_id and mapping list
    request_body = {
        "supplier_id": "1",
        "mapping": [
            {
                "supplier_item_ids": "ABC-1",
                "mpi_item": "MPI001",
                "mpi_description": "Desc",
            }
        ],
    }
    with patch.object(
        gm.ItemsMappingController,
        "update_mapping",
        return_value={"status": "success"},
    ):
        res = client.post("/mapping", json=request_body)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert "details" in body


def test_update_item_mappings_skips_empty_supplier_item_ids(client):
    request_body = {
        "supplier_id": "1",
        "mapping": [
            {
                "supplier_item_ids": " ",
                "mpi_item": "MPI001",
                "mpi_description": "Desc",
            }
        ],
    }
    with patch.object(
        gm.ItemsMappingController,
        "update_mapping",
        return_value={"status": "success"},
    ):
        res = client.post("/mapping", json=request_body)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["details"]["results"][0]["status"] == "skipped_empty_item"


def test_update_item_mappings_internal_error(client):
    request_body = {
        "supplier_id": "1",
        "mapping": [
            {
                "supplier_item_ids": "ABC-1",
                "mpi_item": "MPI001",
                "mpi_description": "Desc",
            }
        ],
    }
    with patch.object(
        gm.ItemsMappingController,
        "update_mapping",
        side_effect=RuntimeError("db error"),
    ):
        res = client.post("/mapping", json=request_body)
        assert res.status_code == 500
        assert "Failed to update item mapping" in res.text


def test_search_item_mapping_ok(client):
    with patch.object(
        gm.ItemsMappingController,
        "search_clean_item_across_suppliers",
        return_value={"found": False, "matches": []},
    ):
        res = client.get("/mapping/search-item", params={"item": "ABC"})
        assert res.status_code == 200
        assert res.json()["found"] is False


def test_search_item_mapping_missing_item(client):
    res = client.get("/mapping/search-item")
    assert res.status_code in (400, 422)


def test_get_mpi_types_ok(client):
    with patch.object(
        gm.ItemsMappingController,
        "get_items_mappings_by_mpi_type",
        return_value={},
    ):
        res = client.get("/mapping/mpi_types")
        assert res.status_code == 200
        assert isinstance(res.json(), dict)


def test_get_mapping_by_supplier_id_ok(client):
    with patch.object(
        gm.ItemsMappingController,
        "get_items_mappings_by_supplier_id",
        side_effect=[[], []],
    ):
        res = client.get("/mapping/1")
        assert res.status_code == 200
        assert res.json() == []

