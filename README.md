# Seventy48 2027

Planning tools for a Seventy48 2027 entry: Tacoma to Port Townsend, 70 miles, human power only, 48 hours. The 2027 race starts Friday 28 May 2027 at 19:00 from the Foss Waterway Seaport in Tacoma (teams have 30 minutes to cross the line). The only required checkpoints are Owen Beach and the Port Townsend Ship Canal; the finish is the bell at Northwest Maritime in Port Townsend, by 19:00 Sunday.

## Race planner

`index.html` is an interactive map, built the same way as the R2AK 2028 planner:

- NOAA ENC charts over a light gray or satellite base map, with an opacity slider.
- Course lines west of Vashon (Colvos Passage, 62.3 nm, 71.7 statute miles) and east of Vashon (East Passage, 66.5 nm). Every tracked boat in 2024, 2025 and 2026 went west of Vashon.
- Plan by target finish (default 18 hours: it solves for the speed through the water that gets you there) or by speed (it shows the finish). Breaks every so many hours, drifting with the stream or not, a slower night pace, and fade over the race are all settings.
- The tidal stream along the course comes from the 19 NOAA current stations within 1.2 nm of either line. Each station's predicted speed is resolved onto the course heading using its mean flood and ebb directions, so "with you" comes from the data. Between stations the stream is blended along the course; a station's stream holds 5 nm either side and then fades out (the Port Townsend Canal station only speaks for the canal).
- Result tiles: the speed you need, finish time, average speed over the bottom, how much time the stream saves or costs against still water, time paddling in the dark, the other side of Vashon at the same speed, and the margin to the cutoff.
- Checkpoints and waypoints with your arrival time and what the nearest NOAA station is doing then (and when it turns).
- Stream along the course: a distance by time picture of the stream with your boat's line on it, next to the still-water line, with night shaded.
- Finish time against speed for both sides of Vashon, with your break and pace settings.
- Hour by hour: where you are, speed through the water, stream and speed over the bottom.
- Map time and play bar: the boat moves along the course and every current station shows its arrow (flood, ebb, slack). Click a station for its curve over the race, with the time your plan passes it.
- Past races: every boat in the 2024 to 2026 races from YB Tracking, with where your planned finish would have placed each year, median finish, and which side of Vashon the finishers took. Filter by class; click a team to see its track.

Open it from GitHub with `https://raw.githack.com/georgeclaudevandam-sketch/Seventy48-2027/<branch>/index.html`, or serve the folder locally (`python3 -m http.server`) and open `http://localhost:8000`. It needs to be served over HTTP because it loads `data/*.json`.

## Data

- `data/route.json`: course lines and marks, from `scripts/build_route.py` (shortest water path on a ~55 m grid from the GSHHG full-resolution coastline, with the Thea Foss Waterway and Port Townsend Canal carved in by hand because they are narrower than the grid). For distance and ETA only.
- `data/stations.json` and `data/predictions.json`: from `scripts/fetch_predictions.py`, which the **Fetch tide and current predictions** workflow runs on GitHub Actions whenever the script or the course changes (or on demand from the Actions tab). It finds NOAA current prediction stations near the course from NOAA's metadata API, keeps the shallowest bin of each, and fetches max/slack events for 24 May to 3 June 2027, plus high/low tides at Tacoma, Seattle and Port Townsend.
- `data/tracks/`: past races from YB Tracking (`scripts/fetch_tracks.py`, the **Fetch past Seventy48 tracks** workflow). 2024, 2025 and 2026 are on YB under `seventy48_<year>`; earlier years were not found under the keys tried.

Not for navigation. Use official NOAA tables and current charts aboard.
