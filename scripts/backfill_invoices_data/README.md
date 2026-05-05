# Invoice Data Extraction Script

This script processes invoices by extracting data using both Gemini and OpenAI models, then stores the extracted data in the database. It supports two modes: processing files from S3 or processing local files.

## Overview

The script:
1. Extracts invoice data (line items, amounts, dates, etc.) using both Gemini and OpenAI models
2. Validates the extracted data
3. Stores the results in the `model_extracted_data` database table
4. Handles retries and error cases

## Prerequisites

- Python 3.x
- PostgreSQL database with the required tables (`invoices`, `suppliers`, `model_extracted_data`)
- Required Python packages (install via pip/requirements.txt):
  - `psycopg2` (PostgreSQL adapter)
  - `boto3` (AWS SDK for S3 operations)
  - `openai` (OpenAI API client)
  - `google-genai` (Google Gemini API client)
  - `pydantic` (Data validation)
  - `python-dotenv` (Environment variable management)

## Environment Variables

Create a `.env` file in the project root with the following variables:

### Database Configuration
```env
POSTGRES_DB=mpi_backend
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### AWS S3 Configuration (required for S3 mode)
```env
PUBLIC_ACCESS_KEY=your_access_key
SECRET_ACCESS_KEY=your_secret_key
REGION=us-east-1
BUCKET_NAME=nl-mpi-storage
```

### API Keys
```env
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key
```

## Usage

### S3 Mode

Process invoices by fetching them from the database and downloading files from S3:

```bash
python main.py --mode s3
```

**How it works:**
- Fetches all invoices from the database
- Constructs S3 file paths as `{supplier_name}/{invoice_id}.pdf` for each invoice
- Downloads each invoice file from S3
- Retrieves supplier information for each invoice
- Processes each invoice with both Gemini and OpenAI extraction models
- Stores extracted line items in the database

### Local Mode

Process invoices using local file paths from the database:

```bash
python main.py --mode local
```

**How it works:**
- Fetches all invoices from the database
- Uses the `storage_path` field from each invoice as the local file path
- Retrieves supplier information for each invoice
- Processes each invoice with both Gemini and OpenAI extraction models
- Stores extracted line items in the database

**Note:** Local mode does not require additional command-line arguments. It processes all invoices in the database using their `storage_path` values.

## Command-Line Arguments

| Argument | Required | Choices | Description |
|----------|----------|---------|-------------|
| `--mode` | Yes | `s3`, `local` | Operation mode |

## Data Extraction

The script uses two AI models for extraction:
- **Gemini**: `gemini-2.5-flash` model with structured JSON output using Pydantic schemas
- **OpenAI**: `gpt-4.1-mini` model with structured JSON output

The script extracts the following fields for each line item:
- `item`: Item name/product code
- `description`: Description of the product/service
- `qty`: Quantity
- `cost`: Unit price before tax
- `amount`: Total amount (quantity × unit price)
- `date`: Invoice date (MM/DD/YYYY format)
- `ref_no`: Invoice reference number
- `po_no`: Purchase order number (optional)
- `customer_job`: Customer job number or ID
- `bill`: Bill information (optional)
- `vendor`: Vendor/company name
- `class_`: Invoice class (optional)
- `memo`: Memo field (optional)
- `buyer`: Buyer information (optional for most suppliers, required for some)

Each extraction includes a confidence score that is also stored in the database.

### Validation

The extracted data is validated based on supplier-specific requirements:
- Most suppliers require: `item`, `description`, `qty`, `cost`, `amount`, `date`, `ref_no`, `customer_job`, `vendor`
- Some suppliers (e.g., Flow Mark Plumbing Supply, Lion Hvac Supplies) also require `buyer`
- The validation ensures at least one valid product line item is present (excluding "10 Materials" entries)
- Each model retries up to 5 times if validation fails

### Data Comparison and Status

The script compares extracted data from both models line by line:
- **If both models extract the same item**: Both records are marked with status `model_approved`
- **If models extract different items**: Both records are marked with status `human_review_required`
- **If only one model extracts an item**: That record is marked with status `human_review_required`

This comparison allows for automatic approval of consistent extractions while flagging discrepancies for human review.

## Output

The script outputs:
- Processing status for each invoice
- Extraction status for both Gemini and OpenAI models
- Database insertion confirmations with record IDs
- Error messages if extraction or validation fails

Example output:
```
Running in S3 mode - fetching invoices from database...
Downloading file from S3 for invoice abc-123
Processing invoice abc-123
Extracting data using Gemini for invoice abc-123
Extracting data using OpenAI for invoice abc-123
Adding data to database for invoice abc-123
New record inserted with ID: 42
New record inserted with ID: 43
```

Each line item from both models is stored as a separate record with its corresponding status.

## Error Handling

- The script validates extracted data before storing based on supplier-specific requirements
- Failed extractions are logged but don't stop processing of other invoices
- Each extraction model retries up to 5 times if:
  - API calls fail
  - Data validation fails
  - JSON parsing errors occur
- Database connection errors are caught and reported
- If one model fails but the other succeeds, the successful extraction is still stored with `human_review_required` status

## Files Structure

```
backfill_invoices_data/
├── main.py                    # Main script entry point
├── db_utils.py                # Database operations
├── s3.py                      # S3 file download utilities
├── data_extraction.py         # Unified extraction logic for both Gemini and OpenAI
├── data_validation.py         # Data validation utilities with supplier-specific rules
├── invoice_extraction_schema.py # Pydantic schemas for structured data extraction
└── README.md                  # This file
```

## Database Schema

The script stores extracted data in the `model_extracted_data` table with the following key fields:
- All extracted line item fields (item, description, qty, cost, amount, etc.)
- `model_name`: Either "gemini" or "openai"
- `confidence_score`: Confidence score from the extraction model
- `invoice_id`: Reference to the invoice being processed
- `status`: Either "model_approved" or "human_review_required"
- `file_path`: Local file path used for extraction
- `s3_file_key`: S3 key/path (for S3 mode) or empty string (for local mode)
- `raw_data`: Complete JSON of the extracted line item data

## Notes

- When running in S3 mode, ensure your AWS credentials are properly configured
- The script uses environment variables from `.env` file in the project root (three levels up from the script directory)
- Both models extract data independently and are compared line by line
- Items are stored separately for each model, allowing for comparison and quality assessment
- Each line item is stored as a separate record in the database
- The script automatically determines supplier-specific validation requirements based on supplier name or vendor field
