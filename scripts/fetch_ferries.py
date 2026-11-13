#!/usr/bin/env python3
"""Washington State Ferries sailings on and across the course, for animating the ferries in the planner (data/ferries.json).

From the WSF GTFS feed. The 2027 spring schedule isn't published yet, so this takes the sailings in the current feed for a
Friday, a Saturday and a Sunday (the race runs Friday evening to Sunday evening), the first such dates the feed covers,
for every route with a terminal near the course: Point Defiance-Tahlequah, Fauntleroy-Vashon-Southworth, Seattle-Bremerton,
Seattle-Bainbridge, Edmonds-Kingston, Mukilteo-Clinton and Port Townsend-Coupeville. Times are seconds after local midnight.
Re-run when WSF publishes the spring 2027 schedule.
"""
import csv, io, json, sys, urllib.request, zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URLS = ["https://business.wsdot.wa.gov/Transit/csv_files/wsf/google_transit.zip"]
UA = {"User-Agent": "seventy48-2027 planner (github.com/georgeclaudevandam-sketch/Seventy48-2027)"}
BBOX = (47.20, -122.95, 48.25, -122.20)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch():
    for u in URLS:
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120) as r:
                b = r.read()
            if b[:2] == b"PK":
                log(f"{u}: {len(b)} bytes"); return zipfile.ZipFile(io.BytesIO(b))
            log(f"{u}: not a zip")
        except Exception as e:
            log(f"{u}: {type(e).__name__} {e}")
    return None


def table(z, name):
    try:
        return list(csv.DictReader(io.TextIOWrapper(z.open(name), "utf-8-sig")))
    except KeyError:
        return []


def secs(s):
    h, m, x = (int(v) for v in s.strip().split(":"))
    return h * 3600 + m * 60 + x


def main():
    z = fetch()
    if not z:
        sys.exit(1)
    stops = {s["stop_id"]: s for s in table(z, "stops.txt")}
    near = {k for k, s in stops.items() if BBOX[0] <= float(s["stop_lat"]) <= BBOX[2] and BBOX[1] <= float(s["stop_lon"]) <= BBOX[3]}
    routes = {r["route_id"]: r for r in table(z, "routes.txt")}
    trips = {t["trip_id"]: t for t in table(z, "trips.txt")}
    st = {}
    for r in table(z, "stop_times.txt"):
        st.setdefault(r["trip_id"], []).append((int(r["stop_sequence"]), r["stop_id"], secs(r["departure_time"] or r["arrival_time"]), secs(r["arrival_time"] or r["departure_time"])))
    cal = {c["service_id"]: c for c in table(z, "calendar.txt")}
    cdates = {}
    for c in table(z, "calendar_dates.txt"):
        cdates.setdefault(c["date"], {})[c["service_id"]] = c["exception_type"]
    def active(d):
        ds, wd, out = d.strftime("%Y%m%d"), d.strftime("%A").lower(), set()
        for sid, c in cal.items():
            if c["start_date"] <= ds <= c["end_date"] and c.get(wd) == "1":
                out.add(sid)
        for sid, x in cdates.get(ds, {}).items():
            (out.add if x == "1" else out.discard)(sid)
        return out
    all_dates = sorted({c["start_date"] for c in cal.values()} | {c["end_date"] for c in cal.values()} | set(cdates))
    d0, d1 = date.fromisoformat(f"{all_dates[0][:4]}-{all_dates[0][4:6]}-{all_dates[0][6:]}"), date.fromisoformat(f"{all_dates[-1][:4]}-{all_dates[-1][4:6]}-{all_dates[-1][6:]}")
    log(f"feed covers {d0} to {d1}")
    shapes = {}
    for s in table(z, "shapes.txt"):
        shapes.setdefault(s["shape_id"], []).append((int(s["shape_pt_sequence"]), round(float(s["shape_pt_lat"]), 5), round(float(s["shape_pt_lon"]), 5)))
    used_shapes, used_stops, days = set(), set(), {}
    for name, wd in (("fri", 4), ("sat", 5), ("sun", 6)):
        best = None
        d = d0
        while d <= d1:   # the first date with this weekday that has sailings near the course (later ones may be holidays)
            if d.weekday() == wd:
                sv = active(d)
                n = sum(1 for t in trips.values() if t["service_id"] in sv and any(x[1] in near for x in st.get(t["trip_id"], [])))
                if n:
                    best = (d, sv); break
            d += timedelta(days=1)
        if not best:
            log(f"{name}: no sailings"); continue
        d, sv = best; out = []
        for tid, t in trips.items():
            if t["service_id"] not in sv:
                continue
            seq = sorted(st.get(tid, []))
            if len(seq) < 2 or not any(x[1] in near for x in seq):
                continue
            r = routes.get(t["route_id"], {})
            out.append({"route": r.get("route_long_name") or r.get("route_short_name") or t["route_id"], "shape": t.get("shape_id") or None,
                        "st": [[x[1], x[3], x[2]] for x in seq]})   # stop, arrive, depart
            used_stops.update(x[1] for x in seq)
            if t.get("shape_id"): used_shapes.add(t["shape_id"])
        out.sort(key=lambda x: x["st"][0][2])
        days[name] = {"date": d.isoformat(), "trips": out}
        log(f"{name} {d}: {len(out)} sailings")
    (ROOT / "data/ferries.json").write_text(json.dumps({
        "source": "Washington State Ferries GTFS (" + URLS[0] + ")", "feed": [d0.isoformat(), d1.isoformat()],
        "note": "Sailings from the current WSF schedule for a Friday, Saturday and Sunday; the spring 2027 schedule may differ.",
        "stops": {k: {"name": stops[k]["stop_name"], "lat": float(stops[k]["stop_lat"]), "lon": float(stops[k]["stop_lon"])} for k in used_stops},
        "shapes": {k: [[p[1], p[2]] for p in sorted(shapes[k])] for k in used_shapes if k in shapes},
        "days": days}, separators=(",", ":")))


if __name__ == "__main__":
    main()
