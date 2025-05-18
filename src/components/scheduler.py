# src/components/scheduler.py
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
    Query all scheduled tasks (events + todos with start_time/end_time) on target_date and return their occupied intervals.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    tasks = (
        db.query(models.Task)
        .filter(
            models.Task.start_time != None,
            models.Task.end_time != None,
            models.Task.start_time < day_end,
            models.Task.end_time > day_start
        )
        .all()
    )
    intervals: List[timeInterval] = []
    for t in tasks:
        start = max(t.start_time, day_start)
        end = min(t.end_time, day_end)
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
    score += (task.priority or 0) * weights.get('priority', 1.0)
    if task.deadline:
        delta = task.deadline - now
        minutes = delta.total_seconds() / 60
        if minutes > 0:
            score += weights.get('deadline', 0.0) / minutes
        else:
            score += weights.get('deadline', 0.0) * 1000
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
    Auto-schedule ALL TODO tasks on every run, rescheduling previously scheduled ones:
      - Clear existing schedule from all TODOs.
      - Sort by descending score.
      - For each task, scan days from today, trim today's windows to future only.
      - Recompute busy slots including newly scheduled todos.
      - Place task into first fitting free slot, then commit and move to next.
    """
    now = datetime.utcnow()
    # Fetch all TODO tasks and clear previous scheduling
    todos = (
        db.query(models.Task)
        .filter(models.Task.type == models.TaskType.TODO)
        .all()
    )
    for task in todos:
        task.scheduled_for = None
        task.start_time = None
        task.end_time = None
        db.add(task)
    db.commit()

    if not todos:
        return

    pending = sorted(
        todos,
        key=lambda t: compute_priority_score(t, now, weights),
        reverse=True
    )

    for task in pending:
        estimate = task.estimate or 0
        scheduled = False
        day_offset = 0

        while not scheduled:
            target_date = date.today() + timedelta(days=day_offset)
            windows = availability_config.get_windows_for_date(target_date)
            if day_offset == 0:
                windows = [(max(s, now), e) for s, e in windows if e > now]

            if not windows:
                day_offset += 1
                continue

            busy = find_busy_intervals(db, target_date)
            free_slots = find_free_slots(windows, busy)

            for slot_start, slot_end in free_slots:
                avail_minutes = (slot_end - slot_start).total_seconds() / 60
                if avail_minutes >= estimate:
                    task.scheduled_for = target_date
                    task.start_time = slot_start
                    task.end_time = slot_start + timedelta(minutes=estimate)
                    db.add(task)
                    db.commit()
                    scheduled = True
                    break

            day_offset += 1
            # continue until placed
