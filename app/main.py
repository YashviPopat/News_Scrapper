"""FastAPI application: JSON API + dashboard."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analyzer, config, database, pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

STATIC_DIR = Path(__file__).parent / "static"


async def _auto_scrape_loop():
    while True:
        await asyncio.sleep(config.AUTO_SCRAPE_MINUTES * 60)
        pipeline.run_pipeline_async()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    task = None
    if config.AUTO_SCRAPE_MINUTES > 0:
        task = asyncio.create_task(_auto_scrape_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Gujarat News Intelligence", lifespan=lifespan)


class Preferences(BaseModel):
    target_state: str = "Gujarat"
    interests: list[str]
    ignore_topics: list[str]
    min_score_to_keep: int = 40
    notes: str = ""


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "llm_enabled": config.LLM_ENABLED,
        "provider": config.LLM_PROVIDER if config.LLM_ENABLED else None,
        "model": config.LLM_MODEL if config.LLM_ENABLED else None,
    }


@app.post("/api/scrape")
def trigger_scrape():
    started = pipeline.run_pipeline_async()
    if not started:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")
    return {"started": True}


@app.get("/api/scrape/status")
def scrape_status():
    return pipeline.status


@app.get("/api/articles")
def list_articles(relevant_only: bool = False, min_score: int = 0,
                  domain: str | None = None, search: str | None = None,
                  limit: int = 200):
    return database.query_articles(
        relevant_only=relevant_only, min_score=min_score,
        domain=domain or None, search=search or None, limit=min(limit, 500),
    )


@app.get("/api/stats")
def stats():
    return database.get_stats()


@app.get("/api/preferences")
def get_preferences():
    return config.load_user_profile()


@app.put("/api/preferences")
def update_preferences(prefs: Preferences):
    config.save_user_profile(prefs.model_dump())
    analyzer.refresh_system_prompt()
    return {"saved": True}


@app.get("/api/sources")
def list_sources():
    return config.load_json(config.SOURCES_PATH)["sources"]


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
