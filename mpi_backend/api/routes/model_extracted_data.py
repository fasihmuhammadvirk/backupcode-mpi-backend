from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Tuple, Union
from collections import defaultdict
import logging
from sqlalchemy import func
from mpi_backend.utils.auth.roles import UserRole
from mpi_backend.database import get_db
from mpi_backend.database.models.ModelExtractedData import (
    ModelExtractedData
)
from mpi_backend.database.schemas.ModelExtractedData import (
    ModelExtractedDataResponse,
    GroupedModelExtractedDataResponse
)
from mpi_backend.utils.auth.dependencies import get_current_user
from mpi_backend.database.models.User import User
from mpi_backend.utils.s3_utils import get_presigned_url

router = APIRouter(
    prefix="/model-extracted-data",
    tags=["Model Extracted Data"]
)
logger = logging.getLogger(__name__)


@router.get("")
def get_model_extracted_data_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    pdf_extraction_queue_id: Optional[str] = Query(None, description="Filter by invoice ID"),
    model_name: Optional[str] = Query(None, description="Filter by model name (e.g., 'gemini', 'openai)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    grouped: bool = Query(False, description="Group records by item, pdf_extraction_queue_id, qty, and description")
) -> Union[List[ModelExtractedDataResponse], List[GroupedModelExtractedDataResponse]]:
    """
    Get model extracted data with optional filtering and grouping.

    **Summary:**
        Retrieves a list of model extracted data records with support for
        filtering, pagination, and optional grouping. Returns only the most
        recent records for each unique combination of pdf_extraction_queue_id, model_name,
        item, ref_no, date, qty, and cost (based on extracted_at timestamp).
        Each record includes a presigned S3 URL for accessing the associated
        invoice file when available.

    **Query Parameters:**
        - **pdf_extraction_queue_id** (`str`, optional): Filter records by specific invoice ID
        - **model_name** (`str`, optional): Filter records by model name
            (e.g., 'gemini', 'openai'). Case-sensitive.
        - **limit** (`int`, optional): Maximum number of records to return.
            Defaults to 100. Must be between 1 and 1000.
        - **offset** (`int`, optional): Number of records to skip for pagination.
            Defaults to 0. Must be >= 0.
        - **grouped** (`bool`, optional): If True, groups records by
            (item, pdf_extraction_queue_id, qty). Defaults to False.

    **Authentication:**
        - Requires valid JWT token in Authorization header
        - Requires ADMIN role

    **Returns:**
        - **List[ModelExtractedDataResponse]**: List of individual records when
            grouped=False
        - **List[GroupedModelExtractedDataResponse]**: List of grouped records
            when grouped=True. Each group contains records that share the same
            (item, pdf_extraction_queue_id, qty) values.

    **Response Example (ungrouped):**
    ```json
    [
        {
            "id": 1,
            "item": "ABC123",
            "pdf_extraction_queue_id": "uuid-here",
            "model_name": "gemini",
            "qty": 10,
            "cost": 25.50,
            "signed_url": "https://s3-presigned-url...",
            ...
        }
    ]
    ```

    **Response Example (grouped):**
    ```json
    [
        {
            "item": "ABC123",
            "pdf_extraction_queue_id": "uuid-here",
            "qty": 10,
            "records": [
                {
                    "id": 1,
                    "model_name": "gemini",
                    "cost": 25.50,
                    ...
                }
            ]
        }
    ]
    ```

    **Error Codes:**
        - **403**: User does not have ADMIN role
        - **500**: Database error during query

    **Use Cases:**
        - Retrieving all extracted data for review and approval
        - Filtering extracted data by invoice or model for analysis
        - Grouping duplicate or similar records for comparison
        - Paginating through large datasets of extracted data
        - Accessing invoice files via presigned URLs for verification
    """
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this resource"
        )
    logger.info(
        "GET /model-extracted-data - Fetching records "
        "(pdf_extraction_queue_id=%s, model_name=%s, limit=%s, offset=%s, grouped=%s)",
        pdf_extraction_queue_id, model_name, limit, offset, grouped
    )

    try:
        subquery = db.query(
            ModelExtractedData.pdf_extraction_queue_id,
            ModelExtractedData.model_name,
            ModelExtractedData.item,
            ModelExtractedData.ref_no,
            ModelExtractedData.date,
            ModelExtractedData.qty,
            ModelExtractedData.cost,
            func.max(ModelExtractedData.extracted_at).label('max_extracted_at')
        ).group_by(
            ModelExtractedData.pdf_extraction_queue_id,
            ModelExtractedData.model_name,
            ModelExtractedData.item,
            ModelExtractedData.ref_no,
            ModelExtractedData.date,
            ModelExtractedData.qty,
            ModelExtractedData.cost
        ).subquery()

        query = db.query(ModelExtractedData).join(
            subquery,
            (ModelExtractedData.pdf_extraction_queue_id == subquery.c.pdf_extraction_queue_id) &
            (ModelExtractedData.model_name == subquery.c.model_name) &
            (ModelExtractedData.item == subquery.c.item) &
            (ModelExtractedData.ref_no == subquery.c.ref_no) &
            (ModelExtractedData.date == subquery.c.date) &
            (ModelExtractedData.qty == subquery.c.qty) &
            (ModelExtractedData.cost.is_not_distinct_from(subquery.c.cost)) &
            (ModelExtractedData.extracted_at == subquery.c.max_extracted_at)
        )
        if pdf_extraction_queue_id:
            query = query.filter(ModelExtractedData.pdf_extraction_queue_id == pdf_extraction_queue_id)

        if model_name:
            query = query.filter(ModelExtractedData.model_name == model_name)

        query = query.order_by(
            ModelExtractedData.id.desc()
        ).offset(offset).limit(limit)
        records = query.all()
        # Generate signed URLs for each record from ModelExtractedData's
        # s3_file_key
        response_list = []
        for record in records:
            signed_url = None
            # Get signed URL from ModelExtractedData's s3_file_key if available
            if record.s3_file_key:
                signed_url = get_presigned_url(
                    file_key=record.s3_file_key,
                    expiration_time=180,
                    is_invoice=True
                )

            # Convert record to response model with signed_url
            response = ModelExtractedDataResponse.model_validate(record)
            response.signed_url = signed_url
            response_list.append(response)

        # If grouped=True, group the records by (item, pdf_extraction_queue_id, qty)
        if grouped:
            grouped_dict: Dict[Tuple[Optional[str], Optional[str], Optional[int]], List[ModelExtractedDataResponse]] = defaultdict(list)
            
            for response in response_list:
                # Create grouping key: (item, pdf_extraction_queue_id, qty)
                # Normalize None values for consistent grouping
                key = (
                    response.item if response.item else None,
                    str(response.pdf_extraction_queue_id) if response.pdf_extraction_queue_id else None,
                    response.qty,
                )
                grouped_dict[key].append(response)
            
            # Convert to GroupedModelExtractedDataResponse
            grouped_response = []
            for (item, inv_id, qty), records_list in grouped_dict.items():
                # Get pdf_extraction_queue_id from first record (all records in group have same pdf_extraction_queue_id)
                invoice_uuid = records_list[0].pdf_extraction_queue_id if records_list else None
                
                grouped_response.append(
                    GroupedModelExtractedDataResponse(
                        item=item,
                        pdf_extraction_queue_id=invoice_uuid,
                        qty=qty,
                        records=records_list
                    )
                )
            
            logger.info(
                "GET /model-extracted-data - Successfully fetched and grouped %s records into %s groups",
                len(response_list),
                len(grouped_response)
            )
            return grouped_response

        logger.info(
            "GET /model-extracted-data - Successfully fetched %s records",
            len(response_list)
        )
        return response_list

    except Exception as e:
        logger.exception(
            "GET /model-extracted-data - Failed to fetch records"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch model extracted data"
        ) from e


