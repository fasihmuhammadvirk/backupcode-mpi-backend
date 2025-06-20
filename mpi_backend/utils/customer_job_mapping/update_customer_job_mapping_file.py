import pandas as pd
import json
import logging

# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def update_customer_job_mappings_json(excel_file, json_file="mpi_backend/storage/fixtures/customer-job-mapping.json"):
    """
    Update the customer job mappings JSON file based on the provided Excel file.

    This function reads an Excel file containing customer job mappings, processes
    the data to extract relevant columns, and updates a JSON file with any new
    mappings found. The Excel file must contain 'Customer Job' and 'Updated Customer
    Job' columns. The JSON file is updated only with mappings that are not already
    present.

    Parameters:
        excel_file (str): Path to the Excel file containing the mappings.
        json_file (str): Path to the JSON file to be updated. Defaults to
                         "../../storage/fixtures/customer-job-mapping.json".

    Returns:
        int: The number of new mappings added to the JSON file.

    Raises:
        FileNotFoundError: If the Excel file is not found or unreadable.
        ValueError: If the Excel file is missing required columns or if the JSON
                    file is corrupted.
        Exception: If there is a failure in processing the Excel file or writing
                   to the JSON file.
    """
    try:
        # Step 1: Load the Excel sheet, skip first 3 rows to reach the real header
        df_raw = pd.read_excel(excel_file, sheet_name="Mappings", skiprows=3)

        # Step 2: Strip all column names of whitespace
        df_raw.columns = df_raw.columns.str.strip()

        # Step 3: Show column names for verification (optional)
        logger.info("Columns found: %s", df_raw.columns.tolist())

        # Step 4: Select and clean relevant columns
        try:
            df_cleaned = df_raw[['Customer Job', 'Updated Customer Job']].dropna()
        except KeyError as ke:
            raise ValueError("Excel file must contain 'Customer Job' and 'Updated Customer Job' columns.") from ke

        # Step 5: Rename columns for consistency
        df_cleaned = df_cleaned.rename(columns={
            'Customer Job': 'customer_job',
            'Updated Customer Job': 'updated_customer_job'
        })

        df = df_cleaned

    except FileNotFoundError:
        raise FileNotFoundError("Excel file not found or unreadable.")
    except ValueError as ve:
        raise ve
    except Exception as e:
        raise Exception(f"Failed to process Excel file: {str(e)}")

    # Load existing data from JSON
    try:
        with open(json_file, 'r') as f:
            existing_data = json.load(f)
    except FileNotFoundError:
        existing_data = []
    except json.JSONDecodeError:
        raise ValueError("Existing JSON file is corrupted or contains invalid JSON.")

    # Create a set of existing pairs for fast lookup
    existing_set = {(item['customer_job'], item['updated_customer_job']) for item in existing_data}

    # Collect only new mappings
    new_entries = []
    for _, row in df.iterrows():
        logger.debug("Processing row: %s", row)
        customer_job = str(row['customer_job']).strip()
        updated_job = str(row['updated_customer_job']).strip()
        if (customer_job, updated_job) not in existing_set:
            new_entries.append({
                "customer_job": customer_job,
                "updated_customer_job": updated_job
            })

    # Update the existing list
    if new_entries:
        try:
            with open(json_file, 'w') as f:
                json.dump(existing_data + new_entries, f, indent=4)
        except Exception as e:
            raise Exception(f"Failed to write to JSON file: {str(e)}")

        logger.info(" Added %d new mappings.", len(new_entries))
        return len(new_entries)
    else:
        logger.info(" No new mappings to add. JSON file is already up to date.")
        return len(new_entries)


# Run the function
if __name__ == "__main__":
    excel_file = "/Users/fasihmuhammadvirk/Downloads/mappings.xlsm"
    json_file = "mpi_backend/storage/fixtures/customer-job-mapping.json"
    update_customer_job_mappings_json(excel_file, json_file)
