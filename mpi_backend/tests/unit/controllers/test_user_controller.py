import pytest
from unittest.mock import MagicMock, Mock
from uuid import uuid4

from mpi_backend.database.controllers.UserController import UserController
from mpi_backend.database.models.User import User
from mpi_backend.database.models.UserAuditLog import UserAuditLog


@pytest.fixture
def mock_db():
    """Provides a mocked SQLAlchemy database session for unit tests."""
    return MagicMock()


class TestPasswordOperations:
    """Test password hashing and verification (pure business logic)."""

    def test_hash_password_returns_bcrypt_hash(self, mock_db):
        """Test that hash_password creates a bcrypt hash."""
        controller = UserController(mock_db)

        password = "test123"
        hashed = controller.hash_password(password)

        # Hash should be different from plain password
        assert hashed != password

        # Bcrypt hashes are long (around 60 characters)
        assert len(hashed) > 50

        # Should start with bcrypt identifier
        assert hashed.startswith("$2b$")

    def test_hash_password_creates_unique_hashes(self, mock_db):
        """Test that same password produces different hashes (salt)."""
        controller = UserController(mock_db)

        password = "password123"
        hash1 = controller.hash_password(password)
        hash2 = controller.hash_password(password)

        # Same password should produce different hashes due to salt
        assert hash1 != hash2

        # But both should verify against the original password
        assert controller.verify_password(password, hash1) is True
        assert controller.verify_password(password, hash2) is True

    def test_verify_password_accepts_correct_password(self, mock_db):
        """Test that verify_password returns True for correct password."""
        controller = UserController(mock_db)

        password = "correct_password"
        hashed = controller.hash_password(password)

        assert controller.verify_password(password, hashed) is True

    def test_verify_password_rejects_incorrect_password(self, mock_db):
        """Test that verify_password returns False for incorrect password."""
        controller = UserController(mock_db)

        hashed = controller.hash_password("correct_password")

        assert controller.verify_password("wrong_password", hashed) is False
        assert controller.verify_password("", hashed) is False
        assert controller.verify_password("CORRECT_PASSWORD", hashed) is False

    def test_verify_password_handles_special_characters(self, mock_db):
        """Test password verification with special characters."""
        controller = UserController(mock_db)

        password = "P@ssw0rd!#$%^&*()"
        hashed = controller.hash_password(password)

        assert controller.verify_password(password, hashed) is True
        assert controller.verify_password("P@ssw0rd!#$%^&*)", hashed) is False  # Missing char


class TestValidateCredentials:
    """Test credential validation business rules."""

    def test_validate_credentials_accepts_active_user_with_correct_password(self, mock_db):
        """Test that active user with correct password is validated."""
        controller = UserController(mock_db)

        # Mock DB to return active user
        active_user = User(
            id=uuid4(),
            username="active_user",
            password=controller.hash_password("correct123"),
            is_active=True
        )
        mock_db.query.return_value.filter.return_value.first.return_value = active_user

        # Should return True for active user with correct password
        result = controller.validate_credentials("active_user", "correct123")
        assert result is True

        # Verify DB query was made
        mock_db.query.assert_called_with(User)

    def test_validate_credentials_rejects_inactive_user(self, mock_db):
        """Business rule: inactive users cannot authenticate even with correct password."""
        controller = UserController(mock_db)

        # Mock DB to return inactive user with correct password
        inactive_user = User(
            id=uuid4(),
            username="inactive_user",
            password=controller.hash_password("test123"),
            is_active=False  # INACTIVE!
        )
        mock_db.query.return_value.filter.return_value.first.return_value = inactive_user

        # Should reject inactive user even with correct password
        result = controller.validate_credentials("inactive_user", "test123")
        assert result is False

    def test_validate_credentials_rejects_nonexistent_user(self, mock_db):
        """Test that validation fails for non-existent user."""
        controller = UserController(mock_db)

        # Mock DB to return None (user not found)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.validate_credentials("nonexistent", "password")
        assert result is False

    def test_validate_credentials_rejects_active_user_with_wrong_password(self, mock_db):
        """Test that active user with wrong password is rejected."""
        controller = UserController(mock_db)

        active_user = User(
            id=uuid4(),
            username="testuser",
            password=controller.hash_password("correct_password"),
            is_active=True
        )
        mock_db.query.return_value.filter.return_value.first.return_value = active_user

        # Wrong password should fail
        result = controller.validate_credentials("testuser", "wrong_password")
        assert result is False

    def test_validate_credentials_handles_database_exception(self, mock_db):
        """Test error handling when database query fails."""
        controller = UserController(mock_db)

        # Mock DB to raise exception
        mock_db.query.side_effect = Exception("Database connection error")

        result = controller.validate_credentials("testuser", "password")

        # Should return None on exception (not False)
        assert result is None


