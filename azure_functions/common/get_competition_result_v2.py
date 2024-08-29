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
    report_url = f"https://www.botgc.co.uk/competition.php?tab=details&compid={compid}&preview=1&div=ALL"
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
        return []

    tables = soup.find_all('table')
    logging.info(f"Found {len(tables)} tables")

    all_tables_data = []

    for table in tables:
        rows = []
        body_rows = table.find('tbody').find_all('tr')
        
        for tr in body_rows:
            cols = tr.find_all('td')
            row_data = []

            for col in cols:
                # Clean the text: remove unnecessary whitespace and newlines
                col_text = ' '.join(col.get_text().split())
                if col_text:  # Only include non-empty values
                    row_data.append(col_text)

            if row_data:  # Only include rows with data
                rows.append(row_data)
        
        if rows:
            all_tables_data.extend(rows)  # Directly extend the list instead of appending nested lists

    logging.info(f"Extracted and cleaned table data: {all_tables_data}")
    return all_tables_data


def identify_name_column(data):
    """
    Identify the column that most likely contains names with optional handicaps.
    """
    for col_index in range(len(data[0])):  # Iterate over column indices
        match_count = 0
        for row in data:  # Iterate over each row
            cell = row[col_index]  # Get the individual cell in the current column
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
    name_col_index = identify_name_column(data)

    if name_col_index is None:
        logging.error("Name column not found in the data.")
        raise ValueError("Name column not found in the data.")

    for row in data:
        value = row.pop(name_col_index)
        match = re.match(r"^([a-zA-Z]{3,}\s[a-zA-Z\'\s]+)(?:\(([-\d]+)\))?$", value)
        if match:
            name = match.group(1).strip()
            handicap = int(match.group(2)) if match.group(2) else None
            destination.append({'name': name, 'handicap': handicap})
        else:
            logging.warning(f"Could not match name and handicap in row: {row}")

    return data

# Child Function 2: Extract Position
def extract_position(data, destination):
    for row in data:
        for i, value in enumerate(row):
            if re.match(r"^\d+(?:st|nd|rd|th)$", value):  # Match 1st, 2nd, 3rd, etc.
                position = int(value[:-2])  # Remove the suffix (st, nd, etc.)
                row.pop(i)  # Remove position column from the row
                for dest in destination:
                    if 'position' not in dest:
                        dest['position'] = position
                        break
                break

# Child Function 3: Extract Scores
def extract_scores(data, destination):
    for row in data:
        scores = []
        for i, value in enumerate(row):
            if re.match(r"^\d+$", value) or re.match(r"^\+\d+$", value):  # Match numeric scores
                scores.append(int(value))
        for dest in destination:
            if 'scores' not in dest:
                dest['scores'] = scores
                break
        row.clear()  # Remove all score columns from the row

# Master Function
def process_data(data):
    destination = []

    # Array of child functions
    extraction_functions = [
        extract_name_and_handicap,
        # extract_position,
        # extract_scores,
    ]

    # Apply each child function
    for func in extraction_functions:
        func(data, destination)

    return destination

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
        process_data(data)

        logging.info(data)

        if comp is not None and data is not None:
            results = process_competition_results(comp, data, config)
            logging.info(f"Competition Name: {comp} data: {data} results: {results}")

        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()
    
    logging.info(results)

    return results