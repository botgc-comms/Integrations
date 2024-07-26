from common.get_competitions import execute
from azure.functions import HttpRequest, HttpResponse
import logging
import json

def main(req: HttpRequest) -> HttpResponse:
    results = execute(req)
    results_json = json.dumps(results)

    return HttpResponse(results_json, status_code=200, mimetype="application/json")
