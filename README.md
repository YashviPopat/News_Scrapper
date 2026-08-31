# Gujarat News Intelligence

A personalized news scraper that doesn't just ask *"Is this news about Gujarat?"* —
it asks *"Could this be useful for Gujarat?"*

It scrapes national and regional news sources, then runs each article through a
relevance engine that compares it against a **Gujarat knowledge profile**
(climate, crops, economy, cities, departments, ongoing programs). A traffic-AI
policy from Maharashtra scores high (Ahmedabad has the same problem and the
smart-city infrastructure to adopt it); a Kerala rubber-plantation subsidy
scores near zero (semi-arid Gujarat grows cotton and groundnut, not rubber).

## Architecture

```
RSS sources ──▶ Scraper ──▶ SQLite ──▶ Relevance Engine ──▶ Dashboard
 (sources.json)  (feedparser        (Claude structured      (FastAPI +
                  + full-text        output, with keyword    vanilla JS)
                  extraction)        heuristic fallback)
```

- **Scraper** (`app/scraper.py`) — pulls all enabled feeds in `app/sources.json`,
  optionally fetches full article text.
- **Relevance engine** (`app/analyzer.py`) — sends each article to Claude with the
  Gujarat profile (`app/gujarat_profile.json`) and your preferences as a cached
  system prompt, and gets back a strict JSON verdict: relevance type, domain,
  transferability reasoning, implementation notes, responsible departments,
  target regions, and 0–100 scores (feasibility, benefit, urgency, cost).
  If no API key is configured it falls back to a keyword heuristic so the app
  still works end to end.
- **Storage** (`app/database.py`) — SQLite at `data/news.db`, deduplicated by URL.
- **Dashboard** (`app/static/`) — filterable card view with score rings,
  per-article reasoning, department/region chips, live pipeline progress, and a
  preferences editor.

## Setup

```powershell
cd d:\news_scrapper
pip install -r requirements.txt
copy .env.example .env      # then edit .env and set ANTHROPIC_API_KEY
python run.py
```

Open http://127.0.0.1:8000 and click **Run Pipeline**.

Without an `ANTHROPIC_API_KEY` the app runs in heuristic mode (keyword
matching). With a key, every article is judged by Claude with full
policy-transfer reasoning.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(empty)* | Enables LLM analysis |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Model for relevance analysis |
| `MAX_ANALYZE_PER_RUN` | `15` | LLM cost control — articles analyzed per run |
| `FETCH_FULL_TEXT` | `true` | Fetch article pages for better analysis |
| `AUTO_SCRAPE_MINUTES` | `0` | Auto-run interval (0 = manual only) |

## Customizing

- **Sources** — edit `app/sources.json` (any RSS feed works; set `enabled: false` to disable one).
- **Gujarat knowledge base** — edit `app/gujarat_profile.json`. The richer this
  is, the smarter the transferability judgments.
- **Your preferences** — use the ⚙ Preferences button in the dashboard, or edit
  `data/user_profile.json` (interests, ignore topics, minimum score).

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/scrape` | Trigger a pipeline run |
| `GET /api/scrape/status` | Live run progress |
| `GET /api/articles?relevant_only=&min_score=&domain=&search=` | Query analyzed articles |
| `GET /api/stats` | Counts + per-domain breakdown |
| `GET/PUT /api/preferences` | Read/update your profile |
| `GET /api/sources` | List configured sources |

## Note on sentinel.gujarat.gov.in

That site is the **Gujarat Police Innovation Challenge 2026** hackathon portal
(registration platform), not a news source, so it isn't scraped here. The
sources list instead uses Gujarat and national outlets with working RSS feeds.
