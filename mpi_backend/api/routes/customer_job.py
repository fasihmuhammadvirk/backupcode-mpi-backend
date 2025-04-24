from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.database.controllers import CustomerJobMappingController

router = APIRouter(prefix="/customer-job")


@router.post("/update-mappings")
async def update_customer_job_mappings(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer())
):
    """
    Endpoint to update customer job mappings from an Excel file.
    The Excel file should have two columns:
    - customer_job: The original customer job name
    - updated_customer_job: The new customer job name
    """
    try:
        # Validate file extension
        if not file.filename.lower().endswith(('.xlsx', '.xls', '.xlsm')):
            raise HTTPException(
                status_code=400,
                detail="Only Excel files (.xlsx, .xls, .xlsm) are allowed"
            )

        # Read file object
        # excel_file = file.file

        # You can add a check here if needed to validate contents
        message = CustomerJobMappingController.add_new_mappings(excel_file=file.file, db=db)

        return {
            "status": "success",
            "message": message
        }

    except HTTPException as http_ex:
        # Pass through known HTTP exceptions
        raise http_ex

    except ValueError as ve:
        raise HTTPException(
            status_code=422,
            detail=f"Value error: {str(ve)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while processing the file: {str(e)}"
        )
