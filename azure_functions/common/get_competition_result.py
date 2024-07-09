import requests
from requests.auth import HTTPBasicAuth
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
    response = session.post(login_url, headers=headers, data=data)
    if response.ok:
        print_success("First login successful!")
    else:
        print_error("First login failed.")
        logging.error("First login failed with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting member_login with failure")
        return False

    logging.info("Exiting member_login with success")
    return True

def execute_report(compid):
    logging.info(f"Entering execute_report for comp id {compid}")

    report_url = f"https://www.botgc.co.uk/competition.php?compid={compid}"
    response = session.get(report_url)

    if response.ok:
        print_success("Successfully accessed the report.")
        logging.debug("Report content: %s", response.content)
        logging.info("Exiting execute_report with success")
        return BeautifulSoup(response.content, 'html.parser')
    else:
        print_error("Failed to access the report.")
        logging.error("Failed to access report with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting execute_report with failure")
        return None

def extract_data(soup):
    comp_name = ""

    logging.info("Entering extract_data")
    if soup is None:
        logging.warning("Soup is None, returning empty data list")
        return []

    global_div = soup.find('div', class_='global')
    if global_div:
        h3_element = global_div.find('h3')
        
        # Check if the h3 was found and extract its contents
        if h3_element:
            comp_name = h3_element.get_text()
        else:
            print_error('H3 element not found within the div.')
            logging.warning('H3 element not found within the div.')
    else:
        print_error('Div with class "global" not found.')
        logging.warning('Div with class "global" not found.')

    table = soup.find('table')
    if table is None:
        print_error("No table found in the provided HTML.")
        logging.warning("No table found in the provided HTML.")
        return []

    table_rows = []
    
    for tr in table.find_all('tr'):
        cols = tr.find_all('td')
        if len(cols) < 3:
            continue

        # Extract position as an integer
        position = cols[0].get_text(strip=True).rstrip('stndrh')
        if position.isdigit():
            position = int(position)
        else:
            continue

        # Extract name and handicap
        name_and_handicap = cols[1].get_text(strip=True)
        name = cols[1].find('a').get_text(strip=True)

        handicap = 999
        handicap_string = re.findall(r'\(([^)]+)\)', name_and_handicap)[0]
        if '+' in handicap_string:
            handicap_string = handicap_string.replace('+', '')
            handicap = -int(handicap_string)
        else:
            handicap = int(handicap_string)
        
        score_string = cols[2].find('a').get_text(strip=True)
        
        countback_results = cols[2].find('a')['title'].split(':')[-1].strip()

        result = {
            'position': position,
            'name': name,
            'handicap': handicap,
            'score': score_string,
            'countback_results': countback_results
        }

        logging.info(result)

        table_rows.append(result)
    
    logging.info("Exiting extract_data with %d rows", len(table_rows))
    return comp_name, table_rows

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

# Filter and sort competition results
def process_competition_results(competition_name, data, config):
    # Find the matching competition config
    competition_config = None
    for comp in config['competitions']:
        if re.match(comp['regex'], competition_name):
            competition_config = comp
            break
    
    if not competition_config:
        raise ValueError(f"No matching config found for competition: {competition_name}")
    
    min_handicap = competition_config['minHandicap']
    max_handicap = competition_config['maxHandicap']
    number_of_winners = competition_config['numberOfWinners']
    scoreType = competition_config['scoreType']
    
    # Filter data based on handicap limits
    filtered_data = [entry for entry in data if entry['score'] != 'NR' and min_handicap <= entry['handicap'] <= max_handicap]

    # Sort data by points in descending order
    sorted_data = sorted(filtered_data, key=lambda x: x['position'])
    
    # Get the top N winners and update positions
    top_winners = []
    for new_position, entry in enumerate(sorted_data[:number_of_winners], start=1):
        updated_entry = entry.copy()
        updated_entry['original_position'] = updated_entry['position']
        updated_entry['position'] = new_position
        top_winners.append(updated_entry)
    
    return top_winners

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
        soup = execute_report(compid)
        comp, data = extract_data(soup)

        logging.info(f"Competition Name: {comp}")

        if comp is not None and data is not None:
            results = process_competition_results(comp, data, config)

        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()

    logging.info(results)

    return results  
