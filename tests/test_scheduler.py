#tests/test_scheduler.py
from idlelib.debugger_r import DictProxy

import pytest
from datetime import datetime, date, time, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession
from sqlalchemy.pool import StaticPool
from typing import Dict

from src.components.scheduler import (
    merge_intervals,
    find_free_slots,
    compute_priority_score,
    slot_tasks,
    AvailabilityConfig,
    find_busy_intervals
)
from src.components import models
from src.components.models import TaskType, Status

# In-memory SQLite setup for testing
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False}, # Specific to SQLite
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function") # Changed to function scope for better test isolation
def db_session() -> SQLAlchemySession:
    models.Base.metadata.create_all(bind=engine) # Create tables for each test
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback() # Ensure no changes are accidentally committed if a test fails mid-transaction
        # Clean up data from all known tables that might be affected
        session.query(models.Task).delete()
        session.query(models.Category).delete() # If categories were involved
        session.commit() # Commit the deletions
        # models.Base.metadata.drop_all(bind=engine) # Optionally drop tables if create_all is slow
        session.close()

@pytest.fixture
def empty_availability() -> AvailabilityConfig:
    """Provides an AvailabilityConfig with no available time slots."""
    return AvailabilityConfig({})

@pytest.fixture
def standard_availability_config() -> AvailabilityConfig:
    """
    Provides a standard AvailabilityConfig:
    - Mon-Fri: 9 AM - 12 PM, 1 PM - 5 PM
    - Sat: 10 AM - 2 PM
    - Sun: No availability
    """
    slots = {
        i: [(time(9, 0), time(12, 0)), (time(13, 0), time(17, 0))] for i in range(5) # Mon-Fri
    }
    slots[5] = [(time(10,0), time(14,0))] # Saturday (weekday 5)
    slots[6] = [] # Sunday (weekday 6)
    return AvailabilityConfig(slots)

@pytest.fixture
def original_sample_availability() -> AvailabilityConfig:
    """Availability from the original test: 9-10 AM and 3-4 PM every day."""
    slots = {i: [(time(9,0), time(10,0)), (time(15,0), time(16,0))] for i in range(7)}
    return AvailabilityConfig(slots)


def create_task_in_db(db: SQLAlchemySession, **kwargs) -> models.Task:
    """Helper function to create and commit a task to the database."""
    # Sensible defaults, can be overridden by kwargs
    params = {
        "title": "Test Task",
        "type": TaskType.TODO,
        "status": Status.PENDING,
        "priority": 0,
        # Default TODO fields (can be overridden or removed if type is EVENT)
        "estimate": 30,
        "deadline": datetime.utcnow() + timedelta(days=1),
        **kwargs
    }

    if params["type"] == TaskType.EVENT:
        if not params.get("start_time") or not params.get("end_time"):
            raise ValueError("EVENT tasks require start_time and end_time.")
        # Remove TODO-specific fields if present and not applicable
        params.pop("estimate", None)
        params.pop("deadline", None)
        params["duration"] = int((params["end_time"] - params["start_time"]).total_seconds() / 60)
    elif params["type"] == TaskType.TODO:
        if params.get("estimate") is None:
            raise ValueError("TODO tasks require an estimate.")
        if params.get("deadline") is None:
            raise ValueError("TODO tasks require a deadline.")
        # Remove EVENT-specific fields if present
        params.pop("start_time", None)
        params.pop("end_time", None)
        params.pop("duration", None)

    task = models.Task(**params)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@pytest.fixture
def default_weights() -> Dict[str, float]:
    """Provides a default set of weights for scoring."""
    return {'priority': 1.0, 'deadline': 10.0, 'estimate': 0.1}


# --- Tests for merge_intervals ---
def test_merge_intervals_empty_list():
    assert merge_intervals([]) == []

