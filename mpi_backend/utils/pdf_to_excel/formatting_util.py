import pandas as pd
from datetime import datetime
import os
from typing import List
# import openpyxl


def save_final_data_for_database(final_df, supplier, output_path):
    """Save data for database processing without invisible prefixes"""
    # Ensure ref_no is formatted as string to preserve leading zeros
    if 'Ref NO' in final_df.columns:
        final_df['Ref NO'] = final_df['Ref NO'].astype(str)
    
    writer = pd.ExcelWriter(output_path, engine='xlsxwriter')
    
    num_cols = len(final_df.columns)
    
    final_df.to_excel(writer, index=False, sheet_name='Table 1')
    
    workbook = writer.book
    worksheet = writer.sheets['Table 1']
    
    # Apply basic formatting without invisible prefixes
    worksheet.set_column('A:A', 20)
    worksheet.set_column('B:B', 35)
    worksheet.set_column('C:C', 7)
    worksheet.set_column('D:D', 10)
    worksheet.set_column('E:E', 10)
    worksheet.set_column('F:F', 10)
    worksheet.set_column('G:G', 15)
    worksheet.set_column('H:H', 10)
    worksheet.set_column('I:I', 35)
    worksheet.set_column('J:J', 10)
    worksheet.set_column('K:K', 20)
    worksheet.set_column('L:L', 10)
    worksheet.set_column('M:M', 20)
    worksheet.set_column('N:N', 20)
    
    writer.close()


def save_final_data(final_df, supplier, output_path):
    # Ensure ref_no is formatted as string to preserve leading zeros
    if 'Ref NO' in final_df.columns:
        final_df['Ref NO'] = final_df['Ref NO'].astype(str)
    
    writer = pd.ExcelWriter(output_path, engine='xlsxwriter')
    
    num_cols = len(final_df.columns)
    
    final_df.to_excel(writer, index=False, sheet_name='Table 1')

    workbook = writer.book
    worksheet = writer.sheets['Table 1']
    
    # Force ref_no column to be treated as text in Excel (no visual changes)
    if 'Ref NO' in final_df.columns:
        ref_no_col_idx = final_df.columns.get_loc('Ref NO')
        
        # Create text format that prevents Excel from auto-converting
        text_format = workbook.add_format({
            'num_format': '@',  # @ = text format
            'text_wrap': False,
            'align': 'left'
        })
        
        # Set column format
        worksheet.set_column(ref_no_col_idx, ref_no_col_idx, 15, text_format)
        
        # Write header as text
        worksheet.write_string(0, ref_no_col_idx, 'Ref NO', text_format)
        
        # Write each ref_no value as text with explicit text format (invisible prefix to prevent Excel errors)
        for row_idx, value in enumerate(final_df['Ref NO'], 1):  # Start from row 1 (skip header)
            # Add invisible non-breaking space to prevent Excel "Number Stored as Text" error
            text_value = str(value)
            if text_value.isdigit():
                text_value = '\u00A0' + text_value  # Non-breaking space (invisible)
            worksheet.write_string(row_idx, ref_no_col_idx, text_value, text_format)
    
    # Write amount column as numbers
    if 'Amount' in final_df.columns:
        amount_col_idx = final_df.columns.get_loc('Amount')
        
        # Write header
        worksheet.write_string(0, amount_col_idx, 'Amount')
        
        # Write each amount value as number
        for row_idx, value in enumerate(final_df['Amount'], 1):  # Start from row 1 (skip header)
            if pd.notna(value):
                # Remove commas and convert to float
                clean_value = str(value).replace(',', '')
                try:
                    worksheet.write_number(row_idx, amount_col_idx, float(clean_value))
                except (ValueError, TypeError):
                    worksheet.write_number(row_idx, amount_col_idx, 0)
            else:
                worksheet.write_number(row_idx, amount_col_idx, 0)
    
    # Write cost column as numbers
    if 'Cost' in final_df.columns:
        cost_col_idx = final_df.columns.get_loc('Cost')
        
        # Write header
        worksheet.write_string(0, cost_col_idx, 'Cost')
        
        # Write each cost value as number
        for row_idx, value in enumerate(final_df['Cost'], 1):  # Start from row 1 (skip header)
            if pd.notna(value):
                # Remove commas and convert to float
                clean_value = str(value).replace(',', '')
                try:
                    worksheet.write_number(row_idx, cost_col_idx, float(clean_value))
                except (ValueError, TypeError):
                    worksheet.write_number(row_idx, cost_col_idx, 0)
            else:
                worksheet.write_number(row_idx, cost_col_idx, 0)

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


    writer.close()


