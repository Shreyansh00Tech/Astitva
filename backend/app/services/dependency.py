"""Access dependency graph: who and what is affected if access to a resource is revoked.

The graph is built from live data:
  * users     - ACTIVE access grants on the resource (and grants revoked in the last 24 hours, shown as REVOKED)
  * AI agents - agent permissions on the resource (active, or revoked in the last 24 hours)
  * APIs      - simulated service links (ResourceDependency) that consume the resource
  * indirect  - when a dependent is itself a registered resource (e.g. a dataset that trains a model), its own
                users, agents and APIs are shown one level further out as INDIRECTLY affected.

Visibility: the Security Manager sees everyone. A Manager sees their own team by name; people outside the team are
folded into one "other teams" node per resource so no names leak. Only those two roles can call this (graph:read).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.context import Actor
from app.core.rbac import SECURITY_ADMIN
from app.models import (
    AccessGrant,
    AccessToken,
    AgentPermission,
    AiAgent,
    EmergencySession,
    Resource,
    ResourceDependency,
    User,
    utcnow,
)
from app.services import audit
from app.services.grants import revoke_grant
from app.services.notify import notify, notify_role

RECENT = timedelta(hours=24)
MAX_DEPTH = 2


@dataclass
class Viewer:
    user_id: str
    full_view: bool  # Security Manager: every name is visible
    can_revoke_agents: bool
    can_revoke_services: bool
    can_manage_grant: Callable[[AccessGrant], bool]


@dataclass
class _Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)

    def node(self, nid: str, **data) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            n = self.nodes[nid] = {"id": nid, **data}
        elif n["impact"] == "DIRECT" and data.get("impact") == "INDIRECT":
            pass  # already directly affected: its direct link decides status and what can be revoked
        else:
            if data.get("impact") == "DIRECT" and n["impact"] == "INDIRECT":
                n.update({k: v for k, v in data.items() if k not in ("id",)})  # direct link replaces the indirect view
                return n
            # Same level reached twice (e.g. two grants): an active link wins over a revoked one.
            if data.get("status") == "ACTIVE":
                n["status"] = "ACTIVE"
            n["can_revoke"] = n.get("can_revoke") or data.get("can_revoke", False)
        return n

    def edge(self, source: str, target: str, **data):
        self.edges.append({"id": f"{source}->{target}#{len(self.edges)}", "source": source, "target": target, **data})


def _status_of_grant(g: AccessGrant) -> str:
    return "ACTIVE" if g.status == "ACTIVE" else "REVOKED"


def build_graph(db: Session, resource: Resource, viewer: Viewer) -> dict:
    now = utcnow()
    since = now - RECENT
    team_ids = set(db.execute(select(User.id).where(User.manager_id == viewer.user_id)).scalars())
    g = _Graph()
    root = f"res:{resource.id}"
    g.node(root, type="RESOURCE", label=resource.name, sub=f"{resource.code} · {resource.sensitivity.title()}",
           sensitivity=resource.sensitivity, resource_type=resource.resource_type, status="ACTIVE", depth=0,
           impact="ROOT", resource_id=resource.id)
    tokens = db.execute(select(AccessToken.grant_id).where(AccessToken.resource_id == resource.id,
                                                           AccessToken.revoked_at.is_(None))).scalars().all()
    live_tokens: dict[str, int] = {}
    for gid in tokens:
        live_tokens[gid] = live_tokens.get(gid, 0) + 1

    visited: set[str] = set()

    def walk(res: Resource, parent: str, depth: int, link_status: str):
        if res.id in visited or depth > MAX_DEPTH:
            return
        visited.add(res.id)
        impact = "DIRECT" if depth == 1 else "INDIRECT"
        # ---- users holding grants
        grants = db.execute(
            select(AccessGrant).where(AccessGrant.resource_id == res.id,
                                      or_(AccessGrant.status == "ACTIVE",
                                          (AccessGrant.status == "REVOKED") & (AccessGrant.revoked_at >= since)))
            .order_by(AccessGrant.granted_at.desc())
        ).scalars().all()
        hidden: dict[str, list[AccessGrant]] = {}
        for gr in grants:
            if not viewer.full_view and gr.user_id not in team_ids:
                hidden.setdefault(gr.status, []).append(gr)
                continue
            st = _status_of_grant(gr) if link_status == "ACTIVE" else "DEGRADED"
            if gr.status != "ACTIVE":
                st = "REVOKED"
            u = gr.user
            nid = f"user:{u.id}"
            g.node(nid, type="USER", label=u.full_name, sub=u.designation or (u.department.name if u.department else ""),
                   status=st, depth=depth, impact=impact, user_id=u.id,
                   can_revoke=depth == 1 and gr.status == "ACTIVE" and viewer.can_manage_grant(gr))
            g.edge(parent, nid, kind="GRANT", status="REVOKED" if gr.status != "ACTIVE" else st,
                   permissions=gr.permissions, emergency=gr.is_emergency, grant_id=gr.id if depth == 1 else None,
                   expires_at=gr.expires_at, tokens=live_tokens.get(gr.id, 0) if depth == 1 else 0,
                   revoked_at=gr.revoked_at, revoke_reason=gr.revoke_reason)
        for status, items in hidden.items():
            people = {x.user_id for x in items}
            nid = f"group:{res.id}:{status}"
            st = "REVOKED" if status != "ACTIVE" else ("ACTIVE" if link_status == "ACTIVE" else "DEGRADED")
            g.node(nid, type="USER_GROUP", label=f"{len(people)} user{'s' if len(people) != 1 else ''} in other teams",
                   sub="Names visible to the Security Manager", status=st, depth=depth, impact=impact, count=len(people),
                   can_revoke=False)
            g.edge(parent, nid, kind="GRANT", status=st, permissions=sorted({p for x in items for p in x.permissions}))
        # ---- AI agents
        perms = db.execute(
            select(AgentPermission).where(AgentPermission.resource_id == res.id,
                                          or_(AgentPermission.revoked_at.is_(None), AgentPermission.revoked_at >= since))
        ).scalars().all()
        for p in perms:
            agent = db.get(AiAgent, p.agent_id)
            if not agent:
                continue
            expired = p.expires_at is not None and p.expires_at <= now
            if expired and p.revoked_at is None:
                continue
            if p.revoked_at is not None:
                st = "REVOKED"
            elif agent.status != "ACTIVE":
                st = "SUSPENDED"
            else:
                st = "ACTIVE" if link_status == "ACTIVE" else "DEGRADED"
            nid = f"agent:{agent.id}"
            g.node(nid, type="AGENT", label=agent.name, sub=agent.code, status=st, depth=depth, impact=impact,
                   agent_id=agent.id, can_revoke=depth == 1 and p.revoked_at is None and viewer.can_revoke_agents)
            g.edge(parent, nid, kind="AGENT_PERMISSION", status=st, permissions=p.permissions,
                   expires_at=p.expires_at, revoked_at=p.revoked_at)
        # ---- APIs and downstream resources
        for d in db.execute(select(ResourceDependency).where(ResourceDependency.resource_id == res.id)
                            .order_by(ResourceDependency.name)).scalars():
            if d.suspended_at is not None:
                st = "SUSPENDED"
            else:
                st = "ACTIVE" if link_status == "ACTIVE" else "DEGRADED"
            if d.dependent_resource_id:
                child = db.get(Resource, d.dependent_resource_id)
                if not child:
                    continue
                nid = f"res:{child.id}"
                if nid == root:
                    continue
                g.node(nid, type="API" if child.resource_type == "API" else "RESOURCE", label=child.name,
                       sub=f"{child.code} · {d.kind.replace('_', ' ').title()}", status=st, depth=depth, impact=impact,
                       resource_id=child.id, resource_type=child.resource_type, sensitivity=child.sensitivity,
                       criticality=d.criticality, dependency_id=d.id,
                       can_revoke=depth == 1 and d.suspended_at is None and viewer.can_revoke_services,
                       can_restore=depth == 1 and d.suspended_at is not None and viewer.can_revoke_services)
                g.edge(parent, nid, kind=d.kind, status=st, dependency_id=d.id, label=d.name)
                walk(child, nid, depth + 1, "ACTIVE" if st == "ACTIVE" else "DEGRADED")
            else:
                nid = f"api:{d.id}"
                g.node(nid, type="API", label=d.name, sub=d.endpoint or d.kind, status=st, depth=depth, impact=impact,
                       criticality=d.criticality, dependency_id=d.id, description=d.description,
                       can_revoke=depth == 1 and d.suspended_at is None and viewer.can_revoke_services,
                       can_restore=depth == 1 and d.suspended_at is not None and viewer.can_revoke_services)
                g.edge(parent, nid, kind="API", status=st, dependency_id=d.id)

    walk(resource, root, 1, "ACTIVE")

    nodes = list(g.nodes.values())
    direct = [n for n in nodes if n.get("impact") == "DIRECT" and n["status"] == "ACTIVE"]
    indirect = [n for n in nodes if n.get("impact") == "INDIRECT" and n["status"] == "ACTIVE"]

    def count(items, *types):
        return sum(n.get("count", 1) for n in items if n["type"] in types)

    direct_grant_edges = [e for e in g.edges if e["source"] == root and e["kind"] == "GRANT" and e["status"] == "ACTIVE"]
    summary = {
        "users": count(direct, "USER", "USER_GROUP"),
        "agents": count(direct, "AGENT"),
        "apis": count(direct, "API", "RESOURCE"),
        "indirect_users": count(indirect, "USER", "USER_GROUP"),
        "indirect_agents": count(indirect, "AGENT"),
        "indirect_apis": count(indirect, "API", "RESOURCE"),
        "active_tokens": sum(e.get("tokens", 0) for e in direct_grant_edges),
        "emergency_sessions": sum(1 for e in direct_grant_edges if e.get("emergency")),
        "revoked_recently": sum(1 for n in nodes if n["status"] in ("REVOKED", "SUSPENDED") and n.get("impact") == "DIRECT"),
        "revocable": sum(1 for n in nodes if n.get("can_revoke")),
    }
    return {
        "resource": {"id": resource.id, "code": resource.code, "name": resource.name, "type": resource.resource_type,
                     "sensitivity": resource.sensitivity, "owner": resource.owner.full_name if resource.owner else None},
        "viewer": {"full_view": viewer.full_view, "can_revoke_agents": viewer.can_revoke_agents,
                   "can_revoke_services": viewer.can_revoke_services},
        "nodes": nodes,
        "edges": g.edges,
        "summary": summary,
        "generated_at": now,
        "simulated": True,
    }


class RevokeError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


def revoke_resource_access(db: Session, actor: Actor, resource: Resource, viewer: Viewer, *, reason: str,
                           users: bool = True, agents: bool = False, services: bool = False,
                           node_ids: list[str] | None = None) -> dict:
    """Cut access to a resource from the dependency graph. Every item is checked against the viewer's own rights:
    a Manager can only revoke their team's grants; agents and service links need the Security Manager.
    `node_ids` limits the action to selected graph nodes (user:<id>, agent:<id>, api:<dep id>, res:<id>)."""
    if (agents and not viewer.can_revoke_agents) or (services and not viewer.can_revoke_services):
        raise RevokeError("Only the Security Manager can revoke AI agents or API links.", 403)
    picked = set(node_ids or [])

    def wanted(nid: str) -> bool:
        return not picked or nid in picked

    now = utcnow()
    out = {"users": [], "grants": 0, "tokens": 0, "emergency_sessions": 0, "agents": [], "services": [], "skipped": 0}
    if users:
        for gr in db.execute(select(AccessGrant).where(AccessGrant.resource_id == resource.id,
                                                       AccessGrant.status == "ACTIVE")).scalars().all():
            if not wanted(f"user:{gr.user_id}"):
                continue
            if not viewer.can_manage_grant(gr):
                out["skipped"] += 1
                continue
            out["tokens"] += len(db.execute(select(AccessToken.id).where(AccessToken.grant_id == gr.id,
                                                                         AccessToken.revoked_at.is_(None))).all())
            if gr.is_emergency:
                es = db.execute(select(EmergencySession).where(EmergencySession.grant_id == gr.id,
                                                               EmergencySession.status == "ACTIVE")).scalar_one_or_none()
                if es:
                    es.status, es.ended_at, es.revoked_by_id = "REVOKED", now, actor.user.id
                    audit.record(db, actor, "BREAKGLASS_REVOKED", resource_id=resource.id, target_type="EMERGENCY_SESSION",
                                 target_id=es.ref, previous_state={"status": "ACTIVE"}, new_state={"status": "REVOKED"},
                                 reason=f"Dependency graph revocation: {reason}")
                    out["emergency_sessions"] += 1
            revoke_grant(db, actor, gr, f"Resource access revoked: {reason}")
            out["grants"] += 1
            if gr.user.full_name not in out["users"]:
                out["users"].append(gr.user.full_name)
    if agents:
        for p in db.execute(select(AgentPermission).where(AgentPermission.resource_id == resource.id,
                                                          AgentPermission.revoked_at.is_(None))).scalars().all():
            if not wanted(f"agent:{p.agent_id}"):
                continue
            agent = db.get(AiAgent, p.agent_id)
            p.revoked_at, p.revoked_by_id = now, actor.user.id
            audit.record(db, actor, "AGENT_PERMISSION_REVOKED", resource_id=resource.id, target_type="AGENT",
                         target_id=agent.code if agent else p.agent_id, previous_state={"permissions": p.permissions},
                         new_state={"permissions": []}, reason=reason)
            out["agents"].append(agent.name if agent else p.agent_id)
    if services:
        for d in db.execute(select(ResourceDependency).where(ResourceDependency.resource_id == resource.id,
                                                             ResourceDependency.suspended_at.is_(None))).scalars().all():
            nid = f"res:{d.dependent_resource_id}" if d.dependent_resource_id else f"api:{d.id}"
            if not wanted(nid):
                continue
            d.suspended_at, d.suspended_by_id, d.suspend_reason = now, actor.user.id, reason
            audit.record(db, actor, "SERVICE_LINK_SUSPENDED", resource_id=resource.id, target_type="SERVICE_LINK",
                         target_id=d.id, previous_state={"status": "ACTIVE"}, new_state={"status": "SUSPENDED", "name": d.name},
                         reason=reason)
            out["services"].append(d.name)
    total = out["grants"] + len(out["agents"]) + len(out["services"])
    if total == 0:
        raise RevokeError("Nothing to revoke that you are allowed to change.", 409)
    audit.record(db, actor, "RESOURCE_ACCESS_REVOKED", resource_id=resource.id, target_type="RESOURCE",
                 target_id=resource.code, previous_state=None,
                 new_state={"grants": out["grants"], "tokens": out["tokens"], "agents": out["agents"],
                            "services": out["services"], "emergency_sessions": out["emergency_sessions"]},
                 reason=reason)
    summary = (f"{actor.display_name} revoked access to {resource.name}: {out['grants']} grant(s), "
               f"{len(out['agents'])} agent(s), {len(out['services'])} API link(s). {reason}")
    if resource.owner_id and resource.owner_id != actor.user.id:
        notify(db, resource.owner_id, "ACCESS_REVOKED", f"Access cut: {resource.name}", summary,
               f"/dependency-graph?resource={resource.id}", "WARNING")
    if SECURITY_ADMIN not in (actor.user.role_names if actor.user else []):
        notify_role(db, SECURITY_ADMIN, "ACCESS_REVOKED", f"Manager revoked access: {resource.name}", summary,
                    f"/dependency-graph?resource={resource.id}", "INFO")
    return out


def restore_service_link(db: Session, actor: Actor, dep: ResourceDependency, reason: str) -> None:
    if dep.suspended_at is None:
        raise RevokeError("This API link is not suspended.", 409)
    dep.suspended_at = dep.suspended_by_id = dep.suspend_reason = None
    audit.record(db, actor, "SERVICE_LINK_RESTORED", resource_id=dep.resource_id, target_type="SERVICE_LINK",
                 target_id=dep.id, previous_state={"status": "SUSPENDED"}, new_state={"status": "ACTIVE", "name": dep.name},
                 reason=reason)
