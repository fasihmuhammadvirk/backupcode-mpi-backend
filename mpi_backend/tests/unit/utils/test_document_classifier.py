"""Unit tests for document_classifier.py

Tests the public API using real extracted text from InvoicesByType/ samples.
Mock strategy: patch _read_first_page so that _extract_header_text (called internally
by DocumentClassifier.classify) returns real PDF text without touching the filesystem.
"""

import pytest
from unittest.mock import patch

from mpi_backend.utils.document_classifier import (
    DocumentClassifier,
    DocumentType,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Real extracted text from InvoicesByType/ samples (first 15 lines each)
# ---------------------------------------------------------------------------

BMW_INVOICE_TEXT = """\
Invoice
Date
12/16/2019
Invoice #
176855
Bill To
MPI PLUMBING CORP
Ship To
MPI PLUMBING CORP
795 FRANKLIN AVE
1 917 662 7069
BMW PLUMBING SUPPLIES NY INC.
199 Lee Ave. #678
BROOKLYN, NY 11211
P.O. No."""

FLOWMARK_INVOICE_TEXT = """\
FLOWMARK PLUMBING SUPPLY
P: 845-244-4999
E: SALES@FLOWMARKSUPPLY.COM
S: it starts from the flow
382 NY-59
AIRMONT, NY, 10952, USA
Customer: MPI PLUMBING - 2892 NOSTRAND
Page 1 of 2
Invoice I-0008871
Invoice I-0008871
Bill to
Ship to
MPI PLUMBING - 2892 NOSTRAND
670 Myrtle Avenue
#234"""

SUPREME_INVOICE_TEXT = """\
Page 1 of 1
179 Lincoln Ave - Suite L-9
Orange, NJ, 07050, USA
Supreme Plumbing Supply
F:
E:
P:
orders@supremeplumbingnj.com
973-840-7788
Invoice I-0058941
Customer: MPI PLUMBING CORP
Date
Due Date
Rep
PO #"""

PARK_INVOICE_TEXT = """\
INVOICE
Page
1/1
Sold To
Ship To
Customer #
Order Date
Sales Order #
Buyer
Customer P/O #
Ship Via
Salesman
Invoice #
Invoice Date
Ship Date"""

YS_INVOICE_TEXT = """\
INVOICE
Y&S Plumbing & Heating Supply
962 Washington Ave
Bronx, NY 10456
Phone 718-400-1818
Fax
718-604-4522
Page
1/4
Sold To
Ship To
Customer #
Order Date
Sales Order #
Buyer"""

BMW_CREDIT_MEMO_TEXT = """\
Credit Memo
Date
12/16/2019
Credit No.
176975
Customer
MPI PLUMBING CORP
Ship To
MPI PLUMBING CORP
zevi
BMW PLUMBING SUPPLIES NY INC.
199 Lee Ave. #678
BROOKLYN, NY 11211
Project
Phone #"""

BMW_CREDIT_TEXT = """\
CREDIT
Page
1/1
Sold To
Ship To
Customer #
Order Date
Sales Order #
Buyer
Customer P/O #
Ship Via
Salesman
Invoice #
Invoice Date
Ship Date"""

PYRAMID_CREDIT_TEXT = """\
CREDIT
Page
1/1
Sold To
Ship To
Customer #
Order Date
Sales Order #
Buyer
Customer P/O #
Ship Via
Salesman
Invoice #
Invoice Date
Ship Date"""

FLOWMARK_CREDIT_TEXT = """\
FLOWMARK PLUMBING SUPPLY
P: 845-244-4999
E: SALES@FLOWMARKSUPPLY.COM
S: it starts from the flow
382 NY-59
AIRMONT, NY, 10952, USA
Customer: MPI PLUMBING - 19 MONTAUK AVE.
Page 1 of 2
Customer Credit CR-0000609
Customer Credit CR-0000609
Billing Address
Shipping Address
MPI PLUMBING - 19 MONTAUK AVE.
670 Myrtle Avenue
#234"""

# Real S3 header text from CR-0000881 (exact first page output from fitz)
FLOWMARK_CREDIT_CR0000881_TEXT = """\
FLOWMARK PLUMBING SUPPLY
P: 845-244-4999
E: SALES@FLOWMARKSUPPLY.COM
S: IT STARTS FROM THE FLOW
382 NY-59
AIRMONT, NY, 10952, USA
CUSTOMER: MPI PLUMBING
PAGE 1 OF 1
CUSTOMER CREDIT CR-0000881
CUSTOMER CREDIT CR-0000881
BILLING ADDRESS
SHIPPING ADDRESS
MPI PLUMBING
670 MYRTLE AVENUE
#234"""

WWPS_STATEMENT_TEXT = """\
STATEMENT
MPI PLUMBING
Statement Date
04/01/21
670 MYRTLE AVE
Customer Account 0002180
#234
Terms NET 30
BROOKLYN, NY 11205
F
- Before Invoice Number Denotes Finance Charge.
OA - Before Invoice Number Denotes Payment On Account.
CM - Before Invoice Number Denotes Credit Memo.
DM - Before Invoice Number Denotes Charge Back.
Invoice"""

SALES_ORDER_TEXT = """\
Sales Order Recap
09:25 09/18/23 BW
Page 1/6
BR/WHSE USER
Order #
B/O
Rel
118141 00 00
01/01
EK
S
MPI PLUMBING CORP
S
MPI PLUMBING CORP
O T"""

PAYMENT_RECEIPT_TEXT = """\
Supreme Plumbing Supply
P: 973-840-7788
E: orders@supremeplumbingnj.com
314 Dodd Street
East Orange, NJ, 07017, USA
Page 1 of 1
Customer: MPI PLUMBING CORP
Payment Receipt
From
MPI PLUMBING CORP
Date Paid
Payment Method
Card Type
09/11/2025
Credit Card"""

PACKING_SLIP_TEXT = """\
Supreme Plumbing Supply
973-840-7788
P:
orders@supremeplumbingnj.com
835 Bloomfield Ave
Clifton
NJ, 07012
E:
F:
Packing Slip 0085294
Customer: MPI PLUMBING TAX EXEMPT
Page 1 of 1
Packing Slip 0085294
Bill to
Ship to"""

SUPREME_STATEMENT_TEXT = """\
Supreme Plumbing Supply
P: 973-840-7788
E: orders@supremeplumbingnj.com
314 Dodd Street
East Orange, NJ, 07017, USA
Statement of Accounts
Bill to
Summary
MPI PLUMBING CORP
Balance Forward
$0.00
Open Invoices
$1,372.57
Payments not Applied
$0.00"""

AF_INVOICE_TEXT = """\
I N V O I C E
REMIT PAYMENT TO   
AF SUPPLY CORPORATION
1000 SOUTH 2ND STREET
HARRISON NJ  07029
AF BROOKLYN
942LAFAYETTE AVENUEBROOKLYNNY
TEL 718.443.6900       FAX  718.443.0474"""

AF_STATEMENT_TEXT = """\
1121932
01
11/22/2024 9000178116           778.46 
1121807
01
11/22/2024 9000178117         4,165.36 
1121348     19+ MO
01
11/27/2024 9000182156        12,341.50 
1112925
01
11/27/2024 9000181286         1,538.32 
11181100
01
11/27/2024 9000181288           387.76 
-----------------------
BALANCE 03/03/2025 USD 
          19,211.40 
BILLING ADDRESS
MPI PLUMBING CORP
670 MYRTLE AVE #234
BROOKLYN NY  11205
CUSTOMER PO#
DOC
DOCUMENT
AF INVOICE
AMOUNT
TYPE
DATE
CURRENT
OVERDUE 1-30
OVERDUE 31-60
OVERDUE 61-90
OVERDUE 91+
ACCT BALANCE
             0.00              0.00              0.00         12,341.50          6,869.90 
$19,211.40 
DOCUMENT TYPE: 01=INVOICE; 06=CHARGE BACK; 11=CREDIT MEMO; 15=PAYMENT; 16=PAYMENT DIFFERENCE
AF SUPPLY CORP. 
1000 SOUTH 2ND ST
HARRISON, NJ 07029
PH:  973-481-7500 FAX: 862-772-4129
AF STATEMENT
INFORMATION
CUSTOMER NUMBER
MPIPLUMB
STATEMENT DATE
03/03/2025
YOUR PAYMENT TERMS
NT00
OPEN ITEM LIST ON
03/03/2025
PAGE  1   OF    1"""


BRUCE_INVOICE_TEXT = """\
INVOICE
BSCFEINR
JOB NO.
SLS
R
E
M
I
T
T
O
S
O
L
D"""

BRUCE_STATEMENT_TEXT = """\
STATEMENT
BSCESTMR
CODES
REMIT TO
PAGE NO.
STATEMENT DATE
CUSTOMER NO.
PAGE NO.
STATEMENT DATE
CUSTOMER NO.
JOB NO.
REFERENCE NO.
BR #
DATE
CD"""

PE_INVOICE_TEXT = """\
SOLD TO:
SHIP TO:
SUB TOTAL
DISCOUNT
NYS SALES TAX

ORDER # 
DATE ORDERED 
PO # 
SHIP VIA 
TERMS 
LINES
 LINE 
ORDER  
SHIP 
B/O 
DESCRIPTION 
LIST 
DISCOUNT 
UNIT 
AMOUNT
ACCOUNT #
INVOICE #
DATE:
PAGE #
PLUMBING 
EXCHANGE
THE
182 10TH STREET • BROOKLYN, NY  11215
PHONE:718.499.6700 • FAX:718.499.6716
SALES@THEPLUMBINGEXCHANGE.COM
INVOICE"""

PE_ORDER_CONFIRMATION_TEXT = """\
TO:
 
PO # 
SHIP VIA 
COMMENT 
TERMS 
LINES
 
 
QUANTITY 
 
 
 
UNIT 
EXTENDED 
 LINE 
ORDER 
DESCRIPTION 
LIST PRICE 
DISCOUNT 
PRICE  
PRICE
PLUMBING 
EXCHANGE
THE
182 10TH STREET • BROOKLYN, NY  11215
PHONE:718.499.6700 • FAX:718.499.6716
SALES@THEPLUMBINGEXCHANGE.COM
ORDER CONFIRMATION
ACCOUNT #
QUOTE #
DATE:
PAGE #
SALE 
DISCOUNT
NYS SALES TAX
TOTAL"""

PE_QUOTE_TEXT = """\
PLUMBING 
EXCHANGE
THE
182 10TH STREET • BROOKLYN, NY  11215
QUOTE # 12345
DATE: 03/13/2026
PAGE # 1
This is a quotation for the requested materials.
"""

PE_CORRESPONDENCE_TEXT = """\
PLUMBING 
EXCHANGE
THE
182 10TH STREET • BROOKLYN, NY  11215
To whom it may concern,
Please find the attached documentation regarding our upcoming holiday hours.
Thank you!
"""


GOTHAM_BID_TEXT = """\
Bid Number:
Prepared For:
Branch Location:
Line
Quantity
Description
Unit Price
Discount
Net Unit Price
Extended Price


                                       MPI PLUMBING CORP - CASH            GOTHAM PIPE SUPPLY, LLC
                                       670 MYRTLE AVE                      18-19 Flushing Avenue
                                       BROOKLYN, NY  11205                 Ridgewood, NY  11385

                                                                           Telephone: 718-416-6300



 BID PROPOSAL
1 of 1
 9/06/22
QUOTE - GALV S40 PIPE
5759389"""

# ---------------------------------------------------------------------------
# Real text from misclassified PDFs (analysis/low_validation_invoices/)
# ---------------------------------------------------------------------------

# Payment / Receipt documents
YS_PAYMENT_RECEIPT_TEXT = """\
Y&S Plumbing & Heating Supply Inc.
244 Rogers Avenue
Brooklyn, NY 11225
Received From:
MPI PLUMBING CORP.
MPI Plumbing Corp
670 Myrtle Ave. #234
Brooklyn NY 11205
Date Received
03/20/2018
Payment Amount
$19,086.65
Payment Method
Check
Check/Ref. No."""

BMW_PAYMENT_RECEIPT_TEXT = """\
BMW PLUMBING SUPPLIES NY INC.
199 Lee Ave. #678
BROOKLYN, NY 11211
Received From:
MPI PLUMBING CORP #2
MPI PLUMBING CORP
Date Received
12/18/2020
Payment Amount
$8,500.00
Payment Method
Check
Check/Ref. No.
1208
Invoices Paid"""

PYRAMID_RECEIPT_TEXT = """\
RECEIPT
DATE : 27 JUN 2022
*** RECEIPT OF PAYMENT ***
MPI Plumbing Corp.
,
--------------------------------------------------------------------------------
Account Number
: 0004469
Check Number
: *CC*
Payment Date
: 27 JUN 2022
Amount
: $5696.72
Credit Card Info"""

CARDKNOX_PORTAL_TEXT = """\
CARD INFORMATION
Card type: Amex
Card expiration: 10/25
Card number: **** 3010
Cardholder name:
BILLING INFORMATION
MPI PLUMBING CORP
3479716499
ADDITIONAL INFORMATION
Entry method: Keyed
Reference Number: 845517692
Payment type: Credit Card
Authorization Code: 178370
Invoice: I-0068715
AVS:"""

# Delivery / Shipping documents
AF_POD_TEXT = """\
Proof of Delivery
Delivery#: 8002086809
Delivery Details
Ln#
Delivery#
Material
Description
Carton
Qty
QtyRcv
10
8002086809
INH1020
IMPORT NH PIPE 2X10 (68/SKID)
68"""

WWPS_POD_TEXT = """\
Proof of Delivery
Page
1/1
Sold To
Ship To
Customer #
Order Date
Sales Order #
Buyer
Customer P/O #
Ship Via
Salesman
Invoice #
Invoice Date
Ship Date"""

YS_SHIPMENT_CONF_TEXT = """\
Shipment Confirmation
Y&S Plumbing & Heating Supply
962 Washington Ave
Bronx, NY 10456
Phone 718-400-1818
Fax
718-604-4522
11:26 02/07/24 ST
Page 1/1
BR/WHSE USER
Order #
B/O
Rel
115335 00 00
02/02"""

WWPS_MATERIAL_RETURN_TEXT = """\
Material Returned
Date
8/29/2021
RET No.
13525
World Wide Plumbing
Returned From:
948 Myrtle
Total
Thank you for choosing MPI Plumbing. We hope to work with you again in the future.
Item
Description
Qty
FWT8050
8X5'' STD STRAIGHT TEES"""

# Order / Administrative documents
BMW_SALES_ORDER_TEXT = """\
SALES ORDER
10:28 02/26/26 EK
Page 1/1
BR/WHSE USER
Order #
B/O  Rel
210817 01 00
01/01   YN
S     MPI PLUMBING CORP                  S     MPI PLUMBING CORP
O T                                      H T   4212 Park Ave
L O                                      I O   Bronx,  NY 10457
D                                        P
Buyer: MOTTY,  347-633-5481
Tel 718-280-9049   Fax"""

WWPS_SALES_ORDER_TEXT = """\
SALES ORDER
09:33 02/08/23 MW
09:32 02/08/23 MW
Page 1/4
BR/WHSE USER REPRINT
Order #
B/O
Rel
388520 00 00
04/05
MW
1
S
MPI PLUMBING
S"""

SUPREME_CHANGE_ORDER_TEXT = """\
MPI Plumbing NY
Customer:
Change Order CO-0061951
973-840-7788
orders@supremeplumbingnj.com
P:
E:
F:
Supreme Plumbing Supply
179 Lincoln Ave - Suite L-9
Orange, NJ, 07050, USA
Page 1 of 2
Bill to
Ship to
Mpi, NY"""

BRUCE_ACKNOWLEDGEMENT_TEXT = """\
ACKNOWLEDGEMENT
BSCSA
PAYMENT TYPE
DOCUMENT NUMBER
DOCUMENT DATE
CUSTOMER NUMBER
WAREHOUSE
PAGE NO.
CUSTOMER P.O. NUMBER
JOB NAME
JOB NUMBER
WTR
SALES
ORDER DATE
SHIPPING METHOD"""

# Payment Stub documents
FLOWMARK_PAYSTUB_TEXT = """\
Bill Payment Stub
Check Date:
1/10/2025
Check No.:
1544
Check Amount:
74,115.64
MPI Plumbing Corp.
Brooklyn, NY 11205
670 Myrtle Ave. #234
Paid To: Flowmark Plumbing Supply
46 Main St, Unit 123
Spring Valley, NY 10977
Date
Type"""

# Submittal / Technical documents
GRUNDFOS_SUBMITTAL_TEXT = """\
Submittal Data
PROJECT:
REPRESENTATIVE:
ENGINEER:
CONTRACTOR:
UNIT TAG:
TYPE OF SERVICE:
SUBMITTED BY:
APPROVED BY:
ORDER NO.:
QUANTITY:
DATE:
DATE:
DATE:
Product photo could vary from the actual product"""

# Report documents (spaced letter headers)
YS_CASH_RECEIPTS_TEXT = """\
11:34:03am
19 Sep 2022
USER: Isaac
Page
1
Y & S
P l u m b i n g
&
H e a t i n g
S u p p l y
N Y
L L C
C A S H
R E C E I P T S
H I S T O R Y"""

PYRAMID_PAYMENT_HISTORY_TEXT = """\
14:14:25 20 NOV 2023
User: Rikki Koth
Page 1
P Y R A M I D
P L U M B I N G
S U P P L Y
I N C .
C U S T O M E R
P A Y M E N T
H I S T O R Y
f o r
2 3
Customer 0004469
MPI Plumbing Corp.
Phone 718-280-9049"""

# Quote / Estimate / Contract documents
WWPS_PRICE_QUOTE_TEXT = """\
PRICE QUOTE
Page 1
Printed 05/02/23 BS
Quoted
Ship To
MPI PLUMBING
THE MONARCH AT RIDGE HILL
670 MYRTLE AVE
701 RIDGE HILL BLVD
#234
YONKERS
NY
BROOKLYN NY 11205
Tel:845-783-5954 Fax:
Quote #"""

BMW_ESTIMATE_NEW_TEXT = """\
Estimate
Date
2/4/2021
Estimate #
12392
Name / Address
MPI PLUMBING CORP
160 Clarkson
RFQ #22740
BMW PLUMBING SUPPLIES
199 Lee Ave. #678
BROOKLYN, NY 11211
Total
Subtotal
Sales Tax  (8.875%)"""

BRUCE_CONTRACT_TEXT = """\
M560286
10/31/22
BRUCE SUPPLY CORP
8805 18th Avenue
Brooklyn, NY 11214
BRUCE SUPPLY CORP
8805 18th Avenue
Brooklyn, NY 11214
211946
MPI Plumbing Corp.
670 Myrtle Ave. #234
Brooklyn, NY 11205
Copper Tubing Contract
*** EXCLUDES ALL 5-6-8" SIZES OF TUBING ***
1"""

BRUCE_BID_BILL_TEXT = """\
Bid Number:
Prepared For:
Branch Location:
Line
Quantity
Description
Unit Price
Discount
Net Unit Price
Extended Price
MPI PLUMBING CORP                   BRUCE SUPPLY CORP.-18 AVE
670 MYRTLE AVE #234                 8805  18TH AVENUE
BROOKLYN, NY  11205                 BROOKLYN, NY  11214
Telephone: 718-259-4900
BID PROPOSAL"""


MOCK_TARGET = "mpi_backend.utils.document_classifier.DocumentClassifier._read_first_page"


# ---------------------------------------------------------------------------
# Bid classification
# ---------------------------------------------------------------------------

class TestBidClassification:

    @patch(MOCK_TARGET, return_value=GOTHAM_BID_TEXT)
    def test_gotham_bid_proposal(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.BID
        assert result.is_invoice_or_credit is True
        assert "BID" in result.details["match_reason"]


# ---------------------------------------------------------------------------
# Invoice classification
# ---------------------------------------------------------------------------

class TestInvoiceClassification:

    @patch(MOCK_TARGET, return_value=BMW_INVOICE_TEXT)
    def test_bmw_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 1.0

    @patch(MOCK_TARGET, return_value=FLOWMARK_INVOICE_TEXT)
    def test_flowmark_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 0.95

    @patch(MOCK_TARGET, return_value=SUPREME_INVOICE_TEXT)
    def test_supreme_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 0.95

    @patch(MOCK_TARGET, return_value=PARK_INVOICE_TEXT)
    def test_park_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 1.0

    @patch(MOCK_TARGET, return_value=YS_INVOICE_TEXT)
    def test_ys_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 1.0

    @patch(MOCK_TARGET, return_value=AF_INVOICE_TEXT)
    def test_af_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 1.0
        assert "Spaced INVOICE" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=BRUCE_INVOICE_TEXT)
    def test_bruce_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 1.0

    @patch(MOCK_TARGET, return_value=PE_INVOICE_TEXT)
    def test_pe_invoice(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert result.confidence == 0.95
        assert "PLUMBING EXCHANGE" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=PE_ORDER_CONFIRMATION_TEXT)
    def test_pe_order_confirmation(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert "ORDER CONFIRMATION" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=PE_QUOTE_TEXT)
    def test_pe_quote(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert "QUOTE" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=PE_CORRESPONDENCE_TEXT)
    def test_pe_generic_correspondence(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.details["match_reason"] == "default fallback"


# ---------------------------------------------------------------------------
# Credit classification
# ---------------------------------------------------------------------------

class TestCreditClassification:

    @patch(MOCK_TARGET, return_value=BMW_CREDIT_MEMO_TEXT)
    def test_bmw_credit_memo(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.CREDIT
        assert result.confidence == 1.0
        assert "CREDIT MEMO" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=BMW_CREDIT_TEXT)
    def test_bmw_credit(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.CREDIT
        assert result.confidence == 0.9

    @patch(MOCK_TARGET, return_value=PYRAMID_CREDIT_TEXT)
    def test_pyramid_credit(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.CREDIT
        assert result.confidence == 0.9

    @patch(MOCK_TARGET, return_value=FLOWMARK_CREDIT_TEXT)
    def test_flowmark_customer_credit(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.CREDIT
        assert result.confidence == 0.95

    @patch(MOCK_TARGET, return_value=FLOWMARK_CREDIT_CR0000881_TEXT)
    def test_flowmark_customer_credit_from_s3(self, _mock):
        """Real header text from CR-0000881 streamed from S3."""
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.CREDIT
        assert result.confidence == 0.95
        assert "CUSTOMER CREDIT" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=(
        "SOME VENDOR NAME\n"
        "123 Main St\n"
        "City, State, 12345\n"
        "Phone: 555-1234\n"
        "Page 1 of 1\n"
        "Customer: ACME CORP\n"
        "\n"
        "\n"
        "Customer Credit CR-9999\n"
        "Billing Address\n"
        "Shipping Address\n"
    ))
    def test_customer_credit_deep_in_header(self, _mock):
        """CUSTOMER CREDIT on line 9 with no other indicators."""
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.CREDIT
        assert result.confidence == 0.95


# ---------------------------------------------------------------------------
# Statement classification
# ---------------------------------------------------------------------------

class TestStatementClassification:

    @patch(MOCK_TARGET, return_value=WWPS_STATEMENT_TEXT)
    def test_wwps_statement(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.STATEMENT
        assert result.confidence == 1.0

    @patch(MOCK_TARGET, return_value=SUPREME_STATEMENT_TEXT)
    def test_supreme_statement_of_accounts(self, _mock):
        """Vendor header block pushes 'Statement of Accounts' to line 5."""
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.STATEMENT
        assert result.confidence == 0.95
        assert "extended header" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=AF_STATEMENT_TEXT)
    def test_af_statement(self, _mock):
        """AF Statement has 'AF STATEMENT' late in the document (line 43)."""
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.STATEMENT
        assert result.confidence == 0.95
        assert "AF STATEMENT" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=BRUCE_STATEMENT_TEXT)
    def test_bruce_statement(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.STATEMENT
        assert result.confidence == 1.0

    @patch(MOCK_TARGET, return_value=(
        "Supreme Plumbing Supply\n"
        "P: 973-840-7788\n"
        "E: orders@supremeplumbingnj.com\n"
        "314 Dodd Street\n"
        "East Orange, NJ, 07017, USA\n"
        "Statement of Accounts\n"
        "Bill to\n"
        "MPI PLUMBING CORP\n"
        "Date Description\n"
        "Invoice: I-0151486 $1,372.57\n"
        "Total Due $1,372.57"
    ))
    def test_statement_with_invoice_reference_not_misclassified(self, _mock):
        """Statement listing 'Invoice: I-xxxxx' must not match INVOICE pattern."""
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.STATEMENT
        assert result.confidence == 0.95


# ---------------------------------------------------------------------------
# Other document classification
# ---------------------------------------------------------------------------

class TestOtherDocumentClassification:

    @patch(MOCK_TARGET, return_value=SALES_ORDER_TEXT)
    def test_sales_order(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 1.0
        assert "SALES ORDER" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=PAYMENT_RECEIPT_TEXT)
    def test_payment_receipt(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 1.0
        assert "PAYMENT RECEIPT" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=PACKING_SLIP_TEXT)
    def test_packing_slip(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 1.0
        assert "PACKING SLIP" in result.details["match_reason"]

    @patch(MOCK_TARGET, return_value=(
        "SOME VENDOR\n"
        "CREDIT TERMS: NET 30\n"
        "123 Main St\n"
    ))
    def test_credit_terms_not_classified_as_credit(self, _mock):
        """'CREDIT TERMS' must NOT match -- it's an exclude pattern."""
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type != DocumentType.CREDIT


# ---------------------------------------------------------------------------
# Fallback / edge-case classification
# ---------------------------------------------------------------------------

class TestFallbackClassification:

    @patch(MOCK_TARGET, side_effect=Exception("corrupted PDF"))
    def test_empty_extraction(self, _mock):
        result = DocumentClassifier.classify("bad.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 0.0
        assert result.details["reason"] == "no_text_extracted"

    @patch(MOCK_TARGET, return_value="Lorem ipsum dolor sit amet\nconsectetur")
    def test_unrecognized_text(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 0.5
        assert result.details["match_reason"] == "default fallback"


# ---------------------------------------------------------------------------
# is_invoice_or_credit (via ClassificationResult property)
# ---------------------------------------------------------------------------

class TestIsInvoiceOrCredit:

    @patch(MOCK_TARGET, return_value=BMW_INVOICE_TEXT)
    def test_invoice_is_valid(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.is_invoice_or_credit is True
        assert result.doc_type == DocumentType.INVOICE

    @patch(MOCK_TARGET, return_value=BMW_CREDIT_MEMO_TEXT)
    def test_credit_is_valid(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.is_invoice_or_credit is True
        assert result.doc_type == DocumentType.CREDIT

    @patch(MOCK_TARGET, return_value=WWPS_STATEMENT_TEXT)
    def test_statement_is_invalid(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.is_invoice_or_credit is False
        assert result.doc_type == DocumentType.STATEMENT

    @patch(MOCK_TARGET, return_value=SALES_ORDER_TEXT)
    def test_other_is_invalid(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.is_invoice_or_credit is False
        assert result.doc_type == DocumentType.UNKNOWN

    @patch(MOCK_TARGET, return_value=BRUCE_STATEMENT_TEXT)
    def test_bruce_statement_is_invalid(self, _mock):
        result = DocumentClassifier.classify("any.pdf")
        assert result.is_invoice_or_credit is False
        assert result.doc_type == DocumentType.STATEMENT


# ---------------------------------------------------------------------------
# Payment / Receipt classification
# ---------------------------------------------------------------------------

class TestPaymentReceiptClassification:

    def test_pyramid_receipt(self):
        result = DocumentClassifier.classify("any.pdf", text=PYRAMID_RECEIPT_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 1.0
        assert "RECEIPT" in result.details["match_reason"]

    def test_ys_payment_receipt(self):
        """Y&S payment receipts have 'Payment Amount' but no INVOICE/RECEIPT header."""
        result = DocumentClassifier.classify("any.pdf", text=YS_PAYMENT_RECEIPT_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "PAYMENT" in result.details["match_reason"]

    def test_bmw_payment_receipt(self):
        """BMW payment receipts follow same pattern as Y&S."""
        result = DocumentClassifier.classify("any.pdf", text=BMW_PAYMENT_RECEIPT_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "PAYMENT" in result.details["match_reason"]

    def test_cardknox_portal(self):
        """Cardknox credit card portal page with Invoice reference must be OTHER."""
        result = DocumentClassifier.classify("any.pdf", text=CARDKNOX_PORTAL_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.doc_type != DocumentType.INVOICE


# ---------------------------------------------------------------------------
# Delivery / Shipping classification
# ---------------------------------------------------------------------------

class TestDeliveryShippingClassification:

    def test_af_proof_of_delivery(self):
        result = DocumentClassifier.classify("any.pdf", text=AF_POD_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "PROOF OF DELIVERY" in result.details["match_reason"]

    def test_wwps_proof_of_delivery(self):
        result = DocumentClassifier.classify("any.pdf", text=WWPS_POD_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "PROOF OF DELIVERY" in result.details["match_reason"]

    def test_ys_shipment_confirmation(self):
        result = DocumentClassifier.classify("any.pdf", text=YS_SHIPMENT_CONF_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "SHIPMENT CONFIRMATION" in result.details["match_reason"]

    def test_wwps_material_return(self):
        result = DocumentClassifier.classify("any.pdf", text=WWPS_MATERIAL_RETURN_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "MATERIAL RETURNED" in result.details["match_reason"]


# ---------------------------------------------------------------------------
# Order / Administrative classification
# ---------------------------------------------------------------------------

class TestOrderAdminClassification:

    def test_bmw_sales_order(self):
        result = DocumentClassifier.classify("any.pdf", text=BMW_SALES_ORDER_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "SALES ORDER" in result.details["match_reason"]

    def test_wwps_sales_order(self):
        result = DocumentClassifier.classify("any.pdf", text=WWPS_SALES_ORDER_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "SALES ORDER" in result.details["match_reason"]

    def test_supreme_change_order(self):
        result = DocumentClassifier.classify("any.pdf", text=SUPREME_CHANGE_ORDER_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "CHANGE ORDER" in result.details["match_reason"]

    def test_bruce_acknowledgement(self):
        result = DocumentClassifier.classify("any.pdf", text=BRUCE_ACKNOWLEDGEMENT_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "ACKNOWLEDGEMENT" in result.details["match_reason"]

    def test_flowmark_paystub(self):
        result = DocumentClassifier.classify("any.pdf", text=FLOWMARK_PAYSTUB_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "BILL PAYMENT STUB" in result.details["match_reason"]


# ---------------------------------------------------------------------------
# Submittal / Technical classification
# ---------------------------------------------------------------------------

class TestSubmittalClassification:

    def test_grundfos_submittal(self):
        result = DocumentClassifier.classify("any.pdf", text=GRUNDFOS_SUBMITTAL_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "SUBMITTAL DATA" in result.details["match_reason"]


# ---------------------------------------------------------------------------
# Spaced-letter report classification
# ---------------------------------------------------------------------------

class TestSpacedLetterClassification:

    def test_ys_cash_receipts_history(self):
        """Y&S uses spaced letters: 'C A S H  R E C E I P T S  H I S T O R Y'."""
        result = DocumentClassifier.classify("any.pdf", text=YS_CASH_RECEIPTS_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "CASH RECEIPTS" in result.details["match_reason"]

    def test_pyramid_customer_payment_history(self):
        """Pyramid uses spaced letters: 'C U S T O M E R  P A Y M E N T  H I S T O R Y'."""
        result = DocumentClassifier.classify("any.pdf", text=PYRAMID_PAYMENT_HISTORY_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "CUSTOMER PAYMENT" in result.details["match_reason"]


# ---------------------------------------------------------------------------
# Quote / Estimate / Contract classification
# ---------------------------------------------------------------------------

class TestQuoteEstimateClassification:

    def test_wwps_price_quote(self):
        result = DocumentClassifier.classify("any.pdf", text=WWPS_PRICE_QUOTE_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "QUOTE" in result.details["match_reason"]

    def test_bmw_estimate(self):
        """BMW estimates have 'Estimate' on line 1 -- should match existing ESTIMATE rule."""
        result = DocumentClassifier.classify("any.pdf", text=BMW_ESTIMATE_NEW_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN

    def test_bruce_contract(self):
        """Copper Tubing Contract from Bruce Supply."""
        result = DocumentClassifier.classify("any.pdf", text=BRUCE_CONTRACT_TEXT)
        assert result.doc_type == DocumentType.UNKNOWN
        assert "CONTRACT" in result.details["match_reason"]

    def test_bruce_bid(self):
        """Bruce Supply bid documents should match existing BID rules."""
        result = DocumentClassifier.classify("any.pdf", text=BRUCE_BID_BILL_TEXT)
        assert result.doc_type == DocumentType.BID
        assert "BID" in result.details["match_reason"]




