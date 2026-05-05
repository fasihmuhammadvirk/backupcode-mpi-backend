"""
Parse customer_job addresses using the usaddress library.

This script extracts distinct customer_job values from the database,
parses them using the usaddress library, and stores the results in
the parsed_customer_job_addresses table for dbt to consume.

Usage:
    python scripts/parse_customer_job_addresses.py [--batch-size N] [--force]

Options:
    --batch-size N  Number of addresses to process at a time (default: 500)
    --force         Re-parse all addresses even if they already exist

Dependencies:
    pip install usaddress python-dotenv psycopg2-binary
"""
import os
import re
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv

try:
    import usaddress
except ImportError:
    print("Error: usaddress library not installed. Run: pip install usaddress")
    exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

# Database connection parameters
db_params = {
    'dbname': os.getenv("POSTGRES_DB", "mpi_backend"),
    'user': os.getenv("POSTGRES_USERNAME", "postgres"),
    'password': os.getenv("POSTGRES_PASSWORD", ""),
    'host': os.getenv("POSTGRES_HOST", "localhost"),
    'port': os.getenv("POSTGRES_PORT", "5432")
}


def connect_to_db():
    """Establish database connection."""
    try:
        connection = psycopg2.connect(**db_params)
        logger.info("Connected to database successfully.")
        return connection
    except Exception as e:
        logger.exception(f"Error connecting to database: {e}")
        return None


def create_table_if_not_exists(conn):
    """Create the parsed_customer_job_addresses table if it doesn't exist."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS parsed_customer_job_addresses (
        id SERIAL PRIMARY KEY,
        customer_job TEXT UNIQUE NOT NULL,

        -- Parsed address components
        address_number TEXT,
        street_name_pre_directional TEXT,
        street_name TEXT,
        street_name_post_type TEXT,
        street_name_post_directional TEXT,
        occupancy_type TEXT,
        occupancy_identifier TEXT,
        place_name TEXT,
        state_name TEXT,
        zip_code TEXT,

        -- Cleaned/reconstructed address
        extracted_address TEXT,
        clean_street_address TEXT,

        -- Metadata
        parse_type TEXT,
        confidence TEXT,
        needs_manual_review BOOLEAN DEFAULT FALSE,
        raw_parse_result JSONB,
        prefix_removed TEXT,

        -- Timestamps
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_parsed_cja_customer_job
        ON parsed_customer_job_addresses(customer_job);
    CREATE INDEX IF NOT EXISTS idx_parsed_cja_confidence
        ON parsed_customer_job_addresses(confidence);
    """

    with conn.cursor() as cur:
        cur.execute(create_sql)
    conn.commit()
    logger.info("Table parsed_customer_job_addresses created/verified.")


def get_distinct_customer_jobs(conn, force: bool = False) -> List[str]:
    """Get distinct customer_job values that haven't been parsed yet.

    Pulls from both invoice_items and model_extracted_data tables.
    """
    query = """
    SELECT DISTINCT customer_job
    FROM (
        SELECT customer_job FROM invoice_items
        WHERE customer_job IS NOT NULL AND TRIM(customer_job) != ''
        UNION
        SELECT customer_job FROM model_extracted_data
        WHERE customer_job IS NOT NULL AND TRIM(customer_job) != ''
    ) all_jobs
    """

    if not force:
        query += """
    WHERE customer_job NOT IN (
        SELECT customer_job FROM parsed_customer_job_addresses
    )
    """

    query += " ORDER BY customer_job"

    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    return [row[0] for row in rows]


