#src/components/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.components.models import Base

SQLALCHEMY_DATABASE_URL = "sqlite:///./tasks.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# j main database
Base.metadata.create_all(bind=engine)
