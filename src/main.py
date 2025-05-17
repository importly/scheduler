# src/main.py
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from src.components import models, schemas, crud
from src.components.calendar_sync import router as calendar_router  # Calendar sync endpoints
from src.components.database import SessionLocal, engine

from fastapi.responses import ORJSONResponse

load_dotenv()

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="scheduler API",default_response_class=ORJSONResponse)

app.include_router(calendar_router)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/categories/", response_model=schemas.Category)
def create_category(category: schemas.CategoryCreate, db: Session = Depends(get_db)):
    # Ensure unique name
    existing = db.query(models.Category).filter(models.Category.name == category.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    return crud.create_category(db, category)


@app.get("/categories/", response_model=List[schemas.Category])
def list_categories(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_categories(db, skip=skip, limit=limit)


@app.get("/categories/{category_id}", response_model=schemas.Category)
def get_category(category_id: int, db: Session = Depends(get_db)):
    db_cat = crud.get_category(db, category_id)
    if not db_cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return db_cat


@app.post("/tasks/", response_model=schemas.Task)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    # Validate category if provided
    if task.category_id is not None:
        if not crud.get_category(db, task.category_id):
            raise HTTPException(status_code=400, detail="Invalid category_id")
    return crud.create_task(db, task, category_id=task.category_id)


@app.get("/tasks/", response_model=List[schemas.Task])
def list_tasks(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_tasks(db, skip=skip, limit=limit)


@app.get("/tasks/{task_id}", response_model=schemas.Task)
def get_task(task_id: int, db: Session = Depends(get_db)):
    db_task = crud.get_task(db, task_id)
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    return db_task


@app.patch("/tasks/{task_id}", response_model=schemas.Task)
def update_task(task_id: int, updates: schemas.TaskUpdate, db: Session = Depends(get_db)):
    db_task = crud.get_task(db, task_id)
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    return crud.update_task(db, db_task, updates)


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    db_task = crud.get_task(db, task_id)
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    crud.delete_task(db, db_task)
    return None


if __name__ == "__main__":
    import cProfile
    import uvicorn

    profiler = cProfile.Profile()
    profiler.enable()

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        loop="asyncio",
        http="httptools",
        reload=False,
        workers=1,
    )

    profiler.disable()
    profiler.dump_stats("profile.prof")
    print("👉 Profile data written to profile.prof")