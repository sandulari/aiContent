import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.session import engine
from db.migrations import run_migrations
from db.seed_master_templates import seed_master_templates
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(","),
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# CSRF (Task 2.1) — double-submit cookie on mutating routes. Must be
# added AFTER CORS so the cookie is set on the response after CORS
# headers have been merged. Order matters: Starlette runs middleware
# in the REVERSE order they're added, so this entry runs before
# CORSMiddleware in the request path and after it in the response path.
from middleware.csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware)

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


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
