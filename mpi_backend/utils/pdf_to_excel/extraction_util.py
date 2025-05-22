import re
import tabula
import fitz
regular_area = (290, 20, 290 + 415, 20 + 570)


def extract_job_info(filename):
    tables = tabula.read_pdf(filename, pages=1, area=(129, 317, 143 + 55, 317 + 274), guess=False)
    job_name = ""
    potential_job_names = [tables[0].columns[0]]
    job_name = potential_job_names[0]
    potential_job_names += list(tables[0][tables[0].columns[0]])
    for pjb in potential_job_names:
        if re.split('\W+', pjb)[0].isdigit():
            job_name = pjb
            break

    if job_name.count(" ") > 4: # threshold to identify if there are extra spaces
        job_name = job_name.replace(" ", "")
        job_name = re.sub(r'(?<!^)([A-Z])', r' \1', job_name)  # add space before capital letters

    return job_name


def extract_tax_etc(filename):
    tables = tabula.read_pdf(filename, pages="all", area=regular_area)
    financial_details_table = tabula.read_pdf(filename, pages=len(tables), area=(658, 425, 658 + 84, 425 + 165),
                                              guess=False)

    if 'M e rc h a n d is e' in str(financial_details_table[0].columns.values):
        financial_details_table = tabula.read_pdf(filename, pages=len(tables), area=(650.95, 410.77, 650+84, 430+164.67),
                                              guess=False)

        tax = str(financial_details_table[0]).split('T a x ( 00 4 )')[-1]
        tax = ''.join(tax.split())

        try:
            raw_text = read_invoice(filename)
            if 'Freight\n' in raw_text:
                freight = raw_text.split('Freight\n')[1].split('\n',1)[0].replace(',','').replace(' ','')
                freight = float(freight)
                return {'tax' : float(tax) + freight}
            else: return {'tax': tax}
        except:
            return {'tax': tax}

    if financial_details_table[0].shape[1] == 1:
        first_item = financial_details_table[0].columns[0]
        first_col = " ".join(first_item.split(" ")[:-1])
        second_col = first_item.split(" ")[-1]
        financial_details_table[0][first_col] = financial_details_table[0][first_item].str.split().str[:-1].str.join(
            " ")
        financial_details_table[0][second_col] = financial_details_table[0][first_item].str.split().str[-1]
        financial_details_table[0] = financial_details_table[0].reindex(columns=[first_col, second_col])

    financial_data = {}

    for i in range(len(financial_details_table[0])):
        fin_key = financial_details_table[0].iloc[i][0].lower()
        if not "taxable" in fin_key and not "total" in fin_key:
            try:
                value = float(financial_details_table[0].iloc[i][1].replace("$", "").replace(",", ""))
            except:
                value = 0
            # if "sub total" in fin_key:
            #     financial_data["sub total"] = value
            #     continue
            # elif "total" in fin_key:
            #     financial_data["total"] = value
            #     continue
            if "tax" in fin_key:
                financial_data["tax"] = value
                continue
            if value != 0:
                financial_data[fin_key] = value

    return financial_data


def extract_invoice_info(filename, pages =1, check = False ,supplier = "default"):
    invoice_num = ''
    invoice_date = ''
    tables = None

    if supplier == "default":
        # in case we need it in the future
        # tables = tabula.read_pdf(filename, pages=pages, area=(245, 21, 245 + 30, 21 + 160), guess=False,
        #                          columns=[20,98], pandas_options={'dtype': str})
        tables = tabula.read_pdf(
            filename,
            pages=pages,
            area=(245, 21, 300 + 30 , 21 + 160),  # Adjusted the area with the provided dimensions
            guess=False,
            columns=[20, 98],  # Adjust column positions (can tweak these as needed)
            pandas_options={'dtype': str}
        )

        try :
            if {'Unnamed: 0', 'Inv oi ce #', 'Inv oi ce D at e'}.issubset(tables[0].columns.values):
                if len(tables[0])==0: # if dataframe is empty - fix for misprinting / misplacement
                    tables = tabula.read_pdf(filename, pages=pages, area=(245, 21, 245 + 50, 21 + 160), guess=False,
                                             columns=[20, 98], pandas_options={'dtype': str})
                    tables[0].dropna(how='all', inplace=True)
                    tables[0].reset_index(inplace=True)
                invoice_num = str(tables[0]['Inv oi ce #'][0])
                invoice_date = tables[0]['Inv oi ce D at e'][0]
                invoice_num = ''.join(invoice_num.split()) # remove extra spaces
                invoice_date = ''.join(invoice_date.split())
            else:
                invoice_num = str(tables[0]['Invoice #'][0])
                invoice_date = tables[0]['Invoice Date'][0]
        except:
            return '', ''  # triggered in case no invoice num or date present

    elif supplier == "Ferguson":

        tables = tabula.read_pdf(filename, pages=pages, area=(33.84, 344.16, 56.88, 599.76), guess=False,
                                 columns=[344.16, 413.76,486.72,554.56], pandas_options={'dtype': str})

    # check will ensure that this file fulfills all criteria to be splited i.e is not supreme, page > 1 etc
    if check:
        # separate case for extraction of invoice num for all pages
        invoice_num = []

        for invoice_id in range(len(tables)):
            if supplier == "Ferguson":
                invoice_num.append(tables[invoice_id]['INVOICE NUMBER'][0])
            else:
                try:
                    invoice_num.append(tables[invoice_id]['Invoice #'][0])
                except:  invoice_num.append(tables[invoice_id]['Inv oi ce #'][0])
        return invoice_num

    return invoice_num, invoice_date


