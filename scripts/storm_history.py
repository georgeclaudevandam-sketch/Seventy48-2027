#!/usr/bin/env python3
"""Late May - June wind history, 1976-2025, along the Seventy48 course, for the storm Monte Carlo page.

Seventy48 is one night and a day, so what matters is not multi-day gales but any strong blow while you are on the water, and
which way it blows: a southerly pushes a northbound boat, a northerly stops it and stands the sea up against the ebb. The
50-year record is ERA5 reanalysis (ECMWF, via the Open-Meteo archive API, hourly 10 m wind speed and direction) at a point on
the course in each stretch. ERA5 is a ~30 km grid and smooths the wind in Puget Sound, so where an NDBC station sits on the
stretch (West Point, Port Townsend, Tacoma) its observed wind for the same hours is compared with ERA5 (ratio of their 95th
percentiles) to give a scale factor the planner can apply. The NWS small craft advisories and gale warnings issued since
2005 for the two marine zones on the course (Puget Sound and Hood Canal PZZ135, Admiralty Inlet PZZ134) are counted too.

Writes data/storm_history/wind.json (hourly ERA5 for the window each year, per stretch) and data/storm_history/summary.json.
Usage: storm_history.py [--cache DIR]   (the ERA5 and NDBC downloads are kept in DIR, default data/storm_history/cache, so a
re-run only fetches what is missing)
"""
from __future__ import annotations

import gzip
import io
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "storm_history"
CACHE = Path(sys.argv[sys.argv.index("--cache") + 1]) if "--cache" in sys.argv else OUT / "cache"
Y0, Y1 = 1976, 2025
UA = {"User-Agent": "seventy48-2027 planner (github.com/georgeclaudevandam-sketch/Seventy48-2027)"}
# window: 10 May 00:00 to 20 June 24:00 PDT, so a race on any date from mid May to mid June can be sampled
M0, D0, DAYS = 5, 10, 42
HOURS = DAYS * 24
# stretch, NWS zone, a point on the course in it, NDBC stations for the observed wind (first with data wins)
AREAS = [
    ("Tacoma to Colvos Passage", "PZZ135", (47.36, -122.50), ["tcmw1", "wpow1"]),
    ("Vashon to Kingston", "PZZ135", (47.70, -122.45), ["wpow1"]),
    ("Kingston to Foulweather Bluff (Point No Point)", "PZZ135", (47.91, -122.55), ["wpow1", "ptww1"]),
    ("Admiralty Inlet to Port Townsend", "PZZ134", (48.05, -122.70), ["ptww1"]),
]
SCA, GALE = 21, 34   # US inland waters: small craft advisory 21-33 kn sustained, gale 34-47


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, timeout=120, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            log(f"  HTTP {e.code} ({url[:100]})")
        except Exception as e:
            log(f"  {type(e).__name__} {e} ({url[:100]})")
        time.sleep(min(120, 10 * (i + 1) ** 2))
    return None


def era5(i, lat, lon):
    """{year: [[kn, from deg], ...HOURS]} for the window each year (None where missing)."""
    f = CACHE / f"era5_{i}.json"
    if f.exists():
        return {int(k): v for k, v in json.loads(f.read_text()).items()}
    out = {}
    for y in range(Y0, Y1 + 1, 10):
        ya, yb = y, min(Y1, y + 9)
        q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "start_date": f"{ya}-05-01", "end_date": f"{yb}-06-30",
                                    "hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "kn", "models": "era5",
                                    "timezone": "Etc/GMT+7"})
        b = get("https://archive-api.open-meteo.com/v1/archive?" + q, 300)
        if not b:
            log(f"  ERA5 {lat},{lon} {ya}-{yb}: no data"); continue
        h = json.loads(b)["hourly"]
        idx = {t: k for k, t in enumerate(h["time"])}
        for yr in range(ya, yb + 1):
            t0 = datetime(yr, M0, D0)
            row = []
            for k in range(HOURS):
                j = idx.get((t0 + timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M"))
                s = h["wind_speed_10m"][j] if j is not None else None
                d = h["wind_direction_10m"][j] if j is not None else None
                row.append(None if s is None or d is None else [round(s, 1), int(round(d / 5) * 5) % 360])
            out[yr] = row
        log(f"  ERA5 area {i} {ya}-{yb}")
        time.sleep(5)
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


def ndbc(st):
    """{year: [kn or None, ...HOURS]} observed wind at an NDBC station for the window (WSPD m/s, UTC)."""
    f = CACHE / f"ndbc_{st}.json"
    if f.exists():
        return {int(k): v for k, v in json.loads(f.read_text()).items()}
    out = {}
    for yr in range(Y0, Y1 + 1):
        b = get(f"https://www.ndbc.noaa.gov/view_text_file.php?filename={st}h{yr}.txt.gz&dir=data/historical/stdmet/", 120, 2)
        if not b:
            continue
        txt = (gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b).decode("latin-1")
        lines = txt.splitlines()
        if not lines:
            continue
        cols = lines[0].lstrip("#").split()   # YY/YYYY MM DD hh [mm] WD/WDIR WSPD ...
        if "WSPD" not in cols:
            continue
        iw, has_mm = cols.index("WSPD"), "mm" in cols
        row = [None] * HOURS
        t0 = datetime(yr, M0, D0)
        for l in lines[1:]:
            p = l.split()
            if not p or not p[0].isdigit():
                continue
            try:
                y = int(p[0]); y = y + 1900 if y < 100 else y
                dt = datetime(y, int(p[1]), int(p[2]), int(p[3]), int(p[4]) if has_mm else 0) - timedelta(hours=7)
                ws = float(p[iw])
            except (ValueError, IndexError):
                continue
            k = int((dt - t0).total_seconds() // 3600)
            if 0 <= k < HOURS and 0 <= ws < 60:
                row[k] = max(row[k] or 0, round(ws * 1.943844, 1))
        if sum(x is not None for x in row) > HOURS // 4:
            out[yr] = row
            log(f"  NDBC {st} {yr}: {sum(x is not None for x in row)} h")
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p / 100 * len(v)))] if v else None


