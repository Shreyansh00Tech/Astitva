"""Permission drift detection: compare effective permissions with approved baselines."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.catalog import SENSITIVITY_RANK, risk_level, sort_perms
from app.core.context import Actor
from app.models import AccessGrant, DriftFinding, PermissionBaseline, Resource, ResourceAccessEvent, User, utcnow
from app.services import audit
from app.services.notify import notify, raise_alert

EXCESS_POINTS = {"READ": 5, "EXECUTE": 10, "WRITE": 18, "DELETE": 25, "ADMIN": 35}
SENS_MULT = {"PUBLIC": 0.6, "INTERNAL": 0.8, "CONFIDENTIAL": 1.0, "RESTRICTED": 1.15, "CRITICAL": 1.3}


def analyse_user_resource(db: Session, user: User, res: Resource, grants: list[AccessGrant],
                          baseline: PermissionBaseline | None) -> dict | None:
    now = utcnow()
    base = set(baseline.permissions) if baseline else set()
    # Approved, time-bound, request-backed grants are legitimate temporary elevation, not drift.
    standing = [g for g in grants if not (g.source in ("REQUEST", "EMERGENCY") and g.expires_at and g.expires_at > now)]
    current = set()
    for g in grants:
        current |= set(g.permissions)
    standing_perms = set()
    for g in standing:
        standing_perms |= set(g.permissions)
    excess = sort_perms(standing_perms - base)
    issues: list[str] = []
    score = 0.0
    for p in excess:
        score += EXCESS_POINTS.get(p, 10)
    if excess:
        issues.append(f"Permissions beyond approved baseline: {', '.join(excess)}")
    if any(p in ("ADMIN", "DELETE") for p in excess):
        issues.append("Privilege escalation: destructive/administrative rights accumulated")
    expired_active = [g for g in grants if g.expires_at and g.expires_at <= now]
    if expired_active:
        score += 30
        issues.append(f"{len(expired_active)} grant(s) past expiry still active")
    permanent = [g for g in standing if g.expires_at is None]
    if permanent and SENSITIVITY_RANK[res.sensitivity] >= 2 and (baseline is None or excess):
        score += 10
        issues.append("Standing (non-expiring) access to sensitive resource without a matching baseline")
    used = set(db.execute(select(ResourceAccessEvent.action).where(
        ResourceAccessEvent.user_id == user.id, ResourceAccessEvent.resource_id == res.id,
        ResourceAccessEvent.outcome == "ALLOWED", ResourceAccessEvent.occurred_at >= now - timedelta(days=30))
    ).scalars())
    old_enough = [g for g in standing if g.granted_at <= now - timedelta(days=14)]
    unused: list[str] = []
    if old_enough:
        perms_old = set()
        for g in old_enough:
            perms_old |= set(g.permissions)
        unused = sort_perms(perms_old - used)
        if unused:
            score += 6 * len(unused)
            issues.append(f"Unused for 30+ days: {', '.join(unused)}")
    if not issues:
        return None
    score = int(min(100, round(score * SENS_MULT[res.sensitivity])))
    if score < 10:
        return None  # below noise floor
    severity = risk_level(score)
    keep = sort_perms((base & current) or (set(used) & current) or ({"READ"} & current))
    remove = sort_perms(current - set(keep))
    rec = (f"Reduce to {', '.join(keep)}; revoke {', '.join(remove)}." if keep and remove
           else f"Revoke {', '.join(remove)}." if remove else "Schedule access review.")
    if expired_active:
        rec = "Expire the overdue grant(s) immediately. " + rec
    return {"baseline": sort_perms(base), "current": sort_perms(current), "excess": excess, "unused": unused,
            "issues": issues, "score": score, "severity": severity, "recommendation": rec}


def scan(db: Session, actor: Actor | None = None, user_ids: list[str] | None = None) -> dict:
    q = select(AccessGrant).where(AccessGrant.status == "ACTIVE")
    if user_ids:
        q = q.where(AccessGrant.user_id.in_(user_ids))
    grants = db.execute(q).scalars().all()
    by_pair: dict[tuple[str, str], list[AccessGrant]] = defaultdict(list)
    for g in grants:
        by_pair[(g.user_id, g.resource_id)].append(g)
    baselines = {(b.user_id, b.resource_id): b for b in db.execute(select(PermissionBaseline)).scalars()}
    open_findings = {(f.user_id, f.resource_id): f for f in db.execute(
        select(DriftFinding).where(DriftFinding.status.in_(["OPEN", "REVIEW_SCHEDULED"]))).scalars()}
    created = updated = resolved = 0
    seen = set()
    for (uid, rid), gs in by_pair.items():
        user, res = gs[0].user, gs[0].resource
        result = analyse_user_resource(db, user, res, gs, baselines.get((uid, rid)))
        if not result:
            continue
        seen.add((uid, rid))
        f = open_findings.get((uid, rid))
        if f:
            f.current_permissions, f.excess_permissions, f.unused_permissions = result["current"], result["excess"], result["unused"]
            f.issues, f.drift_score, f.severity, f.recommendation = result["issues"], result["score"], result["severity"], result["recommendation"]
            updated += 1
            continue
        f = DriftFinding(user_id=uid, resource_id=rid, baseline_permissions=result["baseline"],
                         current_permissions=result["current"], excess_permissions=result["excess"],
                         unused_permissions=result["unused"], issues=result["issues"], drift_score=result["score"],
                         severity=result["severity"], recommendation=result["recommendation"])
        db.add(f)
        created += 1
        if result["severity"] in ("HIGH", "CRITICAL"):
            raise_alert(db, result["severity"], "PERMISSION_DRIFT", f"Permission drift: {user.full_name} on {res.name}",
                        "; ".join(result["issues"]), user_id=uid, resource_id=rid, notify_admins=True)
        if user.manager_id:
            notify(db, user.manager_id, "PERMISSION_DRIFT", f"Permission drift identified: {user.full_name}",
                   f"{res.name}: {result['recommendation']}", "/drift", "WARNING")
    # Findings whose drift has disappeared are auto-resolved (permissions already reduced)
    for key, f in open_findings.items():
        if key not in seen and (not user_ids or key[0] in user_ids):
            f.status = "REMEDIATED"
            f.resolved_at = utcnow()
            resolved += 1
    if actor:
        audit.record(db, actor, "DRIFT_SCAN", target_type="SYSTEM",
                     new_state={"created": created, "updated": updated, "resolved": resolved})
    db.commit()
    return {"created": created, "updated": updated, "resolved": resolved}
