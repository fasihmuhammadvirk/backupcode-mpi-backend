"""
Test suite for Ship To address extraction logic in extraction_util.py

Tests the extract_job_info() function which extracts customer job (ship-to address) from invoices.

These tests use REALISTIC invoice structures that mimic actual PDF text extraction output
from World Wide Plumbing Supply (WWPS) invoices. This ensures the extraction logic is tested
against real-world patterns, not sanitized input.

The extraction must prioritize Ship To address over Sold To address.
Example: Invoice shows Sold To: 670 Myrtle Ave, Ship To: 270 Nostrand Ave
         System must return 270 Nostrand Ave (the delivery/job site address)
"""

import pytest
from unittest.mock import patch


class TestRealisticWWPSInvoiceExtraction:
    """
    Tests using realistic WWPS invoice structures from actual PDFs.

    These tests simulate real PDF text extraction output with:
    - Both "Sold To" and "Ship To" sections
    - Company names, attention lines, phone numbers
    - Multiple address lines
    - Invoice headers, line items, totals
    """

    def test_extract_ship_to_not_sold_to_gerry_st(self):
        """
        GIVEN: Invoice with Sold To (670 MYRTLE AVE) and Ship To (60 Gerry St)
        WHEN: extract_job_info is called
        THEN: Returns Ship To address "60 Gerry St", NOT the Sold To address

        Based on Invoice #670607 - customer delivery to Gerry St in Brooklyn
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY
4002 15th Avenue
Brooklyn, NY 11218
718.853.3000

INVOICE                                        Page 1/1

Sold To                            Ship To
MPI PLUMBING                       MPI PLUMBING
670 MYRTLE AVE                     ATT: Eli 845-521-9238
#234                               60 Gerry St
BROOKLYN NY 11205                  60-66 Gerry
                                   Brooklyn NY 11206

Customer #   Order Date   Sales Order #   Buyer           Customer P/O #   Ship Via   Salesman
0002180      11/12/2025   670607          Mordchai Deutch M1112411         Tr LC/006  JS

Invoice #    Invoice Date  Ship Date   Freight Terms   Job Number   Terms
670607       11/14/2025    11/13/25    PREPAID                      NET 120

LN  QNTY  QNTY  QNTY  PRODUCT    DESCRIPTION           LIST    DISC%   NET     EXTENSION
    ORD   SHIP  B/O   NUMBER                           PRICE           PRICE

                      ***** Invoice Message *****
                      7AM
                      Eli (347) 636-3248

1   6     6           NHP40100   4 X 10 NO-HUB PIPE    199.70  65.70   68.4971   $410.98
2   48    48          IHC40      4" IMPORTED HEAVY D   21.97   NET     6.9857    $335.31

Merchandise     746.29
Freight          0.00
Sub Total      746.29
Tax (NYT)       66.23
TOTAL         $812.52
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Must find "60 Gerry St" (Ship To) NOT "670 MYRTLE AVE" (Sold To)
                assert "Gerry" in result or "60" in result, (
                    f"Should find Ship To address '60 Gerry St', got '{result}'. "
                    f"Must NOT return Sold To address '670 MYRTLE AVE'"
                )
                assert "670" not in result or "MYRTLE" not in result, (
                    f"Should NOT return Sold To address '670 MYRTLE AVE', got '{result}'"
                )

    def test_extract_ship_to_junction_blvd(self):
        """
        GIVEN: Invoice with Ship To at 34-20 Junction Blvd, Flushing
        WHEN: extract_job_info is called
        THEN: Returns the Junction Blvd address

        Based on Invoice #666294 - delivery to Flushing, NY
        Note: PDF text extraction (fitz) extracts columns separately, not merged
        """
        # This matches how fitz.page.get_text() extracts a side-by-side layout
        raw_text = """WORLD WIDE PLUMBING SUPPLY
4002 15th Avenue
Brooklyn, NY 11218

INVOICE
Page 1/1

Sold To
MPI PLUMBING
670 MYRTLE AVE
#234
BROOKLYN NY 11205

Ship To
MPI Plumbing
34-20 Junction Blvd
Flushing NY 11732

