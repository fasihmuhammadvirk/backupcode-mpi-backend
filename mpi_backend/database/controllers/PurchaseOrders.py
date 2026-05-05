import logging
import math
from typing import List

from typing import Optional, Union, Dict, Any
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from mpi_backend.database.dao.purchase_order_dao import PurchaseOrderDAO
from mpi_backend.database.schemas.PurchaseOrder import PODraftCreate, PODraftSummary, PaginatedPODraftResponse, PODraftDetail
from mpi_backend.database.schemas.PurchaseOrder import (
    POItemResponse,
    POBulkImportRequest
)
from mpi_backend.utils import export_utils

logger = logging.getLogger(__name__)


class PurchaseOrder:

    def __init__(self, db):
        self.db_context = db

    def _get_db_session(self) -> Session:
        """Get a database session object, whether db_context is a factory or session."""
        # Check if it's already a session instance (has query, add, commit methods)
        if hasattr(self.db_context, 'query') and hasattr(self.db_context, 'commit'):
            return self.db_context
        # Otherwise assume it's a session factory
        return self.db_context()

    def get_price_comparison(
            self,
            filter_request: POBulkImportRequest
    ) -> List[POItemResponse]:
        """
        This method retrieves the cheapest price comparison for purchase order items
        based on the provided filters.
        """

        purchase_order_dao = PurchaseOrderDAO()
        db = self._get_db_session()
        items = purchase_order_dao.get_price_comparison(db=db, filter_request=filter_request)

        return [
            POItemResponse.from_dict(item)
            for item in items
        ]

    @classmethod
    def export_price_comparison_to_csv(
        cls,
        data: List[POItemResponse],
        background_tasks: Optional[BackgroundTasks] = None,
        threshold: int = 1000
    ) -> Union[Dict[str, Any], Any]:
        """
        Export price comparison data to CSV.

        Uses streaming for small datasets (<threshold) and async S3 upload for large datasets.

        Args:
            data: List of POItemResponse objects to export
            background_tasks: FastAPI BackgroundTasks for async processing (optional)
            threshold: Record count threshold for async processing (default 1000)

        Returns:
            - For streaming: Dict with type='streaming', generator, and filename
            - For async: Dict with type='async', export_id, status, and status_endpoint
        """
        if len(data) == 0:
            raise ValueError("No data available to export")

        dicts = [item.to_dict() for item in data]
        return export_utils.export_generic(
            items=dicts,
            background_tasks=background_tasks,
            threshold=threshold,
            filename_prefix="purchase_order_export"
        )

    @classmethod
    def export_price_comparison_to_pdf(
        cls,
        data: List[POItemResponse],
        background_tasks: Optional[BackgroundTasks] = None,
        threshold: int = 1000
    ) -> Union[Dict[str, Any], bytes]:
        """
        Export price comparison data to a styled PDF document.

        Uses sync rendering for small datasets (<threshold) and async S3 upload for large datasets.

        Args:
            data: List of POItemResponse objects to include in the PDF.
            background_tasks: FastAPI BackgroundTasks for async processing (optional)
            threshold: Record count threshold for async processing (default 1000)

        Returns:
            - For sync: Dict with type='streaming', pdf_bytes, and filename
            - For async: Dict with export_id, status, and status_endpoint
        """
        if len(data) == 0:
            raise ValueError("No data available to export")

        dicts = [item.to_dict() for item in data]
        return export_utils.export_generic(
            items=dicts,
            background_tasks=background_tasks,
            threshold=threshold,
            file_type="pdf",
            filename_prefix="purchase_order_export"
        )


    def save_draft(self, draft_data: PODraftCreate, user_id: UUID) -> PODraftSummary:
        purchase_order_dao = PurchaseOrderDAO()
        db_draft = purchase_order_dao.create_draft(self._get_db_session(), draft_data, user_id)
        return PODraftSummary.model_validate(db_draft)

    def get_drafts_summary(self, page: int = 1, size: int = 20) -> PaginatedPODraftResponse:
        purchase_order_dao = PurchaseOrderDAO()
        items, total = purchase_order_dao.get_drafts_summary(self._get_db_session(), page, size)
        pages = math.ceil(total / size) if size > 0 else 0

        return PaginatedPODraftResponse(
            items=[PODraftSummary.model_validate(item) for item in items],
            total=total,
            page=page,
            size=size,
            pages=pages
        )

    def get_draft_detail(self, draft_id: UUID) -> Optional[PODraftDetail]:
        purchase_order_dao = PurchaseOrderDAO()
        db_draft = purchase_order_dao.get_draft_by_id(self._get_db_session(), draft_id)
        if not db_draft:
            return None
        return PODraftDetail.model_validate(db_draft)

    def delete_draft(self, draft_id: UUID) -> bool:
        purchase_order_dao = PurchaseOrderDAO()
        return purchase_order_dao.delete_draft(self._get_db_session(), draft_id)
