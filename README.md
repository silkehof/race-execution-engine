# Race-Day Execution Engine — MVP

Given a race course (GPX) and a goal pace, generates a segment-by-segment
pacing plan (grade + heat adjusted) and a fueling plan (carbs/fluid/sodium).
Fully deterministic so far — the LLM reasoning layer is the next piece.

## Setup

```bash
pip install -r requirements.txt
```

## Run the tests

```bash
pytest tests/ -v
```

62 tests, all deterministic — no network calls required (the weather
module uses dependency injection so it's tested with canned responses).

## Run the MVP

With manual weather (works anywhere, no internet needed):

```bash
python race_plan.py --gpx data/sample_race.gpx --goal-pace 5:05 --temp 18 --humidity 55
```

With live weather (needs internet + your race's real lat/lon/date —
Open-Meteo is free, no API key):

```bash
python race_plan.py --gpx data/sample_race.gpx --goal-pace 5:05 \
    --lat 52.52 --lon 13.405 --date 2026-10-04 --start-hour 9
```

Open-Meteo's forecast only covers ~2 weeks out. If your race date is
further away than that, the output falls back to a 5-year historical
average for that calendar date, clearly labeled as an estimate — once
the date is within the forecast window, the same command switches to
a live forecast automatically.

`data/sample_race.gpx` is a synthetic rolling 8km course
(`scripts/generate_sample_gpx.py`) — swap in your real race's GPX
(exportable from Strava, Garmin Connect, or most race organizer sites)
whenever you have it.

## Architecture

```
GPX file  ─┐
            ├─→ segment_course_from_gpx()  ─→  per-km CourseSegment (grade)
Weather   ─┘                                        │
                                                      ▼
                                       segment_target_pace()  (deterministic)
                                                      │
                                                      ▼
                                          race_fueling_plan()  (deterministic)
                                                      │
                                                      ▼
                                              race_plan.py output
```

See `race-execution-engine-spec.md` for the full v1 spec and roadmap
(LLM reasoning layer, execution analysis, eval harness — not built yet).

## What's built so far

- [x] `engine/pacing.py` — grade adjustment (Minetti et al. 2002) + heat de-rate (WBGT, Ely et al. 2007 / El Helou et al. 2012), 26 tests
- [x] `engine/fueling.py` — carb/fluid/sodium targets, 12 tests
- [x] `ingest/gpx_course.py` — GPX parsing + segmentation, 15 tests (incl. integration checks against `data/sample_race.gpx`)
- [x] `ingest/weather.py` — Open-Meteo fetch, historical-average fallback beyond the forecast window (dependency-injected), 9 tests
- [x] `race_plan.py` — MVP CLI tying it all together
- [ ] `reasoning/` — LLM layer: structured plan + coaching narrative
- [ ] execution analysis — planned vs actual splits
- [ ] `eval/` — the eval harness (the portfolio centerpiece)
- [ ] frontend
