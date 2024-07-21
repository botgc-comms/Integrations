import logging
import os
import azure.functions as func

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Serving the static HTML page.')

    html_file_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(html_file_path, 'r') as html_file:
        html_content = html_file.read()

    return func.HttpResponse(html_content, mimetype="text/html")
