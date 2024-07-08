import logging
from azure.functions import HttpRequest, HttpResponse
import requests
from bs4 import BeautifulSoup
import mailchimp_marketing as MailchimpMarketing
from mailchimp_marketing.api_client import ApiClientError
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from applicationinsights import TelemetryClient

# Initialize a session for persistent connections
session = requests.Session()

# Check for Application Insights instrumentation key
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
        return False
    return True

def obtain_admin_rights():
    second_login_url = "https://www.botgc.co.uk/membership2.php"
    second_login_data = {
        "leveltwopassword": os.environ["ADMIN_PASSWORD"]
    }
    response = session.post(second_login_url, data=second_login_data)
    if response.ok:
        print_success("Second login successful!")
    else:
        print_error("Second login failed.")
        return False
    return True

def execute_report():
    report_url = "https://www.botgc.co.uk/membership_reports.php?tab=report&section=viewreport&md=742de18a45d454919df8d52ba1bad62b"
    response = session.get(report_url)
    if response.ok:
        print_success("Successfully accessed the report.")
        return BeautifulSoup(response.content, 'html.parser')
    else:
        print_error("Failed to access the report.")
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

def update_mailchimp_subscriber(client, audience_id, merge_fields):
    email_address = merge_fields["EMAIL"]
    subscriber_hash = hashlib.md5(email_address.lower().encode('utf-8')).hexdigest()

    body = {
        "email_address": email_address,
        "status_if_new": "subscribed",
        "merge_fields": merge_fields,
    }

    try:
        response = client.lists.set_list_member(audience_id, subscriber_hash, body)
        print_success(f"Successfully updated/added {email_address}")
        return response.status_code
    except ApiClientError as error:
        print_error(f"Error updating/adding {email_address}: {error.text} {merge_fields}")
        return None

def update_mailchimp(merge_fields_collection):
    added_count = 0
    updated_count = 0
    try:
        client = MailchimpMarketing.Client()
        client.set_config({
            "api_key": os.environ["MAILCHIMP_API_KEY"],
            "server": os.environ["MAILCHIMP_SERVER"]
        })

        audience_id = os.environ["MAILCHIMP_AUDIENCE_ID"]

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(update_mailchimp_subscriber, client, audience_id, merge_fields)
                       for merge_fields in merge_fields_collection]

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result == 200:
                        updated_count += 1
                    elif result == 201:
                        added_count += 1
                except Exception as e:
                    print_error(f"Error in processing: {e}")

    except ApiClientError as error:
        print_error("Error: {}".format(error.text))

    if tc:
        tc.track_metric(name="Mailchimp Contacts Added", value=added_count)
        tc.track_metric(name="Mailchimp Contacts Updated", value=updated_count)
        tc.flush()

def main(req: HttpRequest) -> HttpResponse:
    soup = execute_report()
    data = extract_data(soup)
    merge_field_collection = map_data_to_merge_fields(data)
    update_mailchimp(merge_field_collection)
    if tc:
        tc.track_event("Function executed successfully")
        tc.flush()

    return HttpResponse(
        "Sync executed successfully",
        status_code=200
    )
