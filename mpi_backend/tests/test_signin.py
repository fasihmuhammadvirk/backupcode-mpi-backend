def test_signin_missing_body(client):
    res = client.post("/signin")
    assert res.status_code in (400, 422)
