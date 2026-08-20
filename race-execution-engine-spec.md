# Race-Day Execution Engine — v1 Spec & Roadmap

Companion to `README.md` / `OVERVIEW.md`. Those describe what's built;
this describes what the finished v1 looks like and the shape of each
remaining layer. Update this as decisions get made — sections below are
a starting proposal, not locked.

Last updated: 2026-08-20

## Problem

Race-day pacing and fueling advice is usually either a flat goal pace
("just run 5:05/km") that ignores hills and heat, or generic nutrition
rules of thumb. This project generates a course- and weather-aware plan
deterministically, then (v1 goal) layers an LLM on top to turn the raw
numbers into a coaching narrative and to reason about tradeoffs the
deterministic layer can't — e.g. "you're front-loading risk on that
km 6 descent" or "your carb plan assumes 4 gels but you said you only
tolerate 3 — here's the adjustment."

The eval harness is the centerpiece: the interesting engineering problem
isn't generating a plan, it's proving the LLM layer is actually reliable
and grounded in the deterministic numbers rather than hallucinating over
them.

## Non-goals (v1)

- Not a training-plan generator (no periodization, no multi-week plans).
- Not a personalized physiology model — coefficients are population-
  level defaults (see `engine/pacing.py`, `engine/fueling.py` docstrings),
  not fitted to any individual runner.
- Not real-time / in-race (no live GPS feed, no watch integration) —
  plans are generated pre-race and compared post-race.
- No auth/multi-user concerns for v1 — single-user CLI/local tool first,
  frontend (if built) can stay unauthenticated local-only.

## Architecture layers

```
1. Ingest              ─┐
2. Deterministic engine ├─ built (see OVERVIEW.md)
                        ─┘
3. Reasoning (LLM)      ─ built, narrower scope than originally sketched (see below)
4. Execution analysis   ─ not built
5. Eval harness         ─ grounding checks built; consistency/constraint/quality/backtest not built
6. Frontend             ─ not built
```

### 1–2. Ingest + deterministic engine — built

See `OVERVIEW.md` for current state. This is the ground truth the
reasoning layer sits on top of and must not contradict.

### 3. Reasoning layer (`reasoning/`) — built (`reasoning/narrative.py`)

Takes the deterministic `SegmentPacePlan` list + `FuelingPlan` (already
produced by `race_plan.py`) and produces:

- A structured plan object (`structured_race_plan()` — JSON-serializable
  segments + fueling numbers + WBGT safety flags). This part is pure
  Python, no LLM call, and exists regardless of whether a narrative is
  ever generated.
- A short coaching narrative in prose (`generate_race_narrative()`),
  grounded in that structured plan, via a single LLM call.

Design constraint honored: the prompt explicitly tells the model not to
invent, recompute, or restate any number not already in the structured
JSON — narrative and strategy only. Whether the model actually
complies is now checkable — see section 5, grounding checks are built.

Resolved open questions from the original spec:
- **Single LLM call**, not per-segment — the whole structured plan is
  small enough to fit in one prompt.
- **LLM provider/model**: Anthropic, `claude-haiku-4-5-20251001` by
  default (cheapest current model — the prompt is short and doesn't
  need more reasoning power). Dependency-injected (`call_llm_fn`) the
  same way `ingest/weather.py` injects `fetch_fn`, so the whole module
  has full test coverage with zero real API calls.

