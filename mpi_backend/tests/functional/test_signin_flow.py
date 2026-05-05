from unittest.mock import patch


def test_signin_missing_body(client):
    # Missing body entirely
    res = client.post("/signin")
    assert res.status_code in (400, 422)


def test_signin_missing_fields(client):
    # Missing username
    res = client.post("/signin", json={"password": "x"})
    assert res.status_code == 422
    # Missing password
    res = client.post("/signin", json={"username": "u"})
    assert res.status_code == 422


def test_signin_invalid_credentials(client, monkeypatch):
    # Mock a user object that exists but has wrong password
    from unittest.mock import MagicMock
    mock_user = MagicMock()
    mock_user.id = "test-user-id"
    mock_user.is_active = True
    mock_user.role = "standard"
    mock_user.company_id = 1

    with patch(
        "mpi_backend.api.routes.signin.UserController.get_user_by_username",
        return_value=mock_user,
    ), patch(
        "mpi_backend.api.routes.signin.UserController.validate_credentials",
        return_value=False,
    ):
        res = client.post(
            "/signin", json={"username": "user", "password": "wrong"}
        )
        assert res.status_code == 403
        assert "invalid credentials" in res.json()["detail"].lower()


def test_signin_success_returns_token(client):
    # Mock a valid active user and successful authentication
    from unittest.mock import MagicMock
    mock_user = MagicMock()
    mock_user.id = "test-user-id"
    mock_user.is_active = True
    mock_user.role = "standard"
    mock_user.company_id = 1

    with patch(
        "mpi_backend.api.routes.signin.UserController.get_user_by_username",
        return_value=mock_user,
    ), patch(
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
