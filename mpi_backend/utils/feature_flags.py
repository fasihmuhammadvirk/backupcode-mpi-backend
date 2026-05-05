"""
Feature flag system with user-based allowlists.

Security:
- Allowlists are server-side only (never exposed to client)
- Username extracted from authenticated JWT token
- User must be authenticated to check flags
"""
import logging
from typing import Dict, List, Set
from mpi_backend.database.models.User import User

logger = logging.getLogger(__name__)


# ============================================================================
# FEATURE FLAG CONFIGURATION
# ============================================================================
# Format: "flag_name": ["username1", "username2", ...]
# Empty list [] means disabled for all users
# To enable for all users, check in is_enabled() function instead
# ============================================================================

FEATURE_FLAG_ALLOWLISTS: Dict[str, List[str]] = {
    # ================================
    # DAO Feature Flags
    # ================================
    # Here we determine which users can use the DAO results
    # we want to slowly switch to using the DAO but we want to run the legacy version
    # in parallel.
    #
    # Currently there are two ways of getting the price difference:
    # 1. A separate prife diff endpoint (`filter/price-difference?page=1&size=50`)
    # 2. As part of the filter endpoint (`filter?page=1&size=50`)
    # For No. 1, the frontend combines the data
    # For No. 2, the backend sends the data combined
    "use_dao_with_fallback": ["testuser"],  # DAO with ORM fallback on failure
    "use_dao_only": ["testuser"],  # DAO only mode, no fallback (raises errors)

}


def get_user_feature_flags(user: User) -> Dict[str, bool]:
    """
    Get all feature flags for a specific user.

    Args:
        user: Authenticated User object (from JWT validation)

    Returns:
        Dict mapping feature flag names to boolean enabled state

    Example:
        {
            "use_dao_with_fallback": True,
            "use_dao_only": False,
        }
    """
    if not user or not user.username:
        logger.warning("get_user_feature_flags called with invalid user")
        return {flag: False for flag in FEATURE_FLAG_ALLOWLISTS.keys()}

    username = user.username.lower()  # Case-insensitive comparison

    flags = {}
    for flag_name, allowlist in FEATURE_FLAG_ALLOWLISTS.items():
        # Check if user is in allowlist (case-insensitive)
        allowlist_lower = [u.lower() for u in allowlist]
        flags[flag_name] = username in allowlist_lower

    logger.info(f"Feature flags for user '{user.username}': {flags}")
    return flags


def is_enabled(flag_name: str, user: User) -> bool:
    """
    Check if a specific feature flag is enabled for a user.

    Args:
        flag_name: Name of the feature flag
        user: Authenticated User object

    Returns:
        True if flag is enabled for user, False otherwise
    """
    if flag_name not in FEATURE_FLAG_ALLOWLISTS:
        logger.warning(f"Unknown feature flag: {flag_name}")
        return False

    if not user or not user.username:
        logger.warning(f"is_enabled called for flag '{flag_name}' with invalid user")
        return False

    username = user.username.lower()
    allowlist = FEATURE_FLAG_ALLOWLISTS[flag_name]
    allowlist_lower = [u.lower() for u in allowlist]

    enabled = username in allowlist_lower
    logger.debug(f"Feature flag '{flag_name}' for user '{user.username}': {enabled}")
    return enabled


def add_user_to_flag(flag_name: str, username: str) -> None:
    """
    Programmatically add a user to a feature flag allowlist.

    WARNING: This modifies the in-memory allowlist. Changes are lost on restart.
    For persistent changes, update FEATURE_FLAG_ALLOWLISTS directly.

    Args:
        flag_name: Name of the feature flag
        username: Username to add to allowlist
    """
    if flag_name not in FEATURE_FLAG_ALLOWLISTS:
        logger.error(f"Cannot add user to unknown flag: {flag_name}")
        return

    if username not in FEATURE_FLAG_ALLOWLISTS[flag_name]:
        FEATURE_FLAG_ALLOWLISTS[flag_name].append(username)
        logger.info(f"Added user '{username}' to feature flag '{flag_name}'")
    else:
        logger.debug(f"User '{username}' already in allowlist for '{flag_name}'")


def remove_user_from_flag(flag_name: str, username: str) -> None:
    """
    Programmatically remove a user from a feature flag allowlist.

    WARNING: This modifies the in-memory allowlist. Changes are lost on restart.

    Args:
        flag_name: Name of the feature flag
        username: Username to remove from allowlist
    """
    if flag_name not in FEATURE_FLAG_ALLOWLISTS:
        logger.error(f"Cannot remove user from unknown flag: {flag_name}")
        return

    if username in FEATURE_FLAG_ALLOWLISTS[flag_name]:
        FEATURE_FLAG_ALLOWLISTS[flag_name].remove(username)
        logger.info(f"Removed user '{username}' from feature flag '{flag_name}'")
    else:
        logger.debug(f"User '{username}' not in allowlist for '{flag_name}'")