def nws(zone):
    """Small craft advisories and gale warnings since 2005 whose time overlaps the window: [[year, start hour, hours, level]]."""
    b = get(f"https://mesonet.agron.iastate.edu/json/vtec_events_byugc.php?ugc={zone}&sdate=2005-01-01&edate={Y1}-12-31")
    if not b:
        return None
    out = []
    for e in json.loads(b).get("events", []):
        lv = {("SC", "Y"): 1, ("GL", "W"): 2, ("SR", "W"): 3}.get((e.get("phenomena"), e.get("significance")))
        if not lv:
            continue
        i = datetime.fromisoformat(e["issue"][:19]) - timedelta(hours=7)
        x = datetime.fromisoformat(e["expire"][:19]) - timedelta(hours=7)
        t0 = datetime(i.year, M0, D0)
        h0, h1 = int((i - t0).total_seconds() // 3600), int((x - t0).total_seconds() // 3600)
        if h1 < 0 or h0 >= HOURS:
            continue
        out.append([i.year, max(0, h0), min(HOURS, h1) - max(0, h0), lv])
    return out


def main():
    route = json.loads((ROOT / "data" / "route.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    areas, wind = [], {}
    for i, (name, zone, (lat, lon), obs) in enumerate(AREAS):
        log(f"{name}")
        e = era5(i, lat, lon)
        wind[i] = e
        a = {"name": name, "zone": zone, "lat": lat, "lon": lon, "scale": 1.0, "obs": None}
        # along each course line, for blending between stretches
        a["legs"] = {}
        for leg in route["legs"]:
            pts, cum, best = leg["points"], 0.0, (1e9, 0)
            for p, q in zip(pts, pts[1:]):
                d = math.hypot((p[0] - lat) * 60, (p[1] - lon) * 60 * math.cos(math.radians(lat)))
                if d < best[0]: best = (d, cum)
                cum += math.hypot((q[0] - p[0]) * 60, (q[1] - p[1]) * 60 * math.cos(math.radians(p[0])))
            a["legs"][leg["key"]] = {"along": round(best[1], 1)}
        for st in obs:
            o = ndbc(st)
            pairs = [(o[y][k], e[y][k][0]) for y in o if y in e for k in range(HOURS) if o[y][k] is not None and e[y][k]]
            if len(pairs) < 2000:
                log(f"  {st}: only {len(pairs)} matched hours"); continue
            ro, re_ = pct([p[0] for p in pairs], 95), pct([p[1] for p in pairs], 95)
            a["scale"] = round(ro / re_, 2) if re_ else 1.0
            a["obs"] = {"station": st.upper(), "years": sorted(o), "hours": len(pairs), "p95_obs": ro, "p95_era5": re_}
            log(f"  {st}: {len(o)} years, {len(pairs)} h, p95 obs {ro} vs ERA5 {re_}: scale {a['scale']}")
            break
        areas.append(a)
    zones = {}
    for z in sorted({a[1] for a in AREAS}):
        zones[z] = nws(z)
        log(f"NWS {z}: {len(zones[z] or [])} events in the window since 2005")
    years = list(range(Y0, Y1 + 1))
    (OUT / "wind.json").write_text(json.dumps({
        "source": "ERA5 (ECMWF) via Open-Meteo archive API; NDBC; NWS via Iowa Environmental Mesonet",
        "window": {"month": M0, "day": D0, "hours": HOURS, "tz": "PDT (UTC-7)"}, "years": years, "areas": areas,
        "era5": [[wind[i].get(y) for y in years] for i in range(len(AREAS))], "nws": zones}, separators=(",", ":")))
    # summary: per stretch, share of window hours and days at each strength, split by direction
    summ = []
    for i, a in enumerate(areas):
        hrs = [x for y in years for x in (wind[i].get(y) or []) if x]
        sc = a["scale"]
        def share(f): return round(sum(1 for x in hrs if f(x)) / max(1, len(hrs)), 4)
        days = {lvl: 0 for lvl in (15, SCA, GALE)}
        for y in years:
            row = wind[i].get(y) or []
            for d in range(DAYS):
                m = max((x[0] * sc for x in row[d * 24:(d + 1) * 24] if x), default=0)
                for lvl in days:
                    if m >= lvl: days[lvl] += 1
        summ.append({"name": a["name"], "scale": sc,
                     "hours_15": share(lambda x: x[0] * sc >= 15), "hours_sca": share(lambda x: x[0] * sc >= SCA),
                     "hours_15_south": share(lambda x: x[0] * sc >= 15 and 90 < x[1] < 270),
                     "hours_15_north": share(lambda x: x[0] * sc >= 15 and not 90 < x[1] < 270),
                     "days_15": round(days[15] / len(years), 1), "days_sca": round(days[SCA] / len(years), 1), "days_gale": round(days[GALE] / len(years), 2)})
    (OUT / "summary.json").write_text(json.dumps({"window_days": DAYS, "years": [Y0, Y1], "areas": summ}, indent=1))
    log("done")


if __name__ == "__main__":
    main()
