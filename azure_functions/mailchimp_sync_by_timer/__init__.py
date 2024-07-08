from common.mailchimp_sync import execute
from azure.functions import TimerRequest
import logging

def main(timer: TimerRequest) -> None:
    added_count, updated_count = execute()
    response_message = (
        f"Azure function 'mailchimp_sync' completed. "
        f"Added: {added_count}, Updated: {updated_count}"
    )
    logging.info(response_message)
