"""Relevance engine.

Primary path: Claude (Anthropic API) with structured JSON output — judges
whether a news item is useful/implementable for Gujarat, not merely "about"
Gujarat. Fallback path: a keyword heuristic used when no API key is set or
the API call fails, so the app always produces something.
"""
import json
import logging

from . import config

log = logging.getLogger("analyzer")

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {
            "type": "boolean",
            "description": "True if this news is useful for Gujarat — either directly about Gujarat, or a policy/innovation from elsewhere that could realistically be adapted to Gujarat's conditions.",
        },
        "relevance_type": {
            "type": "string",
            "enum": ["directly_about_gujarat", "transferable_policy", "national_impact", "not_relevant"],
        },
        "confidence": {"type": "number", "description": "0.0 to 1.0"},
        "origin_state": {
            "type": "string",
            "description": "State/country the news originates from or concerns, e.g. 'Maharashtra', 'Kerala', 'National', 'Gujarat'.",
        },
        "domain": {
            "type": "string",
            "enum": [
                "Transportation", "Agriculture", "Water Resources", "Technology",
                "Education", "Healthcare", "Industry & Economy", "Energy",
                "Urban Development", "Environment & Climate", "Governance & Policy",
                "Other",
            ],
        },
        "summary": {"type": "string", "description": "2-3 sentence neutral summary of the news item."},
        "reason": {
            "type": "string",
            "description": "Why this is or isn't relevant to Gujarat. Compare origin conditions with Gujarat's (climate, crops, economy, infrastructure) when judging transferability.",
        },
        "implementation_notes": {
            "type": "string",
            "description": "If relevant: how Gujarat could adopt this — which cities/districts, what already exists to build on, main obstacles. Empty string if not relevant.",
        },
        "departments": {
            "type": "array", "items": {"type": "string"},
            "description": "Gujarat government departments that would own this.",
        },
        "regions": {
            "type": "array", "items": {"type": "string"},
            "description": "Gujarat cities/districts/regions where this applies most.",
        },
        "scores": {
            "type": "object",
            "properties": {
                "implementation_feasibility": {"type": "integer", "description": "0-100"},
                "expected_benefit": {"type": "integer", "description": "0-100"},
                "urgency": {"type": "integer", "description": "0-100"},
                "cost_burden": {"type": "integer", "description": "0-100, higher = more expensive to implement"},
            },
            "required": ["implementation_feasibility", "expected_benefit", "urgency", "cost_burden"],
            "additionalProperties": False,
        },
        "overall_score": {
            "type": "integer",
            "description": "0-100 overall usefulness for Gujarat. Below 40 means ignore.",
        },
        "priority": {"type": "string", "enum": ["High", "Medium", "Low", "None"]},
    },
    "required": [
        "relevant", "relevance_type", "confidence", "origin_state", "domain",
        "summary", "reason", "implementation_notes", "departments", "regions",
        "scores", "overall_score", "priority",
    ],
    "additionalProperties": False,
}

_anthropic_client = None
_groq_client = None
_system_prompt = None


def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None and config.ANTHROPIC_API_KEY:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def get_groq_client():
    global _groq_client
    if _groq_client is None and config.GROQ_API_KEY:
        from groq import Groq
        _groq_client = Groq(api_key=config.GROQ_API_KEY)
    return _groq_client


def build_system_text() -> str:
    """Stable analyst instructions + Gujarat profile + user preferences.
    Shared by both providers."""
    gujarat = config.load_json(config.GUJARAT_PROFILE_PATH)
    prefs = config.load_user_profile()
    return (
        "You are a public-policy analyst for the state of Gujarat, India. "
        "You evaluate news items and decide whether they are USEFUL for Gujarat — "
        "not merely whether they mention Gujarat.\n\n"
        "Decision rules:\n"
        "1. News directly about Gujarat in the user's areas of interest is relevant.\n"
        "2. A policy, scheme, or innovation from ANOTHER state or country is relevant "
        "only if it could realistically be adapted to Gujarat. Compare the origin's "
        "conditions (climate, crops, economy, urban profile, infrastructure) with "
        "Gujarat's profile below. Example: an AI traffic system from Pune transfers "
        "well to Ahmedabad (similar congestion, existing smart-city infrastructure); "
        "a rubber-plantation subsidy from Kerala does not (Gujarat is semi-arid and "
        "grows cotton/groundnut, not rubber).\n"
        "3. Topics in the ignore list are not relevant regardless of location.\n"
        "4. Pure political commentary, opinion, and speculation are not relevant.\n"
        "5. Score honestly — most general news should score below 40.\n\n"
        f"GUJARAT PROFILE:\n{json.dumps(gujarat, indent=1, ensure_ascii=False)}\n\n"
        f"USER PREFERENCES:\n{json.dumps(prefs, indent=1, ensure_ascii=False)}"
    )