class TestGetAllUsers:
    """Test user retrieval with exclusion logic."""

    def test_get_all_users_returns_all_users_when_no_exclusion(self, mock_db):
        """Test that get_all_users returns all users when no exclusion specified."""
        controller = UserController(mock_db)

        # Mock users
        users = [
            User(id=uuid4(), username="user1"),
            User(id=uuid4(), username="user2"),
            User(id=uuid4(), username="user3")
        ]
        mock_db.query.return_value.all.return_value = users

        result = controller.get_all_users()

        assert result == users
        assert len(result) == 3
        mock_db.query.assert_called_once_with(User)

    def test_get_all_users_excludes_specified_user(self, mock_db):
        """Business rule: can exclude specific user from results (e.g., current admin)."""
        controller = UserController(mock_db)
        exclude_id = uuid4()

        # Mock query chain for exclusion
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_filtered = Mock()
        mock_query.filter.return_value = mock_filtered
        mock_filtered.all.return_value = [
            User(id=uuid4(), username="user1"),
            User(id=uuid4(), username="user2")
        ]

        result = controller.get_all_users(exclude_user_id=exclude_id)

        # Verify filter was applied
        mock_db.query.assert_called_once_with(User)
        assert mock_query.filter.called
        assert len(result) == 2


class TestGetUserMethods:
    """Test user retrieval methods."""

    def test_get_user_by_username_returns_user(self, mock_db):
        """Test retrieving user by username."""
        controller = UserController(mock_db)

        expected_user = User(id=uuid4(), username="testuser")
        mock_db.query.return_value.filter.return_value.first.return_value = expected_user

        result = controller.get_user_by_username("testuser")

        assert result == expected_user
        mock_db.query.assert_called_once_with(User)

    def test_get_user_by_username_returns_none_when_not_found(self, mock_db):
        """Test that None is returned when user not found."""
        controller = UserController(mock_db)

        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.get_user_by_username("nonexistent")

        assert result is None

    def test_get_user_by_id_returns_user(self, mock_db):
        """Test retrieving user by UUID."""
        controller = UserController(mock_db)
        user_id = uuid4()

        expected_user = User(id=user_id, username="testuser")
        mock_db.query.return_value.filter.return_value.first.return_value = expected_user

        result = controller.get_user_by_id(user_id)

        assert result == expected_user
        mock_db.query.assert_called_once_with(User)

    def test_get_user_by_id_returns_none_when_not_found(self, mock_db):
        """Test that None is returned when user ID not found."""
        controller = UserController(mock_db)

        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.get_user_by_id(uuid4())

        assert result is None