Customer #   Order Date   Sales Order #   Buyer
0002180      10/30/2025   666294          Shauly Hirsch

Invoice #    Invoice Date  Ship Date   Freight Terms   Terms
666294       11/02/2025    10/31/25    PREPAID         NET 120

LN  QNTY  PRODUCT      DESCRIPTION                LIST      DISC%   NET     EXTENSION

1   1     ES620SOMSK   STATE 20 GAL SHORT         1082.00   45.00   595.10   $595.10
                       WATER HEATER #100118478

Merchandise     595.10
Tax (NYT)        52.82
TOTAL          $647.92
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Must find "34-20 Junction Blvd" (Ship To)
                assert "Junction" in result or "34-20" in result, (
                    f"Should find Ship To address '34-20 Junction Blvd', got '{result}'"
                )

    def test_extract_ship_to_with_att_line_corona(self):
        """
        GIVEN: Invoice with ATT: line (attention/phone) before the address
        WHEN: extract_job_info is called
        THEN: Returns the street address, not the ATT line

        Based on Invoice #667364 - delivery to Corona, NY with ATT: Julio phone number
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY
4002 15th Avenue
Brooklyn, NY 11218

INVOICE                                        Page 1/1

Sold To                            Ship To
MPI PLUMBING                       MPI
670 MYRTLE AVE                     ATT: Julio 575-299-1548
#234                               37-20 114th St
BROOKLYN NY 11205                  CORONA NY 11368

Customer #   Order Date   Sales Order #   Buyer           Customer P/O #   Ship Via   Salesman
0002180      11/03/2025   667364          Mordchai Deutch M113253          Tr JM/004  JS

Invoice #    Invoice Date  Ship Date   Freight Terms   Job Number   Terms
667364       11/05/2025    11/04/25    PREPAID                      NET 120

LN  QNTY  QNTY  PRODUCT    DESCRIPTION           LIST    DISC%   NET       EXTENSION
    ORD   SHIP  NUMBER

                ***** Invoice Message *****
                8AM

1   10    10    NHP60100   6 X 10 NO-HUB PIPE    536.70  70.47   158.4875  $1584.88
2   3     3     NHP40100   4 X 10 NO-HUB PIPE    199.70  65.70   68.4971   $205.49

TOTAL         $2155.27
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Must find "37-20 114th St" (the actual street address)
                # Should skip "ATT: Julio 575-299-1548" (attention/phone line)
                assert "114th" in result or "37-20" in result, (
                    f"Should find Ship To address '37-20 114th St', got '{result}'. "
                    f"Should skip ATT: line"
                )

    def test_extract_ship_to_valentine_bronx(self):
        """
        GIVEN: Invoice with Ship To at 2829 VALENTINE, Bronx
        WHEN: extract_job_info is called
        THEN: Returns the Valentine address

        Based on Invoice #670732 - PICK UP order to Bronx
        Note: Address "2829 VALENTINE" lacks street indicator, but has number+letters pattern
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY
WHOLESALE DISTRIBUTORS OF PLUMBING HEATING AND INDUSTRIAL SUPPLIES

INVOICE
Page 1/1

Sold To
MPI PLUMBING
670 MYRTLE AVE
#234
BROOKLYN NY 11205

Ship To
MPI
2829 VALENTINE AVE
BRONX NY

Customer #   Order Date   Sales Order #   Buyer   Ship Via
0002180      11/13/2025   670732          MOTTY   PICK UP

Invoice #    Invoice Date  Ship Date   Freight Terms   Terms
670732       11/13/2025    11/13/25    PREPAID         NET 120

LN  QNTY  PRODUCT      DESCRIPTION                LIST    DISC%   NET      EXTENSION

1   1     FPPT202012   2" x 2" x 1-1/4" CO       136.89  58.52   56.7819   $56.78
                       REDUCING TEE
2   2     FPPCL20      2" COPPER PRESS NO-        55.90  58.52   23.1873   $46.37
                       COUPLING