def clean_prefix(text: str) -> Tuple[str, Optional[str]]:
    """
    Remove common prefixes that appear before the actual address.
    Returns (cleaned_text, prefix_removed).
    """
    original = text
    prefix_removed = None

    # Common company name patterns
    company_patterns = [
        r'^(?:MPI\s+Plumbing|Mpi\s+Plumbing)(?:\s+Corp\.?)?\s*[-:]?\s*',
        r'^(?:MPI\s+Copper)\s*[-:]?\s*',
        r'^(?:ATT|Att|att):\s*',
        r'^(?:ATTN|Attn|attn):\s*',
        # Company names followed by colon (e.g., "Galaxy Developers:625 Fulton")
        # Handles: "Company LLC:addr", "Company, LLC:addr", "M & Y Inc:addr"
        r'^[A-Z][A-Za-z\s&]+,?\s*(?:LLC|Inc|Corp|Co|Ltd|LP|LLP)\.?\s*[:\-]\s*',
        # Just "LLC:" at the start (leftover from partial match)
        r'^(?:LLC|Inc|Corp|Co|Ltd|LP|LLP)\.?\s*[:\-]\s*',
        # Company names with colon pattern: "Name Name:Address"
        r'^[A-Z][A-Za-z\s]{2,30}:\s*(?=\d)',
    ]

    # Phone number patterns
    phone_patterns = [
        r'^\+?1?\s*[\(\-\.]?\s*\d{3}\s*[\)\-\.]?\s*\d{3}\s*[\-\.]?\s*\d{4}\s*',
    ]

    # Day/time patterns
    datetime_patterns = [
        r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*',
        r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*',
        r'^\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)\s+',
        r'^(?:TODAY|Today|ASAP|Asap)\s+',
    ]

    # Other noise patterns
    noise_patterns = [
        r'^Piggy\s+Back\s+',
        r'^PIGGY\s+BACK\s+',
        r'^[-–—]\s+',  # Leading dashes
    ]

    all_patterns = company_patterns + phone_patterns + datetime_patterns + noise_patterns

    for pattern in all_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            prefix_removed = match.group(0).strip()
            text = text[match.end():]

    # Recursively clean until no more prefixes found
    if text != original and prefix_removed:
        inner_text, inner_prefix = clean_prefix(text)
        if inner_prefix:
            prefix_removed = f"{prefix_removed} | {inner_prefix}"
        return inner_text, prefix_removed

    return text.strip(), prefix_removed


def deduplicate_address(text: str) -> str:
    """
    Remove duplicate street addresses.
    E.g., "69 Hope St. 69 Hope St. Brooklyn Ny" -> "69 Hope St. Brooklyn Ny"
    E.g., "- 1584 Fulton St 1584 Fulton St Brooklyn" -> "1584 Fulton St Brooklyn"
    """
    # Strip leading punctuation/dashes that might be left after prefix removal
    text = re.sub(r'^[-–—:,.\s]+', '', text).strip()

    # Find street number at the beginning
    match = re.match(r'^(\d+(?:-\d+)?)\s+', text, re.IGNORECASE)
    if not match:
        return text

    street_num = match.group(1)

    # Look for the same street number appearing again (case insensitive)
    pattern = re.escape(street_num) + r'\s+'
    matches = list(re.finditer(pattern, text, re.IGNORECASE))

    if len(matches) >= 2:
        # Return from second occurrence onwards
        second_pos = matches[1].start()
        return text[second_pos:].strip()

    return text


def strip_leading_city_name(text: str) -> str:
    """
    Remove leading city/borough names from address text.
    If the address starts with just a city name (no street number), strip it.

    Examples:
        "Brooklyn 123 Main St Brooklyn NY" -> "123 Main St Brooklyn NY"
        "Brooklyn NY 11201" -> "" (no street address)
        "Monroe NY 10949" -> "" (no street address)
    """
    # Known NYC boroughs and common city names
    cities = (
        r'Brooklyn|Queens|Bronx|The\s+Bronx|Manhattan|Staten\s+Island|'
        r'Jamaica|Flushing|Astoria|Forest\s+Hills|Mineola|Monroe|'
        r'New\s+York|NYC|Yonkers|Mount\s+Vernon|White\s+Plains'
    )

    # Pattern: City name at start, followed by optional comma, then either:
    # - Another city/state (no street address)
    # - A street number (has street address - keep the rest)
    # - End of string

    # Check if starts with city name
    city_start_match = re.match(
        rf'^({cities})\s*,?\s*',
        text,
        flags=re.IGNORECASE
    )

    if city_start_match:
        remainder = text[city_start_match.end():].strip()

        # Check if remainder starts with a street number (valid address continues)
        if re.match(r'^\d', remainder):
            return remainder

        # Check if remainder is just state/zip (no street address)
        # e.g., "NY 11201" or "NY, 11201" or just "NY"
        if re.match(r'^(NY|NJ|CT|PA|MA)\b', remainder, re.IGNORECASE):
            return ''  # No street address, return empty

        # Otherwise return remainder (might have more content)
        return remainder

    return text


