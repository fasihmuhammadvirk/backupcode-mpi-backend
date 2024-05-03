# run as a separate job and will process all the downloaded invoices
import pandas as pd
import os
import shutil
from datetime import datetime, timedelta

from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER, TIMEZONE
from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data
from mpi_backend.utils.pdf_to_excel.cleaning_util import get_files_from_folder
from mpi_backend.utils.pdf_to_excel.abc_opus_services_utils import process_invoice


def convert_invoice(base_folder):
    print("Convert to Excel Background Task Triggered ...")

    if os.path.isdir(f'{INVOICE_DOWNLOAD_FOLDER}/{base_folder}/no_supplier'):  # delete no_supplier directory
        shutil.rmtree(f'{INVOICE_DOWNLOAD_FOLDER}/{base_folder}/no_supplier', ignore_errors=True)

    folders = get_leaf_directories(f'{INVOICE_DOWNLOAD_FOLDER}/{base_folder}')
    folders = [path.replace('/', '\\') for path in folders]
    converted_paths, failed_files = [],[]

    for folder in folders:
        output, failed = convert_and_combine(folder)
        if failed is not None: failed_files.extend(failed)
        if output is not None: converted_paths.extend(output)

    return converted_paths, failed_files


def get_leaf_directories(root_dir):
    leaf_dirs = []
    for dirpath, dirnames, files in os.walk(root_dir):
        if not dirnames:  # This is a leaf directory if it contains no subdirectories
            leaf_dirs.append(dirpath)
    return leaf_dirs


def convert_and_combine(all_files):

    folder_path = all_files # folder path will be embedded in excel file
    all_files = get_files_from_folder(all_files)
    all_output_paths = []
    failed_input_paths = []

    for filepath in all_files:
        try:
            print(filepath)
            filename = filepath.split("/")[-1]
            if not filename[-4:].lower() == ".pdf":
                print("Please only select PDF files")
                continue

            outputpath = filepath.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx")

            if filepath.count('/') ==3 : supplier_sub_stirng = filepath.split("/")[-2] # for upload invoice
            else : supplier_sub_stirng = filepath.split("/")[3]  # for downloaded invoice through background task

            if "BMW Plumbing Supplies" in supplier_sub_stirng: supplier = 'BMW Plumbing Supplies'
            elif "World Wide Plumbing" in supplier_sub_stirng:supplier = 'World Wide Plumbing'
            elif 'Y & S Plumbing Supply' in supplier_sub_stirng:supplier = 'Y & S Plumbing Supply'
            elif 'Supreme Plumbing Supply' in supplier_sub_stirng:supplier = 'Supreme Plumbing Supply'
            elif 'Pyramid Plumbing' in supplier_sub_stirng:supplier = 'Pyramid Plumbing'
            elif 'Park Plumbing Supply' in supplier_sub_stirng:supplier = 'Park Plumbing Supply'
            elif 'ABC Opus Services' in supplier_sub_stirng:supplier = 'ABC Opus Services'
            elif "FW Webb Plumbing Supply" in supplier_sub_stirng:supplier = "FW Webb Plumbing Supply"
            else: continue

            if supplier == 'ABC Opus Services':
                process_invoice(filepath,outputpath)
                continue

            splited_filepaths = extract_data(filepath, outputpath, supplier)
            all_output_paths.append(filepath)

            # integrating the flow of multiple invoices in single file
            if splited_filepaths: # check for splited file list is not empty
                for splitFile_path in splited_filepaths:
                    output_splited_filepath= splitFile_path.replace(".pdf", ".xlsx").replace(".PDF", ".xlsx")
                    returned_paths = extract_data(splitFile_path, output_splited_filepath, supplier)
                    all_output_paths.append(splitFile_path)

        except Exception as e:
            print(f"File Conversion Failed becasue : {e}")
            failed_input_paths.append(filepath)

    return all_output_paths, failed_input_paths
