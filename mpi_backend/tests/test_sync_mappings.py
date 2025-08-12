from unittest.mock import patch
import mpi_backend.api.routes.sync_mappings as sm


def test_sync_mapping_already_running(client):
    with patch.object(
        sm.GoogleSheetSyncController,
        "get_sync_status",
        return_value={
            "is_running": True,
            "current_operation": "sync",
            "current_sub_operation": None,
            "last_sync_time": None,
            "last_update_no_match_uidi_time": None,
            "last_update_all_time": None,
        },
    ):
        res = client.post("/sync/mapping")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is False


def test_sync_mapping_start_success(client):
    with patch.object(
        sm.GoogleSheetSyncController,
        "get_sync_status",
        side_effect=[
            {"is_running": False},
            {"is_running": False},
        ],
    ), patch.object(
        sm.GoogleSheetSyncController,
        "_execute_sync_task_worker",
        return_value=None,
    ):
        res = client.post("/sync/mapping")
        assert res.status_code == 200
        assert res.json()["success"] is True


def test_sync_status_ok(client):
    with patch(
        "mpi_backend.api.routes.sync_mappings.GoogleSheetSyncController"
        ".get_sync_status",
        return_value={
            "is_running": False,
            "last_sync_time": None,
            "last_update_no_match_uidi_time": None,
            "last_update_all_time": None,
        },
    ):
        res = client.get("/sync/status")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] in ("idle", "running")


def test_update_no_match_uidi_already_running(client):
    with patch.object(
        sm.GoogleSheetSyncController,
        "get_sync_status",
        return_value={
            "is_running": True,
            "current_operation": "update_no_match_uidi",
            "current_sub_operation": "syncing_temporary_mappings",
        },
    ):
        res = client.post("/sync/update-no-match-uidi-mappings")
        assert res.status_code == 200
        assert res.json()["status"] == "error"


def test_update_no_match_uidi_start_ok(client):
    with patch.object(
        sm.GoogleSheetSyncController,
        "get_sync_status",
        side_effect=[
            {"is_running": False},
            {"is_running": False},
        ],
    ), patch.object(
        sm.GoogleSheetSyncController,
        "_execute_sync_task_worker",
        return_value=None,
    ):
        res = client.post("/sync/update-no-match-uidi-mappings")
        assert res.status_code == 200
        assert res.json()["status"] == "success"


def test_update_all_mappings_already_running(client):
    with patch.object(
        sm.GoogleSheetSyncController,
        "get_sync_status",
        return_value={
            "is_running": True,
            "current_operation": "update_all",
            "current_sub_operation": "syncing_google_sheets",
        },
    ):
        res = client.post("/sync/update-all-mappings")
        assert res.status_code == 200
        assert res.json()["status"] == "error"


def test_update_all_mappings_start_ok(client):
    with patch.object(
        sm.GoogleSheetSyncController,
        "get_sync_status",
        side_effect=[
            {"is_running": False},
            {"is_running": False},
        ],
    ), patch.object(
        sm.GoogleSheetSyncController,
        "_execute_sync_task_worker",
        return_value=None,
    ):
        res = client.post("/sync/update-all-mappings")
        assert res.status_code == 200
        assert res.json()["status"] == "success"