def extract_po(filename):
    tables = tabula.read_pdf(filename, pages=1, area=(215, 337, 215 + 30, 337 + 115), guess=False,
                             pandas_options={'dtype': str})
    po = ""
    if len(tables[0]):
        if {'C us tom e r P /O  #'}.issubset(tables[0].columns):
            po = tables[0]['C us tom e r P /O  #'][0]
            po = ''.join(po.split())
        else :
            po = tables[0]['Customer P/O #'][0]
    return po


def extract_buyer(filename):
    try:
        tables = tabula.read_pdf(filename, pages=1, area=(210, 243, 290, 243 + 94), guess=False,
                                 pandas_options={'dtype': str})

        if not tables or tables[0].empty:
            print("No table data found.")
            return ""

        df = tables[0]

        # Handle the specific case where buyer is split across two columns
        if 'Buyer' in df.columns and 'Unnamed: 0' in df.columns:
            first = str(df['Buyer'].iloc[0]).strip()
            last = str(df['Unnamed: 0'].iloc[0]).strip()
            return f"{first} {last}"

        elif 'Buyer' in df.columns:
            buyer_text = str(df['Buyer'].iloc[0]).strip()
            return buyer_text

        elif 'Bu ye r' in df.columns and 'Unnamed: 0' in df.columns:
            s = str(df['Bu ye r'].iloc[0]).strip()

            # First, check if it's a simple number or float
            try:
                # If it's a simple number or float, return as is
                float_val = float(s.replace(',', ''))
                return str(float_val) if float_val != int(float_val) else str(int(float_val))
            except ValueError:
                # Not a simple number, proceed with text processing
                pass

            # Try to extract phone number with various formats
            phone_patterns = [
                r'(\d[\s\(\)\-\d]{9,})',  # Matches phone numbers with various separators
                r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})',  # Standard US/Canada format
                r'(\(\d{3}\)\s*\d{3}[-.]?\d{4})',  # (123) 456-7890 format
                r'(\d{1}\s*\(\d{3}\)\s*\d{3}[-.]?\d{4})'  # 1 (123) 456-7890 format
            ]

            # Preserve original for fallback
            original_s = s
            # Remove any commas that might interfere with parsing
            s = s.replace(',', '')

            # Find the first matching phone number pattern
            phone_number = None
            for pattern in phone_patterns:
                match = re.search(pattern, s)
                if match:
                    phone_number = match.group(1).strip()
                    # Only use if we have a name before the number
                    if s.split(phone_number)[0].strip():
                        name = s.split(phone_number)[0].strip()
                        return f"{name} {phone_number}"

            # If no phone number found or no name before number, try to split by last space
            parts = re.match(r"([a-zA-Z\s]*)([\d\s\-\.]*)", original_s.replace(" ", ""))
            if parts:
                name, number = parts.group(1).strip(), re.sub(r"[^\d\.]", "", parts.group(2))
                if name and number:
                    # Format the number if it's long enough and looks like a phone number
                    if len(number) == 10 and '.' not in number:
                        number = re.sub(r"(\d{3})(\d{3})(\d{4})", r"(\1) \2-\3", number)
                    return f"{name} {number}"
                elif name:
                    return name
                elif number:
                    # If it's just a number, return it as is (could be a simple number or float)
                    try:
                        float_val = float(number)
                        return str(float_val) if float_val != int(float_val) else str(int(float_val))
                    except ValueError:
                        return number

        return s if 's' in locals() else ""

    except Exception as e:
        print("Error during PDF parsing:", e)
        return ""


def check_for_unique_invoices(filename, supplier):
    # file may have single invoice spanning over multiple pages
    unique_invoices = []

    if supplier == 'Supreme Plumbing Supply':
        with fitz.open(filename) as doc:
            for page in doc:
                text = page.get_text()
                invoice_data = text.split("Invoice", 1)
                invoice_data = invoice_data[1].split("\n", 1)
                invoice_data = invoice_data[0]
                if 8 < len(invoice_data) < 14:unique_invoices.append(invoice_data)

    elif supplier == 'AF Supply':
        with fitz.open(filename) as doc:
            for page in doc:
                text = page.get_text()
                invoice_data = text.split("INVOICE NO.", 1)
                invoice_data = invoice_data[1].split("\n", 2)
                invoice_data = invoice_data[1]
                if 8 < len(invoice_data) < 14:unique_invoices.append(invoice_data)

    elif supplier == 'Plumbing Exchange':
        with fitz.open(filename) as doc:
            for page in doc:
                try:
                    text = page.get_text()
                    invoice_num = text.split('mpip01', 1)[-1].split('\n \n', 2)[1].strip()
                except: continue
                if len(invoice_num) >= 5:unique_invoices.append(invoice_num)
    elif supplier == 'Lion Hvac Supplies':
        with fitz.open(filename) as doc:
            for page in doc:
                try:
                    text = page.get_text()
                    invoice_num = text.split('Invoice #:',1)[-1].split('\n',2)[0].strip()
                except: continue
                if len(invoice_num) >= 5: unique_invoices.append(invoice_num)

    elif supplier == "Ferguson":
        unique_invoices = extract_invoice_info(filename,'all',True,"Ferguson")

    else:

        unique_invoices = extract_invoice_info(filename, 'all', True)

    # adding break statement here
    if len(set(unique_invoices)) == 1:
        return False  # dont do anything if there is only one unique invoice id
    else:
        return True


def read_invoice(filename):
    text = ''
    with fitz.open(filename) as doc:
        for page in doc:
            text += page.get_text() +'\n'
    return text
