"""Orchestrates one pipeline run: scrape -> store -> analyze -> score."""
import logging
import threading

from . import analyzer, config, database, scraper

log = logging.getLogger("pipeline")

# In-memory status the UI polls while a run is in progress.
status = {
    "running": False,
    "phase": "idle",
    "fetched": 0,
    "new_articles": 0,
    "analyzed": 0,
    "to_analyze": 0,
    "relevant_found": 0,
    "last_error": None,
}
_lock = threading.Lock()


def run_pipeline() -> dict:
    with _lock:
        if status["running"]:
            return status
        status.update(running=True, phase="scraping", fetched=0, new_articles=0,
                      analyzed=0, to_analyze=0, relevant_found=0, last_error=None)

    run_id = database.start_run()
    try:
        articles = scraper.scrape_all_sources()
        status["fetched"] = len(articles)

        new_count = 0
        for art in articles:
            if database.insert_article(art):
                new_count += 1
        status["new_articles"] = new_count

        pending = database.get_unanalyzed(config.MAX_ANALYZE_PER_RUN)
        status["to_analyze"] = len(pending)
        status["phase"] = "analyzing"

        relevant_found = 0
        for art in pending:
            if config.FETCH_FULL_TEXT and not art.get("content"):
                art["content"] = scraper.fetch_full_text(art["url"])
            analysis, mode = analyzer.analyze(art)
            database.save_analysis(art["id"], analysis, mode)
            if analysis.get("relevant"):
                relevant_found += 1
            status["analyzed"] += 1
        status["relevant_found"] = relevant_found

        database.finish_run(run_id, "done", fetched=len(articles),
                            new_articles=new_count, analyzed=len(pending),
                            relevant_found=relevant_found)
        status["phase"] = "done"
    except Exception as e:
        log.exception("Pipeline run failed")
        status["last_error"] = str(e)
        status["phase"] = "error"
        database.finish_run(run_id, "error", error=str(e))
    finally:
        status["running"] = False
    return status


def run_pipeline_async() -> bool:
    """Kick off a run in a background thread. Returns False if already running."""
    if status["running"]:
        return False
    threading.Thread(target=run_pipeline, daemon=True).start()
    return True
