import logging
import azure.functions as func
from mailchimp_sync import main as mailchimp_sync_main
# from other_function import main as other_function_main

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('HTTP trigger function processed a request.')

    action = req.params.get('action')
    if not action:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            action = req_body.get('action')

    if action == 'sync_mailchimp':
        result = mailchimp_sync_main()
        return func.HttpResponse(result, status_code=200)
    elif action == 'other_function':
        result = other_function_main()
        return func.HttpResponse(result, status_code=200)
    else:
        return func.HttpResponse(
             "Please pass a valid action on the query string or in the request body",
             status_code=400
        )
