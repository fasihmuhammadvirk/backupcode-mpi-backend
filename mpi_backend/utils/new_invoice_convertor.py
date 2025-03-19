# run as a separate job and will process all the downloaded invoices
import pandas as pd
import os
import shutil
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER, TIMEZONE
from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data
from mpi_backend.utils.pdf_to_excel.cleaning_util import get_files_from_folder
from mpi_backend.utils.pdf_to_excel.abc_opus_services_utils import process_invoice


def convert_invoice(base_folder):
    """Process invoices with proper path resolution"""
    logger.info("Convert to Excel Background Task Triggered ...")
    converted_paths = []
    failed_files = []

    print(base_folder)
    print(INVOICE_DOWNLOAD_FOLDER)

    try:
        base_path = base_folder
        # Resolve base path using pathlib
        # base_path = (Path(INVOICE_DOWNLOAD_FOLDER) / base_folder).resolve()
        logger.info(f"Resolved base path: {base_path}")

        if not base_path.exists():
            logger.error(f"Base directory does not exist: {base_path}")
            return [], []

        # Handle no_supplier directory
        no_supplier_path = base_path / "no_supplier"
        if no_supplier_path.exists():
            logger.info(f"Removing no_supplier directory: {no_supplier_path}")
            shutil.rmtree(no_supplier_path, ignore_errors=True)

        # Get leaf directories
        leaf_dirs = get_leaf_directories(base_path)
        logger.info(f"Found {len(leaf_dirs)} leaf directories")

        # Process directories
        for folder in leaf_dirs:
            output, failed = convert_and_combine(folder)
            converted_paths.extend(output)
            failed_files.extend(failed)

        return converted_paths, failed_files

    except Exception as error:
        logger.error(f"Fatal error in convert_invoice: {str(error)}")
        return [], []


def get_leaf_directories(root_dir):
    leaf_dirs = []
    for dirpath, dirnames, files in os.walk(root_dir):
        logger.info("Scanning Directory")
        if not dirnames:  # This is a leaf directory if it contains no subdirectories
            leaf_dirs.append(dirpath)
    return leaf_dirs


def convert_and_combine(all_files):
    folder_path = all_files  # folder path will be embedded in excel file
    all_files = get_files_from_folder(all_files)
    all_output_paths = []
    failed_input_paths = []

    for filepath in all_files:
        try:
            print(filepath)
            filename = filepath.split("/")[-1]
            if not filename[-4:].lower() == ".pdf":
                logger.info(f"Invalid File >> {filename}")
                continue

            outputpath = filepath.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx")

            if filepath.count('/') == 3:
                supplier_sub_stirng = filepath.split("/")[-2]  # for upload invoice
            else:
                supplier_sub_stirng = filepath.split("/")[3]  # for downloaded invoice through background task

            if "BMW Plumbing Supplies" in supplier_sub_stirng:
                supplier = 'BMW Plumbing Supplies'
            elif "World Wide Plumbing" in supplier_sub_stirng:
                supplier = 'World Wide Plumbing'
            elif 'Y & S Plumbing Supply' in supplier_sub_stirng:
                supplier = 'Y & S Plumbing Supply'
            elif 'Supreme Plumbing Supply' in supplier_sub_stirng:
                supplier = 'Supreme Plumbing Supply'
            elif 'Pyramid Plumbing' in supplier_sub_stirng:
                supplier = 'Pyramid Plumbing'
            elif 'Park Plumbing Supply' in supplier_sub_stirng:
                supplier = 'Park Plumbing Supply'
            elif 'ABC Opus Services' in supplier_sub_stirng:
                supplier = 'ABC Opus Services'
            elif "FW Webb Plumbing Supply" in supplier_sub_stirng:
                supplier = "FW Webb Plumbing Supply"
            elif "Flow Mark Plumbing Supply" in supplier_sub_stirng:
                supplier = "Flow Mark Plumbing Supply"
            elif "Plumbing Exchange" in supplier_sub_stirng:
                supplier = "Plumbing Exchange"
            elif "AF Supply" in supplier_sub_stirng:
                supplier = "AF Supply"
            elif "Lion Hvac Supplies" in supplier_sub_stirng:
                supplier = "Lion Hvac Supplies"
            else:
                continue

            if supplier == 'ABC Opus Services':
                process_invoice(filepath, outputpath)
                logger.info(f"ABC Opus: Downloaded at -> {outputpath}")
                logger.warning(f"Skipping ABC Opus file for Processing")
                continue

            splited_filepaths = extract_data(filepath, outputpath, supplier)
            all_output_paths.append(filepath)

            # integrating the flow of multiple invoices in single file
            if splited_filepaths:  # check for splited file list is not empty
                for splitFile_path in splited_filepaths:
                    output_splited_filepath = splitFile_path.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx")
                    returned_paths = extract_data(splitFile_path, output_splited_filepath, supplier)
                    all_output_paths.append(splitFile_path)

        except Exception as e:
            logger.error(f"File ->{filepath.split('/')[-1]} Conversion Failed because : {e}")
            failed_input_paths.append(filepath)

    for file_path in all_files:
        if all_files != 0 and file_path not in all_output_paths:
            if file_path.count('/') == 3:
                supplier_sub_stirng = file_path.split("/")[-2]  # for upload invoice
            else:
                supplier_sub_stirng = file_path.split("/")[3]  # for downloaded invoice through background task

            if 'ABC Opus Services' in supplier_sub_stirng:
                continue

            failed_input_paths.append(filepath)

    return all_output_paths, failed_input_paths


def detect_supplier(file_path):
    """Improved supplier detection using path components"""
    try:
        # Walk up the directory tree to find supplier
        for parent in file_path.parents:
            parent_name = parent.name.lower()

            if 'bmw' in parent_name:
                return 'BMW Plumbing Supplies'
            if 'world wide' in parent_name:
                return 'World Wide Plumbing'
            if 'y&s' in parent_name or 'y and s' in parent_name:
                return 'Y & S Plumbing Supply'
            if 'supreme' in parent_name:
                return 'Supreme Plumbing Supply'
            if 'pyramid' in parent_name:
                return 'Pyramid Plumbing'
            if 'park plumbing' in parent_name:
                return 'Park Plumbing Supply'
            if 'opus' in parent_name:
                return 'ABC Opus Services'
            if 'webb' in parent_name:
                return 'FW Webb Plumbing Supply'
            if 'flow mark' in parent_name:
                return 'Flow Mark Plumbing Supply'
            if 'exchange' in parent_name:
                return 'Plumbing Exchange'
            if 'af supply' in parent_name:
                return 'AF Supply'
            if 'lion' in parent_name:
                return 'Lion Hvac Supplies'

        logger.warning(f"No supplier detected in path hierarchy: {file_path}")
        return None

    except Exception as error:
        logger.error(f"Supplier detection failed: {str(error)}")
        return None
