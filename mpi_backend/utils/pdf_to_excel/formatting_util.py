import pandas as pd
from datetime import datetime
import os
# import openpyxl


def save_final_data(final_df, supplier, output_path):
    writer = pd.ExcelWriter(output_path, engine='xlsxwriter')
    
    num_cols = len(final_df.columns)
    
    final_df.to_excel(writer, index=False, sheet_name='Table 1')

    workbook = writer.book
    worksheet = writer.sheets['Table 1']

    worksheet.set_column('A:A', 20)
    worksheet.set_column('B:B', 35)
    worksheet.set_column('C:C', 7)
    worksheet.set_column('D:D', 10)
    worksheet.set_column('E:E', 10)
    worksheet.set_column('F:F', 11)
    worksheet.set_column('G:G', 10)
    worksheet.set_column('H:H', 7)
    worksheet.set_column('I:I', 35)
    worksheet.set_column('J:J', 5)
    worksheet.set_column('K:K', 25)
    worksheet.set_column('L:L', 10)
    worksheet.set_column('M:M', 15)
    worksheet.set_column('N:N', 15)

    if num_cols > 14: # data-review tab export
        worksheet.set_column('O:S', 20)

    columns_format = workbook.add_format({'bg_color': 'yellow', 'font_color': 'red'})
    bolded_column_format = workbook.add_format({'bold': True})

    column_range = "A1:N1" if num_cols <= 14 else "A1:S1"
    bolded_range1 = "F2:H"+str(len(final_df)+1)
    bolded_range2 = "K2:K"+str(len(final_df)+1)
    # elif num_cols == 14:
    #     column_range = "A1:N1"
    #     bolded_range1 = "G2:I"+str(len(final_df)+1)
    #     bolded_range2 = "L2:L"+str(len(final_df)+1)


    worksheet.conditional_format(column_range, {'type': 'cell',
                                            'criteria': '>=',
                                            'value': '0',
                                            'format': columns_format})
    worksheet.conditional_format(column_range, {'type': 'cell',
                                            'criteria': '<',
                                            'value': '0',
                                            'format': columns_format})

    worksheet.conditional_format(bolded_range1, {'type': 'cell',
                                            'criteria': '>=',
                                            'value': '0',
                                            'format': bolded_column_format})
    worksheet.conditional_format(bolded_range1, {'type': 'cell',
                                            'criteria': '<',
                                            'value': '0',
                                            'format': bolded_column_format})

    worksheet.conditional_format(bolded_range2, {'type': 'cell',
                                            'criteria': '>=',
                                            'value': '0',
                                            'format': bolded_column_format})
    worksheet.conditional_format(bolded_range2, {'type': 'cell',
                                            'criteria': '<',
                                            'value': '0',
                                            'format': bolded_column_format})


    writer.save()


