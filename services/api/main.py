import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.session import engine
from db.migrations import run_migrations
from models.base import Base
import models  # noqa: F401 — triggers registration of every SQLAlchemy model
from routers import auth, my_pages, recommendations, reels, templates, exports, ai, files, niches, jobs, ig_oauth, scheduled_reels


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations(engine)
    yield
    await engine.dispose()


app = FastAPI(title="Viral Reel Engine v2", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(","),
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

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


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
