# the file will be responsible to read all the converted excel files, map their items, descriptions and customer jobs
# and store them in database.
import pandas as pd
from mpi_backend.config import INVOICE_DOWNLOAD_FOLDER


def process_extracted_data(event):
    converted_files, failed_files = event.retval
    lookup_file = pd.read_excel(f'{INVOICE_DOWNLOAD_FOLDER}/Lookup Sheet.xlsx',
                                                                     sheet_name=[0, 1, 2])
    temp_items= lookup_file[0]
    item_mappings= lookup_file[1]
    customer_job_mappings = lookup_file[2]

    for file in converted_files:
        extracted_data = pd.read_excel(file)
        extracted_data.insert(0, 'Sheet Name', '')
        extracted_data = extracted_data.apply(search_replace, args=(temp_items, item_mappings,), axis=1)

        extracted_customer_job = extracted_data['Customer Job'][0]
        extracted_data['Customer Job'] = get_updated_customer_job(extracted_customer_job, customer_job_mappings)
        pass


def search_replace(row, temp_items, item_mappings):
    item = row['Item']
    description = row['Description']

    # Searching in temp_items
    temp_match = temp_items[temp_items['Original Item Number'] == item]
    if not temp_match.empty:
        row['Item'] = temp_match.iloc[0]['Temporary Item Number']
        row['Description'] = temp_match.iloc[0]['Description']
        row['Sheet Name'] = ''
        return row

    # Searching in item_mappings
    for column in item_mappings.columns:
        mapping_match = item_mappings[item_mappings[column] == item]
        if not mapping_match.empty:
            row['Item'] = mapping_match.iloc[0]['MPI']
            row['Description'] = mapping_match.iloc[0]['Description']
            sheet_name = mapping_match.iloc[0]['Google Sheet Name']
            row['Sheet Name'] = sheet_name
            return row
    return row


def get_updated_customer_job(customer_job, customer_job_mappings):
    updated_job = ''
    filtered_df = customer_job_mappings[customer_job_mappings['Customer Job'] == customer_job]

    if not filtered_df.empty:
        updated_job = filtered_df.iloc[0]['Updated Customer Job']

    return updated_job
