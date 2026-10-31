"""Dynamic Separation-of-Duties engine.

Built-in rules are always enforced; administrators can add SOD policies
(policy_type="SOD") of the kinds ROLE_CONFLICT, STAGE_CONFLICT and DEPARTMENT_CONFLICT.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import MANAGER, RESOURCE_OWNER, RISK_REVIEWER, SECURITY_ADMIN
from app.models import AccessRequest, ApprovalRecord, Policy, User

STAGES = ("MANAGER", "RISK", "OWNER")
STAGE_LABEL = {"MANAGER": "Manager review", "RISK": "Security review", "OWNER": "Resource owner approval"}
STAGE_ROLE = {"MANAGER": MANAGER, "RISK": RISK_REVIEWER, "OWNER": RESOURCE_OWNER}


@dataclass
class SodViolation(Exception):
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.message}"


def eligible_for_stage(db: Session, actor: User, req: AccessRequest, stage: str) -> bool:
    try:
        check(db, actor, req, stage)
        return True
    except SodViolation:
        return False


def stage_authority(actor: User, req: AccessRequest, stage: str) -> None:
    requester = req.requester
    roles = set(actor.role_names)
    if stage == "MANAGER":
        if requester.manager_id:
            if actor.id != requester.manager_id or MANAGER not in roles:
                raise SodViolation("STAGE_AUTHORITY", "Only the requester's reporting manager can perform manager review.")
        elif SECURITY_ADMIN not in roles:
            raise SodViolation("STAGE_AUTHORITY", "Requester has no manager; a Security Admin must perform manager review.")
    elif stage == "RISK":
        if RISK_REVIEWER not in roles:
            raise SodViolation("STAGE_AUTHORITY", "Only the Security Manager can perform security review.")
    elif stage == "OWNER":
        res = req.resource
        if actor.id not in (res.owner_id, res.backup_owner_id) or RESOURCE_OWNER not in roles:
            raise SodViolation("STAGE_AUTHORITY", "Only the resource owner (or designated backup owner) can give final approval.")
    else:
        raise SodViolation("STAGE_AUTHORITY", f"Unknown stage {stage}.")


def check(db: Session, actor: User, req: AccessRequest, stage: str) -> None:
    requester = req.requester
    # Rule 1: no self-approval, in any stage, under any role.
    if actor.id == requester.id:
        raise SodViolation("SELF_APPROVAL", "Requesters cannot approve their own access request.")
    # Rule 2: the actor must hold authority for this stage.
    stage_authority(actor, req, stage)
    # Rule 3: a subordinate cannot approve for their own manager.
    if actor.manager_id == requester.id:
        raise SodViolation("REPORTING_CONFLICT", "You report to the requester and cannot approve their request.")
    # Rule 4: reviewers must be independent - one person may act on only one stage of a request.
    prior = db.execute(select(ApprovalRecord).where(ApprovalRecord.request_id == req.id,
                                                    ApprovalRecord.approver_id == actor.id,
                                                    ApprovalRecord.stage != stage,
                                                    ApprovalRecord.action.in_(["APPROVE", "NARROW_SCOPE"]))).scalars().first()
    if prior:
        raise SodViolation("INDEPENDENT_REVIEWERS",
                           f"You already approved the {STAGE_LABEL.get(prior.stage, prior.stage).lower()} stage of this "
                           "request. Required reviewers must be independent.")
    # Rule 5: the requester's manager cannot also act as the resource owner / risk reviewer for the same request.
    if stage in ("OWNER", "RISK") and requester.manager_id == actor.id:
        raise SodViolation("MANAGER_DUAL_ROLE",
                           "The requester's manager cannot also give the security approval for the same request.")
    # Admin-defined policies
    for pol in db.execute(select(Policy).where(Policy.policy_type == "SOD", Policy.enabled.is_(True))).scalars():
        _apply_policy(db, pol, actor, req, stage)


def _apply_policy(db: Session, pol: Policy, actor: User, req: AccessRequest, stage: str) -> None:
    r = pol.rules or {}
    kind = r.get("kind")
    stages = r.get("stages") or list(STAGES)
    if kind == "ROLE_CONFLICT":
        # A person holding all of these roles may not act on the listed stages.
        if stage in stages and set(r.get("roles", [])) <= set(actor.role_names) and r.get("roles"):
            raise SodViolation(f"POLICY:{pol.name}", r.get("message") or
                               f"Holding roles {' + '.join(r['roles'])} together conflicts with {STAGE_LABEL[stage].lower()}.")
    elif kind == "STAGE_CONFLICT":
        # The same person may not act on both stages in the pair (already covered by Rule 4, kept for explicit policy).
        pair = r.get("pair", [])
        if stage in pair:
            others = [s for s in pair if s != stage]
            prior = db.execute(select(ApprovalRecord).where(ApprovalRecord.request_id == req.id,
                                                            ApprovalRecord.approver_id == actor.id,
                                                            ApprovalRecord.stage.in_(others))).scalars().first()
            if prior:
                raise SodViolation(f"POLICY:{pol.name}", r.get("message") or "Conflicting approval combination.")
    elif kind == "DEPARTMENT_CONFLICT":
        # Reviewer for these stages must come from a different department than the requester.
        if stage in stages and actor.department_id and actor.department_id == req.requester.department_id:
            raise SodViolation(f"POLICY:{pol.name}", r.get("message") or
                               "Reviewer must be independent of the requester's department for this stage.")
    elif kind == "RESOURCE_SENSITIVITY_DUAL_CONTROL":
        # For listed sensitivities, the owner stage cannot be the backup owner if the primary owner is available.
        if stage == "OWNER" and req.resource.sensitivity in r.get("sensitivities", []) and actor.id != req.resource.owner_id:
            raise SodViolation(f"POLICY:{pol.name}", r.get("message") or "Primary resource owner approval required.")
