#src/components/models.py
import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class TaskType(enum.Enum):
    EVENT = "event"
    TODO = "todo"


class Status(enum.Enum):
    PENDING = "pending"
    LATER = "later"
    NOT_STARTED = "not-started"
    DONE = "done"


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    color = Column(String(7), default="#CCCCCC")

    tasks = relationship("Task", back_populates="category")


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    type = Column(Enum(TaskType), nullable=False)
    status = Column(Enum(Status), nullable=False, default=Status.NOT_STARTED)
    priority = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Category relationship
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="tasks")

    # Event-specific fields
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)  # in minutes

    # Todo-specific fields
    deadline = Column(DateTime, nullable=True)
    estimate = Column(Integer, nullable=True)  # in minutes
    scheduled_for = Column(Date, nullable=True)
    recurrence_rule = Column(String, nullable=True)

    # External sync field
    external_id = Column(String, unique=True, nullable=True)  # Google Calendar event ID
