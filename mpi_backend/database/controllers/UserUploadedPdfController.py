import logging
import os
from uuid import uuid4
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session

from mpi_backend.database.dao.user_uploaded_pdf_dao import UserUploadedPdfDAO
from mpi_backend.database.controllers.Suppliers import SupplierController
from mpi_backend.utils.s3_utils import upload_file
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER, MAX_BULK_UPLOAD_COUNT, MAX_FILE_SIZE_MB, MAX_TOTAL_BULK_UPLOAD_SIZE_MB

logger = logging.getLogger(__name__)

class UserUploadedPdfController:
    def __init__(self, db: Session):
        self.db = db
        self.dao = UserUploadedPdfDAO()

    async def bulk_upload_invoices(
        self, 
        supplier_id: int, 
        files: List[UploadFile],
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Process multiple invoice uploads:
        1. Fetch supplier name
        2. Validate each file is a PDF
        3. Upload each file to S3
        4. Create database records (trigger handles queue addition)
        """
        supplier_name = SupplierController(self.db).get_supplier_by_id(supplier_id)
        if not supplier_name:
            raise HTTPException(status_code=404, detail=f"Supplier with ID {supplier_id} not found")
        
        if len(files) > MAX_BULK_UPLOAD_COUNT:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files. Maximum allowed is {MAX_BULK_UPLOAD_COUNT} files per upload."
            )

        results = []
        total_size = 0
        current_date_prefix = datetime.now().strftime("%Y-%m")
        
        # Ensure temp directory exists for local processing before S3 upload
        os.makedirs(INVOICE_DOWNLOAD_FOLDER, exist_ok=True)

        for file in files:
            temp_path = None

            try:
                if hasattr(file, 'size') and file.size:
                    file_size = file.size
                else:
                    # Seek to end to get size if not already available
                    file.file.seek(0, 2)
                    file_size = file.file.tell()
                    file.file.seek(0) # Reset to beginning
                
                if file_size > (MAX_FILE_SIZE_MB * 1024 * 1024):
                    results.append({
                        "filename": file.filename,
                        "status": "error",
                        "error": f"File size exceeds limit of {MAX_FILE_SIZE_MB}MB"
                    })
                    continue
                
                total_size += file_size
                if total_size > (MAX_TOTAL_BULK_UPLOAD_SIZE_MB * 1024 * 1024):
                     results.append({
                        "filename": file.filename,
                        "status": "error",
                        "error": f"Total batch size exceeds limit of {MAX_TOTAL_BULK_UPLOAD_SIZE_MB}MB. Remaining files skipped."
                    })
                     break
            except Exception as e:
                logger.exception("Error checking file size for %s", file.filename)
                results.append({
                        "filename": file.filename,
                        "status": "error",
                        "error": "Failed to validate file size"
                })
                continue

            if not file.filename.lower().endswith('.pdf'):
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": "Only PDF files are allowed"
                })
                continue

            try:
                # 1. Prepare S3 Key: invoices/{supplier_name}/{date}/{filename}
                # Sanitize supplier name for S3 key? Usually alphanumeric is safe.
                safe_supplier_name = "".join(x for x in supplier_name if x.isalnum() or x in (' ', '-', '_')).strip()
                safe_filename = os.path.basename(file.filename)
                s3_key = f"invoices/{safe_supplier_name}/{current_date_prefix}/{safe_filename}"
                
                # 2. Save locally temporarily for upload utility
                temp_path = os.path.join(INVOICE_DOWNLOAD_FOLDER, f"temp_{uuid4()}_{safe_filename}")
                content = await file.read()
                with open(temp_path, "wb") as f:
                    f.write(content)
                
                # 3. Upload to S3
                upload_success = upload_file(file_name=temp_path, file_key=s3_key)

                if not upload_success:
                    results.append({
                        "filename": safe_filename,
                        "status": "error",
                        "error": "Failed to upload to S3"
                    })
                    continue

                # 4. Create metadata record
                self.dao.create_upload_record(
                    db=self.db,
                    s3_file_key=s3_key,
                    supplier_id=supplier_id,
                    supplier_name=supplier_name,
                    user_id=user_id
                )

                results.append({
                    "filename": safe_filename,
                    "status": "success",
                    "s3_key": s3_key
                })

            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {str(e)}")
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": "Failed to process file"
                })
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

        return results

    def get_recent_uploads(
        self,
        page: int = 1,
        size: int = 20,
        supplier_id: Optional[int] = None,
        user_id: str = None,
    ) -> dict:
        """
        Return paginated list of user-uploaded PDFs with their extraction queue status.

        Args:
            page:        Page number (1-indexed)
            size:        Items per page (max 100)
            supplier_id: Optional supplier filter
            user_id:     Required user ID for filtering uploads

        Returns:
            Dict with keys: items, total, page, size, pages
        """
        return self.dao.get_recent_uploads(
            db=self.db,
            page=page,
            size=size,
            supplier_id=supplier_id,
            user_id=user_id,
        )

    def get_extracted_header_details(self, queue_id: str) -> Optional[dict]:
        """
        Return extracted header fields from raw.model_extracted_data table for the given
        pdf_extraction_queue_id.

        Returns None when the AI worker has not yet processed the file.
        """
        return self.dao.get_extracted_header_details_by_queue_id(
            db=self.db,
            queue_id=queue_id,
        )
