import logging
from typing import Dict, Any

from sqlalchemy.orm import Session

from mpi_backend.database.dao.mappings_review_dao import MappingsReviewDAO
from mpi_backend.database.models.User import User
from mpi_backend.database.schemas.MappingsReview import MappingsReviewItemRequest, IsolatedItemResponse

logger = logging.getLogger(__name__)

class MappingsReviewController:
    """Controller for handling mapping review items isolation and retrieval."""

    ALLOWED_STATUSES = {"pending", "done"}

    def __init__(self, db: Session):
        self.db = db

    def isolate_items(self, request: MappingsReviewItemRequest, current_user: User) -> Dict[str, Any]:
        """
        Isolate item for review.
        """
        try:
            MappingsReviewDAO.bulk_create_review_items(
                db=self.db,
                vendor=request.vendor,
                item_id=request.item_id,
                reason=request.reason,
                map_to_item=request.map_to_item,
                user_id=str(current_user.id)
            )
            
            return {
                "success": True,
                "message": f"Successfully isolated {request.item_id} item for review.",
            }
            
        except Exception as e:
            logger.error(f"Error in controller while isolating items: {str(e)}")
            raise e

    def get_isolated_items(self, page: int = 1, size: int = 10, status: str = "all") -> Dict[str, Any]:
        """Retrieve paginated isolated items with joined metadata."""
        try:
            items, total_count = MappingsReviewDAO.get_isolated_items(self.db, page, size, status)

            formatted_items = [IsolatedItemResponse.from_dict(item) for item in items]

            total_pages = (total_count + size - 1) // size if size > 0 and total_count > 0 else 0
            
            return {
                "items": formatted_items,
                "total_count": total_count,
                "page": page,
                "size": size,
                "pages": total_pages
            }
            
        except Exception as e:
            logger.error(f"Error in controller while fetching isolated items: {str(e)}")
            raise e

    def get_isolated_total_amount(self) -> Dict[str, Any]:
        """
        Get aggregate sum of total amount for all isolated items.
        """
        try:
            total_amount = MappingsReviewDAO.get_isolated_total_amount(self.db)
            return {
                "success": True,
                "total_amount": total_amount
            }
        except Exception as e:
            logger.error(f"Error in controller while fetching isolated total: {str(e)}")
            raise e

    def remove_isolated_item(self, item_id: str) -> Dict[str, Any]:
        """
        Remove an item from mappings_review_items by ID.
        Raises ValueError if the item has status 'done'.
        """
        try:
            MappingsReviewDAO.remove_isolated_item(self.db, item_id)
            return {
                "success": True,
                "message": f"Successfully removed item with ID {item_id} from review."
            }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error in controller while removing isolated item: {str(e)}")
            raise e

    def update_item_status(self, item_id: str, status: str) -> Dict[str, Any]:
        """
        Update the status of a review item.
        Raises ValueError if status is not in the allowed set.
        """
        normalized = status.strip().lower()
        if normalized not in self.ALLOWED_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Allowed values: {sorted(self.ALLOWED_STATUSES)}")
        try:
            MappingsReviewDAO.update_item_status(self.db, item_id, normalized)
            return {
                "success": True,
                "message": f"Successfully updated item status to {normalized}."
            }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error in controller while updating item status: {str(e)}")
            raise e
