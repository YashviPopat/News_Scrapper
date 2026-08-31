"""Fetches articles from all configured RSS sources."""
import logging
import re

import feedparser
import requests
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger("scraper")

TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return TAG_RE.sub(" ", text).replace("&nbsp;", " ").strip()


def fetch_feed(source: dict) -> list[dict]:
    """Fetch one RSS feed with a hard timeout, return normalized entries."""
    try:
        resp = requests.get(
            source["url"],
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Feed failed: %s (%s)", source["name"], e)
        return []

    parsed = feedparser.parse(resp.content)
    articles = []
    for entry in parsed.entries[:40]:
        url = entry.get("link", "").strip()
        title = strip_html(entry.get("title", "")).strip()
        if not url or not title:
            continue
        articles.append({
            "url": url,
            "title": title,
            "source": source["name"],
            "source_region": source.get("region", ""),
            "published": entry.get("published", entry.get("updated", "")),
            "description": strip_html(entry.get("summary", ""))[:1500],
        })
    log.info("Fetched %d entries from %s", len(articles), source["name"])
    return articles


def fetch_full_text(url: str) -> str:
    """Best-effort extraction of the article body from the page."""
    try:
        resp = requests.get(
            url, timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        # Prefer <article>, fall back to the densest run of paragraphs.
        container = soup.find("article") or soup.body or soup
        paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
        text = " ".join(p for p in paragraphs if len(p) > 60)
        return text[:config.FULL_TEXT_MAX_CHARS]
    except Exception:
        return ""


def scrape_all_sources() -> list[dict]:
    sources = config.load_json(config.SOURCES_PATH)["sources"]
    all_articles: list[dict] = []
    for source in sources:
        if not source.get("enabled", True):
            continue
        all_articles.extend(fetch_feed(source))
    return all_articles
