#!/usr/bin/env python3
"""Where past Seventy48 teams stopped: data/stops.json, from the YB tracks in data/tracks.

A stop is a run of fixes that stays within STAY_NM of where it began for MIN_MIN minutes or more (ashore, tied up or
anchored; a boat resting on the water drifts out of that circle). Stops at the start and finish are left out. Stops within
GROUP_NM of each other are one site, listed with how many teams used it, in which years, and how long they stayed.
"""
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
STAY_NM, MIN_MIN, GROUP_NM, NEAR_NM = 0.08, 15, 0.25, 1.5


def nm(a, b):
    return math.hypot((b[0] - a[0]) * 60, (b[1] - a[1]) * 60 * math.cos(math.radians(a[0])))


def project(pts, p):
    best, cum = (1e9, 0.0), 0.0
    for a, b in zip(pts, pts[1:]):
        L = nm(a, b)
        for k in range(max(1, int(L / 0.05)) + 1):
            f = k / max(1, int(L / 0.05)); q = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f); d = nm(q, p)
            if d < best[0]: best = (d, cum + L * f)
        cum += L
    return best


def main():
    route = json.loads((ROOT / "data" / "route.json").read_text())
    legs = {l["key"]: l["points"] for l in route["legs"]}
    marks = {m["key"]: (m["lat"], m["lon"]) for m in route["marks"]}
    idx = json.loads((ROOT / "data" / "tracks" / "index.json").read_text())
    stops = []
    for r in idx["races"]:
        race = json.loads((ROOT / "data" / "tracks" / f"{r['key']}.json").read_text())
        year = r["title"].split()[-1]
        for t in race["teams"]:
            tr = [(p[0], p[1], p[2]) for p in t["track"] if p[0] >= (t["start"] or 0) - 600]
            if t.get("finished"):
                tr = [p for p in tr if p[0] <= t["finished"]]
            i = 0
            while i < len(tr):
                j = i
                while j + 1 < len(tr) and nm(tr[i][1:], tr[j + 1][1:]) <= STAY_NM:
                    j += 1
                mins = (tr[j][0] - tr[i][0]) / 60
                if mins >= MIN_MIN:
                    ll = (median(p[1] for p in tr[i:j + 1]), median(p[2] for p in tr[i:j + 1]))
                    if nm(ll, marks["start"]) > 0.6 and nm(ll, marks["finish"]) > 0.6:
                        stops.append({"ll": ll, "min": mins, "team": t["name"], "year": year, "t": tr[i][0]})
                    i = j + 1
                else:
                    i += 1
    print(len(stops), "stops")
    sites = []
    for s in sorted(stops, key=lambda s: s["ll"]):
        g = next((g for g in sites if nm(g["ll"], s["ll"]) <= GROUP_NM), None)
        if g:
            g["m"].append(s); n = len(g["m"]); g["ll"] = ((g["ll"][0] * (n - 1) + s["ll"][0]) / n, (g["ll"][1] * (n - 1) + s["ll"][1]) / n)
        else:
            sites.append({"ll": s["ll"], "m": [s]})
    out = []
    for g in sites:
        on = {}
        for k, pts in legs.items():
            d, a = project(pts, g["ll"])
            if d <= NEAR_NM:
                on[k] = {"along": round(a, 2), "offset": round(d, 2)}
        if not on:
            continue
        teams = sorted({(s["year"], s["team"]) for s in g["m"]})
        out.append({"lat": round(g["ll"][0], 4), "lon": round(g["ll"][1], 4), "teams": len(teams), "stops": len(g["m"]),
                    "median_min": round(median(s["min"] for s in g["m"])), "years": sorted({s["year"] for s in g["m"]}),
                    "who": [f"{y} {n}" for y, n in teams][:12], "legs": on})
    out.sort(key=lambda x: min(v["along"] for v in x["legs"].values()))
    (ROOT / "data" / "stops.json").write_text(json.dumps({"stay_nm": STAY_NM, "min_minutes": MIN_MIN, "group_nm": GROUP_NM, "sites": out}, indent=0))
    print(len(out), "sites;", sum(1 for x in out if x["teams"] >= 3), "used by 3+ teams")
    for x in sorted(out, key=lambda x: -x["teams"])[:15]:
        print(x["teams"], x["median_min"], x["lat"], x["lon"], x["legs"])


if __name__ == "__main__":
    main()
