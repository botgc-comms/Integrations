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

    report_url = f"https://www.botgc.co.uk/compadmin3.php?tab=startsheet&compid={compid}&print=true"
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

def extract_data(soup):
    comp_name = ""

    logging.info("Entering extract_data")
    if soup is None:
        logging.warning("Soup is None, returning empty data list")
        return []

    players = []

    for player_div in soup.find_all('div', class_='player'):
        name = player_div.find('span').contents[0].strip()
        hcap_info = player_div.find('span', class_='hcap').text.strip()
        
        # Extracting HI, CH, and PH
        hi = hcap_info.split(', ')[0].replace('HI: ', '').replace('(', '')
        ch = hcap_info.split(', ')[1].replace('CH: ', '')
        ph = hcap_info.split(', ')[2].replace('PH: ', '').replace(')', '')
        
        players.append({
            'name': name,
            'HI': hi,
            'CH': ch,
            'PH': ph
        })

    # Output the results
    for player in players:
        print(f"Name: {player['name']}, HI: {player['HI']}, CH: {player['CH']}, PH: {player['PH']}")
   
    logging.info("Exiting extract_data with %d rows", len(players))
    return players

def get_startsheet(compid):

    results = []

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
        results = extract_data(soup)

        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()
   
    return results

def execute(req: HttpRequest):

    # Extract the 'compid' parameter from the query string
    compid = req.params.get('compid')
    results = get_startsheet(compid)

    return results