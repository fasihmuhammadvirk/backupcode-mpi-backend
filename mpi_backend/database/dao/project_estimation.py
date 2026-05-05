import logging
from uuid import UUID  # For handling UUID in the API requests

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mpi_backend.database.models.ProjectEstimation import ProjectEstimation

logger = logging.getLogger(__name__)

ALLOWED_UPDATE_FIELDS = [
        'name', 'location', 'contract_value', 'budget_allocation',
        'labor_percentage', 'material_percentage', 'dollar_point',
        'budget_limit', 'labor_rem', 'material_rem', 'finishing',
        'point_value', 'target_value', 'fixed_costs'
]
class ProjectEstimationDAO:
    def __init__(self, db: Session):
        self.db = db
    
    def create_project_estimation(self, project_estimation_data: dict, user_id: UUID) -> ProjectEstimation:
        """
        Create a new project estimation record.

        Args:
            project_estimation_data (dict): Dictionary containing project estimation data.
            user_id (UUID): The ID of the user creating the project estimation.

        Returns:
            ProjectEstimation: The created ProjectEstimation instance.
        """
        try:
            project_estimation = ProjectEstimation(
                name=project_estimation_data.get('name'),
                location=project_estimation_data.get('location'),
                contract_value=project_estimation_data.get('contract_value'),
                budget_allocation=project_estimation_data.get('budget_allocation'),
                labor_percentage=project_estimation_data.get('labor_percentage'),
                material_percentage=project_estimation_data.get('material_percentage'),
                dollar_point=project_estimation_data.get('dollar_point'),
                budget_limit=project_estimation_data.get('budget_limit'),
                labor_rem=project_estimation_data.get('labor_rem'),
                material_rem=project_estimation_data.get('material_rem'),
                finishing=project_estimation_data.get('finishing'),
                point_value=project_estimation_data.get('point_value'),
                target_value=project_estimation_data.get('target_value'),
                fixed_costs=project_estimation_data.get('fixed_costs'),
                user_id=user_id
            )
            self.db.add(project_estimation)
            self.db.commit()
            self.db.refresh(project_estimation)
            logger.info(f"Project estimation created successfully: {project_estimation.id}")
            return project_estimation
        except SQLAlchemyError as e:
            logger.error(f"Error creating project estimation: {str(e)}")
            self.db.rollback()
            raise

    def get_project_estimation_by_id_or_trow(self, project_estimation_id: int):
        """
        Get a project estimation by its ID.

        Args:
            project_estimation_id (int): The ID of the project estimation to fetch.

        Returns:
            ProjectEstimation: The project estimation instance.
        """
        try:
            project_estimation = self.db.query(ProjectEstimation).filter(ProjectEstimation.id == project_estimation_id).first()
            if project_estimation:
                logger.info(f"Project estimation found: {project_estimation.id}")
                return project_estimation
            else:
                logger.info(f"Project estimation with id {project_estimation_id} not found.")
                raise ValueError(f"Project estimation with id {project_estimation_id} not found.")
        except SQLAlchemyError as e:
            logger.error(f"Error fetching project estimation by id: {str(e)}")
            raise

    def get_all_project_estimations(self) -> list[ProjectEstimation]:
        """
        Get all project estimations.

        Returns:
            List[ProjectEstimation]: List of all project estimation instances.
        """
        try:
            project_estimations = self.db.query(ProjectEstimation).all()
            logger.info(f"Fetched {len(project_estimations)} project estimations.")
            return project_estimations
        except SQLAlchemyError as e:
            logger.error(f"Error fetching all project estimations: {str(e)}")
            raise

    def update_project_estimation(self, project_estimation_id: int, update_data: dict) -> ProjectEstimation | None:
        """
        Update an existing project estimation record.

        Args:
            project_estimation_id (int): The ID of the project estimation to update.
            update_data (dict): Dictionary containing fields to update.

        Returns:
            ProjectEstimation: The updated project estimation instance.
        """
        try:
            project_estimation = self.db.query(ProjectEstimation).filter(ProjectEstimation.id == project_estimation_id).first()
            if project_estimation:
                for key, value in update_data.items():
                    if key in ALLOWED_UPDATE_FIELDS and value is not None:
                        setattr(project_estimation, key, value)
                    else:
                        logger.warning(f"Field {key} is not allowed to be updated.")
                self.db.commit()
                self.db.refresh(project_estimation)
                logger.info(f"Project estimation updated successfully: {project_estimation.id}")
                return project_estimation
            else:
                logger.info(f"Project estimation with id {project_estimation_id} not found for update.")
                return None
        except SQLAlchemyError as e:
            logger.error(f"Error updating project estimation: {str(e)}")
            self.db.rollback()
            raise

    def delete_project_estimation(self, project_estimation_id: int) -> bool:
        """
        Delete a project estimation by its ID.

        Args:
            project_estimation_id (int): The ID of the project estimation to delete.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        try:
            project_estimation = self.db.query(ProjectEstimation).filter(ProjectEstimation.id == project_estimation_id).first()
            if project_estimation:
                self.db.delete(project_estimation)
                self.db.commit()
                logger.info(f"Project estimation deleted successfully: {project_estimation.id}")
                return True
            else:
                logger.info(f"Project estimation with id {project_estimation_id} not found for deletion.")
                return False
        except SQLAlchemyError as e:
            logger.error(f"Error deleting project estimation: {str(e)}")
            self.db.rollback()
            raise
    
    def get_all_project_estimations_by_user(self, user_id: UUID) -> list[ProjectEstimation]:
        """
        Get all project estimations for a specific user.
        
        Args:
            user_id (UUID): The ID of the user for filtering.
        
        Returns:
            List[ProjectEstimation]: List of project estimations for the specified user.
        """
        try:
            project_estimations = self.db.query(ProjectEstimation).filter(ProjectEstimation.user_id == user_id).all()
            logger.info(f"Fetched {len(project_estimations)} project estimations for user: {user_id}")
            return project_estimations
        except SQLAlchemyError as e:
            logger.error(f"Error fetching project estimations for user {user_id}: {str(e)}")
            raise