def refresh_system_prompt() -> None:
    """Call after preferences change."""
    global _system_prompt
    _system_prompt = None


def build_user_text(article: dict) -> str:
    body = article.get("content") or ""
    return (
        f"Analyze this news item for Gujarat:\n\n"
        f"TITLE: {article.get('title', '')}\n"
        f"SOURCE: {article.get('source', '')} ({article.get('source_region', '')})\n"
        f"PUBLISHED: {article.get('published', '')}\n"
        f"DESCRIPTION: {article.get('description', '')}\n"
        + (f"ARTICLE TEXT: {body}\n" if body else "")
    )


def llm_analyze(article: dict) -> dict | None:
    """Route to the configured provider. Returns None on any failure so the
    caller can fall back to the heuristic."""
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = build_system_text()
    if config.LLM_PROVIDER == "anthropic":
        return anthropic_analyze(article, _system_prompt)
    if config.LLM_PROVIDER == "groq":
        return groq_analyze(article, _system_prompt)
    return None


def anthropic_analyze(article: dict, system_text: str) -> dict | None:
    client = get_anthropic_client()
    if client is None:
        return None
    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=16000,
            # Cache breakpoint: the stable profile prompt is reused across
            # every per-article call in a run.
            system=[{"type": "text", "text": system_text,
                     "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
            messages=[{"role": "user", "content": build_user_text(article)}],
        )
        if response.stop_reason == "refusal":
            log.warning("Model refused analysis for: %s", article.get("title"))
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        return json.loads(text) if text else None
    except Exception as e:
        log.error("Anthropic analysis failed (%s): %s", article.get("title", "")[:60], e)
        return None


def groq_analyze(article: dict, system_text: str) -> dict | None:
    """Groq (OpenAI-compatible) path. JSON mode guarantees a JSON object but
    not our exact schema, so the schema goes in the prompt and the result is
    validated before use."""
    client = get_groq_client()
    if client is None:
        return None
    system_with_schema = (
        system_text
        + "\n\nRespond ONLY with a single JSON object matching this JSON Schema "
          "exactly (all required fields, correct types, enum values only):\n"
        + json.dumps(ANALYSIS_SCHEMA)
    )
    try:
        completion = client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_with_schema},
                {"role": "user", "content": build_user_text(article)},
            ],
            temperature=0.2,
            max_completion_tokens=4096,
            reasoning_effort="medium",
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content or ""
        result = parse_json_lenient(raw)
        if result is None or not validate_analysis(result):
            log.warning("Groq returned unusable JSON for: %s", article.get("title", "")[:60])
            return None
        return result
    except Exception as e:
        log.error("Groq analysis failed (%s): %s", article.get("title", "")[:60], e)
        return None