Deliberately **out of scope for this pass** (narrower than the original
sketch above):
- **No free-text runner context** (goals/constraints like "I can only
  tolerate 3 gels") — the narrative is generated from the deterministic
  plan alone. Adding this is a real follow-up, not a bug; it would need
  a decision on structure (freeform string vs. a small schema) same as
  originally flagged.
- **No per-km fueling schedule** ("gel at km 6, 8, 10") — the narrative
  discusses fueling *timing relative to terrain* in prose (e.g. fueling
  around a tough climb) but doesn't generate a structured gel-by-gel
  schedule. Would need a decision on what unit of fueling to schedule
  around (calories per gel? user's own product?) that the engine
  doesn't currently model.
- Added beyond the original sketch: **WBGT safety flags**
  (`safety_flags_for_conditions()`) — computed deterministically from
  the fluid/sodium literature review's ACSM thresholds (WBGT ≥20.5°C
  "non-elite races shouldn't start," ≥28°C hard competition limit), fed
  to the LLM as facts to open the narrative with, not something it
  computes itself.

### 4. Execution analysis — not built

Post-race: compare planned vs. actual splits (actual splits sourced
from a GPX/TCX file or manually entered per-segment times). Outputs:
- Per-segment delta (ahead/behind plan, and by how much).
- Where the runner's actual pacing diverged from plan and possibly why
  (e.g. "faded starting km 6" cross-referenced against the steep
  descent at that segment).

This is what eventually feeds the eval harness with real-world ground
truth (did the plan's assumptions hold up?) rather than only synthetic
test cases.

### 5. Eval harness (`eval/`) — grounding checks built, rest not yet; portfolio centerpiece

Purpose: demonstrate the reasoning layer is reliable, not just plausible-
sounding. Proposed dimensions:

- **Grounding checks — built (`eval/grounding.py`).** Does the LLM
  narrative's stated paces/times/fueling-rates/grades match the
  structured plan it was given? No LLM judge — regex extraction of
  numeric claims (`check_narrative_grounding()`), checked against exact
  values (paces, total time) or ranges (fluid/sodium). Pass/fail bar
  resolved: **exact string match** for paces/times (they come from
  `format_pace()`/a fixed H:MM:SS format, so exact match is the right
  bar, not a tolerance band — there's no reason a grounded citation
  would round differently) and **range membership** for fueling
  (already a low-high band, not a point value). Wired into
  `race_plan.py --narrative --eval`; 11 tests against hand-written
  narrative fixtures, both clean and deliberately fabricated, including
  a fixture that caught a real bug in the checker itself during
  development (comparing `"6:04"` against `"6:04/km"` never matched).
  Known limitation: pattern-matching only catches numeric claims with a
  recognizable format, not prose-only claims, and will false-positive
  on a coincidental match (e.g. a percentage used as a vague qualifier,
  not a grade citation) — an accepted cost of avoiding an LLM judge.
- **Consistency checks** — same inputs in, same structured plan out
  (or within tolerance) across repeated calls. Not built: the
  structured plan itself is already guaranteed identical (pure
  Python, no LLM), so the only open question is narrative-text
  consistency across repeated real calls — needs actual repeated API
  calls (cost) to be meaningful, not just a fixture-based test.
- **Constraint adherence** — if runner context says "max 3 gels," does
  the fueling schedule respect that? Blocked on runner free-text
  context existing at all (see section 3's "out of scope" list) — not
  built.
- **Quality/usefulness** — harder to automate; likely needs an LLM-judge
  rubric or a small hand-labeled set, scored against criteria like
  "identifies the highest-risk segment," "fueling timing is
  actionable." Not built — needs either an LLM judge (cost) or manual
  labeling effort.
- **Backtest against real races** (once execution analysis exists) —
  did the plan's risk calls (e.g. "you'll fade on this climb") predict
  what actually happened in the runner's actual splits? Not built —
  blocked on section 4 (execution analysis) existing.

Open questions:
- Golden test set: synthetic courses only, or curated real GPX files
  too? (`mmm25.gpx`, a real Madrid half marathon course, already exists
  in the repo and was used to validate the grade-damping fix — a
  natural candidate for a grounding-check golden set once real
  `--narrative` output is being collected somewhere, e.g. cached
  fixtures of real model responses rather than only synthetic ones.)

### 6. Frontend — not built

Lowest priority; exact shape (web form, simple static report, CLI-only)
still open. Should consume the structured plan JSON from the reasoning
layer, not reimplement any formatting logic already in `race_plan.py`.

## Roadmap / suggested order

1. ~~`reasoning/` — structured plan + narrative, single-call~~ — built,
   no runner context yet (see section 3's "out of scope" list).
2. ~~`eval/` grounding checks against `reasoning/`~~ — built
   (`eval/grounding.py`), catches the most damaging failure mode (LLM
   contradicting the deterministic math) without needing an LLM judge.
   Consistency checks not built (need real repeated API calls to be
   meaningful, not just fixtures).
3. **Next up.** Execution analysis — needs at least one real race's
   actual splits to be useful; can be stubbed with synthetic "actual"
   data before that.
4. Eval harness quality/backtest dimensions, once execution analysis
   and a few real races exist.
5. Frontend, once the JSON contract from `reasoning/` is stable.

## Open questions (repo-level)

- ~~No git repo yet~~ — resolved, see https://github.com/silkehof/race-execution-engine (private).
- ~~LLM provider/model choice for `reasoning/`~~ — resolved: Anthropic,
  `claude-haiku-4-5-20251001` by default, see `reasoning/narrative.py`.
