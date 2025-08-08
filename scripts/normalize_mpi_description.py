#!/usr/bin/env python3
"""
Normalize MPI descriptions:
- Set mpi_description = 'No Match' where mpi_item is 'No Match' or
  starts with 'UIDI'.

Usage:
  python -m scripts.normalize_mpi_description [--dry-run]
"""

from sqlalchemy import text
import sys
from mpi_backend.database import SessionLocal


def normalize(dry_run: bool = False) -> int:
    """Normalize invoice_items.mpi_description.

    Returns the number of rows that would be affected (dry run) or were
    actually updated.
    """
    with SessionLocal() as db:
        # Count rows to change
        count_sql = text(
            """
            SELECT COUNT(*)
            FROM invoice_items
            WHERE (
                mpi_item = 'No Match' OR mpi_item ILIKE 'UIDI%'
            )
            AND COALESCE(mpi_description, '') <> 'No Match'
            """
        )
        total_to_change = db.execute(count_sql).scalar() or 0

        if dry_run or total_to_change == 0:
            return int(total_to_change)

        update_sql = text(
            """
            UPDATE invoice_items
            SET mpi_description = 'No Match'
            WHERE (
                mpi_item = 'No Match' OR mpi_item ILIKE 'UIDI%'
            )
            AND COALESCE(mpi_description, '') <> 'No Match'
            """
        )
        result = db.execute(update_sql)
        db.commit()
        return int(getattr(result, 'rowcount', total_to_change) or 0)


def main() -> None:
    dry_run = '--dry-run' in sys.argv
    affected = normalize(dry_run=dry_run)
    if dry_run:
        print(f"[DRY-RUN] Rows needing normalization: {affected}")
    else:
        print(f"Normalized rows: {affected}")


if __name__ == '__main__':
    main()
