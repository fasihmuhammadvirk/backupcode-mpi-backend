from unittest.mock import patch


def test_signin_missing_body(client):
    # Missing body entirely
    res = client.post("/signin")
    assert res.status_code in (400, 422)


def test_signin_missing_fields(client):
    # Missing username
    res = client.post("/signin", json={"password": "x"})
    assert res.status_code == 400
    # Missing password
    res = client.post("/signin", json={"username": "u"})
    assert res.status_code == 400


def test_signin_invalid_credentials(client, monkeypatch):
    # Stub UserController.validate_credentials to False
    with patch(
        "mpi_backend.api.routes.signin.UserController.validate_credentials",
        return_value=False,
    ):
        res = client.post(
            "/signin", json={"username": "user", "password": "wrong"}
        )
        assert res.status_code == 403
        assert res.json()["detail"].lower().startswith("wrong login")


def test_signin_success_returns_token(client):
    # Stub both validate_credentials and signJWT
    with patch(
        "mpi_backend.api.routes.signin.UserController.validate_credentials",
        return_value=True,
    ), patch(
        "mpi_backend.api.routes.signin.signJWT",
        return_value={"access_token": "test.jwt.token"},
    ):
        res = client.post(
            "/signin", json={"username": "user", "password": "pass"}
        )
        assert res.status_code == 200
        body = res.json()
        assert "access_token" in body
