#!/usr/bin/env python3
"""
Comprehensive test suite for authentication and JWT handling.
Tests token creation, validation, expiration, and security features.
"""

import os
import pytest

# Set up environment variables BEFORE importing the module
os.environ["JWT_SECRET"] = "test_secret_key_for_testing_only"
os.environ["JWT_ALGORITHM"] = "HS256"

import time
import jwt
from unittest.mock import patch

from mpi_backend.utils.auth.auth_handler import (
    signJWT,
    decodeJWT,
    token_response,
    JWT_SECRET,
    JWT_ALGORITHM,
    TOKEN_EXPIRE_SESSION,
    TOKEN_EXPIRE_REMEMBER_ME
)
from mpi_backend.utils.auth.roles import UserRole
from mpi_backend.utils.auth.models import TokenResponse


class TestAuthHandler:
    """Test suite for authentication and JWT handling."""

    def test_token_response_format(self):
        """Test that token_response returns correct format."""
        test_token = "test.jwt.token"
        response = token_response(test_token)

        assert isinstance(response, TokenResponse)
        assert response.access_token == test_token

    def test_sign_jwt_creates_valid_token(self):
        """Test that signJWT creates a valid JWT token."""
        user_id = "test_user_123"
        result = signJWT(user_id, UserRole.STANDARD, 1)

        # Check response format
        assert isinstance(result, TokenResponse)
        assert isinstance(result.access_token, str)

        # Verify it's a valid JWT structure (3 parts separated by dots)
        token_parts = result.access_token.split('.')
        assert len(token_parts) == 3

    def test_sign_jwt_payload_content(self):
        """Test that signJWT creates token with correct payload."""
        user_id = "test_user_456"
        result = signJWT(user_id, UserRole.STANDARD, 1)
        token = result.access_token

        # Decode without verification to check payload
        payload = jwt.decode(token, options={"verify_signature": False})

        # Check new JWT format
        assert "sub" in payload
        assert payload["sub"] == user_id
        assert "role" in payload
        assert payload["role"] == UserRole.STANDARD.value
        assert "company_id" in payload
        assert payload["company_id"] == 1
        assert "exp" in payload
        assert isinstance(payload["exp"], (int, float))

        # Check expiration is in the future
        current_time = time.time()
        assert payload["exp"] > current_time

    def test_sign_jwt_expiration_time(self):
        """Test that JWT expiration is set correctly (8 hours for session-only tokens)."""
        user_id = "test_user_789"
        before_time = time.time()
        result = signJWT(user_id, UserRole.STANDARD, 1)
        after_time = time.time()

        token = result.access_token
        payload = jwt.decode(token, options={"verify_signature": False})

        exp = payload["exp"]
        iat = payload["iat"]

        # Should expire in approximately 8 hours (TOKEN_EXPIRE_SESSION seconds)
        expected_min = before_time + TOKEN_EXPIRE_SESSION - 5  # 5 second tolerance
        expected_max = after_time + TOKEN_EXPIRE_SESSION + 5

        assert expected_min <= exp <= expected_max
        assert exp - iat == TOKEN_EXPIRE_SESSION

    def test_decode_jwt_valid_token(self):
        """Test decoding a valid, non-expired JWT token."""
        user_id = "test_user_valid"
        token_response_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_response_data.access_token

        decoded = decodeJWT(token)

        assert decoded is not None
        assert decoded.sub == user_id
        assert decoded.role == UserRole.STANDARD.value
        assert decoded.company_id == 1
        assert decoded.exp is not None

    def test_decode_jwt_expired_token(self):
        """Test decoding an expired JWT token."""
        # Create a token that's already expired
        expired_payload = {
            "sub": "test_user_expired",
            "role": "standard",
            "company_id": 1,
            "iat": int(time.time()) - 7200,  # 2 hours ago
            "exp": int(time.time()) - 3600,  # Expired 1 hour ago
            "jti": "test-jti-123"
        }

        expired_token = jwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        decoded = decodeJWT(expired_token)

        assert decoded is None

    def test_decode_jwt_invalid_signature(self):
        """Test decoding a JWT with invalid signature."""
        # Create token with wrong secret
        invalid_payload = {
            "sub": "test_user_invalid",
            "role": "standard",
            "company_id": 1,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "test-jti-456"
        }

        invalid_token = jwt.encode(invalid_payload, "wrong_secret", algorithm=JWT_ALGORITHM)
        decoded = decodeJWT(invalid_token)

        assert decoded is None

    def test_decode_jwt_malformed_token(self):
        """Test decoding malformed JWT tokens."""
        malformed_tokens = [
            "not.a.jwt",
            "invalid_token",
            "",
            "a.b",  # Missing part
            "a.b.c.d",  # Too many parts
        ]

        for token in malformed_tokens:
            decoded = decodeJWT(token)
            assert decoded is None

    def test_decode_jwt_none_token(self):
        """Test decoding None token."""
        decoded = decodeJWT(None)
        assert decoded is None

    def test_jwt_algorithm_consistency(self):
        """Test that encoding and decoding use the same algorithm."""
        user_id = "test_algorithm_consistency"
        token_response_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_response_data.access_token
        
        # Manually decode to verify algorithm
        header = jwt.get_unverified_header(token)
        assert header["alg"] == JWT_ALGORITHM

    def test_jwt_secret_usage(self):
        """Test that JWT uses the configured secret."""
        user_id = "test_secret_usage"
        token_response_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_response_data.access_token
        
        # Should be able to decode with the same secret
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            assert payload["sub"] == user_id
        except jwt.InvalidTokenError:
            pytest.fail("Token should be decodable with the correct secret")

    def test_multiple_users_different_tokens(self):
        """Test that different users get different tokens."""
        user1 = "user_one"
        user2 = "user_two"
        
        token1 = signJWT(user1, UserRole.STANDARD, 1).access_token
        token2 = signJWT(user2, UserRole.STANDARD, 1).access_token
        
        assert token1 != token2
        
        # Verify each token decodes to correct user
        decoded1 = decodeJWT(token1)
        decoded2 = decodeJWT(token2)
        
        assert decoded1.sub == user1
        assert decoded2.sub == user2

    def test_same_user_different_tokens(self):
        """Test that same user gets different tokens at different times."""
        user_id = "same_user"
        
        token1 = signJWT(user_id, UserRole.STANDARD, 1).access_token
        time.sleep(0.01)  # Small delay to ensure different timestamps
        token2 = signJWT(user_id, UserRole.STANDARD, 1).access_token
        
        # Tokens should be different due to different expiration timestamps
        assert token1 != token2
        
        # But both should decode to same user
        decoded1 = decodeJWT(token1)
        decoded2 = decodeJWT(token2)
        
        assert decoded1.sub == user_id
        assert decoded2.sub == user_id

    def test_edge_case_user_ids(self):
        """Test JWT creation with edge case user IDs."""
        edge_case_ids = [
            "",  # Empty string
            "user with spaces",
            "user@email.com",
            "user-with-dashes",
            "user_with_underscores",
            "UserWithMixedCase",
            "123456789",  # Numeric string
            "user!@#$%^&*()",  # Special characters
        ]
        
        for user_id in edge_case_ids:
            token_response_data = signJWT(user_id, UserRole.STANDARD, 1)
            token = token_response_data.access_token
            
            decoded = decodeJWT(token)
            assert decoded is not None
            assert decoded.sub == user_id

    def test_token_expiration_boundary(self):
        """Test token behavior at expiration boundary."""
        # Create a token that expires very soon
        short_expiry_payload = {
            "sub": "boundary_test",
            "role": "standard",
            "company_id": 1,
            "iat": int(time.time()),
            "exp": int(time.time()) + 1,  # Expires in 1 second
            "jti": "test-jti-boundary"
        }

        token = jwt.encode(short_expiry_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # Should be valid initially
        decoded = decodeJWT(token)
        assert decoded is not None
        assert decoded.sub == "boundary_test"

        # Wait for expiration
        time.sleep(1.1)

        # Should now be invalid
        decoded_after_expiry = decodeJWT(token)
        assert decoded_after_expiry is None

    def test_concurrent_token_operations(self):
        """Test that JWT operations are thread-safe."""
        import threading
        import queue
        
        results = queue.Queue()
        errors = queue.Queue()
        
        def worker(user_id):
            try:
                # Create token
                token_data = signJWT(f"user_{user_id}", UserRole.STANDARD, 1)
                token = token_data.access_token
                
                # Decode token
                decoded = decodeJWT(token)

                results.put((user_id, decoded.sub))
            except Exception as e:
                errors.put((user_id, e))
        
        # Create multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # Check results
        assert errors.empty(), f"Errors occurred: {list(errors.queue)}"
        assert results.qsize() == 10
        
        # Verify all results are correct
        while not results.empty():
            user_id, decoded_user_id = results.get()
            assert decoded_user_id == f"user_{user_id}"

    @patch('mpi_backend.utils.auth.auth_handler.JWT_SECRET', 'test_secret')
    def test_configuration_override(self):
        """Test behavior with overridden configuration."""
        user_id = "config_test"
        
        # Create token with mocked secret
        token_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_data.access_token
        
        # Should be decodable with the mocked secret
        decoded = decodeJWT(token)
        assert decoded is not None
        assert decoded.sub == user_id

    def test_jwt_standard_compliance(self):
        """Test that generated JWTs comply with JWT standards."""
        user_id = "compliance_test"
        token_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_data.access_token
        
        # Should have standard JWT structure
        parts = token.split('.')
        assert len(parts) == 3
        
        # Header should be valid JSON
        header = jwt.get_unverified_header(token)
        assert "alg" in header
        assert "typ" in header
        assert header["typ"] == "JWT"
        
        # Payload should be valid
        payload = jwt.decode(token, options={"verify_signature": False})
        assert isinstance(payload, dict)

    def test_security_features(self):
        """Test security-related features of JWT implementation."""
        user_id = "security_test"
        token_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_data.access_token
        
        # Token should not contain sensitive information in header
        header = jwt.get_unverified_header(token)
        assert "secret" not in str(header).lower()
        assert "password" not in str(header).lower()
        
        # Payload should only contain expected fields
        payload = jwt.decode(token, options={"verify_signature": False})
        expected_fields = {"sub", "role", "company_id", "iat", "exp", "jti"}
        actual_fields = set(payload.keys())
        assert actual_fields == expected_fields

        # Should not have unexpected sensitive fields
        sensitive_fields = {"password", "secret", "key", "private"}
        assert not any(field in str(payload).lower() for field in sensitive_fields)

    def test_error_handling_robustness(self):
        """Test error handling in edge cases."""
        # Test with various invalid inputs
        invalid_inputs = [
            123,  # Number instead of string
            [],   # List
            {},   # Dict
            True, # Boolean
        ]
        
        for invalid_input in invalid_inputs:
            try:
                # This might raise TypeError or return None
                result = decodeJWT(invalid_input)
                # If it doesn't raise, should return None
                assert result is None
            except TypeError:
                # This is also acceptable behavior
                pass

    def test_performance_characteristics(self):
        """Test performance of JWT operations."""
        import time
        
        user_id = "performance_test"
        
        # Measure token creation time
        start_time = time.time()
        for _ in range(100):
            signJWT(user_id, UserRole.STANDARD, 1)
        creation_time = time.time() - start_time
        
        # Should be reasonably fast (less than 1 second for 100 tokens)
        assert creation_time < 1.0
        
        # Measure token decoding time
        token_data = signJWT(user_id, UserRole.STANDARD, 1)
        token = token_data.access_token
        
        start_time = time.time()
        for _ in range(100):
            decodeJWT(token)
        decoding_time = time.time() - start_time
        
        # Should be reasonably fast
        assert decoding_time < 1.0

    def test_remember_me_false_creates_session_token(self):
        """Test that remember_me=False creates tokens with 8-hour expiration."""
        user_id = "test_user_session"
        before_time = time.time()
        result = signJWT(user_id, UserRole.STANDARD, 1, remember_me=False)
        after_time = time.time()

        token = result.access_token
        payload = jwt.decode(token, options={"verify_signature": False})

        exp = payload["exp"]
        iat = payload["iat"]

        # Should expire in approximately 8 hours (TOKEN_EXPIRE_SESSION seconds)
        expected_min = before_time + TOKEN_EXPIRE_SESSION - 5  # 5 second tolerance
        expected_max = after_time + TOKEN_EXPIRE_SESSION + 5

        assert expected_min <= exp <= expected_max
        assert exp - iat == TOKEN_EXPIRE_SESSION

    def test_remember_me_true_creates_long_lived_token(self):
        """Test that remember_me=True creates tokens with 7-day expiration."""
        user_id = "test_user_remember"
        before_time = time.time()
        result = signJWT(user_id, UserRole.STANDARD, 1, remember_me=True)
        after_time = time.time()

        token = result.access_token
        payload = jwt.decode(token, options={"verify_signature": False})

        exp = payload["exp"]
        iat = payload["iat"]

        # Should expire in approximately 7 days (TOKEN_EXPIRE_REMEMBER_ME seconds)
        expected_min = before_time + TOKEN_EXPIRE_REMEMBER_ME - 5  # 5 second tolerance
        expected_max = after_time + TOKEN_EXPIRE_REMEMBER_ME + 5

        assert expected_min <= exp <= expected_max
        assert exp - iat == TOKEN_EXPIRE_REMEMBER_ME

    def test_remember_me_default_is_false(self):
        """Test that remember_me defaults to False (8-hour session token)."""
        user_id = "test_user_default"
        # Call signJWT without remember_me parameter
        result = signJWT(user_id, UserRole.STANDARD, 1)

        token = result.access_token
        payload = jwt.decode(token, options={"verify_signature": False})

        exp = payload["exp"]
        iat = payload["iat"]

        # Should use session expiration (8 hours), not remember_me expiration (7 days)
        assert exp - iat == TOKEN_EXPIRE_SESSION
        assert exp - iat != TOKEN_EXPIRE_REMEMBER_ME

    def test_role_cannot_be_changed_in_token(self):
        """Test that changing role in token breaks signature (privilege escalation attack)."""
        from uuid import uuid4

        user_id = str(uuid4())
        token = signJWT(user_id, UserRole.STANDARD, 1).access_token

        # Try to decode and re-encode with different role
        payload = jwt.decode(token, options={"verify_signature": False})
        payload["role"] = "admin"  # Try to escalate privileges

        # Re-encode with wrong secret (attacker doesn't have real secret)
        fake_token = jwt.encode(payload, "fake_secret", algorithm=JWT_ALGORITHM)

        # Should be rejected
        decoded = decodeJWT(fake_token)
        assert decoded is None or decoded == {}
