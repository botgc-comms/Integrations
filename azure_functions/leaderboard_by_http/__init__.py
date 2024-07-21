import logging
import os
import azure.functions as func
from urllib.parse import unquote

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Serving the static HTML page and assets.')

    # Get the requested file path from the route, default to 'index.html'
    req_path = req.route_params.get('file', 'index.html')
    req_path = unquote(req_path)  # Decode URL-encoded characters

    # Log the requested path
    logging.info(f'Requested path: {req_path}')

    # Construct the full file path
    base_path = os.path.dirname(__file__)
    file_path = os.path.join(base_path, req_path)

    # Log the constructed file path
    logging.info(f'Constructed file path: {file_path}')

    # Check if the requested file exists
    if not os.path.isfile(file_path):
        logging.error(f'File not found: {file_path}')
        return func.HttpResponse(f"File not found {file_path}", status_code=404)

    # Read the file content
    with open(file_path, 'rb') as file:
        file_content = file.read()

    # Convert the file content to a string for text files (HTML, CSS, JS)
    if file_path.endswith(('.html', '.css', '.js')):
        file_content = file_content.decode('utf-8')
        file_content = file_content.replace('%root%', 'leaderboard_by_http')
        file_content = file_content.encode('utf-8')  # Convert back to bytes

    # Determine the content type
    content_type = "text/html"
    if req_path.endswith('.css'):
        content_type = "text/css"
    elif req_path.endswith('.js'):
        content_type = "application/javascript"
    elif req_path.endswith('.png'):
        content_type = "image/png"
    elif req_path.endswith('.jpg') or req_path.endswith('.jpeg'):
        content_type = "image/jpeg"
    elif req_path.endswith('.otf'):
        content_type = "font/otf"

    # Log the content type
    logging.info(f'Serving file {file_path} with content type {content_type}')

    # Return the file content as the HTTP response
    return func.HttpResponse(file_content, mimetype=content_type)
