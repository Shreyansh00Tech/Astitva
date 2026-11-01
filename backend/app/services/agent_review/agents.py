"""The review agents. Each one reads a narrow slice of simulated ASTITVA data and returns evidence-cited findings.

Every agent is deterministic code, so the same request always gets the same review and the tests can pin it. A
finding is a claim + points + the ids of the records that prove it. A claim without evidence is dropped by the
Challenger. The agents never read secrets, never call an external service and cannot change access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.catalog import PURPOSES, SENSITIVITY_RANK, purpose_label
from app.models import (
    AccessGrant,
    AccessRequest,
    ApprovalRecord,
    Resource,
    ResourceAccessEvent,
    ResourceDependency,
    RiskAssessment,
    User,
)
from app.services import mock_catalog, projects
from app.services.agent_review import policy_search

HISTORY_WINDOW_DAYS = 180
MODIFY = {"WRITE", "DELETE", "ADMIN"}
TICKET = re.compile(r"\b(?:[A-Z]{2,6})-\d{2,6}\b")
# Text that tries to steer a reviewer, a tool or a model. The request text is data, never an instruction.
INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above|earlier) (instructions|rules)|disregard (the |all )?(rules|policy|instructions)"
    r"|you are now|system prompt|act as (an? )?(admin|approver)|(auto[- ]?approve|approve this|approve immediately|"
    r"mark (this )?as (safe|low risk))|bypass (the )?(check|review|policy|approval)|set (the )?risk (score )?to"
    r"|risk score (is|should be) (0|zero|low))", re.I)
VAGUE = re.compile(r"\b(need(ed)? (it|access)|for (my )?work|asap|urgent(ly)?|please approve|as discussed|required)\b", re.I)
PURPOSE_WORDS = {
    "MODEL_TESTING": ["test", "testing", "validate", "validation", "evaluate", "evaluation", "benchmark", "holdout",
                      "accuracy", "precision", "recall", "drift", "regression"],
    "MODEL_TRAINING": ["train", "training", "retrain", "fine-tune", "finetune", "fit", "epoch", "feature", "dataset"],
    "ANALYTICS_REPORTING": ["report", "reporting", "dashboard", "analysis", "analyse", "analyze", "metrics", "kpi", "trend"],
    "FRAUD_INVESTIGATION": ["fraud", "case", "investigation", "investigate", "suspicious", "alert", "chargeback"],
    "COMPLIANCE_AUDIT": ["audit", "compliance", "evidence", "control", "sox", "review", "regulator"],
    "FEATURE_DEVELOPMENT": ["feature", "develop", "build", "implement", "sprint", "story", "release"],
    "FRONTEND_TESTING": ["ui", "frontend", "screen", "page", "test", "qa"],
    "DATA_MIGRATION": ["migrate", "migration", "move", "schema", "copy", "cutover"],
    "INCIDENT_RESPONSE": ["incident", "outage", "inc", "breach", "root cause", "rca", "sev"],
    "PAYROLL_PROCESSING": ["payroll", "salary", "payslip", "compensation", "month-end"],
    "CUSTOMER_SUPPORT": ["customer", "ticket", "support", "case", "complaint"],
    "SECURITY_REVIEW": ["security", "review", "vulnerability", "threat", "pentest", "access"],
}


@dataclass
class Finding:
    id: str
    claim: str
    points: int
    severity: str                      # good | info | warn | risk
    evidence: list[str]
    overlaps: list[str] = field(default_factory=list)          # rule factors that already count this fully
    partial_overlaps: list[str] = field(default_factory=list)  # rule factors that count part of it
    signal: str | None = None          # same signal found by two agents is counted once

    def out(self) -> dict:
        return {"id": self.id, "claim": self.claim, "points": self.points, "severity": self.severity,
                "evidence": self.evidence, "overlaps": self.overlaps, "partial_overlaps": self.partial_overlaps,
                "signal": self.signal}


@dataclass
class AgentResult:
    code: str
    name: str
    role: str
    reads: list[str]
    findings: list[Finding] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    stats: list[tuple[str, str]] = field(default_factory=list)
    suggest: dict = field(default_factory=dict)  # drop_permissions, max_hours
    extra: dict = field(default_factory=dict)

    @property
    def delta(self) -> int:
        return sum(f.points for f in self.findings)

    def verdict(self) -> str:
        scored = [f for f in self.findings if f.points]
        if not self.findings or (not scored and self.data_gaps and all(f.severity == "info" for f in self.findings)):
            return "NO_DATA" if self.data_gaps else "OK"
        if any(f.severity == "risk" and f.points > 0 for f in self.findings) or self.delta >= 8:
            return "RISK"
        if self.delta > 0:
            return "CAUTION"
        return "OK"

    def summary(self) -> str:
        top = sorted(self.findings, key=lambda f: -abs(f.points))
        if not top:
            return self.data_gaps[0] if self.data_gaps else "Nothing unusual found."
        f = top[0]
        return f.claim

    def out(self) -> dict:
        return {"code": self.code, "name": self.name, "role": self.role, "reads": self.reads,
                "verdict": self.verdict(), "delta": self.delta, "summary": self.summary(),
                "findings": [f.out() for f in self.findings], "data_gaps": self.data_gaps,
                "stats": [{"label": k, "value": v} for k, v in self.stats], "suggest": self.suggest, **self.extra}


@dataclass
class Context:
    """Facts loaded once and shared by all agents, all bounded at the moment the request was made."""
    req: AccessRequest
    user: User
    res: Resource
    ra: RiskAssessment
    as_of: datetime
    perms: list[str]
    project: object | None

    @property
    def rule_points(self) -> dict[str, int]:
        return {f["code"]: f["points"] for f in self.ra.factors or [] if f.get("available", True)}


def _ref(r: AccessRequest) -> str:
    return r.ref


def _gref(g: AccessGrant) -> str:
    return f"GRANT-{g.id[:8]}"


# ------------------------------------------------------------------------------------------------ 1. History
def history_agent(db: Session, c: Context) -> AgentResult:
    a = AgentResult("HISTORY", "History agent", "Learns from this person's earlier requests and how they used access.",
                    ["Own earlier requests and decisions", "Own grants and gateway use", "Team peers (counts only)"])
    since = c.as_of - timedelta(days=HISTORY_WINDOW_DAYS)
    past = db.execute(select(AccessRequest).where(
        AccessRequest.requester_id == c.user.id, AccessRequest.id != c.req.id,
        AccessRequest.created_at < c.as_of, AccessRequest.created_at >= since)
        .order_by(AccessRequest.created_at.desc())).scalars().all()
    grants = db.execute(select(AccessGrant).where(
        AccessGrant.user_id == c.user.id, AccessGrant.source == "REQUEST",
        AccessGrant.granted_at < c.as_of, AccessGrant.granted_at >= since)).scalars().all()
    decided = [r for r in past if r.status in ("APPROVED", "REJECTED")]
    narrowed_ids = set(db.execute(select(ApprovalRecord.request_id).where(
        ApprovalRecord.request_id.in_([r.id for r in past] or [""]), ApprovalRecord.action == "NARROW_SCOPE")).scalars())
    narrowed = [r for r in past if r.id in narrowed_ids]
    a.stats = [("Earlier requests (180 days)", str(len(past))), ("Approved", str(sum(r.status == "APPROVED" for r in past))),
               ("Narrowed by approvers", str(len(narrowed))), ("Grants issued", str(len(grants)))]

    if not past and not grants:
        a.data_gaps.append("No earlier requests or grants for this person in 180 days, so there is no track record "
                           "to learn from. No points added.")
    if len(past) >= 2 and len(narrowed) / len(past) >= 0.5:
        a.findings.append(Finding("H1", f"Often asks for more than needed: {len(narrowed)} of {len(past)} earlier "
                                        "requests were narrowed by an approver.", 5, "warn",
                                  [_ref(r) for r in narrowed[:4]], signal="OVER_ASKING"))
    used_ids = set(db.execute(select(ResourceAccessEvent.grant_id).where(
        ResourceAccessEvent.grant_id.in_([g.id for g in grants] or [""]),
        ResourceAccessEvent.outcome == "ALLOWED")).scalars())
    settled = [g for g in grants if g.status != "ACTIVE" or (c.as_of - g.granted_at) > timedelta(hours=24)]
    unused = [g for g in settled if not g.last_used_at and g.id not in used_ids]
    if len(unused) >= 2:
        a.findings.append(Finding("H2", f"{len(unused)} of {len(settled)} earlier grants were never used. "
                                        "Shorter access is enough.", 4, "warn", [_gref(g) for g in unused[:4]]))
        a.suggest["max_hours"] = min(c.req.approved_duration_hours, 24)
    revoked_here = [g for g in grants if g.resource_id == c.res.id and g.status == "REVOKED"
                    and g.revoked_by_id and g.revoked_by_id != c.user.id
                    and g.revoked_at and g.revoked_at >= c.as_of - timedelta(days=90)]
    if revoked_here:
        g = revoked_here[0]
        a.findings.append(Finding("H3", f"Access to {c.res.name} was revoked by someone else on "
                                        f"{g.revoked_at:%d %b}: “{(g.revoke_reason or 'no reason given')[:140]}”.",
                                  8, "risk", [_gref(x) for x in revoked_here[:3]]))
    clean_here = [g for g in grants if g.resource_id == c.res.id and g not in revoked_here
                  and (g.last_used_at or g.id in used_ids)]
    denied_here = db.scalar(select(ResourceAccessEvent.id).where(
        ResourceAccessEvent.user_id == c.user.id, ResourceAccessEvent.resource_id == c.res.id,
        ResourceAccessEvent.outcome == "DENIED", ResourceAccessEvent.occurred_at < c.as_of,
        ResourceAccessEvent.occurred_at >= c.as_of - timedelta(days=90)).limit(1))
    if len(clean_here) >= 2 and not revoked_here and not denied_here:
        a.findings.append(Finding("H4", f"Clean track record on this resource: {len(clean_here)} earlier grants used "
                                        "with no blocked calls and no revocation.", -4, "good",
                                  [_gref(g) for g in clean_here[:4]], overlaps=["PRIOR_ACCESS"]))
    if len(decided) >= 3 and all(r.status == "APPROVED" for r in decided) and not narrowed:
        a.findings.append(Finding("H5", f"All {len(decided)} earlier decided requests were approved as asked.", -3, "good",
                                  [_ref(r) for r in decided[:4]]))

    # Peer baseline: counts only, no names.
    if c.user.department_id:
        peers = set(db.execute(select(AccessGrant.user_id).join(User, User.id == AccessGrant.user_id).where(
            AccessGrant.resource_id == c.res.id, User.department_id == c.user.department_id,
            AccessGrant.user_id != c.user.id, AccessGrant.granted_at < c.as_of,
            AccessGrant.granted_at >= since)).scalars())
        dept = c.user.department.name if c.user.department else "the team"
        a.stats.append((f"Teammates who used it ({dept})", str(len(peers))))
        cross = bool(c.res.department_id and c.res.department_id != c.user.department_id)
        if peers:
            a.findings.append(Finding("H6", f"{len(peers)} teammate(s) in {dept} also had access to this resource.",
                                      -2, "good", [f"PEERS:{c.user.department.code if c.user.department else ''}:{len(peers)}"]))
        elif cross:
            a.findings.append(Finding("H6", f"No one else in {dept} has used {c.res.name} in 180 days.", 3, "warn",
                                      [f"PEERS:{c.user.department.code if c.user.department else ''}:0"],
                                      overlaps=["CROSS_DEPARTMENT", "DEPARTMENT_SCOPE"]))
    return a


# ------------------------------------------------------------------------------------------------ 2. Data impact
def data_impact_agent(db: Session, c: Context) -> AgentResult:
    a = AgentResult("DATA_IMPACT", "Data impact agent", "Checks what this access could see or break: personal fields "
                    "and downstream services.", ["Mock data catalog (column flags)", "Dependency graph links",
                                                 "Active grants on the resource (counts only)"])
    modify = sorted(set(c.perms) & MODIFY)
    tables = mock_catalog.tables_for(c.res.code)
    pii = [f"{t}.{col['name']}" for t in tables for col in mock_catalog.TABLES[t]["columns"] if col.get("pii")]
    consumers = db.execute(select(ResourceDependency).where(ResourceDependency.resource_id == c.res.id,
                                                            ResourceDependency.suspended_at.is_(None))).scalars().all()
    feeds = db.execute(select(ResourceDependency).where(ResourceDependency.dependent_resource_id == c.res.id)).scalars().all()
    holders = len(db.execute(select(AccessGrant.id).where(AccessGrant.resource_id == c.res.id,
                                                          AccessGrant.status == "ACTIVE")).all())
    a.stats = [("Tables", str(len(tables)) if tables else "—"), ("Personal fields", str(len(pii))),
               ("Downstream services", str(len(consumers))), ("Upstream feeds", str(len(feeds))),
               ("People with access now", str(holders or 0))]
    if pii:
        if modify:
            a.findings.append(Finding("D1", f"{', '.join(modify)} on data with {len(pii)} pseudonymous personal field(s) "
                                            f"({', '.join(p.split('.')[1] for p in pii[:3])}).", 5, "risk",
                                      [f"FIELD:{p}" for p in pii[:4]]))
            drop = [p for p in modify if p in ("DELETE", "ADMIN")]
            if drop:
                a.suggest["drop_permissions"] = drop
        else:
            a.findings.append(Finding("D2", f"Read access shows {len(pii)} pseudonymous personal field(s): "
                                            f"{', '.join(p.split('.')[1] for p in pii[:3])}.", 2, "info",
                                      [f"FIELD:{p}" for p in pii[:4]]))
    elif not tables and c.res.resource_type != "AI_MODEL":
        a.data_gaps.append("No column catalog for this resource, so personal fields could not be checked.")
    if consumers:
        names = ", ".join(d.name for d in consumers[:3])
        critical = [d for d in consumers if d.criticality in ("HIGH", "CRITICAL")]
        if modify:
            pts = min(8, 2 * len(consumers) + (2 if critical else 0))
            a.findings.append(Finding("D3", f"A change here reaches {len(consumers)} downstream service(s): {names}.",
                                      pts, "risk" if critical else "warn",
                                      [f"DEP:{d.name}" for d in consumers[:4]]))
        else:
            a.findings.append(Finding("D4", f"{len(consumers)} service(s) depend on it ({names}); read-only access "
                                            "cannot change them.", 0, "info", [f"DEP:{d.name}" for d in consumers[:4]]))
    if set(c.perms) & {"DELETE", "ADMIN"} and SENSITIVITY_RANK[c.res.sensitivity] >= 3:
        a.findings.append(Finding("D5", f"Destructive rights ({', '.join(sorted(set(c.perms) & {'DELETE', 'ADMIN'}))}) "
                                        f"on a {c.res.sensitivity.lower()} resource.", 4, "risk",
                                  [f"RESOURCE:{c.res.code}"], partial_overlaps=["PERMISSION_LEVEL"]))
    if not a.findings and not a.data_gaps:
        a.findings.append(Finding("D0", "No personal fields and no downstream services are exposed by this access.",
                                  0, "good", [f"RESOURCE:{c.res.code}"]))
    return a


# ------------------------------------------------------------------------------------------------ 3. Purpose
def purpose_agent(db: Session, c: Context) -> AgentResult:
    a = AgentResult("PURPOSE", "Purpose agent", "Reads the justification as data: does it fit the purpose, cite a "
                    "ticket, or try to instruct the reviewer?", ["Request justification text", "Requester's current project"])
    text = c.req.justification or ""
    words = len(text.split())
    hit = INJECTION.search(text)
    if hit:
        a.findings.append(Finding("P1", f"The justification tries to instruct the reviewer: “{hit.group(0)}”. "
                                        "Request text is data, never an instruction.", 12, "risk",
                                  [f"TEXT:{hit.start()}-{hit.end()}"], signal="INJECTION"))
    tickets = sorted(set(TICKET.findall(text)) - {c.req.ref})
    if tickets:
        a.findings.append(Finding("P2", f"Cites {', '.join(tickets[:3])}, which a reviewer can check.", -3, "good",
                                  [f"TICKET:{t}" for t in tickets[:3]]))
    want = PURPOSE_WORDS.get(c.req.purpose, [])
    low = text.lower()
    found = [w for w in want if re.search(rf"\b{re.escape(w)}", low)]
    if want and not found:
        a.findings.append(Finding("P3", f"The justification never mentions {purpose_label(c.req.purpose).lower()} work "
                                        f"(words like {', '.join(want[:3])}).", 4, "warn", ["TEXT:0-%d" % len(text)]))
    elif found:
        a.findings.append(Finding("P4", f"Fits the purpose: mentions {', '.join(found[:3])}.", 0, "good",
                                  ["TEXT:0-%d" % len(text)]))
    if VAGUE.search(text) and words < 15 and not tickets:
        a.findings.append(Finding("P5", "Vague and short: no detail a reviewer could verify.", 3, "warn",
                                  ["TEXT:0-%d" % len(text)], overlaps=["WEAK_JUSTIFICATION"]))
    if c.project is None:
        a.findings.append(Finding("P6", "Not on an active project, so there is no project end date to time-box this "
                                        "access.", 3, "warn", [f"USER:{c.user.employee_id or c.user.id[:8]}"]))
    else:
        p = c.project
        ends = c.as_of + timedelta(hours=c.req.approved_duration_hours)
        if p.end_date and ends > p.end_date:
            a.findings.append(Finding("P7", f"Asks beyond the end of {p.name} ({p.end_date:%d %b}); the grant will be "
                                            "capped at the project end anyway.", 0, "info", [f"PROJECT:{p.code}"]))
        if p.name.lower() in low or (p.code and p.code.lower() in low):
            a.findings.append(Finding("P8", f"Names the requester's current project ({p.name}).", -2, "good",
                                      [f"PROJECT:{p.code}"]))
    a.stats = [("Words", str(words)), ("Tickets cited", str(len(tickets))),
               ("Current project", c.project.name if c.project else "None")]
    return a


# ------------------------------------------------------------------------------------------------ 4. Policy
OVERLAPS = {"NX-POL-302": ["LONG_DURATION"], "NX-POL-102": ["EXCESSIVE_PERMISSIONS"],
            "NX-POL-701": ["EXCESSIVE_PERMISSIONS"], "NX-POL-401": ["CROSS_DEPARTMENT", "DEPARTMENT_SCOPE"]}
PARTIAL = {"NX-POL-201": ["EXCESSIVE_PERMISSIONS"], "NX-POL-501": ["EXCESSIVE_PERMISSIONS"],
           "NX-POL-301": ["PERMISSION_LEVEL"]}


def policy_agent(db: Session, c: Context) -> AgentResult:
    a = AgentResult("POLICY", "Policy agent (search)", "Searches the Nexora policy handbook and earlier decisions on "
                    "the same resource and purpose.", ["Policy handbook (12 simulated clauses)",
                                                       "Closed requests on this resource (outcomes only)"])
    text = c.req.justification or ""
    pii = sum(1 for t in mock_catalog.tables_for(c.res.code) for col in mock_catalog.TABLES[t]["columns"] if col.get("pii"))
    ctx = {"sensitivity": c.res.sensitivity, "perms": c.perms, "purpose": c.req.purpose,
           "hours": c.req.approved_duration_hours, "pii_fields": pii, "tickets": sorted(set(TICKET.findall(text)) - {c.req.ref}),
           "project": c.project.name if c.project else None, "injection": bool(INJECTION.search(text)),
           "cross_dept": bool(c.res.department_id and c.res.department_id != c.user.department_id)}
    query = (f"{c.res.sensitivity} {c.res.resource_type.replace('_', ' ')} {c.res.name} {' '.join(c.perms)} "
             f"{purpose_label(c.req.purpose)} {text[:400]}")
    hits = policy_search.search(query, ctx, top_k=4)
    shown = {h["id"] for h in hits}
    for clause in policy_search.CORPUS:  # an applicable clause is always cited, even if it ranked low
        if clause.applies(ctx) and clause.points and clause.id not in shown:
            hits += [h for h in policy_search.search(clause.title + " " + clause.text, ctx, top_k=len(policy_search.CORPUS))
                     if h["id"] == clause.id]
            shown.add(clause.id)
    for h in hits:
        if h["applies"] and h["points"]:
            a.findings.append(Finding(f"C-{h['id'][-3:]}", f"{h['id']} · {h['title']}: {h['suggestion']}", h["points"],
                                      "risk" if h["points"] >= 6 else "warn", [h["id"]],
                                      overlaps=OVERLAPS.get(h["id"], []), partial_overlaps=PARTIAL.get(h["id"], []),
                                      signal="INJECTION" if h["id"] == "NX-POL-601" else None))
    a.extra["retrieval"] = {"method": "BM25 + structured match, fused with RRF (k=60)", "query": query[:240], "hits": hits}

    prec = db.execute(select(AccessRequest).where(
        AccessRequest.resource_id == c.res.id, AccessRequest.purpose == c.req.purpose, AccessRequest.id != c.req.id,
        AccessRequest.created_at < c.as_of, AccessRequest.status.in_(["APPROVED", "REJECTED"]))
        .order_by(AccessRequest.created_at.desc()).limit(20)).scalars().all()
    narrowed_ids = set(db.execute(select(ApprovalRecord.request_id).where(
        ApprovalRecord.request_id.in_([r.id for r in prec] or [""]), ApprovalRecord.action == "NARROW_SCOPE")).scalars())
    as_asked = [r for r in prec if r.status == "APPROVED" and r.id not in narrowed_ids]
    cut = [r for r in prec if r.status == "REJECTED" or r.id in narrowed_ids]
    a.stats = [("Clauses searched", str(len(policy_search.CORPUS))), ("Clauses that apply", str(len(a.findings))),
               ("Similar past decisions", str(len(prec)))]
    if len(prec) < 2:
        a.data_gaps.append(f"Fewer than 2 earlier decisions on {c.res.name} for {purpose_label(c.req.purpose).lower()}, "
                           "so there is no precedent to compare with.")
    elif len(cut) * 2 >= len(prec):
        a.findings.append(Finding("PR1", f"Precedent: {len(cut)} of {len(prec)} similar requests were narrowed or "
                                         "rejected.", 3, "warn", [r.ref for r in cut[:4]], signal="OVER_ASKING"))
    elif len(as_asked) >= 2:
        a.findings.append(Finding("PR2", f"Precedent: {len(as_asked)} of {len(prec)} similar requests were approved as "
                                         "asked.", -3, "good", [r.ref for r in as_asked[:4]]))
    if not any(f.id.startswith("C-") for f in a.findings):
        a.findings.append(Finding("C0", "No handbook clause is broken by this request.", 0, "good",
                                  [h["id"] for h in hits[:2]]))
    return a


# ------------------------------------------------------------------------------------------------ 5. Challenger
def challenger_agent(c: Context, agents: list[AgentResult], max_up: int, max_down: int) -> AgentResult:
    """Second opinion on the other agents: removes claims without evidence, signals the rule engine already counts,
    and the same signal counted twice. Then caps the total so the agents can never outweigh the rule engine."""
    a = AgentResult("CHALLENGER", "Challenger agent", "Questions the other agents: no evidence, double counting or "
                    "overreach gets removed.", ["Other agents' findings", "Rule engine factors"])
    rule = c.rule_points
    adjustments = []

    def adjust(agent: AgentResult, f: Finding, new: int, why: str):
        if new == f.points:
            return
        adjustments.append({"agent": agent.code, "finding": f.id, "from": f.points, "to": new, "reason": why})
        a.findings.append(Finding(f"X{len(adjustments)}", f"{agent.name}: {why}", new - f.points, "info",
                                  [f"{agent.code}:{f.id}"]))

    best: dict[str, tuple[int, AgentResult, Finding]] = {}
    for ag in agents:
        for f in ag.findings:
            if not f.evidence:
                adjust(ag, f, 0, f"“{f.claim[:60]}” has no evidence, so it is not counted.")
                continue
            hit = [code for code in f.overlaps if rule.get(code)]
            if hit and f.points > 0:
                adjust(ag, f, 0, f"already counted by the rule engine ({hit[0].replace('_', ' ').lower()} "
                                 f"{rule[hit[0]]:+d}), removed.")
                continue
            if hit and f.points < 0 and rule.get(hit[0], 0) < 0:
                adjust(ag, f, 0, f"the rule engine already gives this credit ({hit[0].replace('_', ' ').lower()}), removed.")
                continue
            part = [code for code in f.partial_overlaps if rule.get(code)]
            if part and f.points > 1:
                adjust(ag, f, f.points // 2, f"partly counted by the rule engine ({part[0].replace('_', ' ').lower()}), halved.")
            if f.signal:
                eff = next((x["to"] for x in adjustments if x["agent"] == ag.code and x["finding"] == f.id), f.points)
                prev = best.get(f.signal)
                if prev is None or eff > prev[0]:
                    if prev:
                        adjust(prev[1], prev[2], 0, f"same signal also found by {ag.name}, counted once.")
                    best[f.signal] = (eff, ag, f)
                else:
                    adjust(ag, f, 0, f"same signal also found by {prev[1].name}, counted once.")

    raw = sum(ag.delta for ag in agents) + a.delta
    if raw > max_up:
        a.findings.append(Finding("CAP", f"The agents together may add at most +{max_up}; capped from +{raw}.",
                                  max_up - raw, "info", ["CAP:agents"]))
    elif raw < -max_down:
        a.findings.append(Finding("CAP", f"The agents together may lower the score by at most {max_down}; capped from "
                                         f"{raw}.", -max_down - raw, "info", ["CAP:agents"]))
    gaps = sum(1 for ag in agents if ag.verdict() == "NO_DATA" or ag.data_gaps)
    evidence = sum(1 for ag in agents for f in ag.findings if f.evidence and f.points)
    confidence = "LOW" if gaps >= 3 or evidence == 0 else "HIGH" if gaps <= 1 and evidence >= 3 else "MEDIUM"
    a.extra["adjustments"] = adjustments
    a.extra["confidence"] = confidence
    a.stats = [("Findings checked", str(sum(len(ag.findings) for ag in agents))), ("Adjusted", str(len(adjustments))),
               ("Confidence", confidence.title())]
    if not a.findings:
        a.findings.append(Finding("X0", "Every finding has evidence and nothing is counted twice.", 0, "good",
                                  [f"{ag.code}" for ag in agents]))
    return a


def challenger_verdict(a: AgentResult) -> str:
    return "ADJUSTED" if a.extra.get("adjustments") or any(f.id == "CAP" for f in a.findings) else "AGREES"


def least_privilege(c: Context) -> tuple[list[str], int]:
    need = PURPOSES.get(c.req.purpose, (None, ["READ"]))[1]
    return [p for p in c.perms if p in need] or c.perms[:1], c.req.approved_duration_hours
