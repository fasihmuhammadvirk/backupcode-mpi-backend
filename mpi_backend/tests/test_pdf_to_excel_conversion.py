from pathlib import Path
from typing import List, Tuple

import pandas as pd
import pytest

from mpi_backend.utils.pdf_to_excel.main_extractor import extract_data


# Folder-to-supplier name mapping. Keys are folder names under
# `tests/convert_to_excel_test_files/`. Values are the exact supplier names
# expected by the conversion logic. Defaults to the folder name if not found.
SUPPLIER_NAME_MAP = {
    "BMW": "BMW Plumbing Supplies",
    "WWPS": "FW Webb Plumbing Supply",
    "Y&S": "Y & S Plumbing Supply",
    "WWP": "World Wide Plumbing",
    "Pyramid": "Pyramid Plumbing",
    "Supreme": "Supreme Plumbing Supply",
    "Gotham": "Gotham Plumbing Supply",
    "FlowMark": "Flow Mark Plumbing Supply",
    "PlumbingExchange": "Plumbing Exchange",
    "AF": "AF Supply",
    "LionHVAC": "Lion Hvac Supplies",
}


def _collect_supplier_cases() -> List[Tuple[str, Path, Path]]:
    """Collects all suppliers with their input and expected files.

    Returns a list of tuples: (supplier_name, input_pdf, expected_excel).
    Supplier name is resolved via SUPPLIER_NAME_MAP.
    """
    data_root = Path(__file__).parent / "convert_to_excel_test_files"
    cases = []
    if not data_root.exists():
        return cases

    for supplier_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        folder_key = supplier_dir.name
        supplier_name = SUPPLIER_NAME_MAP.get(folder_key, folder_key)
        input_pdf = supplier_dir / "input.pdf"
        expected_xlsx = supplier_dir / "expected_output.xlsx"
        if input_pdf.exists() and expected_xlsx.exists():
            cases.append((supplier_name, input_pdf, expected_xlsx))
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
    supplier_name: str, input_pdf: Path, expected_xlsx: Path, tmp_path: Path
) -> None:
    """Regression test for supplier-specific PDF-to-Excel conversions.

    Steps per supplier:
    1) Run conversion and assert no exception, output file is created
    2) Compare generated Excel vs expected: headers, shape, cell-by-cell
    """
    if not _SUPPLIER_CASES:
        msg = (
            "No supplier test data found in "
            "'tests/convert_to_excel_test_files'."
        )
        pytest.skip(msg)

    output_path = tmp_path / f"{Path(input_pdf).parent.name}_actual.xlsx"

    # Execute conversion; assert it runs without raising.
    extract_data(str(input_pdf), str(output_path), supplier_name)

    # Verify that the output file was created.
    assert output_path.exists(), (
        "Conversion did not produce an output file at: {p}".format(
            p=output_path
        )
    )

    # Compare content.
    _compare_excels_cell_by_cell(expected_xlsx, output_path)
