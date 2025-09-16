import os
# from openpyxl import load_workbook
import time
import shutil
import platform

# Windows-specific imports
if platform.system() == "Windows":
    try:
        import win32com.client
    except ImportError:
        win32com = None
else:
    win32com = None


def embed_folderPath_in_consolidated_bills(output_path):
    """
    Windows-specific function for Excel automation.
    On non-Windows systems, this function does nothing.
    """
    if platform.system() != "Windows" or win32com is None:
        print("Excel automation is only available on Windows with win32com installed.")
        return

    # output_path = output_path.rpartition('/')[0] or output_path
    # output_path = output_path.replace('/', '//')

    path = os.getcwd()
    path = path.replace('\'', '\\') + '\\'

    # copying sample EXCEL file for refresh to work
    # shutil.copy(path + "..\\data\\0000_Sample_Data.xlsx", output_path)
    shutil.copy(path + "data\\0000_Sample_Data.xlsx", output_path)

    xl = win32com.client.DispatchEx("Excel.Application")
    # wb = xl.workbooks.open(path + "..\\data\\Consolidated_Bills_v0.2.3.xlsm")
    wb = xl.workbooks.open(path + "data\\Consolidated_Bills_v0.2.3.xlsm")

    work_sheet = wb.Worksheets("Mappings")
    row = 4
    col = 5
    work_sheet.Cells(row, col).Value = output_path
    wb.Save()

    wb.Close(True)
    xl.Quit()
    refresh_data()


def refresh_data():
    """
    Windows-specific function for Excel data refresh.
    On non-Windows systems, this function does nothing.
    """
    if platform.system() != "Windows" or win32com is None:
        print("Excel automation is only available on Windows with win32com installed.")
        return
        
    path = os.getcwd()

    path = path.replace('\'', '\\') + '\\'
    xl = win32com.client.DispatchEx("Excel.Application")
    # wb = xl.workbooks.open(path + "..\\data\\Consolidated_Bills_v0.2.3.xlsm")
    wb = xl.workbooks.open(path + "data\\Consolidated_Bills_v0.2.3.xlsm")
    xl.Visible = True
    wb.RefreshAll()
    # time.sleep(30)
    # wb.Close(True)
    # wb.SaveAs(Filename=path + "data\\Consolidated_Bills_v0.2.3.xlsm")
    # xl.Quit()
