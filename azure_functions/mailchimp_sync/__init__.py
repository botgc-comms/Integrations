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

def obtain_admin_rights():
    logging.info("Entering obtain_admin_rights")
    second_login_url = "https://www.botgc.co.uk/membership2.php"
    second_login_data = {
        "leveltwopassword": os.environ["ADMIN_PASSWORD"]
    }
    response = session.post(second_login_url, data=second_login_data)
    if response.ok:
        print_success("Second login successful!")
    else:
        print_error("Second login failed.")
        logging.error("Second login failed with status code: %s and response: %s", response.status_code, response.text)
        logging.info("Exiting obtain_admin_rights with failure")
        return False
    logging.info("Exiting obtain_admin_rights with success")
    return True

def execute_report():
    logging.info("Entering execute_report")
    report_url = "https://www.botgc.co.uk/membership_reports.php?tab=report&section=viewreport&md=742de18a45d454919df8d52ba1bad62b"
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
    logging.info("Entering extract_data")
    if soup is None:
        logging.warning("Soup is None, returning empty data list")
        return []
    table = soup.find('table')
    if table is None:
        print_error("No table found in the provided HTML.")
        logging.warning("No table found in the provided HTML.")
        return []

    table_rows = []
    header = table.find('thead')
    
    if header:
        header_row = [th.get_text(strip=True) for th in header.find_all('th')]
        table_rows.append(header_row)
    for tr in table.find_all('tr'):
        row = [td.get_text(strip=True) for td in tr.find_all(['td'])]
        if row and row[0].strip():  # Exclude rows where the first column is blank
            table_rows.append(row)
    
    logging.info("Exiting extract_data with %d rows", len(table_rows) - 1)
    return table_rows[1:]

def convert_date_format(date_string):
    logging.debug("Converting date format for: %s", date_string)
    day, month, year = date_string.split('/')
    return f"{month}/{day}/{year}"

def map_data_to_merge_fields(table_rows):
    logging.info("Entering map_data_to_merge_fields")
    merge_fields_collection = []

    for row in table_rows:
        try:
            account_number = int(row[0])
            if account_number > 10000:
                logging.debug("Skipping row with account number > 10000: %d", account_number)
                continue  # Skip this row and move to the next one
        except ValueError:
            logging.warning("Warning: Unable to process account number '%s'. Skipping row.", row[0])
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

    logging.info("Exiting map_data_to_merge_fields with %d merge fields", len(merge_fields_collection))
    return merge_fields_collection

def update_mailchimp_subscriber_direct(audience_id, merge_fields, api_key, server_prefix, retries=3, backoff_factor=1):
    email_address = merge_fields["EMAIL"]
    subscriber_hash = hashlib.md5(email_address.lower().encode('utf-8')).hexdigest()
    url = f"https://{server_prefix}.api.mailchimp.com/3.0/lists/{audience_id}/members/{subscriber_hash}"
    auth = HTTPBasicAuth('anystring', api_key)
    body = {
        "email_address": email_address,
        "status_if_new": "subscribed",
        "merge_fields": merge_fields,
    }
    result_response = "updated"

    for attempt in range(retries):
        try:
            logging.info(f"Attempt {attempt + 1}: Processing email: {email_address}")
            
            query_response = requests.get(url, auth=auth)
            if query_response.status_code == 404:
                result_response = "added"
            
            response = requests.put(url, auth=auth, json=body)
            if response.status_code == 200:
                logging.info(f"Successfully {result_response} {email_address}")
                return result_response, email_address
            else:
                logging.error(f"Unexpected status code {response.status_code} for {email_address}")
                return "unexpected", email_address
        except requests.exceptions.RequestException as e:
            logging.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(backoff_factor * (2 ** attempt))  # Exponential backoff
            else:
                logging.error(f"Failed after {retries} attempts: {e}")
                return "error", email_address
    return "error", email_address

def update_mailchimp(merge_fields_collection):
    logging.info("Entering update_mailchimp")
    added_count = 0
    updated_count = 0
    try:
        audience_id = os.environ["MAILCHIMP_AUDIENCE_ID"]
        api_key = os.environ["MAILCHIMP_API_KEY"]
        server_prefix = os.environ["MAILCHIMP_SERVER"]

        for merge_fields in merge_fields_collection:
            email_address = merge_fields["EMAIL"]
            
            try:
                result = update_mailchimp_subscriber_direct(audience_id, merge_fields, api_key, server_prefix)
                logging.info(f"Result from update_mailchimp_subscriber: {result}")

                if result == "updated":
                    updated_count += 1
                elif result == "added":
                    added_count += 1
            except Exception as e:
                print_error(f"Error in processing: {e}")
                logging.error("Error in processing: %s", e)

    except ApiClientError as error:
        print_error("Error: {}".format(error.text))
        logging.error("Mailchimp API Client Error: %s", error.text)

    if tc:
        tc.track_metric(name="Mailchimp Contacts Added", value=added_count)
        tc.track_metric(name="Mailchimp Contacts Updated", value=updated_count)
        tc.flush()
    
    logging.info("Exiting update_mailchimp with %d added and %d updated", added_count, updated_count)

def update_mailchimp_async(merge_fields_collection):
    logging.info("Entering update_mailchimp_async")
    added_count = 0
    updated_count = 0
    try:
        audience_id = os.environ["MAILCHIMP_AUDIENCE_ID"]
        api_key = os.environ["MAILCHIMP_API_KEY"]
        server_prefix = os.environ["MAILCHIMP_SERVER"]

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(update_mailchimp_subscriber_direct, audience_id, merge_fields, api_key, server_prefix)
                for merge_fields in merge_fields_collection
            ]

            for future in as_completed(futures):
                try:
                    result, email_address = future.result()
                    logging.info(f"Result from update_mailchimp_subscriber_direct for {email_address}: {result}")
                    if result == "updated":
                        updated_count += 1
                    elif result == "added":
                        added_count += 1
                except Exception as e:
                    logging.error(f"Error in processing: {e}")

    except Exception as error:
        logging.error(f"Mailchimp API Client Error: {error}")

    if tc:
        tc.track_metric(name="Mailchimp Contacts Added", value=added_count)
        tc.track_metric(name="Mailchimp Contacts Updated", value=updated_count)
        tc.flush()

    logging.info("Exiting update_mailchimp_async with %d added and %d updated", added_count, updated_count)

    return added_count, updated_count


def main(req: HttpRequest) -> HttpResponse:
    logging.info("Azure function 'mailchimp_sync' triggered.")
    if member_login() and obtain_admin_rights():
        soup = execute_report()
        data = extract_data(soup)
        merge_field_collection = map_data_to_merge_fields(data)
        added_count, updated_count = update_mailchimp_async(merge_field_collection)
        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()
    
    response_message = (
        f"Azure function 'mailchimp_sync' completed. "
        f"Added: {added_count}, Updated: {updated_count}"
    )

    logging.info("Azure function 'mailchimp_sync' completed.")

    return HttpResponse(response_message, status_code=200)
