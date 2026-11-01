"""Seed the simulated Nexora Technologies environment.

    python -m app.seed            # seed if empty
    python -m app.seed --reset    # drop & recreate all data
    python -m app.seed --reset --clean   # only the 5 people, resources and policies: no grants or requests

Every person, credential, dataset and system here is fictional.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta

import pyotp
from sqlalchemy import select, text

from app.core.dependency_catalog import DEFAULT_DEPENDENCIES
from app.core.context import SYSTEM, Actor
from app.core.db import Base, SessionLocal, engine
from app.core.rbac import ALL_ROLES, MANAGER, REQUESTER, RESOURCE_OWNER, RISK_REVIEWER, ROLE_DESCRIPTIONS, SECURITY_ADMIN
from app.models import (
    AccessGrant,
    AccessRequest,
    AccessReview,
    AccessReviewCampaign,
    AgentPermission,
    AiAgent,
    ApprovalRecord,
    Department,
    EmergencySession,
    MfaCredential,
    PermissionBaseline,
    Policy,
    Project,
    ProjectMember,
    Resource,
    ResourceAccessEvent,
    ResourceDependency,
    Role,
    SecurityAlert,
    Task,
    TaskEvent,
    User,
    utcnow,
)
from app.security import crypto
from app.services import audit, drift, recert, risk, workflow
from app.services.grants import issue_token

DEMO_PASSWORD = "Nexora@Demo2026"
DOMAIN = "nexora.example"
AGENT_KEYS = {
    "AGT-FIN-01": "agk_demo_finance_agent_key_0001",
    "AGT-SUP-01": "agk_demo_support_agent_key_0002",
    "AGT-DEV-01": "agk_demo_developer_agent_key_0003",
    "AGT-HR-01": "agk_demo_hr_assistant_key_0004",
}

R = random.Random(20261031)
NOW = utcnow()


def ago(days: float = 0, hours: float = 0) -> datetime:
    return NOW - timedelta(days=days, hours=hours)


def _day(days: int) -> datetime:
    """A calendar day relative to seeding, at 12:00 UTC (project milestones fall on whole days)."""
    return (NOW + timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)


FIRST = ["Aarav", "Ishita", "Kabir", "Diya", "Vivaan", "Anika", "Reyansh", "Myra", "Arnav", "Saanvi", "Dhruv", "Kiara",
         "Advait", "Tara", "Ayaan", "Nisha", "Karan", "Pooja", "Siddharth", "Riya", "Manav", "Sneha", "Yash", "Aditi",
         "Varun", "Meghna", "Rohit", "Lavanya", "Nikhil", "Shreya", "Harsh", "Zoya", "Om", "Ira", "Tanvi", "Gaurav",
         "Neel", "Esha", "Parth", "Mira"]
LAST = ["Agarwal", "Bhatt", "Chopra", "Dutta", "Ghosh", "Joshi", "Kulkarni", "Mehta", "Naidu", "Pandey", "Rao", "Saxena",
        "Shetty", "Sinha", "Thakur", "Trivedi", "Banerjee", "Chatterjee", "Das", "Fernandes", "Hegde", "Jain", "Kapoor",
        "Mishra", "Patil", "Qureshi", "Rastogi", "Sengupta", "Tiwari", "Vyas"]

DEPARTMENTS = [
    ("ENG", "Engineering", "Product engineering, platform and SRE."),
    ("FIN", "Finance", "Financial planning, risk and treasury."),
    ("HR", "Human Resources", "People operations, payroll and talent."),
    ("SEC", "Security", "Security operations, GRC and identity."),
    ("DS", "Data Science", "ML platform, models and analytics."),
]

# The organisation is deliberately small and easy to follow:
# 1 Manager, 3 Employees (the requesters) and 1 Security Manager.
# key, name, dept, designation, roles, manager key
DEMO_USERS = [
    ("admin", "Meera Krishnan", "SEC", "Security Manager", [SECURITY_ADMIN, RISK_REVIEWER], None),
    ("mgr", "Priya Desai", "ENG", "Team Manager", [MANAGER], None),
    ("eng_emp", "Rahul Sharma", "ENG", "Software Engineer", [], "mgr"),
    ("fin_emp", "Neha Gupta", "FIN", "Financial Analyst", [], "mgr"),
    ("hr_emp", "Kavya Reddy", "HR", "HR Generalist", [], "mgr"),
]
DEMO_EMAILS = {"admin": "admin", "mgr": "priya.desai", "eng_emp": "rahul.sharma", "fin_emp": "neha.gupta",
               "hr_emp": "kavya.reddy"}
EXTRA: dict = {}  # no background employees

RESOURCES = [
    # code, name, type, dept, sensitivity, perms, purposes, depts, max_h, breakglass, owner, backup, description
    ("RES-FIN-001", "Financial Risk Prediction Model", "AI_MODEL", "FIN", "RESTRICTED", ["READ", "EXECUTE", "WRITE", "ADMIN"],
     ["MODEL_TESTING", "MODEL_TRAINING", "ANALYTICS_REPORTING", "COMPLIANCE_AUDIT"], [], 72, False, "admin", None,
     "Gradient-boosted credit and market risk model used for quarterly exposure forecasts."),
    ("RES-FIN-002", "Customer Transaction Dataset", "DATASET", "FIN", "CONFIDENTIAL", ["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"],
     ["ANALYTICS_REPORTING", "FRAUD_INVESTIGATION", "COMPLIANCE_AUDIT", "MODEL_TRAINING"], [], 168, False, "admin", None,
     "Pseudonymised card and wallet transactions (synthetic) for analytics and fraud research."),
    ("RES-HR-001", "HR Employee Database", "DATABASE", "HR", "RESTRICTED", ["READ", "WRITE", "DELETE", "ADMIN"],
     ["PAYROLL_PROCESSING", "COMPLIANCE_AUDIT"], ["HR", "SEC"], 72, False, "admin", None,
     "Employee records, compensation bands and payroll (simulated personal data)."),
    ("RES-ENG-001", "Internal Analytics API", "API", "ENG", "INTERNAL", ["READ", "EXECUTE", "WRITE"],
     ["ANALYTICS_REPORTING", "FEATURE_DEVELOPMENT", "FRONTEND_TESTING"], [], 336, False, "admin", None,
     "Internal metrics and product analytics REST API."),
    ("RES-DS-001", "Fraud Detection Model", "AI_MODEL", "DS", "CRITICAL", ["READ", "EXECUTE", "WRITE", "ADMIN"],
     ["FRAUD_INVESTIGATION", "MODEL_TESTING", "MODEL_TRAINING", "INCIDENT_RESPONSE"], [], 48, True, "admin", None,
     "Real-time transaction fraud scoring model (production tier, simulated)."),
    ("RES-DS-002", "Product Recommendation Model", "AI_MODEL", "DS", "CONFIDENTIAL", ["READ", "EXECUTE", "WRITE"],
     ["MODEL_TESTING", "MODEL_TRAINING", "FEATURE_DEVELOPMENT", "ANALYTICS_REPORTING"], [], 168, False, "admin", None,
     "Collaborative-filtering recommender for the Nexora storefront."),
    ("RES-ENG-002", "Development Database", "DATABASE", "ENG", "INTERNAL", ["READ", "WRITE", "DELETE", "ADMIN"],
     ["FEATURE_DEVELOPMENT", "FRONTEND_TESTING", "DATA_MIGRATION", "INCIDENT_RESPONSE"], [], 336, True, "admin", None,
     "Shared PostgreSQL development cluster with masked data."),
    ("RES-DS-003", "Customer Support AI Dataset", "DATASET", "DS", "CONFIDENTIAL", ["READ", "EXECUTE", "WRITE", "DELETE"],
     ["CUSTOMER_SUPPORT", "MODEL_TRAINING", "ANALYTICS_REPORTING"], [], 168, False, "admin", None,
     "Redacted support transcripts used to fine-tune the support assistant."),
    ("RES-FIN-003", "Finance Ledger Database", "DATABASE", "FIN", "CRITICAL", ["READ", "WRITE", "DELETE", "ADMIN"],
     ["COMPLIANCE_AUDIT", "ANALYTICS_REPORTING", "INCIDENT_RESPONSE"], ["FIN", "SEC"], 24, True, "admin", None,
     "General ledger and payments reconciliation database (the 'Financial Database')."),
    ("RES-FIN-004", "Loan Approval Model", "AI_MODEL", "FIN", "RESTRICTED", ["READ", "EXECUTE", "WRITE", "ADMIN"],
     ["MODEL_TESTING", "COMPLIANCE_AUDIT", "ANALYTICS_REPORTING"], [], 72, False, "admin", None,
     "Retail loan pre-screening scorecard (simulated; never used for real lending decisions)."),
    ("RES-DS-004", "Fraud Investigation Dataset", "DATASET", "DS", "RESTRICTED", ["READ", "EXECUTE", "WRITE", "DELETE", "ADMIN"],
     ["FRAUD_INVESTIGATION", "INCIDENT_RESPONSE", "COMPLIANCE_AUDIT"], [], 72, False, "admin", None,
     "Synthetic fraud case files linking alerts, investigations and outcomes."),
]

BASELINE_PROFILES = {
    "ENG": {"RES-ENG-002": ["READ", "WRITE"], "RES-ENG-001": ["READ"]},
    "FIN": {"RES-FIN-002": ["READ"], "RES-FIN-003": ["READ"]},
    "DS": {"RES-DS-002": ["READ", "EXECUTE"], "RES-DS-003": ["READ"], "RES-ENG-001": ["READ"]},
    "HR": {"RES-HR-001": ["READ"]},
    "SEC": {"RES-ENG-001": ["READ"]},
}

PROJECTS = [
    ("PRJ-ATLAS", "Atlas Checkout Revamp", "ENG"), ("PRJ-HELIOS", "Helios Observability", "ENG"),
    ("PRJ-ORION", "Orion Mobile App", "ENG"), ("PRJ-LEDGER", "Ledger Reconciliation 2.0", "FIN"),
    ("PRJ-BASEL", "Basel IV Risk Reporting", "FIN"), ("PRJ-PULSE", "Pulse Employee Experience", "HR"),
    ("PRJ-SENTRY", "Zero Trust Rollout", "SEC"),
]
# Projects added after the random work history is generated, so the rest of the seed stays the same.
EXTRA_PROJECTS = [("PRJ-FALCON", "Project Falcon: Fraud Model Refresh", "FIN")]
FALCON_TASKS = ["Label Q3 chargeback cases", "Backtest fraud thresholds", "Review model drift report", "Prepare Falcon sign-off pack"]
# code -> (team name, start: days ago, submission: days from now, end: days from now). Simulated project calendar.
# Atlas and Falcon end 15 days after seeding, so access granted for them expires on that day too.
PROJECT_TIMELINE = {
    "PRJ-ATLAS": ("Checkout Platform Squad", 45, 10, 15), "PRJ-HELIOS": ("SRE & Observability", 90, 30, 40),
    "PRJ-ORION": ("Mobile Guild", 20, 50, 70), "PRJ-FALCON": ("Fraud Intelligence Team", 30, 10, 15),
    "PRJ-LEDGER": ("Finance Systems", 120, 25, 35), "PRJ-BASEL": ("Risk Reporting", 60, 55, 75),
    "PRJ-PULSE": ("People Experience", 40, 14, 20), "PRJ-SENTRY": ("Identity & Zero Trust", 100, 20, 30),
}
# Each employee's current project (the one ending soonest) plus the people who sit on that project's team.
CURRENT_PROJECT = {"eng_emp": "PRJ-ATLAS", "fin_emp": "PRJ-FALCON", "hr_emp": "PRJ-PULSE"}
PROJECT_STAFF = {"PRJ-ATLAS": [("mgr", "Project Manager")], "PRJ-FALCON": [("mgr", "Project Manager"), ("admin", "Security Reviewer")],
                 "PRJ-PULSE": [("mgr", "Project Manager")]}
TASK_VERBS = ["Implement", "Refactor", "Review", "Document", "Optimise", "Test", "Migrate", "Design", "Audit", "Automate"]
TASK_NOUNS = ["payment retries", "session handling", "dashboard filters", "ETL pipeline", "alert routing", "feature store",
              "model evaluation", "reconciliation report", "onboarding flow", "access logs", "API pagination",
              "cache layer", "variance analysis", "payroll export", "SLO dashboards", "retention cohort",
              "data quality checks", "quarterly forecast", "IAM policy", "threat model"]


class Seeder:
    def __init__(self, db):
        self.db = db
        self.audit_queue: list[tuple[datetime, Actor, str, dict]] = []
        self.users: dict[str, User] = {}
        self.res: dict[str, Resource] = {}
        self.depts: dict[str, Department] = {}

    def q(self, ts: datetime, actor: Actor, action: str, **kw):
        self.audit_queue.append((ts, actor, action, kw))

    def actor(self, u: User) -> Actor:
        return Actor(user=u, ip=f"10.20.{R.randint(1, 30)}.{R.randint(2, 250)}", user_agent="Mozilla/5.0 (simulated)")

    # -------------------------------------------------------------- org
    def org(self):
        db = self.db
        roles = {}
        for r in ALL_ROLES:
            roles[r] = Role(name=r, description=ROLE_DESCRIPTIONS[r])
            db.add(roles[r])
        for code, name, desc in DEPARTMENTS:
            self.depts[code] = Department(code=code, name=name, description=desc)
            db.add(self.depts[code])
        db.flush()
        pw = crypto.hash_password(DEMO_PASSWORD)
        n = 1
        for key, name, dept, desig, extra_roles, mgr in DEMO_USERS:
            u = User(employee_id=f"NX-{1000 + n:05d}", email=f"{DEMO_EMAILS[key]}@{DOMAIN}", full_name=name,
                     password_hash=pw, department_id=self.depts[dept].id, designation=desig,
                     manager_id=self.users[mgr].id if mgr else None, joined_at=ago(R.randint(400, 2400)),
                     email_verified=True, location=R.choice(["Bengaluru", "Pune", "Hyderabad", "Mumbai", "Gurugram"]),
                     phone=f"+91-90000-{10000 + n}", password_changed_at=ago(30))
            u.roles = [roles[REQUESTER]] + [roles[r] for r in extra_roles]
            db.add(u)
            db.flush()
            self.users[key] = u
            n += 1
        used = {u.full_name for u in self.users.values()}
        for dept, (count, mgr, titles) in EXTRA.items():
            for i in range(count):
                while True:
                    name = f"{R.choice(FIRST)} {R.choice(LAST)}"
                    if name not in used:
                        used.add(name)
                        break
                email = name.lower().replace(" ", ".") + f"@{DOMAIN}"
                u = User(employee_id=f"NX-{1000 + n:05d}", email=email, full_name=name, password_hash=pw,
                         department_id=self.depts[dept].id, designation=R.choice(titles), manager_id=self.users[mgr].id,
                         joined_at=ago(R.randint(60, 2000)), email_verified=True,
                         location=R.choice(["Bengaluru", "Pune", "Hyderabad", "Mumbai", "Gurugram", "Remote"]),
                         device_trust=R.choices(["TRUSTED", "UNKNOWN", "UNTRUSTED"], [85, 12, 3])[0])
                u.roles = [roles[REQUESTER]]
                db.add(u)
                db.flush()
                self.users[f"{dept.lower()}_{i}"] = u
                n += 1
        # Everyone signs in with password + email OTP (the dev mailbox shows the code in development).
        for u in self.users.values():
            self.q(u.joined_at, SYSTEM, "USER_PROVISIONED", target_type="USER", target_id=u.id,
                   new_state={"employee_id": u.employee_id, "department": next(c for c, d in self.depts.items() if d.id == u.department_id),
                              "roles": [r.name for r in u.roles]})
        db.flush()

    def resources(self):
        for code, name, typ, dept, sens, perms, purposes, depts, max_h, bg, owner, backup, desc in RESOURCES:
            r = Resource(code=code, name=name, resource_type=typ, department_id=self.depts[dept].id, sensitivity=sens,
                         available_permissions=perms, allowed_purposes=purposes, allowed_departments=depts,
                         max_duration_hours=max_h, breakglass_allowed=bg, owner_id=self.users[owner].id,
                         backup_owner_id=self.users[backup].id if backup else None, description=desc,
                         requires_risk_review=sens not in ("PUBLIC", "INTERNAL"))
            self.db.add(r)
            self.db.flush()
            self.res[code] = r
            self.q(ago(420), SYSTEM, "RESOURCE_REGISTERED", resource_id=r.id, target_type="RESOURCE", target_id=code,
                   new_state={"sensitivity": sens, "owner": self.users[owner].full_name})
        db = self.db
        # Simulated service links (APIs and data feeds) used by the access dependency graph.
        for up, down, name, kind, endpoint, crit, desc in DEFAULT_DEPENDENCIES:
            db.add(ResourceDependency(resource_id=self.res[up].id, dependent_resource_id=self.res[down].id if down else None,
                                      name=name, kind=kind, endpoint=endpoint, criticality=crit, description=desc))
        db.flush()
        admin = self.users["admin"]
        db.add_all([
            Policy(name="Manager and security approval by different people", policy_type="SOD", created_by_id=admin.id,
                   description="The same person can never give both the manager and the security approval.",
                   rules={"kind": "STAGE_CONFLICT", "pair": ["MANAGER", "RISK"]}),
            Policy(name="Security review must be outside requester's department", policy_type="SOD", created_by_id=admin.id,
                   description="Optional example policy (disabled).",
                   rules={"kind": "DEPARTMENT_CONFLICT", "stages": ["RISK"]}, enabled=False),
            Policy(name="HR data restricted to HR and Security", policy_type="ABAC", resource_id=self.res["RES-HR-001"].id,
                   created_by_id=admin.id, description="Enforced via resource allowed_departments.",
                   rules={"allowed_departments": ["HR", "SEC"]}),
            Policy(name="Finance ledger restricted to Finance and Security", policy_type="ABAC",
                   resource_id=self.res["RES-FIN-003"].id, created_by_id=admin.id,
                   description="Enforced via resource allowed_departments.", rules={"allowed_departments": ["FIN", "SEC"]}),
            Policy(name=workflow.ROUTING_POLICY_NAME, policy_type="GLOBAL", created_by_id=admin.id,
                   description="Risk-based routing on the rule-based score: low risk is auto-approved by policy (the manager "
                               "is informed), medium needs the Manager, high needs the Manager and the Security Manager. Sensitive "
                               "resources (Confidential, Restricted, Critical), WRITE/DELETE/ADMIN and unusual behaviour "
                               "always need a human.",
                   rules=dict(workflow.DEFAULT_ROUTING)),
            Policy(name="Break-glass maximum duration", policy_type="GLOBAL", created_by_id=admin.id,
                   description="Emergency sessions expire automatically.", rules={"max_minutes": 240, "default_minutes": 60}),
        ])
        db.flush()

    # -------------------------------------------------------------- work
    def work(self):
        db = self.db
        projects = {}
        for code, name, dept in PROJECTS:
            team, start, submit, end = PROJECT_TIMELINE[code]
            p = Project(code=code, name=name, department_id=self.depts[dept].id, description=f"{name} programme.",
                        team_name=team, start_date=_day(-start), submission_date=_day(submit), end_date=_day(end))
            db.add(p)
            db.flush()
            projects[code] = p
        by_dept: dict[str, list[Project]] = {}
        for code, _, dept in PROJECTS:
            by_dept.setdefault(dept, []).append(projects[code])
        task_n = 1
        staffed: set[tuple[str, str]] = set()
        dept_res = {"ENG": ["RES-ENG-002", "RES-ENG-001"], "FIN": ["RES-FIN-002", "RES-FIN-003"], "HR": ["RES-HR-001"],
                    "DS": ["RES-DS-002", "RES-DS-003"], "SEC": ["RES-ENG-001"]}
        for key, u in self.users.items():
            dept = next(c for c, d in self.depts.items() if d.id == u.department_id)
            if key in ("ceo",):
                continue
            ps = by_dept[dept]
            mine = R.sample(ps, k=min(len(ps), R.randint(1, 3))) if len(ps) > 1 else ps
            if key == "eng_emp":
                mine = ps  # Rahul: 3 projects
            for p in mine:
                role = R.choice(["Contributor", "Lead", "Reviewer"])
                staff = dict(PROJECT_STAFF.get(p.code, []))
                if key in staff:
                    role = staff[key]
                elif CURRENT_PROJECT.get(key) == p.code:
                    role = "Lead" if key == "fin_emp" else "Contributor"
                db.add(ProjectMember(project_id=p.id, user_id=u.id, role=role, joined_at=ago(R.randint(100, 200))))
                staffed.add((p.code, key))
            # Performance profile (hidden driver of simulated outcomes)
            talent = R.uniform(0.55, 1.0)
            n_tasks = int(R.randint(14, 30) * (0.6 + talent * 0.6))
            if key == "eng_emp":
                n_tasks, talent = 28, 0.9
            verifier = u.manager_id or (self.users["admin"].id if key != "admin" else None)
            for _ in range(n_tasks):
                p = R.choice(mine)
                created = ago(R.uniform(2, 175))
                due = created + timedelta(days=R.randint(3, 14))
                done = created < ago(4) and R.random() < 0.85
                t = Task(code=f"TSK-{task_n:05d}", project_id=p.id, assignee_id=u.id,
                         title=f"{R.choice(TASK_VERBS)} {R.choice(TASK_NOUNS)}",
                         priority=R.choices(["LOW", "MEDIUM", "HIGH", "CRITICAL"], [20, 50, 25, 5])[0],
                         status="DONE" if done else R.choice(["TODO", "IN_PROGRESS"]), due_at=due, created_at=created)
                task_n += 1
                db.add(t)
                db.flush()
                events = [("CREATED", created), ("STARTED", created + timedelta(hours=R.randint(2, 48)))]
                res_code = R.choice(dept_res[dept])
                for _c in range(R.randint(1, 4)):
                    events.append(("COMMIT", created + timedelta(hours=R.randint(6, 24 * 6))))
                if done:
                    late = R.random() > talent
                    completed = due + timedelta(days=R.randint(1, 4)) if late else created + (due - created) * R.uniform(0.4, 0.98)
                    completed = min(completed, ago(0.5))
                    t.completed_at = completed
                    events.append(("COMPLETED", completed))
                    if verifier and R.random() < 0.92:
                        t.verified_by_id = verifier
                        t.verified_at = completed + timedelta(hours=R.randint(2, 30))
                        if t.verified_at > NOW:
                            t.verified_at = NOW - timedelta(minutes=5)
                        t.quality_score = round(min(5.0, max(2.0, R.gauss(2.6 + talent * 2.2, 0.4))), 1)
                        events.append(("VERIFIED", t.verified_at))
                for et, ts in events:
                    if ts > NOW:
                        continue
                    db.add(TaskEvent(task_id=t.id, user_id=u.id, project_id=p.id, event_type=et, occurred_at=ts,
                                     resource_id=self.res[res_code].id if et == "COMMIT" else None,
                                     action="WRITE" if et == "COMMIT" else None,
                                     outcome="SUCCESS" if et in ("COMMIT", "COMPLETED", "VERIFIED") else None,
                                     details={"source": "simulated-tracker"}))
        # Extra projects and fixed memberships use their own random stream so the history above is unchanged.
        rx = random.Random(1115)
        for code, name, dept in EXTRA_PROJECTS:
            team, start, submit, end = PROJECT_TIMELINE[code]
            p = Project(code=code, name=name, department_id=self.depts[dept].id, description=f"{name} programme.",
                        team_name=team, start_date=_day(-start), submission_date=_day(submit), end_date=_day(end))
            db.add(p)
            db.flush()
            projects[code] = p
        for key, code in CURRENT_PROJECT.items():
            if (code, key) in staffed:
                continue
            p, u = projects[code], self.users[key]
            db.add(ProjectMember(project_id=p.id, user_id=u.id, role="Lead", joined_at=p.start_date))
            staffed.add((code, key))
            for i, title in enumerate(FALCON_TASKS if code == "PRJ-FALCON" else []):
                created = p.start_date + timedelta(days=3 + i * 6)
                done = i < 2
                t = Task(code=f"TSK-{task_n:05d}", project_id=p.id, assignee_id=u.id, title=title,
                         priority=rx.choice(["MEDIUM", "HIGH"]), status="DONE" if done else "IN_PROGRESS",
                         due_at=created + timedelta(days=7), created_at=created,
                         completed_at=created + timedelta(days=5) if done else None)
                task_n += 1
                db.add(t)
                db.flush()
                for et, ts in [("CREATED", created), ("STARTED", created + timedelta(hours=6))] + (
                        [("COMPLETED", t.completed_at)] if done else []):
                    db.add(TaskEvent(task_id=t.id, user_id=u.id, project_id=p.id, event_type=et, occurred_at=ts,
                                     outcome="SUCCESS" if et == "COMPLETED" else None,
                                     details={"source": "simulated-tracker"}))
        for code, staff in PROJECT_STAFF.items():
            for key, role in staff:
                if (code, key) not in staffed:
                    db.add(ProjectMember(project_id=projects[code].id, user_id=self.users[key].id, role=role,
                                         joined_at=projects[code].start_date))
        db.flush()

    # -------------------------------------------------------------- baselines & standing access
    def baselines(self, clean: bool = False):
        db = self.db
        for key, u in self.users.items():
            dept = next(c for c, d in self.depts.items() if d.id == u.department_id)
            if key == "ceo":
                continue
            for code, perms in BASELINE_PROFILES.get(dept, {}).items():
                perms = list(perms)
                if dept == "HR" and "Payroll" in (u.designation or ""):
                    perms = ["READ", "WRITE"]
                db.add(PermissionBaseline(user_id=u.id, resource_id=self.res[code].id, permissions=perms,
                                          source="JOB_PROFILE", approved_by_id=u.manager_id))
                if clean:
                    continue  # job-profile baseline only, no standing access
                g = AccessGrant(user_id=u.id, resource_id=self.res[code].id, permissions=perms, purpose="FEATURE_DEVELOPMENT"
                                if dept == "ENG" else "ANALYTICS_REPORTING" if dept in ("FIN", "DS", "SEC") else "PAYROLL_PROCESSING",
                                source="LEGACY", granted_at=u.joined_at or ago(300), expires_at=None)
                db.add(g)
        db.flush()
        if clean:
            return

        def legacy(key, code, perms, purpose, days_ago, expires=None):
            g = AccessGrant(user_id=self.users[key].id, resource_id=self.res[code].id, permissions=perms, purpose=purpose,
                            source="LEGACY", granted_at=ago(days_ago), expires_at=expires)
            db.add(g)
            self.q(ago(days_ago), self.actor(self.users["admin"]), "GRANT_ACTIVATED", resource_id=self.res[code].id,
                   target_type="GRANT", new_state={"user": self.users[key].full_name, "permissions": perms, "source": "LEGACY"})
            return g

        # Drift case 1: Rahul accumulated DELETE + ADMIN on the dev database over time.
        legacy("eng_emp", "RES-ENG-002", ["READ", "WRITE", "DELETE", "ADMIN"], "DATA_MIGRATION", 140)
        # Drift case 2: Neha holds ADMIN on the Customer Transaction Dataset.
        legacy("fin_emp", "RES-FIN-002", ["READ", "WRITE", "DELETE", "ADMIN"], "ANALYTICS_REPORTING", 200)
        # Drift case 3: expired temporary grant that is still ACTIVE (missed by a legacy process).
        legacy("eng_emp", "RES-DS-001", ["READ", "EXECUTE", "WRITE"], "MODEL_TRAINING", 30, expires=ago(9))
        # Drift case 4: mover - Neha moved from Engineering to Finance and still holds dev database WRITE.
        legacy("fin_emp", "RES-ENG-002", ["READ", "WRITE"], "FEATURE_DEVELOPMENT", 260)
        self.q(ago(45), self.actor(self.users["admin"]), "USER_TRANSFERRED", target_type="USER",
               target_id=self.users["fin_emp"].id, previous_state={"department": "ENG"}, new_state={"department": "FIN"})
        # Drift case 5: Kavya with WRITE/DELETE on the HR database.
        legacy("hr_emp", "RES-HR-001", ["READ", "WRITE", "DELETE"], "PAYROLL_PROCESSING", 180)
        db.flush()

    # -------------------------------------------------------------- historical requests
    def history(self):
        db = self.db
        purposes_by_res = {r.code: r.allowed_purposes for r in self.res.values()}
        dept_targets = {"ENG": ["RES-ENG-001", "RES-ENG-002", "RES-DS-002", "RES-FIN-001"],
                        "FIN": ["RES-FIN-001", "RES-FIN-002", "RES-FIN-003"],
                        "DS": ["RES-DS-001", "RES-DS-002", "RES-DS-003", "RES-FIN-002", "RES-FIN-001"],
                        "HR": ["RES-HR-001"], "SEC": ["RES-FIN-003", "RES-HR-001", "RES-DS-001"]}
        requesters = ["eng_emp", "eng_emp", "fin_emp", "fin_emp", "hr_emp", "hr_emp", "mgr"]
        risk_actor = Actor(actor_type="SYSTEM", name="ASTITVA Risk Engine")
        seq = 1
        for i in range(30):
            key = R.choice(requesters)
            u = self.users[key]
            dept = next(c for c, d in self.depts.items() if d.id == u.department_id)
            code = R.choice(dept_targets[dept])
            res = self.res[code]
            purpose = R.choice(purposes_by_res[code]) if R.random() < 0.85 else R.choice(["FRONTEND_TESTING", "CUSTOMER_SUPPORT"])
            perms = ["READ"] + ([R.choice([p for p in res.available_permissions if p != "READ"])] if R.random() < 0.45 else [])
            perms = [p for p in res.available_permissions if p in perms]
            hours = R.choice([8, 24, 48, 72, 168, 336])
            created = ago(R.uniform(3, 88))
            req = AccessRequest(ref=f"REQ-{created.year}-{seq:05d}", requester_id=u.id, resource_id=res.id,
                                requested_permissions=perms, approved_permissions=perms, purpose=purpose,
                                justification=R.choice([
                                    f"Need {', '.join(perms).lower()} access for the {R.choice(PROJECTS)[1]} sprint deliverables.",
                                    "Quarter-end analysis requested by leadership; read access needed for the reporting pack.",
                                    "Investigating anomalies flagged in last week's monitoring report, scoped to sample records.",
                                    "Validating model performance after the latest retraining run against the holdout set.",
                                    "testing"]), requested_duration_hours=hours, approved_duration_hours=hours,
                                status="PENDING", required_stages=[], created_at=created)
            seq += 1
            db.add(req)
            db.flush()
            db.refresh(req)
            ra = risk.assess(db, req)
            ra.created_at = created
            req.required_stages, req.routing_reasons = workflow.route(res, ra.score, u, db, perms, workflow.is_anomalous(ra))
            self.q(created, self.actor(u), "REQUEST_CREATED", resource_id=res.id, target_type="ACCESS_REQUEST",
                   target_id=req.ref, request_id=req.id, new_state={"permissions": perms, "purpose": purpose, "hours": hours})
            self.q(created + timedelta(seconds=1), risk_actor, "RISK_ASSESSED", resource_id=res.id,
                   target_type="ACCESS_REQUEST", target_id=req.ref, request_id=req.id,
                   new_state={"score": ra.score, "level": ra.level})
            # Decide outcome
            reject = ra.score > 70 and R.random() < 0.7 or R.random() < 0.12
            t = created
            final_status = "APPROVED"
            for stage in req.required_stages:
                t = t + timedelta(hours=R.uniform(0.5, 20))
                approver = self._approver(req, stage)
                if approver is None:
                    final_status = "PENDING"
                    break
                action = "APPROVE"
                comment = None
                if reject and stage == req.required_stages[-1]:
                    action, comment = "REJECT", R.choice(["Purpose does not match resource.", "Excessive permissions requested.",
                                                          "Use the masked dataset instead."])
                elif stage == "RISK" and set(ra.recommended_permissions) != set(req.approved_permissions):
                    action, comment = "NARROW_SCOPE", "Narrowed to least privilege per risk recommendation."
                prev = {"permissions": list(req.approved_permissions), "duration_hours": req.approved_duration_hours}
                if action == "NARROW_SCOPE":
                    req.approved_permissions = ra.recommended_permissions
                    req.approved_duration_hours = min(req.approved_duration_hours, ra.recommended_duration_hours)
                db.add(ApprovalRecord(request_id=req.id, stage=stage, approver_id=approver.id, action=action, comment=comment,
                                      previous_scope=prev, created_at=t,
                                      new_scope={"permissions": list(req.approved_permissions),
                                                 "duration_hours": req.approved_duration_hours}))
                self.q(t, self.actor(approver), f"REQUEST_{action}", resource_id=res.id, target_type="ACCESS_REQUEST",
                       target_id=req.ref, request_id=req.id, reason=comment,
                       new_state={"stage": stage, "permissions": req.approved_permissions})
                if action == "REJECT":
                    final_status = "REJECTED"
                    break
            req.status = final_status
            req.current_stage = None if final_status != "PENDING" else stage
            if final_status == "PENDING":
                req.status = "CANCELLED"
                req.current_stage = None
            req.decided_at = t if final_status in ("APPROVED", "REJECTED") else None
            req.updated_at = t
            if final_status == "APPROVED":
                expires = t + timedelta(hours=req.approved_duration_hours)
                g = AccessGrant(user_id=u.id, resource_id=res.id, request_id=req.id, permissions=req.approved_permissions,
                                purpose=purpose, source="REQUEST", granted_at=t, expires_at=expires,
                                status="ACTIVE" if expires > NOW else "EXPIRED")
                if g.status == "EXPIRED":
                    g.revoked_at, g.revoke_reason = expires, "Grant reached its expiry time"
                db.add(g)
                db.flush()
                tok, _ = issue_token(db, g, f"APR-{req.ref[4:]}")
                tok.issued_at = t
                if g.status == "EXPIRED":
                    tok.revoked_at = expires
                if not req.required_stages:
                    self.q(t, Actor(actor_type="SYSTEM", name="ASTITVA Policy Engine"), "REQUEST_AUTO_APPROVED",
                           resource_id=res.id, target_type="ACCESS_REQUEST", target_id=req.ref, request_id=req.id,
                           reason=f"Auto-approved by policy: rule-based risk score {ra.score}")
                self.q(t + timedelta(seconds=1), self.actor(self._approver(req, req.required_stages[-1]) if req.required_stages else u) if req.required_stages else Actor(actor_type="SYSTEM", name="ASTITVA Policy Engine"), "GRANT_ACTIVATED",
                       resource_id=res.id, target_type="GRANT", target_id=g.id, request_id=req.id,
                       new_state={"permissions": g.permissions, "expires_at": expires, "token": tok.token_hint})
                if g.status == "EXPIRED":
                    self.q(expires, SYSTEM, "GRANT_EXPIRED", resource_id=res.id, target_type="GRANT", target_id=g.id,
                           request_id=req.id, reason="Grant reached its expiry time")
                self._usage(u, res, g, t, min(expires, NOW))
        db.flush()

    def _approver(self, req: AccessRequest, stage: str) -> User | None:
        u = self.db.get(User, req.requester_id)
        if stage == "MANAGER":
            return self.db.get(User, u.manager_id) if u.manager_id else None
        if stage == "RISK":
            sec = self.users["admin"]
            return sec if sec.id not in (u.id, u.manager_id) else None
        return None

    def _usage(self, u: User, res: Resource, g: AccessGrant, start: datetime, end: datetime):
        span = (end - start).total_seconds()
        if span <= 0:
            return
        for _ in range(R.randint(1, 8)):
            ts = start + timedelta(seconds=R.uniform(0, span))
            act = R.choice(g.permissions)
            self.db.add(ResourceAccessEvent(user_id=u.id, resource_id=res.id, grant_id=g.id, action=act, purpose=g.purpose,
                                            outcome="ALLOWED", reason=f"Authorized: {act}", occurred_at=ts, ip="10.20.4.17"))
        g.last_used_at = end

    def standing_usage(self):
        """Activity on standing (baseline) grants, plus a few denials."""
        db = self.db
        for g in db.execute(select(AccessGrant).where(AccessGrant.source == "LEGACY", AccessGrant.status == "ACTIVE")).scalars().all():
            if R.random() < 0.2:
                continue  # some standing access is never used -> unused-permission drift
            used_perms = ["READ"] if "READ" in g.permissions else g.permissions[:1]
            if "WRITE" in g.permissions and R.random() < 0.6:
                used_perms.append("WRITE")
            for _ in range(R.randint(3, 25)):
                ts = ago(R.uniform(0.2, 85))
                act = R.choice(used_perms)
                db.add(ResourceAccessEvent(user_id=g.user_id, resource_id=g.resource_id, grant_id=g.id, action=act,
                                           purpose=g.purpose, outcome="ALLOWED", reason=f"Authorized: {act}", occurred_at=ts,
                                           ip=f"10.20.{R.randint(1, 30)}.{R.randint(2, 250)}"))
                g.last_used_at = max(g.last_used_at or ts, ts)
        denials = [("eng_emp", "RES-FIN-003", "READ", "No purpose-bound access token presented."),
                   ("eng_emp", "RES-HR-001", "READ", "No purpose-bound access token presented."),
                   ("fin_emp", "RES-DS-001", "EXECUTE", "Token is not valid for this resource."),
                   ("hr_emp", "RES-FIN-003", "WRITE", "Access token has expired."),
                   ("eng_emp", "RES-FIN-002", "READ", "Token is bound to a different employee.")]
        for key, code, act, reason in denials:
            ts = ago(R.uniform(1, 40))
            u = self.users[key]
            db.add(ResourceAccessEvent(user_id=u.id, resource_id=self.res[code].id, action=act, purpose="ANALYTICS_REPORTING",
                                       outcome="DENIED", reason=reason, occurred_at=ts, ip="10.20.9.44"))
            self.q(ts, self.actor(u), "RESOURCE_ACCESS_DENIED", resource_id=self.res[code].id, target_type="RESOURCE",
                   target_id=code, reason=reason, new_state={"action": act})
        db.add(SecurityAlert(severity="HIGH", category="TOKEN_MISUSE", title=f"Token presented by wrong identity ({self.users['eng_emp'].full_name})",
                             description="A purpose-bound token issued to another employee was presented for Customer Transaction Dataset.",
                             user_id=self.users["eng_emp"].id, resource_id=self.res["RES-FIN-002"].id, status="RESOLVED",
                             created_at=ago(12), resolved_at=ago(11), resolved_by_id=self.users["admin"].id,
                             resolution="CONFIRMED"))
        db.add(SecurityAlert(severity="MEDIUM", category="UNAUTHORIZED_ACCESS", title=f"Repeated denied access by {self.users['eng_emp'].full_name}",
                             description="Multiple denied resource calls within 15 minutes.", user_id=self.users["eng_emp"].id,
                             created_at=ago(20)))
        db.flush()

    # -------------------------------------------------------------- agents
    def agents(self):
        db = self.db
        specs = [
            ("AGT-FIN-01", "Finance AI Agent", "Generates exposure summaries and variance commentary for Finance.", "mgr", "FIN", 34,
             ["model.invoke", "sql.read", "report.generate"], {"RES-FIN-001": ["READ", "EXECUTE"], "RES-FIN-002": ["READ"]}, 180),
            ("AGT-SUP-01", "Customer Support AI Agent", "Answers customer tickets using the support knowledge base.", "mgr", "DS", 22,
             ["kb.search", "ticket.update", "model.invoke"], {"RES-DS-003": ["READ"], "RES-DS-002": ["EXECUTE"]}, 120),
            ("AGT-DEV-01", "Developer AI Agent", "Assists engineers with schema questions and test data generation.", "mgr", "ENG", 41,
             ["sql.read", "sql.write", "code.search", "api.call"], {"RES-ENG-002": ["READ", "WRITE"], "RES-ENG-001": ["READ", "EXECUTE"]}, 90),
            ("AGT-HR-01", "HR Assistant Agent", "Answers employee policy questions; looks up non-sensitive HR records.", "admin", "HR", 48,
             ["hr.lookup", "policy.search"], {"RES-HR-001": ["READ"]}, 12),
        ]
        self.agent_objs = {}
        for code, name, purpose, owner, dept, score, tools, perms, days in specs:
            a = AiAgent(code=code, name=name, purpose=purpose, owner_id=self.users[owner].id, department_id=self.depts[dept].id,
                        api_key_hash=crypto.token_digest(AGENT_KEYS[code]), risk_score=score, allowed_tools=tools,
                        expires_at=NOW + timedelta(days=days))
            db.add(a)
            db.flush()
            for rc, p in perms.items():
                db.add(AgentPermission(agent_id=a.id, resource_id=self.res[rc].id, permissions=p, expires_at=NOW + timedelta(days=days)))
            self.agent_objs[code] = a
            self.q(ago(200), self.actor(self.users["admin"]), "AGENT_REGISTERED", target_type="AGENT", target_id=code,
                   new_state={"tools": tools, "permissions": perms})
        db.flush()
        # Historical agent traffic
        for code, a in self.agent_objs.items():
            perms = db.execute(select(AgentPermission).where(AgentPermission.agent_id == a.id)).scalars().all()
            for _ in range(R.randint(25, 60)):
                p = R.choice(perms)
                db.add(ResourceAccessEvent(agent_id=a.id, resource_id=p.resource_id, action=R.choice(p.permissions),
                                           tool=R.choice(a.allowed_tools), outcome="ALLOWED", reason="Authorized agent call",
                                           occurred_at=ago(R.uniform(0.1, 30))))
        sup = self.agent_objs["AGT-SUP-01"]
        for days in (6, 2):
            ts = ago(days)
            db.add(ResourceAccessEvent(agent_id=sup.id, resource_id=self.res["RES-FIN-003"].id, action="READ", tool="kb.search",
                                       outcome="DENIED", reason="Agent is not authorized to access this resource.", occurred_at=ts))
            self.q(ts, Actor(actor_type="AGENT", name=sup.name, agent_id=sup.id), "AGENT_ACCESS_DENIED",
                   resource_id=self.res["RES-FIN-003"].id, target_type="RESOURCE", target_id="RES-FIN-003",
                   reason="Agent is not authorized to access this resource.")
        db.add(SecurityAlert(severity="HIGH", category="AGENT_UNAUTHORIZED", title="Customer Support AI Agent denied access to Finance Ledger Database",
                             description="Agent is not authorized to access this resource.", agent_id=sup.id,
                             resource_id=self.res["RES-FIN-003"].id, created_at=ago(2)))
        db.flush()

    # -------------------------------------------------------------- emergency
    def emergency(self):
        db = self.db
        cases = [("eng_emp", "RES-ENG-002", ["READ", "WRITE"], "INC-40211", 40, 60, "EXPIRED", "JUSTIFIED"),
                 ("mgr", "RES-DS-001", ["READ", "EXECUTE"], "INC-40257", 22, 90, "REVOKED", "INCONCLUSIVE"),
                 ("mgr", "RES-FIN-003", ["READ"], "INC-40310", 8, 45, "EXPIRED", None),
                 ("eng_emp", "RES-ENG-002", ["READ", "WRITE", "DELETE"], "INC-40388", 3, 120, "EXPIRED", "JUSTIFIED")]
        for key, code, perms, inc, days, minutes, status, outcome in cases:
            u = self.users[key]
            start = ago(days)
            end = start + timedelta(minutes=minutes if status == "EXPIRED" else minutes / 3)
            g = AccessGrant(user_id=u.id, resource_id=self.res[code].id, permissions=perms, purpose="INCIDENT_RESPONSE",
                            source="EMERGENCY", is_emergency=True, granted_at=start, expires_at=start + timedelta(minutes=minutes),
                            status="EXPIRED" if status == "EXPIRED" else "REVOKED", revoked_at=end,
                            revoke_reason="Break-glass session ended")
            db.add(g)
            db.flush()
            es = EmergencySession(ref=f"BG-{inc[4:]}", user_id=u.id, resource_id=self.res[code].id, grant_id=g.id,
                                  justification=f"Production incident {inc}: elevated error rates require direct database inspection and hotfix verification.",
                                  incident_ref=inc, permissions=perms, status=status, started_at=start,
                                  expires_at=start + timedelta(minutes=minutes), ended_at=end,
                                  revoked_by_id=self.users["admin"].id if status == "REVOKED" else None,
                                  review_status="COMPLETED" if outcome else "PENDING", review_outcome=outcome,
                                  review_notes="Actions matched the incident runbook." if outcome == "JUSTIFIED" else
                                  ("Session revoked early; scope broader than needed." if outcome else None),
                                  reviewed_by_id=self.users["admin"].id if outcome else None,
                                  reviewed_at=end + timedelta(hours=6) if outcome else None)
            db.add(es)
            db.flush()
            for _ in range(R.randint(3, 9)):
                ts = start + timedelta(seconds=R.uniform(0, (end - start).total_seconds()))
                act = R.choice(perms)
                db.add(ResourceAccessEvent(user_id=u.id, resource_id=self.res[code].id, grant_id=g.id, emergency_session_id=es.id,
                                           action=act, purpose="INCIDENT_RESPONSE", outcome="ALLOWED",
                                           reason=f"Authorized: {act} (break-glass)", occurred_at=ts))
            self.q(start, self.actor(u), "BREAKGLASS_ACTIVATED", resource_id=self.res[code].id, target_type="EMERGENCY_SESSION",
                   target_id=es.ref, new_state={"permissions": perms, "minutes": minutes, "incident": inc})
            db.add(SecurityAlert(severity="CRITICAL", category="BREAKGLASS", title=f"BREAK-GLASS activated by {u.full_name}",
                                 description=f"{', '.join(perms)} on {self.res[code].name} for {minutes} min. Incident {inc}.",
                                 user_id=u.id, resource_id=self.res[code].id, status="RESOLVED", created_at=start,
                                 resolved_at=end, resolved_by_id=self.users["admin"].id, resolution="FALSE_POSITIVE"))
            self.q(end, self.actor(self.users["admin"]) if status == "REVOKED" else SYSTEM,
                   "BREAKGLASS_REVOKED" if status == "REVOKED" else "BREAKGLASS_EXPIRED", resource_id=self.res[code].id,
                   target_type="EMERGENCY_SESSION", target_id=es.ref)
        db.flush()

    # -------------------------------------------------------------- recertification
    def reviews(self):
        db = self.db
        old = AccessReviewCampaign(name=f"Access recertification {ago(38):%B %Y}", started_at=ago(38), due_at=ago(31),
                                   created_by_id=None)
        db.add(old)
        db.flush()
        grants = db.execute(select(AccessGrant).where(AccessGrant.status == "ACTIVE", AccessGrant.is_emergency.is_(False))).scalars().all()
        R.shuffle(grants)
        for i, g in enumerate(grants[:40]):
            u = db.get(User, g.user_id)
            reviewer = u.manager_id or db.get(Resource, g.resource_id).owner_id
            if reviewer == u.id:
                continue  # never self-review
            decided = i >= 5  # five items left pending -> overdue
            db.add(AccessReview(campaign_id=old.id, reviewer_id=reviewer, grant_id=g.id, user_id=g.user_id,
                                resource_id=g.resource_id, due_at=old.due_at, unused=g.last_used_at is None,
                                status="RETAINED" if decided else "PENDING", decided_at=ago(R.uniform(31, 37)) if decided else None,
                                created_at=old.started_at))
        self.q(old.started_at, SYSTEM, "RECERT_CAMPAIGN_STARTED", target_type="CAMPAIGN", target_id=old.id,
               new_state={"items": 40})
        db.flush()

    def flush_audit(self):
        for ts, actor, action, kw in sorted(self.audit_queue, key=lambda x: x[0]):
            audit.record(self.db, actor, action, occurred_at=ts, **kw)
        self.audit_queue.clear()
        self.db.flush()

    # -------------------------------------------------------------- live state through the real workflow
    def live(self):
        db = self.db
        U = self.users
        rahul, neha, kavya = U["eng_emp"], U["fin_emp"], U["hr_emp"]
        mgr, sec = U["mgr"], U["admin"]
        A = lambda u: Actor(user=u, ip="10.20.4.17", user_agent="seed")  # noqa: E731
        def sub(u, code, perms, purpose, hours, why, impact="MEDIUM", deadline_h=None, waited_h=0):
            r = workflow.submit(db, A(u), resource_id=self.res[code].id, permissions=perms, purpose=purpose,
                                justification=why, duration_hours=hours, business_impact=impact,
                                deadline_at=NOW + timedelta(hours=deadline_h) if deadline_h and deadline_h > 0 else None)
            if waited_h or (deadline_h is not None and deadline_h <= 0):
                # demo data only: make the request look older / overdue so the priority queue has variety
                row = db.get(AccessRequest, r.id)
                row.created_at = NOW - timedelta(hours=waited_h)
                if deadline_h is not None and deadline_h <= 0:
                    row.deadline_at = NOW + timedelta(hours=deadline_h)
                db.commit()
            return r

        # 1. Low risk, INTERNAL resource, READ only -> auto-approved by policy (Priya gets an FYI notification)
        sub(rahul, "RES-ENG-001", ["READ"], "ANALYTICS_REPORTING", 24,
            "Pull checkout conversion metrics for the Atlas sprint review deck this Friday.", "LOW")
        # 2. RESTRICTED HR database with WRITE -> a human must approve; deadline tomorrow, waiting 30h
        sub(kavya, "RES-HR-001", ["READ", "WRITE"], "PAYROLL_PROCESSING", 72,
            "Monthly payroll corrections for the October cycle, including three retroactive salary revisions.",
            "HIGH", deadline_h=20, waited_h=30)
        # 3. High risk (purpose mismatch, WRITE on confidential data) -> Manager + Security Manager, no deadline
        sub(rahul, "RES-FIN-002", ["READ", "WRITE"], "FRONTEND_TESTING", 168, "Need realistic data for UI testing",
            "LOW", waited_h=2)
        # 4. CRITICAL model, Manager already approved -> waiting for the Security Manager; deadline already passed
        r4 = sub(neha, "RES-DS-001", ["READ", "EXECUTE", "WRITE"], "MODEL_TRAINING", 72,
                 "Retrain the fraud model with Q3 chargeback labels from the finance reconciliation extract.",
                 "CRITICAL", deadline_h=-3, waited_h=50)
        if db.get(AccessRequest, r4.id).current_stage == "MANAGER":
            workflow.act(db, A(mgr), r4.id, "APPROVE", "Part of the Q3 fraud model refresh.")
        # 5. Medium risk approved by the Manager -> active purpose-bound grant
        #    Asked for 30 days, but Atlas ends in 15, so the grant is capped at the Atlas end date.
        r5 = sub(rahul, "RES-DS-002", ["READ", "EXECUTE"], "FEATURE_DEVELOPMENT", 720,
                 "Integrate recommendation scores into the Atlas checkout upsell widget behind a feature flag "
                 "until the Atlas launch.")
        while db.get(AccessRequest, r5.id).status == "PENDING":
            stage = db.get(AccessRequest, r5.id).current_stage
            workflow.act(db, A(mgr if stage == "MANAGER" else sec), r5.id, "APPROVE", "Approved.")
        # 6. Active break-glass session (live monitoring screen)
        from app.services import breakglass

        breakglass.activate(db, A(rahul), resource_id=self.res["RES-ENG-002"].id, permissions=["READ", "WRITE"],
                            justification="Checkout latency incident: lock contention on orders table, need to kill blocking queries and verify fix.",
                            incident_ref="INC-40412", duration_minutes=90)
        # A current recertification campaign + overdue processing
        recert.start_campaign(db, SYSTEM, "Access recertification (current cycle)")
        recert.process_overdue(db)
        drift.scan(db, SYSTEM)
        # Spread first-detection dates over the last ~12 weeks so the trend chart reflects history
        from app.models import DriftFinding
        for f in db.execute(select(DriftFinding)).scalars():
            f.detected_at = ago(R.randint(0, 80))
        db.commit()


def reset_schema():
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    from alembic import command
    from alembic.config import Config
    import os

    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic"))
    command.upgrade(cfg, "head")


def ensure_catalog(db) -> int:
    """Bring an existing database up to the current resource list without touching grants or history:
    adds resources that are missing and any newly offered permissions. Returns how many resources were added."""
    owner = db.execute(select(User).where(User.email == f"{DEMO_EMAILS['admin']}@{DOMAIN}")).scalar_one_or_none()
    added = 0
    for code, name, typ, dept, sens, perms, purposes, depts, max_h, bg, _owner, _backup, desc in RESOURCES:
        r = db.execute(select(Resource).where(Resource.code == code)).scalar_one_or_none()
        if r:
            missing = [p for p in perms if p not in (r.available_permissions or [])]
            if missing:
                r.available_permissions = [p for p in perms if p in set(r.available_permissions or []) | set(missing)]
            continue
        d = db.execute(select(Department).where(Department.code == dept)).scalar_one_or_none()
        if not owner or not d:
            continue
        db.add(Resource(code=code, name=name, resource_type=typ, department_id=d.id, sensitivity=sens,
                        available_permissions=perms, allowed_purposes=purposes, allowed_departments=depts,
                        max_duration_hours=max_h, breakglass_allowed=bg, owner_id=owner.id, description=desc,
                        requires_risk_review=sens not in ("PUBLIC", "INTERNAL")))
        added += 1
    db.commit()
    return added


def run(reset: bool = False, clean: bool = False):
    if reset:
        reset_schema()
    with SessionLocal() as db:
        if db.execute(select(User).limit(1)).first():
            added = ensure_catalog(db)
            print("Database already seeded. Use --reset to recreate."
                  + (f" Added {added} new mock resource(s) to the registry." if added else ""))
            return
        s = Seeder(db)
        if clean:
            # Blank slate: the 5 people, resources, policies, AI agents and work history only.
            # No access grants, requests, drift cases, emergency sessions or reviews.
            s.org()
            s.resources()
            s.work()
            s.baselines(clean=True)
            s.agents()
            s.flush_audit()
            db.commit()
            print("Seeded ASTITVA (clean): 5 people (1 Manager, 3 Employees, 1 Security Manager), "
                  f"{len(s.res)} resources, 4 AI agents, no access grants or requests.")
            print(f"Demo password for all accounts: {DEMO_PASSWORD}")
            return
        s.org()
        s.resources()
        s.work()
        s.baselines()
        s.history()
        s.standing_usage()
        s.agents()
        s.emergency()
        s.reviews()
        s.flush_audit()
        db.commit()
        s.live()
        db.commit()
        n_users = db.query(User).count()
        print(f"Seeded ASTITVA demo: {n_users} people (1 Manager, 3 Employees, 1 Security Manager), {len(s.res)} resources, 4 AI agents.")
        print(f"Demo password for all accounts: {DEMO_PASSWORD}")


if __name__ == "__main__":
    run(reset="--reset" in sys.argv, clean="--clean" in sys.argv)