def test_merge_intervals_single_interval():
    interval = (datetime(2025, 5, 18, 9, 0), datetime(2025, 5, 18, 10, 0))
    assert merge_intervals([interval]) == [interval]

def test_merge_intervals_non_overlapping_sorted():
    intervals = [
        (datetime(2025, 5, 18, 9, 0), datetime(2025, 5, 18, 10, 0)),
        (datetime(2025, 5, 18, 11, 0), datetime(2025, 5, 18, 12, 0)),
    ]
    assert merge_intervals(intervals) == intervals

def test_merge_intervals_adjacent_intervals():
    intervals = [
        (datetime(2025, 5, 18, 9, 0), datetime(2025, 5, 18, 10, 0)),
        (datetime(2025, 5, 18, 10, 0), datetime(2025, 5, 18, 11, 0)), # Adjacent
    ]
    expected = [(datetime(2025, 5, 18, 9, 0), datetime(2025, 5, 18, 11, 0))]
    assert merge_intervals(intervals) == expected

def test_merge_intervals_overlapping_and_contained():
    intervals = [
        (datetime(2025, 5, 18, 9, 0), datetime(2025, 5, 18, 12, 0)),  # Outer
        (datetime(2025, 5, 18, 10, 0), datetime(2025, 5, 18, 11, 0)), # Inner, contained
        (datetime(2025, 5, 18, 11, 30), datetime(2025, 5, 18, 13, 0)),# Overlapping outer
        (datetime(2025, 5, 18, 14, 0), datetime(2025, 5, 18, 15, 0)), # Separate
    ]
    expected = [
        (datetime(2025, 5, 18, 9, 0), datetime(2025, 5, 18, 13, 0)),
        (datetime(2025, 5, 18, 14, 0), datetime(2025, 5, 18, 15, 0)),
    ]
    assert merge_intervals(intervals) == expected

def test_merge_intervals_unsorted_input_provided():
    intervals = [
        (datetime(2025,5,18,12,0), datetime(2025,5,18,12,30)),
        (datetime(2025,5,18,9,30), datetime(2025,5,18,11,0)), # This interval overlaps the next one
        (datetime(2025,5,18,9,0), datetime(2025,5,18,10,0)),
    ]
    merged = merge_intervals(intervals) # Function sorts internally
    assert merged == [
        (datetime(2025,5,18,9,0), datetime(2025,5,18,11,0)),
        (datetime(2025,5,18,12,0), datetime(2025,5,18,12,30))
    ]

# --- Tests for AvailabilityConfig.get_windows_for_date ---
def test_get_windows_for_date_configured_weekday(standard_availability_config):
    target_date = date(2025, 5, 19) # Monday
    windows = standard_availability_config.get_windows_for_date(target_date)
    assert windows == [
        (datetime(2025, 5, 19, 9, 0), datetime(2025, 5, 19, 12, 0)),
        (datetime(2025, 5, 19, 13, 0), datetime(2025, 5, 19, 17, 0)),
    ]

def test_get_windows_for_date_configured_saturday(standard_availability_config):
    target_date = date(2025, 5, 24) # Saturday
    windows = standard_availability_config.get_windows_for_date(target_date)
    assert windows == [(datetime(2025, 5, 24, 10, 0), datetime(2025, 5, 24, 14, 0))]

def test_get_windows_for_date_unconfigured_sunday(standard_availability_config):
    target_date = date(2025, 5, 25) # Sunday
    windows = standard_availability_config.get_windows_for_date(target_date)
    assert windows == [] # No slots configured for Sunday

def test_get_windows_for_date_with_empty_availability_config(empty_availability):
    target_date = date(2025, 5, 19) # Monday
    windows = empty_availability.get_windows_for_date(target_date)
    assert windows == []

# --- Tests for find_busy_intervals ---
def test_find_busy_intervals_no_tasks_on_date(db_session):
    target_date = date(2025, 5, 19)
    busy = find_busy_intervals(db_session, target_date)
    assert busy == []