def strip_cross_street_info(text: str) -> str:
    """
    Remove cross-street references from address text.

    Examples:
        "172-02 Hillside Ave Cor 173 St Jamaica" -> "172-02 Hillside Ave Jamaica"
        "123 Main St Corner of Oak Ave Brooklyn" -> "123 Main St Brooklyn"
        "456 Pine St Bet 5th and 6th Ave Queens" -> "456 Pine St Queens"
        "789 Oak Ave @ 42nd St Manhattan" -> "789 Oak Ave Manhattan"
    """
    # Pattern: Cross-street indicators followed by street reference
    # Cor, Corner, Bet, Between, Near, @, etc.
    cross_street_patterns = [
        # "Cor 173 St", "Corner of Oak Ave", "Corner Oak"
        r'\b(?:Cor|Corner)(?:\s+of)?\s+\d*\s*[A-Za-z]+(?:\s+(?:St|Ave|Blvd|Rd|Dr|Ln|Pl|Way|Ter|Ct))?\.?\s*',
        # "Bet 5th and 6th Ave", "Between Main and Oak"
        r'\b(?:Bet|Between)\s+[A-Za-z0-9]+(?:\s+(?:St|Ave|Blvd|Rd|Dr|Ln|Pl))?\.?\s+(?:and|&)\s+[A-Za-z0-9]+(?:\s+(?:St|Ave|Blvd|Rd|Dr|Ln|Pl))?\.?\s*',
        # "@ 42nd St", "@ Main Ave"
        r'@\s*\d*\s*[A-Za-z]+(?:\s+(?:St|Ave|Blvd|Rd|Dr|Ln|Pl|Way))?\.?\s*',
        # "Near Central Park", "Near 5th Ave"
        r'\bNear\s+[A-Za-z0-9]+(?:\s+[A-Za-z]+)*\s*',
    ]

    for pattern in cross_street_patterns:
        text = re.sub(pattern, ' ', text, flags=re.IGNORECASE)

    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def strip_phone_and_trailing_noise(text: str) -> str:
    """
    Remove phone numbers and trailing noise from address text.
    This should be called BEFORE sending to usaddress to prevent mislabeling.

    Examples:
        "1580 Story Avenue tel: 929-365 2278 The Bronx NY" -> "1580 Story Avenue The Bronx NY"
        "123 Main St Brooklyn NY 11201 Us" -> "123 Main St Brooklyn NY 11201"
        "159 Prospect Road Monroe, NY, 10950, US, tel: +1 (347) 740-7344" -> "159 Prospect Road Monroe NY 10950"
    """
    # Pattern 1: Remove "tel:", "phone:", "ph:", "call:", "fax:" and EVERYTHING after
    # until we hit a known city/borough or state. This handles names, +1 prefixes, etc.
    # Matches: "tel: +1 (347) 740-7344, Rolando" and everything after
    phone_label_pattern = r',?\s*\b(?:tel|phone|ph|call|fax)\s*[:.]?\s*.*$'
    text = re.sub(phone_label_pattern, '', text, flags=re.IGNORECASE)

    # Pattern 2: Remove standalone phone numbers with +1 prefix
    # Matches: "+1 (347) 740-7344", "+1 718-576-9873"
    phone_with_plus_pattern = r'\+?1?\s*\(?\d{3}\)?[\s\-\.]+\d{3}[\s\-\.]+\d{4}'
    text = re.sub(phone_with_plus_pattern, ' ', text, flags=re.IGNORECASE)

    # Pattern 3: Remove country codes and "Us" at the end
    # Matches: "Us", "USA", "United States" at end of string
    text = re.sub(r',?\s*(?:Us|USA|U\.S\.A\.?|United\s+States)\s*,?\s*$', '', text, flags=re.IGNORECASE)

    # Pattern 4: Remove trailing content after zip code
    # Match state + zip, then remove everything after
    truncate_match = re.search(
        r'\b([A-Z]{2}),?\s+(\d{5}(?:-\d{4})?)[,\s]+.+$',
        text,
        flags=re.IGNORECASE
    )
    if truncate_match:
        # Keep only up to the zip code
        end_pos = truncate_match.end(2)
        text = text[:end_pos]

    # Pattern 5: Remove trailing comma and whitespace
    text = re.sub(r',\s*$', '', text)

    # Clean up multiple spaces and commas
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r',\s*,', ',', text)  # Remove double commas

    return text


