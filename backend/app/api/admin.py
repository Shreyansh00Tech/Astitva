"""Dashboard, audit & compliance, alerts, policies, notifications, search, users and settings."""
from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import ACCESS_COOKIE, CurrentUser, get_current_user, require
from app.api.serializers import resource_brief, user_brief
from app.core.config import get_settings
from app.core.db import SessionLocal, get_db
from app.core.catalog import SENSITIVITY_RANK
from app.core.rbac import ALL_ROLES, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.models import (
    AccessRequest,
    AiAgent,
    AuditEvent,
    LoginAttempt,
    Notification,
    Policy,
    Resource,
    Role,
    SecurityAlert,
    User,
    utcnow,
)
from app.services import analytics, audit

router = APIRouter(prefix="/api", tags=["platform"])


@router.get("/dashboard")
def dashboard(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if not cu.has("dashboard:read"):
        # Requesters get a personal overview rather than org-wide security metrics.
        from app.models import AccessGrant

        mine = db.execute(select(AccessRequest).where(AccessRequest.requester_id == cu.id)).scalars().all()
        grants = db.execute(select(AccessGrant).where(AccessGrant.user_id == cu.id, AccessGrant.status == "ACTIVE")).scalars().all()
        return {"personal": True, "metrics": {
            "open_requests": sum(1 for r in mine if r.status in ("PENDING", "CHANGES_REQUESTED")),
            "approved_requests": sum(1 for r in mine if r.status == "APPROVED"),
            "rejected_requests": sum(1 for r in mine if r.status == "REJECTED"),
            "active_grants": len(grants),
            "expiring_soon": sum(1 for g in grants if g.expires_at and (g.expires_at - utcnow()).total_seconds() < 86400)},
            "work": analytics.work_stats(db, cu.id), "charts": analytics.employee_charts(db, cu.id)}
    return {"personal": False, **analytics.dashboard(db)}


# ------------------------------------------------------------------ audit
def _audit_query(q: str | None, actor_id: str | None, action: str | None, resource_id: str | None,
                 date_from: datetime | None, date_to: datetime | None):
    stmt = select(AuditEvent)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(AuditEvent.actor_name).like(like), func.lower(AuditEvent.action).like(like),
                              func.lower(AuditEvent.target_id).like(like), func.lower(AuditEvent.reason).like(like)))
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if resource_id:
        stmt = stmt.where(AuditEvent.resource_id == resource_id)
    if date_from:
        stmt = stmt.where(AuditEvent.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.occurred_at <= date_to)
    return stmt


def _audit_out(e: AuditEvent, res: dict) -> dict:
    return {"seq": e.seq, "event_id": e.event_id, "occurred_at": e.occurred_at, "actor_type": e.actor_type,
            "actor_id": e.actor_id, "actor_name": e.actor_name, "actor_role": e.actor_role, "action": e.action,
            "resource": res.get(e.resource_id), "resource_id": e.resource_id, "target_type": e.target_type,
            "target_id": e.target_id, "request_id": e.request_id, "previous_state": e.previous_state,
            "new_state": e.new_state, "reason": e.reason, "ip": e.ip, "user_agent": e.user_agent,
            "prev_hash": e.prev_hash, "hash": e.hash}