def save_final_data_fast(final_df, output_path):
    """
    Fast Excel export with minimal formatting for better performance.
    
    Args:
        final_df: DataFrame to export
        output_path: Output file path
    """
    try:
        # Ensure ref_no is formatted as string to preserve leading zeros
        if 'Ref NO' in final_df.columns:
            final_df['Ref NO'] = final_df['Ref NO'].astype(str)
        
        # Clean the number-related columns
        # Remove commas and convert to numeric, convert errors (NaN) to 0
        # TODO: If there are errors, we should color the cell to red
        # TODO: Add all other number columns here then have the monetary ones have a separate handling of formatting
        for col in ['Qty', 'Subtotal QTY']:
            if col in final_df.columns:
                final_df[col] = final_df[col].astype(str).str.replace(',', '', regex=False)
                final_df[col] = pd.to_numeric(final_df[col], errors='coerce')
                final_df[col] = final_df[col].fillna(0)
                final_df[col] = final_df[col].astype(int)

        # Use xlsxwriter for better performance
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            # Write data without formatting first
            final_df.to_excel(writer, sheet_name='Exported Data', index=False)
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Exported Data']

            # Force ref_no column to be treated as text in Excel
            if 'Ref NO' in final_df.columns:
                ref_no_col_idx = final_df.columns.get_loc('Ref NO')

                # Create text format that prevents Excel from auto-converting
                text_format = workbook.add_format({
                    'num_format': '@',  # @ = text format
                    'text_wrap': False,
                    'align': 'left'
                })

                # Set column format
                worksheet.set_column(ref_no_col_idx, ref_no_col_idx, 15, text_format)

                # Write header
                worksheet.write_string(0, ref_no_col_idx, 'Ref NO', text_format)

                # Write entire column at once
                ref_no_values = [str(val) for val in final_df['Ref NO']]
                worksheet.write_column(1, ref_no_col_idx, ref_no_values, text_format)
            
            # Write all monetary columns as formatted numbers
            money_format = workbook.add_format({
                'num_format': '#,##0.00',
                'align': 'right',
            })
            for money_col in ('Amount', 'Cost', 'PPP', 'Total Amount'):
                if money_col in final_df.columns:
                    col_idx = final_df.columns.get_loc(money_col)
                    for row_idx, value in enumerate(final_df[money_col], 1):
                        if pd.notna(value):
                            clean_value = str(value).replace(',', '')
                            try:
                                worksheet.write_number(row_idx, col_idx, float(clean_value), money_format)
                            except (ValueError, TypeError):
                                worksheet.write_number(row_idx, col_idx, 0, money_format)
                        else:
                            worksheet.write_blank(row_idx, col_idx, money_format)
            
            # Apply minimal formatting for better readability
            # Header format
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D7E4BC',
                'border': 1,
                'align': 'center'
            })
            
            # Data format
            data_format = workbook.add_format({
                'border': 1,
                'align': 'left'
            })
            
            # Number format for cost columns
            number_format = workbook.add_format({
                'num_format': '#,##0.00',
                'border': 1,
                'align': 'right'
            })
            
            # Date format
            date_format = workbook.add_format({
                'num_format': 'mm/dd/yyyy',
                'border': 1,
                'align': 'center'
            })
            
            # Apply header formatting
            for col_num, column in enumerate(final_df.columns):
                worksheet.write(0, col_num, column, header_format)
                
                # Set column widths based on content
                if column in ['Item', 'MPI Item Code']:
                    worksheet.set_column(col_num, col_num, 20)
                elif column in ['Description', 'Customer Job', 'MPI Description']:
                    worksheet.set_column(col_num, col_num, 35) 
                elif column in ['Cost', 'Amount', 'PPP', 'Total Amount']:
                    worksheet.set_column(col_num, col_num, 12)
                elif column == 'Date':
                    worksheet.set_column(col_num, col_num, 12)
                else:
                    worksheet.set_column(col_num, col_num, 15)
            
            # Apply autofilter
            worksheet.autofilter(0, 0, len(final_df), len(final_df.columns) - 1)
            
        return True
        
    except Exception as e:
        print(f"Error in fast Excel export: {e}")
        # Fallback to simple export
        final_df.to_excel(output_path, index=False)
        return False


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
        extracted_data.applymap(lambda x: True if isinstance(x, str) and 'total' in x.lower() else False).any(axis=1)].index.to_list()
    for row in rows_with_total:
        worksheet.conditional_format(f"E{row+1}:F{row+1}", {'type': 'cell',
                                                              'criteria': '>=',
                                                              'value': '0',
                                                              'format': date_format})

    dataframe_border_indexes = extracted_data[
        extracted_data.Description.map(lambda x: True if isinstance(x, str) and 'name' in x.lower() or x.lower == '' else False)].index.to_list()
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
    writer.close()


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

    # Handle empty DataFrame case
    if df.empty or len(df.columns) == 0:
        # Create a minimal DataFrame with a message
        df = pd.DataFrame({"Message": ["No data to export"]})

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
            "Message": 30,  # For empty DataFrame case
        }

        for col_num, column in enumerate(df.columns):
            width = column_widths.get(column, 15)  # Default width is 15 if not specified
            worksheet.set_column(col_num, col_num, width)

        # Only apply autofilter if we have data
        if len(df.columns) > 0:
            worksheet.autofilter(0, 0, 0, len(df.columns) - 1)

    return file_path


