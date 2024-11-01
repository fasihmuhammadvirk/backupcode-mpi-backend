from fuzzywuzzy import fuzz
import re

ADDRESS_FILE = "mpi_backend/storage/fixtures/processed_addresses.txt"


def preprocess_address(address):
    replacements = {"Street": "St", "Avenue": "Ave", "Road": "Rd", "Drive": "Dr", "Place": "Pl"}

    for term, abbr in replacements.items(): # replace abbreviations
        address = re.sub(rf'\b{abbr}\b', term, address, flags=re.IGNORECASE)

    address = re.sub(r'\b\d+(?:-\d+)?\s', '', address) # remove street numbers from address
    return address.title()


def extract_street_number(address):
    pattern = r'\b\d+(?:-\d+)?\b'  # Match standalone number or range (e.g., 312-314, 32)
    match = re.search(pattern, address)
    return match.group(0) if match else None


def find_closest_match(new_addr, references, threshold=90):
    new_addr_processed = preprocess_address(new_addr)
    best_match = None
    highest_ratio = 0
    for ref in references:
        ratio = fuzz.ratio(new_addr_processed.lower(), ref.lower())
        if ratio > threshold and ratio > highest_ratio:
            best_match = ref
            highest_ratio = ratio
    return best_match


def map_address(new_address, customer_jobs):
    closest_match = find_closest_match(new_address, customer_jobs)
    street_number = extract_street_number(new_address)

    if closest_match: # the address pre-exists possibly with some variations
        mapped_address = f"{street_number} {closest_match}" if street_number else closest_match
    else: # this is new address
        preprocessed_address = preprocess_address(new_address)
        mapped_address = f"{street_number} {preprocessed_address}" if street_number else preprocessed_address
        customer_jobs.append(preprocessed_address)

        save_address(preprocessed_address)

    return mapped_address


def save_address(address):
    with open(ADDRESS_FILE, "a") as file:
        file.write(address + "\n")


def load_addresses():
    try:
        with open(ADDRESS_FILE, "r") as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []
