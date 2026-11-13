#!/usr/bin/env python3
"""Places to land or tie up near the Seventy48 course, for breaks, rests and sheltering from wind.

Reads OpenStreetMap (Overpass) for beaches and shingle shores, campsites (Cascadia Marine Trail sites are tagged as
campsites), slipways and boat launches, marinas and small-craft facilities within NEAR_NM of either course line, merges
features within MERGE_NM of each other, and writes data/landings.json. For checking them by eye it also writes contact sheets
of Esri satellite imagery around each one (data/landings/sheets/*.jpg, 16 per sheet, ~400 m across, numbered as in
landings.json).
"""
from __future__ import annotations

import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
NEAR_NM, MERGE_NM = 1.5, 0.15
BBOX = (47.22, -122.85, 48.15, -122.30)
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
             "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
UA = {"User-Agent": "seventy48-2027 planner (github.com/georgeclaudevandam-sketch/Seventy48-2027)"}
B = ",".join(map(str, BBOX))
QUERY = f"""[out:json][timeout:300];
(nwr["natural"~"^(beach|shingle)$"]({B}); nwr["tourism"="camp_site"]({B}); nwr["leisure"~"^(slipway|marina)$"]({B});
 nwr["amenity"="boat_launch"]({B}); nwr["seamark:type"~"^(small_craft_facility|harbour)$"]({B}););
out center tags;"""
IMG = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
Z = 17
RANK = {"campsite": 0, "beach": 1, "shingle": 2, "slipway": 3, "marina": 4, "small craft": 5}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, data=None, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA), timeout=timeout) as r:
        return r.read()


def overpass():
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    for i in range(6):
        url = ENDPOINTS[i % len(ENDPOINTS)]
        try:
            return json.loads(get(url, data, 400))["elements"]
        except Exception as e:
            log(f"  {url}: {type(e).__name__} {e}")
            time.sleep(15 * (i + 1))
    sys.exit("Overpass failed")


def nm(a, b):
    return math.hypot((b[0] - a[0]) * 60, (b[1] - a[1]) * 60 * math.cos(math.radians(a[0])))


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def chip(lat, lon, size=256, z=Z):
    """~400 m (zoom 17) or ~750 m (zoom 16) of imagery centred on lat, lon, scaled to size px, with a crosshair."""
    fx, fy = tile_xy(lat, lon, z)
    x0, y0 = int(fx) - 1, int(fy) - 1
    im = Image.new("RGB", (768, 768), (20, 30, 40))
    for dx in range(3):
        for dy in range(3):
            try:
                im.paste(Image.open(io.BytesIO(get(IMG.format(z=z, x=x0 + dx, y=y0 + dy)))).convert("RGB"), (dx * 256, dy * 256))
            except Exception as e:
                log(f"  tile {e}")
    cx, cy = (fx - x0) * 256, (fy - y0) * 256
    im = im.crop((int(cx - 256), int(cy - 256), int(cx + 256), int(cy + 256)))   # the point is in the middle tile, so this fits
    im = im.resize((size, size))
    d = ImageDraw.Draw(im)
    c = size // 2
    d.line((c - 14, c, c - 5, c), fill=(255, 60, 60), width=2); d.line((c + 5, c, c + 14, c), fill=(255, 60, 60), width=2)
    d.line((c, c - 14, c, c - 5), fill=(255, 60, 60), width=2); d.line((c, c + 5, c, c + 14), fill=(255, 60, 60), width=2)
    return im


def kind_of(t):
    if t.get("tourism") == "camp_site": return "campsite"
    if t.get("natural") in ("beach", "shingle"): return t["natural"]
    if t.get("leisure") == "slipway" or t.get("amenity") == "boat_launch": return "slipway"
    if t.get("leisure") == "marina": return "marina"
    return "small craft"


def main():
    route = json.loads((ROOT / "data" / "route.json").read_text())
    legs = {l["key"]: l["points"] for l in route["legs"]}
    dense = {}
    for k, pts in legs.items():
        d, cum = [], 0.0
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(nm(a, b) / 0.1))
            for j in range(n):
                d.append((a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n, cum + nm(a, b) * j / n))
            cum += nm(a, b)
        dense[k] = d
    els = overpass()
    log(f"{len(els)} candidate features in the box")
    cand = []
    for e in els:
        la, lo = (e["lat"], e["lon"]) if "lat" in e else (e["center"]["lat"], e["center"]["lon"])
        on = {}
        for k, d in dense.items():
            best = min(d, key=lambda p: nm((la, lo), p))
            if nm((la, lo), best) <= NEAR_NM:
                on[k] = {"along": round(best[2], 2), "offset": round(nm((la, lo), best), 2)}
        if not on:
            continue
        t = e.get("tags", {})
        if t.get("access") in ("private", "no"):
            continue
        cand.append({"lat": round(la, 5), "lon": round(lo, 5), "kind": kind_of(t), "name": t.get("name", ""), "osm": f"{e['type']}/{e['id']}", "legs": on})
    cand.sort(key=lambda x: (RANK[x["kind"]], not x["name"]))
    out = []
    for c in cand:
        o = next((o for o in out if nm((c["lat"], c["lon"]), (o["lat"], o["lon"])) < MERGE_NM), None)
        if o:
            if not o["name"] and c["name"]: o["name"] = c["name"]
            if c["kind"] != o["kind"] and c["kind"] not in o.setdefault("also", []): o["also"].append(c["kind"])
            continue
        out.append(c)
    out.sort(key=lambda x: min(v["along"] for v in x["legs"].values()))
    for i, o in enumerate(out):
        o["n"] = i + 1
    (ROOT / "data" / "landings.json").write_text(json.dumps({
        "source": "OpenStreetMap contributors (ODbL); imagery Esri World Imagery", "near_nm": NEAR_NM,
        "generated": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "landings": out}, indent=0))
    log(f"{len(out)} landings within {NEAR_NM} nm of the course")
    sd = ROOT / "data" / "landings" / "sheets"
    sd.mkdir(parents=True, exist_ok=True)
    for f in sd.glob("*.jpg"):
        f.unlink()
    for s in range(0, len(out), 16):
        sheet = Image.new("RGB", (4 * 260, 4 * 278), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for k, o in enumerate(out[s:s + 16]):
            x, y = (k % 4) * 260, (k // 4) * 278
            sheet.paste(chip(o["lat"], o["lon"]), (x + 2, y + 2))
            d.text((x + 4, y + 260), f"#{o['n']} {o['kind']} {o['name'][:22]}", fill=(0, 0, 0))
        sheet.save(sd / f"sheet{s // 16 + 1:02d}.jpg", quality=72)
        log(f"  sheet {s // 16 + 1}")


if __name__ == "__main__":
    main()
