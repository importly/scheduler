import typer
import httpx
from datetime import datetime
from typing import Optional

app = typer.Typer()
API_URL = "http://localhost:8000"

# Category Commands
@app.command()
def list_categories():
    """List all categories"""
    resp = httpx.get(f"{API_URL}/categories/")
    resp.raise_for_status()
    cats = resp.json()
    for c in cats:
        typer.echo(f"[{c['id']}] {c['name']} (color={c['color']})")

@app.command()
def create_category(name: str, color: str = "#CCCCCC"):
    """Create a new category"""
    payload = {"name": name, "color": color}
    resp = httpx.post(f"{API_URL}/categories/", json=payload)
    resp.raise_for_status()
    c = resp.json()
    typer.echo(f"Created category [ID {c['id']}] {c['name']}")

# Task Commands
@app.command()
def list_tasks():
    """List all tasks"""
    resp = httpx.get(f"{API_URL}/tasks/")
    resp.raise_for_status()
    tasks = resp.json()
    for t in tasks:
        typer.echo(f"[{t['id']}] {t['title']} (type={t['type']}, status={t['status']})")

@app.command()
def create_event(
    title: str,
    start: str = typer.Option(..., help="ISO datetime start, e.g. 2025-05-20T14:00:00"),
    end: str = typer.Option(..., help="ISO datetime end, e.g. 2025-05-20T15:00:00"),
    description: Optional[str] = None
):
    """Create an event task"""
    payload = {"title": title, "type": "event", "start_time": start, "end_time": end}
    if description:
        payload['description'] = description
    resp = httpx.post(f"{API_URL}/tasks/", json=payload)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"Created event task [ID {t['id']}] {t['title']}")

@app.command()
def create_todo(
    title: str,
    estimate: int = typer.Option(..., help="Estimate in minutes"),
    deadline: str = typer.Option(..., help="ISO datetime deadline, e.g. 2025-05-25T23:59:00"),
    priority: int = 0,
    description: Optional[str] = None
):
    """Create a todo task"""
    payload = {"title": title, "type": "todo", "estimate": estimate, "deadline": deadline, "priority": priority}
    if description:
        payload['description'] = description
    resp = httpx.post(f"{API_URL}/tasks/", json=payload)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"Created todo task [ID {t['id']}] {t['title']}")

@app.command()
def update_task(
    task_id: int,
    status: Optional[str] = typer.Option(None, help="New status"),
    title: Optional[str] = typer.Option(None),
    priority: Optional[int] = typer.Option(None),
):
    """Update a task"""
    payload = {}
    if status:
        payload['status'] = status
    if title:
        payload['title'] = title
    if priority is not None:
        payload['priority'] = priority
    if not payload:
        typer.echo("No updates provided.")
        raise typer.Exit()
    resp = httpx.patch(f"{API_URL}/tasks/{task_id}", json=payload)
    resp.raise_for_status()
    t = resp.json()
    typer.echo(f"Updated task [ID {t['id']}] status={t['status']} priority={t['priority']}")

@app.command()
def delete_task(task_id: int):
    """Delete a task"""
    resp = httpx.delete(f"{API_URL}/tasks/{task_id}")
    if resp.status_code == 204:
        typer.echo(f"Deleted task ID {task_id}")
    else:
        resp.raise_for_status()

@app.command()
def sync_calendar():
    """Trigger calendar sync endpoint"""
    resp = httpx.post(f"{API_URL}/calendar/sync")
    resp.raise_for_status()
    result = resp.json()
    typer.echo(f"Imported {result.get('imported',0)} events from Google Calendar.")

if __name__ == "__main__":
    app()