def save_opus_services(extracted_data, output_path):
    writer = pd.ExcelWriter(output_path, engine='xlsxwriter')
    num_cols = len(extracted_data.columns)
    number_rows = len(extracted_data.index) + 1
    extracted_data.to_excel(writer, index=False, header= False, sheet_name='Table 1')
    workbook = writer.book
    worksheet = writer.sheets['Table 1']

    right_align_format = workbook.add_format()
    right_align_format.set_align('right')
    center_format = workbook.add_format()
    center_format.set_align('center')

    worksheet.set_column('A:A', 1)
    worksheet.set_column('B:B', 35)
    worksheet.set_column('C:C', 20)
    worksheet.set_column('D:D', 8, right_align_format)
    worksheet.set_column('E:E', 10, right_align_format)
    worksheet.set_column('F:F', 15, right_align_format)
    worksheet.set_column('G:G', 1)
    worksheet.set_column('H:J', 15)
    worksheet.set_column('K:K', 1)
    worksheet.set_column('L:N', 15)
    worksheet.set_column('O:O', 1)
    worksheet.set_column('P:R', 15)

    date_invoice_num_format = workbook.add_format({'bg_color': '#EBF1DE', 'font_color': 'Automatic', 'bold': True})
    date_invoice_num_format.set_align('center')
    header_format = workbook.add_format({'bg_color': '#F4DBDA', 'font_color': 'Automatic', 'bold': True,
                                                   'align': 'center', 'border': 1})
    date_format = workbook.add_format({'bg_color': '#DDEBF7', 'font_color': 'Automatic', 'bold': True,
                                         'align': 'center', 'border': 1})
    alternate_row_color_format = workbook.add_format({'bg_color': '#DDDDDD'})
    address_format =  workbook.add_format({'bg_color': '#DA9694', 'border': 1})
    date_section_format =  workbook.add_format({'bg_color': '#95B3D7', 'border': 1})
    amount_format =  workbook.add_format({'bg_color': '#F4DBDA', 'border': 1})

    column_range = "B1:F1"
    date_invoice_num_range = "B2:C3"

    worksheet.conditional_format(date_invoice_num_range, {'type': 'cell',
                                                 'criteria': '>=',
                                                 'value': '0',
                                                 'format': date_invoice_num_format})
    draw_frame_border(workbook,worksheet,1,1,2,2)
    worksheet.set_row(1, None, center_format)
    worksheet.set_row(2, None, center_format)

    worksheet.conditional_format("$B$1:$F$%d" % (number_rows),
                                 {"type": "formula",
                                  "criteria": '=INDIRECT("C"&ROW())="Timetable"',
                                  "format": header_format
                                  })

    # worksheet.conditional_format("$B$1:$B$%d" % (number_rows),
    #                              {"type": "formula",
    #                               "criteria": '=INDIRECT("E"&ROW())="0.00"',
    #                               "format": date_format
    #                               })

    rows_with_total = extracted_data[
        extracted_data.applymap(lambda x: True if isinstance(x, str) and 'total' in x.lower() else False).any(1)].index.to_list()
    for row in rows_with_total:
        worksheet.conditional_format(f"E{row+1}:F{row+1}", {'type': 'cell',
                                                              'criteria': '>=',
                                                              'value': '0',
                                                              'format': date_format})

    dataframe_border_indexes = extracted_data[
        extracted_data.Description.map(lambda x: True if isinstance(x, str) and 'name' in x.lower() or x.lower is '' else False)].index.to_list()
    border_areas = []
    for index,border_index in enumerate(dataframe_border_indexes):
        if index+1 < len(dataframe_border_indexes):
            row_counts= dataframe_border_indexes[index+1] - border_index
        else:
            row_counts = number_rows-border_index
        border_areas.append(border_index+1)
        border_areas.append(row_counts-4)
        draw_frame_border(workbook,worksheet,border_index+1,1, row_counts-4,5)

        draw_frame_border(workbook,worksheet,border_index+1,7, row_counts-4,3)
        draw_frame_border(workbook,worksheet,border_index+1,11, row_counts-4,3)
        draw_frame_border(workbook,worksheet,border_index+1,15, row_counts-4,3)

        for row in range(border_index+1, border_index+1+row_counts-4,2):
            worksheet.conditional_format(f"B{row}:F{row}", {'type': 'cell',
                                                 'criteria': '>=',
                                                 'value': '0',
                                                 'format': alternate_row_color_format})

        for row in range(border_index+3, border_index+3+row_counts-5,2):
            worksheet.conditional_format(f"H{row}:J{row}", {'type': 'cell',
                                                 'criteria': '>=',
                                                 'value': '0',
                                                 'format': alternate_row_color_format})

        for row in range(border_index+3, border_index+3+row_counts-5,2):
            worksheet.conditional_format(f"L{row}:N{row}", {'type': 'cell',
                                                 'criteria': '>=',
                                                 'value': '0',
                                                 'format': alternate_row_color_format})

        for row in range(border_index+3, border_index+3+row_counts-5,2):
            worksheet.conditional_format(f"P{row}:R{row}", {'type': 'cell',
                                                 'criteria': '>=',
                                                 'value': '0',
                                                 'format': alternate_row_color_format})

        apply_format_on_cell(worksheet,f"H{border_index+1}",address_format)
        apply_format_on_cell(worksheet,f"L{border_index+1}",address_format)
        apply_format_on_cell(worksheet,f"P{border_index+1}",address_format)

        apply_format_on_cell(worksheet, f"I{border_index + 1}", date_section_format)
        apply_format_on_cell(worksheet, f"M{border_index + 1}", date_section_format)
        apply_format_on_cell(worksheet, f"Q{border_index + 1}", date_section_format)

        apply_format_on_cell(worksheet, f"J{border_index + 1}", amount_format)
        apply_format_on_cell(worksheet, f"N{border_index + 1}", amount_format)
        apply_format_on_cell(worksheet, f"R{border_index + 1}", amount_format)


    for index, border_index in enumerate(border_areas):
        if index == 0:
            border_index-=1
        elif index % 2 == 0:
            border_index-= 1
        else:
            continue

        worksheet.conditional_format(f"B{border_index}:B{border_index}", {'type': 'cell',
                                                        'criteria': '>=',
                                                        'value': '0',
                                                        'format': date_format})

    worksheet.ignore_errors({'number_stored_as_text': f"B1:F{number_rows}"})
    writer.save()


