#test_api.py
#written with AI
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.main import app, get_db
from src.components.database import Base

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Use a shared in‐memory DB so tables persist across connections
TEST_SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)

# 2. Create tables before any tests run
@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

# 3. Override get_db dependency to use the testing session
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_create_and_list_category():
    # create
    resp = client.post("/categories/", json={"name": "Work", "color": "#00FF00"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Work"
    assert data["color"] == "#00FF00"
    assert "id" in data

    # list
    resp = client.get("/categories/")
    assert resp.status_code == 200
    assert any(cat["name"] == "Work" for cat in resp.json())

def test_crud_task_event_and_todo():
    # create an event‐type task
    event_payload = {
      "title": "Meeting",
      "type": "event",
      "start_time": "2025-05-20T14:00:00",
      "end_time":   "2025-05-20T15:00:00"
    }
    resp = client.post("/tasks/", json=event_payload)
    assert resp.status_code == 200
    event_task = resp.json()
    assert event_task["type"] == "event"
    assert event_task["duration"] == 60

    # create a todo‐type task
    todo_payload = {
      "title": "Write report",
      "type": "todo",
      "estimate": 120,
      "deadline": "2025-05-25T23:59:00"
    }
    resp = client.post("/tasks/", json=todo_payload)
    assert resp.status_code == 200
    todo_task = resp.json()
    assert todo_task["type"] == "todo"
    assert todo_task["estimate"] == 120

    # list and verify both
    resp = client.get("/tasks/")
    names = [t["title"] for t in resp.json()]
    assert "Meeting" in names and "Write report" in names

    # update the todo to mark as done
    resp = client.patch(f"/tasks/{todo_task['id']}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

    # delete the event
    resp = client.delete(f"/tasks/{event_task['id']}")
    assert resp.status_code == 204

    # ensure it’s gone
    resp = client.get("/tasks/")
    assert all(t["id"] != event_task["id"] for t in resp.json())
