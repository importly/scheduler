#src/components/crud.py
from datetime import datetime
from sqlalchemy.orm import Session
from src.components import models, schemas


def get_task(db: Session, task_id: int):
    return db.query(models.Task).filter(models.Task.id == task_id).first()


def get_tasks(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Task).offset(skip).limit(limit).all()


def create_task(db: Session, task: schemas.TaskCreate, category_id: int = None):
    db_task = models.Task(
        title=task.title,
        description=task.description,
        type=task.type,
        status=task.status,
        priority=task.priority,
        start_time=task.start_time,
        end_time=task.end_time,
        duration=task.duration,
        deadline=task.deadline,
        estimate=task.estimate,
        scheduled_for=task.scheduled_for,
        recurrence_rule=task.recurrence_rule,
        category_id=category_id
    )
    if db_task.type == models.TaskType.EVENT and db_task.start_time and db_task.end_time and not db_task.duration:
        delta = db_task.end_time - db_task.start_time
        db_task.duration = int(delta.total_seconds() // 60)

    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def update_task(db: Session, db_task: models.Task, updates: schemas.TaskUpdate):
    for var, value in vars(updates).items():
        if value is not None:
            setattr(db_task, var, value)
    if db_task.type == models.TaskType.EVENT and db_task.start_time and db_task.end_time and not db_task.duration:
        delta = db_task.end_time - db_task.start_time
        db_task.duration = int(delta.total_seconds() // 60)
    db.commit()
    db.refresh(db_task)
    return db_task


def delete_task(db: Session, db_task: models.Task):
    db.delete(db_task)
    db.commit()


def get_categories(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Category).offset(skip).limit(limit).all()


def get_category(db: Session, category_id: int):
    return db.query(models.Category).filter(models.Category.id == category_id).first()


def create_category(db: Session, category: schemas.CategoryCreate):
    db_cat = models.Category(name=category.name, color=category.color)
    db.add(db_cat)
    db.commit()
    db.refresh(db_cat)
    return db_cat


def create_or_update_event(
        db: Session,
        title: str,
        start_iso: str,
        end_iso: str,
        external_id: str,
        description: str = None
):
    """
    Upsert a Google Calendar event into the local DB as a Task.
    If external_id exists, update the existing task; otherwise, create a new one.
    """
    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)
    duration = int((end_dt - start_dt).total_seconds() // 60)

    existing = db.query(models.Task).filter(models.Task.external_id == external_id).first()
    if existing:
        existing.title = title
        existing.description = description or existing.description
        existing.start_time = start_dt
        existing.end_time = end_dt
        existing.duration = duration
        db.commit()
        db.refresh(existing)
        return existing
    else:
        new_event = models.Task(
            title=title,
            description=description,
            type=models.TaskType.EVENT,
            status=models.Status.PENDING,
            start_time=start_dt,
            end_time=end_dt,
            duration=duration,
            external_id=external_id
        )
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        return new_event
