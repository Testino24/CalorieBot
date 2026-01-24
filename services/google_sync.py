import os.path
import logging
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2 import service_account

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']

def get_service():
    """Builds and returns the Google Docs service."""
    creds_path = 'credentials.json'
    if not os.path.exists(creds_path):
        logging.error("credentials.json not found!")
        return None
    
    try:
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        service = build('docs', 'v1', credentials=creds)
        return service
    except Exception as e:
        logging.error(f"Error connecting to Google Docs: {e}")
        return None

async def append_to_doc(doc_id: str, text: str):
    """Appends text to the end of a Google Doc."""
    # Clean doc_id (handle both full URLs and raw IDs)
    if "docs.google.com/document/d/" in doc_id:
        doc_id = doc_id.split("/d/")[1].split("/")[0]

    service = get_service()
    if not service:
        logging.error("Failed to get Google Docs service.")
        return False
    
    try:
        # 1. Get current doc to find the total length (end index)
        doc = service.documents().get(documentId=doc_id).execute()
        content = doc.get('body').get('content')
        end_index = content[-1].get('endIndex') - 1
        if end_index < 1: end_index = 1

        print(f"DEBUG [v2.1]: Doc length is {end_index}. Appending...")

        # If document is not empty, add a page break FIRST
        if end_index > 2:
            service.documents().batchUpdate(documentId=doc_id, body={
                'requests': [{'insertPageBreak': {'location': {'index': end_index}}}]
            }).execute()
            # After inserting a page break, the document length increases by 1
            end_index += 1

        # Now insert the text
        service.documents().batchUpdate(documentId=doc_id, body={
            'requests': [{
                'insertText': {
                    'location': {'index': end_index},
                    'text': f"\n{text}\n"
                }
            }]
        }).execute()

        print(f"✅ [v2.1] Синхронизация завершена (ID: {doc_id})")
        return True
    except Exception as e:
        print(f"❌ Ошибка Google Docs API: {e}")
        logging.error(f"Error appending to Google Doc: {e}")
        return False
