import camelot
import os
import numpy as np

dll_dir = 'C:\Program Files\gs\gs10.04.0'
os.environ['PATH'] += ';' + dll_dir
table_area = ['19,506,589,85']
columns = ['21,36,67,97,128,228,409,434,511']


def process_bmw_with_camelot(filepath):
    extracted_tables = []
    tables = camelot.read_pdf(
        filepath,
        flavor='stream',
        table_areas=table_area,
        columns=columns,
        split_text=True,
        pages='all'
    )

    for table in tables:
        extracted_table = table.df
        extracted_table.drop(extracted_table.columns[[0,2,7]], axis=1, inplace=True)
        extracted_table.columns = ['LN', 'QNTY.1', 'QNTY.2', 'PRODUCT', 'Unnamed: 1', 'NET', 'EXTENSION']

        extracted_table['LN'].replace(['', 'LN'], np.nan, inplace=True) # for dropping garbage rows
        extracted_table = extracted_table.dropna(subset=['LN'])

        extracted_tables.append(extracted_table)

    return extracted_tables


def extract_customer_job_double_spaced_invoice(filepath):
    tables = camelot.read_pdf(
        filepath,
        flavor='stream',
        table_areas=['296,675,616,592'],
        split_text=True
    )
    try:
        customer_job = tables[0].df[0][1]
    except:
        customer_job = ''

    return customer_job

