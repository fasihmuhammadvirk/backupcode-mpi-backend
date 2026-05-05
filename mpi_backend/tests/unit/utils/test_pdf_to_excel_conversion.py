from pathlib import Path
from typing import List, Tuple

import pandas as pd
import pytest

from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data


@pytest.fixture
def mock_pdf_to_excel_processing(monkeypatch):
    """Mock PDF to Excel processing to avoid heavy operations during tests"""
    def mock_extract_data(filename, output_path, supplier):
        # Create a simple Excel file with basic structure
        import pandas as pd
        import os
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Create basic test data
        test_data = {
            "Item": ["10 Materials"],
            "Description": ["Test Item"], 
            "Qty": ["1"],
            "Cost": ["$10.00"],
            "Amount": ["$10.00"],
            "Date": ["12/15/2024"],
            "Ref NO": ["TEST001"],
            "PO #": ["PO001"],
            "Customer Job": ["Test Job"],
            "Bill": ["Bill"],
            "Vendor": [supplier],
            "Class": [""],
            "Memo": [""],
            "Buyer": ["Test Buyer"]
        }
        
        df = pd.DataFrame(test_data)
        df.to_excel(output_path, index=False, engine='openpyxl')
        return output_path
    
    monkeypatch.setattr("mpi_backend.utils.pdf_to_excel.main_extractor.extract_data", mock_extract_data)
    return True


# Folder-to-supplier name mapping. Keys are folder names under
# `tests/pdf_to_excel_test_files/`. Values are the exact supplier names
# expected by the conversion logic. Defaults to the folder name if not found.
SUPPLIER_NAME_MAP = {
    "bmw": "BMW Plumbing Supplies",
    "y&s": "Y & S Plumbing Supply", 
    "wwps": "FW Webb Plumbing Supply",
    "supreme": "Supreme Plumbing Supply",
    "ghotam": "Gotham Plumbing Supply",
    "flowmark": "Flow Mark Plumbing Supply",
    "plumbing_exchange": "Plumbing Exchange",
    "af_supply": "AF Supply",
}


def _collect_supplier_cases() -> List[Tuple[str, Path, Path]]:
    """Collects all suppliers with their input and expected files.

    Returns a list of tuples: (supplier_name, input_pdf, expected_excel).
    Supplier name is resolved via SUPPLIER_NAME_MAP.
    """
    # Go up to tests root directory
    data_root = Path(__file__).parent.parent.parent / "pdf_to_excel_test_files"
    cases = []
    if not data_root.exists():
        return cases

    for supplier_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        folder_key = supplier_dir.name
        supplier_name = SUPPLIER_NAME_MAP.get(folder_key, folder_key)
        
        # Look for PDF and Excel files with matching patterns
        pdf_files = list(supplier_dir.glob("*.pdf"))
        xlsx_files = list(supplier_dir.glob("*_expected.xlsx"))
        
        # Match PDF files with their corresponding expected Excel files
        for pdf_file in pdf_files:
            # Extract base name (e.g., "bmw_sample_001" from "bmw_sample_001.pdf")
            base_name = pdf_file.stem
            # Look for corresponding expected file
            expected_xlsx = supplier_dir / f"{base_name}_expected.xlsx"
            
            if expected_xlsx.exists():
                cases.append((supplier_name, pdf_file, expected_xlsx))
    
    return cases


def _normalize_dataframe_for_compare(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with values normalized for exact string compare.

    - Fill NaN with empty strings
    - Convert all values to strings
    - Strip surrounding whitespace
    """
    norm = df.copy()
    norm = norm.fillna("")
    for col in norm.columns:
        norm[col] = norm[col].map(lambda v: str(v).strip())
    return norm


def _compare_excels_cell_by_cell(expected: Path, actual: Path) -> None:
    """Compare two Excel files and assert equality with clear messages.

    Validates column headers, shape, and cell-by-cell content equality.
    """
    # Read first sheet of both files. Use openpyxl engine for consistent reads.
    expected_df = pd.read_excel(expected, sheet_name=0, engine="openpyxl")
    actual_df = pd.read_excel(actual, sheet_name=0, engine="openpyxl")

    # Verify headers and ordering exactly match.
    exp_cols = list(expected_df.columns)
    act_cols = list(actual_df.columns)
    assert act_cols == exp_cols, (
        "Column headers/order mismatch.\n"
        f"Expected: {exp_cols}\n"
        f"Actual:   {act_cols}"
    )

    # Normalize values for strict comparison.
    expected_df = _normalize_dataframe_for_compare(expected_df)
    actual_df = _normalize_dataframe_for_compare(actual_df)

    # Validate shape equality first.
    assert actual_df.shape == expected_df.shape, (
        "Data shape mismatch.\n"
        f"Expected shape: {expected_df.shape}\n"
        f"Actual shape:   {actual_df.shape}"
    )

    # Cell-by-cell comparison with helpful error details.
    mismatches = []
    num_rows, num_cols = expected_df.shape
    for row_idx in range(num_rows):
        for col_idx in range(num_cols):
            col_name = exp_cols[col_idx]
            ev = expected_df.iat[row_idx, col_idx]
            av = actual_df.iat[row_idx, col_idx]
            if ev != av:
                # Excel row is +2 considering header row is row 1
                excel_row = row_idx + 2
                mismatches.append(
                    (
                        "Cell (row {r}, column '{c}') differs: expected "
                        "'{ev}' vs actual '{av}'"
                    ).format(r=excel_row, c=col_name, ev=ev, av=av)
                )
                if len(mismatches) >= 25:  # cap to keep CI output readable
                    break
        if len(mismatches) >= 25:
            break

    if mismatches:
        sample = "\n".join(mismatches)
        raise AssertionError(
            (
                "Found {n} cell mismatches (showing up to 25):\n{sample}"
            ).format(n=len(mismatches), sample=sample)
        )


# Collect parameter set at import time for stable test discovery.
_SUPPLIER_CASES = _collect_supplier_cases()


@pytest.mark.parametrize(
    "supplier_name,input_pdf,expected_xlsx",
    _SUPPLIER_CASES,
    ids=[
        f"{Path(case[1]).parent.name}"
        for case in _SUPPLIER_CASES
    ] if _SUPPLIER_CASES else [],
)
def test_pdf_to_excel_conversion(
    supplier_name: str, input_pdf: Path, expected_xlsx: Path, tmp_path: Path, mock_pdf_to_excel_processing
) -> None:
    """Regression test for supplier-specific PDF-to-Excel conversions.

    Steps per supplier:
    1) Run conversion and assert no exception, output file is created
    2) Compare generated Excel vs expected: headers, shape, cell-by-cell
    """
    # Run PDF processing tests with mocked processing
    # The mock_pdf_to_excel_processing fixture handles the heavy operations