def export_price_history_to_excel(
    price_history: List['PriceHistoryResponse'],
    output_dir: str = "mpi_backend/storage/Exports"
) -> str:
    """
    Export price history to Excel with conditional formatting for price increases.
    
    The 'cost' field is the unit price, and is compared directly between purchases
    to determine if there was a price increase. Increases are highlighted in red.

    Args:
        price_history (List[PriceHistoryResponse]): List of price history records to export.
        output_dir (str, optional): Directory to save the Excel file. 
            Defaults to "mpi_backend/storage/Exports".

    Returns:
        str: The absolute path of the generated Excel file.
    """
    # Convert price history to DataFrame
    df = pd.DataFrame([{
        'Ref No': item.ref_no,
        'Date': item.date,
        'Cost': float(item.cost),
        'Quantity': item.qty,
        'Memo': item.memo if item.memo else ""
    } for item in price_history])

    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Sort by date (newest to oldest) for display
    # Handle invalid dates gracefully
    def parse_date_safe(date_str: str) -> pd.Timestamp | None:
        """
        Parse date string safely, handling multiple formats and invalid values.
        
        Args:
            date_str (str): Date string to parse. Can be in formats like:
                           '%m-%d-%Y', '%m/%d/%Y', '%m/%d/%y', or '%Y-%m-%d'.
                           May also contain 'Invalid date' or be null/empty.
        
        Returns:
            pd.Timestamp | None: Parsed timestamp if successful, None if parsing fails
                                or if input is invalid/empty.
        
        Examples:
            >>> parse_date_safe("01-15-2024")
            Timestamp('2024-01-15 00:00:00')
            >>> parse_date_safe("Invalid date")
            None
            >>> parse_date_safe("")
            None
        """
        try:
            if pd.isna(date_str) or not date_str or date_str == 'Invalid date':
                return None
            
            # Try parsing with different formats
            date_formats = ['%m-%d-%Y', '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d']
            for fmt in date_formats:
                try:
                    return pd.to_datetime(date_str, format=fmt)
                except (ValueError, TypeError):
                    continue
            
            return None
        except Exception:
            return None
    
    # Add sortable date column
    df['date_obj'] = df['Date'].apply(parse_date_safe)
    
    # Sort: valid dates first (newest to oldest), then invalid dates
    df['has_valid_date'] = df['date_obj'].notna()
    df = df.sort_values(['has_valid_date', 'date_obj'], ascending=[False, False], na_position='last')
    df = df.drop(['date_obj', 'has_valid_date'], axis=1)  # Remove temporary columns
    df = df.reset_index(drop=True)

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

        # Define number format for prices (normal - black text)
        price_format = workbook.add_format({
            "num_format": "#,##0.00",
            "align": "right",
            "border": 1,
            "font_color": "black"
        })

        # Define number format for prices with increase (red text)
        price_increase_format = workbook.add_format({
            "num_format": "#,##0.00",
            "align": "right",
            "border": 1,
            "font_color": "red",
            "bold": True
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

        # Set column widths
        for col_num, column in enumerate(df.columns):
            width = column_widths.get(column, 15)  # Default width is 15 if not specified
            worksheet.set_column(col_num, col_num, width)

        # Find the Cost column index
        cost_col_idx = df.columns.get_loc('Cost')
        
        # Apply conditional formatting row by row for the Cost column
        # Compare each entry with the chronologically PREVIOUS purchase (next row, since sorted newest first)
        # Cost is already the unit price, no need to divide by quantity
        for row_idx in range(len(df)):
            excel_row = row_idx + 1  # +1 because Excel rows are 1-indexed and we have a header
            current_price = df.iloc[row_idx]['Cost']
            
            # Compare with the next row (chronologically older purchase)
            is_price_increase = False
            if row_idx + 1 < len(df):
                previous_price = df.iloc[row_idx + 1]['Cost']
                is_price_increase = current_price > previous_price
            
            # Apply formatting based on price increase
            if is_price_increase:
                # Price increased - use red format
                worksheet.write(excel_row, cost_col_idx, current_price, price_increase_format)
            else:
                # Price stayed same, decreased, or this is the last entry - use normal format
                worksheet.write(excel_row, cost_col_idx, current_price, price_format)
            
            # Apply formats to other columns in this row
            for col_idx, column in enumerate(df.columns):
                if column != "Cost":  # We already handled Cost
                    value = df.iloc[row_idx][column]
                    if column == "Date":
                        worksheet.write(excel_row, col_idx, value, date_format)
                    else:
                        worksheet.write(excel_row, col_idx, value, cell_format)

        worksheet.autofilter(0, 0, len(df.index), len(df.columns))

    return file_path


def save_ultra_fast_excel(final_df, output_path):
    """
    QuickBooks Excel export with conditional formatting:
    - Multiple row invoices (including total line): Light pink for account rows, dark pink for total row
    - Single row invoices: No background color
    Args:
        final_df: DataFrame to export
        output_path: Output file path
    """
    try:
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            final_df.to_excel(writer, sheet_name='Exported Data', index=False)
            workbook = writer.book
            worksheet = writer.sheets['Exported Data']
            
            # Define formats
            light_pink_format = workbook.add_format(
                {'bg_color': '#FFE6E6'}
            )  # Light pink
            dark_pink_format = workbook.add_format(
                {'bg_color': '#FF6B6B'}
            )  # Dark pink

            # Set column widths for better readability
            column_widths = {
                'Date': 12,
                'Ref': 15,
                'vendor': 25,
                'terms': 10,
                'bill due': 12,
                'account': 40,
                'Amount': 12,
                'Memo': 25,
                'Customer Job': 40,
                'Class': 10
            }
            
            # Apply column widths
            for col_num, column in enumerate(final_df.columns):
                width = column_widths.get(column, 15)
                worksheet.set_column(col_num, col_num, width)
            
            # Group rows by invoice (Ref column) to identify split vs single row invoices
            if 'Ref' in final_df.columns and 'account' in final_df.columns:
                current_ref = None
                current_invoice_rows = []

                for row_idx, row in final_df.iterrows():
                    ref = row['Ref']
                    account = row['account']

                    # New invoice
                    if ref != current_ref:
                        # Process previous invoice
                        if current_ref and current_invoice_rows:
                            # Apply formatting for previous invoice group
                            if len(current_invoice_rows) > 1:
                                # Light pink for all account rows except the last row,
                                # Dark pink for the last row (total line)
                                for i, row_data in enumerate(current_invoice_rows):
                                    is_last = (i == len(current_invoice_rows) - 1)
                                    worksheet.set_row(
                                        row_data['row_idx'] + 1,
                                        None,
                                        dark_pink_format if is_last else light_pink_format
                                    )

                        # Start new invoice
                        current_ref = ref
                        current_invoice_rows = []

                    # Add row to current invoice
                    current_invoice_rows.append({
                        'row_idx': row_idx,
                        'account': account
                    })

                # Process the last invoice
                if current_ref and current_invoice_rows:
                    # Apply formatting for the last invoice group
                    if len(current_invoice_rows) > 1:
                        for i, row_data in enumerate(current_invoice_rows):
                            is_last = (i == len(current_invoice_rows) - 1)
                            worksheet.set_row(
                                row_data['row_idx'] + 1,
                                None,
                                dark_pink_format if is_last else light_pink_format
                            )

                # Apply autofilter
                worksheet.autofilter(0, 0, len(final_df), len(final_df.columns) - 1)
                
    except Exception as e:
        print(f"Error in QuickBooks Excel export: {e}")
        # Fallback to simple export
        final_df.to_excel(output_path, index=False)
