#src/components/scheduler.py
from datetime import datetime, date, time, timedelta
from typing import List, Tuple, Dict

from sqlalchemy.orm import Session

from src.components import models

# Type alias for datetime intervals
timeInterval = Tuple[datetime, datetime]


class AvailabilityConfig:
    """
    Represents availability windows for each weekday.
    Attributes:
        availability: Dict[int, List[Tuple[time, time]]]
            Mapping from weekday (0=Monday, 6=Sunday) to a list of (start_time, end_time) tuples.
    """

    def __init__(self, availability: Dict[int, List[Tuple[time, time]]]):
        self.availability = availability

    def get_windows_for_date(self, target_date: date) -> List[timeInterval]:
        """
        Return available datetime intervals for the given date based on weekday availability.
        """
        weekday = target_date.weekday()
        windows: List[timeInterval] = []
        if weekday not in self.availability:
            return []
        for start_t, end_t in self.availability[weekday]:
            start_dt = datetime.combine(target_date, start_t)
            end_dt = datetime.combine(target_date, end_t)
            windows.append((start_dt, end_dt))
        return windows


def find_busy_intervals(db: Session, target_date: date) -> List[timeInterval]:
    """
    Query all 'event' tasks on target_date and return their occupied intervals.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    events = (
        db.query(models.Task)
        .filter(
            models.Task.type == models.TaskType.EVENT,
            models.Task.start_time < day_end,
            models.Task.end_time > day_start
        )
        .all()
    )
    intervals: List[timeInterval] = []
    for ev in events:
        start = max(ev.start_time, day_start)
        end = min(ev.end_time, day_end)
        intervals.append((start, end))
    intervals.sort(key=lambda x: x[0])
    return intervals


def find_free_slots(
        avail_windows: List[timeInterval],
        busy_intervals: List[timeInterval]
) -> List[timeInterval]:
    """
    Subtract busy intervals from availability windows to get free slots.
    """
    # Merge overlapping busy intervals
    merged: List[timeInterval] = []
    for interval in sorted(busy_intervals, key=lambda x: x[0]):
        if not merged:
            merged.append(interval)
        else:
            last_start, last_end = merged[-1]
            curr_start, curr_end = interval
            if curr_start <= last_end:
                merged[-1] = (last_start, max(last_end, curr_end))
            else:
                merged.append(interval)

    free_slots: List[timeInterval] = []
    # Subtract merged busy from each availability window
    for window_start, window_end in avail_windows:
        cursor = window_start
        for busy_start, busy_end in merged:
            if busy_end <= cursor:
                continue
            if busy_start >= window_end:
                break
            if busy_start > cursor:
                free_slots.append((cursor, min(busy_start, window_end)))
            cursor = max(cursor, busy_end)
            if cursor >= window_end:
                break
        if cursor < window_end:
            free_slots.append((cursor, window_end))
    return free_slots


def compute_priority_score(
        task: models.Task,
        now: datetime,
        weights: Dict[str, float]
) -> float:
    score = 0.0
    # Priority factor
    score += (task.priority or 0) * weights.get('priority', 1.0)
    # Deadline (inverse) factor
    if task.deadline:
        delta = task.deadline - now
        minutes = delta.total_seconds() / 60
        if minutes > 0:
            score += weights.get('deadline', 0.0) / minutes
        else:
            score += weights.get('deadline', 0.0) * 1000
    # Additional factors
    for field, weight in weights.items():
        if field in ('priority', 'deadline'):
            continue
        val = getattr(task, field, None)
        if isinstance(val, (int, float)):
            score += val * weight
    return score


def slot_tasks(
        db: Session,
        availability_config: AvailabilityConfig,
        weights: Dict[str, float]
) -> None:
    """
    Auto-schedule unscheduled 'todo' tasks indefinitely:
      1. Fetch all TODO tasks without a scheduled_for date.
      2. Rank by adjustable priority score.
      3. Loop day by day, following weekly availability, until all tasks are scheduled.
    """
    todos = db.query(models.Task).filter(
        models.Task.type == models.TaskType.TODO,
        models.Task.scheduled_for.is_(None)
    ).all()
    if not todos:
        return
    now = datetime.utcnow()
    scored = sorted(
        todos,
        key=lambda t: compute_priority_score(t, now, weights),
        reverse=True
    )
    day_offset = 0
    # Continue until all scored tasks are scheduled
    while scored:
        target_date = date.today() + timedelta(days=day_offset)
        avail_windows = availability_config.get_windows_for_date(target_date)
        if avail_windows:
            busy = find_busy_intervals(db, target_date)
            free_slots = find_free_slots(avail_windows, busy)
            for slot_start, slot_end in free_slots:
                if not scored:
                    break
                task = scored[0]
                estimate = task.estimate or 0
                avail_min = (slot_end - slot_start).total_seconds() / 60
                if avail_min >= estimate:
                    task.scheduled_for = target_date
                    task.start_time = slot_start
                    task.end_time = slot_start + timedelta(minutes=estimate)
                    db.add(task)
                    db.commit()
                    scored.pop(0)
        day_offset += 1
    # End loop when all tasks scheduled