def parse_address(customer_job: str) -> Dict:
    """
    Parse a customer_job string into address components using usaddress.
    Returns a dictionary with parsed components and metadata.
    """
    result = {
        'customer_job': customer_job,
        'address_number': None,
        'street_name_pre_directional': None,
        'street_name': None,
        'street_name_post_type': None,
        'street_name_post_directional': None,
        'occupancy_type': None,
        'occupancy_identifier': None,
        'place_name': None,
        'state_name': None,
        'zip_code': None,
        'extracted_address': None,
        'clean_street_address': None,
        'parse_type': None,
        'confidence': 'low',
        'needs_manual_review': False,
        'raw_parse_result': None,
        'prefix_removed': None,
    }

    if not customer_job or not customer_job.strip():
        result['needs_manual_review'] = True
        return result

    # Step 1: Clean prefixes
    cleaned, prefix = clean_prefix(customer_job)
    result['prefix_removed'] = prefix

    # Step 2: Deduplicate repeated addresses
    cleaned = deduplicate_address(cleaned)

    # Step 3: Strip phone numbers and trailing noise before parsing
    cleaned = strip_phone_and_trailing_noise(cleaned)

    # Step 4: Strip cross-street references (e.g., "Cor 173 St", "Corner of Oak Ave")
    cleaned = strip_cross_street_info(cleaned)

    # Step 5: Strip leading city names (e.g., "Brooklyn NY 11201" -> "")
    cleaned = strip_leading_city_name(cleaned)
    result['extracted_address'] = cleaned

    # If nothing left after cleaning, mark as needing review
    if not cleaned or not cleaned.strip():
        result['needs_manual_review'] = True
        result['confidence'] = 'low'
        return result

    # Step 6: Try to parse with usaddress
    try:
        parsed, address_type = usaddress.tag(cleaned)
        result['parse_type'] = address_type
        result['raw_parse_result'] = json.dumps(parsed)

        # Map usaddress fields to our schema
        field_mapping = {
            'AddressNumber': 'address_number',
            'StreetNamePreDirectional': 'street_name_pre_directional',
            'StreetName': 'street_name',
            'StreetNamePostType': 'street_name_post_type',
            'StreetNamePostDirectional': 'street_name_post_directional',
            'OccupancyType': 'occupancy_type',
            'OccupancyIdentifier': 'occupancy_identifier',
            'PlaceName': 'place_name',
            'StateName': 'state_name',
            'ZipCode': 'zip_code',
        }

        for usaddress_field, our_field in field_mapping.items():
            if usaddress_field in parsed:
                result[our_field] = parsed[usaddress_field]

        # Normalize state name
        if result['state_name']:
            state = result['state_name'].upper().strip('.')
            state_map = {
                'NY': 'NY', 'N.Y.': 'NY', 'N.Y': 'NY', 'NEW YORK': 'NY',
                'NJ': 'NJ', 'N.J.': 'NJ', 'N.J': 'NJ', 'NEW JERSEY': 'NJ',
                'CT': 'CT', 'CONNECTICUT': 'CT',
            }
            result['state_name'] = state_map.get(state, state)

        # Build clean street address (just the street portion)
        street_parts = []
        if result['address_number']:
            street_parts.append(result['address_number'])
        if result['street_name_pre_directional']:
            street_parts.append(result['street_name_pre_directional'])
        if result['street_name']:
            street_parts.append(result['street_name'])
        if result['street_name_post_type']:
            street_parts.append(result['street_name_post_type'])
        if result['street_name_post_directional']:
            street_parts.append(result['street_name_post_directional'])

        result['clean_street_address'] = ' '.join(street_parts) if street_parts else None

        # Build extracted_address from parsed components
        # ONLY include street address (number + name + type + unit)
        # EXCLUDE city, state, zip - those are stored separately
        if result['address_number']:
            address_parts = []

            # Street address only
            if result['clean_street_address']:
                address_parts.append(result['clean_street_address'])

            # Unit/occupancy (e.g., "Apt 2B")
            if result['occupancy_type'] or result['occupancy_identifier']:
                unit_parts = []
                if result['occupancy_type']:
                    unit_parts.append(result['occupancy_type'])
                if result['occupancy_identifier']:
                    unit_parts.append(result['occupancy_identifier'])
                if unit_parts:
                    address_parts.append(' '.join(unit_parts))

            # Override extracted_address with just the street portion
            if address_parts:
                result['extracted_address'] = ' '.join(address_parts)
            else:
                result['extracted_address'] = None
        else:
            # No street number = no valid street address
            result['extracted_address'] = None

        # Determine confidence
        if result['address_number'] and result['state_name']:
            result['confidence'] = 'high'
        elif result['address_number']:
            result['confidence'] = 'medium'
        else:
            result['confidence'] = 'low'
            result['needs_manual_review'] = True

        # Mark as needing review if parse type is ambiguous
        if address_type == 'Ambiguous':
            result['needs_manual_review'] = True
            if result['confidence'] == 'high':
                result['confidence'] = 'medium'

    except usaddress.RepeatedLabelError as e:
        # This happens when the same label appears multiple times (e.g., phone numbers)
        # We can still extract the FIRST occurrence of each component
        logger.debug(f"RepeatedLabelError for '{customer_job}': {e}")
        result['parse_type'] = 'RepeatedLabelError'
        result['raw_parse_result'] = json.dumps({'error': str(e), 'parsed': e.parsed_string})
        result['needs_manual_review'] = True

        # Extract first occurrence of each component from parsed tokens
        parsed_tokens = e.parsed_string  # List of [token, label] pairs
        seen_labels = set()

        for token, label in parsed_tokens:
            # Skip if we've already seen this label (take first occurrence only)
            if label in seen_labels:
                continue
            seen_labels.add(label)

            # Clean the token (remove trailing commas/punctuation)
            token = token.rstrip('.,')

            # Map to our fields (first occurrence only)
            if label == 'AddressNumber' and not result['address_number']:
                result['address_number'] = token
            elif label == 'StreetNamePreDirectional' and not result['street_name_pre_directional']:
                result['street_name_pre_directional'] = token
            elif label == 'StreetName' and not result['street_name']:
                result['street_name'] = token
            elif label == 'StreetNamePostType' and not result['street_name_post_type']:
                result['street_name_post_type'] = token
            elif label == 'StreetNamePostDirectional' and not result['street_name_post_directional']:
                result['street_name_post_directional'] = token
            elif label == 'OccupancyType' and not result['occupancy_type']:
                result['occupancy_type'] = token
            elif label == 'OccupancyIdentifier' and not result['occupancy_identifier']:
                result['occupancy_identifier'] = token
            elif label == 'PlaceName' and not result['place_name']:
                result['place_name'] = token
            elif label == 'StateName' and not result['state_name']:
                result['state_name'] = token
            elif label == 'ZipCode' and not result['zip_code']:
                result['zip_code'] = token

        # Normalize state name
        if result['state_name']:
            state = result['state_name'].upper().strip('.')
            state_map = {
                'NY': 'NY', 'N.Y.': 'NY', 'N.Y': 'NY', 'NEW YORK': 'NY',
                'NJ': 'NJ', 'N.J.': 'NJ', 'N.J': 'NJ', 'NEW JERSEY': 'NJ',
                'CT': 'CT', 'CONNECTICUT': 'CT',
            }
            result['state_name'] = state_map.get(state, state)

        # Build clean street address
        street_parts = []
        if result['address_number']:
            street_parts.append(result['address_number'])
        if result['street_name_pre_directional']:
            street_parts.append(result['street_name_pre_directional'])
        if result['street_name']:
            street_parts.append(result['street_name'])
        if result['street_name_post_type']:
            street_parts.append(result['street_name_post_type'])
        if result['street_name_post_directional']:
            street_parts.append(result['street_name_post_directional'])

        result['clean_street_address'] = ' '.join(street_parts) if street_parts else None

        # Build extracted_address - ONLY street address (excludes city, state, zip)
        if result['address_number'] and result['clean_street_address']:
            result['extracted_address'] = result['clean_street_address']
        else:
            result['extracted_address'] = None

        # Determine confidence
        if result['address_number'] and result['state_name']:
            result['confidence'] = 'high'
        elif result['address_number']:
            result['confidence'] = 'medium'
        else:
            result['confidence'] = 'low'

    except Exception as e:
        logger.warning(f"Error parsing '{customer_job}': {e}")
        result['parse_type'] = 'Error'
        result['raw_parse_result'] = json.dumps({'error': str(e)})
        result['needs_manual_review'] = True
        result['confidence'] = 'low'

    return result


