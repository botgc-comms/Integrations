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
from datetime import datetime, timedelta

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
    """
    Convert a date string to ISO 8601 format (YYYY-MM-DD).
    - Dates containing '/' are assumed to be in DD/MM/YYYY format (UK format) and converted.
    - Dates in 'YYYY-MM-DD' format are returned as-is.
    - Invalid or empty dates return None.
    """
    if not date_string or date_string.strip() in ["", "0000-00-00"]:
        return None  # Return None for invalid or blank dates

    try:
        # If date contains '/', assume it is in DD/MM/YYYY format and convert to ISO
        if "/" in date_string:
            day, month, year = map(int, date_string.split('/'))
            date_obj = datetime(year=year, month=month, day=day)
            return date_obj.strftime("%Y-%m-%d")
        
        # If date contains '-', assume it is already in YYYY-MM-DD format
        if "-" in date_string:
            # Validate the date and return it as-is
            date_obj = datetime.strptime(date_string, "%Y-%m-%d")
            return date_obj.strftime("%Y-%m-%d")
        
    except (ValueError, TypeError):
        logging.warning(f"Invalid date format: {date_string}")
        return None  # Return None for unparseable dates

def determine_recent_leaver(leave_date, membership_status):
    """
    Determine if a member is a recent leaver based on leave date and status.
    - Recent leaver = left within the last 7 days and the leave date is in the past.
    """
    today = datetime.now()
    start_of_seven_days_ago = (today - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_today = today.replace(hour=23, minute=59, second=59, microsecond=999999)

    if membership_status == "R":
        # Active members are not recent leavers
        return "No"
    
    if not leave_date or leave_date.strip() in ["", "0000-00-00"]:
        # Missing or invalid leave date → not a recent leaver
        return "No"
    
    try:
        # Parse leave date
        leave_date_obj = datetime.strptime(leave_date, "%Y-%m-%d")
        
        if leave_date_obj > today:
            # Future leave date - member has not yet left
            return "No"
        
        # Check if the leave date is within the last 7 days
        if start_of_seven_days_ago <= leave_date_obj <= end_of_today:
            return "Yes"
        else:
            return "No"
    except ValueError:
        # Invalid leave date → not a recent leaver
        return "No"


def determine_recent_joiner(join_date):
    """
    Determine if a member is a recent joiner based on the join date.
    - Recent joiner = joined within the last 7 days.
    """
    today = datetime.now()
    start_of_seven_days_ago = (today - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_today = today.replace(hour=23, minute=59, second=59, microsecond=999999)

    if not join_date or join_date.strip() in ["", "0000-00-00"]:
        # Missing or invalid join date → not a recent joiner
        return "No"
    
    try:
        # Parse join date and check if it falls within the range
        join_date_obj = datetime.strptime(join_date, "%Y-%m-%d")
        if start_of_seven_days_ago <= join_date_obj <= end_of_today:
            return "Yes"
        else:
            return "No"
    except ValueError:
        # Invalid join date → not a recent joiner
        return "No"


def process_leave_date(leave_date, membership_status):
    """
    Process the leave date based on membership status, join date, and leave date validity.
    - If leave date is invalid or blank and status is not R, set it to today's date.
    - If leave date is invalid and status is R, set it to None.
    - If leave date is valid and in the future or past, return it as is.
    """
    if leave_date in ["0000-00-00", None, ""]:
        # Handle explicitly invalid or blank leave dates
        return None if membership_status == "R" else datetime.now().strftime("%Y-%m-%d")
    
    try:
        # Parse the leave date
        leave_date_obj = datetime.strptime(leave_date, "%Y-%m-%d")
        return leave_date  # Valid leave date (past or future)
    except (ValueError, TypeError):
        # Invalid leave date
        return None if membership_status == "R" else datetime.now().strftime("%Y-%m-%d")


def is_past_date(date_string):
    """
    Check if a given date string is in the past.
    """
    try:
        date = datetime.strptime(date_string, "%Y-%m-%d")
        return date < datetime.now()
    except ValueError:
        return False

def map_data_to_merge_fields(table_rows):
    logging.info("Entering map_data_to_merge_fields")
    merge_fields_collection = []

    for row in table_rows:
        try:
            account_number = int(row[0])
            if account_number > 10000:
                logging.debug("Skipping row with account number > 10000: %d", account_number)
                continue
        except ValueError:
            logging.warning("Warning: Unable to process account number '%s'. Skipping row.", row[0])
            continue

        # Extract relevant data
        membership_status = row[7].strip() if len(row) > 7 else None
        leave_date = row[17].strip() if len(row) > 17 and row[17] else None
        join_date = row[16].strip() if len(row) > 16 else None

        # Process the leave date using the helper function
        processed_leave_date = process_leave_date(leave_date, membership_status)
        is_active = membership_status == "R" and (not processed_leave_date or not is_past_date(processed_leave_date))

        # Address processing
        addr2_parts = []
        if row[9]:
            addr2_parts.append(row[9].strip())
        if row[10]:
            addr2_parts.append(row[10].strip())
        
        addr2 = " ".join(addr2_parts)
        city = row[11].strip()
        if not city and addr2:
            city = addr2.split()[-1].strip()
            if city:
                addr2 = addr2.rsplit(' ', 1)[0] if ' ' in addr2 else ""

        addr1 = row[8]
        if not addr1 and addr2:
            addr1, addr2 = addr2, ""

        state = row[12]
        zip = row[13]

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

        # Map to merge fields
        merge_fields = {
            "EMAIL": row[14],
            "FNAME": row[2],
            "LNAME": row[3],
            "FULLNAME": row[4],
            "TITLE": row[1],
            "GENDER": row[5],
            "CATEGORY": row[6],
            "ID": row[0],
            "DOB": convert_date_format(row[15]),
            "JOINED": convert_date_format(join_date),
            "LEAVEDATE": "",
            "HANDICAP": row[18] if len(row) > 18 else None,
            "DISABLED": row[19] if len(row) > 19 else None,
            "UNPAID": row[20] if len(row) > 20 else None,
            "STATUS": membership_status,
            "ISACTIVE": "Yes" if is_active else "No", 
            "RECLEAVER": determine_recent_leaver(processed_leave_date, membership_status),
            "RECJOINER": determine_recent_joiner(join_date)
        }

        if address:
            merge_fields["ADDRESS"] = address

        if processed_leave_date:
            merge_fields["LEAVEDATE"] = processed_leave_date

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

    is_active = merge_fields.get("ISACTIVE", "No") == "Yes"

    for attempt in range(retries):
        try:
            logging.info(f"Attempt {attempt + 1}: Processing email: {email_address}")
            
            # Fetch existing data from Mailchimp
            query_response = requests.get(url, auth=auth)
            if query_response.status_code == 404:
                # Member does not exist in Mailchimp
                if not is_active:
                    logging.info(f"Skipping inactive member {email_address} as they do not exist in Mailchimp.")
                    return "skipped", email_address, ""
                result_response = "added"
            elif query_response.status_code == 200:
                current_data = query_response.json()
                current_join_date = current_data.get("merge_fields", {}).get("JOINED")
                current_leave_date = current_data.get("merge_fields", {}).get("LEAVEDATE")
                membership_status = merge_fields.get("STATUS")
                
                logging.info("Current Leave Date")
                logging.info(current_leave_date)

                if membership_status != "R":
                    if current_leave_date not in [None, "", "0000-00-00"]:
                        merge_fields["LEAVEDATE"] = current_leave_date
                
                # Recalculate recent leaver/joiner based on reconciled data
                try:
                    merge_fields["RECLEAVER"] = determine_recent_leaver(
                        merge_fields["LEAVEDATE"],
                        merge_fields.get("ISACTIVE", "No")
                    )
                except Exception as e:
                    logging.error(f"Error determining RECLEAVER for {email_address}: {e}")
                    merge_fields["RECLEAVER"] = "No"  # Default to not recent if an error occurs

                try:
                    merge_fields["RECJOINER"] = determine_recent_joiner(merge_fields["JOINED"])
                except Exception as e:
                    logging.error(f"Error determining RECJOINER for {email_address}: {e}")
                    merge_fields["RECJOINER"] = "No"  # Default to not recent if an error occurs

            # Update or add the member in Mailchimp
            response = requests.put(url, auth=auth, json=body)
            if response.status_code == 200:
                logging.info(f"Successfully {result_response} {email_address}")
                return result_response, email_address, ""
            else:
                logging.error(f"Unexpected status code {response.status_code} for {email_address}")
                return "unexpected", email_address, response.text
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(backoff_factor * (2 ** attempt))  # Exponential backoff
            else:
                logging.error(f"Failed after {retries} attempts: {e}")
                return "error", email_address, str(e)
    return "error", email_address

def update_mailchimp_async(merge_fields_collection):
    logging.info("Entering update_mailchimp_async")

    # merge_fields_collection = [
    #     fields for fields in merge_fields_collection if fields["EMAIL"] == "comms@botgc.co.uk"
    # ]

    added_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0
    try:
        audience_id = os.environ["MAILCHIMP_AUDIENCE_ID"]
        api_key = os.environ["MAILCHIMP_API_KEY"]
        server_prefix = os.environ["MAILCHIMP_SERVER"]

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(update_mailchimp_subscriber_direct, audience_id, merge_fields, api_key, server_prefix)
                for merge_fields in merge_fields_collection
            ]

            for future in as_completed(futures):
                try:
                    result, email_address, additional_info = future.result()
                    
                    logging.info(f"Result from update_mailchimp_subscriber_direct for {email_address}: {result}")
                    if result == "updated":
                        updated_count += 1
                    elif result == "added":
                        added_count += 1
                    elif result == "skipped":
                        skipped_count += 1
                    else:
                        error_count += 1

                    if (additional_info):
                        logging.error(additional_info)

                except Exception as e:
                    logging.error(f"Error in processing: {e}")

    except Exception as error:
        logging.error(f"Mailchimp API Client Error: {error}")

    if tc:
        tc.track_metric(name="Mailchimp Contacts Added", value=added_count)
        tc.track_metric(name="Mailchimp Contacts Updated", value=updated_count)
        tc.track_metric(name="Mailchimp Contacts Skipped", value=skipped_count)
        tc.track_metric(name="Mailchimp Contacts Errored", value=error_count)
        tc.flush()

    logging.info("Exiting update_mailchimp_async with %d added and %d updated", added_count, updated_count)

    return added_count, updated_count


def execute(req=None):
    added_count = 0
    updated_count = 0
    if member_login() and obtain_admin_rights():
        soup = execute_report()
        data = extract_data(soup)
        merge_field_collection = map_data_to_merge_fields(data)

        logging.info("Starting")

        added_count, updated_count = update_mailchimp_async(merge_field_collection)
        if tc:
            tc.track_event("Function executed successfully")
            tc.flush()

    return added_count, updated_count