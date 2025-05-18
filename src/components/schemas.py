#src/components/schemas.py
from datetime import datetime, date, time
from typing import Optional, Any, Dict, List

from pydantic import BaseModel, Field, model_validator

from src.components.models import TaskType, Status


# Category Schemas
class CategoryBase(BaseModel):
    name: str
    color: Optional[str] = Field(default="#CCCCCC", description="Hex color for UI")


class CategoryCreate(CategoryBase):
    pass


class Category(CategoryBase):
    id: int

    class Config:
        from_attributes = True


# Task Schemas
class TaskBase(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    type: TaskType
    status: Status = Status.PENDING
    priority: int = Field(default=0, ge=0)
    category_id: Optional[int] = None

    # Event-specific fields
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[int] = Field(None, ge=0)

    # Todo-specific fields
    deadline: Optional[datetime] = None
    estimate: Optional[int] = Field(None, gt=0)
    scheduled_for: Optional[date] = None
    recurrence_rule: Optional[str] = None

    @model_validator(mode='after')
    def validate_fields(cls, values: Any) -> Any:
        ttype = values.type
        start = values.start_time
        end = values.end_time
        est = values.estimate
        duration = values.duration
        deadline = values.deadline

        if ttype == TaskType.EVENT:
            if start is None or end is None:
                raise ValueError('Event tasks must have both start_time and end_time')
            if end <= start:
                raise ValueError('end_time must be after start_time')
            expected_duration = int((end - start).total_seconds() // 60)
            if duration is not None and duration != expected_duration:
                raise ValueError('duration must match end_time - start_time')

        if ttype == TaskType.TODO:
            if est is None:
                raise ValueError('Todo tasks must have an estimate')
            if deadline is None:
                raise ValueError('Todo tasks must have a deadline')

        return values


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    type: Optional[TaskType] = None
    status: Optional[Status] = None
    priority: Optional[int] = Field(None, ge=0)
    category_id: Optional[int] = None

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[int] = Field(None, ge=0)

    deadline: Optional[datetime] = None
    estimate: Optional[int] = Field(None, gt=0)
    scheduled_for: Optional[date] = None
    recurrence_rule: Optional[str] = None

    @model_validator(mode='after')
    def validate_update(cls, values: Any) -> Any:
        start = values.start_time
        end = values.end_time
        est = values.estimate

        if start and end and end <= start:
            raise ValueError('end_time must be after start_time')
        if est is not None and est <= 0:
            raise ValueError('estimate must be positive')
        return values


class Task(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
    category: Optional[Category] = None

    class Config:
        from_attributes = True

class AvailabilityWindow(BaseModel):
    start: time
    end:   time

class AutoScheduleRequest(BaseModel):
    # weekday 0=Mon … 6=Sun → list of availability windows
    availability: Dict[int, List[AvailabilityWindow]]
    # e.g. {"priority": 1.0, "deadline": 100.0, "estimate": 0.5}
    weights:       Dict[str, float]