# ASTITVA

**Enterprise identity, access governance and AI-agent security for Nexora Technologies (fictional).**

ASTITVA handles the whole access lifecycle for people and AI agents:

1. An employee asks for access to a resource and states a purpose.
2. A risk engine scores the request and recommends the least privilege needed.
3. The risk score picks the path: low risk is auto-approved by a deterministic policy (the manager is informed), medium risk needs the employee's **Manager**, and high risk needs the Manager and then the **Security Manager**. A separation-of-duties engine enforces the rules at every step.
4. On final approval, the platform issues a short-lived token bound to that person, resource, purpose and set of permissions.
5. Every call to the resource goes through a gateway that checks the token.
6. Access ends on expiry or revocation, and is reviewed again in recertification campaigns.

Every security-relevant action is written to a SHA-256 hash-chained audit trail that can be verified.

> **Simulated environment.** All employees, resources, credentials, agents and datasets are fictional. Nothing connects to a real production system. Email and SMS go to a database-backed dev outbox, not to a provider.

---

## Contents

1. [Quick start (Docker)](#quick-start-docker)
2. [Demo credentials](#demo-credentials)
3. [Architecture](#architecture)
4. [Security model](#security-model)
5. [Access lifecycle](#access-lifecycle)
6. [Risk engine](#risk-engine)
7. [Review priority](#review-priority)
8. [Database schema](#database-schema)
9. [API](#api)
10. [Local development](#local-development)
11. [Configuration](#configuration)
12. [Tests and results](#tests-and-results)
13. [Production deployment](#production-deployment)
14. [Known limitations](#known-limitations)

---

## Quick start (Docker)

```bash
cp .env.example .env          # optional: the defaults work for a local demo
docker compose up --build
```

| Service | URL / role |
|---|---|
| Web app | http://localhost:3000 |
| API + OpenAPI docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/health |
| `worker` / `beat` | Celery worker and scheduler: grant expiry, expiry notices, recertification overdue processing, drift scans |
| `postgres` / `redis` | Data store, rate limiting, pub/sub for live notifications, Celery broker |

When the backend container starts, it runs `alembic upgrade head` and then seeds the demo data, but only if the database is empty. To reset the demo:

```bash
docker compose exec backend python -m app.seed --reset
```

## Demo credentials

The demo organisation is deliberately small: **1 Manager, 3 Employees and 1 Security Manager.**

Every account uses the password **`Nexora@Demo2026`**. Every sign-in needs a second factor: a 6-digit email code. In development, the login screen shows a **Dev mailbox** panel with the simulated email, so you can complete MFA without a real inbox. The login page also has one-click buttons for the five accounts.

| Email | Person | Role | What they do |
|---|---|---|---|
| `rahul.sharma@nexora.example` | Rahul Sharma, Software Engineer (Engineering) | Employee | Requests access, uses tokens, emergency access |
| `neha.gupta@nexora.example` | Neha Gupta, Financial Analyst (Finance) | Employee | Requests access (the only employee allowed on the Finance Ledger) |
| `kavya.reddy@nexora.example` | Kavya Reddy, HR Generalist (Human Resources) | Employee | Requests access (the only employee allowed on the HR database) |
| `priya.desai@nexora.example` | Priya Desai, Team Manager | Manager | Manager of all three employees. Approves medium and high risk employee requests, gets an FYI for auto-approved ones, team analytics, leaderboard, access reviews |
| `admin@nexora.example` | Meera Krishnan, Security Manager | Security Manager + Risk Reviewer | Security approval on high-risk requests, routing thresholds, alerts, emergency access, drift, audit, AI agents, policies, users |

**Approval chain (by risk score, thresholds editable on the Policies page)**

```
risk 0–30    Employee request  ──►  auto-approved by policy (Priya gets an FYI)        ──►  access active + token
risk 31–60   Employee request  ──►  Manager (Priya)                                   ──►  access active + token
risk 61–100  Employee request  ──►  Manager (Priya)  ──►  Security Manager (Meera)  ──►  access active + token
```

- **A human always decides** (these can never be auto-approved, whatever the score, and an admin cannot turn this off):
  - sensitive resources: CONFIDENTIAL, RESTRICTED and CRITICAL (every model, dataset and database except the two INTERNAL engineering resources);
  - WRITE, DELETE or ADMIN permissions (only READ and EXECUTE can be auto-approved);
  - unusual behaviour flagged by the anomaly model, which also forces the Security Manager review.
- Every request stores the reason for its path, and the request page shows it under "Why this approval path".

- A request from the Manager has no manager above it, so it goes straight to the Security Manager.
- The Security Manager can't approve their own request. The app refuses such a request up front and points to Emergency Access, which is monitored and reviewed afterwards.

The seed also creates:

- **9 resources:** ML models, datasets, an internal API, the HR database, the development database and the Finance Ledger Database.
- **4 AI agents** with these demo keys:

  | Agent | Demo key |
  |---|---|
  | AGT-FIN-01 | `agk_demo_finance_agent_key_0001` |
  | AGT-SUP-01 | `agk_demo_support_agent_key_0002` |
  | AGT-DEV-01 | `agk_demo_developer_agent_key_0003` |
  | AGT-HR-01 | `agk_demo_hr_assistant_key_0004` |

- **About 35 historical and live access requests**, plus:
  - projects and task events
  - 5 drift cases
  - emergency-access history and one live break-glass session
  - an overdue recertification campaign

  Live demo requests cover every path: REQ-2026-00031 was auto-approved (INTERNAL resource, READ only, risk 23); 00032 waits for the Manager (RESTRICTED HR database with WRITE, risk 41, deadline tomorrow, so "Due soon"); 00033 waits for the Manager and then needs security review (risk 100, no deadline); and 00034 is waiting for the Security Manager (CRITICAL model, risk 74, deadline already passed, so "Overdue").

---

## Architecture

```
 Browser (Next.js 15 / React 19, Tailwind, Radix/shadcn-style UI, Recharts, SWR)
   │  same-origin /api/* (Next rewrite)          ws://…:8000/api/ws/notifications
   ▼                                              ▲
 FastAPI (app/main.py) ── security headers, CORS, CSRF double-submit, auth deps
   ├─ api/auth.py        login, MFA, refresh rotation, registration, reset, sessions
   ├─ api/access.py      catalog, requests, approvals, grants/tokens, resources,
   │                     resource gateway, AI agent gateway
   ├─ api/governance.py  employees + analytics, leaderboard, drift, emergency,
   │                     recertification, agents
   └─ api/admin.py       dashboard, audit, alerts, policies, notifications, search, users
          │
   services/ (all business rules live here, never in the UI)
     auth · risk · sod · workflow · grants · gateway · audit · drift ·
     breakglass · recert · users · analytics · notify · maintenance
          │                             │
   PostgreSQL (SQLAlchemy 2, Alembic)   Redis: token buckets, failure counters,
                                         lockouts, pub/sub notifications, Celery
          ▲
   Celery worker + beat (app/worker.py): expiry, notices, recert overdue, drift scan
```

**Design principles**

- **The server is the source of truth for authorization.** Every route declares its permission with `require("perm")`. The UI hides what you can't use, but the API returns 403 regardless.
- **AI recommends and never authorizes.** The risk engine combines deterministic rules with an IsolationForest anomaly signal. An optional LLM (Anthropic or an OpenAI-compatible provider) only writes the plain-language explanation. Grants come solely from policy checks plus human approvals.
- **Every token is purpose-bound.** A token is valid only for one person, one resource, one purpose, its approved permissions and its expiry, and the gateway checks all of these on each call.
- **Writes are audited in the same transaction.** Audit records are hash-chained, so editing or deleting a row is detectable.

## Security model

| Control | Implementation |
|---|---|
| Password storage | Argon2id (argon2-cffi, t=3, m=64 MiB, p=2). The policy needs 12+ characters and a mix of character classes, and rejects passwords containing the email or name or found on a common-password list. |
| MFA | TOTP (RFC 6238, replay-protected by time step), email OTP, single-use backup codes. An SMS adapter interface is ready. A short-lived `mfa_pending` token links the two steps, and MFA cannot be skipped. |
| Sessions | 15-minute JWT access token plus an opaque refresh token that rotates on every use. **Reuse of an old refresh token revokes the whole session and raises an alert.** |
| Cookies | `astitva_at` (HttpOnly, path `/`) and `astitva_rt` (HttpOnly, path `/api/auth`), both `Secure` in production with `SameSite=Strict`. `astitva_csrf` is the double-submit token, sent back as the `X-CSRF-Token` header. |
| Brute force | Redis Lua token buckets per IP (20 tokens, refill 20/min) and per account (10 tokens per 5 min). Five failures in 15 minutes trigger a **temporary** progressive lockout: 60s, then 120s, 240s and so on, capped at 30 min. Lockout is never permanent. Unknown accounts are tracked too, so attackers can't enumerate. 8 or more distinct accounts from one IP raises a credential-stuffing alert. A CAPTCHA verifier hook is in place. |
| Error messages | Errors are generic ("Invalid email or password"). Forgot-password always returns 202. |
| Secrets at rest | Refresh tokens, access tokens and agent keys are stored as HMAC-SHA256 digests with a pepper. TOTP secrets and re-revealable resource tokens are Fernet-encrypted. |
| Headers | API: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, plus HSTS in production. Web: the same plus `Permissions-Policy`. |
| Production guard | The app refuses to start with `dev-only` secrets when `APP_ENV=production`. Production also forces Secure cookies and disables the dev outbox. |

## Access lifecycle

1. **Request.** The requester picks a resource, a purpose from the catalog (each purpose has least-privilege permissions), the permissions and a duration, plus a justification.
   - ABAC checks the allowed departments and purposes for that resource and its maximum duration.
   - Duplicate open requests are rejected.
2. **Risk score (0–100).** See [Risk engine](#risk-engine) for every factor and weight.
   - Levels are LOW (0–30), MEDIUM (31–60), HIGH (61–80) and CRITICAL (81–100). Backend (`catalog.risk_level`) and UI use the same scale.
   - The output also includes recommended permissions, a recommended duration and an action.
   - The requester also gives an optional **deadline** and a **business impact**. They set the review [priority](#review-priority), never the risk or the path.
3. **Stages (risk-based routing).** The deterministic, rule-based risk score decides the path on the server. The AI model never grants access.

   | Risk score | Path |
   |---|---|
   | 0–30 | **Auto-approved by policy**, only for a non-sensitive (PUBLIC/INTERNAL) resource with READ/EXECUTE and no anomaly. Grant and token are issued at once, audited as `REQUEST_AUTO_APPROVED` by the "ASTITVA Policy Engine" actor, and the reporting manager gets an FYI notification saying who got which permission. |
   | 31–60, or a low score on a sensitive resource or with WRITE/DELETE/ADMIN | `MANAGER` only: the employee's reporting manager. |
   | 61–100, or any score with a behaviour anomaly | `MANAGER`, then `RISK`: the **security review**, done by the Security Manager. |

   - The thresholds live in the GLOBAL policy "Risk-based approval routing" and the Security Manager can change them on the Policies page (validated, audited as `POLICY_UPDATED`).
   - Guardrails (hard-coded in `workflow.ALWAYS_HUMAN_SENSITIVITIES` / `AUTO_SAFE_PERMISSIONS`, also enforced when a policy is saved): CONFIDENTIAL, RESTRICTED and CRITICAL resources and WRITE/DELETE/ADMIN are never auto-approved; an anomaly always adds the security review. Even a policy edited directly in the database cannot loosen them.
   - If the policy is disabled or deleted, every request needs both approvals.
   - A requester with no manager (Priya) goes to the Security Manager instead of the Manager stage.
   - The request page shows an animated stepper for the chosen path, and the requests list shows a compact version. Motion uses transform/opacity only and is off under `prefers-reduced-motion`.
   - The login page has the same rule: the moving glows, orbit emblem, headline reveal and button sweep are pure CSS transform/opacity (no blur filters, no WebGL). Measured in headless Chromium: a steady 60 fps (the display's refresh rate) with 0 frames over 25 ms; on a 120 Hz screen it runs at 120.

   There is no separate resource-owner stage, and the model shows a resource's owner for information only.
   - At each stage an approver can approve, reject, **narrow scope** (remove permissions or shorten the duration) or **request modification** (sends it back to the requester).
4. **Separation of duties.** These built-in rules always apply:
   - SELF_APPROVAL
   - STAGE_AUTHORITY
   - REPORTING_CONFLICT
   - INDEPENDENT_REVIEWERS (one person, one stage)
   - MANAGER_DUAL_ROLE

   Admins can add policies of the kinds ROLE_CONFLICT, STAGE_CONFLICT, DEPARTMENT_CONFLICT and RESOURCE_SENSITIVITY_DUAL_CONTROL. Violations are blocked, audited and raise an alert.
5. **Grant and token.** Final approval creates a grant and a token in the form `SIM-ACCESS-XXXXXXX.<secret>`.
6. **Gateway.** `POST /api/gateway/resources/{id}/access` with an `X-Access-Token` header. A call can be denied with one of these codes:
   - `NO_TOKEN`
   - `INVALID_TOKEN`
   - `TOKEN_REVOKED`
   - `TOKEN_EXPIRED` (the grant expires inline)
   - `TOKEN_IDENTITY_MISMATCH` (raises a HIGH alert)
   - `TOKEN_RESOURCE_MISMATCH`
   - `TOKEN_PURPOSE_MISMATCH`
   - `PERMISSION_NOT_GRANTED`
   - `POLICY_DENIED`
7. **AI agents** call `POST /api/agent-gateway/invoke` with the `X-Agent-Id` and `X-Agent-Key` headers.
   - Each call is checked against the agent's approved tools, resources and permissions.
   - Denials are audited, and repeated denials raise alerts. Admins can suspend agents or rotate their keys.
8. **Emergency access (break-glass).** Requires an incident reference and a justification.
   - Capped at 240 minutes.
   - Raises an immediate CRITICAL alert, records every action, and must be reviewed after use.
9. **Drift detection.** Compares current access with each person's role baseline.
   - It flags excess permissions, standing access with no baseline, permissions unused for 30 days and grants that are past expiry but still active.
   - Each finding can be remediated (revoke), accepted, or marked false positive.
10. **Recertification.** Campaigns run every 30 days and ask managers to keep or revoke each person's access.
    - Overdue reviews raise `RECERT_OVERDUE` alerts and notifications.
    - When someone transfers department (a mover), reviews are created automatically.
11. **Removing access.** The Security Manager (any employee) and the Manager (own team only) can open **Active Access** or the request page and either remove single permissions (the grant is narrowed and a new token is issued; the old token stops working) or revoke the whole access. A reason is required, the action is audited (`GRANT_RESTRICTED` / `GRANT_REVOKED`) and the employee is notified. The request page stepper and the requests list then show "Access revoked" (or "Now READ only"). Employees cannot change their own grants; this is enforced on the server.
12. **Deactivation.** Revokes all grants, tokens and sessions in one transaction.
13. **Employee intelligence.** Analytics and the leaderboard use only verified task events: tasks completed, on time, cycle time, reopen rate and contribution. They never use self-reported data.

## Risk engine

`backend/app/services/risk.py`, weights in `backend/app/core/risk_config.py` (one place for every number).

| Factor | Points | Notes |
|---|---|---|
| Resource sensitivity | 0 / 5 / 15 / 22 / 30 | PUBLIC … CRITICAL |
| Privilege level | READ 0, EXECUTE 5, WRITE 12, DELETE 18, ADMIN 28, +2 per extra permission | |
| Excessive for purpose | 10 per permission, max 25 | compared with the purpose's least privilege |
| Purpose mismatch | 20 | purpose not approved for the resource |
| Department | 15 out of scope, 5 cross-department | |
| Long duration | 10 (≤3× the proportionate max) or 15 | |
| Weak justification | 8 | fewer than 8 words |
| Prior access / first access | −5 / +3 | positive signal for earlier approved grants |
| Device trust (simulated) | 5 unknown, 15 untrusted | |
| **History group (max 20 together)** | | |
| Confirmed violations | 8 each | only alerts a Security Manager resolved as **Confirmed** |
| Unreviewed alerts | 3 each, max 6 | open alerts may be false positives, so they count less |
| Repeated denied operations | 4 (≥3) or 8 (≥10) in 30 days | blocked gateway calls, not violations |
| **Behaviour group (max 12 together)** | | |
| Request velocity | 8 | ≥5 other requests in 7 days **and** ≥3× the person's own weekly baseline (previous 8 weeks) |
| Behaviour anomaly (Isolation Forest) | 10 | only when the model has enough data |

What was fixed:

- **Denied requests are not violations.** A rejected access request is never counted. Only alerts confirmed by a Security Manager count as violations. On the Security alerts tab each alert is resolved as **Confirm** or **False positive**; false positives never count.
- **No future leakage.** Every history query is bounded at the request's `created_at` (a resubmission is scored as of the resubmission time).
- **No double counting.** The current request is excluded from velocity, and related signals share a cap (history group 20, behaviour group 12).
- **Isolation Forest.** Reference population: every user with requests or gateway events in the 30 days before the start of the request's day (UTC). The model (`n_estimators=100`, `contamination=0.08`, `random_state=42`) is trained once per day on that population and cached, separately from scoring. With fewer than 12 people (the demo has 5) it is **not used**: the request shows "Behaviour model: n/a, not enough data" with 0 points, the engine is reported as `rules-v2`, and the explanation says the signal was unavailable. It never makes up a result.
- **Explainable.** Every factor has a label, points and a sentence; unavailable signals are listed too.

## Review priority

`backend/app/services/priority.py`. Priority decides only the **order** in the Approval Center. It never changes the risk score, the approval path or the grant.

```
priority = 0.40 × deadline + 0.30 × business impact + 0.20 × waiting time + 0.10 × urgency     (clamped 0–100)
```

| Deadline left | Points | | Waiting | Points | | Impact | Points |
|---|---|---|---|---|---|---|---|
| none or > 7 days | 0 | | < 4 h | 0 | | Low | 10 |
| 3–7 days | 10 | | 4–24 h | 20 | | Medium | 40 |
| 1–3 days | 25 | | 1–3 days | 40 | | High | 70 |
| 6–24 h | 40 | | 3–7 days | 70 | | Critical | 100 |
| 1–6 h (under 6 h) | 50 | | > 7 days | 100 | | | |
| overdue | 60 | | | | | | |

- **Urgency** comes from the purpose, not from the requester: Incident Response 100, Fraud Investigation 70, Security Review 50, Compliance Audit 40, others 0.
- **Levels:** 0–24 Low, 25–49 Medium, 50–74 High, 75–100 Critical. Flags: **Overdue** (deadline passed) and **Due soon** (within 24 h).
- Computed on every read with an injectable clock (`compute(..., now=)`), so it is always current and nobody can store or edit a score. A score sent by a client is ignored.
- The deadline is optional, must include a timezone (the form sends the browser's local time as UTC) and cannot be in the past or more than a year ahead. The requester can change deadline and impact while the request is open (`PATCH /api/requests/{id}/priority-inputs`, audited as `REQUEST_PRIORITY_INPUTS_CHANGED`).
- **Approval Center:** Priority and Needed-by columns, sort by highest priority (ties: earliest deadline, then longest waiting), earliest deadline or longest waiting, and filters All / Overdue / Due in 24h / Critical / High / Medium / Low (`GET /api/approvals/queue?sort=&filter=`).

## Database schema

The schema has 33 normalized tables. It is defined in `backend/app/models.py`. Migrations: `ccd77e69f635_initial_schema.py` and `b7e2a1c9d4f0_priority_and_routing.py` (additive only: `access_requests.deadline_at`, `business_impact`, `routing_reasons`, and `security_alerts.resolution`; tested up and down on a populated database).

| Area | Tables |
|---|---|
| Organisation | `departments`, `users`, `roles`, `user_roles`, `projects`, `project_members`, `tasks`, `task_events` |
| Authentication | `mfa_credentials`, `otp_challenges`, `login_attempts`, `user_sessions`, `refresh_tokens`, `dev_outbox` |
| Access | `resources`, `policies`, `access_requests`, `approval_records`, `risk_assessments`, `access_grants`, `access_tokens`, `resource_access_events` |
| Governance | `permission_baselines`, `drift_findings`, `access_review_campaigns`, `access_reviews`, `emergency_sessions` |
| AI agents | `ai_agents`, `agent_permissions` |
| Audit and alerts | `audit_events`, `audit_chain_head`, `security_alerts`, `notifications` |

**Key relationships**

- `users.manager_id` points to `users`, which forms the reporting line.
- An `access_requests` row has many `approval_records` (one per stage) and many `risk_assessments` (the latest one counts).
- On approval, a request has one `access_grants` row, which has one `access_tokens` row.
- `access_grants` has many `resource_access_events`, the usage evidence that drift detection and analytics rely on.
- `audit_events.hash` is SHA-256 over the event's fields plus `prev_hash`.
- `audit_chain_head` is locked `FOR UPDATE` on every append, so the chain stays linear even with concurrent writers.

## API

There are 85 REST endpoints plus one WebSocket. Interactive docs are at **http://localhost:8000/docs**.

| Group | Endpoints |
|---|---|
| Auth | `POST /api/auth/login`, `/mfa/verify`, `/mfa/resend`, `/refresh`, `/logout`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password`, `/password/change`, `/password-strength`; `GET /api/auth/me`; MFA: `GET /mfa`, `POST /mfa/totp/setup`, `/mfa/totp/confirm`, `/mfa/backup-codes`; `GET/DELETE /sessions` |
| Requests | `GET /api/catalog`, `GET/POST /api/requests`, `GET /api/requests/{id}`, `POST …/resubmit`, `POST …/cancel` |
| Approvals | `GET /api/approvals/queue`, `GET /api/approvals/{id}/context`, `POST /api/approvals/{id}/action` (`APPROVE`, `REJECT`, `NARROW`, `REQUEST_MODIFICATION`) |
| Grants | `GET /api/grants`, `POST /api/grants/{id}/token/reveal`, `/revoke`, `/restrict` |
| Resources | `GET /api/resources`, `GET/PATCH /api/resources/{id}` |
| Gateways | `POST /api/gateway/resources/{id}/access`, `POST /api/agent-gateway/invoke` |
| People | `GET /api/departments`, `/projects`, `/employees`, `/employees/{id}` with `/analytics`, `/timeline` and `/evidence`; `GET /api/leaderboard`; `POST /api/employees/{id}/deactivate` and `/transfer` |
| Drift | `GET /api/drift`, `POST /api/drift/scan`, `POST /api/drift/{id}/action` |
| Emergency | `GET/POST /api/emergency`, `GET …/{id}/actions`, `POST …/{id}/revoke`, `POST …/{id}/review` |
| Recertification | `GET /api/reviews`, `POST /api/reviews/campaigns`, `/process-overdue`, `/{id}/decide` |
| Agents | `GET /api/agents`, `POST …/{id}/simulate`, `/status`, `/rotate-key`; `PUT …/{id}/permissions` |
| Audit | `GET /api/audit/events`, `GET /api/audit/verify`, `GET /api/audit/export.csv`; `GET /api/alerts`, `POST /api/alerts/{id}/status` |
| Admin | `GET /api/dashboard`; `GET/POST/PUT/DELETE /api/policies`; `GET /api/admin/users`, `PUT /api/admin/users/{id}/roles`, `GET /api/admin/login-attempts`; `GET /api/settings/security`; `GET /api/search` |
| Notifications | `GET /api/notifications`, `POST /{id}/read`, `/{id}/unread`, `/read-all`; WebSocket at `/api/ws/notifications` |

**Example: use a token at the gateway**

```bash
curl -X POST http://localhost:8000/api/gateway/resources/<resource-id>/access \
  -H "Authorization: Bearer <access-jwt>" -H "X-Access-Token: SIM-ACCESS-XXXXXXX.<secret>" \
  -H "Content-Type: application/json" -d '{"action":"READ","purpose":"MODEL_TESTING"}'
```

**Example: an AI agent calls a tool**

```bash
curl -X POST http://localhost:8000/api/agent-gateway/invoke \
  -H "X-Agent-Id: AGT-SUP-01" -H "X-Agent-Key: agk_demo_support_agent_key_0002" \
  -H "Content-Type: application/json" -d '{"tool":"kb.search","resource":"RES-FIN-003","action":"READ"}'
# → 403 {"decision":"DENIED","code":"RESOURCE_NOT_ALLOWED", ...}  (the support agent cannot touch the Finance Ledger)
# An unapproved tool such as "sql.query" returns TOOL_NOT_ALLOWED.
```

## Local development

**macOS, one command (no Docker):** `./run-local.sh` installs Postgres 16 and Redis with Homebrew if needed, creates the venv, runs migrations, seeds the demo data the first time and starts both servers. Use `./run-local.sh --reset` for fresh demo data, or `./run-local.sh --clean` for an empty start (only the 5 people, resources, policies and AI agents; no grants, requests, drift cases or emergency history). Celery is not needed locally; the backend's in-process scheduler runs the expiry, recert and drift jobs.

Manual steps:

You need Python 3.12 or later, Node 20 or later, PostgreSQL 14 or later, and Redis 6 or later.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
createdb astitva                       # or set DATABASE_URL
alembic upgrade head
python -m app.seed                     # --reset to recreate, --reset --clean for no grants/requests
uvicorn app.main:app --reload --port 8000
# the in-process scheduler runs expiry, recert and drift jobs in dev; or run Celery:
celery -A app.worker.celery_app worker -l INFO
celery -A app.worker.celery_app beat -l INFO

# frontend
cd frontend
npm install
npm run dev                            # http://localhost:3000 (proxies /api to :8000)
npm run typecheck && npm run build
```

## Configuration

All settings are environment variables. See [`.env.example`](.env.example) for the full annotated list. The most important ones:

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` turns on the startup guard, Secure cookies and no dev outbox |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/astitva` | |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `JWT_SECRET`, `TOKEN_PEPPER` | `dev-only-…` | **Must** be replaced in production. Rotating `TOKEN_PEPPER` invalidates stored tokens and encrypted TOTP secrets. |
| `COOKIE_SECURE`, `COOKIE_SAMESITE` | `false`, `strict` | |
| `LOGIN_MAX_FAILURES`, `LOCKOUT_BASE_SECONDS`, `LOCKOUT_MAX_SECONDS` | 5, 60, 1800 | |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | `none` | Optional explanations only |
| `ENABLE_INPROCESS_SCHEDULER` | `true` | Set to `false` when Celery beat runs (Docker does this) |
| `BACKEND_URL` (frontend, at build time) | `http://localhost:8000` | Target of the `/api` rewrite |
| `NEXT_PUBLIC_WS_URL` | empty, which means `ws://<host>:8000` | Set it behind a reverse proxy |

## Tests and results

```bash
cd backend && pytest -q        # uses database astitva_test and an in-memory fakeredis (Lua enabled)
```

**Latest run: 101 passed, 0 failed (20 s).** All 15 required scenarios are covered, plus additional platform tests:

| # | Scenario | Test |
|---|---|---|
| 1 | Full chain (Manager, then Security Manager) activates access and issues a token | `test_01_full_approval_chain_activates_access` |
| 2 | Requester cannot approve their own request | `test_02_requester_cannot_approve_own_request` |
| 3 | Expired token is rejected, and the scheduler expires grants | `test_03_…`, `test_03b_scheduler_expires_grants` |
| 4 | Unauthorized resource access is blocked | `test_04_unauthorized_resource_access_blocked` |
| 5 | Token is bound to identity, purpose and permission | `test_05_token_is_purpose_identity_and_permission_bound` |
| 6 | Conflicting approvals are blocked by SoD | `test_06_conflicting_approvals_blocked` |
| 7 | Permission drift is detected and remediated | `test_07_permission_drift_detected_and_remediated` |
| 8 | Break-glass access alerts, is monitored, and is revoked | `test_08_breakglass_alert_monitor_and_revoke` |
| 9 | Audit tampering is detected | `test_09_audit_tampering_detected` |
| 10 | Five failures lock the account temporarily; errors are generic; IP token bucket | `test_10_…`, `test_10b_…` |
| 11 | MFA cannot be bypassed; TOTP enrolment and login | `test_11_…`, `test_11b_…` |
| 12 | Support agent is blocked from the financial database | `test_12_support_agent_blocked_from_financial_database` |
| 13 | Deactivation revokes grants and sessions | `test_13_deactivation_revokes_grants_and_sessions` |
| 14 | Manager analytics match recorded task events | `test_14_manager_analytics_match_recorded_task_events` |
| 15 | Overdue recertification raises an alert | `test_15_overdue_recertification_raises_alert` |

The additional tests in `tests/test_platform.py` cover:

- CSRF enforcement and refresh-token reuse detection
- logout invalidation
- the risk engine on a purpose mismatch
- narrow scope and request modification
- RBAC route protection
- registration with email verification and password policy
- password reset revoking sessions
- the dashboard reflecting live events

`tests/test_revoke.py` covers removing access: the Manager narrows then revokes a team member's grant (audit, new token, notification, "revoked" on the request), employees get 403 on their own and others' grants, and the Security Manager can revoke any grant.

`tests/test_routing_guardrails.py` covers the guardrails: the 30/31/60/61 boundaries, CONFIDENTIAL/RESTRICTED/CRITICAL never auto-approved, WRITE/DELETE/ADMIN never auto-approved, an anomaly forcing security review, guardrails holding even when the policy row is loosened in the database, the API refusing to remove them, and the stored "why this path" reason.

`tests/test_risk_engine.py` covers the risk fixes: rejected requests are not violations; confirmed vs unreviewed vs false-positive alerts; denied operations as a separate weak signal; no events after the request are used; velocity excludes the current request and respects the person's baseline; the history cap; the Isolation Forest reporting "not enough data", and with a 15-person population flagging the outlier reproducibly from a cached model; weights read from the central config; score and level on the shared scale.

`tests/test_priority.py` covers priority with a fixed clock: every waiting and deadline band edge, impact mapping, level edges, a worked formula example, minimum/maximum, priority rising over time, naive datetimes, deadline validation (past, no timezone, bad impact, IST to UTC), the API ignoring a client-sent score, the requester editing deadline/impact (audited, others get 404), priority never changing risk or path, queue sorting and filters, and closed requests having no priority.

`tests/test_routing.py` covers risk-based routing: low risk auto-approved by policy with audit + manager FYI, medium needs the Manager only, high needs Manager then Security Manager, CRITICAL never auto-approved, and threshold updates (422 on invalid, 403 for the Manager, audited).

**Other verification performed**

- `tsc --noEmit` and `next build` pass with no errors (22 routes).
- A Playwright run went through the real UI end to end:
  1. Kavya submitted a request from the form.
  2. It appeared in Priya's queue, and she approved it.
  3. It then appeared in Meera's queue, and she approved it.
  4. Kavya's token was **ALLOWED** with the right purpose and refused with **TOKEN_PURPOSE_MISMATCH** with the wrong one.
- A second Playwright run as Kavya submitted three requests from the form: Internal Analytics API READ 8h (risk 17, auto-approved, Priya got the FYI notification), Customer Support AI Dataset READ+WRITE 7 days (risk 51, Manager only) and Fraud Detection Model READ/EXECUTE/WRITE 7 days (risk 91, Priya then Meera). Meera also opened the routing card on the Policies page.
- All 13 main screens were loaded for each of the 5 accounts with zero page errors. Screens outside a role return a server-side 403.
- The full `docker compose` stack (postgres, redis, backend, worker, beat, frontend) was built and run earlier. That smoke test ran against the previous, larger demo org; the Dockerfiles and compose file have not changed since.
- After seeding, `GET /api/audit/verify` reports the chain as valid.

## Production deployment

1. **Secrets.** Generate `JWT_SECRET` and `TOKEN_PEPPER` (48+ random bytes each) and store them in your secret manager. Set `APP_ENV=production`.
2. **TLS.** Terminate HTTPS at a reverse proxy or load balancer. Serve the frontend and `/api` from **one origin**: route `/api/*` and `/api/ws/*` (WebSocket upgrade) to the backend, and set `NEXT_PUBLIC_WS_URL=wss://your-host`. Cookies are then first-party, `Secure` and `SameSite=Strict`.
3. **Data stores.** Use managed PostgreSQL with backups and point-in-time recovery, and managed Redis with authentication and TLS. Run `alembic upgrade head` as a release step. Set `SEED_DEMO=false`.
4. **Processes.** Run the API with several uvicorn workers behind the proxy, one Celery beat (singleton), and one or more workers. Set `ENABLE_INPROCESS_SCHEDULER=false`.
5. **Integrations to replace.**
   - Swap the dev outbox for a real email/SMS provider (`services/notify.py` and the OTP senders in `services/auth.py`).
   - Configure a CAPTCHA provider in `CaptchaVerifier`.
   - Connect the HR directory for joiner/mover/leaver events in place of the seed.
   - Point the gateway adapters at real resource connectors.
6. **Audit.** Export audit events regularly (CSV or a SIEM forwarder) to WORM storage. The hash chain shows tampering, but it can't prevent an attacker with DBA access from truncating the table and its head together. Schedule `GET /api/audit/verify` and alert on failure.
7. **Hardening.** Use a restricted DB role for the app with no DDL at runtime, and put a WAF and per-route rate limits at the edge. Run the containers as non-root (the images already do).

## Known limitations

- **Simulated integrations.** Email, SMS and CAPTCHA are adapters with development stand-ins. Resource "access" returns mock payloads, and agent tools are simulated.
- **No SSO/SAML/OIDC.** Federation with an external IdP and SCIM provisioning are not implemented. Users come from the seed or self-registration, and registration needs email verification.
- **Single tenant.** The organisation switcher in the UI is presentational. The data model is single-organisation.
- **Risk model.** The anomaly detector (IsolationForest) needs at least 12 active people, so with the 5-person demo it reports "not enough data" and adds nothing. Its behaviour with a larger population is covered by a test with synthetic users. Calibrate the weights on real data before relying on them. LLM explanations are off by default.
- **Login.** The existing email + password + MFA login is unchanged. NamoID hosted login is not implemented: it needs the app's NamoID console details (credentials and redirect settings), which were not provided, so it has not been built or tested.
- **Audit chain** proves integrity but not completeness against a privileged DB operator. Ship events off-box for that guarantee (see deployment).
- **Notifications** use a Redis pub/sub fan-out. Clients that are offline catch up through the REST list, not by replaying the WebSocket stream.
- **Tests** run against Postgres with fakeredis. Load and performance testing and frontend unit tests are not included. The UI was verified with Playwright smoke runs rather than a full end-to-end suite.
- **No Content-Security-Policy yet.** Add a strict CSP at the reverse proxy (Next.js inline runtime scripts need a nonce or hash).
- **Accessibility.** Built on Radix primitives with keyboard support and labelled controls, but it has not been formally audited against WCAG.

## Repository layout

```
backend/
  app/            FastAPI app: api/, services/, security/, core/, models.py, seed.py, worker.py
  alembic/        migrations
  tests/          pytest suites (scenarios + platform)
frontend/
  src/app/        Next.js routes: (auth)/ login, register, verify, reset · (app)/ all product screens
  src/components/ shell, charts, status badges, request detail, UI primitives
  src/lib/        api client (CSRF + refresh), session/RBAC context, utils
docker-compose.yml, .env.example
```
