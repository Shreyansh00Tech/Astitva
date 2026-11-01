import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import access, admin, auth, governance, graph, messages, workspace
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("astitva")
settings = get_settings()


async def _scheduler():
    from app.services import maintenance

    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        try:
            await asyncio.to_thread(maintenance.expire_and_warn)
            if tick % 60 == 0:
                await asyncio.to_thread(maintenance.recertification)
            if tick % 360 == 0:
                await asyncio.to_thread(maintenance.drift_scan)
        except Exception as exc:
            log.warning("in-process scheduler error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if settings.enable_inprocess_scheduler and settings.app_env != "test":
        task = asyncio.create_task(_scheduler())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="ASTITVA API",
    version="1.0.0",
    description="ASTITVA - Intelligent Identity, Access Governance & AI Security Platform (simulated Nexora Technologies environment).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Access-Token", "Authorization", "X-Agent-Id", "X-Agent-Key"],
)


# Periodic jobs on serverless hosts: each one runs at most once per interval, triggered by normal
# traffic, before the request that triggered it is answered (so expired access is never served).
_TICKS = (("expire", 60, "expire_and_warn"), ("recert", 3600, "recertification"), ("drift", 6 * 3600, "drift_scan"))


def _run_due_ticks() -> None:
    from app.security.ratelimit import get_redis
    from app.services import maintenance

    r = get_redis()
    for name, every, fn in _TICKS:
        if r.set(f"astitva:tick:{name}", "1", nx=True, ex=every):
            try:
                getattr(maintenance, fn)()
            except Exception as exc:
                log.warning("periodic job %s failed: %s", name, exc)


@app.middleware("http")
async def hosted_setup_and_ticks(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        if settings.auto_setup:
            from app import deploy_setup

            try:
                await asyncio.to_thread(deploy_setup.ensure)
            except Exception as exc:
                log.exception("database setup failed")
                return JSONResponse({"detail": "The database is still being set up, or DATABASE_URL is wrong "
                                               f"({type(exc).__name__}). Open /api/health and the function logs."},
                                    status_code=503)
        if settings.enable_request_ticks:
            try:
                await asyncio.to_thread(_run_due_ticks)
            except Exception as exc:
                log.warning("periodic jobs skipped: %s", exc)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Cache-Control", "no-store")
    if settings.cookie_secure:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    # Login rate limits and sessions need Redis and Postgres. Fail closed, but say what is wrong.
    import redis
    from sqlalchemy.exc import OperationalError

    if isinstance(exc, redis.exceptions.ConnectionError):
        return JSONResponse({"detail": "Redis is not running, so sign-in is blocked. Start it (Mac: brew services start redis) "
                                       "and try again."}, status_code=503)
    if isinstance(exc, OperationalError):
        return JSONResponse({"detail": "The database is not reachable. Start Postgres (Mac: brew services start postgresql@16) "
                                       "and try again."}, status_code=503)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


for r in (auth.router, access.router, governance.router, admin.router, graph.router, messages.router, workspace.router):
    app.include_router(r)


@app.get("/api/health", tags=["platform"])
def health():
    from sqlalchemy import text

    from app.core.db import engine
    from app.security.ratelimit import get_redis

    status = {"api": "ok"}
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        status["database"] = "ok"
    except Exception:
        status["database"] = "down"
    try:
        get_redis().ping()
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "down"
    if os.environ.get("VERCEL") and "down" in status.values():
        # Names only (never values), so a missing storage connection is easy to spot.
        status["env_seen"] = sorted(k for k in os.environ if any(t in k for t in ("DATABASE", "POSTGRES", "REDIS", "KV_")))
    return status
