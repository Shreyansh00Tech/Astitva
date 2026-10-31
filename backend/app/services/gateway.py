"""Continuous-authorization enforcement for protected (simulated) resources.

Every human call must present a purpose-bound token; every agent call must present agent
credentials. Checks are evaluated server-side on every request; nothing relies on the UI.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.catalog import purpose_label
from app.core.context import Actor
from app.models import (
    AccessGrant,
    AccessToken,
    AgentPermission,
    AiAgent,
    EmergencySession,
    Resource,
    ResourceAccessEvent,
    User,
    utcnow,
)
from app.security import crypto
from app.services import audit
from app.services.grants import revoke_grant
from app.services.notify import notify, raise_alert
from app.services.workflow import check_abac


@dataclass
class Decision:
    allowed: bool
    reason: str
    code: str
    event: ResourceAccessEvent | None = None
    data: dict | None = None
    token_hint: str | None = None


def _deny_alert_threshold(db: Session, user_id: str | None, agent_id: str | None) -> int:
    since = utcnow() - timedelta(minutes=15)
    q = select(func.count()).select_from(ResourceAccessEvent).where(ResourceAccessEvent.outcome == "DENIED",
                                                                     ResourceAccessEvent.occurred_at >= since)
    q = q.where(ResourceAccessEvent.user_id == user_id) if user_id else q.where(ResourceAccessEvent.agent_id == agent_id)
    return db.scalar(q) or 0


def simulated_payload(res: Resource, action: str, purpose: str) -> dict:
    """Mock data only - ASTITVA never connects to real systems."""
    rnd = random.Random(f"{res.code}:{action}")
    if action == "READ":
        if res.resource_type == "AI_MODEL":
            return {"model": res.name, "version": f"v{rnd.randint(2, 6)}.{rnd.randint(0, 9)}",
                    "metrics": {"auc": round(rnd.uniform(0.82, 0.95), 3), "precision": round(rnd.uniform(0.7, 0.9), 3),
                                "recall": round(rnd.uniform(0.65, 0.9), 3)}, "simulated": True}
        rows = [{"id": f"SIM-{rnd.randint(10000, 99999)}", "value": round(rnd.uniform(10, 5000), 2),
                 "category": rnd.choice(["A", "B", "C"])} for _ in range(5)]
        return {"resource": res.name, "rows": rows, "simulated": True}
    if action == "EXECUTE":
        return {"resource": res.name, "prediction": round(rnd.random(), 4), "latency_ms": rnd.randint(20, 90), "simulated": True}
    return {"resource": res.name, "result": f"Simulated {action} accepted for {purpose_label(purpose)} (no real system touched)",
            "simulated": True}


def enforce_user_access(db: Session, actor: Actor, resource_id: str, raw_token: str | None, action: str,
                        purpose: str) -> Decision:
    user: User = actor.user
    res = db.get(Resource, resource_id) or db.execute(select(Resource).where(Resource.code == resource_id)).scalar_one_or_none()
    now = utcnow()
    tok: AccessToken | None = None
    grant: AccessGrant | None = None

    def decide(allowed: bool, code: str, reason: str) -> Decision:
        es_id = None
        if grant is not None and grant.is_emergency:
            es = db.execute(select(EmergencySession).where(EmergencySession.grant_id == grant.id)).scalar_one_or_none()
            es_id = es.id if es else None
        ev = ResourceAccessEvent(user_id=user.id, resource_id=res.id if res else None,
                                 grant_id=grant.id if grant else None, emergency_session_id=es_id, action=action,
                                 purpose=purpose, outcome="ALLOWED" if allowed else "DENIED", reason=reason, ip=actor.ip)
        db.add(ev)
        audit.record(db, actor, "RESOURCE_ACCESS_ALLOWED" if allowed else "RESOURCE_ACCESS_DENIED",
                     resource_id=res.id if res else None, target_type="RESOURCE", target_id=res.code if res else resource_id,
                     request_id=tok.request_id if tok else None, reason=reason,
                     new_state={"action": action, "purpose": purpose, "code": code,
                                "token": tok.token_hint if tok else None, "breakglass": bool(es_id)})
        if allowed:
            grant.last_used_at = now
        else:
            if code in ("TOKEN_IDENTITY_MISMATCH",):
                raise_alert(db, "HIGH", "TOKEN_MISUSE", f"Token presented by wrong identity ({user.full_name})",
                            f"{tok.token_hint} belongs to another employee; presented by {user.full_name} for "
                            f"{res.name if res else resource_id}.", user_id=user.id, resource_id=res.id if res else None)
            elif _deny_alert_threshold(db, user.id, None) == 3:
                raise_alert(db, "MEDIUM", "UNAUTHORIZED_ACCESS", f"Repeated denied access by {user.full_name}",
                            f"Multiple denied resource calls within 15 minutes (latest: {reason}).", user_id=user.id,
                            resource_id=res.id if res else None)
        db.flush()
        return Decision(allowed, reason, code, ev, simulated_payload(res, action, purpose) if allowed else None,
                        tok.token_hint if tok else None)

    if res is None:
        return Decision(False, "Unknown resource.", "UNKNOWN_RESOURCE")
    if not raw_token:
        return decide(False, "NO_TOKEN", "No purpose-bound access token presented.")
    tok = db.execute(select(AccessToken).where(AccessToken.token_hash == crypto.token_digest(raw_token.strip()))
                     ).scalar_one_or_none()
    if not tok:
        return decide(False, "INVALID_TOKEN", "Access token is not recognised.")
    grant = db.get(AccessGrant, tok.grant_id)
    if tok.revoked_at is not None or grant.status == "REVOKED":
        return decide(False, "TOKEN_REVOKED", "Access token has been revoked.")
    if tok.expires_at <= now or (grant.expires_at and grant.expires_at <= now) or grant.status == "EXPIRED":
        if grant.status == "ACTIVE":
            from app.core.context import SYSTEM

            revoke_grant(db, SYSTEM, grant, "Grant reached its expiry time", status="EXPIRED")
        return decide(False, "TOKEN_EXPIRED", "Access token has expired.")
    if tok.user_id != user.id:
        return decide(False, "TOKEN_IDENTITY_MISMATCH", "Token is bound to a different employee.")
    if tok.resource_id != res.id:
        return decide(False, "TOKEN_RESOURCE_MISMATCH", "Token is not valid for this resource.")
    if tok.purpose != purpose:
        return decide(False, "TOKEN_PURPOSE_MISMATCH",
                      f"Token was approved for {purpose_label(tok.purpose)}, not {purpose_label(purpose)}.")
    if action not in tok.permissions or action not in grant.permissions:
        return decide(False, "PERMISSION_NOT_GRANTED",
                      f"{action} is not among the approved permissions ({', '.join(tok.permissions)}).")
    denial = check_abac(user, res) if not grant.is_emergency else None
    if denial:
        return decide(False, "POLICY_DENIED", denial)
    return decide(True, "ALLOWED", f"Authorized: {action} for {purpose_label(purpose)}.")


# ---------------------------------------------------------------- AI agents
def authenticate_agent(db: Session, agent_id: str, key: str) -> AiAgent | None:
    agent = db.get(AiAgent, agent_id) or db.execute(select(AiAgent).where(AiAgent.code == agent_id)).scalar_one_or_none()
    if not agent or not key or agent.api_key_hash != crypto.token_digest(key):
        return None
    return agent


def enforce_agent_access(db: Session, agent: AiAgent, resource_ref: str, action: str, tool: str,
                         ip: str | None = None) -> Decision:
    res = db.get(Resource, resource_ref) or db.execute(select(Resource).where(Resource.code == resource_ref)).scalar_one_or_none()
    actor = Actor(actor_type="AGENT", name=agent.name, agent_id=agent.id, ip=ip)
    now = utcnow()

    def decide(allowed: bool, code: str, reason: str) -> Decision:
        ev = ResourceAccessEvent(agent_id=agent.id, resource_id=res.id if res else None, action=action, tool=tool,
                                 outcome="ALLOWED" if allowed else "DENIED", reason=reason, ip=ip)
        db.add(ev)
        audit.record(db, actor, "AGENT_ACCESS_ALLOWED" if allowed else "AGENT_ACCESS_DENIED",
                     resource_id=res.id if res else None, target_type="RESOURCE",
                     target_id=res.code if res else resource_ref, reason=reason,
                     new_state={"agent": agent.code, "action": action, "tool": tool, "code": code})
        if not allowed:
            raise_alert(db, "HIGH" if res and res.sensitivity in ("RESTRICTED", "CRITICAL") else "MEDIUM",
                        "AGENT_UNAUTHORIZED", f"{agent.name} denied access to {res.name if res else resource_ref}",
                        reason, agent_id=agent.id, resource_id=res.id if res else None,
                        details={"action": action, "tool": tool, "code": code})
            notify(db, agent.owner_id, "SUSPICIOUS_ACTIVITY", f"{agent.name} was blocked", reason, "/ai-security",
                   "WARNING")
        db.flush()
        return Decision(allowed, reason, code, ev, simulated_payload(res, action, "AGENT") if allowed else None)

    if agent.status != "ACTIVE":
        return decide(False, "AGENT_SUSPENDED", "Agent identity is suspended.")
    if agent.expires_at and agent.expires_at <= now:
        return decide(False, "AGENT_EXPIRED", "Agent identity has expired.")
    if res is None:
        return decide(False, "UNKNOWN_RESOURCE", "Unknown resource.")
    if tool not in (agent.allowed_tools or []):
        return decide(False, "TOOL_NOT_ALLOWED", f"Agent is not authorized to use tool '{tool}'.")
    perm = db.execute(select(AgentPermission).where(AgentPermission.agent_id == agent.id,
                                                    AgentPermission.resource_id == res.id)).scalar_one_or_none()
    if not perm:
        return decide(False, "RESOURCE_NOT_ALLOWED", "Agent is not authorized to access this resource.")
    if perm.expires_at and perm.expires_at <= now:
        return decide(False, "PERMISSION_EXPIRED", "Agent's permission for this resource has expired.")
    if action not in perm.permissions:
        return decide(False, "PERMISSION_NOT_GRANTED",
                      f"Agent may only {', '.join(perm.permissions)} on this resource, not {action}.")
    return decide(True, "ALLOWED", f"Authorized agent {action} via {tool}.")
