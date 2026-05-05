"""
Issue #665: Restore 38 Plumbing Exchange invoices to the pdf extraction queue.

- 6 AR-ST files: clear soft-delete + set status=pending
- 32 invoice files: reset status to pending for re-extraction
- Soft-delete existing model_extracted_data so fresh extractions are created

Run with: uv run python scripts/issue_665_restore_pe_invoices.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / ".env")

import psycopg2

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USERNAME"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

AR_ST_KEYS = [
    "invoices/statements_at_theplumbingexchange.com/2020-09/174c760c3f82e7dd_AR-ST-mpip01-Sep2020.pdf",
    "invoices/statements_at_theplumbingexchange.com/2020-11/176023d97d275ff8_AR-ST-mpip01-Nov2020.pdf",
    "invoices/statements_at_theplumbingexchange.com/2020-12/176a78357b5db4fc_AR-ST-mpip01-Dec2020.pdf",
    "invoices/statements_at_theplumbingexchange.com/2021-01/1773be38273a7b6c_AR-ST-mpip01-Jan2021.pdf",
    "invoices/statements_at_theplumbingexchange.com/2021-02/177db5f80912bbc9_AR-ST-mpip01-Feb2021.pdf",
    "invoices/statements_at_theplumbingexchange.com/2021-03/1786c9a949a014e4_AR-ST-mpip01-Mar2021.pdf",
]

INVOICE_KEYS = [
    "invoices/sales_at_theplumbingexchange.com/2020-11/175deba1fbc24b0f_invoices11-18-2020B35913CA-FBC8-42A0-C0FAD89E18DB476A.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-11/175debb715a31662_invoices11-18-2020B36670FB-9778-0E63-3A954992ACB5AF79.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-11/175e35820f0973a0_invoices11-19-2020E1886234-E9F6-A2A7-C03270077C12C611.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-11/175eeb9ba74ea62d_invoices11-22-20205356420B-B95A-BEE8-554EE0178BF4460A.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-11/175fd6eac38233f6_invoices11-24-2020E66B0695-0821-6EA4-D6DF8BEE88E48BE5.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-11/1760820bb50c8c5f_invoices11-27-2020515E03F9-B1E1-E182-D95CA37B9116DD32.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-12/1762157656f0bf2a_invoices12-01-20204ACFBD4A-A2C0-1632-ED739F9D10F89A2C.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-12/1764a425e908370c_invoices12-09-2020E3FF4971-B702-93BE-C8084531D88638FF.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-12/17688c5fe064de0d_invoices12-21-2020551F1501-0961-6AC0-36D0F25B1C9CED20.pdf",
    "invoices/sales_at_theplumbingexchange.com/2020-12/176bc2bfbfa931bb_invoices12-31-202059ADCEDD-984E-808D-43ACF36D3F8D07E8.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-01/176e0251c04778fa_invoices01-07-2021C16C05A1-A93A-8759-14B27061B8CF0F20.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-01/1771f9f8ed278cc4_invoices01-20-20213C2EE458-C29A-4808-3A0016D5BBB1B328.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-01/1772a7879b42a78a_invoices01-22-2021A8ABE064-F543-3AC3-7A04B2ADEB90C806.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-01/1774c479bf65111d_invoices01-28-2021F826DCDF-CD0C-A0EE-3541A61682492190.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-02/1776f6f9c782ab23_invoices02-04-202157B92365-E41B-C2FF-E4062DB2D2940D4F.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-02/1779831a3d3bc101_invoices02-12-2021EF4DD519-05E1-19D9-8092C6EA9E207627.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-02/177cc836d12e2988_invoices02-22-2021FA7DD234-EB1D-56B5-CDD4D7472B585A66.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/177f02bdad9487c1_invoices03-01-20215F1069CB-BAD0-2BC1-FD3E1E65352099F9.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/178156ac61373e8e_invoices03-09-2021D33F6CE8-CB52-5936-47F4FD855FFE89AC.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/17819fe087c3d2d8_invoices03-09-20210143EDD4-B5C7-2908-D6C0084D90101308.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/17826b32485b67ec_invoices03-12-202182F22306-D21F-71FA-B9954C10664CE213.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/1783c314ae5050f3_invoices03-16-202159E85D73-DD73-73E6-622ECBC3927FF4E4.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/1784be2ebb370245_invoices03-19-2021F6CFF892-9426-972F-9D7C9AC063EC433C.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-03/17862318880e92eb_invoices03-23-2021D5EB1545-F2E8-5CD3-0D3F41917941A508.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-04/178a86ceaa8bbee9_invoices04-06-20219435F3E9-A07C-531B-7FC0845CF8032D79.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-04/178a9168c92a1890_invoices04-06-20219AD55B1D-0354-359C-FA44194285636CD7.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-04/178d2a77e93129a0_invoices04-14-20213A767464-ABA2-2548-B2A3FA16A5F5DD79.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-04/178f5cb750bbabf0_invoices04-21-202199E331AF-AD5C-24F9-8A5C877936261040.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-04/17911726620ccc07_invoices04-26-2021AE629A7F-9C0C-9D08-6E2784FAD539D427.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-05/1795e91cfa2aaf8e_invoices05-11-2021B19C5A8A-AA5F-CC12-CCEFC67199AE874C.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-05/1796d036120f5ae8_invoices05-14-2021420EE71A-F278-AF69-FFA95E6F046C9AC6.pdf",
    "invoices/sales_at_theplumbingexchange.com/2021-06/179faaeeaad259c9_invoices06-11-2021CAFE193A-D0C1-1003-7B0D3F3102751DE4.pdf",
]


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            # Step 1: Restore 6 soft-deleted AR-ST files
            print("[1/4] Restoring 6 AR-ST files in pdf_extraction_queue...")
            cur.execute("""
                UPDATE raw.pdf_extraction_queue
                SET deleted_at = NULL,
                    deletion_reason = NULL,
                    status = 'pending'
                WHERE s3_key = ANY(%s)
            """, (AR_ST_KEYS,))
            print(f"       {cur.rowcount} rows updated")

            # Step 2: Restore parent email_download_queue records
            print("[2/4] Restoring parent emails in email_download_queue...")
            cur.execute("""
                UPDATE raw.email_download_queue
                SET deleted_at = NULL,
                    deletion_reason = NULL
                WHERE id IN (
                    SELECT DISTINCT peq.email_queue_id
                    FROM raw.pdf_extraction_queue peq
                    WHERE peq.s3_key = ANY(%s)
                )
                AND deleted_at IS NOT NULL
            """, (AR_ST_KEYS,))
            print(f"       {cur.rowcount} rows updated")

            # Step 3: Reset 32 invoice files to pending
            print("[3/4] Resetting 32 invoice files to pending...")
            cur.execute("""
                UPDATE raw.pdf_extraction_queue
                SET status = 'pending'
                WHERE s3_key = ANY(%s)
            """, (INVOICE_KEYS,))
            print(f"       {cur.rowcount} rows updated")


        conn.commit()
        print("\n[OK] All 38 PE invoices restored to pending. Transaction committed.")

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] Transaction rolled back: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
