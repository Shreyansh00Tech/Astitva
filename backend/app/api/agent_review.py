"""Agent review (dual score). The full agent graph is for the Security Manager only; a Manager sees the final record."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import _can_view_request
from app.api.deps import CurrentUser, get_current_user, require
from app.api.serializers import request_out
from app.core.db import get_db
from app.models import AccessRequest, AgentReview
from app.services import agent_review

router = APIRouter(prefix="/api", tags=["agent-review"])


@router.get("/agent-review/queue")
def queue(cu: CurrentUser = Depends(require("risk:decide")), db: Session = Depends(get_db)):
    rows = db.execute(select(AgentReview, AccessRequest).join(AccessRequest, AccessRequest.id == AgentReview.request_id)
                      .order_by(AgentReview.updated_at.desc()).limit(100)).all()
    out = {"awaiting": [], "recent": []}
    for review, req in rows:
        item = {**agent_review.summary_out(review), "request": request_out(req),
                "agents": [{"code": a["code"], "name": a["name"], "verdict": a["verdict"], "delta": a["delta"]}
                           for a in review.agents or []]}
        (out["awaiting"] if review.status == "AWAITING_CHOICE" else out["recent"]).append(item)
    return out


@router.get("/requests/{request_id}/agent-review")
def get_review(request_id: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    req = db.get(AccessRequest, request_id)
    if not req or not _can_view_request(db, cu, req):
        raise HTTPException(404, "Request not found")
    review = agent_review.get(db, request_id)
    if not review:
        raise HTTPException(404, "No agent review for this request")
    if cu.has("risk:decide"):
        out = agent_review.full_out(review)
        out["can_choose"] = (review.status == "AWAITING_CHOICE" and cu.id not in (req.requester_id, req.requester.manager_id))
        out["request"] = request_out(req, include_detail=True)
        return out
    if cu.has("approvals:read") and cu.id != req.requester_id:
        return {**agent_review.summary_out(review), "view": "summary"}
    raise HTTPException(404, "No agent review for this request")


@router.post("/agent-review/demo")
def load_demo(cu: CurrentUser = Depends(require("risk:decide")), db: Session = Depends(get_db)):
    """Submit three simulated requests through the real workflow so every agent (and a disagreement) can be shown."""
    from app.services.agent_review import demo
    from app.services.workflow import WorkflowError

    try:
        return {"scenarios": demo.run(db, cu.actor)}
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(e.status, {"message": e.message, "rule": e.rule})


class ChoiceIn(BaseModel):
    choice: str = Field(pattern="^(RULE|AI)$")
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/agent-review/{request_id}/choose")
def choose(request_id: str, body: ChoiceIn, cu: CurrentUser = Depends(require("risk:decide")),
           db: Session = Depends(get_db)):
    req = db.get(AccessRequest, request_id)
    if not req or not _can_view_request(db, cu, req):
        raise HTTPException(404, "Request not found")
    try:
        review = agent_review.choose(db, cu.actor, request_id, body.choice, body.reason)
    except agent_review.ReviewError as e:
        raise HTTPException(e.status, {"message": e.message, "rule": e.rule})
    return agent_review.full_out(review)
