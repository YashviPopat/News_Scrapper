"""SQLite storage for articles and pipeline runs."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    source_region TEXT,
    published TEXT,
    fetched_at TEXT NOT NULL,
    description TEXT,
    content TEXT,
    analyzed INTEGER DEFAULT 0,
    analysis_mode TEXT,
    relevant INTEGER,
    overall_score INTEGER,
    confidence REAL,
    domain TEXT,
    priority TEXT,
    origin_state TEXT,
    analysis_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_analyzed ON articles(analyzed);
CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(overall_score);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    fetched INTEGER DEFAULT 0,
    new_articles INTEGER DEFAULT 0,
    analyzed INTEGER DEFAULT 0,
    relevant_found INTEGER DEFAULT 0,
    error TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_article(article: dict) -> bool:
    """Insert a scraped article. Returns True if it was new."""
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO articles (url, title, source, source_region, published,
                   fetched_at, description, content)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article["url"], article["title"], article.get("source"),
                    article.get("source_region"), article.get("published"),
                    now_iso(), article.get("description"), article.get("content"),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_unanalyzed(limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE analyzed = 0 ORDER BY RANDOM() LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def save_analysis(article_id: int, analysis: dict, mode: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE articles SET analyzed = 1, analysis_mode = ?, relevant = ?,
               overall_score = ?, confidence = ?, domain = ?, priority = ?,
               origin_state = ?, analysis_json = ? WHERE id = ?""",
            (
                mode,
                1 if analysis.get("relevant") else 0,
                int(analysis.get("overall_score", 0)),
                float(analysis.get("confidence", 0)),
                analysis.get("domain"),
                analysis.get("priority"),
                analysis.get("origin_state"),
                json.dumps(analysis, ensure_ascii=False),
                article_id,
            ),
        )


def query_articles(relevant_only: bool = False, min_score: int = 0,
                   domain: str | None = None, search: str | None = None,
                   limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM articles WHERE analyzed = 1"
    params: list = []
    if relevant_only:
        sql += " AND relevant = 1"
    if min_score > 0:
        sql += " AND overall_score >= ?"
        params.append(min_score)
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    if search:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    sql += " ORDER BY overall_score DESC, id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("analysis_json"):
            try:
                d["analysis"] = json.loads(d["analysis_json"])
            except json.JSONDecodeError:
                d["analysis"] = None
        d.pop("analysis_json", None)
        d.pop("content", None)
        out.append(d)
    return out


def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
        analyzed = conn.execute("SELECT COUNT(*) c FROM articles WHERE analyzed=1").fetchone()["c"]
        relevant = conn.execute("SELECT COUNT(*) c FROM articles WHERE relevant=1").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM articles WHERE analyzed=0").fetchone()["c"]
        domains = conn.execute(
            """SELECT domain, COUNT(*) c, ROUND(AVG(overall_score)) avg_score
               FROM articles WHERE relevant=1 AND domain IS NOT NULL
               GROUP BY domain ORDER BY c DESC"""
        ).fetchall()
        last_run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "total": total,
        "analyzed": analyzed,
        "relevant": relevant,
        "pending": pending,
        "domains": [dict(d) for d in domains],
        "last_run": dict(last_run) if last_run else None,
    }


def start_run() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')", (now_iso(),)
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, fetched: int = 0, new_articles: int = 0,
               analyzed: int = 0, relevant_found: int = 0, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE runs SET finished_at=?, status=?, fetched=?, new_articles=?,
               analyzed=?, relevant_found=?, error=? WHERE id=?""",
            (now_iso(), status, fetched, new_articles, analyzed, relevant_found, error, run_id),
        )
