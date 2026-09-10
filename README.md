# Race-Day Execution Engine — MVP

Given a race course (GPX) and a goal pace, generates a segment-by-segment
pacing plan (grade + heat adjusted) and a fueling plan (carbs/fluid/sodium).
The pacing/fueling core is fully deterministic and free to run. An
opt-in LLM layer (`--narrative`) turns that plan into a coaching
narrative — the only part of the project that calls an LLM or costs
money — and a free eval harness (`--eval`) checks whether that
narrative actually stayed grounded in the numbers it was given.

## How this was built

This is an AI-built project. The code was written by Claude (via Claude Code) rather
than typed by hand, and the physiology it rests on — Minetti's grade curve, the WBGT
heat model, the ACSM fueling ranges — was researched during the build, not knowledge
I brought to it. The Python is deliberately plain for the same reason.

What I contributed is the direction: keep the LLM out of the math, damp the grade
curve to something a runner can actually execute instead of the theoretical optimum,
and build the grounding eval because a model writing a coaching note will otherwise
invent numbers. Those are the calls I'd stand behind in a conversation about it.

## Setup

```bash
pip install -r requirements.txt
```

## Run the tests

```bash
pytest tests/ -v
```

100 tests, all deterministic — no network calls and no LLM calls
required (the weather and reasoning modules both use dependency
injection so they're tested with canned responses; the eval module is
tested against hand-written narrative fixtures).

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
(`scripts/generate_sample_gpx.py`); `mmm25.gpx` is a real half marathon
course (Movistar Medio Maraton Madrid) — swap in your own race's GPX
(exportable from Strava, Garmin Connect, or most race organizer sites)
whenever you have it.

## Grade model: practical (default) vs. raw

The per-km target pace is grade-adjusted using Minetti et al. 2002's
metabolic-cost curve. Used *raw*, that curve swings pace by 2+ min/km
on a real, fairly modest rolling course (Madrid's ~4% hills) — a
constant-effort theoretical target, not something a runner can actually
execute km-by-km. By default the swing is damped by half
(`GRADE_DAMPING_RATIO = 0.5` in `engine/pacing.py`) toward a more
pace-able target; add `--raw-grade-model` to see the undamped curve.
The header always states which one is active:

```bash
python race_plan.py --gpx mmm25.gpx --goal-pace 5:05 --temp 22 --humidity 55                    # practical (default)
python race_plan.py --gpx mmm25.gpx --goal-pace 5:05 --temp 22 --humidity 55 --raw-grade-model   # raw Minetti
```

## Adding a coaching narrative (optional, costs money)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
python race_plan.py --gpx data/sample_race.gpx --goal-pace 5:05 --temp 18 --humidity 55 --narrative
```

Everything above this flag is free and deterministic. `--narrative`
makes one real Anthropic API call (currently Haiku — see
`reasoning/narrative.py`) to turn the already-computed plan into a
short coaching note. It's given the exact numbers and told not to
invent, recompute, or restate anything not already there — its job is
strategy and narrative (e.g. "don't bank time on the km 8 downhill,
that's where the heat starts biting"), not the math.

## Checking the narrative stayed grounded (free)

```bash
python race_plan.py --gpx mmm25.gpx --goal-pace 5:05 --temp 22 --humidity 55 --narrative --eval
```

`--eval` (only meaningful alongside `--narrative`) runs `eval/grounding.py`
against the narrative that was just generated — no extra API call, it's
just inspecting the response already returned. It regex-extracts
numeric claims (paces, total times, fueling rates, grade percentages)
and checks each one against the structured plan, catching exactly the
failure mode the prompt asks the model to avoid but can't enforce on
its own: stating a pace or number that isn't actually in the plan. It's
pattern-matching, not an LLM judge — narrow by design, see
`OVERVIEW.md` for the tradeoffs.

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
                                              race_plan.py output  (free, always)
                                                      │
                                                      ▼  (only with --narrative)
                                     structured_race_plan() → generate_race_narrative()
                                                                (LLM call, costs money)
                                                      │
                                                      ▼  (only with --narrative --eval)
                                          evaluate_race_narrative()  (free)
```

See `race-execution-engine-spec.md` for the full v1 spec and roadmap
(execution analysis, and the eval harness's remaining dimensions —
consistency, constraint adherence, quality/backtest — not built yet).

## What's built so far

- [x] `engine/pacing.py` — grade adjustment (Minetti et al. 2002, damped by default for practical pacing, `--raw-grade-model` for the undamped curve) + heat de-rate (WBGT, Ely et al. 2007 / El Helou et al. 2012), 34 tests
- [x] `engine/fueling.py` — carbs (point) + fluid/sodium as ranges, not point targets (ACSM/Sawka et al. 2007, Baker et al. 2017/2023) with a "drink to thirst" safety caveat in the CLI output, 17 tests
- [x] `ingest/gpx_course.py` — GPX parsing + segmentation, 15 tests (incl. integration checks against `data/sample_race.gpx`)
- [x] `ingest/weather.py` — Open-Meteo fetch, historical-average fallback beyond the forecast window (dependency-injected), 9 tests
- [x] `reasoning/narrative.py` — structured plan (free) + coaching narrative (opt-in LLM call, dependency-injected same as weather), WBGT-based safety flags, 14 tests
- [x] `eval/grounding.py` — grounding checks (does the narrative's numeric claims match the structured plan?), free, opt-in via `--eval`, 11 tests
- [x] `race_plan.py` — MVP CLI tying it all together
- [ ] execution analysis — planned vs actual splits
- [ ] eval harness: consistency checks, constraint adherence, quality/usefulness scoring, backtesting — grounding checks only so far
- [ ] frontend
