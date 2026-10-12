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
from datetime import datetime, timedelta
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


# race starts (PDT): 2018 went off at 17:30 on Monday 11 June (Team Epic, first in at 03:09, took 9 h 39 min); other years at
# 19:00 on the Friday, the evening before the first finishers came in
STARTS = {2018: datetime(2018, 6, 11, 17, 30)}


def finish_dt(year, row, cols):
    """Finish as a datetime from 'Finish Time (PDT)' ('6/1/2019 5:49 AM', or a bare time with a separate 'Finish Date')."""
    t = row[cols["time"]].strip() if cols["time"] is not None and cols["time"] < len(row) else ""
    d = row[cols["date"]].strip() if cols["date"] is not None and cols["date"] < len(row) else ""
    if not t:
        return None
    for f in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(t, f)
        except ValueError:
            pass
    if d:
        for f in ("%m/%d/%Y", "%B %d %Y", "%b %d %Y"):
            try:
                day = datetime.strptime(d if f == "%m/%d/%Y" else f"{d} {year}", f)
                break
            except ValueError:
                day = None
        if day:
            for f in ("%I:%M %p", "%I:%M:%S %p", "%H:%M:%S", "%H:%M"):
                try:
                    tt = datetime.strptime(t, f)
                    return day.replace(hour=tt.hour, minute=tt.minute, second=tt.second)
                except ValueError:
                    pass
    return None


def parse(year, text):
    rows = list(csv.reader(io.StringIO(text)))
    for hi, row in enumerate(rows[:10]):
        low = [c.strip().lower() for c in row]
        team = next((i for i, c in enumerate(low) if "team" in c), None)
        tcol = next((i for i, c in enumerate(low) if c.startswith("finish time") or c == "time"), None)
        if team is None or tcol is None:
            continue
        cols = {"time": tcol, "date": next((i for i, c in enumerate(low) if c.startswith("finish date")), None)}
        vt = next((i for i, c in enumerate(low) if "vessel" in c or "boat" in c or "class" in c), None)
        pl = next((i for i, c in enumerate(low) if c == "place"), None)
        teams = []
        for r in rows[hi + 1:]:
            if len(r) <= team or not r[team].strip():
                continue
            f = finish_dt(year, r, cols)
            if f and f.year != year:   # typos in the sheet (2002, 0201 for 2019)
                f = f.replace(year=year)
            place = r[pl].strip() if pl is not None and pl < len(r) else ""
            if place and not place.isdigit():   # DSQ, DNF
                f = None
            teams.append({"team": r[team].strip(), "class": r[vt].strip().lower() if vt is not None and vt < len(r) else "",
                          "place": place, "finish": f})
        fins = [t["finish"] for t in teams if t["finish"]]
        if not fins or min(fins).year != year:
            return None
        start = STARTS.get(year) or (min(fins) - timedelta(days=1)).replace(hour=19, minute=0, second=0)
        for t in teams:
            f = t.pop("finish")
            t["finish"] = f.strftime("%Y-%m-%dT%H:%M") if f else None
            t["elapsed_h"] = round((f - start).total_seconds() / 3600, 2) if f and f > start else None
        return {"start": start.strftime("%Y-%m-%dT%H:%M"), "teams": teams}
    return None


def reparse():
    """Rebuild index.json from the CSVs already in data/results (no network)."""
    index = {}
    for f in sorted(OUT.glob("*.csv")):
        year = int(f.stem.split("-")[0])
        r = parse(year, f.read_text())
        if r and year not in index:
            index[year] = {"file": f.name, **r}
            log(f"{f.name}: {len(r['teams'])} teams, {sum(1 for t in r['teams'] if t['elapsed_h'])} timed, start {r['start']}")
    (OUT / "index.json").write_text(json.dumps({"source": "seventy48.com race recaps (published Google Sheets)", "years": index}, indent=0))


def main():
    if "--parse" in sys.argv:
        return reparse()
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
            r = parse(year, text)
            log(f"  {name}: {'%d teams, %d with a time, start %s' % (len(r['teams']), sum(1 for t in r['teams'] if t['elapsed_h']), r['start']) if r else 'not this year or unreadable'}")
            if r and year not in index:
                index[year] = {"file": name, "sheet": base + "/pubhtml", **r}
    (OUT / "index.json").write_text(json.dumps({"source": "seventy48.com race recaps (published Google Sheets)", "years": index}, indent=0))
    for y in MAPROGRESS:
        html = get(f"https://seventy48-{y}.maprogress.com/")
        if html:
            scripts = re.findall(r"src=[\"'](.*?)[\"']", html)[:10]
            urls = sorted(set(re.findall(r"https?://[\w./-]+", html)))[:25]
            log(f"MAProgress {y}: {len(html)} bytes; scripts {scripts}; urls {urls}")


if __name__ == "__main__":
    main()
