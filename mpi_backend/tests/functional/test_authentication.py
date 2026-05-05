#!/usr/bin/env python3
"""
Tests for authentication dependencies and protected endpoints.
"""

import pytest
from unittest.mock import Mock, MagicMock
from uuid import uuid4
from fastapi import HTTPException

from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.auth.auth_handler import signJWT
from mpi_backend.utils.auth.roles import UserRole
from mpi_backend.database.models.User import User


def test_protected_endpoint_uses_bypass_in_tests(client, override_get_current_user, mock_invoice_controller):
    # A protected endpoint like /invoice should succeed when using override_get_current_user
    with override_get_current_user():
        res = client.get("/invoice?page=1&size=10")
        assert res.status_code == 200


class TestGetCurrentUser:
    """Test suite for get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_get_current_user_extracts_user_id_from_jwt(self):
        """Test that get_current_user correctly extracts user_id from JWT payload."""
        # Create a valid JWT token
        user_id = str(uuid4())
        token_response = signJWT(user_id, UserRole.ADMIN, None)
        token = token_response.access_token

        # Mock database and user
        mock_db = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.username = "testadmin"
        mock_user.role = "admin"
        mock_user.is_active = True

        # Setup query chain: db.query(User).filter(...).first()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_user
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        # Mock request
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        # Call get_current_user
        result = await get_current_user(mock_request, token, mock_db)

        # Verify user was returned
        assert result == mock_user
        assert result.id == user_id
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_get_current_user_with_standard_user(self):
        """Test get_current_user with standard user role."""
        user_id = str(uuid4())
        company_id = 5
        token_response = signJWT(user_id, UserRole.STANDARD, company_id)
        token = token_response.access_token

        # Mock database and user
        mock_db = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.username = "standarduser"
        mock_user.role = "standard"
        mock_user.company_id = company_id
        mock_user.is_active = True

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_user
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        result = await get_current_user(mock_request, token, mock_db)

        assert result == mock_user
        assert result.role == "standard"
        assert result.company_id == company_id

    @pytest.mark.asyncio
    async def test_get_current_user_rejects_expired_token(self):
        """Test that get_current_user rejects expired tokens."""
        # Use an intentionally malformed token to simulate expiry
        invalid_token = "expired.jwt.token"

        mock_db = MagicMock()
        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, invalid_token, mock_db)

        assert exc_info.value.status_code == 401
        assert "invalid or expired token" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_current_user_rejects_invalid_token(self):
        """Test that get_current_user rejects invalid/malformed tokens."""
        invalid_tokens = ["invalid.token", "not-a-jwt", ""]

        mock_db = MagicMock()
        mock_request = MagicMock()

        for token in invalid_tokens:
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(mock_request, token, mock_db)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_blocks_inactive_user(self):
        """Test that get_current_user blocks inactive/deactivated users."""
        user_id = str(uuid4())
        token_response = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_response.access_token

        # Mock database with inactive user
        mock_db = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.username = "inactiveuser"
        mock_user.is_active = False  # User is deactivated

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_user
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, token, mock_db)

        assert exc_info.value.status_code == 403
        assert "deactivated" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_current_user_rejects_nonexistent_user(self):
        """Test that get_current_user rejects tokens for users that don't exist in DB."""
        user_id = str(uuid4())
        token_response = signJWT(user_id, UserRole.ADMIN, None)
        token = token_response.access_token

        # Mock database with no user found
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None  # User not found
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, token, mock_db)

        assert exc_info.value.status_code == 401
        assert "user not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_current_user_attaches_request_info(self):
        """Test that get_current_user attaches user and client IP to request state."""
        user_id = str(uuid4())
        token_response = signJWT(user_id, UserRole.BOOKKEEPING, 3)
        token = token_response.access_token

        mock_db = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.username = "bookkeeper"
        mock_user.role = "bookkeeping"
        mock_user.is_active = True

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_user
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.100"
        mock_request.state = MagicMock()

        result = await get_current_user(mock_request, token, mock_db)

        # Verify request state was populated
        assert mock_request.state.user == mock_user
        assert mock_request.state.client_ip == "192.168.1.100"