class TestCreateUser:
    """Test user creation with audit logging."""

    def test_create_user_hashes_password(self, mock_db):
        """Test that passwords are hashed before storage."""
        controller = UserController(mock_db)

        plain_password = "test123"
        controller.create_user(
            username="newuser",
            password=plain_password,
            email="test@test.com"
        )

        # Verify db.add was called
        assert mock_db.add.called

        # Get the User object that was added
        user_add_call = [c for c in mock_db.add.call_args_list
                        if isinstance(c[0][0], User)]
        assert len(user_add_call) == 1

        added_user = user_add_call[0][0][0]

        # Password should be hashed, not plain text
        assert added_user.password != plain_password
        assert len(added_user.password) > 50  # Bcrypt hash length

    def test_create_user_sets_default_values(self, mock_db):
        """Test that default values are set correctly."""
        controller = UserController(mock_db)

        controller.create_user(
            username="newuser",
            password="test123"
        )

        # Get the User object that was added
        user_add_call = [c for c in mock_db.add.call_args_list
                        if isinstance(c[0][0], User)]
        added_user = user_add_call[0][0][0]

        # Check defaults
        assert added_user.is_active is True
        assert added_user.role == "standard"
        assert added_user.email is None
        assert added_user.company_id is None

    def test_create_user_creates_audit_log_when_created_by_provided(self, mock_db):
        """Test that audit log is created when created_by is provided."""
        controller = UserController(mock_db)
        admin_id = uuid4()

        controller.create_user(
            username="newuser",
            password="test123",
            email="test@test.com",
            role="bookkeeping",
            company_id=1,
            created_by=admin_id,
            ip_address="192.168.1.1"
        )

        # Verify audit log was added
        audit_calls = [c for c in mock_db.add.call_args_list
                      if isinstance(c[0][0], UserAuditLog)]
        assert len(audit_calls) == 1

        audit = audit_calls[0][0][0]
        assert audit.action == "created"
        assert audit.changed_by == admin_id
        assert audit.ip_address == "192.168.1.1"
        assert audit.new_values["username"] == "newuser"
        assert audit.new_values["role"] == "bookkeeping"
        assert audit.new_values["company_id"] == 1

    def test_create_user_skips_audit_log_when_created_by_not_provided(self, mock_db):
        """Test that audit log is not created when created_by is None."""
        controller = UserController(mock_db)

        controller.create_user(
            username="newuser",
            password="test123"
        )

        # Should only have one add call (User), not audit log
        user_adds = [c for c in mock_db.add.call_args_list
                    if isinstance(c[0][0], User)]
        audit_adds = [c for c in mock_db.add.call_args_list
                     if isinstance(c[0][0], UserAuditLog)]

        assert len(user_adds) == 1
        assert len(audit_adds) == 0

    def test_create_user_calls_flush_before_commit(self, mock_db):
        """Test that flush is called to get user ID before commit."""
        controller = UserController(mock_db)

        controller.create_user(username="newuser", password="test123")

        # Verify flush and commit were called
        assert mock_db.flush.called
        assert mock_db.commit.called

    def test_create_user_rolls_back_on_exception(self, mock_db):
        """Test that transaction is rolled back on error."""
        controller = UserController(mock_db)

        # Make flush raise exception
        mock_db.flush.side_effect = Exception("Database error")

        result = controller.create_user(username="newuser", password="test123")

        # Should return None on error
        assert result is None

        # Rollback should be called
        assert mock_db.rollback.called


