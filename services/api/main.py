import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from db.session import engine
from db.migrations import run_migrations
from db.seed_master_templates import seed_master_templates
from middleware.cors_config import cors_kwargs
from models.base import Base
import models  # noqa: F401 — triggers registration of every SQLAlchemy model
from routers import auth, my_pages, recommendations, reels, templates, exports, ai, files, niches, jobs, ig_oauth, scheduled_reels, reference_pages, discovery_filters, discovery_items


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations(engine)
    await seed_master_templates(engine)
    yield
    await engine.dispose()


app = FastAPI(title="Viral Reel Engine v2", version="2.0.0", lifespan=lifespan)

# CORS (Task 2.5) — strict allowlist driven by ALLOWED_ORIGINS env.
# No '*' origin allowed when credentials are enabled (browsers ignore
# it anyway). Methods + request headers + exposed response headers are
# enumerated explicitly — see middleware/cors_config.py for the lists.
app.add_middleware(CORSMiddleware, **cors_kwargs(allow_credentials=True))

# Idempotency (Task 2.2) — Idempotency-Key header support for mutating
# routes. Added BEFORE CSRF so CSRF still validates incoming requests
# (Starlette runs middleware in REVERSE order — last added runs first
# in the request path). A cached idempotent replay never bypasses CSRF.
from middleware.idempotency import IdempotencyMiddleware
app.add_middleware(IdempotencyMiddleware)

# CSRF (Task 2.1) — double-submit cookie on mutating routes. Must be
# added AFTER CORS so the cookie is set on the response after CORS
# headers have been merged. Order matters: Starlette runs middleware
# in the REVERSE order they're added, so this entry runs before
# CORSMiddleware in the request path and after it in the response path.
from middleware.csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware)

# Security headers (Task 2.6) — added LAST so it runs FIRST in request
# path and LAST in response path. That way every response — including
# the CSRF 403, the auth 401, and validation 422s — gets CSP / HSTS /
# nosniff / frame-deny / referrer / permissions headers on the way out.
from middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(my_pages.router)
app.include_router(recommendations.router)
app.include_router(reels.router)
app.include_router(templates.router)
app.include_router(exports.router)
app.include_router(ai.router)
app.include_router(files.router)
app.include_router(niches.router)
app.include_router(jobs.router)
app.include_router(ig_oauth.router)
app.include_router(scheduled_reels.router)
app.include_router(reference_pages.router)
app.include_router(discovery_filters.router)
app.include_router(discovery_items.router)


_validation_log = logging.getLogger("validation")


@app.exception_handler(RequestValidationError)
async def _log_validation_errors(request: Request, exc: RequestValidationError):
    """Log validation failures with field-level detail so we can debug
    422s from prod without leaking the raw body (which contains
    passwords on /auth/* routes).

    The keys + types are useful for diagnosis; the values aren't —
    Pydantic already tells us which field was missing or malformed.
    """
    errors = exc.errors()
    sanitized_errors = []
    for e in errors:
        # Drop the ``input`` field — it contains the user-submitted
        # value, which on auth routes is a password.
        sanitized_errors.append({
            "type": e.get("type"),
            "loc": e.get("loc"),
            "msg": e.get("msg"),
        })
    _validation_log.warning(
        "422 validation failure on %s %s: %s",
        request.method, request.url.path, sanitized_errors,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
