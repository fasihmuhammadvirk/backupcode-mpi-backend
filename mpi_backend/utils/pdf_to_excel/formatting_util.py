import pandas as pd
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