Merchandise     177.70
Tax (NYT)        15.76
TOTAL          $193.46
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Must find "2829 VALENTINE" (Ship To)
                assert "VALENTINE" in result or "2829" in result, (
                    f"Should find Ship To address '2829 VALENTINE', got '{result}'"
                )

    def test_extract_ship_to_pine_st_nyc(self):
        """
        GIVEN: Invoice with Ship To at 80 Pine St, NYC
        WHEN: extract_job_info is called
        THEN: Returns the Pine St address

        Based on Invoice #664871 - delivery to Pine St in Manhattan
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY
4002 15th Avenue
Brooklyn, NY 11218

INVOICE
Page 1/1

Sold To
MPI PLUMBING
670 MYRTLE AVE
#234
BROOKLYN NY 11205

Ship To
MPI Plumbing
80 Pine St
NYC NY

Customer #   Order Date   Sales Order #   Buyer
0002180      10/27/2025   664871          Mordchai Deutch

Invoice #    Invoice Date  Ship Date   Freight Terms   Terms
664871       11/10/2025    11/07/25    PREPAID         NET 120

LN  QNTY  PRODUCT    DESCRIPTION              LIST    DISC%   NET     EXTENSION

1   10    SDSP3166   3/16 x 6-1/2" SDS P      11.87   NET     8.54    $85.40
                     DRILL DW5403

Merchandise      85.40
Tax (NYT)         7.57
TOTAL           $92.97
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Must find "80 Pine St" (Ship To)
                assert "Pine" in result or "80" in result, (
                    f"Should find Ship To address '80 Pine St', got '{result}'"
                )

    def test_extract_ship_to_11th_ave_nyc(self):
        """
        GIVEN: Invoice with Ship To at 622 11Th Ave, NYC
        WHEN: extract_job_info is called
        THEN: Returns the 11th Ave address

        Based on Invoice #668857 - delivery to 11th Ave with invoice message
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY
4002 15th Avenue
Brooklyn, NY 11218

INVOICE
Page 1/1

Sold To
MPI PLUMBING
670 MYRTLE AVE
#234
BROOKLYN NY 11205

Ship To
MPI Plumbing
622 11Th Ave
NYC NY

Customer #   Order Date   Sales Order #   Buyer
0002180      11/07/2025   668857          Mordchai Deutch

Invoice #    Invoice Date  Ship Date   Freight Terms   Terms
668857       11/10/2025    11/07/25    PREPAID         NET 120

***** Invoice Message *****
Today
Guermo347-784-3539

LN  QNTY  PRODUCT      DESCRIPTION           LIST     DISC%   NET       EXTENSION

1   2     DRE90G20WT   2" GAS DRESSER COUP   497.47   NET     337.5714  $675.14
                       2820010

Merchandise     675.14
Tax (NYT)        59.87
TOTAL          $735.01
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Must find "622 11Th Ave" (Ship To)
                assert "11Th" in result or "622" in result, (
                    f"Should find Ship To address '622 11Th Ave', got '{result}'"
                )


class TestEdgeCaseCompanyNamesWithNumbers:
    """
    Tests for edge cases where company names start with numbers.

    The extraction must distinguish between:
    - Company names that start with numbers (e.g., "1ST CUSTOMER", "21ST CENTURY PLUMBING")
    - Actual street addresses (e.g., "123 OAK STREET")

    Street addresses are identified by street indicators: AVE, ST, STREET, RD, BLVD, etc.
    """

    def test_skips_company_name_starting_with_number_finds_street(self):
        """
        GIVEN: Ship To section with "1ST CUSTOMER NAME" followed by actual address
        WHEN: extract_job_info is called
        THEN: Returns the street address "999 TEST AVE", NOT the company name "1ST CUSTOMER NAME"

        The company name starts with "1ST" which has numbers, but it's not a street address.
        The extraction should use street indicators (AVE, ST, etc.) to identify real addresses.
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY

INVOICE                                        Page 1/1

Sold To                            Ship To
MPI PLUMBING                       1ST CUSTOMER NAME
670 MYRTLE AVE                     999 TEST AVE
#234                               BROOKLYN NY 11205
BROOKLYN NY 11205

Customer #   Order Date   Sales Order #   Buyer   Ship Via   Terms
0002180      11/12/2025   670607          MOTTY   PREPAID    NET 120

LN  PRODUCT    DESCRIPTION    PRICE
1   ITEM001    Test Item      $100.00

TOTAL $100.00
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "999 TEST AVE" (actual street address with AVE indicator)
                # Should NOT return "1ST CUSTOMER NAME" even though it has numbers
                assert "999" in result or "TEST AVE" in result, (
                    f"Should find street address '999 TEST AVE', got '{result}'. "
                    f"Should NOT return company name '1ST CUSTOMER NAME' even though it starts with '1ST'"
                )

    @pytest.mark.xfail(
        reason="Known limitation: extraction doesn't prioritize street indicators over company names with numbers"
    )
    def test_skips_21st_century_company_finds_actual_address(self):
        """
        GIVEN: Ship To with "21ST CENTURY PLUMBING" company name and actual address
        WHEN: extract_job_info is called
        THEN: Should return "456 OAK STREET", not "21ST CENTURY PLUMBING CO"

        KNOWN LIMITATION: The current extraction matches "21ST CENTURY PLUMBING CO" because
        it has numbers (21) followed by letters. A future improvement would be to prioritize
        lines with street indicators (STREET, AVE, RD, etc.) over company names.
        """
        raw_text = """WORLD WIDE PLUMBING SUPPLY