@router.patch(
    "/{record_id}/approve", response_model=ModelExtractedDataResponse
)
def approve_model_extracted_data(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Approve a model extracted data record by setting status to
    'Human Approved'.

    **Summary:**
        Updates the status of a model extracted data record to
        'Human Approved', indicating that a human reviewer has verified
        and approved the extracted data.

    **Path Parameters:**
        - **record_id** (`int`, required): The ID of the record to approve

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **ModelExtractedDataResponse**: Updated record with status set to
            'Human Approved'

    **Response Example:**
    ```json
    {
        "id": 1,
        "item": "ABC123",
        "description": "Pipe Fitting",
        "status": "human_approved",
        ...
    }
    ```

    **Error Codes:**
        - **404**: Record not found
        - **500**: Database error during update

    **Use Cases:**
        - Human reviewer approves extracted data after verification
        - Marking records as verified for quality assurance
        - Workflow management for data extraction review process
    """
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this resource"
        )
    logger.info(
        "PATCH /model-extracted-data/%s/approve - Approving record",
        record_id
    )

    try:
        record = db.query(ModelExtractedData).filter(
            ModelExtractedData.id == record_id
        ).first()

        if not record:
            logger.warning(
                "PATCH /model-extracted-data/%s/approve - Record not found",
                record_id
            )
            raise HTTPException(
                status_code=404,
                detail=f"Record with id {record_id} not found"
            )

        record.status = "human_approved"
        db.commit()
        db.refresh(record)

        logger.info(
            "PATCH /model-extracted-data/%s/approve - Successfully approved",
            record_id
        )
        return record

    except Exception as e:
        logger.exception(
            "PATCH /model-extracted-data/%s/approve - Failed",
            record_id
        )
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to approve record"
        ) from e


@router.patch("/{record_id}/reject", response_model=ModelExtractedDataResponse)
def reject_model_extracted_data(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Reject a model extracted data record by setting status to 'Human Rejected'.

    **Summary:**
        Updates the status of a model extracted data record to
        'Human Rejected', indicating that a human reviewer has identified
        issues with the extracted data and it requires correction or
        re-extraction.

    **Path Parameters:**
        - **record_id** (`int`, required): The ID of the record to reject

    **Authentication:**
        - Requires valid JWT token in Authorization header

    **Returns:**
        - **ModelExtractedDataResponse**: Updated record with status set to
            'Human Rejected'

    **Response Example:**
    ```json
    {
        "id": 1,
        "item": "ABC123",
        "description": "Pipe Fitting",
        "status": "human_rejected",
        ...
    }
    ```

    **Error Codes:**
        - **404**: Record not found
        - **500**: Database error during update

    **Use Cases:**
        - Human reviewer rejects extracted data due to errors
        - Marking records that need correction or re-extraction
        - Quality control workflow for data extraction review
    """
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this resource"
        )
    logger.info(
        "PATCH /model-extracted-data/%s/reject - Rejecting record",
        record_id
    )

    try:
        record = db.query(ModelExtractedData).filter(
            ModelExtractedData.id == record_id
        ).first()

        if not record:
            logger.warning(
                "PATCH /model-extracted-data/%s/reject - Record not found",
                record_id
            )
            raise HTTPException(
                status_code=404,
                detail=f"Record with id {record_id} not found"
            )

        record.status = "human_rejected"
        db.commit()
        db.refresh(record)

        logger.info(
            "PATCH /model-extracted-data/%s/reject - Successfully rejected",
            record_id
        )
        return record

    except Exception as e:
        logger.exception(
            "PATCH /model-extracted-data/%s/reject - Failed",
            record_id
        )
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to reject record"
        ) from e
