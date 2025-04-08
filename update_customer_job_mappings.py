import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from mpi_backend.database.models import CustomerJobMapping, InvoiceItem
from mpi_backend.config import SQLALCHEMY_DATABASE_URI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_existing_invoice_items(db):
    try:
        # Fetch customer job mappings directly from DB
        mappings = db.query(CustomerJobMapping).all()
        mapping_dict = {
            m.customer_job: m.updated_customer_job
            for m in mappings
        }

        # Fetch all invoice items
        invoice_items = db.query(InvoiceItem).all()
        updated_count = 0

        for item in invoice_items:
            if item.customer_job in mapping_dict:
                new_job = mapping_dict[item.customer_job]
                if new_job != item.customer_job:
                    item.customer_job = new_job
                    updated_count += 1

        db.commit()
        logger.info(f"✅ Updated {updated_count} invoice items.")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating invoice items: {str(e)}")
        raise

def main():
    engine = create_engine(SQLALCHEMY_DATABASE_URI)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        update_existing_invoice_items(db)
        logger.info("✅ Invoice update completed.")
    except Exception as e:
        logger.error(f"❌ Failed in main: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