def test_find_busy_intervals_one_event_fully_within(db_session):
    target_date = date(2025, 5, 19)
    create_task_in_db(
        db_session, type=TaskType.EVENT,
        start_time=datetime(2025, 5, 19, 10, 0), end_time=datetime(2025, 5, 19, 11, 0)
    )
    busy = find_busy_intervals(db_session, target_date)
    assert busy == [(datetime(2025, 5, 19, 10, 0), datetime(2025, 5, 19, 11, 0))]

def test_find_busy_intervals_task_starts_before_ends_within_day(db_session):
    target_date = date(2025, 5, 19)
    create_task_in_db(
        db_session, type=TaskType.EVENT,
        start_time=datetime(2025, 5, 18, 23, 0), end_time=datetime(2025, 5, 19, 1, 0)
    )
    busy = find_busy_intervals(db_session, target_date)
    # Busy interval should be clipped to the start of target_date
    expected_start = datetime.combine(target_date, time.min)
    assert busy == [(expected_start, datetime(2025, 5, 19, 1, 0))]

def test_find_busy_intervals_task_starts_within_ends_after_day(db_session):
    target_date = date(2025, 5, 19)
    create_task_in_db(
        db_session, type=TaskType.EVENT,
        start_time=datetime(2025, 5, 19, 23, 0), end_time=datetime(2025, 5, 20, 1, 0)
    )
    busy = find_busy_intervals(db_session, target_date)
    # Busy interval should be clipped to the end of target_date
    expected_end = datetime.combine(target_date, time.max)
    assert busy == [(datetime(2025, 5, 19, 23, 0), expected_end)]

def test_find_busy_intervals_task_spans_entire_day(db_session):
    target_date = date(2025, 5, 19)
    create_task_in_db(
        db_session, type=TaskType.EVENT,
        start_time=datetime(2025, 5, 18, 10, 0), end_time=datetime(2025, 5, 20, 10, 0)
    )
    busy = find_busy_intervals(db_session, target_date)
    expected_start = datetime.combine(target_date, time.min)
    expected_end = datetime.combine(target_date, time.max)
    assert busy == [(expected_start, expected_end)]



# --- Tests for find_free_slots ---
def test_find_free_slots_no_availability_windows():
    busy = [(datetime(2025,5,19,9,0), datetime(2025,5,19,10,0))]
    assert find_free_slots([], busy) == []

def test_find_free_slots_no_busy_intervals(standard_availability_config):
    day = date(2025, 5, 19) # Monday: 9-12, 13-17
    avail_windows = standard_availability_config.get_windows_for_date(day)
    assert find_free_slots(avail_windows, []) == avail_windows

def test_find_free_slots_busy_covers_all_avail(standard_availability_config):
    day = date(2025, 5, 19)
    avail_windows = standard_availability_config.get_windows_for_date(day) # [(9-12), (13-17)]
    busy = [(datetime(2025,5,19,8,0), datetime(2025,5,19,18,0))] # Covers 8 AM to 6 PM
    assert find_free_slots(avail_windows, busy) == []

def test_find_free_slots_busy_at_edges_of_windows(standard_availability_config):
    day = date(2025, 5, 19)
    avail_windows = standard_availability_config.get_windows_for_date(day) # [(9-12), (13-17)]
    busy = [
        (datetime(2025,5,19,9,0), datetime(2025,5,19,9,30)),   # Busy 9:00-9:30
        (datetime(2025,5,19,11,30), datetime(2025,5,19,12,0)), # Busy 11:30-12:00
        (datetime(2025,5,19,13,0), datetime(2025,5,19,13,30)), # Busy 13:00-13:30
        (datetime(2025,5,19,16,30), datetime(2025,5,19,17,0)), # Busy 16:30-17:00
    ]
    expected_free = [
        (datetime(2025,5,19,9,30), datetime(2025,5,19,11,30)),
        (datetime(2025,5,19,13,30), datetime(2025,5,19,16,30)),
    ]
    assert find_free_slots(avail_windows, busy) == expected_free

