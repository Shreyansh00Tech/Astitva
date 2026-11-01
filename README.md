# ASTITVA

**[Powered by NamoID](https://namoid.in)** ·
[NamoID documentation](https://docs.namoid.in) ·
[Challenge catalog](https://challenges.namoid.in)

> Built on the NamoID identity platform for the **NamoID Community Challenges** program.

This repository is a contributor-owned response to the
`responsible-ai-access-gate` problem statement. It was created from the official
[NamoID challenge template](https://github.com/namoidhq/namoid-challenge-template).

> 📘 **New here? Read the [ASTITVA Handbook](./HANDBOOK.md)**: how the service works, how a new employee is
> onboarded, what each role does, and the request → approval → expiry → revoke flow. Live demo:
> <https://astitva-gray.vercel.app>.

This project is an independent community build. It is not an official
NamoID product, security recommendation, or endorsement.

## NamoID integration

This project must use **NamoID Hosted Auth as the application's sign-in
system**. Hosted Auth is the application's authentication system, not a
social-login button.

ASTITVA's users sign in with **Continue with NamoID** on the login page.

- **Application/client type:** web application. The FastAPI backend runs the
  OpenID Connect **Authorization Code flow with PKCE (S256)**. If the NamoID app
  has a Client Secret, the backend sends it with `client_secret_basic`; without
  one it works as a public client with PKCE. The secret only ever lives in the
  local `.env`.
- **Issuer/environment:** sandbox issuer (also the built-in default, so it works without a `.env`)
  `https://astitva-0efc7e.sandbox.namoid.in` (endpoints are read from its
  `/.well-known/openid-configuration`). Set `NAMOID_ISSUER` and
  `NAMOID_CLIENT_ID` in `.env` (see `.env.example`).
- **Callback path:** `http://localhost:8000/api/auth/namoid/callback`. It must
  be registered in the NamoID Console exactly like this.
- **Validation:** `state` (CSRF), `nonce`, PKCE verifier, the RFC 9207 `iss`
  parameter, and the ID token's RS256 signature (JWKS), issuer, audience and
  expiry are all checked. A verified email is required.
- **Roles come from NamoID.** Assign each user a role in the NamoID Console:
  `requester`, `manager`, `risk_reviewer`, `resource_owner` or
  `security_manager`. At every sign-in ASTITVA reads the roles from the ID token
  (or userinfo), from `roles`, `groups`, `organizations[].roles` or the claim
  set in `NAMOID_ROLES_CLAIM`, and makes them the user's ASTITVA roles. Changes
  are written to the audit trail. If NamoID sends no role, the user keeps their
  ASTITVA roles (new users start as Employee), and `NAMOID_USER_MAP` can link a
  NamoID email to a seeded demo persona.
- **Application session:** ASTITVA then issues its own HttpOnly,
  SameSite=Strict session cookies. NamoID tokens are never sent to the browser
  or stored.
- **User journey:** Login → Continue with NamoID → NamoID Hosted Auth sign-in →
  callback → ASTITVA dashboard for that role (requester, manager, risk reviewer
  or resource owner) → request, review, use or revoke access.

The flow is covered by `backend/tests/test_namoid.py` (NamoID responses are
mocked there).

## Community project metadata

- **Challenge ID:** `responsible-ai-access-gate`
- **Contributor:** Ishan Jha
- **Live demo:** Local only for now (`docker compose up --build`)
- **Final commit:** Added at submission time
- **Time spent:** About 6 hours
- **License:** MIT

## Start here

1. Create your repository using **[Use this template](https://github.com/namoidhq/namoid-challenge-template/generate)**.
2. In the new repository, run:

```bash
npm run setup -- --challenge=responsible-ai-access-gate --name="Your Name" --title="Your Project" --repo=https://github.com/you/project
npm run check
```

Replace `responsible-ai-access-gate` with the ID shown in the selected problem statement.
Setup removes
the remaining template placeholders and records machine-readable attribution in
[`namoid-challenge.json`](./namoid-challenge.json).

3. [Create an application in the NamoID Console](https://console.namoid.in/login).
4. Configure its callback URL and integrate NamoID Hosted Auth into your POC.
5. Build, test, deploy, and submit the pinned commit.

## Run locally

The application lives in `backend/` (FastAPI, Postgres, Redis, Celery) and
`frontend/` (Next.js). The root `index.html` is the template's project page for
GitHub Pages.

```bash
cp .env.example .env          # local values only, never commit .env
docker compose up --build     # web: http://localhost:3000, API docs: http://localhost:8000/docs
```

Without Docker (macOS/Linux): `./run-local.sh --clean`.

Tests:

```bash
cd backend && pytest -q
```

Template metadata check: `npm run check`. Template starter page: `npm run dev`
(http://localhost:8080).

Product handbook: [HANDBOOK.md](./HANDBOOK.md). Full product guide: [docs/ASTITVA-GUIDE.md](./docs/ASTITVA-GUIDE.md). Demo
walkthrough: [docs/demo-test-workflow.md](./docs/demo-test-workflow.md).

## Deploy on Vercel

One Vercel project serves both the UI and the API (Vercel Services, `vercel.json`), with Neon Postgres and Upstash Redis from the Vercel dashboard. Steps: [docs/DEPLOY-VERCEL.md](docs/DEPLOY-VERCEL.md).

## What works

ASTITVA is a purpose-bound access request and approval gate for fictional
Nexora Technologies models, datasets and databases.

- A requester names a mock model or dataset, purpose, duration and permissions.
- A risk engine scores it. Low risk on non-sensitive resources is auto-approved
  by deterministic policy; sensitive resources, WRITE/DELETE/ADMIN and anomalies
  always need a human. Medium risk goes to the manager, high risk to the manager
  and then the risk reviewer.
- Reviewers can approve, **narrow** (drop permissions or shorten time) or reject.
- Approved access issues a short-lived token bound to person, resource, purpose
  and permissions. A gateway refuses use outside the approved purpose.
- Grants **expire automatically**; extensions need a new request (no silent
  extension). Managers and the security manager can **revoke** fully or drop
  single permissions; emergency (break-glass) access is monitored and revocable.
- **Access dependency graph** (Manager and Security Manager only): pick a model
  and see every user, AI agent and API that depends on it, including indirect
  impact through downstream APIs. Revoke from the graph and compare **before /
  after**. A manager can only cut their own team's grants; agents and API links
  need the security manager. API links are simulated.
- **Separation of duties:** nobody approves their own request.
- **Access ends with the project:** every request is linked to the requester's
  current project, and a grant never outlives the project end date (asked for
  30 days, project ends in 15, so access ends in 15). The employee Overview shows
  the current project, due date and team, plus one timeline with the project
  start, submission and end dates and each grant's start and expiry.
- Active grants, decision history and a hash-chained audit trail are visible in
  the UI.

Tests (`backend/tests`) cover separation of duties, expiry, narrowed scope,
emergency revocation, routing guardrails, risk engine, priority and project-bound expiry.

## Known limitations

- NamoID sign-in is tested with mocked NamoID responses. The live sandbox flow
  must be run from a browser on a local machine. The email + password + MFA
  login is kept as a demo fallback for the seeded accounts.
- Signing out ends the ASTITVA session only, not the NamoID session.
- All integrations (email, resources, AI agents) are simulated.
- See [docs/ASTITVA-GUIDE.md](./docs/ASTITVA-GUIDE.md#known-limitations) for the
  full list.

## AI and external resources

Built with substantial help from Claude (Anthropic) for code, tests and docs.
Main libraries: FastAPI, SQLAlchemy, Alembic, Celery, scikit-learn, Next.js,
React, Tailwind CSS, Radix UI, Recharts, SWR.

## NamoID attribution

Keep the factual challenge attribution in this README,
`namoid-challenge.json`, and the deployed page. You may change the surrounding
design and implementation. Attribution must not imply that NamoID authored,
audited, or endorses your solution.

## Submit to the catalog

Commit and push the exact version you want reviewed, then copy its full SHA:

```bash
git push
git rev-parse HEAD
```

Open the [Submit a community build](https://github.com/namoidhq/namoid-challenges/issues/new?template=community-build.yml)
form and paste the 40-character SHA into **Pinned commit SHA**. This identifies
one immutable version even if you continue changing the repository later. You
can request a catalog update or removal later.