def upsert_parsed_addresses(conn, parsed_results: List[Dict]):
    """Insert or update parsed addresses in batch."""
    if not parsed_results:
        return 0

    upsert_sql = """
    INSERT INTO parsed_customer_job_addresses (
        customer_job, address_number, street_name_pre_directional,
        street_name, street_name_post_type, street_name_post_directional,
        occupancy_type, occupancy_identifier, place_name, state_name, zip_code,
        extracted_address, clean_street_address, parse_type, confidence,
        needs_manual_review, raw_parse_result, prefix_removed, updated_at
    ) VALUES %s
    ON CONFLICT (customer_job) DO UPDATE SET
        address_number = EXCLUDED.address_number,
        street_name_pre_directional = EXCLUDED.street_name_pre_directional,
        street_name = EXCLUDED.street_name,
        street_name_post_type = EXCLUDED.street_name_post_type,
        street_name_post_directional = EXCLUDED.street_name_post_directional,
        occupancy_type = EXCLUDED.occupancy_type,
        occupancy_identifier = EXCLUDED.occupancy_identifier,
        place_name = EXCLUDED.place_name,
        state_name = EXCLUDED.state_name,
        zip_code = EXCLUDED.zip_code,
        extracted_address = EXCLUDED.extracted_address,
        clean_street_address = EXCLUDED.clean_street_address,
        parse_type = EXCLUDED.parse_type,
        confidence = EXCLUDED.confidence,
        needs_manual_review = EXCLUDED.needs_manual_review,
        raw_parse_result = EXCLUDED.raw_parse_result,
        prefix_removed = EXCLUDED.prefix_removed,
        updated_at = EXCLUDED.updated_at
    """

    values = [
        (
            r['customer_job'], r['address_number'], r['street_name_pre_directional'],
            r['street_name'], r['street_name_post_type'], r['street_name_post_directional'],
            r['occupancy_type'], r['occupancy_identifier'], r['place_name'],
            r['state_name'], r['zip_code'], r['extracted_address'],
            r['clean_street_address'], r['parse_type'], r['confidence'],
            r['needs_manual_review'], r['raw_parse_result'], r['prefix_removed'],
            datetime.now()
        )
        for r in parsed_results
    ]

    with conn.cursor() as cur:
        execute_values(cur, upsert_sql, values)
    conn.commit()

    return len(values)


