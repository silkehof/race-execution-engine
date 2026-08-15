# Project Overview — Race-Day Execution Engine

Living document. Update this as the project grows — new modules, new
layers, new decisions. Keep it in sync with reality, not aspirational.

Last updated: 2026-08-15

## What this is

Given a race course (GPX) and a goal pace, generates a segment-by-segment
pacing plan (grade + heat adjusted) and a fueling plan (carbs/fluid/sodium).

Current stage: fully deterministic MVP. No LLM call yet. The eventual
plan is to add an LLM reasoning layer on top of this deterministic
core, plus execution analysis and an eval harness — see
`race-execution-engine-spec.md` for the full v1 spec and roadmap, and
"Not built yet" below for the short version.

## Layout

```
execution-engine/
├── engine/              deterministic math — pacing & fueling
│   ├── pacing.py        grade adjustment, heat de-rate, target pace
│   └── fueling.py       carb/fluid/sodium targets
├── ingest/              turning raw inputs into structured data
│   ├── gpx_course.py    GPX parsing → per-km CourseSegment list
│   └── weather.py       Open-Meteo fetch (dependency-injected fetch_fn)
├── scripts/
│   └── generate_sample_gpx.py   builds data/sample_race.gpx
├── data/
│   └── sample_race.gpx  synthetic 8km rolling course
├── tests/               44 tests, pytest, no network calls required
├── race_plan.py         MVP CLI — ties everything together
├── demo.py              quick sanity check with hand-built segments
├── requirements.txt     gpxpy, requests, pytest
└── README.md
```

## Data flow

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

## Module notes

**`engine/pacing.py`** — pure functions, no I/O.
- `grade_adjustment_factor(grade)`: ratio of metabolic cost at this
  grade vs. flat ground, from Minetti et al. 2002's fitted polynomial
  (`minetti_energy_cost`) — the same physiological basis Strava's GAP
  is built on. Uphill cost rises convexly (10% grade costs ~66% more
  than flat, not the ~33% a linear model would suggest); downhill cost
  drops to a minimum around -18% grade (~half of flat) before rising
  again, crossing back above flat-ground cost around -40%. Clamped to
  ±45% grade (`MINETTI_GRADE_CLAMP`), the range the curve is validated
  for. Not fitted to this project's own data — it's the published
  research curve as-is, not a personal calibration. Was previously a
  hand-picked piecewise-linear approximation that had a bug: it flipped
  sign around -18/-20% grade and predicted steep descents were *harder*
  than flat, which contradicts every source checked.
