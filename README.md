# ASTITVA

**[Powered by NamoID](https://namoid.in)** ·
[NamoID documentation](https://docs.namoid.in) ·
[Challenge catalog](https://challenges.namoid.in)

> Built on the NamoID identity platform for the **NamoID Community Challenges** program.

This repository is a contributor-owned response to the
`responsible-ai-access-gate` problem statement. It was created from the official
[NamoID challenge template](https://github.com/namoidhq/namoid-challenge-template).

This project is an independent community build. It is not an official
NamoID product, security recommendation, or endorsement.

## NamoID integration

This project must use **NamoID Hosted Auth as the application's sign-in
system**. Hosted Auth is the application's authentication system, not a
social-login button.

**Status: pending NamoID Console app.** The integration is wired in only once
the NamoID Console application exists, so it is not claimed as working yet.

Planned setup:

- **Application/client type:** confidential web application. The FastAPI
  backend runs the Authorization Code flow (with PKCE) and keeps the client
  secret server-side; the browser never sees it.
- **Issuer/environment:** `NAMOID_ISSUER`, `NAMOID_CLIENT_ID` and
  `NAMOID_CLIENT_SECRET` come from the local `.env` (see `.env.example`).
  Nothing real is committed.
- **Callback path:** `http://localhost:8000/api/auth/namoid/callback` for local
  development.
- **Application session:** after the code exchange the backend maps the NamoID
  identity to an ASTITVA user (requester, manager, risk reviewer or resource
  owner) and issues ASTITVA's own HttpOnly session and refresh cookies. The
  NamoID tokens are not stored in the browser.
- **User journey:** Sign in → redirect to NamoID Hosted Auth → callback →
  ASTITVA dashboard for that role → request / review / use / revoke access.

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

Full product guide: [docs/ASTITVA-GUIDE.md](./docs/ASTITVA-GUIDE.md). Demo
walkthrough: [docs/demo-test-workflow.md](./docs/demo-test-workflow.md).

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
- **Separation of duties:** nobody approves their own request.
- Active grants, decision history and a hash-chained audit trail are visible in
  the UI.

Tests (`backend/tests`) cover separation of duties, expiry, narrowed scope,
emergency revocation, routing guardrails, risk engine and priority.

## Known limitations

- **NamoID Hosted Auth is not wired in yet.** It waits for the NamoID Console
  application values. Until then the app uses its own email + password + MFA
  login with seeded demo accounts.
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
