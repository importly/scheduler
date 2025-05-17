#src/components/calendar_sync.py

import os
import pickle
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from src.components import models, crud

router = APIRouter(prefix="/calendar", tags=["calendar"])

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_PATH', '../../credentials.json')
TOKEN_PICKLE = os.getenv('GOOGLE_TOKEN_PATH', '../../token.pickle')
REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/calendar/oauth2callback')


def get_db():
    from database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_credentials():
    """
    Load or refresh OAuth2 credentials from disk.
    """
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise HTTPException(status_code=401, detail="Credentials not found or invalid. Please authenticate.")
    return creds


@router.get("/auth-url")
def get_auth_url():
    """
    Generate the OAuth2
    """
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    return {"url": auth_url}


@router.get("/oauth2callback")
def oauth2callback(code: str):
    """
    OAuth2 callback
    """
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    with open(TOKEN_PICKLE, 'wb') as token:
        pickle.dump(creds, token)
    return {"status": "success"}


@router.post("/sync")
def sync_calendar(db: Session = Depends(get_db)):
    """
    Sync events from Google Calendar into the local DB.
    """
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    now_iso = datetime.now(timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId='primary',
        timeMin=now_iso,
        maxResults=2500,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    imported = 0
    for item in events:
        # Only handle events with explicit datetimes
        start_iso = item['start'].get('dateTime')
        end_iso = item['end'].get('dateTime')
        if not start_iso or not end_iso:
            continue
        title = item.get('summary', '')
        description = item.get('description', '')
        crud.create_or_update_event(
            db,
            title,
            start_iso,
            end_iso,
            external_id=item['id'],
            description=description
        )
        imported += 1
    return {"imported": imported}


@router.post("/push/{task_id}")
def push_task(task_id: int, db: Session = Depends(get_db)):
    """
    Push a local event task to Google Calendar.
    """
    task = crud.get_task(db, task_id)
    if not task or task.type != models.TaskType.EVENT:
        raise HTTPException(status_code=400, detail="Invalid event task")
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    event_body = {
        'summary': task.title,
        'description': task.description or '',
        'start': {'dateTime': task.start_time.isoformat()},
        'end': {'dateTime': task.end_time.isoformat()},
    }
    created = service.events().insert(calendarId='primary', body=event_body).execute()
    task.external_id = created.get('id')
    db.add(task)
    db.commit()
    return {"google_event_id": task.external_id}
