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
from datetime import datetime
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

def execute_report():
    logging.info(f"Entering execute_report")

    report_url = f"https://www.botgc.co.uk/compdash.php"
    response_ajax = session.get(report_url)

    ajaxRequest_url = f"https://www.botgc.co.uk/compdash.php?tab=competitions&requestType=ajax&ajaxaction=morecomps&status=upcoming&entrants=all&kind=all&teamsolo=all&year=all&offset=0&limit=20"
    response = session.get(ajaxRequest_url)

    if response.ok:
        print_success("Successfully accessed the report.")
        logging.debug("Report content: %s", response.content)
        logging.info("Exiting execute_report with success")

        data = json.loads(response.content)

        # Extract the 'html' value
        html_content = f"<html><body><table><tbody>{data['html']}</tbody></table></body></html>"

        return BeautifulSoup(html_content, 'html.parser') 
        #'html.parser')
    else:
        print_error("Failed to access the report.")
        logging.error("Failed to access report with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting execute_report with failure")
        return None

def format_date(date_str):
    # Attempt to parse the date string in ISO format
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None
    return date_obj.strftime('%A %dth %B')

def extract_component_competitions(url):
    response = session.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    component_competitions = []
    for comp in soup.select('div.form-group:has(label:contains("Component Competitions:")) li a'):
        comp_name = comp.get_text(strip=True)
        comp_link = comp['href']
        comp_id = re.search(r'compid=(\d+)', comp_link).group(1)
        component_competitions.append({
            'name': comp_name,
            'link': comp_link,
            'id': comp_id
        })
    return component_competitions

def extract_data(soup, target_date_str=None):

    logging.info("Entering extract_data")
    if soup is None:
        logging.warning("Soup is None, returning empty data list")
        return []

    if target_date_str:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
    else:
        target_date = datetime.today()
        
    logging.info(f"Target Date: {target_date}")

    competition_list = soup.find('tbody')
    competitions_on_date = []
    multi_round = []

    current_year = target_date.year

    for row in competition_list.find_all('tr'):
        date_td = row.find_all('td')[1].get_text(strip=True)

        if 'Multiround' in row.get_text():
            comp_name = row.find('a').get_text(strip=True)
            comp_link = row.find('a')['href']
            comp_id = re.search(r'compid=(\d+)', comp_link).group(1)
            multi_round.append({
                'name': comp_name,
                'link': comp_link,
                'id': comp_id
            })
            continue  # Skip further date processing for this row

        try:
            comp_date = datetime.strptime(f"{current_year} {date_td}", '%Y %A %dth %B')
        except ValueError:
            try:
                comp_date = datetime.strptime(f"{current_year} {date_td}", '%Y %A %d %B')
            except ValueError:
                continue

        if comp_date > target_date:
            break

        if target_date == comp_date:
            competition_name = row.find('a').get_text(strip=True)
            competition_link = row.find('a')['href']
            competition_id = re.search(r'compid=(\d+)', competition_link).group(1)
            competitions_on_date.append({
                'name': competition_name,
                'link': competition_link,
                'id': competition_id
            })

    logging.info(f"multi_round: {multi_round}")

    multi_round_with_components = []

    for multi_round_comp in multi_round:
        full_url = f'https://www.botgc.co.uk/{multi_round_comp["link"]}'
        logging.info(f"Visiting {full_url}...")
        component_competitions = extract_component_competitions(full_url)
        multi_round_comp['components'] = component_competitions
        multi_round_with_components.append(multi_round_comp)            

    # Create a set to track which competitions have been replaced
    replaced_components = set()

    # Create a set to track multi-round competitions added to avoid duplication
    added_multi_round = set()

    updated_competitions_on_date = []

    for comp in competitions_on_date:
        comp_name, comp_link, comp_id = comp['name'], comp['link'], comp['id']
        replaced = False

        for multi_round_comp in multi_round_with_components:
            components = multi_round_comp['components']
            for component in components:
                if component['name'] == comp_name:
                    if multi_round_comp['name'] not in added_multi_round:
                        # Add the multi-round competition and its components to the updated list
                        updated_competitions_on_date.append({
                            'name': multi_round_comp['name'],
                            'link': multi_round_comp['link'],
                            'id': multi_round_comp['id'],
                            'components': components
                        })
                        added_multi_round.add(multi_round_comp['name'])
                    # Mark all components as replaced
                    for comp in components:
                        replaced_components.add(comp['name'])
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            updated_competitions_on_date.append(comp)

    # Filter out replaced competitions from the final list
    final_competitions_on_date = []
    for comp in updated_competitions_on_date:
        if isinstance(comp, dict) or comp['name'] not in replaced_components:
            final_competitions_on_date.append(comp)

    return final_competitions_on_date

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

    
    # config = read_config()

    # if not compid:
    #     try:
    #         req_body = req.get_json()
    #     except ValueError:
    #         pass
    #     else:
    #         compid = req_body.get('compid')


    return config

def read_config_local():
    config_file_path = os.path.join(os.path.dirname(__file__), '..', 'common', 'data', 'competitions.json')

    logging.info(f"Retrieving config from {config_file_path}")

    # Load the configuration file
    with open(config_file_path, 'r') as config_file:
        config = json.load(config_file)

    return config

def execute(req: HttpRequest):

    results = []

    date = req.params.get('date')
    
    if member_login():
        soup = execute_report()

        results = extract_data(soup, date)

        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()
    
    logging.info(results)

    return results