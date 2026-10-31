from __future__ import annotations

from app.core.catalog import purpose_label
from app.models import AccessGrant, AccessRequest, AiAgent, EmergencySession, Resource, RiskAssessment, User, utcnow


def user_brief(u: User | None) -> dict | None:
    if not u:
        return None
    return {"id": u.id, "employee_id": u.employee_id, "name": u.full_name, "email": u.email,
            "designation": u.designation, "department": u.department.name if u.department else None,
            "department_code": u.department.code if u.department else None, "status": u.status,
            "roles": u.role_names}


def resource_brief(r: Resource | None) -> dict | None:
    if not r:
        return None
    return {"id": r.id, "code": r.code, "name": r.name, "type": r.resource_type, "sensitivity": r.sensitivity,
            "department": r.department.name if r.department else None}


def resource_full(r: Resource) -> dict:
    return {**resource_brief(r), "description": r.description, "owner": user_brief(r.owner),
            "backup_owner_id": r.backup_owner_id, "available_permissions": r.available_permissions,
            "allowed_purposes": [{"code": p, "label": purpose_label(p)} for p in r.allowed_purposes],
            "allowed_departments": r.allowed_departments, "max_duration_hours": r.max_duration_hours,
            "breakglass_allowed": r.breakglass_allowed, "requires_risk_review": r.requires_risk_review}


def risk_out(ra: RiskAssessment | None) -> dict | None:
    if not ra:
        return None
    return {"score": ra.score, "level": ra.level, "factors": ra.factors, "anomalies": ra.anomalies,
            "recommended_permissions": ra.recommended_permissions,
            "recommended_duration_hours": ra.recommended_duration_hours, "recommended_action": ra.recommended_action,
            "explanation": ra.explanation, "engine": ra.engine, "assessed_at": ra.created_at}


def access_out(g: AccessGrant) -> dict:
    """Current state of the access a request produced: ACTIVE, REVOKED or EXPIRED, and what is left of it."""
    return {"grant_id": g.id, "status": g.status, "permissions": g.permissions, "expires_at": g.expires_at,
            "revoked_at": g.revoked_at, "revoke_reason": g.revoke_reason,
            "revoked_by": user_brief(g.revoked_by) if g.revoked_by else None}


def request_out(r: AccessRequest, include_detail: bool = False, now=None) -> dict:
    from app.services import priority

    is_open = r.status in ("PENDING", "CHANGES_REQUESTED")
    out = {
        "id": r.id, "ref": r.ref, "requester": user_brief(r.requester), "resource": resource_brief(r.resource),
        "requested_permissions": r.requested_permissions, "approved_permissions": r.approved_permissions,
        "purpose": r.purpose, "purpose_label": purpose_label(r.purpose), "justification": r.justification,
        "requested_duration_hours": r.requested_duration_hours, "approved_duration_hours": r.approved_duration_hours,
        "status": r.status, "current_stage": r.current_stage, "required_stages": r.required_stages,
        "created_at": r.created_at, "updated_at": r.updated_at, "decided_at": r.decided_at,
        "risk": {"score": r.risk.score, "level": r.risk.level} if r.risk else None,
        "auto_approved": r.status == "APPROVED" and not r.required_stages,
        "decision_stage": r.approvals[-1].stage if r.status in ("REJECTED", "CHANGES_REQUESTED") and r.approvals else None,
        "access": access_out(r.grant) if r.grant else None,
        "deadline_at": r.deadline_at, "business_impact": r.business_impact,
        # computed on every read, only for open requests; nobody can store or edit it
        "priority": priority.for_request(r, now).as_dict() if is_open else None,
        "routing_reasons": r.routing_reasons or [],
    }
    if include_detail:
        out["risk"] = risk_out(r.risk)
        out["approvals"] = [{"id": a.id, "stage": a.stage, "action": a.action, "comment": a.comment,
                             "approver": user_brief(a.approver), "previous_scope": a.previous_scope,
                             "new_scope": a.new_scope, "at": a.created_at} for a in r.approvals]
    return out


def grant_out(g: AccessGrant, token_hint: str | None = None) -> dict:
    now = utcnow()
    return {"id": g.id, "user": user_brief(g.user), "resource": resource_brief(g.resource), "permissions": g.permissions,
            "purpose": g.purpose, "purpose_label": purpose_label(g.purpose), "status": g.status, "source": g.source,
            "is_emergency": g.is_emergency, "granted_at": g.granted_at, "expires_at": g.expires_at,
            "remaining_seconds": int((g.expires_at - now).total_seconds()) if g.expires_at and g.status == "ACTIVE" else None,
            "revoked_at": g.revoked_at, "revoke_reason": g.revoke_reason, "last_used_at": g.last_used_at,
            "request_id": g.request_id, "token_hint": token_hint,
            "revoked_by": user_brief(g.revoked_by) if g.revoked_by else None}


def emergency_out(e: EmergencySession, actions: int | None = None) -> dict:
    now = utcnow()
    return {"id": e.id, "ref": e.ref, "user": user_brief(e.user), "resource": resource_brief(e.resource),
            "justification": e.justification, "incident_ref": e.incident_ref, "permissions": e.permissions,
            "status": e.status, "started_at": e.started_at, "expires_at": e.expires_at, "ended_at": e.ended_at,
            "remaining_seconds": max(0, int((e.expires_at - now).total_seconds())) if e.status == "ACTIVE" else 0,
            "review_status": e.review_status, "review_outcome": e.review_outcome,
            "review_notes": None if (e.review_notes or "").startswith("[reminded]") else e.review_notes,
            "reviewed_at": e.reviewed_at, "actions_performed": actions}


def agent_out(a: AiAgent, resources: dict[str, Resource] | None = None) -> dict:
    return {"id": a.id, "code": a.code, "name": a.name, "purpose": a.purpose, "owner": user_brief(a.owner),
            "status": a.status, "risk_score": a.risk_score, "allowed_tools": a.allowed_tools, "expires_at": a.expires_at,
            "permissions": [{"id": p.id, "resource": resource_brief(resources.get(p.resource_id)) if resources else p.resource_id,
                             "permissions": p.permissions, "expires_at": p.expires_at} for p in a.permissions]}