class TestUpdateUser:
    """Test user update with change tracking and audit logging."""

    def test_update_user_tracks_email_change(self, mock_db):
        """Test that email changes are tracked in audit log."""
        controller = UserController(mock_db)
        user_id = uuid4()
        admin_id = uuid4()

        # Mock existing user
        existing_user = User(
            id=user_id,
            username="testuser",
            email="old@test.com",
            role="standard",
            is_active=True
        )
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        # Update email
        controller.update_user(
            user_id=user_id,
            changed_by=admin_id,
            email="new@test.com"
        )

        # Verify user was updated
        assert existing_user.email == "new@test.com"

        # Verify audit log was created
        audit_calls = [c for c in mock_db.add.call_args_list
                      if isinstance(c[0][0], UserAuditLog)]
        assert len(audit_calls) == 1

        audit = audit_calls[0][0][0]
        assert audit.action == "updated"
        assert audit.old_values["email"] == "old@test.com"
        assert audit.new_values["email"] == "new@test.com"

    def test_update_user_tracks_role_change(self, mock_db):
        """Test that role changes are tracked."""
        controller = UserController(mock_db)
        user_id = uuid4()

        existing_user = User(
            id=user_id,
            username="testuser",
            role="standard"
        )
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        controller.update_user(
            user_id=user_id,
            changed_by=uuid4(),
            role="bookkeeping"
        )

        assert existing_user.role == "bookkeeping"

        audit = [c for c in mock_db.add.call_args_list
                if isinstance(c[0][0], UserAuditLog)][0][0][0]
        assert audit.old_values["role"] == "standard"
        assert audit.new_values["role"] == "bookkeeping"

    def test_update_user_tracks_is_active_change(self, mock_db):
        """Test that is_active changes are tracked (user deactivation)."""
        controller = UserController(mock_db)
        user_id = uuid4()

        existing_user = User(
            id=user_id,
            username="testuser",
            is_active=True
        )
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        controller.update_user(
            user_id=user_id,
            changed_by=uuid4(),
            is_active=False
        )

        assert existing_user.is_active is False

        audit = [c for c in mock_db.add.call_args_list
                if isinstance(c[0][0], UserAuditLog)][0][0][0]
        assert audit.old_values["is_active"] is True
        assert audit.new_values["is_active"] is False

    def test_update_user_tracks_multiple_changes(self, mock_db):
        """Test that multiple simultaneous changes are all tracked."""
        controller = UserController(mock_db)
        user_id = uuid4()

        existing_user = User(
            id=user_id,
            username="testuser",
            email="old@test.com",
            role="standard",
            company_id=1,
            is_active=True
        )
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        controller.update_user(
            user_id=user_id,
            changed_by=uuid4(),
            email="new@test.com",
            role="bookkeeping",
            company_id=2,
            is_active=False
        )

        # All changes should be tracked
        audit = [c for c in mock_db.add.call_args_list
                if isinstance(c[0][0], UserAuditLog)][0][0][0]

        assert "email" in audit.old_values
        assert "role" in audit.old_values
        assert "company_id" in audit.old_values
        assert "is_active" in audit.old_values

    def test_update_user_skips_audit_when_no_changes(self, mock_db):
        """Business rule: don't create audit log if no actual changes."""
        controller = UserController(mock_db)
        user_id = uuid4()

        existing_user = User(
            id=user_id,
            username="testuser",
            email="test@test.com"
        )
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        # Update with same email (no change)
        controller.update_user(
            user_id=user_id,
            changed_by=uuid4(),
            email="test@test.com"
        )

        # Should NOT create audit log
        audit_calls = [c for c in mock_db.add.call_args_list
                      if isinstance(c[0][0], UserAuditLog)]
        assert len(audit_calls) == 0

        # But commit should still be called
        assert mock_db.commit.called

    def test_update_user_returns_none_when_user_not_found(self, mock_db):
        """Test that None is returned when user doesn't exist."""
        controller = UserController(mock_db)

        # Mock user not found
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = controller.update_user(
            user_id=uuid4(),
            changed_by=uuid4(),
            email="new@test.com"
        )

        assert result is None

        # Commit should not be called
        assert not mock_db.commit.called

    def test_update_user_rolls_back_on_exception(self, mock_db):
        """Test that transaction is rolled back on error."""
        controller = UserController(mock_db)

        existing_user = User(id=uuid4(), username="testuser")
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        # Make commit raise exception
        mock_db.commit.side_effect = Exception("Database error")

        result = controller.update_user(
            user_id=existing_user.id,
            changed_by=uuid4(),
            email="new@test.com"
        )

        assert result is None
        assert mock_db.rollback.called


class TestAuditLogConstruction:
    """Test audit log construction logic."""

    def test_audit_log_includes_ip_address(self, mock_db):
        """Test that IP address is captured in audit log."""
        controller = UserController(mock_db)

        existing_user = User(id=uuid4(), email="old@test.com")
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        controller.update_user(
            user_id=existing_user.id,
            changed_by=uuid4(),
            email="new@test.com",
            ip_address="192.168.1.100"
        )

        audit = [c for c in mock_db.add.call_args_list
                if isinstance(c[0][0], UserAuditLog)][0][0][0]

        assert audit.ip_address == "192.168.1.100"

    def test_audit_log_can_have_none_old_values(self, mock_db):
        """Test that audit log handles None old values correctly."""
        controller = UserController(mock_db)
        user_id = uuid4()

        # User with no email initially
        existing_user = User(id=user_id, email=None)
        mock_db.query.return_value.filter.return_value.first.return_value = existing_user

        # Set email for first time
        controller.update_user(
            user_id=user_id,
            changed_by=uuid4(),
            email="new@test.com"
        )

        audit = [c for c in mock_db.add.call_args_list
                if isinstance(c[0][0], UserAuditLog)][0][0][0]

        # Old value should be None
        assert audit.old_values["email"] is None
        assert audit.new_values["email"] == "new@test.com"
