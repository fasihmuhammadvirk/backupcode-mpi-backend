def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json().get("res") is True


def test_health_method_not_allowed(client):
    # Ensure non-GET returns 405 or 404 depending on router config
    res = client.post("/health")
    assert res.status_code in (404, 405)
