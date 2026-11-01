"""ASTITVA relational schema.

All timestamps are timezone-aware UTC. Secrets (passwords, OTPs, refresh tokens,
access tokens, recovery codes, agent keys) are only ever stored as hashes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


TS = DateTime(timezone=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)


# ---------------------------------------------------------------- org structure
class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), index=True)
    designation: Mapped[str | None] = mapped_column(String(120))
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    joined_at: Mapped[datetime | None] = mapped_column(TS)
    phone: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(80))
    device_trust: Mapped[str] = mapped_column(String(16), default="TRUSTED")  # TRUSTED | UNKNOWN | UNTRUSTED (simulated)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)  # ACTIVE | DEACTIVATED
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_until: Mapped[datetime | None] = mapped_column(TS)
    lockout_level: Mapped[int] = mapped_column(Integer, default=0)
    password_changed_at: Mapped[datetime | None] = mapped_column(TS)
    deactivated_at: Mapped[datetime | None] = mapped_column(TS)
    is_service_account: Mapped[bool] = mapped_column(Boolean, default=False)

    department: Mapped[Department | None] = relationship(lazy="joined")
    manager: Mapped[User | None] = relationship(remote_side="User.id", lazy="select")
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return sorted(r.name for r in self.roles)

    __table_args__ = (CheckConstraint("status IN ('ACTIVE','DEACTIVATED')", name="ck_user_status"),)


# ---------------------------------------------------------------- authentication
class MfaCredential(Base):
    __tablename__ = "mfa_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # TOTP | BACKUP_CODE | SMS
    secret_encrypted: Mapped[str | None] = mapped_column(Text)  # TOTP seed, Fernet-encrypted
    code_hash: Mapped[str | None] = mapped_column(String(255))  # backup codes: Argon2id hash
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)  # prevents TOTP replay
    used_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class OtpChallenge(Base):
    """One-time codes and pending-MFA login challenges. Codes are stored hashed."""

    __tablename__ = "otp_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))  # EMAIL_VERIFY | LOGIN_MFA | PASSWORD_RESET
    code_hash: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str | None] = mapped_column(String(16))  # EMAIL | SMS | TOTP
    ip: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(TS)
    consumed_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    stage: Mapped[str] = mapped_column(String(16), default="PASSWORD")  # PASSWORD | MFA
    reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    mfa_method: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    revoke_reason: Mapped[str | None] = mapped_column(String(64))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    issued_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    expires_at: Mapped[datetime] = mapped_column(TS)


class DevOutbox(Base):
    """Simulated email/SMS delivery for local development (no real messages are sent)."""

    __tablename__ = "dev_outbox"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(8))
    recipient: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ---------------------------------------------------------------- work
class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    description: Mapped[str | None] = mapped_column(Text)
    # Project timeline (simulated). Time-bound access is capped at end_date so access never outlives the project.
    team_name: Mapped[str | None] = mapped_column(String(120))
    start_date: Mapped[datetime | None] = mapped_column(TS)
    submission_date: Mapped[datetime | None] = mapped_column(TS)  # deliverable due date
    end_date: Mapped[datetime | None] = mapped_column(TS)


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), default="Contributor")
    joined_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    assignee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="TODO")  # TODO | IN_PROGRESS | DONE
    priority: Mapped[str] = mapped_column(String(8), default="MEDIUM")
    due_at: Mapped[datetime | None] = mapped_column(TS)
    completed_at: Mapped[datetime | None] = mapped_column(TS)
    quality_score: Mapped[float | None] = mapped_column(Float)  # 0-5 from verified review
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(TS)


class TaskEvent(Base):
    """Recorded, verifiable work events. Analytics are computed only from these."""

    __tablename__ = "task_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(16))  # CREATED | STARTED | COMMIT | COMPLETED | VERIFIED
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"))
    action: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(16))
    details: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


# ---------------------------------------------------------------- resources & policy
SENSITIVITY_LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CRITICAL")


class Resource(Base, TimestampMixin):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    resource_type: Mapped[str] = mapped_column(String(32))  # AI_MODEL | DATASET | DATABASE | API
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    backup_owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    sensitivity: Mapped[str] = mapped_column(String(16), index=True)
    available_permissions: Mapped[list] = mapped_column(JSON, default=list)
    allowed_purposes: Mapped[list] = mapped_column(JSON, default=list)
    allowed_departments: Mapped[list] = mapped_column(JSON, default=list)  # ABAC: empty = any
    max_duration_hours: Mapped[int] = mapped_column(Integer, default=168)
    breakglass_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_risk_review: Mapped[bool] = mapped_column(Boolean, default=True)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id], lazy="joined")
    department: Mapped[Department | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "sensitivity IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED','CRITICAL')", name="ck_resource_sensitivity"
        ),
    )


class Policy(Base, TimestampMixin):
    """Admin-defined policies. policy_type: SOD (conflicting roles/stages), ABAC, GLOBAL."""

    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    policy_type: Mapped[str] = mapped_column(String(16), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------- access lifecycle
class AccessRequest(Base, TimestampMixin):
    __tablename__ = "access_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ref: Mapped[str] = mapped_column(String(24), unique=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), index=True)
    requested_permissions: Mapped[list] = mapped_column(JSON)
    approved_permissions: Mapped[list] = mapped_column(JSON)  # current scope (narrowed by reviewers)
    purpose: Mapped[str] = mapped_column(String(40))
    justification: Mapped[str] = mapped_column(Text)
    requested_duration_hours: Mapped[int] = mapped_column(Integer)
    approved_duration_hours: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    # PENDING | CHANGES_REQUESTED | APPROVED | REJECTED | CANCELLED
    current_stage: Mapped[str | None] = mapped_column(String(16))  # MANAGER | RISK | OWNER
    required_stages: Mapped[list] = mapped_column(JSON)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    # Priority inputs (never used for risk or approval decisions)
    deadline_at: Mapped[datetime | None] = mapped_column(TS, index=True)  # requested completion deadline (UTC)
    business_impact: Mapped[str] = mapped_column(String(10), default="MEDIUM", server_default="MEDIUM")
    routing_reasons: Mapped[list | None] = mapped_column(JSON)  # why this approval path was chosen
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)  # requester's current project

    requester: Mapped[User] = relationship(foreign_keys=[requester_id], lazy="joined")
    resource: Mapped[Resource] = relationship(lazy="joined")
    approvals: Mapped[list[ApprovalRecord]] = relationship(
        back_populates="request", order_by="ApprovalRecord.created_at", lazy="selectin"
    )
    risks: Mapped[list[RiskAssessment]] = relationship(
        back_populates="request", lazy="selectin", order_by="RiskAssessment.created_at.desc()"
    )
    grants: Mapped[list["AccessGrant"]] = relationship(
        primaryjoin="AccessGrant.request_id == AccessRequest.id", viewonly=True, lazy="selectin",
        order_by="AccessGrant.granted_at.desc()"
    )

    @property
    def grant(self) -> "AccessGrant | None":
        """The grant this request produced (latest), if any."""
        return self.grants[0] if self.grants else None

    @property
    def risk(self) -> RiskAssessment | None:
        """Latest risk assessment (requests are re-assessed on resubmission)."""
        return self.risks[0] if self.risks else None


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("access_requests.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(24))  # APPROVE | REJECT | NARROW_SCOPE | REQUEST_MODIFICATION
    comment: Mapped[str | None] = mapped_column(Text)
    previous_scope: Mapped[dict | None] = mapped_column(JSON)
    new_scope: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    request: Mapped[AccessRequest] = relationship(back_populates="approvals")
    approver: Mapped[User] = relationship(lazy="joined")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("access_requests.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(10))
    factors: Mapped[list] = mapped_column(JSON)
    anomalies: Mapped[list] = mapped_column(JSON)
    recommended_permissions: Mapped[list] = mapped_column(JSON)
    recommended_duration_hours: Mapped[int] = mapped_column(Integer)
    recommended_action: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    request: Mapped[AccessRequest] = relationship(back_populates="risks")

    __table_args__ = (CheckConstraint("score >= 0 AND score <= 100", name="ck_risk_score_range"),)


class AccessGrant(Base, TimestampMixin):
    __tablename__ = "access_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), index=True)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("access_requests.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    permissions: Mapped[list] = mapped_column(JSON)
    purpose: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)  # ACTIVE | EXPIRED | REVOKED
    source: Mapped[str] = mapped_column(String(16), default="REQUEST")  # REQUEST | EMERGENCY | LEGACY
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(TS, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(TS)
    expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    resource: Mapped[Resource] = relationship(lazy="joined")
    revoked_by: Mapped[User | None] = relationship(foreign_keys=[revoked_by_id], lazy="joined")

    __table_args__ = (Index("ix_grants_user_resource_status", "user_id", "resource_id", "status"),)


class AccessToken(Base):
    """Purpose-bound simulated access token. Only the SHA-256 (peppered) hash is stored."""

    __tablename__ = "access_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    token_hint: Mapped[str] = mapped_column(String(24))  # e.g. SIM-ACCESS-8F72X91 (public identifier part)
    token_encrypted: Mapped[str] = mapped_column(Text)  # Fernet-encrypted so the holder can re-reveal it
    grant_id: Mapped[str] = mapped_column(ForeignKey("access_grants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    request_id: Mapped[str | None] = mapped_column(ForeignKey("access_requests.id"))
    approval_ref: Mapped[str | None] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(40))
    permissions: Mapped[list] = mapped_column(JSON)
    issued_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class ResourceAccessEvent(Base):
    """Every enforcement decision at the resource gateway (humans and agents)."""

    __tablename__ = "resource_access_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("ai_agents.id"), index=True)
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"), index=True)
    grant_id: Mapped[str | None] = mapped_column(ForeignKey("access_grants.id"))
    emergency_session_id: Mapped[str | None] = mapped_column(ForeignKey("emergency_sessions.id"))
    action: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str | None] = mapped_column(String(40))
    tool: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(8))  # ALLOWED | DENIED
    reason: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


# ---------------------------------------------------------------- audit
class AuditChainHead(Base):
    __tablename__ = "audit_chain_head"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_hash: Mapped[str] = mapped_column(String(64))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=False)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String(8))  # USER | AGENT | SYSTEM
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_name: Mapped[str] = mapped_column(String(160))
    actor_role: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    previous_state: Mapped[dict | None] = mapped_column(JSON)
    new_state: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class SecurityAlert(Base):
    __tablename__ = "security_alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    severity: Mapped[str] = mapped_column(String(10), index=True)  # LOW | MEDIUM | HIGH | CRITICAL
    category: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("ai_agents.id"))
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"))
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)  # OPEN | ACKNOWLEDGED | RESOLVED
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    # Set when RESOLVED: CONFIRMED (a real violation, counts in risk history) | FALSE_POSITIVE (does not count)
    resolution: Mapped[str | None] = mapped_column(String(16), index=True)


# ---------------------------------------------------------------- emergency
class EmergencySession(Base):
    __tablename__ = "emergency_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ref: Mapped[str] = mapped_column(String(24), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    grant_id: Mapped[str | None] = mapped_column(ForeignKey("access_grants.id"))
    justification: Mapped[str] = mapped_column(Text)
    incident_ref: Mapped[str] = mapped_column(String(64))
    permissions: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", index=True)  # ACTIVE | EXPIRED | REVOKED
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_status: Mapped[str] = mapped_column(String(12), default="PENDING")  # PENDING | COMPLETED
    review_outcome: Mapped[str | None] = mapped_column(String(24))  # JUSTIFIED | MISUSE | INCONCLUSIVE
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(TS)

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    resource: Mapped[Resource] = relationship(lazy="joined")


# ---------------------------------------------------------------- drift & reviews
class PermissionBaseline(Base, TimestampMixin):
    __tablename__ = "permission_baselines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    permissions: Mapped[list] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(24), default="JOB_PROFILE")
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("user_id", "resource_id", name="uq_baseline_user_resource"),)


class DriftFinding(Base):
    __tablename__ = "drift_findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    baseline_permissions: Mapped[list] = mapped_column(JSON)
    current_permissions: Mapped[list] = mapped_column(JSON)
    excess_permissions: Mapped[list] = mapped_column(JSON)
    unused_permissions: Mapped[list] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON)
    drift_score: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(10))
    recommendation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    # OPEN | REVIEWED | REMEDIATED | REVIEW_SCHEDULED
    detected_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)


class AccessReviewCampaign(Base):
    __tablename__ = "access_review_campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(TS)
    status: Mapped[str] = mapped_column(String(12), default="OPEN")
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AccessReview(Base):
    __tablename__ = "access_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("access_review_campaigns.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("access_grants.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)  # PENDING | RETAINED | RESTRICTED | REVOKED
    unused: Mapped[bool] = mapped_column(Boolean, default=False)
    due_at: Mapped[datetime] = mapped_column(TS)
    overdue_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ---------------------------------------------------------------- AI agents
class AiAgent(Base, TimestampMixin):
    __tablename__ = "ai_agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    api_key_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")  # ACTIVE | SUSPENDED
    risk_score: Mapped[int] = mapped_column(Integer, default=20)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(TS)

    owner: Mapped[User] = relationship(lazy="joined")
    permissions: Mapped[list[AgentPermission]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class AgentPermission(Base):
    __tablename__ = "agent_permissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("ai_agents.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    permissions: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    # Set when the permission is cut from the dependency graph; the gateway then denies every call.
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("agent_id", "resource_id", name="uq_agent_resource"),)


# ---------------------------------------------------------------- dependency graph
class ResourceDependency(Base, TimestampMixin):
    """A simulated service link: something that consumes `resource_id` (the upstream model, dataset or database).

    Either an internal API / service endpoint (name + endpoint, no registry entry) or another registered resource
    (`dependent_resource_id`), e.g. a training dataset feeding a model. Used by the access dependency graph to show
    the blast radius of a revocation. Suspending a link marks the API as cut off from the upstream resource."""

    __tablename__ = "resource_dependencies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    dependent_resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))  # API | FEED | TRAINING_DATA
    endpoint: Mapped[str | None] = mapped_column(String(160))
    criticality: Mapped[str] = mapped_column(String(10), default="MEDIUM")  # LOW | MEDIUM | HIGH | CRITICAL
    description: Mapped[str | None] = mapped_column(Text)
    suspended_at: Mapped[datetime | None] = mapped_column(TS)
    suspended_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    suspend_reason: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- notifications
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(10), default="INFO")
    read_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


# ---------------------------------------------------------------- internal messaging
class Conversation(Base):
    """A private 1:1 chat between two employees/managers. pair_key keeps one conversation per pair."""

    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pair_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_message_at: Mapped[datetime | None] = mapped_column(TS, index=True)


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    last_read_at: Mapped[datetime | None] = mapped_column(TS)
    joined_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_chat_messages_conv_created", "conversation_id", "created_at"),)


class MockRecord(Base):
    """Synthetic rows behind the simulated model/dataset/database workspaces (never real data).

    table_name "_meta" holds editable model metadata and admin settings for a resource."""

    __tablename__ = "mock_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    table_name: Mapped[str] = mapped_column(String(48))
    record_key: Mapped[str] = mapped_column(String(48))
    position: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (Index("ix_mock_records_res_table", "resource_id", "table_name"),
                      UniqueConstraint("resource_id", "table_name", "record_key", name="uq_mock_record_key"))
