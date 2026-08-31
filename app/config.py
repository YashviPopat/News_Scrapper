"""Central configuration. Reads .env from the project root."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(PROJECT_DIR / ".env")

DB_PATH = DATA_DIR / "news.db"
SOURCES_PATH = BASE_DIR / "sources.json"
GUJARAT_PROFILE_PATH = BASE_DIR / "gujarat_profile.json"
USER_PROFILE_PATH = DATA_DIR / "user_profile.json"
DEFAULT_USER_PROFILE_PATH = BASE_DIR / "user_profile.default.json"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

# Which LLM analyzes articles: "anthropic", "groq", or "" for auto-detect
# (anthropic if its key is set, else groq if its key is set, else heuristic).
_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
if not _provider:
    _provider = "anthropic" if ANTHROPIC_API_KEY else "groq" if GROQ_API_KEY else "none"
LLM_PROVIDER = _provider
LLM_MODEL = ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else GROQ_MODEL if LLM_PROVIDER == "groq" else None
LLM_ENABLED = LLM_PROVIDER in ("anthropic", "groq") and bool(
    ANTHROPIC_API_KEY if LLM_PROVIDER == "anthropic" else GROQ_API_KEY
)
MAX_ANALYZE_PER_RUN = int(os.getenv("MAX_ANALYZE_PER_RUN", "15"))
FETCH_FULL_TEXT = os.getenv("FETCH_FULL_TEXT", "true").lower() in ("1", "true", "yes")
AUTO_SCRAPE_MINUTES = int(os.getenv("AUTO_SCRAPE_MINUTES", "0"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

REQUEST_TIMEOUT = 15  # seconds, per HTTP request while scraping
FULL_TEXT_MAX_CHARS = 4000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 GujaratNewsIntel/1.0"
)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_user_profile() -> dict:
    """User preferences live in data/ so edits survive code updates."""
    if USER_PROFILE_PATH.exists():
        return load_json(USER_PROFILE_PATH)
    profile = load_json(DEFAULT_USER_PROFILE_PATH)
    save_user_profile(profile)
    return profile


def save_user_profile(profile: dict) -> None:
    with open(USER_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
