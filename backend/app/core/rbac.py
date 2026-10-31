"""Role -> permission mapping. The backend is the only source of truth for authorization."""

REQUESTER = "REQUESTER"
MANAGER = "MANAGER"
RISK_REVIEWER = "RISK_REVIEWER"
RESOURCE_OWNER = "RESOURCE_OWNER"
SECURITY_ADMIN = "SECURITY_ADMIN"
ALL_ROLES = [REQUESTER, MANAGER, RISK_REVIEWER, RESOURCE_OWNER, SECURITY_ADMIN]

ROLE_DESCRIPTIONS = {
    REQUESTER: "Employee: requests access, tracks own requests, grants and emergency access.",
    MANAGER: "Manager: first approval for the team's requests, team analytics and access reviews.",
    RISK_REVIEWER: "Security review: final approval of requests after the manager, using the AI risk assessment.",
    RESOURCE_OWNER: "Optional: resource-level administration (not used in the default setup).",
    SECURITY_ADMIN: "Security Manager: alerts, emergency access, drift, audit, AI agents, policies and users.",
}

_BASE = {
    "requests:create", "requests:read_own", "grants:read_own", "emergency:request",
    "resources:read", "notifications:read", "gateway:use", "profile:manage",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    REQUESTER: set(_BASE),
    MANAGER: _BASE | {
        "approvals:read", "approvals:act", "employees:read_team", "analytics:read", "leaderboard:read",
        "reviews:read", "reviews:act", "reviews:initiate", "drift:read", "grants:read_team", "grants:revoke_team", "dashboard:read",
    },
    RISK_REVIEWER: _BASE | {
        "approvals:read", "approvals:act", "risk:read", "alerts:read", "alerts:manage", "requests:read_all",
        "drift:read", "audit:read", "dashboard:read", "agents:read", "emergency:monitor", "grants:read_all",
    },
    RESOURCE_OWNER: _BASE | {
        "approvals:read", "approvals:act", "resources:manage_own", "grants:revoke_own_resource",
        "grants:read_resource", "drift:read", "drift:act", "dashboard:read", "policies:read",
    },
    SECURITY_ADMIN: _BASE | {
        "approvals:read", "risk:read", "alerts:read", "alerts:manage", "requests:read_all", "employees:read_all",
        "employees:read_team", "analytics:read", "leaderboard:read", "users:manage", "policies:read",
        "policies:manage", "resources:manage_all", "grants:read_all", "grants:revoke_any", "drift:read",
        "drift:act", "drift:scan", "emergency:monitor", "emergency:revoke", "emergency:review", "audit:read",
        "audit:verify", "audit:export", "agents:read", "agents:manage", "reviews:read", "reviews:initiate",
        "dashboard:read", "settings:manage",
    },
}


def permissions_for(roles: list[str]) -> set[str]:
    perms: set[str] = set()
    for r in roles:
        perms |= ROLE_PERMISSIONS.get(r, set())
    return perms
