# Deploy ASTITVA on Vercel (one project)

ASTITVA deploys to Vercel as **one project** using Vercel Services. The Next.js UI and the FastAPI API share one
domain: `/api/*` goes to FastAPI and everything else goes to Next.js. `vercel.json` at the repo root sets this up.
Postgres (Neon) and Redis (Upstash) are added from the Vercel dashboard and connect to the same project.
You do not deploy anything separately.

All data is fictional (Nexora Technologies). Nothing connects to real systems.

## 1. Import the repo

1. Vercel, **Add New... > Project**, then import `Shreyansh00Tech/Astitva` (branch `main`).
2. **Root Directory:** `./`. **Application Preset:** `Services`. Vercel shows `backend` (FastAPI, `/api`) and
   `frontend` (Next.js, `/`).
3. Leave **Environment Variables** empty, then click **Deploy**. The first deploy has no database yet, so the
   site loads but sign-in fails. Step 2 fixes that.

## 2. Add Postgres and Redis (one time)

On the project page, open **Storage**:

1. **Create Database > Neon (Serverless Postgres)**, free plan, region close to you, and connect it to this
   project for all environments. This adds `DATABASE_URL`, `DATABASE_URL_UNPOOLED` and others.
2. **Create Database > Upstash for Redis** (or browse the Marketplace for "Upstash"), free plan, and connect
   it to this project. This adds `KV_URL` / `REDIS_URL`.
3. **Deployments**, then the latest deployment, then **... > Redeploy**.

Open `https://<project>.vercel.app`. The first API call creates the tables and seeds the 5 demo people, which
takes about 10 seconds once. Sign in with any demo account and password `Nexora@Demo2026`. The sign-in code
appears on the login page from the simulated inbox.

## 3. NamoID redirect URL

In the NamoID Console, open your app and add this to **Redirect URIs** (keep the localhost one for local dev):

```
https://<project>.vercel.app/api/auth/namoid/callback
```

If you add a custom domain later, add that domain's callback too, and set `FRONTEND_URL` and
`NAMOID_REDIRECT_URI` in Vercel to that domain.

## Environment variables

None are required. On Vercel the backend fills these in by itself:

| Variable | Default on Vercel |
| --- | --- |
| `DATABASE_URL` | From Neon (`postgres://` is converted to the psycopg driver) |
| `REDIS_URL` | `REDIS_URL`, otherwise `KV_URL` from Upstash |
| `FRONTEND_URL`, `CORS_ORIGINS` | `https://<production domain>` |
| `NAMOID_REDIRECT_URI` | `https://<production domain>/api/auth/namoid/callback` |
| `APP_ENV` | `demo` (HTTPS-only cookies, and the simulated inbox stays on so demo sign-in codes show) |
| `JWT_SECRET`, `TOKEN_PEPPER` | Derived from the database URL if neither is set |

Optional:

| Variable | Use |
| --- | --- |
| `JWT_SECRET`, `TOKEN_PEPPER` | Set both (`openssl rand -hex 32`) for your own secrets. Changing them signs everyone out. |
| `SEED_MODE` | `clean` (default: only the 5 people), `demo` (with request history), or `none` |
| `NAMOID_CLIENT_SECRET` | Only if your NamoID app is a confidential client |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | AI explanations (default: rule engine only) |

## Reset the hosted database

From your Mac, in `backend/`, using the **unpooled** Neon URL from Vercel (Storage > Neon > `.env.local` tab):

```bash
DATABASE_URL='postgresql://...neon.tech/neondb?sslmode=require' python -m app.seed --reset --clean
```

Use `--reset` without `--clean` for the version with demo history.

## What is different from Docker

| Docker / run-local.sh | Vercel |
| --- | --- |
| WebSockets push notifications and chat instantly | No WebSockets on Vercel functions. The app polls instead: the bell every 10 s, the open chat every 3 s, and the unread badge every 8 s. Toasts and the Security Manager's emergency beep still work. |
| Celery beat runs expiry every minute, recertification hourly, and drift every 6 h | Each job runs at most once per interval on the back of normal traffic, before the request is answered, so expired access is never served. No cron is needed, and it works on the Hobby plan. |
| Always running | The first request after some idle time takes a few seconds (cold start). |

Local development is unchanged: `docker compose up` or `./run-local.sh` still use WebSockets and Celery.
