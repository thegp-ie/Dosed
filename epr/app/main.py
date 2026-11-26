from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, SessionLocal, engine
from .routers import ai, appointments, auth, clinical, governance, inbox, patients, reference

log = logging.getLogger("epr")
STATIC = Path(__file__).resolve().parent.parent / "static"


async def _healthlink_loop(interval: int):
    from .integrations import healthlink
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            await asyncio.to_thread(healthlink.poll, db)
        except Exception:  # keep polling; errors are audited per file
            log.exception("Healthlink poll failed")
        finally:
            db.close()


async def _maintenance_loop():
    """Hourly housekeeping: purge expired AI scribe transcripts and drafts."""
    from . import ai_scribe
    while True:
        await asyncio.sleep(3600)
        db = SessionLocal()
        try:
            await asyncio.to_thread(ai_scribe.purge_expired, db)
        except Exception:
            log.exception("Maintenance failed")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    # Schema creation for first run. Use migrations (Alembic) for upgrades in production.
    Base.metadata.create_all(engine)
    maint = asyncio.create_task(_maintenance_loop())
    task = None
    interval = int(os.environ.get("EPR_HEALTHLINK_POLL_SECONDS", "0"))
    if interval > 0 and settings.healthlink_mode == "directory":
        task = asyncio.create_task(_healthlink_loop(interval))
    yield
    maint.cancel()
    if task:
        task.cancel()


app = FastAPI(title="Dosed EPR", version="0.1.0", lifespan=lifespan,
              docs_url=None if settings.is_production else "/api/docs", redoc_url=None, openapi_url=None
              if settings.is_production else "/api/openapi.json")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    if settings.cookie_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/") or request.url.path.startswith("/v/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never leak stack traces or patient data in error responses.
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal error"}, status_code=500)


for r in (auth.router, patients.router, clinical.router, inbox.router, appointments.router, governance.router,
          reference.router, ai.router):
    app.include_router(r)


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