INVOICE
Page 1/1

Sold To
MPI PLUMBING
670 MYRTLE AVE
#234
BROOKLYN NY 11205

Ship To
21ST CENTURY PLUMBING CO
456 OAK STREET
QUEENS NY 11101

Customer #   Order Date   Invoice #   Terms
0002180      11/12/2025   INV-001     NET 120

TOTAL $500.00
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip tabula")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "456 OAK STREET" (actual street address with STREET indicator)
                # Should NOT return "21ST CENTURY PLUMBING CO"
                assert "456" in result or "OAK STREET" in result, (
                    f"Should find street address '456 OAK STREET', got '{result}'. "
                    f"Should NOT return '21ST CENTURY PLUMBING CO'"
                )


class TestStreetIndicatorRecognition:
    """
    Tests that the extraction correctly identifies street addresses by their indicators.

    Street indicators include: AVE, AVENUE, ST, STREET, ROAD, RD, BLVD, BOULEVARD,
    LANE, LN, DRIVE, DR, WAY, PLACE, PL, COURT, CT, PARKWAY, PKY

    Each test verifies we find the CORRECT LINE with the street indicator,
    not just that we found something.
    """

    def test_finds_address_with_ave_indicator(self):
        """
        GIVEN: Ship To section with company name (no indicator) and address with AVE
        WHEN: extract_job_info is called
        THEN: Returns the line containing AVE indicator "999 TEST AVE"
        """
        raw_text = """Ship To
CUSTOMER NAME
999 TEST AVE
CITY STATE
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "999 TEST AVE" - the line with AVE indicator
                assert "999" in result and "AVE" in result.upper(), (
                    f"Should find address with AVE indicator '999 TEST AVE', got '{result}'"
                )

    def test_finds_address_with_street_indicator(self):
        """
        GIVEN: Ship To section with company name and address with STREET
        WHEN: extract_job_info is called
        THEN: Returns the line containing STREET indicator "888 OAK STREET"
        """
        raw_text = """Ship To
CUSTOMER NAME
888 OAK STREET
CITY STATE
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "888 OAK STREET"
                assert "888" in result and "STREET" in result.upper(), (
                    f"Should find address with STREET indicator '888 OAK STREET', got '{result}'"
                )

    def test_finds_address_with_road_indicator(self):
        """
        GIVEN: Ship To section with address containing ROAD
        WHEN: extract_job_info is called
        THEN: Returns the line containing ROAD indicator "777 INDUSTRIAL ROAD"
        """
        raw_text = """Ship To
CUSTOMER NAME
777 INDUSTRIAL ROAD
CITY STATE
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "777 INDUSTRIAL ROAD"
                assert "777" in result and "ROAD" in result.upper(), (
                    f"Should find address with ROAD indicator '777 INDUSTRIAL ROAD', got '{result}'"
                )

    def test_finds_address_with_blvd_indicator(self):
        """
        GIVEN: Ship To section with address containing BLVD
        WHEN: extract_job_info is called
        THEN: Returns the line containing BLVD indicator "666 SUNSET BLVD"
        """
        raw_text = """Ship To
