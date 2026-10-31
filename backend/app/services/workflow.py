"""Access request lifecycle: submit -> risk assessment -> staged independent approvals -> grant + token."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.catalog import PURPOSES, purpose_label, sort_perms
from app.core.context import Actor
from app.core.rbac import RISK_REVIEWER, SECURITY_ADMIN
from app.models import AccessGrant, AccessRequest, ApprovalRecord, Resource, User, utcnow
from app.services import audit, priority, risk, sod
from app.services.grants import create_grant
from app.services.notify import notify, notify_role, raise_alert


class WorkflowError(Exception):
    def __init__(self, message: str, status: int = 400, rule: str | None = None):
        super().__init__(message)
        self.message, self.status, self.rule = message, status, rule


def _next_ref(db: Session) -> str:
    n = (db.scalar(select(func.count()).select_from(AccessRequest)) or 0) + 1
    year = utcnow().year
    while True:
        ref = f"REQ-{year}-{n:05d}"
        if not db.scalar(select(AccessRequest.id).where(AccessRequest.ref == ref)):
            return ref
        n += 1


ROUTING_POLICY_NAME = "Risk-based approval routing"
# Hard guardrails. An admin can tighten routing but can never make these auto-approvable.
ALWAYS_HUMAN_SENSITIVITIES = {"CONFIDENTIAL", "RESTRICTED", "CRITICAL"}
AUTO_SAFE_PERMISSIONS = {"READ", "EXECUTE"}
DEFAULT_ROUTING = {
    "auto_approve_max_score": 30,
    "manager_only_max_score": 60,
    # Guardrails: these are never auto-approved, whatever the score. A human always decides.
    "auto_approve_excluded_sensitivities": ["CONFIDENTIAL", "RESTRICTED", "CRITICAL"],
    "auto_approve_allowed_permissions": ["READ", "EXECUTE"],
    "anomaly_requires_security_review": True,
}


def routing_rules(db: Session | None) -> dict | None:
    """Admin-configurable thresholds (a GLOBAL policy). None means routing is off: every request needs both approvals."""
    if db is None:
        return None
    from app.models import Policy

    for pol in db.execute(select(Policy).where(Policy.policy_type == "GLOBAL", Policy.enabled.is_(True))).scalars():
        r = pol.rules or {}
        if "auto_approve_max_score" in r and "manager_only_max_score" in r:
            return {**DEFAULT_ROUTING, **r}
    return None


def route(res: Resource, score: int, requester: User | None = None, db: Session | None = None,
          perms: list[str] | None = None, anomalous: bool = False) -> tuple[list[str], list[str]]:
    """Deterministic routing on the rule-based risk score (never on LLM output). Returns (stages, reasons).

    score <= auto_approve_max_score  -> []                 auto-approved by policy (manager is informed)
    score <= manager_only_max_score  -> [MANAGER]          manager approval only
    above                            -> [MANAGER, RISK]    manager + Security Manager
    Guardrails that always need a human: sensitive resources (CONFIDENTIAL/RESTRICTED/CRITICAL), WRITE/DELETE/ADMIN,
    and a behaviour anomaly (which also forces Security Manager review).
    A requester with no reporting manager (the Manager) is routed to the Security Manager instead.
    """
    rules = routing_rules(db)
    has_mgr = requester is None or bool(requester.manager_id)
    both = (["MANAGER"] if has_mgr else []) + ["RISK"]
    if rules is None:
        return both, ["Routing policy is disabled, so every request needs the Manager and the Security Manager."]
    auto_max, mgr_max = int(rules["auto_approve_max_score"]), int(rules["manager_only_max_score"])
    if anomalous:
        return both, [f"Unusual behaviour was detected for this requester, so the Security Manager must review it (score {score})."]
    if score > mgr_max:
        return both, [f"Risk score {score} is above {mgr_max}, so the Manager and the Security Manager must both approve."]
    blockers = []
    if res.sensitivity in set(rules.get("auto_approve_excluded_sensitivities") or []) | ALWAYS_HUMAN_SENSITIVITIES:
        blockers.append(f"{res.name} is {res.sensitivity}, and sensitive resources are never approved automatically.")
    allowed = set(rules.get("auto_approve_allowed_permissions") or AUTO_SAFE_PERMISSIONS) & AUTO_SAFE_PERMISSIONS
    risky = [p for p in (perms or []) if p not in allowed]
    if risky:
        blockers.append(f"{', '.join(risky)} can change or remove data, so a human must approve it.")
    one = ["MANAGER"] if has_mgr else ["RISK"]
    who = "the Manager" if has_mgr else "the Security Manager"
    if score <= auto_max and not blockers:
        return [], [f"Risk score {score} is {auto_max} or below, on a non-sensitive resource with read-only access, "
                    "so policy approved it automatically. The manager is informed."]
    if score <= auto_max:
        return one, blockers + [f"So {who} must approve, even though the score ({score}) is low."]
    return one, blockers + [f"Risk score {score} is between {auto_max + 1} and {mgr_max}, so {who} must approve."]


def required_stages(res: Resource, score: int, requester: User | None = None, db: Session | None = None,
                    perms: list[str] | None = None, anomalous: bool = False) -> list[str]:
    return route(res, score, requester, db, perms, anomalous)[0]


def is_anomalous(ra) -> bool:
    return any(f.get("code") == "BEHAVIOUR_ANOMALY" for f in (ra.factors or []))


def _auto_approve(db: Session, req: AccessRequest, rules: dict | None, score: int | None = None) -> None:
    """Grant immediately because the deterministic policy allows it. Audited and the manager is informed."""
    policy_actor = Actor(actor_type="SYSTEM", name="ASTITVA Policy Engine")
    if score is None:
        score = req.risk.score if req.risk else None
    req.current_stage = None
    req.status = "APPROVED"
    req.decided_at = utcnow()
    grant, token = create_grant(db, policy_actor, user_id=req.requester_id, resource_id=req.resource_id,
                                permissions=req.approved_permissions, purpose=req.purpose,
                                hours=req.approved_duration_hours, request_id=req.id,
                                approval_ref=f"AUTO-{req.ref[4:]}")
    audit.record(db, policy_actor, "REQUEST_AUTO_APPROVED", resource_id=req.resource_id, target_type="ACCESS_REQUEST",
                 target_id=req.ref, request_id=req.id,
                 reason=f"Auto-approved by policy: rule-based risk score {score} <= {rules['auto_approve_max_score'] if rules else '-'}",
                 new_state={"status": "APPROVED", "permissions": req.approved_permissions,
                            "duration_hours": req.approved_duration_hours, "score": score})
    requester = req.requester
    notify(db, requester.id, "REQUEST_APPROVED", f"Access approved automatically: {req.resource.name}",
           f"Low risk ({score}/100), so policy approved it instantly. {', '.join(req.approved_permissions)} for "
           f"{purpose_label(req.purpose)}, valid {req.approved_duration_hours}h. Token {token.token_hint}.",
           "/active-access", "SUCCESS")
    if requester.manager_id:
        notify(db, requester.manager_id, "REQUEST_AUTO_APPROVED", f"FYI: {requester.full_name} was granted access",
               f"{req.ref}: {', '.join(req.approved_permissions)} on {req.resource.name} for {purpose_label(req.purpose)}, "
               f"{req.approved_duration_hours}h. Auto-approved by policy (risk {score}/100). You can revoke it from Active Access.",
               f"/requests/{req.id}", "INFO")


def _security_reviewers(db: Session, requester: User) -> list[User]:
    from app.services.notify import users_with_role

    return [u for u in users_with_role(db, RISK_REVIEWER) if u.id not in (requester.id, requester.manager_id)]


def check_abac(user: User, res: Resource) -> str | None:
    """Deterministic attribute-based policy. Returns a denial reason or None."""
    if user.status != "ACTIVE":
        return "Requester account is not active."
    dept = user.department.code if user.department else None
    if res.allowed_departments and dept not in res.allowed_departments:
        return (f"Policy ABAC-DEPT: {res.name} may only be accessed by "
                f"{', '.join(res.allowed_departments)} departments.")
    return None


def validate_priority_inputs(deadline_at: datetime | None, business_impact: str | None,
                             now: datetime | None = None) -> tuple[datetime | None, str]:
    """Deadline is optional, must carry a timezone and must be in the future. Impact is one of four levels."""
    impact = (business_impact or "MEDIUM").upper()
    if impact not in priority.IMPACT_SCORE:
        raise WorkflowError("Business impact must be LOW, MEDIUM, HIGH or CRITICAL.", 422)
    if deadline_at is not None:
        if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
            raise WorkflowError("The deadline needs a timezone (for example 2026-11-02T18:00:00+05:30).", 422)
        deadline_at = deadline_at.astimezone(timezone.utc)
        now = now or utcnow()
        if deadline_at <= now:
            raise WorkflowError("The deadline cannot be in the past.", 422)
        if deadline_at > now + timedelta(days=365):
            raise WorkflowError("The deadline must be within one year.", 422)
    return deadline_at, impact


def submit(db: Session, actor: Actor, *, resource_id: str, permissions: list[str], purpose: str, justification: str,
           duration_hours: int, deadline_at: datetime | None = None, business_impact: str | None = None) -> AccessRequest:
    user = actor.user
    res = db.get(Resource, resource_id)
    if not res:
        raise WorkflowError("Resource not found", 404)
    perms = sort_perms(permissions)
    if not perms:
        raise WorkflowError("Select at least one permission.")
    invalid = [p for p in perms if p not in res.available_permissions]
    if invalid:
        raise WorkflowError(f"{', '.join(invalid)} is not available on {res.name}.", 422)
    if purpose not in PURPOSES:
        raise WorkflowError("Unknown purpose.", 422)
    if not (1 <= duration_hours <= 2160):
        raise WorkflowError("Duration must be between 1 hour and 90 days.", 422)
    if len(justification.strip()) < 10:
        raise WorkflowError("Provide a business justification (at least 10 characters).", 422)
    deadline_at, business_impact = validate_priority_inputs(deadline_at, business_impact)
    denial = check_abac(user, res)
    if denial:
        audit.record(db, actor, "REQUEST_DENIED_BY_POLICY", resource_id=res.id, target_type="RESOURCE", target_id=res.id,
                     reason=denial, new_state={"permissions": perms, "purpose": purpose})
        raise_alert(db, "LOW", "POLICY_VIOLATION", f"Policy-blocked request by {user.full_name}", denial,
                    user_id=user.id, resource_id=res.id, notify_admins=False)
        db.commit()
        raise WorkflowError(denial, 403, "ABAC")
    dup = db.scalar(select(AccessRequest.id).where(AccessRequest.requester_id == user.id,
                                                   AccessRequest.resource_id == res.id,
                                                   AccessRequest.status.in_(["PENDING", "CHANGES_REQUESTED"])))
    if dup:
        raise WorkflowError("You already have an open request for this resource.", 409)

    req = AccessRequest(ref=_next_ref(db), requester_id=user.id, resource_id=res.id, requested_permissions=perms,
                        approved_permissions=perms, purpose=purpose, justification=justification.strip(),
                        requested_duration_hours=duration_hours, approved_duration_hours=duration_hours,
                        status="PENDING", required_stages=[], deadline_at=deadline_at, business_impact=business_impact)
    db.add(req)
    db.flush()
    db.refresh(req)
    ra = risk.assess(db, req)
    rules = routing_rules(db)
    req.required_stages, req.routing_reasons = route(res, ra.score, user, db, perms, is_anomalous(ra))
    if "RISK" in req.required_stages and not _security_reviewers(db, user):
        db.rollback()
        raise WorkflowError("No independent Security Manager is available to review your own request. "
                            "Use Emergency Access for urgent needs; it is monitored and reviewed afterwards.",
                            409, "SELF_APPROVAL")
    req.current_stage = req.required_stages[0] if req.required_stages else None
    audit.record(db, actor, "REQUEST_CREATED", resource_id=res.id, target_type="ACCESS_REQUEST", target_id=req.ref,
                 request_id=req.id, new_state={"permissions": perms, "purpose": purpose, "duration_hours": duration_hours,
                                               "stages": req.required_stages, "routing": req.routing_reasons,
                                               "deadline_at": deadline_at.isoformat() if deadline_at else None,
                                               "business_impact": business_impact}, reason=justification[:500])
    audit.record(db, Actor(actor_type="SYSTEM", name="ASTITVA Risk Engine"), "RISK_ASSESSED", resource_id=res.id,
                 target_type="ACCESS_REQUEST", target_id=req.ref, request_id=req.id,
                 new_state={"score": ra.score, "level": ra.level, "recommended_permissions": ra.recommended_permissions,
                            "recommended_duration_hours": ra.recommended_duration_hours, "engine": ra.engine})
    if not req.required_stages:
        _auto_approve(db, req, rules, ra.score)
        db.commit()
        db.expire(req, ["risks", "approvals"])
        return req
    _notify_stage(db, req)
    if ra.level in ("HIGH", "CRITICAL"):
        raise_alert(db, ra.level, "HIGH_RISK_REQUEST", f"{ra.level.title()}-risk request {req.ref}",
                    f"{user.full_name} requested {', '.join(perms)} on {res.name} (score {ra.score}).",
                    user_id=user.id, resource_id=res.id, notify_admins=ra.level == "CRITICAL")
        notify_role(db, RISK_REVIEWER, "HIGH_RISK_REQUEST", f"High-risk request {req.ref}",
                    f"Risk score {ra.score}: {ra.anomalies[0] if ra.anomalies else res.name}", f"/approvals/{req.id}",
                    "WARNING", exclude={user.id})
    notify(db, user.id, "REQUEST_SUBMITTED", f"Request {req.ref} submitted",
           f"Your request for {res.name} is awaiting {sod.STAGE_LABEL[req.current_stage].lower()}.", f"/requests/{req.id}")
    db.commit()
    db.expire(req, ["risks", "approvals"])
    return req


def stage_approvers(db: Session, req: AccessRequest) -> list[User]:
    stage = req.current_stage
    if stage == "MANAGER":
        if req.requester.manager_id:
            m = db.get(User, req.requester.manager_id)
            return [m] if m and m.status == "ACTIVE" else []
        from app.services.notify import users_with_role

        return users_with_role(db, SECURITY_ADMIN)
    if stage == "RISK":
        return _security_reviewers(db, req.requester)
    if stage == "OWNER":
        ids = [i for i in (req.resource.owner_id, req.resource.backup_owner_id) if i]
        return [u for u in (db.get(User, i) for i in ids) if u and u.status == "ACTIVE"]
    return []


def _notify_stage(db: Session, req: AccessRequest) -> None:
    for u in stage_approvers(db, req):
        if sod.eligible_for_stage(db, u, req, req.current_stage):
            notify(db, u.id, "APPROVAL_REQUIRED", f"Approval required: {req.ref}",
                   f"{req.requester.full_name} requests {', '.join(req.approved_permissions)} on {req.resource.name} "
                   f"for {purpose_label(req.purpose)}.", f"/approvals/{req.id}",
                   "WARNING" if (req.risk and req.risk.score > 60) else "INFO")


def act(db: Session, actor: Actor, request_id: str, action: str, comment: str | None = None,
        permissions: list[str] | None = None, duration_hours: int | None = None) -> AccessRequest:
    req = db.get(AccessRequest, request_id)
    if not req:
        raise WorkflowError("Request not found", 404)
    if req.status != "PENDING" or not req.current_stage:
        raise WorkflowError(f"Request is {req.status.lower().replace('_', ' ')} and cannot be actioned.", 409)
    stage = req.current_stage
    try:
        sod.check(db, actor.user, req, stage)
    except sod.SodViolation as v:
        audit.record(db, actor, "SOD_VIOLATION_BLOCKED", resource_id=req.resource_id, target_type="ACCESS_REQUEST",
                     target_id=req.ref, request_id=req.id, reason=str(v),
                     new_state={"attempted_action": action, "stage": stage, "rule": v.rule})
        raise_alert(db, "MEDIUM", "SOD_VIOLATION", f"Separation-of-duties block on {req.ref}",
                    f"{actor.display_name} attempted {action} at {stage} stage: {v.message}",
                    user_id=actor.user.id, resource_id=req.resource_id, notify_admins=False)
        db.commit()
        raise WorkflowError(v.message, 403, v.rule)

    prev_scope = {"permissions": list(req.approved_permissions), "duration_hours": req.approved_duration_hours}
    if action in ("REJECT", "REQUEST_MODIFICATION") and not (comment and comment.strip()):
        raise WorkflowError("A comment is required for this action.", 422)

    if action == "NARROW_SCOPE":
        new_perms = sort_perms(permissions or req.approved_permissions)
        new_hours = duration_hours or req.approved_duration_hours
        if not new_perms or not set(new_perms) <= set(req.approved_permissions):
            raise WorkflowError("Narrowed permissions must be a non-empty subset of the current scope.", 422)
        if new_hours > req.approved_duration_hours or new_hours < 1:
            raise WorkflowError("Narrowed duration cannot exceed the current duration.", 422)
        if set(new_perms) == set(req.approved_permissions) and new_hours == req.approved_duration_hours:
            raise WorkflowError("Narrowing must reduce permissions or duration.", 422)
        req.approved_permissions = new_perms
        req.approved_duration_hours = new_hours

    new_scope = {"permissions": list(req.approved_permissions), "duration_hours": req.approved_duration_hours}
    db.add(ApprovalRecord(request_id=req.id, stage=stage, approver_id=actor.user.id, action=action, comment=comment,
                          previous_scope=prev_scope, new_scope=new_scope))
    prev_state = {"status": req.status, "stage": stage, **prev_scope}

    if action in ("APPROVE", "NARROW_SCOPE"):
        idx = req.required_stages.index(stage)
        if action == "NARROW_SCOPE":
            notify(db, req.requester_id, "PERMISSION_NARROWED", f"Scope narrowed on {req.ref}",
                   f"{actor.display_name} narrowed your request to {', '.join(req.approved_permissions)} for "
                   f"{req.approved_duration_hours}h.", f"/requests/{req.id}", "WARNING")
        if idx + 1 < len(req.required_stages):
            req.current_stage = req.required_stages[idx + 1]
            _notify_stage(db, req)
        else:
            req.current_stage = None
            req.status = "APPROVED"
            req.decided_at = utcnow()
            approval_ref = f"APR-{req.ref[4:]}-{len(req.approvals) + 1}"
            grant, token = create_grant(db, actor, user_id=req.requester_id, resource_id=req.resource_id,
                                        permissions=req.approved_permissions, purpose=req.purpose,
                                        hours=req.approved_duration_hours, request_id=req.id, approval_ref=approval_ref)
            notify(db, req.requester_id, "REQUEST_APPROVED", f"Access approved: {req.resource.name}",
                   f"{', '.join(req.approved_permissions)} for {purpose_label(req.purpose)}, valid "
                   f"{req.approved_duration_hours}h. Token {token.token_hint}.", "/active-access", "SUCCESS")
    elif action == "REJECT":
        req.status = "REJECTED"
        req.current_stage = None
        req.decided_at = utcnow()
        notify(db, req.requester_id, "REQUEST_REJECTED", f"Request {req.ref} rejected",
               f"{actor.display_name}: {comment}", f"/requests/{req.id}", "CRITICAL")
    elif action == "REQUEST_MODIFICATION":
        req.status = "CHANGES_REQUESTED"
        notify(db, req.requester_id, "MODIFICATION_REQUESTED", f"Changes requested on {req.ref}",
               f"{actor.display_name}: {comment}", f"/requests/{req.id}", "WARNING")
    else:
        raise WorkflowError("Unknown action.", 422)

    audit.record(db, actor, f"REQUEST_{action}", resource_id=req.resource_id, target_type="ACCESS_REQUEST",
                 target_id=req.ref, request_id=req.id, previous_state=prev_state,
                 new_state={"status": req.status, "stage": req.current_stage, **new_scope}, reason=comment)
    db.commit()
    db.expire(req, ["risks", "approvals"])
    db.refresh(req)
    return req


def update_priority_inputs(db: Session, actor: Actor, request_id: str, *, deadline_at: datetime | None,
                           business_impact: str) -> AccessRequest:
    """The requester may change the deadline or business impact while the request is open. The priority score
    itself is always computed by the server and cannot be set by anyone."""
    req = db.get(AccessRequest, request_id)
    if not req or req.requester_id != actor.user.id:
        raise WorkflowError("Request not found", 404)
    if req.status not in ("PENDING", "CHANGES_REQUESTED"):
        raise WorkflowError("Only open requests can be changed.", 409)
    deadline_at, business_impact = validate_priority_inputs(deadline_at, business_impact)
    prev = {"deadline_at": req.deadline_at.isoformat() if req.deadline_at else None, "business_impact": req.business_impact}
    req.deadline_at, req.business_impact = deadline_at, business_impact
    audit.record(db, actor, "REQUEST_PRIORITY_INPUTS_CHANGED", resource_id=req.resource_id, target_type="ACCESS_REQUEST",
                 target_id=req.ref, request_id=req.id, previous_state=prev,
                 new_state={"deadline_at": deadline_at.isoformat() if deadline_at else None,
                            "business_impact": business_impact})
    db.commit()
    db.refresh(req)
    return req


def resubmit(db: Session, actor: Actor, request_id: str, *, permissions: list[str], purpose: str, justification: str,
             duration_hours: int, deadline_at: datetime | None = None, business_impact: str | None = None) -> AccessRequest:
    req = db.get(AccessRequest, request_id)
    if not req or req.requester_id != actor.user.id:
        raise WorkflowError("Request not found", 404)
    if req.status != "CHANGES_REQUESTED":
        raise WorkflowError("Only requests with changes requested can be resubmitted.", 409)
    perms = sort_perms(permissions)
    if not perms or any(p not in req.resource.available_permissions for p in perms) or purpose not in PURPOSES:
        raise WorkflowError("Invalid permissions or purpose.", 422)
    deadline_at, business_impact = validate_priority_inputs(deadline_at, business_impact or req.business_impact)
    prev = {"permissions": req.approved_permissions, "purpose": req.purpose, "duration_hours": req.approved_duration_hours}
    req.deadline_at, req.business_impact = deadline_at, business_impact
    req.requested_permissions = req.approved_permissions = perms
    req.purpose = purpose
    req.justification = justification.strip()
    req.requested_duration_hours = req.approved_duration_hours = duration_hours
    req.status = "PENDING"
    db.flush()
    ra = risk.assess(db, req, as_of=utcnow())
    req.required_stages, req.routing_reasons = route(req.resource, ra.score, req.requester, db, perms, is_anomalous(ra))
    req.current_stage = req.required_stages[0] if req.required_stages else None
    audit.record(db, actor, "REQUEST_RESUBMITTED", resource_id=req.resource_id, target_type="ACCESS_REQUEST",
                 target_id=req.ref, request_id=req.id, previous_state=prev,
                 new_state={"permissions": perms, "purpose": purpose, "duration_hours": duration_hours, "risk": ra.score})
    db.expire(req, ["risks"])
    if not req.required_stages:
        _auto_approve(db, req, routing_rules(db), ra.score)
    else:
        _notify_stage(db, req)
    db.commit()
    db.expire(req, ["risks", "approvals"])
    db.refresh(req)
    return req


def cancel(db: Session, actor: Actor, request_id: str) -> AccessRequest:
    req = db.get(AccessRequest, request_id)
    if not req or req.requester_id != actor.user.id:
        raise WorkflowError("Request not found", 404)
    if req.status not in ("PENDING", "CHANGES_REQUESTED"):
        raise WorkflowError("Only open requests can be cancelled.", 409)
    req.status = "CANCELLED"
    req.current_stage = None
    audit.record(db, actor, "REQUEST_CANCELLED", resource_id=req.resource_id, target_type="ACCESS_REQUEST",
                 target_id=req.ref, request_id=req.id, new_state={"status": "CANCELLED"})
    db.commit()
    return req


def active_grants_count(db: Session, user_id: str) -> int:
    return db.scalar(select(func.count()).select_from(AccessGrant).where(AccessGrant.user_id == user_id,
                                                                        AccessGrant.status == "ACTIVE")) or 0
