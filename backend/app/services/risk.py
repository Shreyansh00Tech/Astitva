"""AI-assisted risk assessment.

The deterministic rule engine produces the score and recommendations. An Isolation Forest
(scikit-learn) contributes an anomaly signal on organisation-wide access behaviour, and an
optional LLM may rewrite the explanation. Neither the model nor the LLM can grant access:
authorization is decided only by backend policy plus independent human approvals.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.catalog import (
    PERMISSION_POINTS,
    PURPOSES,
    SENSITIVITY_MAX_HOURS,
    SENSITIVITY_POINTS,
    SENSITIVITY_RANK,
    purpose_label,
    risk_level,
    sort_perms,
)
from app.core.config import get_settings
from app.core.risk_config import (
    ANOMALY,
    DENIALS_DAYS,
    GROUP_CAPS,
    HISTORY_DAYS,
    VELOCITY_BASELINE_WEEKS,
    VELOCITY_DAYS,
    VIOLATION_CATEGORIES,
    WEIGHTS,
)
from app.models import (
    AccessGrant,
    AccessRequest,
    Resource,
    ResourceAccessEvent,
    RiskAssessment,
    SecurityAlert,
    User,
    utcnow,
)

log = logging.getLogger("astitva.risk")


@dataclass
class AnomalyResult:
    """Outcome of the behaviour model. status is ANOMALOUS, NORMAL or UNAVAILABLE (never a made-up verdict)."""
    status: str
    score: float | None = None
    detail: str = ""
    population: int = 0


def _user_features(db: Session, since: datetime, until: datetime) -> dict[str, list[float]]:
    """Per-user behaviour vectors over [since, until): requests, distinct resources, avg sensitivity, denials,
    off-hours ratio. Only events strictly before `until` are used."""
    feats: dict[str, list[float]] = {}
    reqs = db.execute(
        select(AccessRequest.requester_id, AccessRequest.resource_id, Resource.sensitivity, AccessRequest.created_at)
        .join(Resource, Resource.id == AccessRequest.resource_id)
        .where(AccessRequest.created_at >= since, AccessRequest.created_at < until)
    ).all()
    agg: dict[str, dict] = {}
    for uid, rid, sens, ts in reqs:
        a = agg.setdefault(uid, {"n": 0, "res": set(), "sens": [], "off": 0})
        a["n"] += 1
        a["res"].add(rid)
        a["sens"].append(SENSITIVITY_RANK[sens])
        if ts.hour < 7 or ts.hour > 21:
            a["off"] += 1
    denials = dict(db.execute(
        select(ResourceAccessEvent.user_id, func.count()).where(ResourceAccessEvent.outcome == "DENIED",
                                                                ResourceAccessEvent.occurred_at >= since,
                                                                ResourceAccessEvent.occurred_at < until,
                                                                ResourceAccessEvent.user_id.is_not(None))
        .group_by(ResourceAccessEvent.user_id)).all())
    for uid in set(agg) | set(denials):
        a = agg.get(uid, {"n": 0, "res": set(), "sens": [0], "off": 0})
        n = a["n"]
        feats[uid] = [n, len(a["res"]), float(np.mean(a["sens"] or [0])), denials.get(uid, 0), a["off"] / n if n else 0]
    return feats


_MODEL_CACHE: dict[tuple, tuple] = {}


def _reference_model(db: Session, day_start: datetime):
    """Train (or reuse) the Isolation Forest for one UTC day. Training is separate from scoring and cached."""
    cfg = ANOMALY
    feats = _user_features(db, day_start - timedelta(days=cfg["WINDOW_DAYS"]), day_start)
    ids = sorted(feats)
    X = np.array([feats[i] for i in ids], dtype=float) if ids else np.zeros((0, 5))
    key = (day_start.date().isoformat(), len(ids), hashlib.sha256(X.tobytes()).hexdigest()[:16])
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    model = None
    if len(ids) >= cfg["MIN_POPULATION"]:
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(n_estimators=cfg["N_ESTIMATORS"], contamination=cfg["CONTAMINATION"],
                                random_state=cfg["RANDOM_STATE"]).fit(X)
    if len(_MODEL_CACHE) > 32:
        _MODEL_CACHE.clear()
    _MODEL_CACHE[key] = (model, X, len(ids))
    return _MODEL_CACHE[key]


def anomaly_signal(db: Session, user_id: str, as_of: datetime | None = None) -> AnomalyResult:
    """Isolation Forest over org-wide behaviour. Returns UNAVAILABLE (with the reason) instead of guessing."""
    as_of = as_of or utcnow()
    day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        model, X, pop = _reference_model(db, day_start)
    except Exception as exc:  # the rule engine remains the reliable fallback
        log.warning("isolation forest unavailable: %s", exc)
        return AnomalyResult("UNAVAILABLE", detail=f"Behaviour model could not run ({type(exc).__name__}).")
    if model is None:
        return AnomalyResult("UNAVAILABLE", population=pop,
                             detail=f"Not enough data: {pop} people with activity in the last {ANOMALY['WINDOW_DAYS']} "
                                    f"days, the model needs at least {ANOMALY['MIN_POPULATION']}. No points added.")
    v = _user_features(db, as_of - timedelta(days=ANOMALY["WINDOW_DAYS"]), as_of).get(user_id)
    if v is None:
        return AnomalyResult("UNAVAILABLE", population=pop,
                             detail="No recent activity for this person, so there is nothing to compare. No points added.")
    x = np.array([v], dtype=float)
    score = float(-model.score_samples(x)[0])
    if model.predict(x)[0] != -1:
        return AnomalyResult("NORMAL", score, f"Behaviour is in line with {pop} peers.", pop)
    med = np.median(X, axis=0)
    parts = []
    if v[0] > med[0] * 2 and v[0] >= 4:
        parts.append(f"{int(v[0])} requests in 30 days (org median {med[0]:.0f})")
    if v[1] > med[1] * 2 and v[1] >= 3:
        parts.append(f"{int(v[1])} distinct resources")
    if v[3] > max(1, med[3] * 2):
        parts.append(f"{int(v[3])} denied access attempts")
    if v[4] > 0.4:
        parts.append(f"{v[4]:.0%} of requests outside working hours")
    return AnomalyResult("ANOMALOUS", score, "Access behaviour is an outlier versus peers: "
                         + (", ".join(parts) or "unusual combination of signals"), pop)


def assess(db: Session, req: AccessRequest, as_of: datetime | None = None) -> RiskAssessment:
    """Score a request. History is read only up to `as_of` (default: the moment the request was made)."""
    user: User = db.get(User, req.requester_id)
    res: Resource = db.get(Resource, req.resource_id)
    as_of = as_of or req.created_at or utcnow()
    W = WEIGHTS
    factors: list[dict] = []
    anomalies: list[str] = []

    def add(code: str, label: str, points: int, detail: str, group: str | None = None, available: bool = True):
        f = {"code": code, "label": label, "points": points, "detail": detail}
        if group:
            f["group"] = group
        if not available:
            f["available"] = False
        factors.append(f)

    add("SENSITIVITY", "Resource sensitivity", SENSITIVITY_POINTS[res.sensitivity],
        f"{res.name} is classified {res.sensitivity}.")

    perms = sort_perms(req.approved_permissions)
    top = max(PERMISSION_POINTS.get(p, 0) for p in perms)
    extra = max(0, len(perms) - 1) * W["EXTRA_PERMISSION"]
    if top + extra:
        add("PERMISSION_LEVEL", "Requested privilege level", top + extra, f"Requested {', '.join(perms)}.")

    needed = PURPOSES.get(req.purpose, (None, ["READ"]))[1]
    recommended = [p for p in perms if p in needed and p in res.available_permissions]
    if not recommended:
        recommended = ["READ"] if "READ" in res.available_permissions else perms[:1]
    excessive = [p for p in perms if p not in needed]
    if excessive:
        add("EXCESSIVE_PERMISSIONS", "Excessive permissions for purpose",
            min(W["EXCESSIVE_MAX"], W["EXCESSIVE_PER_PERMISSION"] * len(excessive)),
            f"{purpose_label(req.purpose)} normally needs only {', '.join(needed)}; also requested {', '.join(excessive)}.")
        anomalies.append(f"Excessive permissions: {', '.join(excessive)} not required for {purpose_label(req.purpose)}")

    if res.allowed_purposes and req.purpose not in res.allowed_purposes:
        add("PURPOSE_MISMATCH", "Purpose-resource mismatch", W["PURPOSE_MISMATCH"],
            f"{purpose_label(req.purpose)} is not an approved purpose for {res.name}.")
        anomalies.append(f"Purpose-resource mismatch: {purpose_label(req.purpose)} on {res.name}")

    dept_code = user.department.code if user.department else None
    if res.allowed_departments and dept_code not in res.allowed_departments:
        add("DEPARTMENT_SCOPE", "Department outside resource scope", W["DEPARTMENT_SCOPE"],
            f"{res.name} is scoped to {', '.join(res.allowed_departments)}; requester is in {dept_code or 'no department'}.")
    elif res.department and user.department_id != res.department_id:
        add("CROSS_DEPARTMENT", "Cross-department access", W["CROSS_DEPARTMENT"],
            f"Resource belongs to {res.department.name}; requester is in {user.department.name if user.department else 'no department'}.")

    cap = min(SENSITIVITY_MAX_HOURS[res.sensitivity], res.max_duration_hours)
    if req.approved_duration_hours > cap:
        pts = W["LONG_DURATION"] if req.approved_duration_hours <= cap * 3 else W["VERY_LONG_DURATION"]
        add("LONG_DURATION", "Unnecessarily long duration", pts,
            f"Requested {req.approved_duration_hours}h; policy-proportionate maximum is {cap}h.")
        anomalies.append(f"Duration {req.approved_duration_hours}h exceeds proportionate maximum {cap}h")
    suggested_hours = min(req.approved_duration_hours, cap)
    if excessive and SENSITIVITY_RANK[res.sensitivity] >= 2:
        suggested_hours = min(suggested_hours, 24)

    words = len((req.justification or "").split())
    if words < W["WEAK_JUSTIFICATION_WORDS"]:
        add("WEAK_JUSTIFICATION", "Weak business justification", W["WEAK_JUSTIFICATION"],
            f"Justification has only {words} words.")

    # ---- history (bounded at as_of). A rejected access request is never a violation and is not counted.
    hist_since = as_of - timedelta(days=HISTORY_DAYS)
    alert_q = select(func.count()).select_from(SecurityAlert).where(
        SecurityAlert.user_id == user.id, SecurityAlert.created_at >= hist_since, SecurityAlert.created_at < as_of,
        SecurityAlert.category.in_(VIOLATION_CATEGORIES))
    confirmed = db.scalar(alert_q.where(SecurityAlert.status == "RESOLVED",
                                        SecurityAlert.resolution == "CONFIRMED")) or 0
    unreviewed = db.scalar(alert_q.where(SecurityAlert.status != "RESOLVED")) or 0
    denials = db.scalar(select(func.count()).select_from(ResourceAccessEvent).where(
        ResourceAccessEvent.user_id == user.id, ResourceAccessEvent.outcome == "DENIED",
        ResourceAccessEvent.occurred_at >= as_of - timedelta(days=DENIALS_DAYS),
        ResourceAccessEvent.occurred_at < as_of)) or 0
    if confirmed:
        add("CONFIRMED_VIOLATIONS", "Confirmed policy violations", confirmed * W["CONFIRMED_VIOLATION_EACH"],
            f"{confirmed} violation(s) confirmed by the Security Manager in the last {HISTORY_DAYS} days.", "HISTORY")
    if unreviewed:
        add("UNREVIEWED_ALERTS", "Security alerts not reviewed yet",
            min(W["OPEN_ALERT_MAX"], unreviewed * W["OPEN_ALERT_EACH"]),
            f"{unreviewed} alert(s) still open. Not confirmed, so they count less than a violation.", "HISTORY")
    if denials >= W["REPEATED_DENIALS_MIN"]:
        pts = W["REPEATED_DENIALS_HIGH"] if denials >= W["REPEATED_DENIALS_HIGH_MIN"] else W["REPEATED_DENIALS"]
        add("REPEATED_DENIALS", "Repeated denied operations", pts,
            f"{denials} operations were blocked at the gateway in the last {DENIALS_DAYS} days. "
            "These are blocked actions, not confirmed violations.", "HISTORY")

    prior = db.scalar(select(func.count()).select_from(AccessGrant).where(
        AccessGrant.user_id == user.id, AccessGrant.resource_id == res.id, AccessGrant.source == "REQUEST",
        AccessGrant.granted_at < as_of)) or 0
    if prior:
        add("PRIOR_ACCESS", "Previously approved for this resource", W["PRIOR_ACCESS"], f"{prior} earlier approved grant(s).")
    else:
        add("FIRST_ACCESS", "First-time access to this resource", W["FIRST_ACCESS"], "No previous approved access.")

    if user.device_trust == "UNKNOWN":
        add("DEVICE_TRUST", "Unmanaged device (simulated)", W["DEVICE_UNKNOWN"], "Device posture is UNKNOWN.")
    elif user.device_trust == "UNTRUSTED":
        add("DEVICE_TRUST", "Untrusted device (simulated)", W["DEVICE_UNTRUSTED"], "Device failed posture checks.")
        anomalies.append("Request originates from an untrusted device")

    # ---- behaviour: velocity against the requester's own baseline (this request is excluded)
    other = select(func.count()).select_from(AccessRequest).where(
        AccessRequest.requester_id == user.id, AccessRequest.id != req.id, AccessRequest.created_at < as_of)
    recent = db.scalar(other.where(AccessRequest.created_at >= as_of - timedelta(days=VELOCITY_DAYS))) or 0
    base_start = as_of - timedelta(days=VELOCITY_DAYS + 7 * VELOCITY_BASELINE_WEEKS)
    base_total = db.scalar(other.where(AccessRequest.created_at >= base_start,
                                       AccessRequest.created_at < as_of - timedelta(days=VELOCITY_DAYS))) or 0
    baseline = base_total / VELOCITY_BASELINE_WEEKS
    if recent >= W["VELOCITY_MIN_REQUESTS"] and recent >= W["VELOCITY_BASELINE_FACTOR"] * baseline:
        add("REQUEST_VELOCITY", "High request velocity", W["VELOCITY"],
            f"{recent} other requests in the last {VELOCITY_DAYS} days; this person's usual pace is "
            f"{baseline:.1f} per week.", "BEHAVIOUR")
        anomalies.append(f"{recent} access requests in {VELOCITY_DAYS} days (usual {baseline:.1f}/week)")

    an = anomaly_signal(db, user.id, as_of)
    if an.status == "ANOMALOUS":
        add("BEHAVIOUR_ANOMALY", "Behavioural anomaly (Isolation Forest)", W["BEHAVIOUR_ANOMALY"], an.detail, "BEHAVIOUR")
        anomalies.append(an.detail)
    elif an.status == "UNAVAILABLE":
        add("BEHAVIOUR_MODEL", "Behaviour model (Isolation Forest)", 0, an.detail, available=False)

    # ---- group caps: related signals share one ceiling so the same behaviour is not counted twice
    for group, limit in GROUP_CAPS.items():
        members = [f for f in factors if f.get("group") == group and f["points"] > 0]
        over = sum(f["points"] for f in members) - limit
        for f in sorted(members, key=lambda f: f["points"]):
            if over <= 0:
                break
            cut = min(over, f["points"])
            f["points"] -= cut
            over -= cut
            f["detail"] += f" (capped: related {group.lower()} signals share a {limit}-point limit)"

    score = int(max(0, min(100, sum(f["points"] for f in factors))))
    level = risk_level(score)
    narrowed = set(recommended) != set(perms) or suggested_hours < req.approved_duration_hours
    if level == "LOW":
        action = "APPROVE"
    elif level == "MEDIUM":
        action = "APPROVE_WITH_NARROWED_SCOPE" if narrowed else "APPROVE_WITH_MONITORING"
    elif level == "HIGH":
        action = "NARROW_SCOPE" if narrowed else "ESCALATE_FOR_REVIEW"
    else:
        action = "REJECT_OR_ESCALATE"

    explanation = _template_explanation(user, res, req, score, level, factors, recommended, suggested_hours, action)
    engine = "rules-v2+isolation-forest" if an.status != "UNAVAILABLE" else "rules-v2"
    llm = _llm_explanation(user, res, req, score, level, factors, recommended, suggested_hours)
    if llm:
        explanation, engine = llm, engine + f"+llm:{get_settings().llm_provider}"

    ra = RiskAssessment(request_id=req.id, score=score, level=level, factors=factors, anomalies=anomalies,
                        recommended_permissions=sort_perms(recommended), recommended_duration_hours=suggested_hours,
                        recommended_action=action, explanation=explanation, engine=engine)
    db.add(ra)
    db.flush()
    return ra


def _template_explanation(user, res, req, score, level, factors, rec, hours, action) -> str:
    top = sorted([f for f in factors if f["points"] > 0], key=lambda f: -f["points"])[:3]
    drivers = "; ".join(f"{f['label'].lower()} (+{f['points']})" for f in top) or "no significant risk drivers"
    missing = [f["label"] for f in factors if f.get("available") is False]
    gaps = f" Not used (insufficient data): {', '.join(missing)}." if missing else ""
    return (f"{user.full_name} requested {', '.join(req.approved_permissions)} on {res.name} for "
            f"{purpose_label(req.purpose)} ({req.approved_duration_hours}h). Risk is {level} ({score}/100), driven by "
            f"{drivers}. Least-privilege recommendation: {', '.join(rec)} for {hours}h. "
            f"Suggested action: {action.replace('_', ' ').lower()}.{gaps} This is advisory; human approvers decide.")


def _llm_explanation(user, res, req, score, level, factors, rec, hours) -> str | None:
    """Optional: ask a configured LLM to phrase the explanation. Output is text only and never authorizes."""
    s = get_settings()
    if s.llm_provider == "none" or not s.llm_api_key:
        return None
    import httpx

    prompt = (
        "You are a security analyst. In 3 sentences, explain this access-request risk assessment to an approver. "
        "Do not change the score or recommendation and do not approve or deny.\n"
        f"Requester: {user.designation} in {user.department.name if user.department else 'n/a'}\n"
        f"Resource: {res.name} ({res.sensitivity})\nPermissions: {req.approved_permissions}\n"
        f"Purpose: {purpose_label(req.purpose)}\nJustification: {req.justification[:500]}\n"
        f"Score: {score} ({level})\nFactors: {[(f['label'], f['points']) for f in factors]}\n"
        f"Recommendation: {rec} for {hours}h"
    )
    try:
        if s.llm_provider == "anthropic":
            r = httpx.post(s.llm_base_url or "https://api.anthropic.com/v1/messages", timeout=8, headers={
                "x-api-key": s.llm_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": s.llm_model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", [])).strip() or None
        if s.llm_provider == "openai":
            r = httpx.post((s.llm_base_url or "https://api.openai.com/v1") + "/chat/completions", timeout=8,
                           headers={"Authorization": f"Bearer {s.llm_api_key}"},
                           json={"model": s.llm_model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 300})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as exc:
        log.warning("LLM explanation failed, using rule-based text: %s", exc)
    return None
