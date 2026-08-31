"""Fetch the official list of Gujarat government departments from iGOD
(Integrated Government Online Directory) and merge it into the Gujarat
knowledge base (app/gujarat_profile.json) used by the relevance engine.

Usage:  python scripts/fetch_departments.py
"""
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

IGOD_URL = "https://igod.gov.in/sg/GJ/E003/organizations"


def fetch_departments() -> list[dict]:
    resp = requests.get(
        IGOD_URL, timeout=25,
        headers={"User-Agent": config.USER_AGENT},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    departments = []
    seen = set()
    for link in soup.select("a.search-title"):
        name = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
        url = (link.get("href") or "").strip()
        if not name or name.lower() in seen:
            continue
        # The page appends "related sites" (central schemes) with the same CSS
        # class — keep only entries actually scoped to Gujarat.
        if "gujarat" not in name.lower():
            continue
        seen.add(name.lower())
        departments.append({"name": name, "website": url})
    return departments


def merge_into_profile(departments: list[dict]) -> None:
    profile = config.load_json(config.GUJARAT_PROFILE_PATH)
    profile.setdefault("governance", {})["departments"] = departments
    profile["governance"]["departments_source"] = IGOD_URL
    with open(config.GUJARAT_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    deps = fetch_departments()
    if not deps:
        print("No departments found — the iGOD page structure may have changed.")
        sys.exit(1)
    merge_into_profile(deps)
    print(f"Merged {len(deps)} departments into {config.GUJARAT_PROFILE_PATH}:")
    for d in deps:
        print(f"  - {d['name']}  ({d['website']})")