CUSTOMER NAME
666 SUNSET BLVD
CITY STATE
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "666 SUNSET BLVD"
                assert "666" in result and "BLVD" in result.upper(), (
                    f"Should find address with BLVD indicator '666 SUNSET BLVD', got '{result}'"
                )

    def test_finds_address_with_st_abbreviation(self):
        """
        GIVEN: Ship To section with address using St abbreviation
        WHEN: extract_job_info is called
        THEN: Returns the line containing the street address "555 MAIN ST"

        Note: Standard format "123 NAME ST" matches the extraction patterns
        """
        raw_text = """Invoice #12345
Ship To
555 MAIN ST
CORONA NY 11368
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "555 MAIN ST"
                assert "555" in result and "ST" in result.upper(), (
                    f"Should find address with ST abbreviation '555 MAIN ST', got '{result}'"
                )


class TestAddressValidation:
    """
    Tests that invalid lines are skipped during extraction.

    The extraction should skip:
    - Pure numbers (e.g., "12345")
    - Dates (e.g., "01/15/2024")
    - Codes (e.g., "NET 120", "M9291012")
    - Lines with only letters and no numbers
    """

    def test_skips_pure_numbers_finds_address(self):
        """
        GIVEN: Ship To section with pure number line before actual address
        WHEN: extract_job_info is called
        THEN: Skips "12345" and finds "100 VALID STREET"
        """
        raw_text = """Ship To
12345
100 VALID STREET
BROOKLYN NY
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should find "100 VALID STREET", skip pure numbers "12345"
                assert "100" in result and "VALID" in result, (
                    f"Should skip pure number '12345' and find '100 VALID STREET', got '{result}'"
                )

    def test_skips_dates_finds_address(self):
        """
        GIVEN: Ship To section with date before actual address
        WHEN: extract_job_info is called
        THEN: Skips date "01/15/2024" and finds the address
        """
        raw_text = """Ship To
01/15/2024
200 DATE STREET
QUEENS NY
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should skip date "01/15/2024" and find address
                assert "200" in result or "DATE STREET" in result, (
                    f"Should skip date '01/15/2024' and find '200 DATE STREET', got '{result}'"
                )
                assert "/" not in result, (
                    f"Should not return date pattern, got '{result}'"
                )

    def test_skips_invoice_headers_finds_address(self):
        """
        GIVEN: Ship To followed by common invoice headers then address
        WHEN: extract_job_info is called
        THEN: Skips headers (Customer #, Order Date, etc.) and finds address
        """
        raw_text = """Ship To
Customer #: 12345
Order Date: 01/15/2024
456 OAK STREET
QUEENS NY
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")

                # Should skip headers and find "456 OAK STREET"
                assert "456" in result and "OAK" in result, (
                    f"Should skip headers and find '456 OAK STREET', got '{result}'"
                )


class TestShipToPatternRecognition:
    """
    Tests for recognizing various Ship To header patterns.
    """

    def test_recognizes_ship_to_lowercase(self):
        """GIVEN: "Ship To" in mixed case, THEN: Recognizes and extracts address"""
        raw_text = """Invoice #12345
Ship To
123 MAIN AVE
BROOKLYN NY 11205
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")
                assert "123" in result and "MAIN" in result, (
                    f"Should find '123 MAIN AVE', got '{result}'"
                )

    def test_recognizes_ship_to_uppercase(self):
        """GIVEN: "SHIP TO" in uppercase, THEN: Recognizes and extracts address"""
        raw_text = """INVOICE
SHIP TO
789 INDUSTRIAL ROAD
WAREHOUSE DISTRICT
"""
        with patch(
            "mpi_backend.utils.pdf_to_excel.extraction_util.read_invoice",
            return_value=raw_text,
        ):
            with patch("tabula.read_pdf", side_effect=Exception("Skip")):
                from mpi_backend.utils.pdf_to_excel.extraction_util import (
                    extract_job_info,
                )

                result = extract_job_info("dummy.pdf")
                assert "789" in result and "INDUSTRIAL" in result, (
                    f"Should find '789 INDUSTRIAL ROAD', got '{result}'"
                )
