#!/usr/bin/env python3
"""
Delete duplicate monthly statements (and their invoices) from the database.
Duplicates are defined as statements with the same pdf_filename.
Keeps one statement per pdf_filename, deletes the rest and their invoices.
"""

from collections import defaultdict
from mpi_backend.database.models.statement_models import PlumbingStatement, PlumbingInvoice
from mpi_backend.database import get_db

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("delete_duplicate_statements_by_pdf")

def main():
    db_gen = get_db()
    db = next(db_gen)

    # Group statements by pdf_filename
    statement_groups = defaultdict(list)
    all_statements = db.query(PlumbingStatement).all()
    for stmt in all_statements:
        if stmt.pdf_filename:
            statement_groups[stmt.pdf_filename].append(stmt)

    total_duplicates = 0
    total_deleted = 0

    for pdf_filename, stmts in statement_groups.items():
        if len(stmts) > 1:
            # More than one statement for this PDF: duplicates found
            total_duplicates += len(stmts) - 1
            # Keep the first, delete the rest
            to_delete = stmts[1:]
            for stmt in to_delete:
                logger.info(f"Deleting duplicate statement ID {stmt.id} (pdf_filename={pdf_filename})")
                # Delete all invoices for this statement
                deleted_invoices = db.query(PlumbingInvoice).filter(PlumbingInvoice.statement_id == stmt.id).delete()
                logger.info(f"  Deleted {deleted_invoices} invoices for statement {stmt.id}")
                # Delete the statement itself
                db.delete(stmt)
                total_deleted += 1
    db.commit()
    logger.info(f"Deleted {total_deleted} duplicate statements (and their invoices) by pdf_filename.")
    logger.info(f"Scan complete. {total_duplicates} duplicates found.")

if __name__ == "__main__":
    main() 