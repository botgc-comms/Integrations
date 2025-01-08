import requests
from requests.auth import HTTPBasicAuth
from .get_competition_startsheet import get_startsheet 
from bs4 import BeautifulSoup
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import logging
from applicationinsights import TelemetryClient
from azure.functions import HttpRequest, HttpResponse
import time
from azure.storage.blob import BlobServiceClient
import json
import re

class TableCell:
    def __init__(self, value, column):
        self.value = value
        self.column = column

    def __repr__(self):
        return f"TableCell(value={self.value}, column={self.column})"

    def to_dict(self):
        return {
            "value": self.value,
            "column": self.column
        }

class TableData:
    def __init__(self, headers, body):
        self.headers = headers
        self.body = body

    def to_dict(self):
        return {
            "headers": self.headers,
            "body": self.body
        }

# Define headers outside the functions as they are used in multiple places
headers = {
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "Origin": "https://www.botgc.co.uk",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.botgc.co.uk/login.php",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Initialize a session for persistent connections
session = requests.Session()

# Initialize Application Insights
app_insights_key = os.environ.get('APPINSIGHTS_INSTRUMENTATION_KEY')
tc = TelemetryClient(app_insights_key) if app_insights_key else None

def print_success(message):
    logging.info(message)
    if tc:
        tc.track_trace(message)
        tc.flush()

def print_error(message):
    logging.error(message)
    if tc:
        tc.track_trace(message, severity='ERROR')
        tc.flush()

def member_login():
    logging.info("Entering member_login")
    login_url = "https://www.botgc.co.uk/login.php"
    data = {
        "task": "login",
        "topmenu": "1",
        "memberid": os.environ["MEMBER_ID"],
        "pin": os.environ["MEMBER_PIN"],
        "cachemid": "1",
        "Submit": "Login"
    }
    response = session.post(login_url, headers=headers, data=data, verify=False)
    if response.ok:
        print_success("First login successful!")
    else:
        print_error("First login failed.")
        logging.error("First login failed with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting member_login with failure")
        return False

    logging.info("Exiting member_login with success")
    return True

def execute_report(compid, config):
    logging.info(f"Entering execute_report for comp id {compid}")

    grossOrNet = 1 if config.get("grossOrNet", "gross") == "net" else 2

    #report_url = f"https://www.botgc.co.uk/competition.php?tab=details&compid={compid}&preview=1&div=0&sort={grossOrNet}"
    report_url = f"https://www.botgc.co.uk/competition.php?tab=details&compid={compid}&preview=1&div=ALL&fulldetail=2"
    logging.info(f"report_url: {report_url}")
    
    response = session.get(report_url)

    if response.ok:
        print_success("Successfully accessed the report.")
        logging.debug("Report content: %s", response.content)
        logging.info("Exiting execute_report with success")
        return BeautifulSoup(response.content, 'html5lib') 
    else:
        print_error("Failed to access the report.")
        logging.error("Failed to access report with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting execute_report with failure")
        return None

def read_config():
    # Environment variables for Azure Storage account details
    connection_string = os.getenv('DATA_CONTAINER_CONNECTION_STRING')
    container_name = 'data'
    blob_name = 'competitions.json'

    # Initialize the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    # Download the configuration file
    config_data = blob_client.download_blob().readall()
    config = json.loads(config_data)

    return config

def read_config_local():
    config_file_path = os.path.join(os.path.dirname(__file__), '..', 'common', 'data', 'competitions.json')

    logging.info(f"Retrieving config from {config_file_path}")

    # Load the configuration file
    with open(config_file_path, 'r') as config_file:
        config = json.load(config_file)

    return config

def extract_cleaned_table_data(soup):
    logging.info("Entering extract_cleaned_table_data")
    if soup is None:
        logging.warning("Soup is None, returning empty data list")
        return TableData(headers=[], body=[])

    table = soup.find('table')
    if not table:
        logging.warning("No tables found, returning empty data list")
        return TableData(headers=[], body=[])

    headers = []
    rows = []

    # Extract headers (assuming they are in thead or the first row of tbody)
    thead = table.find('thead')
    if thead:
        header_rows = thead.find_all('tr')
    else:
        # If no thead, try to find headers in the first row of tbody
        header_rows = [table.find('tbody').find('tr')]

    for tr in header_rows:
        cols = tr.find_all(['th', 'td'])  # Headers can be in th or td
        header_data = []
        col_index = 1  # Start with column 1
        for col in cols:
            col_text = ' '.join(col.get_text().split())
            colspan = int(col.get('colspan', 1))  # Get colspan, default is 1
            if col_text:  # Only include non-empty values
                header_data.append(TableCell(value=col_text, column=col_index))
            col_index += colspan  # Move to the next available column, accounting for colspan
        if header_data:
            headers.append(header_data)

    # Extract body rows
    body_rows = table.find('tbody').find_all('tr')

    for tr in body_rows:
        cols = tr.find_all('td')
        row_data = []
        col_index = 1  # Start with column 1

        for col in cols:
            col_text = ' '.join(col.get_text().split())
            colspan = int(col.get('colspan', 1))  # Get colspan, default is 1
            if col_text:  # Only include non-empty values
                row_data.append(TableCell(value=col_text, column=col_index))
            col_index += colspan  # Move to the next available column, accounting for colspan

        if row_data:  # Only include rows with data
            rows.append(row_data)

    logging.info("Extracted and cleaned table data with headers and body.")

    return TableData(headers=headers, body=rows)


def identify_name_column(data):
    """
    Identify the column that most likely contains names with optional handicaps.
    """
    for col_index in range(len(data[0])):  # Iterate over column indices
        match_count = 0
        for row in data:  # Iterate over each row
            logging.info(row)
            cell = row[col_index].value  # Get the individual cell in the current column
            if isinstance(cell, str) and re.match(r"^[a-zA-Z]{3,}\s[a-zA-Z\'\s]+(?:\([-\d]+\))?$", cell):
                match_count += 1

        if match_count > len(data) // 2:  # If more than half the rows match, consider it the name column
            return col_index

    return None

def extract_name_and_handicap(data, destination):
    """
    Extract names and handicaps from the identified column, remove that column from the dataset,
    and append the extracted data to the destination.
    """
    logging.info(data)

    name_col_index = identify_name_column(data.body)

    if name_col_index is None:
        logging.error("Name column not found in the data.")
        raise ValueError("Name column not found in the data.")

    for row in data.body:
        value = row.pop(name_col_index).value
        match = re.match(r"^([a-zA-Z\-]{3,}\s[a-zA-Z\'\-\s]+)(?:\(([-\d]+)\))?$", value)
        if match:
            name = match.group(1).strip()
            handicap = int(match.group(2)) if match.group(2) else None
            destination.append({'name': name, 'handicap': handicap})
        else:
            logging.warning(f"Could not match name and handicap in row: {row}")

    return data

# Child Function 2: Extract Position
def extract_position(data, destination):
    for row in data.body:
        for i, cell in enumerate(row):
            value = cell.value
            if re.match(r"^\d+(?:st|nd|rd|th)$", value):  # Match 1st, 2nd, 3rd, etc.
                position = int(value[:-2])  # Remove the suffix (st, nd, etc.)
                row.pop(i)  # Remove position column from the row
                for dest in destination:
                    if 'position' not in dest:
                        dest['position'] = position
                        break
                break
    
    for row in data.body:
        for i, cell in enumerate(row):
            value = cell.value
            if re.match(r"^\d+(?:st|nd|rd|th)$", value):  # Match 1st, 2nd, 3rd, etc.
                position = int(value[:-2])  # Remove the suffix (st, nd, etc.)
                row.pop(i)  # Remove position column from the row
                for dest in destination:
                    if 'position' not in dest:
                        dest['position'] = position
                        break
                break

def extract_gross_score(data, destination):
    # Step 1: Find the "Gross" column in the headers based on the column property
    gross_column_index = None
    for header_row in data.headers:
        for i, cell in enumerate(header_row):
            if cell.value == "Gross":
                gross_column_index = cell.column  # Get the column property (1-based index)
                header_row.pop(i)  # Remove the "Gross" header from the headers
                break
        if gross_column_index is not None:
            break
    
    if gross_column_index is None:
        logging.warning("Gross column not found in headers.")
        return

    # Step 2: Extract the values from the "Gross" column in the body based on column property
    for row, dest in zip(data.body, destination):
        for i, cell in enumerate(row):
            if cell.column == gross_column_index:  # Match the column property
                gross_score = cell.value
                dest['grossScore'] = gross_score
                row.pop(i)  # Remove the "Gross" cell from the row in the body
                break  # We found and removed the cell, no need to continue in this row

def extract_nett_score(data, destination):
    # Step 1: Find the "net" column in the headers based on the column property
    nett_column_index = None
    for header_row in data.headers:
        for i, cell in enumerate(header_row):
            if cell.value == "Nett":
                nett_column_index = cell.column  # Get the column property (1-based index)
                header_row.pop(i)  # Remove the "net" header from the headers
                break
        if nett_column_index is not None:
            break
    
    if nett_column_index is None:
        logging.warning("Nett column not found in headers.")
        return

    # Step 2: Extract the values from the "net" column in the body based on column property
    for row, dest in zip(data.body, destination):
        for i, cell in enumerate(row):
            if cell.column == nett_column_index:  # Match the column property
                nett_score = cell.value
                dest['nettScore'] = nett_score
                row.pop(i)  # Remove the "net" cell from the row in the body
                break  # We found and removed the cell, no need to continue in this row

def extract_countback(data, destination):
    # Regular expression to match a string with four decimal numbers separated by commas
    countback_pattern = r"^\d+\.\d{4},\s*\d+\.\d{4},\s*\d+\.\d{4},\s*\d+\.\d{4}$"

    # Step 1: Find the "Countback" column based on the pattern in the body
    countback_column_index = None
    for row in data.body:
        for i, cell in enumerate(row):
            if re.match(countback_pattern, cell.value):  # If it matches the countback pattern
                countback_column_index = cell.column
                break
        if countback_column_index is not None:
            break
    
    if countback_column_index is None:
        logging.warning("No countback column found in data.")
        return

    # Step 2: Assign the countback values to the destination objects
    for row, dest in zip(data.body, destination):
        for i, cell in enumerate(row):
            if cell.column == countback_column_index:
                # Split the countback string into its components
                countback_values = cell.value.split(',')
                if len(countback_values) == 4:
                    dest['countback'] = {
                        'back9': float(countback_values[0].strip()),
                        'back6': float(countback_values[1].strip()),
                        'back3': float(countback_values[2].strip()),
                        'back1': float(countback_values[3].strip())
                    }
                row.pop(i)  # Remove the countback column from the row
                break

def extract_status(data, destination):
    status_column_index = None
    status_pattern = r"^[+-]\d+$"  # Regex pattern for numbers starting with "+" or "-"

    # Step 1: Check if "Status" is present in the headers
    for header_row in data.headers:
        for i, cell in enumerate(header_row):
            if cell.value == "Status":
                status_column_index = cell.column  # Get the column number for "Status"
                header_row.pop(i)  # Remove the "Status" header
                break
        if status_column_index is not None:
            break
    
    # Step 2: Verify if the column contains valid status values (numbers starting with + or -, or blank)
    if status_column_index is not None:
        valid_status = True
        for row in data.body:
            for cell in row:
                if cell.column == status_column_index:
                    # Allow blank values in the status column
                    if cell.value != "" and not re.match(status_pattern, cell.value):
                        valid_status = False
                        break
            if not valid_status:
                break
        
        # If the "Status" header was found but the values are invalid, reset the column index
        if not valid_status:
            logging.info("Status header found but values are not valid. Searching for a valid column.")
            status_column_index = None

    # Step 3: If no valid "Status" column found by header, search for a column with +/- values
    if status_column_index is None:
        possible_status_columns = set()
        for row in data.body:
            for cell in row:
                if re.match(status_pattern, cell.value):
                    possible_status_columns.add(cell.column)
        
        # If only one column contains valid status values, use it
        if len(possible_status_columns) == 1:
            status_column_index = possible_status_columns.pop()

    if status_column_index is None:
        logging.warning("No valid status column found.")
        return

    # Step 4: Extract status values and remove the column from the table
    for row, dest in zip(data.body, destination):
        for i, cell in enumerate(row):
            if cell.column == status_column_index:
                dest['status'] = cell.value if cell.value != "" else None  # Assign status or None if blank
                row.pop(i)  # Remove the status column from the row
                break  # Move to the next row after extracting

def extract_thru(data, destination):
    numeric_pattern = r"^\d+$"  # Pattern to match numeric values
    thru_header_found = False

    # Step 1: Check if "Thru" is present in the headers
    for header_row in data.headers:
        for i, cell in enumerate(header_row):
            if cell.value == "Thru":
                thru_header_found = True
                header_row.pop(i)  # Remove the "Thru" header from the headers
                break
        if thru_header_found:
            break

    if not thru_header_found:
        logging.warning("No 'Thru' header found. Skipping extraction.")
        return

    # Step 2: Identify columns that contain numeric or empty values in the body
    numeric_columns = set()
    for row in data.body:
        for cell in row:
            # Consider a column valid if it has numeric values or is empty
            if cell.value == "" or re.match(numeric_pattern, cell.value):
                numeric_columns.add(cell.column)

    # Step 3: If there is only one numeric column left, it's the "Thru" column
    if len(numeric_columns) == 1:
        thru_column_index = numeric_columns.pop()
    else:
        logging.warning("Multiple numeric columns found, unable to reliably identify 'Thru'.")
        return

    # Step 4: Extract the "Thru" values and remove the column from the data
    for row, dest in zip(data.body, destination):
        for i, cell in enumerate(row):
            if cell.column == thru_column_index:
                dest['thru'] = cell.value if cell.value != "" else None  # Assign the thru value or None if empty
                row.pop(i)  # Remove the "Thru" column from the row
                break  # Move to the next row after extracting

def calculate_handicap(data, destination):
    for item in destination:
        # Check if both "nettScore" and "grossScore" are present and "handicap" is not set
        if 'nettScore' in item and 'grossScore' in item and 'handicap' not in item:
            try:
                # Calculate handicap as nettScore - grossScore
                nett = int(item['nettScore'])
                gross = int(item['grossScore'])
                item['handicap'] = gross - nett
            except ValueError:
                logging.warning(f"Invalid nettScore or grossScore values in item: {item}")

def extract_competition_name(soup, data, competition):
    global_div = soup.find('div', class_='global')

    if global_div:
        h3_element = global_div.find('h3')
        
        # Check if the h3 was found and extract its contents
        if h3_element:
            competition["name"] = h3_element.get_text()
        else:
            logging.warning('H3 element not found within the div.')
    else:
        logging.warning('Div with class "global" not found.')

# Master Function
def process_data(soup, data):
    destination = []

    # Array of child functions to extract data
    extraction_functions = [
        extract_name_and_handicap,
        extract_position,
        extract_gross_score, 
        extract_nett_score, 
        calculate_handicap,
        extract_status,
        extract_thru,
        extract_countback
    ]

    # Array of post-processing functions
    post_processing_functions = [
        extract_competition_name
    ]

    logging.info(data)

    competition = {}

    # Apply each extraction function
    for func in extraction_functions:
        func(data, destination)

    # Apply each post-processing function (operating on destination)
    for func in post_processing_functions:
        func(soup, destination, competition)

    return competition, destination, data

def execute(req: HttpRequest):

    results = []

    # Extract the 'compid' parameter from the query string
    compid = req.params.get('compid')
    config = read_config()

    if not compid:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            compid = req_body.get('compid')

    # Log the compid for debugging
    logging.info(f"Received compid: {compid}")

    if member_login():
        soup = execute_report(compid, config)

        #startsheet = get_startsheet(compid)

        data = extract_cleaned_table_data(soup)
        comp, data, remaining = process_data(soup, data)

        remaining_body = [[cell.to_dict() for cell in row] for row in remaining.body]
        remaining_headers = [[cell.to_dict() for cell in row] for row in remaining.headers]

        combined = {
            "competition": comp,
            "matched": data, 
            "remaining": remaining_body, 
            "headings": remaining_headers
        }

        logging.info(data)

        if comp is not None and data is not None:
            #results = process_competition_results(comp, data, config)
            logging.info(f"Competition Name: {comp} data: {data} results: {results}")

        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()
    
    return combined