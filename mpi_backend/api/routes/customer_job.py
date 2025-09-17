from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from mpi_backend.database import get_db
from mpi_backend.utils.auth.auth_bearer import JWTBearer
from mpi_backend.database.controllers.CustomerJobMappingContorller import CustomerJobMappingController

router = APIRouter(prefix="/customer-job", tags=["Customer Job Mapping"])


@router.post("/update-mappings")
async def update_customer_job_mappings(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        token: str = Depends(JWTBearer())
):
    """
    Update customer job mappings from an Excel file.
    
    This endpoint allows bulk updating of customer job mappings by uploading
    an Excel file containing the mapping data. The file should contain two
    columns with specific headers for proper processing.
    
    **File Requirements:**
    - **Format**: Excel file (.xlsx, .xls, .xlsm)
    - **Required Columns**:
      - **customer_job**: The original customer job name (existing in system)
      - **updated_customer_job**: The new customer job name to map to
    
    **File Structure Example:**
    ```
    | customer_job        | updated_customer_job |
    |---------------------|---------------------|
    | Old Job Name 1      | New Job Name 1      |
    | Old Job Name 2      | New Job Name 2      |
    | Project Alpha       | Project Alpha v2    |
    ```
    
    **Processing:**
    - Validates file format and structure
    - Reads mapping data from Excel file
    - Updates existing customer job mappings in the database
    - Returns success/failure status with detailed message
    
    **Authentication:**
    - Requires valid JWT token in Authorization header
    
    **Returns:**
    - **status**: Success status ("success" or "error")
    - **message**: Detailed message about the operation result
    
    **Response Examples:**
    
    **Success Response:**
    ```json
    {
        "status": "success",
        "message": "Successfully updated 25 customer job mappings"
    }
    ```
    
    **Error Response:**
    ```json
    {
        "status": "error",
        "message": "Invalid file format. Only Excel files are allowed"
    }
    ```
    
    **Error Codes:**
    - **400**: Invalid file format (non-Excel files)
    - **422**: Value error in file processing (invalid data format)
    - **500**: Internal server error during processing
    
    **Usage Example:**
    ```
    POST /customer-job/update-mappings
    Content-Type: multipart/form-data
    
    Form Data:
    - file: [Excel file with customer_job and updated_customer_job columns]
    ```
    
    **Notes:**
    - The file must be uploaded as multipart/form-data
    - Only the first sheet of the Excel file will be processed
    - Empty rows or rows with missing required columns will be skipped
    - Duplicate mappings will be updated with the latest value
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