- `heat_derate_factor(temp_c, humidity_pct)`: indexed by simplified WBGT
  (`simplified_wbgt`, ACSM's temp+humidity-only formula — no new
  ingestion needed) rather than raw dry-bulb temperature, per Ely et
  al. 2007 / El Helou et al. 2012. Progressive slowdown above a ~5°C
  WBGT baseline (Ely's coolest studied band — there's no true
  zero-effect point) at a fixed ~1.8%/5°C slope, matching a
  recreational/mid-pack finisher (Ely's data shows this varies a lot
  by pace — back-of-pack runners are ~3-4x more heat-sensitive than
  elites — but pace-tiering isn't built yet, see "Open questions").
  Was previously a hand-picked onset-threshold-on-raw-temperature
  heuristic; at the project's own demo conditions (18°C/55% RH) it
  under-predicted slowdown by roughly 5x (0.9% vs. the ~5% the WBGT
  model now gives).
- `segment_target_pace(base_pace_sec_per_km, grade, temp_c, humidity_pct)`:
  combines both into one `SegmentPacePlan`.
- `format_pace` / `parse_pace`: `"5:05"` ↔ `305.0` sec/km.

**`engine/fueling.py`** — pure functions, no I/O.
- `carb_target_g_per_hr(duration_hr)`: tiered ramp, 0g (<1hr) →
  30-60g (1-2.5hr) → 60-90g (>2.5hr, caps at 4hr).
- `fluid_target_ml_per_hr` / `sodium_target_mg_per_hr`: baseline +
  heat/humidity-scaled extra, same shape as the pacing heat de-rate.
- `race_fueling_plan(duration_hr, temp_c, humidity_pct)`: combines all
  three into a `FuelingPlan` with per-hour and total figures.

**`ingest/gpx_course.py`**
- `segment_course_from_profile(cum_dist_km, elevations, segment_length_km)`:
  pure geometry over plain lists — buckets a distance/elevation profile
  into fixed-length `CourseSegment`s, interpolating elevation at
  boundaries. This is the exactly-testable layer.
- `segment_course_from_gpx(gpx_path, segment_length_km)`: thin gpxpy
  wrapper (parse → cumulative 3D distance → hand off to the pure
  function above). Deliberately kept separate so tests don't fight
  GPS floating-point noise. Covered by real-file "does this look sane"
  checks in `tests/test_gpx_course.py` (segment count, total distance,
  climb/descent sign) rather than exact-value assertions.

**`ingest/weather.py`**
- `fetch_weather(lat, lon, date_iso, start_hour, fetch_fn=None)`: hits
  Open-Meteo. Three sources depending on `date_iso`, reported on the
  returned `WeatherConditions.source`:
  - within `FORECAST_WINDOW_DAYS` (~2 weeks): live forecast (`"forecast"`)
  - a past date: real historical actuals (`"archive"`, enables backtesting)
  - a future date beyond the forecast window: average of the same
    calendar date over the past `HISTORICAL_AVERAGE_YEARS` (5) years
    (`"historical_estimate"`) — a planning estimate, not a forecast.
    Re-running the same command once the race date falls inside the
    forecast window switches it to a live forecast automatically.
  `fetch_fn` is injected for testability; no real network call needed
  in tests. `race_plan.py` labels the source in its output so it's
  always clear which kind of weather you're looking at.

**`race_plan.py`** — CLI entrypoint. `--gpx`, `--goal-pace`, plus either
`--temp`/`--humidity` (manual) or `--lat`/`--lon`/`--date`/`--start-hour`
(live fetch). Prints a per-segment pacing table + total time + fueling
summary.

**`demo.py`** — pre-ingest sanity check with hand-built segments
(predates `ingest/`). Superseded by `race_plan.py` for anything
GPX-driven; keep only as long as it's still useful for quick iteration
on `engine/` without needing a GPX file.

## Testing

`pytest tests/ -v` — 59 tests, fully deterministic, no network calls
(weather module tested via injected canned `fetch_fn`; the GPX layer
has a real-file integration check against `data/sample_race.gpx`
alongside the pure-function unit tests).

## Not built yet (see `race-execution-engine-spec.md` for detail)

- [ ] `reasoning/` — LLM layer: structured plan + coaching narrative
      on top of the deterministic engine (not a replacement for it)
- [ ] execution analysis — planned vs. actual splits
- [ ] `eval/` — eval harness (called out as the portfolio centerpiece)
- [ ] frontend

## Open questions / things to revisit as this grows

- **Pace-tiered heat sensitivity, deferred.** `heat_derate_factor` uses
  a single mid-pack/recreational WBGT slope (~1.8%/5°C, per Ely et al.
  2007). Ely's data shows this varies a lot by pace/effort — a
  back-of-pack finisher is ~3-4x more heat-sensitive than an elite
  (~3.2%/5°C vs. ~0.9%/5°C) — so a fast and slow runner in identical
  weather currently get the same heat penalty, which understates it for
  slower runners and overstates it for faster ones. Fixing this needs
  the runner's *goal* pace threaded in as a tier proxy (predicted
  finish time isn't known yet at this point in the pipeline — using it
  directly would be circular) plus a design decision on tier boundaries.
- Both `grade_adjustment_factor` (Minetti et al. 2002 polynomial) and
  `heat_derate_factor` (WBGT-indexed, Ely et al. 2007 / El Helou et al.
  2012) are now built from cited published research rather than
  hand-picked constants — see `engine/pacing.py` for the full citations
  and derivations. Still not calibrated to any individual runner's own
  splits, and `engine/fueling.py`'s fluid/sodium heat scaling hasn't
  had the same research pass yet (it's a separate, independent
  heuristic from the pacing heat model, same onset-threshold pattern
  the old heat model used).
- No git repo yet at the project root — worth initializing once the
  reasoning layer work starts, to track that transition cleanly.
