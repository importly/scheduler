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
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_PATH', './credentials.json')
TOKEN_PICKLE = os.getenv('GOOGLE_TOKEN_PATH', './token.pickle')
REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/calendar/oauth2callback')

# Default timezone: Eastern Time
DEFAULT_TIMEZONE = os.getenv('GOOGLE_CALENDAR_TIMEZONE', 'America/New_York')

def get_db():
    from src.components.database import SessionLocal
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
            raise HTTPException(
                status_code=401,
                detail="Credentials not found or invalid. Please authenticate."
            )
    return creds


@router.get("/auth-url")
def get_auth_url():
    """
    Generate the OAuth2 authorization URL.
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
    OAuth2 callback endpoint to exchange code for tokens.
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
        orderBy='startTime',
        timeZone=DEFAULT_TIMEZONE
    ).execute()
    events = events_result.get('items', [])
    imported = 0
    for item in events:
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
    Push a single local event or scheduled todo to Google Calendar.
    """
    task = crud.get_task(db, task_id)
    if not task or task.type not in (models.TaskType.EVENT, models.TaskType.TODO):
        raise HTTPException(status_code=400, detail="Invalid task type for push.")
    if task.type == models.TaskType.TODO and (not task.start_time or not task.end_time):
        raise HTTPException(status_code=400, detail="Todo tasks must be scheduled before pushing.")

    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)

    event_body = {
        'summary':     task.title,
        'description': task.description or '',
        'start': {
            'dateTime': task.start_time.isoformat(),
            'timeZone': DEFAULT_TIMEZONE,
        },
        'end': {
            'dateTime': task.end_time.isoformat(),
            'timeZone': DEFAULT_TIMEZONE,
        },
    }

    if task.external_id:
        # patch existing (preserves eventType)
        created = service.events().patch(
            calendarId='primary',
            eventId=task.external_id,
            body=event_body
        ).execute()
    else:
        # insert new
        created = service.events().insert(
            calendarId='primary',
            body=event_body
        ).execute()

    task.external_id = created.get('id')
    db.add(task)
    db.commit()
    return {"google_event_id": task.external_id}


@router.post("/push-all")
def push_all(db: Session = Depends(get_db)):
    """
    Push all local events and scheduled todos to Google Calendar.
    """
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    tasks = db.query(models.Task).filter(
        models.Task.type.in_([models.TaskType.EVENT, models.TaskType.TODO])
    ).all()
    pushed = 0
    updated = 0

    for task in tasks:
        if task.type == models.TaskType.TODO and (not task.start_time or not task.end_time):
            continue

        event_body = {
            'summary':     task.title,
            'description': task.description or '',
            'start': {
                'dateTime': task.start_time.isoformat(),
                'timeZone': DEFAULT_TIMEZONE,
            },
            'end': {
                'dateTime': task.end_time.isoformat(),
                'timeZone': DEFAULT_TIMEZONE,
            },
        }

        if task.external_id:
            # patch, not update
            service.events().patch(
                calendarId='primary',
                eventId=task.external_id,
                body=event_body
            ).execute()
            updated += 1
        else:
            created = service.events().insert(
                calendarId='primary',
                body=event_body
            ).execute()
            task.external_id = created.get('id')
            db.add(task)
            db.commit()
            pushed += 1

    return {"pushed": pushed, "updated": updated}
