import os
import re
from datetime import datetime
import fitz
import sys
import tabula
import pandas as pd
import logging
logger = logging.getLogger(__name__)
from mpi_backend.utils.pdf_to_excel.cleaning_util import clean_individual_table,split_multiple_invoices
from mpi_backend.utils.pdf_to_excel.extraction_util import extract_job_info, extract_invoice_info, extract_tax_etc, extract_po, extract_buyer,check_for_unique_invoices, read_invoice
from mpi_backend.utils.pdf_to_excel.formatting_util import save_final_data
from mpi_backend.utils.pdf_to_excel.supremePlumbing_uitl import extract_supremePlumbing_data,get_pages
from mpi_backend.utils.pdf_to_excel.gotham_supply import process_invoice
from mpi_backend.utils.pdf_to_excel import bmw_old
from mpi_backend.utils.pdf_to_excel import ys_old
from mpi_backend.utils.pdf_to_excel import web_co_supply
from mpi_backend.utils.pdf_to_excel import flow_mark
from mpi_backend.utils.pdf_to_excel import plumbing_exchange
from mpi_backend.utils.pdf_to_excel import file_preprocess
from mpi_backend.utils.pdf_to_excel import af_supply
from mpi_backend.utils.pdf_to_excel import lion_havac

regular_area = (290, 20, 290+415, 20+570)
last_page_area = (290, 20, 290+375, 20+570)
wwps_columns = [20, 38, 68, 98, 128, 240, 375, 428, 470, 530]
bmw_columns = [20, 38, 68, 98, 128, 221, 411, 434, 512]
pyramid_columns = [20, 38, 68, 98, 128, 193,390,415,487, 530]