@router.get("/audit/events")
def audit_events(q: str | None = None, actor_id: str | None = None, action: str | None = None,
                 resource_id: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                 cu: CurrentUser = Depends(require("audit:read")), db: Session = Depends(get_db)):
    stmt = _audit_query(q, actor_id, action, resource_id, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(AuditEvent.seq.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    res = dict(db.execute(select(Resource.id, Resource.name)).all())
    actions = db.execute(select(AuditEvent.action).distinct().order_by(AuditEvent.action)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "events": [_audit_out(e, res) for e in rows],
            "actions": actions}


@router.get("/audit/verify")
def audit_verify(cu: CurrentUser = Depends(require("audit:verify")), db: Session = Depends(get_db)):
    result = audit.verify_chain(db)
    result["verified_at"] = utcnow()
    result["note"] = ("SHA-256 hash chaining makes unauthorized modification, deletion or reordering of audit "
                      "records detectable. It does not make the database itself immutable.")
    audit.record(db, cu.actor, "AUDIT_CHAIN_VERIFIED", target_type="AUDIT",
                 new_state={"valid": result["valid"], "checked": result["checked"],
                            "first_invalid_seq": result.get("first_invalid_seq")})
    db.commit()
    return result


@router.get("/audit/export.csv")
def audit_export(q: str | None = None, actor_id: str | None = None, action: str | None = None,
                 resource_id: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                 cu: CurrentUser = Depends(require("audit:export")), db: Session = Depends(get_db)):
    stmt = _audit_query(q, actor_id, action, resource_id, date_from, date_to).order_by(AuditEvent.seq)
    res = dict(db.execute(select(Resource.id, Resource.name)).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["seq", "occurred_at", "actor_type", "actor_name", "actor_role", "action", "resource", "target_type",
            "target_id", "request_id", "reason", "ip", "previous_state", "new_state", "prev_hash", "hash"]
    w.writerow(cols)
    for e in db.execute(stmt.limit(50000)).scalars():
        def safe(v):  # neutralise spreadsheet formula injection
            s = "" if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
            return "'" + s if s[:1] in ("=", "+", "-", "@") else s
        w.writerow([safe(x) for x in (e.seq, e.occurred_at.isoformat(), e.actor_type, e.actor_name, e.actor_role, e.action,
                                      res.get(e.resource_id), e.target_type, e.target_id, e.request_id, e.reason, e.ip,
                                      e.previous_state, e.new_state, e.prev_hash, e.hash)])
    audit.record(db, cu.actor, "AUDIT_EXPORTED", target_type="AUDIT", new_state={"filters": {"q": q, "action": action}})
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=astitva-audit-{utcnow():%Y%m%d-%H%M}.csv"})


# ------------------------------------------------------------------ alerts
@router.get("/alerts")
def alerts(status: str | None = None, severity: str | None = None, cu: CurrentUser = Depends(require("alerts:read")),
           db: Session = Depends(get_db)):
    q = select(SecurityAlert).order_by(SecurityAlert.created_at.desc())
    if status:
        q = q.where(SecurityAlert.status == status)
    if severity:
        q = q.where(SecurityAlert.severity == severity)
    rows = db.execute(q.limit(300)).scalars().all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id} or [""]))).scalars()}
    agents = dict(db.execute(select(AiAgent.id, AiAgent.name)).all())
    res = {r.id: r for r in db.execute(select(Resource)).scalars()}
    return [{"id": a.id, "severity": a.severity, "category": a.category, "title": a.title, "description": a.description,
             "user": user_brief(users.get(a.user_id)), "agent": agents.get(a.agent_id),
             "resource": resource_brief(res.get(a.resource_id)), "status": a.status, "resolution": a.resolution,
             "details": a.details,
             "created_at": a.created_at, "resolved_at": a.resolved_at} for a in rows]


class AlertStatusIn(BaseModel):
    status: str = Field(pattern="^(ACKNOWLEDGED|RESOLVED)$")
    resolution: str | None = Field(default=None, pattern="^(CONFIRMED|FALSE_POSITIVE)$")
    note: str | None = None


