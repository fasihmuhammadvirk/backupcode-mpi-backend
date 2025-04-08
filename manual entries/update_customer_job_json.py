import pandas as pd
import json

# File paths
excel_file = "/Users/fasihmuhammadvirk/Downloads/mappings.xlsm"
json_file = "../mpi_backend/storage/fixtures/customer-job-mapping.json"

# Step 1: Load the Excel sheet, skip first 3 rows to reach the real header
df_raw = pd.read_excel(excel_file, sheet_name="Mappings", skiprows=3)

# Step 2: Strip all column names of whitespace
df_raw.columns = df_raw.columns.str.strip()

# Step 3: Show column names for verification (optional)
print("Columns found:", df_raw.columns.tolist())

# Step 4: Select and clean relevant columns
df_cleaned = df_raw[['Customer Job', 'Updated Customer Job']].dropna()

# Step 5: Rename columns for consistency
df_cleaned = df_cleaned.rename(columns={
    'Customer Job': 'customer_job',
    'Updated Customer Job': 'updated_customer_job'
})

# Final output preview
print(df_cleaned.head())
df = df_cleaned

# Load existing data
try:
    with open(json_file, 'r') as f:
        existing_data = json.load(f)
except FileNotFoundError:
    existing_data = []

# Create a set of existing pairs for fast lookup
existing_set = {(item['customer_job'], item['updated_customer_job']) for item in existing_data}

# Collect only new mappings
new_entries = []
for _, row in df.iterrows():
    print(row)
    customer_job = str(row['customer_job']).strip()
    updated_job = str(row['updated_customer_job']).strip()
    if (customer_job, updated_job) not in existing_set:
        new_entries.append({
            "customer_job": customer_job,
            "updated_customer_job": updated_job
        })

# Update the existing list
if new_entries:
    existing_data.extend(new_entries)

    # Write back to the same JSON file
    with open(json_file, 'w') as f:
        json.dump(existing_data, f, indent=4)

    print(f"✅ Added {len(new_entries)} new mappings.")
else:
    print("✅ No new mappings to add. JSON file is already up to date.")
