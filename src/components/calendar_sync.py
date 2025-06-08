import os
import pickle
import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from typing import Tuple, Optional, List

from src.components import models, crud


router = APIRouter(prefix="/calendar", tags=["calendar"])

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_PATH', './credentials.json')
TOKEN_PICKLE = os.getenv('GOOGLE_TOKEN_PATH', './token.pickle')
REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/calendar/oauth2callback')

# Default timezone: Eastern Time
DEFAULT_TIMEZONE = os.getenv('GOOGLE_CALENDAR_TIMEZONE', 'America/New_York')


def build_description(task: models.Task) -> str:
    """Embed task metadata as JSON in the event description."""
    meta = {
        "id": task.id,
        "type": task.type.value,
        "status": task.status.value,
        "priority": task.priority,
        "estimate": task.estimate,
        "duration": task.duration,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
    }
    desc = task.description or ""
    return f"{desc}\n\nTASK:{json.dumps(meta)}"


def parse_description(desc: str) -> Tuple[str, Optional[dict]]:
    """Split description and parse embedded metadata if present."""
    if not desc:
        return "", None
    if "TASK:" not in desc:
        return desc, None
    user_desc, meta_part = desc.rsplit("TASK:", 1)
    try:
        meta = json.loads(meta_part.strip())
    except Exception:
        return desc, None
    return user_desc.strip(), meta

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
    """Two-way sync with Google Calendar."""
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    now_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    events: List[dict] = []
    page_token = None
    while True:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now_iso,
            maxResults=2500,
            singleEvents=True,
            orderBy='startTime',
            timeZone=DEFAULT_TIMEZONE,
            pageToken=page_token,
        ).execute()
        events.extend(events_result.get('items', []))
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break

    ext_ids = {e['id'] for e in events if 'id' in e}
    imported = 0
    deleted = 0
    for item in events:
        start_iso = item['start'].get('dateTime')
        end_iso = item['end'].get('dateTime')
        if not start_iso or not end_iso:
            continue
        title = item.get('summary', '')
        desc_raw = item.get('description', '')
        user_desc, meta = parse_description(desc_raw)
        start_dt = datetime.fromisoformat(start_iso)
        end_dt = datetime.fromisoformat(end_iso)

        if meta and meta.get('id'):
            local = crud.get_task(db, int(meta['id']))
            if local:
                local.title = title
                local.description = user_desc
                local.start_time = start_dt
                local.end_time = end_dt
                local.duration = int((end_dt - start_dt).total_seconds() // 60)
                if meta.get('deadline'):
                    local.deadline = datetime.fromisoformat(meta['deadline'])
                if meta.get('estimate') is not None:
                    local.estimate = meta['estimate']
                if meta.get('priority') is not None:
                    local.priority = meta['priority']
                if meta.get('status'):
                    try:
                        local.status = models.Status(meta['status'])
                    except Exception:
                        pass
                if local.type == models.TaskType.TODO and (
                    local.start_time != start_dt or local.end_time != end_dt
                ):
                    local.type = models.TaskType.EVENT
                    local.estimate = None
                    local.deadline = None
                    local.scheduled_for = None
                local.external_id = item['id']
                db.add(local)
                db.commit()
                imported += 1
                continue

        crud.create_or_update_event(
            db,
            title,
            start_iso,
            end_iso,
            external_id=item['id'],
            description=desc_raw,
        )
        imported += 1

    existing = db.query(models.Task).filter(models.Task.external_id != None).all()
    for task in existing:
        if task.external_id not in ext_ids:
            crud.delete_task(db, task)
            deleted += 1

    return {"imported": imported, "deleted": deleted}


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
        'description': build_description(task),
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
            'description': build_description(task),
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
