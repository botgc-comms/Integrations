import requests
from bs4 import BeautifulSoup
from io import StringIO
import csv
import mailchimp_marketing as MailchimpMarketing
from mailchimp_marketing.api_client import ApiClientError
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from colorama import init, Fore, Style
import os
import logging
from applicationinsights import TelemetryClient
import azure.functions as func

app = func.FunctionApp()

# Initialize a session for persistent connections
session = requests.Session()

init(autoreset=True)

# Initialize Application Insights Telemetry Client
tc = TelemetryClient(os.environ["APPINSIGHTS_INSTRUMENTATION_KEY"])

def print_success(message):
    logging.info(message)
    tc.track_trace(message, severity='INFO')

def print_error(message):
    logging.error(message)
    tc.track_trace(message, severity='ERROR')

def member_login():
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
        logging.info("First login successful!")
        tc.track_trace("First login successful!")
    else:
        logging.error("First login failed.")
        tc.track_trace("First login failed.", severity='ERROR')
        return False
    return True

def obtain_admin_rights():
    second_login_url = "https://www.botgc.co.uk/membership2.php"
    second_login_data = {
        "leveltwopassword": os.environ["ADMIN_PASSWORD"]
    }
    response = session.post(second_login_url, data=second_login_data)
    if response.ok:
        logging.info("Second login successful!")
        tc.track_trace("Second login successful!")
    else:
        logging.error("Second login failed.")
        tc.track_trace("Second login failed.", severity='ERROR')
        return False
    return True

def execute_report():
    report_url = "https://www.botgc.co.uk/membership_reports.php?tab=report&section=viewreport&md=742de18a45d454919df8d52ba1bad62b"
    response = session.get(report_url)
    if response.ok:
        logging.info("Successfully accessed the report.")
        tc.track_trace("Successfully accessed the report.")
        return BeautifulSoup(response.content, 'html.parser')
    else:
        logging.error("Failed to access the report.")
        tc.track_trace("Failed to access the report.", severity='ERROR')
        return None

def extract_data(soup):
    if soup is None:
        return []
    table = soup.find('table')
    table_rows = []
    header = table.find('thead')
    
    if header:
        header_row = [th.get_text(strip=True) for th in header.find_all('th')]
        table_rows.append(header_row)
    for tr in table.find_all('tr'):
        row = [td.get_text(strip=True) for td in tr.find_all(['td'])]
        if row and row[0].strip():  # Exclude rows where the first column is blank
            table_rows.append(row)
    
    return table_rows[1:]

def convert_date_format(date_string):
    day, month, year = date_string.split('/')
    return f"{month}/{day}/{year}"

def map_data_to_merge_fields(table_rows):
    merge_fields_collection = []

    for row in table_rows:
        try:
            account_number = int(row[0])
            if account_number > 10000:
                continue  # Skip this row and move to the next one
        except ValueError:
            logging.warning(f"Warning: Unable to process account number '{row[0]}'. Skipping row.")
            tc.track_trace(f"Warning: Unable to process account number '{row[0]}'. Skipping row.", severity='WARNING')
            continue

        addr2_parts = []
        if row[8]:
            addr2_parts.append(row[8].strip())
        if row[9]:
            addr2_parts.append(row[9].strip())
        
        addr2 = " ".join(addr2_parts)
        city = row[10].strip()
        if not city and addr2:
            city = addr2.split()[-1].strip()
            if city:
                addr2 = addr2.rsplit(' ', 1)[0] if ' ' in addr2 else ""

        addr1 = row[7]
        if not addr1 and addr2:
            addr1, addr2 = addr2, ""

        state = row[11]
        zip = row[12]

        address = {}
        if addr1 and city and state and zip:
            address = {
                'addr1': addr1,
                'addr2': addr2,
                'city': city,
                "state": state,
                "zip": zip,
                "country": "United Kingdom"
            }

        merge_fields = {
            "EMAIL": row[13],
            "FNAME": row[2],
            "LNAME": row[3],
            "ADDRESS": address,
            "GENDER": row[5],
            "CATEGORY": row[6],
            "FULLNAME": row[4],
            "TITLE": row[1],
            "ID": row[0],
            "DOB": convert_date_format(row[14]),
            "JOINED": convert_date_format(row[15]),
            "HANDICAP": row[16],
            "DISABLED": row[17],
            "UNPAID": row[18]
        }

        if not address:
            del merge_fields["ADDRESS"]

        merge_fields_collection.append(merge_fields)

    return merge_fields_collection

def update_mailchimp_subscriber(client, audience_id, merge_fields, stats):
    email_address = merge_fields["EMAIL"]
    subscriber_hash = hashlib.md5(email_address.lower().encode('utf-8')).hexdigest()

    body = {
        "email_address": email_address,
        "status_if_new": "subscribed",
        "merge_fields": merge_fields,
    }

    try:
        response = client.lists.set_list_member(audience_id, subscriber_hash, body)
        if response['status'] == 'subscribed':
            stats['added'] += 1
            print_success(f"Successfully added {email_address}")
        else:
            stats['updated'] += 1
            print_success(f"Successfully updated {email_address}")
    except ApiClientError as error:
        print_error(f"Error updating/adding {email_address}: {error.text} {merge_fields}")

def update_mailchimp(merge_fields_collection):
    try:
        client = MailchimpMarketing.Client()
        client.set_config({
            "api_key": os.environ["MAILCHIMP_API_KEY"],
            "server": os.environ["MAILCHIMP_SERVER"]
        })

        audience_id = os.environ["MAILCHIMP_AUDIENCE_ID"]

        stats = {
            'added': 0,
            'updated': 0
        }

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(update_mailchimp_subscriber, client, audience_id, merge_fields, stats)
                       for merge_fields in merge_fields_collection]

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print_error(f"Error in processing: {e}")

        logging.info(f"Mailchimp Update Summary: {stats['added']} added, {stats['updated']} updated")
        tc.track_event("Mailchimp Update Summary", {
            "added": stats['added'],
            "updated": stats['updated']
        })
        tc.flush()

    except ApiClientError as error:
        print_error("Error: {}".format(error.text))

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

@app.function_name(name="HttpTrigger1")
@app.route(route="req")
def main(req: func.HttpRequest) -> None:
    tc.track_trace("Script execution started.")
    if member_login() and obtain_admin_rights():
        soup = execute_report()
        data = extract_data(soup)
        merge_field_collection = map_data_to_merge_fields(data)
        update_mailchimp(merge_field_collection)
    tc.track_trace("Script execution completed.")
    tc.flush()
