"""Debug script to inspect normalized PDF text sent to AI models."""
import sys
from pathlib import Path

# Add backfill scripts to path for pdf_utils import
sys.path.insert(0, str(Path(__file__).parent / "backfill_invoices_data"))

from pdf_utils import normalize_pdf_text


def main():
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <absolute_path_to_pdf>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not Path(file_path).exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    pdf_normalize_set, raw_pdf_text = normalize_pdf_text(file_path)

    print("NORMALIZED SET:")
    print(pdf_normalize_set)
    print()
    print("RAW PDF TEXT:")
    print(raw_pdf_text)


if __name__ == "__main__":
    main()
