from common.get_competition_result import execute
from azure.functions import HttpRequest, HttpResponse
import logging

def main(req: HttpRequest) -> HttpResponse:
    added_count, updated_count = execute(req)
    response_message = (
        f"Azure function 'mailchimp_sync' completed. "
        f"Added: {added_count}, Updated: {updated_count}"
    )
    logging.info(response_message)
    return HttpResponse(response_message, status_code=200)
