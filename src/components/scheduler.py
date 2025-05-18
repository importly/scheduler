from datetime import datetime, date, time, timedelta
from typing import List, Tuple, Dict

from sqlalchemy.orm import Session

from src.components import models

# Type alias for datetime intervals
timeInterval = Tuple[datetime, datetime]


def merge_intervals(intervals: List[timeInterval]) -> List[timeInterval]:
    """
    Merge overlapping intervals and return a sorted list.
    """
    if not intervals:
        return []
    sorted_int = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_int[0]]
    for curr in sorted_int[1:]:
        last_start, last_end = merged[-1]
        curr_start, curr_end = curr
        if curr_start <= last_end:
            merged[-1] = (last_start, max(last_end, curr_end))
        else:
            merged.append(curr)
    return merged


class AvailabilityConfig:
    """
    Represents availability windows for each weekday.
    Attributes:
        availability: Dict[int, List[Tuple[time, time]]]
    """

    def __init__(self, availability: Dict[int, List[Tuple[time, time]]]):
        self.availability = availability

    def get_windows_for_date(self, target_date: date) -> List[timeInterval]:
        """
        Return available datetime intervals for the given date based on weekday availability.
        """
        weekday = target_date.weekday()
        windows: List[timeInterval] = []
        for start_t, end_t in self.availability.get(weekday, []):
            windows.append((datetime.combine(target_date, start_t),
                            datetime.combine(target_date, end_t)))
        return windows


def find_busy_intervals(db: Session, target_date: date) -> List[timeInterval]:
    """
    Query all scheduled tasks (events + todos) on target_date and return occupied intervals.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    tasks = db.query(models.Task).filter(
        models.Task.start_time != None,
        models.Task.end_time != None,
        models.Task.start_time < day_end,
        models.Task.end_time > day_start
    ).all()
    intervals: List[timeInterval] = []
    for t in tasks:
        start = max(t.start_time, day_start)
        end = min(t.end_time, day_end)
        intervals.append((start, end))
    return intervals


def find_free_slots(
    avail_windows: List[timeInterval],
    busy_intervals: List[timeInterval]
) -> List[timeInterval]:
    """
    Subtract busy intervals from availability windows to get free slots.
    """
    merged_busy = merge_intervals(busy_intervals)
    free_slots: List[timeInterval] = []
    for window_start, window_end in avail_windows:
        cursor = window_start
        for busy_start, busy_end in merged_busy:
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
    score = (task.priority or 0) * weights.get('priority', 1.0)
    if task.deadline:
        delta_minutes = (task.deadline - now).total_seconds() / 60
        score += weights.get('deadline', 0.0) / max(delta_minutes, 1)
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
    weights: Dict[str, float],
    now: datetime = None
) -> None:
    """
    Auto-schedule ALL TODO tasks with minute-level deadline enforcement:
      Phase 1: fit tasks into free slots ending by their exact deadline.
      Phase 2: queue overflow tasks immediately after today's last busy interval.

    Optional `now` can be provided (for testing); defaults to UTC now.
    """
    if now is None:
        now = datetime.utcnow()
    today = now.date()

    # Fetch and clear all TODO schedules
    todos = db.query(models.Task).filter(models.Task.type == models.TaskType.TODO).all()
    for task in todos:
        task.scheduled_for = None
        task.start_time = None
        task.end_time = None
        db.add(task)
    db.commit()
    if not todos:
        return

    # Sort tasks by descending priority score
    pending = sorted(
        todos,
        key=lambda t: compute_priority_score(t, now, weights),
        reverse=True
    )
    overflow: List[models.Task] = []

    # Phase 1: schedule before deadline
    for task in pending:
        est = task.estimate or 0
        ddl = task.deadline
        # Expired tasks go straight to overflow
        if ddl and now >= ddl:
            overflow.append(task)
            continue

        scheduled = False
        day_offset = 0
        while True:
            target_date = (now + timedelta(days=day_offset)).date()
            # Stop if past deadline date
            if ddl and target_date > ddl.date():
                break

            windows = availability_config.get_windows_for_date(target_date)
            # Trim today's windows to future
            if day_offset == 0:
                windows = [
                    (max(start, now), end)
                    for start, end in windows if end > now
                ]
            if not windows:
                day_offset += 1
                continue

            busy = find_busy_intervals(db, target_date)
            free_slots = find_free_slots(windows, busy)
            for slot_start, slot_end in free_slots:
                start_time = max(slot_start, now)
                end_candidate = start_time + timedelta(minutes=est)
                # Must finish by exact deadline
                if ddl and end_candidate > ddl:
                    continue
                if end_candidate <= slot_end:
                    task.start_time = start_time
                    task.end_time = end_candidate
                    task.scheduled_for = start_time.date()
                    db.add(task)
                    db.commit()
                    scheduled = True
                    break
            if scheduled:
                break
            day_offset += 1

        if not scheduled:
            overflow.append(task)

    # Phase 2: back-to-back scheduling for overflow, considering only existing EVENTS as busy
    if overflow:
        # Compute today's event-only busy intervals
        day_start = datetime.combine(today, time.min)
        day_end = datetime.combine(today, time.max)
        events = db.query(models.Task).filter(
            models.Task.type == models.TaskType.EVENT,
            models.Task.start_time != None,
            models.Task.end_time != None,
            models.Task.start_time < day_end,
            models.Task.end_time > day_start
        ).all()
        event_busy = []
        for ev in events:
            start = max(ev.start_time, day_start)
            end = min(ev.end_time, day_end)
            event_busy.append((start, end))
        merged_busy = merge_intervals(event_busy)
        pointer = merged_busy[-1][1] if merged_busy else now

        # Schedule overflow tasks
        for task in overflow:
            est = task.estimate or 0
            task.start_time = pointer
            task.end_time = pointer + timedelta(minutes=est)
            task.scheduled_for = pointer.date()
            db.add(task)
            db.commit()
            pointer = task.end_time
