import pandas as pd


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
        'buyer': 'Buyer'
    }

    items_dict = [item.__dict__ for item in items]
    df = pd.DataFrame(items_dict).rename(columns=columns_mapping)
    df = df[list(columns_mapping.values())]

    return df