def test_find_free_slots_busy_partially_overlapping_window_outside_edges(standard_availability_config):
    day = date(2025,5,19)
    avail_windows = standard_availability_config.get_windows_for_date(day) # [(9-12), (13-17)]
    busy = [
        (datetime(2025,5,19,8,0), datetime(2025,5,19,9,30)),   # Busy from 8:00, covering start of first window
        (datetime(2025,5,19,16,30), datetime(2025,5,19,18,00)), # Busy until 18:00, covering end of second window
    ]
    expected_free = [
        (datetime(2025,5,19,9,30), datetime(2025,5,19,12,0)),
        (datetime(2025,5,19,13,0), datetime(2025,5,19,16,30)),
    ]
    assert find_free_slots(avail_windows, busy) == expected_free

def test_find_free_slots_multiple_busy_intervals_splitting_one_window(standard_availability_config):
    day = date(2025, 5, 24) # Saturday: 10 AM - 2 PM
    avail_windows = standard_availability_config.get_windows_for_date(day) # Single window: [(10-14)]
    busy = [
        (datetime(2025,5,24,10,30), datetime(2025,5,24,11,0)),
        (datetime(2025,5,24,11,30), datetime(2025,5,24,12,0)),
        (datetime(2025,5,24,12,30), datetime(2025,5,24,13,0)),
    ]
    expected_free = [
        (datetime(2025,5,24,10,0), datetime(2025,5,24,10,30)),
        (datetime(2025,5,24,11,0), datetime(2025,5,24,11,30)),
        (datetime(2025,5,24,12,0), datetime(2025,5,24,12,30)),
        (datetime(2025,5,24,13,0), datetime(2025,5,24,14,0)),
    ]
    assert find_free_slots(avail_windows, busy) == expected_free

# --- Tests for compute_priority_score ---
class DummyTaskForScore: # Simplified dummy task for scoring tests
    def __init__(self, **kwargs):
        self.priority = kwargs.get('priority', 0)
        self.deadline = kwargs.get('deadline', None)
        # Allow any other attributes for testing extra fields in weights
        for key, value in kwargs.items():
            if key not in ['priority', 'deadline']:
                setattr(self, key, value)

def test_compute_priority_score_all_components():
    now = datetime(2025, 5, 18, 8, 0)
    task = DummyTaskForScore(priority=5, deadline=now + timedelta(hours=2), custom_metric=10) # deadline in 120 mins
    weights = {'priority': 2.0, 'deadline': 120.0, 'custom_metric': 0.5}
    # Score = (5 * 2.0) + (120.0 / 120) + (10 * 0.5) = 10 + 1 + 5 = 16
    assert compute_priority_score(task, now, weights) == pytest.approx(16.0)

def test_compute_priority_score_no_deadline_field():
    now = datetime(2025, 5, 18, 8, 0)
    task = DummyTaskForScore(priority=3) # No deadline attribute
    weights = {'priority': 1.0, 'deadline': 100.0}
    assert compute_priority_score(task, now, weights) == 3.0

def test_compute_priority_score_deadline_passed_uses_min_delta():
    now = datetime(2025, 5, 18, 8, 0)
    task = DummyTaskForScore(priority=1, deadline=now - timedelta(minutes=30)) # Deadline in the past
    weights = {'priority': 1.0, 'deadline': 100.0}
    # delta_minutes is < 1, so max(delta_minutes, 1) = 1. Score = (1*1) + (100/1) = 101
    assert compute_priority_score(task, now, weights) == pytest.approx(101.0)