def main():
    parser = argparse.ArgumentParser(description='Parse customer_job addresses using usaddress')
    parser.add_argument('--batch-size', type=int, default=500,
                        help='Number of addresses to process per batch')
    parser.add_argument('--force', action='store_true',
                        help='Re-parse all addresses even if they already exist')
    args = parser.parse_args()

    conn = connect_to_db()
    if not conn:
        logger.error("Failed to connect to database. Exiting.")
        return 1

    try:
        # Create table if needed
        create_table_if_not_exists(conn)

        # Get addresses to parse
        customer_jobs = get_distinct_customer_jobs(conn, force=args.force)
        total = len(customer_jobs)

        if total == 0:
            logger.info("No new addresses to parse.")
            return 0

        logger.info(f"Found {total} addresses to parse.")

        # Process in batches
        processed = 0
        for i in range(0, total, args.batch_size):
            batch = customer_jobs[i:i + args.batch_size]

            # Parse each address
            parsed_results = []
            for customer_job in batch:
                result = parse_address(customer_job)
                parsed_results.append(result)

            # Upsert to database
            count = upsert_parsed_addresses(conn, parsed_results)
            processed += count

            logger.info(f"Processed {processed}/{total} addresses ({processed*100//total}%)")

        # Summary stats
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    confidence,
                    COUNT(*) as count
                FROM parsed_customer_job_addresses
                GROUP BY confidence
                ORDER BY confidence
            """)
            stats = cur.fetchall()

        logger.info("Parsing complete. Summary:")
        for stat in stats:
            logger.info(f"  {stat['confidence']}: {stat['count']} addresses")

        return 0

    finally:
        conn.close()


if __name__ == '__main__':
    exit(main())
