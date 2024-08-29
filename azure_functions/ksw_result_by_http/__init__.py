from common.get_ksw_result import execute
from azure.functions import HttpRequest, HttpResponse
import logging
import json

def main(req: HttpRequest) -> HttpResponse:
    results = execute(req)
    return HttpResponse(results, status_code=200, mimetype="application/json")