def test_compute_priority_score_missing_weights_for_fields():
    now = datetime(2025, 5, 18, 8, 0)
    task = DummyTaskForScore(priority=2, deadline=now + timedelta(minutes=60), extra_val=5)
    weights = {'priority': 3.0} # 'deadline' weight missing (defaults to 0), 'extra_val' weight missing
    # Score = (2 * 3.0) + (0.0 / 60) + (extra_val * 0 if 'extra_val' not in weights) = 6
    assert compute_priority_score(task, now, weights) == pytest.approx(6.0)

def test_compute_priority_score_non_numeric_extra_field_ignored():
    now = datetime(2025, 5, 18, 8, 0)
    task = DummyTaskForScore(priority=1, name="Important Task")
    weights = {'priority': 1.0, 'name': 100.0} # Weight for 'name'
    # 'name' is not numeric, so it's skipped by isinstance check
    assert compute_priority_score(task, now, weights) == 1.0

# --- Tests for slot_tasks ---
# Base 'now' for most slot_tasks tests: Monday, May 19, 2025, 8:00 AM
# Standard availability: Mon-Fri 9-12, 13-17; Sat 10-14

def test_slot_tasks_single_task_fits_perfectly(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    task = create_task_in_db(db_session, title="Easy Fit", estimate=60, deadline=datetime(2025,5,19,17,0))
    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task)
    assert task.scheduled_for == date(2025, 5, 19)
    assert task.start_time == datetime(2025, 5, 19, 9, 0)
    assert task.end_time == datetime(2025, 5, 19, 10, 0)

def test_slot_tasks_wipes_and_reschedules_existing_todos(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    # Pre-existing, possibly badly scheduled TODO
    task_old = create_task_in_db(db_session, title="Old TODO", estimate=30, deadline=datetime(2025,5,20),
                                 start_time=datetime(2025,5,19,1,0), end_time=datetime(2025,5,19,1,30), scheduled_for=date(2025,5,19))
    task_new = create_task_in_db(db_session, title="New TODO", estimate=60, deadline=datetime(2025,5,19,17,0), priority=5) # Higher prio

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task_old)
    db_session.refresh(task_new)

    # task_new (higher prio) should get the first slot
    assert task_new.start_time == datetime(2025,5,19,9,0)
    assert task_new.end_time == datetime(2025,5,19,10,0)
    # task_old should be rescheduled after task_new
    assert task_old.start_time == datetime(2025,5,19,10,0)
    assert task_old.end_time == datetime(2025,5,19,10,30)

def test_slot_tasks_priority_and_deadline_ordering(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    # Task A: High priority, later deadline
    task_A = create_task_in_db(db_session, title="A (HighPrio)", estimate=60, deadline=datetime(2025,5,19,17,0), priority=10)
    # Task B: Low priority, earlier deadline (but not super urgent)
    task_B = create_task_in_db(db_session, title="B (LowPrio, EarlierDDL)", estimate=60, deadline=datetime(2025,5,19,12,0), priority=1)
    # Task C: Medium priority, very urgent deadline that should take precedence if score is higher
    task_C = create_task_in_db(db_session, title="C (MedPrio, UrgentDDL)", estimate=30, deadline=datetime(2025,5,19,9,30), priority=5)
    # Scores (approx, depends on exact 'deadline' weight effect):
    # A: Prio=10. DDL far. Score dominated by Prio.
    # B: Prio=1. DDL closer.
    # C: Prio=5. DDL very close (9:30). DDL score will be high: 10 / (90 mins) = 0.11 per min.  (10 / (90-now_offset))
    # Let's make C's deadline score high. Deadline weight is 10. now=8:00, ddl=9:30 (90min delta) -> 10/90. Prio=5. Score_C ~ 5 + 10/90.
    # Score_A ~ 10 + 10/(9*60). Score_A will be higher due to raw priority. C should still fit its deadline.
    # A should be first, then C must fit before its deadline, then B.

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task_A)
    db_session.refresh(task_B)
    db_session.refresh(task_C)

    # A (highest score due to priority)
    assert task_A.start_time == datetime(2025,5,19,9,0) # 9:00 - 10:00
    assert task_A.end_time == datetime(2025,5,19,10,0)

    # C must fit its deadline of 9:30. This means the current scheduler might not be optimal if A blocks C.
    # The current scheduler sorts all tasks first, then places.
    # If A is first, it takes 9-10. C (ddl 9:30) cannot be placed in Phase 1. It goes to overflow.
    # This highlights a potential refinement area for the scheduler if hard deadlines are critical.
    # For now, we test current behavior.
    # After A (9-10), C (ddl 9:30, estimate 30m) fails Phase 1.
    # B (ddl 12:00, est 60m) is next. Free slots after A: 10:00-12:00. B fits 10:00-11:00.
    assert task_B.start_time == datetime(2025,5,19,10,0) # 10:00 - 11:00
    assert task_B.end_time == datetime(2025,5,19,11,0)

    # C goes to overflow. No events. Starts at `now` (8:00).
    assert task_C.start_time == now # This means it schedules "in the past" conceptually if `now` is used directly.
    assert task_C.end_time == now + timedelta(minutes=30)
    assert task_C.scheduled_for == now.date()

