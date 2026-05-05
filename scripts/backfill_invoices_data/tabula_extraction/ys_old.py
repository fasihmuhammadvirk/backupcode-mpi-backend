import pandas as pd
import numpy as np
import os
import re
import fitz
import tabula
from .formatting_util import save_final_data
from .cleaning_util import clean_individual_table
from .extraction_util import extract_invoice_info, extract_tax_etc, extract_po, extract_buyer
from .supremePlumbing_uitl import get_pages

# Distribution-style configurations (same as World Wide Plumbing)
REGULAR_AREA = (290, 20, 290 + 420, 20 + 570)
LAST_PAGE_AREA = (290, 20, 290 + 375, 20 + 570)
DIST_COLUMNS = [20, 38, 68, 98, 128, 240, 375, 428, 470, 530]

SUPPLIER = "Y & S Plumbing Supplies"


def process_invoice(filename, output_path):
    """Process Y & S Plumbing invoice using distribution-style extraction."""
    doc = fitz.open(filename)
    raw_text = doc[0].get_text()
    doc.close()
    
    # Extract tables from PDF
    tables = tabula.read_pdf(
        filename,
        pages='all',
        area=REGULAR_AREA,
        guess=False,
        stream=True,
        columns=DIST_COLUMNS
    )

    finalized_tables = []

    # Process all pages except the last
    if len(tables) > 1:
        for i in range(len(tables) - 1):
            current_table = tables[i]
            current_table = clean_individual_table(current_table, page=i + 1, check_row_count=True)
            if current_table is not None:
                finalized_tables.append(current_table)

    # Process last page with different area
    last_tables = tabula.read_pdf(
        filename,
        pages=len(tables) if tables else 1,
        area=LAST_PAGE_AREA,
        guess=False,
        stream=True,
        columns=DIST_COLUMNS
    )

    if last_tables:
        last_table = clean_individual_table(last_tables[0], page=-1, check_row_count=True)
        if last_table is not None:
            finalized_tables.append(last_table)

    if not finalized_tables:
        raise ValueError(f"No invoice items could be extracted from {filename}")

    # Combine all tables
    final_df = pd.concat(finalized_tables).reset_index(drop=True)
    final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Qty BO", "Cost", "Amount"])

    # Extract metadata
    invoice_num, invoice_date = extract_invoice_info(filename)
    financial_data = extract_tax_etc(filename)
    buyer = extract_buyer(filename)
    po = extract_po(filename)
    
    # Extract customer job from raw text
    customer_job = ''
    hit = re.search(r'Ship To\s*\n(.*?)\n', raw_text, re.DOTALL)
    if hit:
        customer_job = hit.group(1).strip()

    # Add tax rows
    for i, item in enumerate(financial_data):
        if i == 0:
            tax_row = ["10 Materials", item.capitalize(), "", "", "", financial_data[item]]
            if 'Qty BO' in final_df.columns and final_df['Qty BO'].sum() == 0:
                final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Cost", "Amount"])
                tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            final_df.loc[len(final_df)] = tax_row
        else:
            tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            if "Qty BO" in final_df.columns:
                tax_row = ["10 Materials", item.capitalize(), "", "", "", financial_data[item]]
                qty_bo_sum = pd.to_numeric(final_df['Qty BO'], errors='coerce').sum()
                if qty_bo_sum == 0:
                    final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Cost", "Amount"])
                    tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            final_df.loc[len(final_df)] = tax_row

    # Add metadata columns
    final_df['Date'] = invoice_date
    final_df['Ref NO'] = str(invoice_num)
    final_df['PO #'] = po
    final_df['Customer Job'] = customer_job
    final_df['Bill'] = "Bill"
    final_df["Vendor"] = SUPPLIER
    final_df["Class"] = ""
    final_df["Memo"] = ""
    final_df["Buyer"] = buyer

    # Reorder columns if Qty BO exists
    if "Qty BO" in final_df.columns:
        final_df = final_df.reindex(columns=[
            "Item", "Description", "Qty", "Cost", "Amount", "Date",
            "Ref NO", "PO #", "Customer Job", "Bill", "Vendor", "Class", "Memo", "Buyer"
        ])

    save_final_data(final_df, SUPPLIER, output_path)
    return []