single_invoice_supplier = ['Gotham Plumbing Supply'] # whoose invoices we donot need to split
def extract_data(filename, output_path, supplier):

    # integrating the flow of multiple invoices in single file
    if get_pages(filename) > 1 and supplier not in single_invoice_supplier and check_for_unique_invoices(filename,supplier):
        splited_filepath = split_multiple_invoices(filename, supplier)
        return splited_filepath

    if supplier == 'World Wide Plumbing':
        tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True,
                                 columns=wwps_columns)
    elif supplier == "BMW Plumbing Supplies" and 'Project' in read_invoice(filename):
        bmw_old.process_invoice(filename, output_path)
        return

    elif supplier == "Y & S Plumbing Supply" and "Y&S Plumbing & Heating Supply Inc." in read_invoice(filename):
        ys_old.process_invoice(filename, output_path) # credit memo flow for Y&S
        return

    elif supplier == "BMW Plumbing Supplies" or supplier == "Y & S Plumbing Supply" or supplier == "Park Plumbing Supply":
        tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True,
                                 columns=bmw_columns)
    elif supplier == "Pyramid Plumbing":
        tables = tabula.read_pdf(filename, pages='all', area=regular_area, guess=False, stream=True,
                                 columns=pyramid_columns)
    elif supplier == "Supreme Plumbing Supply":
        extract_supremePlumbing_data(filename, output_path)
        return # stop normal flow execution here
    elif supplier == "Gotham Plumbing Supply":
        process_invoice(filename, output_path)
        return
    elif supplier == "FW Webb Plumbing Supply":
        web_co_supply.process_invoice(filename, output_path)
        return
    elif supplier == "Flow Mark Plumbing Supply":
        flow_mark.process_invoice(filename, output_path)
        return
    elif supplier == "Plumbing Exchange":
        plumbing_exchange.process_invoice(filename, output_path)
        return
    elif supplier == 'AF Supply':
        af_supply.process_invoice(filename, output_path)
        return
    elif supplier == 'Lion Hvac Supplies':
        lion_havac.process_invoice(filename, output_path)
        return
    else:
        logger.info(f'Invalid Supplier -> {supplier} for file -> {filename}.Skipping Invoice.')
        return "Please enter a valid supplier"

    finalized_tables = []
    is_camelot = False
    # FIX--> flow for double-spaced invoices, process them with camelot library
    if (supplier == "BMW Plumbing Supplies"
            and {'L N', 'Q N T Y.2', 'P R O D U C T'}.issubset(tables[0].columns)):
        tables = file_preprocess.process_bmw_with_camelot(filename)
        is_camelot = True  # will track if the file is processed with camelot, because we need to reprocess the files again

    if len(tables) > 1:
        for i in range(len(tables) - 1):
            current_table = tables[i]
            if is_camelot:
                current_table = clean_individual_table(current_table, page=-1,
                                                       check_row_count=False)  # setting any value of page other than one
            else:
                current_table = clean_individual_table(current_table, page=i + 1, check_row_count=True)
            if current_table is not None:
                finalized_tables.append(current_table)
    if supplier == 'World Wide Plumbing':
        last_tables = tabula.read_pdf(filename, pages=len(tables), area=last_page_area, guess=False, stream=True,
                                      columns=wwps_columns)
    elif supplier == "BMW Plumbing Supplies" or supplier == "Y & S Plumbing Supply" or supplier == "Park Plumbing Supply":
        if is_camelot:  # if files are processed by camelot, the extracted table will work for last page as well
            last_tables = tables
        else:
            last_tables = tabula.read_pdf(filename, pages=len(tables), area=last_page_area, guess=False, stream=True,
                                          columns=bmw_columns)
    elif supplier == "Pyramid Plumbing":
        last_tables = tabula.read_pdf(filename, pages=len(tables), area=last_page_area, guess=False, stream=True,
                                      columns=pyramid_columns)

    if is_camelot:
        last_table = clean_individual_table(last_tables[-1], page=-1)
    else:
        last_table = clean_individual_table(last_tables[0], page=-1, check_row_count=True)
    finalized_tables.append(last_table)

    final_df = pd.concat(finalized_tables).reset_index(drop=True)
    final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Qty BO", "Cost", "Amount"])

    job_name = extract_job_info(filename)
    invoice_num, invoice_date = extract_invoice_info(filename)
    financial_data = extract_tax_etc(filename)
    po = extract_po(filename)
    buyer = extract_buyer(filename)

    if is_camelot and job_name.count(" ") > 6:
        # trigger if customer_job is still double spaced and file was processed with camelot
        job_name = file_preprocess.extract_customer_job_double_spaced_invoice(filename)

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

    # Robust fallback for invoice number and date when extraction is empty
    try:
        with fitz.open(filename) as doc:
            pdf_text = "\n".join(page.get_text("text") for page in doc)
    except Exception:
        pdf_text = ""

    if not invoice_num or str(invoice_num).strip() == "":
        patterns = (
            r"Invoice\s*#\s*[:\-]?\s*([A-Za-z0-9\-\./]+)",
            r"Invoice\s*No\.?\s*[:\-]?\s*([A-Za-z0-9\-\./]+)",
            r"INVOICE\s*NO\.?\s*[:\-]?\s*([A-Za-z0-9\-\./]+)",
            r"INVOICE\s*#\s*[:\-]?\s*([A-Za-z0-9\-\./]+)",
            r"INVOICE\s*NUMBER\s*[:\-]?\s*([A-Za-z0-9\-\./]+)",
        )
        for pat in patterns:
            m = re.search(pat, pdf_text, flags=re.IGNORECASE)
            if m:
                invoice_num = m.group(1).strip()
                break

    if not invoice_date or str(invoice_date).strip() == "":
        # Prefer label-adjacent date
        label = re.search(r"Invoice\s*Date\s*[:\-]?\s*(.+)", pdf_text, flags=re.IGNORECASE)
        candidate = None
        if label:
            candidate = label.group(1).splitlines()[0].strip()
        if not candidate:
            dm = re.search(r"(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})", pdf_text)
            if dm:
                candidate = dm.group(1)
        if candidate:
            normalized = None
            for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(candidate, fmt)
                    normalized = dt.strftime("%m/%d/%Y")
                    break
                except ValueError:
                    continue
            invoice_date = normalized or candidate

    final_df['Date'] = invoice_date
    final_df['Ref NO'] = str(invoice_num)
    final_df['PO #'] = po

    # Fallback for job name if extraction failed
    if not job_name or len(str(job_name).strip()) < 3:
        # Try to find address block near common markers
        lines = [ln.strip() for ln in (pdf_text or '').splitlines() if ln.strip()]
        markers = (
            r"^ship\s*to:?$",
            r"^shipping\s*address:?$",
            r"^job\s*address:?$",
            r"^project:?$",
        )
        job_lines = []
        for idx, line in enumerate(lines):
            if any(re.match(p, line, flags=re.IGNORECASE) for p in markers):
                for nxt in lines[idx+1: idx+6]:
                    if re.search(r"invoice|bill\s*to|phone|fax|date|terms", nxt, re.IGNORECASE):
                        break
                    job_lines.append(nxt)
                break
        if not job_lines:
            # Choose longest address-like block in top area
            block = []
            blocks = []
            for ln in lines[:40]:
                if re.search(r"[A-Za-z].*\d|\d.*[A-Za-z]", ln):
                    block.append(ln)
                else:
                    if block:
                        blocks.append(" ".join(block))
                        block = []
            if block:
                blocks.append(" ".join(block))
            if blocks:
                job_name = max(blocks, key=len)[:250]
        else:
            job_name = " ".join(job_lines)[:250]

    memo = ""
    final_df['Customer Job'] = job_name

    final_df['Bill'] = "Bill"
    final_df["Vendor"] = supplier
    final_df["Class"] = ""
    final_df["Memo"] = memo
    final_df["Buyer"] = buyer

    if "Qty BO" in final_df:
        final_df = final_df.reindex(columns=["Item", "Description", "Qty", "Cost", "Amount", "Date",
            "Ref NO", "PO #", "Customer Job", "Bill", "Vendor", "Class", "Memo", "Buyer"])

    save_final_data(final_df, supplier, output_path)

    return []
