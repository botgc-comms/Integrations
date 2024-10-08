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

    report_url = f"https://www.botgc.co.uk/competition.php?tab=details&compid={compid}&preview=1&div=0&sort={grossOrNet}"
    logging.info(f"report_url: {report_url}")
    
    response = session.get(report_url)

    if response.ok:
        print_success("Successfully accessed the report.")
        logging.debug("Report content: %s", response.content)
        logging.info("Exiting execute_report with success")
        return BeautifulSoup(response.content, 'html5lib') 
        #'html.parser')
    else:
        print_error("Failed to access the report.")
        logging.error("Failed to access report with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting execute_report with failure")
        return None

def lookup_handicap(startsheet, name):
    for person in startsheet:
        if person['name'] == name:
            return float(person['HI']), float(person['CH']), float(person['PH'])
    return None, None, None  # Return None if the person is not found

def parse_score(value):
    value = value.strip()
    if value == "":
        return None
    if value == "NR":
        return None
    try:
        return int(value)
    except ValueError:
        return 0

def extract_data(soup, startsheet):
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

    logging.info(f"Competition Name: {comp_name}")

    table = soup.find('table')
    if table is None:
        print_error("No table found in the provided HTML.")
        logging.warning("No table found in the provided HTML.")
        return []

    thead_tr = table.find('thead').find('tr')
    headings = [td.get_text() for td in thead_tr.find_all('td')]
    live_leaderboard = "Thru" in headings
    on_course_scoring = "Latest" in headings
    is_multi_summary = "R1" in headings and "R2" in headings
    has_status = "Status" in headings


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

        if is_multi_summary:

            # Extract name and handicap
            name_and_handicap = cols[2].get_text(strip=True)
            name_and_handicap = re.sub(r'[^a-zA-Z\d\s\-\+\(\)\-]+', '', name_and_handicap).replace('\n', '').replace('\r', '').strip()
            name_and_handicap = re.sub(r'[\s]+', ' ', name_and_handicap)

            name_tag = cols[2].find('a')  # Adjusted to check the correct column
            name = name_tag.get_text(strip=True) if name_tag else name_and_handicap
            name = re.sub(r'\s+\([\-\+\d]+\)', '', name).strip()
            
            hi, ch, ph = lookup_handicap(startsheet, name)

            if ph is None:
                match = re.search(r'\(([^)]+)\)', name_and_handicap)
                if match:
                    ph = int(match.group(1))
            
            r1 = cols[3].find('a') or cols[3].find('span')
            r1_string = r1.get_text(strip=True) if r1 else cols[3].get_text(strip=True)
            
            r2 = cols[4].find('a') or cols[4].find('span')
            r2_string = r2.get_text(strip=True) if r2 else cols[4].get_text(strip=True)

            thru_string = "36"
            
            final_string = cols[6].get_text(strip=True)
            total_string = cols[6].get_text(strip=True)
            
            score = cols[6].get_text(strip=True)

            result = {
                'position': position,
                'name': name,
                'hi': hi,
                'ci': ch, 
                'ph': ph,
                'latest': parse_score(final_string),
                'total': parse_score(total_string),
                'thru': int(thru_string),
                'final': parse_score(final_string),
                'score': parse_score(score),
                'r1': parse_score(r1_string),
                'r2': parse_score(r2_string)
            }

            logging.info(result)

            table_rows.append(result)

        elif on_course_scoring:

            # Extract name and handicap
            name_and_handicap = cols[2].get_text(strip=True)
            name_and_handicap = re.sub(r'[^a-zA-Z\d\s\-\+\(\)\-]+', '', name_and_handicap).replace('\n', '').replace('\r', '').strip()
            name_and_handicap = re.sub(r'[\s]+', ' ', name_and_handicap)

            name_tag = cols[2].find('a')  # Adjusted to check the correct column
            name = name_tag.get_text(strip=True) if name_tag else name_and_handicap
            name = re.sub(r'\s+\([\-\+\d]+\)', '', name).strip()

            hi, ch, ph = lookup_handicap(startsheet, name)
                            
            latest = cols[3].find('a') or cols[3].find('span')
            latest_string = latest.get_text(strip=True) if latest else cols[3].get_text(strip=True)

            thru_string = cols[4].get_text(strip=True)
            
            final_string = cols[5].get_text(strip=True)
            total_string = cols[6].get_text(strip=True)
            
            score = cols[6].get_text(strip=True) if len(cols) > 3 else None

            result = {
                'position': position,
                'name': name,
                'hi': hi,
                'ci': ch, 
                'ph': ph,
                'latest': parse_score(latest_string),
                'total': parse_score(total_string),
                'thru': int(thru_string),
                'final': parse_score(final_string),
                'score': parse_score(score)
            }

            logging.info(result)

            table_rows.append(result)

        else:
            # Extract name and handicap
            name_and_handicap = cols[1].get_text(strip=True)
            name_and_handicap = re.sub(r'[^a-zA-Z\d\s\-\+\(\)\-]+', '', name_and_handicap).replace('\n', '').replace('\r', '').strip()
            name_and_handicap = re.sub(r'[\s]', ' ', name_and_handicap)

            name_tag = cols[1].find('a')  # Adjusted to check the correct column
            name = name_tag.get_text(strip=True) if name_tag else name_and_handicap
            name = re.sub(r'\s*\([\-\+\d]+\)', '', name).strip()

            hi, ch, ph = lookup_handicap(startsheet, name)

            if ph is None:
                match = re.search(r'\(([^)]+)\)', name_and_handicap)
                if match:
                    ph = int(match.group(1))

            if live_leaderboard:

                if has_status:

                    status_string = cols[2].get_text(strip=True)
                    score_string = cols[3].find('a').get_text(strip=True)
                    countback_results = cols[3].find('a')['title'].split(':')[-1].strip()
                    thru_string = cols[4].get_text(strip=True)

                    result = {
                        'position': position,
                        'name': name,
                        'hi': hi,
                        'ci': ch, 
                        'ph': ph,
                        'latest': None,
                        'total': parse_score(status_string),
                        'final': parse_score(score_string),
                        'score': parse_score(status_string),
                        'countback_results': countback_results,
                        'thru': int(thru_string)
                    }

                    logging.info(result)

                    table_rows.append(result)
                else:
                    score_string = cols[2].find('a').get_text(strip=True)
                    countback_results = cols[2].find('a')['title'].split(':')[-1].strip()
                    thru_string = cols[3].get_text(strip=True)

                    result = {
                        'position': position,
                        'name': name,
                        'hi': hi,
                        'ci': ch, 
                        'ph': ph,
                        'latest': None,
                        'total': parse_score(score_string),
                        'final': parse_score(score_string),
                        'score': parse_score(score_string),
                        'countback_results': countback_results,
                        'thru': int(thru_string)
                    }

                    logging.info(result)

                    table_rows.append(result)
            else:
                score_string = cols[2].find('a').get_text(strip=True)

                countback_results = cols[2].find('a')['title'].split(':')[-1].strip()

                parsed_score = parse_score(score_string)

                result = {
                    'position': position,
                    'name': name,
                    'hi': hi,
                    'ci': ch, 
                    'ph': ph,
                    'latest': None,
                    'total': parsed_score is not None and parsed_score - 71 or None,
                    'thru': 18,
                    'final': parse_score(score_string),
                    'score': parsed_score is not None and parsed_score - 71 or None,
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

    logging.info(f"Processing competition results")

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
    number_of_winners = competition_config['numberOfResults']
    scoreType = competition_config['scoreType']

    useHandicap = competition_config.get('useHandicap', 'ph')

    logging.info(competition_config)
                
    # Ensure min_handicap and max_handicap are not None
    if min_handicap is None or max_handicap is None:
        raise ValueError("min_handicap and max_handicap must be defined in the config")

    # Standardize data keys to lowercase
    standardized_data = []
    for entry in data:
        standardized_entry = {k.lower(): v for k, v in entry.items()}
        standardized_data.append(standardized_entry)

    # Filter data based on handicap limits
    filtered_data = [
        entry for entry in standardized_data 
        if entry['score'] != 'NR' 
        and entry.get(useHandicap) is not None
        and min_handicap <= entry[useHandicap] <= max_handicap
        and entry.get('thru', 1) != 0
    ]

    filtered_data = [entry for entry in filtered_data if entry['score'] is not None]

    logging.info(f"filtered_data: {filtered_data}")

    # Determine sorting order based on scoreType
    if scoreType.lower() == 'stroke':
        sorted_data = sorted(filtered_data, key=lambda x: x['score'])
    elif scoreType.lower() == 'points':
        sorted_data = sorted(filtered_data, key=lambda x: x['score'], reverse=True)

        # Find the worst score in the field
        worst_score = max(entry['score'] for entry in sorted_data[:number_of_winners])
        logging.info(f"WORST SCORE: {worst_score}")

        # Calculate total as the difference between each player's score and the worst score
        for entry in sorted_data:
            entry['total'] = (entry['score'] - worst_score)
            # entry['total'] = (entry['total'] - worst_score)
    else:
        raise ValueError(f"Unknown scoreType: {scoreType}")

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
        soup = execute_report(compid, config)

        startsheet = get_startsheet(compid)

        logging.info(startsheet)

        comp, data = extract_data(soup, startsheet)

        logging.info(data)

        if comp is not None and data is not None:
            results = process_competition_results(comp, data, config)
            logging.info(f"Competition Name: {comp} data: {data} results: {results}")

        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()
    
    logging.info(results)

    return results