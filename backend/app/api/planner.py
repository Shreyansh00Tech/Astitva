"""Personal planner: tasks and events an employee adds to their own calendar.

Items are private to their owner: nobody else (not a manager, not the Security Manager) can read or change them.
Project tasks assigned to the user are shown alongside, read-only, so the calendar has one view of the week.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.db import get_db
from app.models import PlannerItem, Project, Task

router = APIRouter(prefix="/api", tags=["planner"])

Category = Literal["WORK", "MEETING", "FOCUS", "DEADLINE", "PERSONAL"]
Priority = Literal["LOW", "MEDIUM", "HIGH"]
MAX_SPAN = timedelta(days=31)
MAX_RANGE = timedelta(days=62)


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def item_out(i: PlannerItem) -> dict:
    return {"id": i.id, "title": i.title, "notes": i.notes, "category": i.category, "priority": i.priority,
            "start_at": i.start_at, "end_at": i.end_at, "all_day": i.all_day, "done": i.done,
            "created_at": i.created_at, "updated_at": i.updated_at}


class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    notes: str | None = Field(None, max_length=2000)
    category: Category = "WORK"
    priority: Priority = "MEDIUM"
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    done: bool = False

    @model_validator(mode="after")
    def _check(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Title is required")
        self.start_at, self.end_at = _utc(self.start_at), _utc(self.end_at)
        if self.end_at < self.start_at:
            raise ValueError("End must be after start")
        if self.end_at - self.start_at > MAX_SPAN:
            raise ValueError("A planner item can span at most 31 days")
        return self


class ItemPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=160)
    notes: str | None = Field(None, max_length=2000)
    category: Category | None = None
    priority: Priority | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    done: bool | None = None


def _own(db: Session, cu: CurrentUser, item_id: str) -> PlannerItem:
    i = db.get(PlannerItem, item_id)
    if i is None or i.user_id != cu.id:  # same answer for "missing" and "someone else's": no existence leak
        raise HTTPException(404, "Planner item not found")
    return i


@router.get("/me/planner")
def list_items(start: datetime = Query(...), end: datetime = Query(...),
               cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _utc(start), _utc(end)
    if end <= start or end - start > MAX_RANGE:
        raise HTTPException(422, "Range must be positive and at most 62 days")
    items = db.execute(select(PlannerItem).where(
        PlannerItem.user_id == cu.id, PlannerItem.start_at < end, PlannerItem.end_at >= start,
    ).order_by(PlannerItem.start_at)).scalars().all()
    tasks = db.execute(select(Task, Project.name).join(Project, Project.id == Task.project_id).where(
        Task.assignee_id == cu.id, Task.due_at.is_not(None), Task.due_at >= start, Task.due_at < end,
    ).order_by(Task.due_at)).all()
    return {
        "items": [item_out(i) for i in items],
        "project_tasks": [{"id": t.id, "code": t.code, "title": t.title, "status": t.status, "priority": t.priority,
                           "due_at": t.due_at, "project": pname} for t, pname in tasks],
    }


@router.post("/me/planner", status_code=201)
def create_item(body: ItemIn, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    i = PlannerItem(user_id=cu.id, **body.model_dump())
    db.add(i)
    db.commit()
    db.refresh(i)
    return item_out(i)


@router.patch("/me/planner/{item_id}")
def update_item(item_id: str, body: ItemPatch, cu: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    i = _own(db, cu, item_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
        if not data["title"]:
            raise HTTPException(422, "Title is required")
    for k in ("title", "category", "priority", "start_at", "end_at", "all_day", "done"):
        if k in data and data[k] is None:
            data.pop(k)
    try:
        merged = ItemIn(**{**item_out(i), **data})  # re-run the same checks on the final values
    except ValidationError as e:
        raise HTTPException(422, e.errors()[0]["msg"].removeprefix("Value error, ")) from None
    for k, v in merged.model_dump().items():
        setattr(i, k, v)
    db.commit()
    db.refresh(i)
    return item_out(i)


@router.delete("/me/planner/{item_id}", status_code=204)
def delete_item(item_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, cu, item_id))
    db.commit()
