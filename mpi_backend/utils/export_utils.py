import pandas as pd
from datetime import datetime

def convert_items_to_dataframe(items):
    columns_mapping = {
        'item': 'Item',
        'description': 'Description',
        'qty': 'Qty',
        'cost': 'Cost',
        'amount': 'Amount',
        'date': 'Date',
        'ref_no': 'Ref NO',
        'po_number': 'PO #',
        'customer_job': 'Customer Job',
        'bill': 'Bill',
        'vendor': 'Vendor',
        'class_': 'Class',
        'memo': 'Memo',
        'buyer': 'Buyer',
        "filename": "Filename",
        "sheet_name": "Sheet Name",
        "mpi_item": "MPI Item Code",
        "mpi_description": "MPI Description",
        "date_added": "Date Added"
    }

    items_dict = [item.__dict__ for item in items]
    df = pd.DataFrame(items_dict).rename(columns=columns_mapping)
    df = df[list(columns_mapping.values())]

    date_columns = ["Date", "Date Added"]  # Adjust this list if more date columns exist
    for col in date_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x.strftime("%m-%d-%Y") if isinstance(x, datetime) else x)

    return df


# because of circular dependency, had to duplicate code here, will find a better way soon (hopefully)
def extract_supplier_id(file_path):
    company_codes = {
        "BMW Plumbing Supplies": 1,
        "World Wide Plumbing": 2,
        "Y & S Plumbing Supply": 3,
        "Supreme Plumbing Supply": 4,
        "Pyramid Plumbing": 5,
        "ABC Opus Services": 6,
        "Park Plumbing Supply": 7,
        "Gotham Plumbing Supply": 8,
        "FW Webb Plumbing Supply": 9,
        "Flow Mark Plumbing Supply": 10
    }
    for company, code in company_codes.items():
        if company in file_path:
            return code, company
    return 1 # need to return some default supplier
