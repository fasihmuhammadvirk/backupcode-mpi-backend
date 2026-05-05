"""
Feature flags API endpoints.

Security:
- Requires authentication (JWT token)
- Only returns flags for authenticated user
- Allowlists never exposed to client
"""
import logging
from fastapi import APIRouter, Depends
from typing import Dict
from mpi_backend.database.models.User import User
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.utils.feature_flags import get_user_feature_flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


@router.get("", response_model=Dict[str, bool])
async def get_feature_flags(
    current_user: User = Depends(get_current_user)
) -> Dict[str, bool]:
    """
    Get all feature flags for the authenticated user.

    Returns:
        Dictionary mapping feature flag names to boolean enabled state

    Example response:
        {
            "use_dao_with_fallback": true,
            "use_dao_only": false,
        }

    Security:
        - Requires valid JWT token
        - Only returns flags for authenticated user
        - Allowlists are server-side only
    """
    logger.info(f"Feature flags requested by user: {current_user.username}")
    return get_user_feature_flags(current_user)