@router.post("/alerts/{alert_id}/status")
def alert_status(alert_id: str, body: AlertStatusIn, cu: CurrentUser = Depends(require("alerts:manage")),
                 db: Session = Depends(get_db)):
    a = db.get(SecurityAlert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    prev = a.status
    if body.status == "RESOLVED" and not body.resolution:
        raise HTTPException(422, "Say whether the alert was a confirmed violation or a false positive.")
    a.status = body.status
    if body.status == "RESOLVED":
        a.resolved_at, a.resolved_by_id, a.resolution = utcnow(), cu.id, body.resolution
    audit.record(db, cu.actor, "ALERT_STATUS_CHANGED", target_type="ALERT", target_id=a.id,
                 previous_state={"status": prev}, new_state={"status": a.status, "resolution": a.resolution},
                 reason=body.note)
    db.commit()
    return {"id": a.id, "status": a.status, "resolution": a.resolution}


# ------------------------------------------------------------------ policies
class PolicyIn(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    policy_type: str = Field(pattern="^(SOD|ABAC|GLOBAL)$")
    description: str | None = None
    resource_id: str | None = None
    rules: dict
    enabled: bool = True


SOD_KINDS = {"ROLE_CONFLICT", "STAGE_CONFLICT", "DEPARTMENT_CONFLICT", "RESOURCE_SENSITIVITY_DUAL_CONTROL"}


def _validate_policy(body: PolicyIn) -> None:
    if body.policy_type == "GLOBAL" and ("auto_approve_max_score" in body.rules or "manager_only_max_score" in body.rules):
        try:
            auto, mgr = int(body.rules["auto_approve_max_score"]), int(body.rules["manager_only_max_score"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "Routing needs whole-number auto_approve_max_score and manager_only_max_score.")
        if not (-1 <= auto <= mgr <= 100):
            raise HTTPException(422, "Thresholds must satisfy -1 <= auto-approve <= manager-only <= 100.")
        body.rules["auto_approve_max_score"], body.rules["manager_only_max_score"] = auto, mgr
        from app.services.workflow import ALWAYS_HUMAN_SENSITIVITIES, AUTO_SAFE_PERMISSIONS

        sens = set(body.rules.get("auto_approve_excluded_sensitivities") or []) | ALWAYS_HUMAN_SENSITIVITIES
        if not sens <= set(SENSITIVITY_RANK):
            raise HTTPException(422, "Unknown sensitivity in auto_approve_excluded_sensitivities.")
        perms = set(body.rules.get("auto_approve_allowed_permissions", sorted(AUTO_SAFE_PERMISSIONS)))
        if not perms <= AUTO_SAFE_PERMISSIONS:
            raise HTTPException(422, "Only READ and EXECUTE may ever be auto-approved.")
        body.rules["auto_approve_excluded_sensitivities"] = sorted(sens, key=SENSITIVITY_RANK.get)
        body.rules["auto_approve_allowed_permissions"] = sorted(perms)
        body.rules["anomaly_requires_security_review"] = True
    if body.policy_type == "SOD":
        kind = body.rules.get("kind")
        if kind not in SOD_KINDS:
            raise HTTPException(422, f"SOD rules.kind must be one of {sorted(SOD_KINDS)}")
        if kind == "ROLE_CONFLICT" and not set(body.rules.get("roles", [])) <= set(ALL_ROLES):
            raise HTTPException(422, "Unknown role in rules.roles")


@router.get("/policies")
def list_policies(cu: CurrentUser = Depends(require("policies:read")), db: Session = Depends(get_db)):
    res = {r.id: r for r in db.execute(select(Resource)).scalars()}
    rows = db.execute(select(Policy).order_by(Policy.policy_type, Policy.name)).scalars().all()
    return {
        "policies": [{"id": p.id, "name": p.name, "policy_type": p.policy_type, "description": p.description,
                      "resource": resource_brief(res.get(p.resource_id)), "rules": p.rules, "enabled": p.enabled,
                      "updated_at": p.updated_at} for p in rows],
        "builtin_sod_rules": [
            {"code": "SELF_APPROVAL", "description": "Requesters can never approve their own request."},
            {"code": "STAGE_AUTHORITY", "description": "Manager stage = the employee's reporting manager; security stage = the Security Manager."},
            {"code": "REPORTING_CONFLICT", "description": "A subordinate cannot approve their manager's request."},
            {"code": "INDEPENDENT_REVIEWERS", "description": "One person may approve only one stage of a request."},
            {"code": "MANAGER_DUAL_ROLE", "description": "The requester's manager cannot also give the security approval."},
        ],
        "resources": [{"id": r.id, "code": r.code, "name": r.name, "max_duration_hours": r.max_duration_hours,
                       "allowed_departments": r.allowed_departments, "allowed_purposes": r.allowed_purposes,
                       "breakglass_allowed": r.breakglass_allowed, "requires_risk_review": r.requires_risk_review,
                       "sensitivity": r.sensitivity} for r in res.values()],
        "can_manage": cu.has("policies:manage"),
    }


@router.post("/policies", status_code=201)
def create_policy(body: PolicyIn, cu: CurrentUser = Depends(require("policies:manage")), db: Session = Depends(get_db)):
    _validate_policy(body)
    p = Policy(**body.model_dump(), created_by_id=cu.id)
    db.add(p)
    db.flush()
    audit.record(db, cu.actor, "POLICY_CREATED", target_type="POLICY", target_id=p.id, new_state=body.model_dump())
    db.commit()
    return {"id": p.id}


@router.put("/policies/{policy_id}")
def update_policy(policy_id: str, body: PolicyIn, cu: CurrentUser = Depends(require("policies:manage")),
                  db: Session = Depends(get_db)):
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    _validate_policy(body)
    prev = {"name": p.name, "rules": p.rules, "enabled": p.enabled}
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    audit.record(db, cu.actor, "POLICY_UPDATED", target_type="POLICY", target_id=p.id, previous_state=prev,
                 new_state=body.model_dump())
    db.commit()
    return {"id": p.id}


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: str, cu: CurrentUser = Depends(require("policies:manage")), db: Session = Depends(get_db)):
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    audit.record(db, cu.actor, "POLICY_DELETED", target_type="POLICY", target_id=p.id,
                 previous_state={"name": p.name, "rules": p.rules})
    db.delete(p)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ notifications
@router.get("/notifications")
def notifications(unread_only: bool = False, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == cu.id).order_by(Notification.created_at.desc())
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.limit(100)).scalars().all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == cu.id,
                                                                           Notification.read_at.is_(None)))
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
                                         "severity": n.severity, "read": n.read_at is not None, "created_at": n.created_at}
                                        for n in rows]}