def test_slot_tasks_task_cannot_fit_before_deadline_goes_to_phase2_overflow(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    create_task_in_db(db_session, type=TaskType.EVENT, title="Blocker", start_time=datetime(2025,5,19,9,0), end_time=datetime(2025,5,19,10,0))
    # Task estimate 60m, deadline 9:30. Cannot fit in avail [9-12] due to blocker.
    task_overflow = create_task_in_db(db_session, title="Cant Fit", estimate=60, deadline=datetime(2025,5,19,9,30))

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task_overflow)
    # Phase 2: overflow starts after blocker event (10:00)
    assert task_overflow.start_time == datetime(2025,5,19,10,0)
    assert task_overflow.end_time == datetime(2025,5,19,11,0)

def test_slot_tasks_deadline_already_passed_goes_to_phase2_overflow(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 10, 0)
    event = create_task_in_db(db_session, type=TaskType.EVENT, title="Blocker", start_time=datetime(2025,5,19,13,0), end_time=datetime(2025,5,19,14,0))
    task_overdue = create_task_in_db(db_session, title="Overdue", estimate=30, deadline=datetime(2025,5,19,9,0)) # Deadline was 9 AM

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task_overdue)
    # Phase 2: overflow starts after event (14:00) because event end (14:00) > now (10:00)
    assert task_overdue.start_time == event.end_time
    assert task_overdue.end_time == event.end_time + timedelta(minutes=30)

def test_slot_tasks_multiple_overflow_tasks_back_to_back_after_event(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    event = create_task_in_db(db_session, type=TaskType.EVENT, title="Blocker", start_time=datetime(2025,5,19,9,0), end_time=datetime(2025,5,19,9,30))
    # These will go to overflow, ordered by priority
    task_over1 = create_task_in_db(db_session, title="Overflow1", estimate=30, deadline=now, priority=10)
    task_over2 = create_task_in_db(db_session, title="Overflow2", estimate=45, deadline=now, priority=5)

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task_over1)
    db_session.refresh(task_over2)

    assert task_over1.start_time == event.end_time # Starts 9:30
    assert task_over1.end_time == event.end_time + timedelta(minutes=30) # Ends 10:00
    assert task_over2.start_time == task_over1.end_time # Starts 10:00
    assert task_over2.end_time == task_over1.end_time + timedelta(minutes=45) # Ends 10:45

def test_slot_tasks_overflow_starts_at_now_if_no_events(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 16, 30) # Available 13-17. Remaining: 16:30-17:00 (30min)
    # Task is 60min, deadline 17:00. Won't fit in Phase 1.
    task = create_task_in_db(db_session, title="Too Long For Slot", estimate=60, deadline=datetime(2025,5,19,17,0))

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task)
    # Phase 2: no events, overflow pointer starts at `now` (16:30)
    assert task.start_time == now
    assert task.end_time == now + timedelta(minutes=60) # 16:30 + 60min = 17:30

