#tests/test_api.py
#written with AI
import pytest
from datetime import datetime, date, time, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.components import models
from src.components.scheduler import AvailabilityConfig, find_free_slots, slot_tasks, compute_priority_score


TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

@pytest.fixture(scope="module")
def db_session():
    models.Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    models.Base.metadata.drop_all(bind=engine)

@pytest.fixture
def sample_availability():
    # Mon-Fri 9:00-17:00, no weekends
    avail = {i: [(time(9,0), time(17,0))] for i in range(0,5)}
    return AvailabilityConfig(avail)


def test_find_free_slots_empty_busy(sample_availability):
    # No busy intervals on a Monday
    monday = date.today()
    if monday.weekday() != 0:
        # shift to next Monday
        monday += timedelta(days=(7 - monday.weekday()))
    avail_windows = sample_availability.get_windows_for_date(monday)
    free = find_free_slots(avail_windows, [])
    assert len(free) == 1
    start, end = free[0]
    assert start.time() == time(9,0)
    assert end.time() == time(17,0)


def test_find_free_slots_with_busy(sample_availability):
    # Busy 10-11 and 14-15 on a Tuesday
    tuesday = date.today()
    while tuesday.weekday() != 1:
        tuesday += timedelta(days=1)
    avail = sample_availability.get_windows_for_date(tuesday)
    busy = [
        (datetime.combine(tuesday, time(10,0)), datetime.combine(tuesday, time(11,0))),
        (datetime.combine(tuesday, time(14,0)), datetime.combine(tuesday, time(15,0)))
    ]
    free = find_free_slots(avail, busy)
    # Expect three slots: 9-10, 11-14, 15-17
    assert [(s.time(), e.time()) for s,e in free] == [
        (time(9,0), time(10,0)),
        (time(11,0), time(14,0)),
        (time(15,0), time(17,0))
    ]


def test_compute_priority_score():
    # Create a dummy task object
    class Dummy:
        def __init__(self, priority, deadline, estimate):
            self.priority = priority
            self.deadline = deadline
            self.estimate = estimate
    now = datetime(2025,5,1,12,0)
    # deadline 2 hours away => 120 minutes
    task = Dummy(priority=5, deadline=now + timedelta(hours=2), estimate=60)
    weights = {'priority': 2.0, 'deadline': 100.0, 'estimate': 1.0}
    score = compute_priority_score(task, now, weights)
    # priority part: 5*2=10, deadline part:100/120≈0.833, estimate part:60*1=60 => total ≈70.833
    assert pytest.approx(score, rel=1e-3) == 10 + (100/120) + 60


def test_slot_tasks_creates_schedule(db_session, sample_availability):
    # Create two todos: one 60min, one 120min
    t1 = models.Task(
        title="Task1", type=models.TaskType.TODO,
        estimate=60, deadline=datetime.utcnow() + timedelta(days=1)
    )
    t2 = models.Task(
        title="Task2", type=models.TaskType.TODO,
        estimate=120, deadline=datetime.utcnow() + timedelta(days=2)
    )
    # Add existing event on tomorrow 9-10 to block
    tomorrow = date.today() + timedelta(days=1)
    ev = models.Task(
        title="Busy",
        type=models.TaskType.EVENT,
        start_time=datetime.combine(tomorrow, time(9,0)),
        end_time=datetime.combine(tomorrow, time(10,0))
    )
    db_session.add_all([t1, t2, ev])
    db_session.commit()

    weights = {'priority': 1.0, 'deadline': 0.0}
    slot_tasks(db_session, sample_availability, weights)

    # Refresh and verify scheduled_for and times
    db_session.refresh(t1)
    db_session.refresh(t2)
    assert t1.scheduled_for is not None
    assert t1.start_time >= datetime.combine(t1.scheduled_for, time(9,0))
    assert t1.end_time <= datetime.combine(t1.scheduled_for, time(17,0))
    assert t2.scheduled_for is not None
    # Ensure they didn't overlap with the morning event
    assert not (t1.start_time < ev.end_time and t1.end_time > ev.start_time)
    # Both tasks scheduled (tasks list empty)
    remaining = db_session.query(models.Task).filter(
        models.Task.type == models.TaskType.TODO,
        models.Task.scheduled_for.is_(None)
    ).all()
    assert remaining == []