@router.post("/notifications/{nid}/read")
def mark_read(nid: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != cu.id:
        raise HTTPException(404, "Not found")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/unread")
def mark_unread(nid: str, cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != cu.id:
        raise HTTPException(404, "Not found")
    n.read_at = None
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(cu: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    for n in db.execute(select(Notification).where(Notification.user_id == cu.id, Notification.read_at.is_(None))).scalars():
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


@router.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket):
    """Live notification push. Authenticated with the HttpOnly access cookie; relays Redis pub/sub."""
    from app.security import jwt_tokens
    from app.services.notify import CHANNEL

    token = ws.cookies.get(ACCESS_COOKIE)
    try:
        claims = jwt_tokens.decode(token or "", "access")
    except Exception:
        await ws.close(code=4401)
        return
    with SessionLocal() as db:
        from app.models import UserSession

        sess = db.get(UserSession, claims.get("sid"))
        if not sess or sess.revoked_at:
            await ws.close(code=4401)
            return
    user_id = claims["sub"]
    await ws.accept()
    import redis.asyncio as aioredis

    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=20)
            if msg and msg.get("type") == "message":
                data = json.loads(msg["data"])
                if data.get("user_id") == user_id:
                    await ws.send_json({"type": "notification", **data})
            else:
                await ws.send_json({"type": "ping"})
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await r.aclose()


# ------------------------------------------------------------------ search
@router.get("/search")
def search(q: str = Query(min_length=2, max_length=80), cu: CurrentUser = Depends(get_current_user),
           db: Session = Depends(get_db)):
    like = f"%{q.lower()}%"
    out: dict = {"employees": [], "resources": [], "requests": [], "pages": []}
    if cu.has("employees:read_all") or cu.has("employees:read_team"):
        from app.api.governance import _visible_user_ids

        ids = _visible_user_ids(db, cu)
        stmt = select(User).where(or_(func.lower(User.full_name).like(like), func.lower(User.employee_id).like(like),
                                      func.lower(User.email).like(like))).limit(6)
        if ids is not None:
            stmt = stmt.where(User.id.in_(ids or [""]))
        out["employees"] = [user_brief(u) for u in db.execute(stmt).scalars()]
    out["resources"] = [resource_brief(r) for r in db.execute(select(Resource).where(
        or_(func.lower(Resource.name).like(like), func.lower(Resource.code).like(like))).limit(6)).scalars()]
    rq = select(AccessRequest).where(func.lower(AccessRequest.ref).like(like)).limit(6)
    if not cu.has("requests:read_all"):
        rq = rq.where(AccessRequest.requester_id == cu.id)
    out["requests"] = [{"id": r.id, "ref": r.ref, "resource": r.resource.name, "status": r.status}
                       for r in db.execute(rq).scalars()]
    return out


# ------------------------------------------------------------------ users / roles (security admin)
@router.get("/admin/users")
def admin_users(cu: CurrentUser = Depends(require("users:manage")), db: Session = Depends(get_db)):
    rows = db.execute(select(User).order_by(User.full_name)).scalars().all()
    return [{**user_brief(u), "mfa_enabled": u.mfa_enabled, "email_verified": u.email_verified,
             "locked_until": u.locked_until, "manager_id": u.manager_id} for u in rows]


class RolesIn(BaseModel):
    roles: list[str] = Field(min_length=1)


@router.put("/admin/users/{user_id}/roles")
def set_roles(user_id: str, body: RolesIn, cu: CurrentUser = Depends(require("users:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if any(r not in ALL_ROLES for r in body.roles):
        raise HTTPException(422, "Unknown role")
    if u.id == cu.id and "SECURITY_ADMIN" not in body.roles:
        raise HTTPException(409, "You cannot remove your own Security Admin role.")
    prev = u.role_names
    u.roles = list(db.execute(select(Role).where(Role.name.in_(set(body.roles) | {"REQUESTER"}))).scalars())
    from app.services.auth import revoke_all_sessions

    revoke_all_sessions(db, u.id, "ROLES_CHANGED")  # force re-authentication with new privileges
    audit.record(db, cu.actor, "USER_ROLES_CHANGED", target_type="USER", target_id=u.id, previous_state={"roles": prev},
                 new_state={"roles": u.role_names})
    db.commit()
    return {"id": u.id, "roles": u.role_names}


@router.get("/admin/login-attempts")
def login_attempts(cu: CurrentUser = Depends(require("users:manage")), db: Session = Depends(get_db)):
    rows = db.execute(select(LoginAttempt).order_by(LoginAttempt.created_at.desc()).limit(200)).scalars().all()
    return [{"email": r.email, "ip": r.ip, "success": r.success, "stage": r.stage, "reason": r.reason,
             "at": r.created_at} for r in rows]


@router.get("/settings/security")
def security_settings(cu: CurrentUser = Depends(get_current_user)):
    s = get_settings()
    return {
        "app_env": s.app_env,
        "auth": {"password_hashing": "Argon2id (t=3, m=64MiB, p=2)", "access_token_ttl_seconds": s.access_token_ttl_seconds,
                 "refresh_token_ttl_seconds": s.refresh_token_ttl_seconds, "refresh_rotation": True,
                 "refresh_reuse_detection": True, "mfa_required": True, "mfa_methods": ["TOTP", "EMAIL", "BACKUP_CODE", "SMS (adapter)"],
                 "cookies": {"httponly": True, "secure": s.cookie_secure, "samesite": s.cookie_samesite},
                 "csrf": "Double-submit cookie (X-CSRF-Token)"},
        "brute_force": {"max_failures": s.login_max_failures, "window_seconds": s.login_failure_window_seconds,
                        "lockout_base_seconds": s.lockout_base_seconds, "lockout_max_seconds": s.lockout_max_seconds,
                        "ip_bucket": {"capacity": s.ip_bucket_capacity, "refill_per_minute": round(s.ip_bucket_refill_per_sec * 60, 2)},
                        "account_bucket": {"capacity": s.account_bucket_capacity,
                                           "refill_per_minute": round(s.account_bucket_refill_per_sec * 60, 2)},
                        "captcha": "Integration-ready (CaptchaVerifier); required after 3 failures when configured"},
        "governance": {"recertification_interval_days": s.recertification_interval_days,
                       "breakglass_default_minutes": s.breakglass_default_minutes,
                       "breakglass_max_minutes": s.breakglass_max_minutes},
        "ai": {"provider": s.llm_provider, "model": s.llm_model if s.llm_provider != "none" else None,
               "note": "AI explains and recommends only. Authorization is deterministic policy + human approval."},
        "roles": [{"name": r, "description": ROLE_DESCRIPTIONS[r], "permissions": sorted(ROLE_PERMISSIONS[r])} for r in ALL_ROLES],
    }