def test_slot_tasks_trims_todays_windows_to_start_from_now(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 9, 30) # Middle of 9-12 slot
    task = create_task_in_db(db_session, title="Mid-Slot Start", estimate=30, deadline=datetime(2025,5,19,12,0))
    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task)
    assert task.start_time == datetime(2025,5,19,9,30) # Starts at 'now'
    assert task.end_time == datetime(2025,5,19,10,0)

def test_slot_tasks_no_todo_tasks_to_schedule(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    create_task_in_db(db_session, type=TaskType.EVENT, title="Only Event", start_time=now, end_time=now+timedelta(hours=1))
    try:
        slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    except Exception as e:
        pytest.fail(f"slot_tasks raised an exception with no TODOs: {e}")
    # Check event is untouched
    event = db_session.query(models.Task).filter_by(title="Only Event").one()
    assert event.start_time == now # Events are not modified by slot_tasks directly

def test_slot_tasks_no_availability_all_tasks_go_to_overflow(db_session, empty_availability, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    task1 = create_task_in_db(db_session, title="T1", estimate=60, deadline=datetime(2025,5,20), priority=10)
    task2 = create_task_in_db(db_session, title="T2", estimate=30, deadline=datetime(2025,5,20), priority=5)
    slot_tasks(db_session, empty_availability, default_weights, now=now)
    db_session.refresh(task1); db_session.refresh(task2)

    assert task1.start_time == now # Overflow starts at now, task1 higher prio
    assert task1.end_time == now + timedelta(minutes=60)
    assert task2.start_time == task1.end_time # Task2 after task1
    assert task2.end_time == task1.end_time + timedelta(minutes=30)

def test_slot_tasks_task_estimate_longer_than_effective_deadline_window(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0) # Avail from 9 AM.
    # Task: 60min estimate, deadline 9:30 AM. Effective window: 9:00-9:30 (30min). Cannot fit.
    task = create_task_in_db(db_session, title="Too Long For DDL Window", estimate=60, deadline=datetime(2025,5,19,9,30))
    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task)
    # Goes to overflow, no events, starts at 'now' (8:00)
    assert task.start_time == now
    assert task.end_time == now + timedelta(minutes=60)

def test_slot_tasks_correctly_skips_over_existing_events(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    create_task_in_db(db_session, type=TaskType.EVENT, title="Mid Morning Event", start_time=datetime(2025,5,19,10,0), end_time=datetime(2025,5,19,11,0))
    task_before = create_task_in_db(db_session, title="Before Event", estimate=60, deadline=datetime(2025,5,19,17,0), priority=10)
    task_after = create_task_in_db(db_session, title="After Event", estimate=60, deadline=datetime(2025,5,19,17,0), priority=5)

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task_before); db_session.refresh(task_after)

    assert task_before.start_time == datetime(2025,5,19,9,0) # 9:00-10:00
    assert task_before.end_time == datetime(2025,5,19,10,0)
    assert task_after.start_time == datetime(2025,5,19,11,0) # Skips 10-11 event, 11:00-12:00
    assert task_after.end_time == datetime(2025,5,19,12,0)

def test_slot_tasks_long_task_uses_large_continuous_slot(db_session, default_weights):
    now = datetime(2025, 5, 19, 8, 0)
    custom_avail = AvailabilityConfig({0: [(time(9,0), time(17,0))]}) # Mon 9AM-5PM (8 hours)
    long_task = create_task_in_db(db_session, title="Long Task", estimate=240, deadline=datetime(2025,5,19,17,0)) # 4 hours

    slot_tasks(db_session, custom_avail, default_weights, now=now)
    db_session.refresh(long_task)
    assert long_task.start_time == datetime(2025,5,19,9,0)
    assert long_task.end_time == datetime(2025,5,19,13,0) # 9 AM + 4 hours = 1 PM

def test_slot_tasks_now_is_past_all_todays_availability(db_session, standard_availability_config, default_weights):
    now = datetime(2025, 5, 19, 18, 0) # Mon 6 PM. All Mon avail (9-12, 13-17) has passed.
    task = create_task_in_db(db_session, title="Next Day Task", estimate=60, deadline=datetime(2025,5,20,17,0))

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task)
    # Should be scheduled on Tue (May 20)
    assert task.scheduled_for == date(2025,5,20)
    assert task.start_time == datetime(2025,5,20,9,0)
    assert task.end_time == datetime(2025,5,20,10,0)

