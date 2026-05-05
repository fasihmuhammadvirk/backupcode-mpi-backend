import logging
from uuid import UUID
from mpi_backend.database.dao.project_estimation import ProjectEstimationDAO
from mpi_backend.database.models.ProjectEstimation import ProjectEstimation

logger = logging.getLogger(__name__)

class ProjectEstimationController:
    def __init__(self, db):
        self.db = db
        self.dao = ProjectEstimationDAO(db)

    def create_estimation(self, data: dict, user_id: UUID) -> ProjectEstimation:
        """
        Create a new project estimation.
        """
        try:
            return self.dao.create_project_estimation(data, user_id)
        except Exception as e:
            logger.error(f"Error in controller creating estimation: {str(e)}")
            raise

    def get_estimations_by_user(self, user_id: UUID) -> list[ProjectEstimation]:
        """
        Get all estimations for a specific user.
        """
        try:
            return self.dao.get_all_project_estimations_by_user(user_id)
        except Exception as e:
            logger.error(f"Error in controller fetching estimations for user {user_id}: {str(e)}")
            raise

    def verify_project_ownership(self, estimation_id: int, user_id: UUID) -> None:
        """
        Verify that the user owns the project estimation.
        Raises ValueError if not found, PermissionError if not owned.
        """
        self.get_estimation_by_id(estimation_id, user_id)

    def get_estimation_by_id(self, estimation_id: int, user_id: UUID) -> ProjectEstimation:
        """
        Get a specific estimation and verify ownership.
        """
        try:
            estimation = self.dao.get_project_estimation_by_id_or_trow(estimation_id)
            
            if estimation.user_id != user_id:
                logger.warning(f"User {user_id} attempted to access estimation {estimation_id} owned by {estimation.user_id}")
                raise PermissionError("Access denied to this project estimation.")
                
            return estimation
        except (ValueError, PermissionError):
            raise
        except Exception as e:
            logger.error(f"Error in controller fetching estimation {estimation_id}: {str(e)}")
            raise

    def update_estimation(self, estimation_id: int, user_id: UUID, data: dict) -> ProjectEstimation:
        """
        Update an estimation after verifying ownership.
        """
        try:
            estimation = self.dao.get_project_estimation_by_id_or_trow(estimation_id)
            
            if estimation.user_id != user_id:
                logger.warning(f"User {user_id} attempted to update estimation {estimation_id} owned by {estimation.user_id}")
                raise PermissionError("Access denied to update this project estimation.")

            updated = self.dao.update_project_estimation(estimation_id, data)
            if not updated:
                raise ValueError(f"Failed to update project estimation with id {estimation_id}.")
            return updated
        except (ValueError, PermissionError):
            raise
        except Exception as e:
            logger.error(f"Error in controller updating estimation {estimation_id}: {str(e)}")
            raise

    def delete_estimation(self, estimation_id: int, user_id: UUID) -> bool:
        """
        Delete an estimation after verifying ownership.
        """
        try:
            estimation = self.dao.get_project_estimation_by_id_or_trow(estimation_id)
            
            if estimation.user_id != user_id:
                logger.warning(f"User {user_id} attempted to delete estimation {estimation_id} owned by {estimation.user_id}")
                raise PermissionError("Access denied to delete this project estimation.")

            return self.dao.delete_project_estimation(estimation_id)
        except (ValueError, PermissionError):
            raise
        except Exception as e:
            logger.error(f"Error in controller deleting estimation {estimation_id}: {str(e)}")
            raise
