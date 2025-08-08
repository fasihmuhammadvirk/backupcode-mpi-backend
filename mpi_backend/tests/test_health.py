def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json().get("res") is True
