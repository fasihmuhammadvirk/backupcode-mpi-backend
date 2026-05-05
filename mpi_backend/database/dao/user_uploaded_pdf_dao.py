import logging
from math import ceil
from typing import Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from mpi_backend.database.models.UserUploadedPdf import UserUploadedPdf

logger = logging.getLogger(__name__)

class UserUploadedPdfDAO:
    """Data Access Object for User Uploaded PDF operations."""

    @staticmethod
    def create_upload_record(
        db: Session,
        s3_file_key: str,
        supplier_id: int,
        supplier_name: str,
        user_id: str = None
    ) -> UserUploadedPdf:
        """Create a new record for a user upload"""
        try:
            upload_record = UserUploadedPdf(
                s3_file_key=s3_file_key,
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                user_id=user_id
            )
            db.add(upload_record)
            db.commit()
            db.refresh(upload_record)
            return upload_record
        except Exception as e:
            db.rollback()
            logger.exception(f"Error creating user upload record: {e}")
            raise

    @staticmethod
    def get_recent_uploads(
        db: Session,
        page: int = 1,
        size: int = 20,
        supplier_id: Optional[int] = None,
        user_id: str = None
    ) -> Dict[str, Any]:
        """
        Return paginated user uploads joined with pdf_extraction_queue.

        Joined columns returned per row:
            id, s3_file_key, supplier_id, supplier_name, uploaded_at,
            queue_status  (pending | in_progress | completed | failed | NULL)

        The filename is derived from the last segment of s3_file_key.
        """
        where_clauses = ["uup.deleted_at IS NULL AND uup.user_id = :user_id"]
        params: Dict[str, Any] = {
            "page_size": size,
            "offset": (page - 1) * size,
            "user_id": user_id
        }

        if supplier_id is not None:
            where_clauses.append("uup.supplier_id = :supplier_id")
            params["supplier_id"] = supplier_id

        where_sql = " AND ".join(where_clauses)

        count_query = f"""
            SELECT COUNT(*)
            FROM raw.user_uploaded_pdfs uup
            WHERE {where_sql}
        """

        data_query = f"""
            SELECT
                uup.id,
                uup.s3_file_key,
                uup.supplier_id,
                uup.supplier_name,
                uup.uploaded_at,
                -- Most recent queue entry for this upload (there should be only one)
                peq.status        AS queue_status,
                peq.error_message AS queue_error,
                peq.id            AS queue_id
            FROM raw.user_uploaded_pdfs uup
            LEFT JOIN raw.pdf_extraction_queue peq
                ON peq.user_upload_id = uup.id
               AND peq.deleted_at IS NULL
            WHERE {where_sql}
            ORDER BY uup.uploaded_at DESC
            LIMIT :page_size OFFSET :offset
        """

        total_count = db.execute(text(count_query), params).scalar() or 0

        rows = db.execute(text(data_query), params).fetchall()

        items = []
        for row in rows:
            row_dict = dict(row._mapping)
            # Derive a friendly filename from the S3 key
            row_dict["filename"] = row_dict["s3_file_key"].split("/")[-1]
            # Stringify UUIDs for JSON serialisation
            row_dict["id"] = str(row_dict["id"])
            # Format timestamp
            if row_dict.get("uploaded_at"):
                row_dict["uploaded_at"] = row_dict["uploaded_at"].isoformat()
            items.append(row_dict)

        total_pages = ceil(total_count / size) if size > 0 and total_count > 0 else 0

        logger.info(
            f"DAO get_recent_uploads: returned {len(items)}/{total_count} rows "
            f"(page={page}, size={size})"
        )

        return {
            "items": items,
            "total": total_count,
            "page": page,
            "size": size,
            "pages": total_pages,
        }

    @staticmethod
    def get_extracted_header_details_by_queue_id(
        db: Session,
        queue_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch extracted invoice header fields **directly from raw.model_extracted_data**
        for a given pdf_extraction_queue_id.
        """
        query = text("""
            WITH best_extraction AS (
                SELECT
                    confidence_score,
                    validation_score,
                    status,
                    extracted_at,
                    -- Resolve JSON shape: flat root vs first element of 'invoices' array.
                    -- Both shapes are produced by the AI worker depending on the model version.
                    CASE
                        WHEN raw_data ? 'invoices'
                        THEN (raw_data->'invoices')->0
                        ELSE raw_data
                    END AS inv
                FROM raw.model_extracted_data
                WHERE pdf_extraction_queue_id = :queue_id
                  AND deleted_at IS NULL
                ORDER BY validation_score DESC NULLS LAST, extracted_at DESC
                LIMIT 1
            ),
            parsed_amounts AS (
                SELECT 
                    *,
                    COALESCE(NULLIF(TRIM(inv->>'tax'), '')::numeric, 0) AS tax,
                    COALESCE(NULLIF(TRIM(inv->>'sub_total'), '')::numeric, 0) AS sub_total,
                    COALESCE(NULLIF(TRIM(inv->>'freight'), '')::numeric, 0) AS freight
                FROM best_extraction
            )
            SELECT
                confidence_score,
                ROUND(validation_score::numeric, 2) AS validation_score,
                status,
                extracted_at,
                tax,
                sub_total,
                freight,
                ROUND((tax + sub_total + freight), 2) AS total,
                TRIM(inv->>'ref_no') AS ref_no,

                -- Multi-format date parsing (ISO, MM/DD/YYYY, MM/DD/YY)
                CASE
                    WHEN inv->>'date' ~ '^\d{4}-\d{2}-\d{2}$'
                    THEN (inv->>'date')::date
                    WHEN inv->>'date' ~ '^\d{1,2}/\d{1,2}/\d{4}$'
                    THEN TO_DATE(inv->>'date', 'MM/DD/YYYY')
                    WHEN inv->>'date' ~ '^\d{1,2}/\d{1,2}/\d{2}$'
                    THEN TO_DATE(inv->>'date', 'MM/DD/YY')
                    ELSE NULL
                END AS date,

                TRIM(COALESCE(
                    NULLIF(inv->>'po_no', ''),
                    NULLIF(inv->>'po_number', '')
                )) AS po_number

            FROM parsed_amounts
        """)

        try:
            row = db.execute(query, {"queue_id": queue_id}).fetchone()
        except Exception as e:
            logger.exception(
                f"DAO get_extraction_details_by_queue_id failed for queue_id={queue_id}: {e}"
            )
            raise

        if row is None:
            return None

        result = dict(row._mapping)
        # Serialise date/datetime fields
        if result.get("date"):
            result["date"] = result["date"].isoformat()
        if result.get("extracted_at"):
            result["extracted_at"] = result["extracted_at"].isoformat()

        logger.info(f"DAO get_extraction_details_by_queue_id: found row for queue_id={queue_id}")
        return result
