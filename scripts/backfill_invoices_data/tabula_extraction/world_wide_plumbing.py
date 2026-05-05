"""
World Wide Plumbing invoice extraction using tabula.

This module provides the extraction function for World Wide Plumbing invoices.
"""

import tabula
import pandas as pd
from .cleaning_util import clean_individual_table, split_multiple_invoices
from .extraction_util import (
    extract_job_info,
    extract_invoice_info,
    extract_tax_etc,
    extract_po,
    extract_buyer,
    check_for_unique_invoices,
)
from .formatting_util import save_final_data
from .supremePlumbing_uitl import get_pages

# Area and column configurations for World Wide Plumbing
REGULAR_AREA = (290, 20, 290 + 420, 20 + 570)
LAST_PAGE_AREA = (290, 20, 290 + 375, 20 + 570)
WWPS_COLUMNS = [20, 38, 68, 98, 128, 240, 375, 428, 470, 530]


def process_invoice(filename: str, output_path: str):
    """
    Extract and process World Wide Plumbing invoice data.
    
    Args:
        filename: Path to the PDF invoice file.
        output_path: Path to save the extracted Excel file.
        
    Returns:
        List of split file paths if invoice was split, empty list otherwise.
    """
    supplier = "World Wide Plumbing"
    
    # Check for multiple invoices in single file
    if get_pages(filename) > 1 and check_for_unique_invoices(filename, supplier):
        split_filepath = split_multiple_invoices(filename, supplier)
        return split_filepath

    # Extract tables from PDF
    tables = tabula.read_pdf(
        filename,
        pages='all',
        area=REGULAR_AREA,
        guess=False,
        stream=True,
        columns=WWPS_COLUMNS
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
        pages=len(tables),
        area=LAST_PAGE_AREA,
        guess=False,
        stream=True,
        columns=WWPS_COLUMNS
    )

    last_table = clean_individual_table(last_tables[0], page=-1, check_row_count=True)
    finalized_tables.append(last_table)

    # Combine all tables
    final_df = pd.concat(finalized_tables).reset_index(drop=True)
    final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Qty BO", "Cost", "Amount"])

    # Extract metadata
    job_name = extract_job_info(filename)
    invoice_num, invoice_date = extract_invoice_info(filename)
    financial_data = extract_tax_etc(filename)
    buyer = extract_buyer(filename)
    po = extract_po(filename)

    # Add tax rows
    for i, item in enumerate(financial_data):
        if i == 0:
            tax_row = ["10 Materials", item.capitalize(), "", "", "", financial_data[item]]
            if final_df['Qty BO'].sum() == 0:
                final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Cost", "Amount"])
                tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            final_df.loc[len(final_df)] = tax_row
        else:
            tax_row = ["10 Materials", item.capitalize(), "", "", financial_data[item]]
            if "Qty BO" in final_df:
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
    final_df['Customer Job'] = job_name
    final_df['Bill'] = "Bill"
    final_df["Vendor"] = supplier
    final_df["Class"] = ""
    final_df["Memo"] = ""
    final_df["Buyer"] = buyer

    # Reorder columns if Qty BO exists
    if "Qty BO" in final_df:
        final_df = final_df.reindex(columns=[
            "Item", "Description", "Qty", "Cost", "Amount", "Date",
            "Ref NO", "PO #", "Customer Job", "Bill", "Vendor", "Class", "Memo", "Buyer"
        ])

    save_final_data(final_df, supplier, output_path)

    return []

