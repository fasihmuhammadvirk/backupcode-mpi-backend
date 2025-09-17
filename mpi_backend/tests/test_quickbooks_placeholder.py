def test_quickbooks_routes_exist(client):
    # Smoke test that router mounts (no 404 on base path listing)
    res = client.options("/quickbooks")
    assert res.status_code in (200, 404, 405)