def apply_format_on_cell( worksheet,cell,format):
    worksheet.conditional_format(f"{cell}:{cell}", {'type': 'cell',
                                                    'criteria': '>=',
                                                    'value': '0',
                                                    'format': format})


def draw_frame_border(workbook, worksheet, first_row, first_col, rows_count, cols_count):

    # top left corner
    worksheet.conditional_format(first_row, first_col,
                                 first_row, first_col,
                                 {'type': 'formula', 'criteria': 'True',
                                  'format': workbook.add_format({'top': 1, 'left': 1})})
    # top right corner
    worksheet.conditional_format(first_row, first_col + cols_count - 1,
                                 first_row, first_col + cols_count - 1,
                                 {'type': 'formula', 'criteria': 'True',
                                  'format': workbook.add_format({'top': 1, 'right': 1})})
    # bottom left corner
    worksheet.conditional_format(first_row + rows_count - 1, first_col,
                                 first_row + rows_count - 1, first_col,
                                 {'type': 'formula', 'criteria': 'True',
                                  'format': workbook.add_format({'bottom': 1, 'left': 1})})
    # bottom right corner
    worksheet.conditional_format(first_row + rows_count - 1, first_col + cols_count - 1,
                                 first_row + rows_count - 1, first_col + cols_count - 1,
                                 {'type': 'formula', 'criteria': 'True',
                                  'format': workbook.add_format({'bottom': 1, 'right': 1})})

    # top
    worksheet.conditional_format(first_row, first_col + 1,
                                 first_row, first_col + cols_count - 2,
                                 {'type': 'formula', 'criteria': 'True', 'format': workbook.add_format({'top': 1})})
    # left
    worksheet.conditional_format(first_row + 1,              first_col,
                                 first_row + rows_count - 2, first_col,
                                 {'type': 'formula', 'criteria': 'True', 'format': workbook.add_format({'left': 1})})
    # bottom
    worksheet.conditional_format(first_row + rows_count - 1, first_col + 1,
                                 first_row + rows_count - 1, first_col + cols_count - 2,
                                 {'type': 'formula', 'criteria': 'True', 'format': workbook.add_format({'bottom': 1})})
    # right
    worksheet.conditional_format(first_row + 1,              first_col + cols_count - 1,
                                 first_row + rows_count - 2, first_col + cols_count - 1,
                                 {'type': 'formula', 'criteria': 'True', 'format': workbook.add_format({'right': 1})})


