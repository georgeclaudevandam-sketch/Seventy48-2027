#!/usr/bin/env python3
"""Official Seventy48 results for every year, from the race recap pages on seventy48.com.

Each recap page embeds the year's results as a published Google Sheet. This reads the page, finds the sheet, downloads it as
CSV (data/results/<year>.csv, as published) and pulls out team, class and elapsed time where the columns can be recognised
(data/results/index.json). Years before 2024 have no YB tracks (their trackers were on MAProgress), so these results are the
only record of how fast boats went in 2018 to 2023. The script also logs what the MAProgress replay pages load, to see if
their tracks can be fetched.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "results"
UA = {"User-Agent": "Mozilla/5.0 (seventy48-2027 planner; github.com/georgeclaudevandam-sketch/Seventy48-2027)"}
RECAPS = {2018: "2018-recap", 2019: "2019-recap", 2021: "2021-recap", 2022: "2022-recap", 2023: "seventy48-2023-recap",
          2024: "seventy48-2024-recap", 2025: "2025-race-recap", 2026: "2026-race-recap"}
MAPROGRESS = [2021, 2022, 2023]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            log(f"  {type(e).__name__} {e} ({url})")
            time.sleep(3 * (i + 1))
    return None


def hours(s):
    """'17:42:10', '1:05:42:10' (d:h:m:s), '17h 42m' -> hours, else None."""
    s = (s or "").strip()
    m = re.fullmatch(r"(?:(\d+)[:d]\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        d, h, mi, se = (int(x) if x else 0 for x in m.groups())
        return round(d * 24 + h + mi / 60 + se / 3600, 3)
    m = re.fullmatch(r"(\d+)\s*h(?:ours?)?\s*(\d+)?\s*m?", s, re.I)
    if m:
        return round(int(m.group(1)) + int(m.group(2) or 0) / 60, 3)
    return None


def parse(rows):
    """Find the header row and the team, class and elapsed-time columns."""
    for hi, row in enumerate(rows[:10]):
        low = [c.strip().lower() for c in row]
        team = next((i for i, c in enumerate(low) if "team" in c and "#" not in c), None)
        el = next((i for i, c in enumerate(low) if "elapsed" in c or c in ("time", "total time", "finish time", "race time")), None)
        if team is not None and el is not None:
            cls = next((i for i, c in enumerate(low) if "class" in c or "category" in c or "division" in c), None)
            boat = next((i for i, c in enumerate(low) if "boat" in c or "craft" in c or "vessel" in c), None)
            out = []
            for r in rows[hi + 1:]:
                if len(r) <= max(team, el) or not r[team].strip():
                    continue
                out.append({"team": r[team].strip(), "class": r[cls].strip() if cls is not None and cls < len(r) else "",
                            "boat": r[boat].strip() if boat is not None and boat < len(r) else "",
                            "elapsed_h": hours(r[el]), "raw": r[el].strip()})
            return row, out
    return rows[0] if rows else [], None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = {}
    for year, slug in RECAPS.items():
        html = get(f"https://seventy48.com/{slug}/")
        if not html:
            continue
        links = sorted(set(re.findall(r"https://docs\.google\.com/spreadsheets/d/e/[\w-]+/pubhtml[^\"'\s<>]*", html)))
        log(f"{year}: {len(links)} sheet(s)")
        for k, link in enumerate(links):
            base = link.split("/pubhtml")[0]
            text = get(f"{base}/pub?output=csv")
            if not text or text.lstrip().startswith("<"):
                log("  not CSV"); continue
            name = f"{year}.csv" if k == 0 else f"{year}-{k + 1}.csv"
            (OUT / name).write_text(text)
            rows = list(csv.reader(io.StringIO(text)))
            head, teams = parse(rows)
            log(f"  {name}: {len(rows)} rows; header {head[:12]}")
            if teams and year not in index:
                fin = [t for t in teams if t["elapsed_h"]]
                index[year] = {"file": name, "sheet": base + "/pubhtml", "teams": teams}
                log(f"  parsed {len(teams)} teams, {len(fin)} with a time")
    (OUT / "index.json").write_text(json.dumps({"source": "seventy48.com race recaps (published Google Sheets)", "years": index}, indent=0))
    for y in MAPROGRESS:
        html = get(f"https://seventy48-{y}.maprogress.com/")
        if html:
            scripts = re.findall(r"src=[\"'](.*?)[\"']", html)[:10]
            urls = sorted(set(re.findall(r"https?://[\w./-]+", html)))[:25]
            log(f"MAProgress {y}: {len(html)} bytes; scripts {scripts}; urls {urls}")


if __name__ == "__main__":
    main()
