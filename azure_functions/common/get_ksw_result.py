import requests
from requests.auth import HTTPBasicAuth
from .get_competition_startsheet import get_startsheet 
from bs4 import BeautifulSoup
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import pandas as pd
import logging
from applicationinsights import TelemetryClient
from azure.functions import HttpRequest, HttpResponse
import time
from azure.storage.blob import BlobServiceClient
import json
import re

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


def read_results():
     # Environment variables for Azure Storage account details
    connection_string = os.getenv('DATA_CONTAINER_CONNECTION_STRING')
    container_name = 'data'
    blob_name = 'KSR Results.csv'

    # Initialize the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    # Download the CSV file from the blob
    csv_data = blob_client.download_blob().readall().decode('utf-8')

    # Load the CSV data into a pandas DataFrame
    from io import StringIO
    df = pd.read_csv(StringIO(csv_data))

    # Convert the DataFrame to JSON
    json_data = df.to_json(orient='records')

    return json_data

def execute(req: HttpRequest):

    results = read_results()

    if tc:
        tc.track_event("Function executed successfully")
        tc.flush()
    
    logging.info(results)

    return results