def export_batch_entry_to_excel(df, output_dir="mpi_backend/storage/Exports"):
    """
    Exports a DataFrame to an Excel file with formatted headers using xlsxwriter
    and generates a unique filename.

    Parameters:
        df (pd.DataFrame): The DataFrame to export.
        output_dir (str): Directory to save the file. Defaults to "output".

    Returns:
        str: The path of the generated Excel file.
    """
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Generate a unique filename based on timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(output_dir, f"exported_data_{timestamp}.xlsx")

    # Use pd.ExcelWriter with xlsxwriter as the engine
    with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
        # Write the DataFrame to Excel
        df.to_excel(writer, sheet_name="Filtered Data", index=False)

        # Access the workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets["Filtered Data"]

        # Define header formatting
        header_format = workbook.add_format({
            "bold": True,
            "font_color": "white",
            "bg_color": "#000000",
            "align": "center",
            "valign": "vcenter",
        })

        # Apply the formatting to the header row
        for col_num, column in enumerate(df.columns):
            worksheet.write(0, col_num, column, header_format)

        column_widths = {
            "Date": 12,
            "Ref": 15,
            "vendor": 25,
            "terms": 10,
            "bill due": 12,
            "account": 40,
            "Amount": 10,
            "Memo": 25,
            "Customer Job": 40,
            "Class": 10,
        }

        for col_num, column in enumerate(df.columns):
            width = column_widths.get(column, 15)  # Default width is 15 if not specified
            worksheet.set_column(col_num, col_num, width)

        worksheet.autofilter(0, 0, 0, len(df.columns) - 1)

    return file_path


def export_price_history_to_excel(price_history, output_dir="mpi_backend/storage/Exports"):
    """
    Exports price history data to an Excel file with formatted headers using xlsxwriter.

    Parameters:
        price_history (List[PriceHistoryResponse]): List of price history records
        output_dir (str): Directory to save the file. Defaults to "mpi_backend/storage/Exports"

    Returns:
        str: The path of the generated Excel file.
    """
    # Convert price history to DataFrame
    df = pd.DataFrame([{
        'Ref No': item.ref_no,
        'Date': item.date,
        'Cost': float(item.cost),
        'Quantity': item.qty,
    } for item in price_history])

    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Generate a unique filename based on timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(output_dir, f"price_history_{timestamp}.xlsx")

    # Use pd.ExcelWriter with xlsxwriter as the engine
    with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
        # Write the DataFrame to Excel
        df.to_excel(writer, sheet_name="Price History", index=False)

        # Access the workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets["Price History"]

        # Define header formatting
        header_format = workbook.add_format({
            "bold": True,
            "font_color": "white",
            "bg_color": "#366092",  # Blue background
            "align": "center",
            "valign": "vcenter",
            "border": 1
        })

        # Define number format for prices
        price_format = workbook.add_format({
            "num_format": "#,##0.00",
            "align": "right",
            "border": 1
        })

        # Define date format
        date_format = workbook.add_format({
            "num_format": "mm-dd-yyyy",
            "align": "center",
            "border": 1
        })

        # Define general cell format
        cell_format = workbook.add_format({
            "align": "left",
            "border": 1
        })

        # Apply the formatting to the header row
        for col_num, column in enumerate(df.columns):
            worksheet.write(0, col_num, column, header_format)

        # Define column widths
        column_widths = {
            "Ref No": 20,
            "Date": 20,
            "Cost": 12,
            "Quantity": 13,
        }

        # Set column widths and formats
        for col_num, column in enumerate(df.columns):
            width = column_widths.get(column, 15)  # Default width is 15 if not specified
            worksheet.set_column(col_num, col_num, width)

            # Apply formats to entire columns
            if column == "Cost":
                worksheet.set_column(col_num, col_num, width, price_format)
            elif column == "Date":
                worksheet.set_column(col_num, col_num, width, date_format)
            else:
                worksheet.set_column(col_num, col_num, width, cell_format)

        worksheet.autofilter(0, 0, len(df.index), len(df.columns))

    return file_path