def test_slot_tasks_deadline_on_day_with_no_availability_goes_to_overflow(db_session, standard_availability_config, default_weights):
    # standard_availability_config: Sunday (weekday 6) has no availability.
    now = datetime(2025, 5, 24, 18, 0) # Saturday 6 PM. Sat avail (10-14) has passed.
                                      # Next day is Sunday, May 25 (no avail).
                                      # Then Monday, May 26.
    # Task deadline is Sunday noon.
    task = create_task_in_db(db_session, title="Sun DDL Task", estimate=60, deadline=datetime(2025,5,25,12,0))

    slot_tasks(db_session, standard_availability_config, default_weights, now=now)
    db_session.refresh(task)

    # Phase 1:
    # Day 0 (Sat, May 24): `now` (18:00) is past avail (10-14). No slots.
    # Day 1 (Sun, May 25): `get_windows_for_date` returns []. No slots. (target_date is not > ddl.date())
    # Day 2 (Mon, May 26): `target_date` (Mon) > `ddl.date()` (Sun). Loop breaks. Task not scheduled.
    # Task goes to overflow. No events. Overflow pointer is `now` (Sat 18:00).
    assert task.scheduled_for == date(2025,5,24) # Scheduled on the 'today' of the overflow phase
    assert task.start_time == now # Sat 18:00
    assert task.end_time == now + timedelta(minutes=60) # Sat 19:00

# --- Tests from original user suite, adapted ---
def test_slot_tasks_original_fit_before_deadline_logic(db_session, original_sample_availability):
    # original_sample_availability: 9-10 AM, 3-4 PM daily
    now = datetime(2025,5,18,8,0) # Sunday, May 18th
    ddl = datetime(2025,5,18,10,0) # Sun 10 AM
    task_to_fit = create_task_in_db(db_session, title='FitBefore', estimate=60, deadline=ddl)
    weights = {'priority':1.0, 'deadline':10.0} # Original weights

    slot_tasks(db_session, original_sample_availability, weights, now=now)
    db_session.refresh(task_to_fit)
    assert task_to_fit.start_time == datetime(2025,5,18,9,0)
    assert task_to_fit.end_time == datetime(2025,5,18,10,0)

def test_slot_tasks_original_overflow_logic(db_session, original_sample_availability):
    now = datetime(2025,5,18,8,0) # Sunday 8 AM
    task_late = create_task_in_db(db_session, title='Late', estimate=30, deadline=now - timedelta(minutes=5)) # Deadline passed
    event_busy = create_task_in_db(db_session, title='Busy', type=TaskType.EVENT, start_time=now, end_time=now + timedelta(minutes=30)) # Event 8:00-8:30 Sun
    weights = {'priority':1.0, 'deadline':5.0} # Original weights

    slot_tasks(db_session, original_sample_availability, weights, now=now)
    db_session.refresh(task_late)

    # task_late goes to overflow. Overflow pointer starts after event_busy (8:30 AM)
    assert task_late.start_time == event_busy.end_time
    assert task_late.end_time == event_busy.end_time + timedelta(minutes=30)