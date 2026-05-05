"""
Excel utility functions for consolidated bills processing.

Note: This module has platform-specific requirements:
- Cell writing operations use openpyxl (cross-platform)
- Data connection refreshing requires Windows with Excel installed
  (COM automation)
"""
from pathlib import Path
import time
import shutil
import sys
import openpyxl

# Platform-specific import for Excel COM automation
if sys.platform == 'win32':
    try:
        import win32com.client
    except ImportError:
        win32com = None
        WIN32COM_AVAILABLE = False
    else:
        WIN32COM_AVAILABLE = True
else:
    win32com = None
    WIN32COM_AVAILABLE = False


class PlatformError(Exception):
    """Raised when a platform-specific operation is attempted on an
    unsupported OS.
    """


def _require_windows_com():
    """Ensure Windows COM automation is available."""
    if not WIN32COM_AVAILABLE:
        if sys.platform != 'win32':
            raise PlatformError(
                "Excel COM automation requires Windows. This operation "
                "cannot be performed on non-Windows platforms. Please run "
                "this on a Windows machine with Excel installed."
            )
        else:
            raise PlatformError(
                "win32com.client is not available. Please install pywin32: "
                "pip install pywin32"
            )


def embed_folderPath_in_consolidated_bills(output_path):
    """
    Embed folder path in the consolidated bills Excel workbook.

    Uses openpyxl for cross-platform cell writing, then refreshes data
    connections (Windows-only operation).
    """
    base_dir = Path(__file__).resolve().parents[3]
    data_dir = base_dir / "data"

    sample_data = data_dir / "0000_Sample_Data.xlsx"
    consolidated_bills = data_dir / "Consolidated_Bills_v0.2.3.xlsm"

    if not sample_data.exists():
        raise FileNotFoundError(f"Sample data file not found: {sample_data}")
    if not consolidated_bills.exists():
        raise FileNotFoundError(
            f"Consolidated bills file not found: {consolidated_bills}"
        )

    shutil.copy(sample_data, output_path)

    # Use openpyxl for cross-platform cell writing
    try:
        wb = openpyxl.load_workbook(consolidated_bills, keep_vba=True)
        work_sheet = wb["Mappings"]
        row = 4
        col = 7
        work_sheet.cell(row=row, column=col).value = str(output_path)
        wb.save(consolidated_bills)
        wb.close()
    except Exception as e:
        raise RuntimeError(
            f"Failed to write cell value using openpyxl: {e}"
        ) from e

    # Refresh data connections (requires Windows with Excel)
    refresh_data()


def refresh_data():
    """
    Refresh data in the consolidated bills Excel workbook.

    This function requires Windows with Excel installed, as it uses COM
    automation to refresh data connections. This cannot be done with
    openpyxl or other cross-platform libraries.

    Raises:
        PlatformError: If not running on Windows or win32com is
            unavailable.
    """
    _require_windows_com()

    base_dir = Path(__file__).resolve().parents[3]
    data_dir = base_dir / "data"

    xl = win32com.client.DispatchEx("Excel.Application")
    try:
        consolidated_path = str(
            data_dir / "Consolidated_Bills_v0.2.3.xlsm"
        )
        wb = xl.workbooks.open(consolidated_path)
        xl.Visible = True
        wb.RefreshAll()
        time.sleep(5)
        wb.Close(SaveChanges=True)
    finally:
        xl.Quit()
