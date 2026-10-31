"""Deadline-based priority for pending access requests.

Priority only decides the ORDER in which reviewers see work. It never changes the risk score, the approval path
or whether access is granted. It is computed when read (with an injectable clock) so it is always current and
nobody can store or edit a priority value.

    priority = 0.40 x deadline + 0.30 x business impact + 0.20 x waiting time + 0.10 x urgency    (clamped 0-100)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core.catalog import purpose_label

WEIGHTS = {"deadline": 0.40, "impact": 0.30, "waiting": 0.20, "urgency": 0.10}
IMPACT_SCORE = {"LOW": 10, "MEDIUM": 40, "HIGH": 70, "CRITICAL": 100}
IMPACT_HELP = {
    "LOW": "Nice to have. Work can continue without it.",
    "MEDIUM": "Normal work. A short delay is acceptable.",
    "HIGH": "Important work for a team or customer is blocked.",
    "CRITICAL": "Business-critical: an outage, a legal or a customer deadline depends on it.",
}
# Urgency comes from the purpose, not from the requester, so it cannot be inflated by typing "urgent".
URGENT_PURPOSES = {"INCIDENT_RESPONSE": 100, "FRAUD_INVESTIGATION": 70, "SECURITY_REVIEW": 50, "COMPLIANCE_AUDIT": 40}
APPROACHING_HOURS = 24


def level(score: int) -> str:
    if score >= 75:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def waiting_points(waited: timedelta) -> int:
    h = waited.total_seconds() / 3600
    if h < 4:
        return 0
    if h < 24:
        return 20
    if h < 72:
        return 40
    if h <= 168:
        return 70
    return 100


def deadline_points(left: timedelta | None) -> int:
    if left is None:
        return 0
    h = left.total_seconds() / 3600
    if h <= 0:
        return 60   # overdue: the strongest deadline signal
    if h <= 6:
        return 50
    if h <= 24:
        return 40
    if h <= 72:
        return 25
    if h <= 168:
        return 10
    return 0


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _span(td: timedelta) -> str:
    s = abs(td.total_seconds())
    if s < 3600:
        return f"{int(s // 60)} min"
    if s < 86400:
        return f"{s / 3600:.0f} h"
    return f"{s / 86400:.1f} days"


@dataclass
class Priority:
    score: int
    level: str
    overdue: bool
    approaching: bool
    components: dict
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"score": self.score, "level": self.level, "overdue": self.overdue, "approaching": self.approaching,
                "components": self.components, "reasons": self.reasons}


def compute(*, created_at: datetime, deadline_at: datetime | None, business_impact: str | None, purpose: str,
            now: datetime | None = None) -> Priority:
    now = _aware(now) or datetime.now(timezone.utc)
    created_at, deadline_at = _aware(created_at), _aware(deadline_at)
    impact = (business_impact or "MEDIUM").upper()
    left = (deadline_at - now) if deadline_at else None
    waited = max(timedelta(0), now - created_at)
    c = {
        "deadline": deadline_points(left),
        "impact": IMPACT_SCORE.get(impact, IMPACT_SCORE["MEDIUM"]),
        "waiting": waiting_points(waited),
        "urgency": URGENT_PURPOSES.get(purpose, 0),
    }
    raw = sum(WEIGHTS[k] * v for k, v in c.items())
    score = int(max(0, min(100, round(raw))))
    overdue = left is not None and left.total_seconds() <= 0
    approaching = left is not None and 0 < left.total_seconds() <= APPROACHING_HOURS * 3600
    reasons = []
    if left is None:
        reasons.append("No deadline given (+0).")
    elif overdue:
        reasons.append(f"Deadline passed {_span(left)} ago (+{round(WEIGHTS['deadline'] * c['deadline'])}).")
    else:
        reasons.append(f"Deadline in {_span(left)} (+{round(WEIGHTS['deadline'] * c['deadline'])}).")
    reasons.append(f"Business impact {impact.title()} (+{round(WEIGHTS['impact'] * c['impact'])}).")
    reasons.append(f"Waiting {_span(waited)} (+{round(WEIGHTS['waiting'] * c['waiting'])}).")
    if c["urgency"]:
        reasons.append(f"{purpose_label(purpose)} is an urgent purpose (+{round(WEIGHTS['urgency'] * c['urgency'])}).")
    return Priority(score, level(score), overdue, approaching, c, reasons)


def for_request(req, now: datetime | None = None) -> Priority:
    return compute(created_at=req.created_at, deadline_at=req.deadline_at, business_impact=req.business_impact,
                   purpose=req.purpose, now=now)