def parse_json_lenient(raw: str) -> dict | None:
    """Parse model output that may carry code fences or surrounding prose."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def validate_analysis(result: dict) -> bool:
    """Minimal shape check + coercion so a slightly-off response still lands."""
    required = ["relevant", "overall_score", "domain", "reason"]
    if not all(k in result for k in required):
        return False
    try:
        result["overall_score"] = max(0, min(100, int(result["overall_score"])))
        result["relevant"] = bool(result["relevant"])
        result["confidence"] = float(result.get("confidence", 0.7))
    except (TypeError, ValueError):
        return False
    result.setdefault("relevance_type", "transferable_policy" if result["relevant"] else "not_relevant")
    result.setdefault("origin_state", "Unknown")
    result.setdefault("summary", "")
    result.setdefault("implementation_notes", "")
    result.setdefault("departments", [])
    result.setdefault("regions", [])
    result.setdefault("scores", {})
    result.setdefault("priority", "Medium" if result["relevant"] else "None")
    return True


# ---------------------------------------------------------------------------
# Heuristic fallback (no API key needed)
# ---------------------------------------------------------------------------

GUJARAT_TERMS = [
    "gujarat", "ahmedabad", "surat", "vadodara", "rajkot", "gandhinagar",
    "bhavnagar", "jamnagar", "kutch", "kachchh", "saurashtra", "gift city",
    "dholera", "narmada", "amul", "morbi", "sanand", "mundra", "kandla",
]

DOMAIN_KEYWORDS = {
    "Transportation": ["traffic", "metro", "highway", "transport", "railway", "bus", "ev charging", "mobility", "parking"],
    "Agriculture": ["farmer", "crop", "agriculture", "irrigation", "msp", "horticulture", "dairy", "fertilizer", "drip"],
    "Water Resources": ["water", "groundwater", "canal", "dam", "rainwater", "desalination", "drought"],
    "Technology": ["artificial intelligence", " ai ", "semiconductor", "startup", "digital", "drone", "5g", "data centre", "fintech"],
    "Education": ["school", "education", "university", "student", "skill", "scholarship", "literacy"],
    "Healthcare": ["hospital", "health", "vaccine", "medical", "telemedicine", "ayushman", "doctor"],
    "Industry & Economy": ["industry", "manufacturing", "msme", "export", "investment", "textile", "pharma", "gdp", "factory"],
    "Energy": ["solar", "wind", "renewable", "power", "electricity", "hydrogen", "energy", "grid"],
    "Urban Development": ["smart city", "urban", "housing", "municipal", "waste management", "sewage", "town planning"],
    "Environment & Climate": ["pollution", "climate", "emission", "heat wave", "cyclone", "flood", "mangrove", "afforestation"],
    "Governance & Policy": ["policy", "scheme", "yojana", "governance", "e-governance", "subsidy", "cabinet", "bill", "act"],
}

NON_TRANSFERABLE = ["rubber", "tea plantation", "coffee", "coconut", "paddy", "areca", "spices board", "backwater", "snowfall", "apple orchard"]
IGNORE_KEYWORDS = ["cricket", "bollywood", "actor", "actress", "film", "movie", "celebrity", "ipl", "match", "horoscope", "murder", "rape", "arrested", "accident kills"]


def heuristic_analyze(article: dict) -> dict:
    text = f" {article.get('title', '')} {article.get('description', '')} ".lower()

    if any(k in text for k in IGNORE_KEYWORDS):
        return _heuristic_result(False, "not_relevant", "Other", 5,
                                 "Matches an ignored topic (sports/entertainment/crime).", text)

    domain, domain_hits = "Other", 0
    for d, kws in DOMAIN_KEYWORDS.items():
        hits = sum(1 for k in kws if k in text)
        if hits > domain_hits:
            domain, domain_hits = d, hits

    gujarat_direct = any(t in text for t in GUJARAT_TERMS)
    policy_signal = any(k in text for k in ["policy", "scheme", "launch", "yojana", "pilot", "initiative", "project", "introduc"])
    non_transferable = any(k in text for k in NON_TRANSFERABLE)

    score = 0
    if gujarat_direct:
        score += 45
    if domain_hits:
        score += min(30, 12 * domain_hits)
    if policy_signal:
        score += 15
    if non_transferable and not gujarat_direct:
        score = min(score, 20)

    relevant = score >= 40
    rtype = ("directly_about_gujarat" if gujarat_direct else
             "transferable_policy" if relevant else "not_relevant")
    reason = ("Heuristic match: " +
              ("mentions Gujarat; " if gujarat_direct else "") +
              (f"domain '{domain}' keywords; " if domain_hits else "") +
              ("policy/scheme signal; " if policy_signal else "") +
              ("but concerns conditions Gujarat lacks (e.g. high-rainfall crops); " if non_transferable else "") +
              "set ANTHROPIC_API_KEY for real reasoning.")
    return _heuristic_result(relevant, rtype, domain, min(score, 95), reason, text)


def _heuristic_result(relevant: bool, rtype: str, domain: str, score: int,
                      reason: str, text: str) -> dict:
    return {
        "relevant": relevant,
        "relevance_type": rtype,
        "confidence": 0.35,
        "origin_state": "Gujarat" if any(t in text for t in GUJARAT_TERMS) else "Unknown",
        "domain": domain,
        "summary": "",
        "reason": reason,
        "implementation_notes": "",
        "departments": [],
        "regions": [],
        "scores": {
            "implementation_feasibility": score,
            "expected_benefit": score,
            "urgency": score // 2,
            "cost_burden": 50,
        },
        "overall_score": score,
        "priority": "High" if score >= 75 else "Medium" if score >= 55 else "Low" if relevant else "None",
    }


def analyze(article: dict) -> tuple[dict, str]:
    """Returns (analysis, mode) where mode is 'llm' or 'heuristic'."""
    result = llm_analyze(article)
    if result is not None:
        return result, "llm"
    return heuristic_analyze(article), "heuristic"
