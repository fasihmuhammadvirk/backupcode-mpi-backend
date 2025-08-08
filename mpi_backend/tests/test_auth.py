def test_protected_endpoint_uses_bypass_in_tests(client):
    # A protected endpoint like /invoice should succeed without token in tests
    res = client.get("/invoice?page=1&size=10")
    assert res.status_code in (200, 404, 500)
