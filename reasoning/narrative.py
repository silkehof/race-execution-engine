"""
LLM reasoning layer.

This is the only part of the project that calls an LLM. Everything it
consumes (per-segment pace, fueling numbers, safety flags) is already
computed by the deterministic engine before this module ever runs --
the LLM's job is strategy and narrative on top of those numbers, not
recomputing them. It's explicitly told not to invent or restate a
number that isn't already in the structured plan it's given; whether
it actually complies is a grounding-check problem for eval/, not
something this module can guarantee on its own.

Same dependency-injection pattern as ingest/weather.py's fetch_fn:
call_llm_fn defaults to a real Anthropic API call but every test (and
all development of this module) passes in a canned function instead --
so this whole module has full test coverage with zero real API calls
and zero cost. A real call only happens if you explicitly run it
without overriding call_llm_fn, e.g. via race_plan.py --narrative.
"""

import json
from dataclasses import dataclass, asdict
from typing import Callable, List, Optional

from engine.pacing import simplified_wbgt, format_pace
from engine.fueling import FuelingPlan
from ingest.gpx_course import CourseSegment
from engine.pacing import SegmentPacePlan


# --- Safety flags ---------------------------------------------------------
#
# Computed deterministically from WBGT, not by the LLM -- per ACSM's
# published guidance (see the fluid/sodium literature review): non-elite
# races are advised not to start above WBGT 20.5C, and 28C is ACSM's
# upper limit for competition at all. These are handed to the LLM as
# facts to narrate, not something it's asked to judge or compute itself.

WBGT_NON_ELITE_START_THRESHOLD_C = 20.5
WBGT_ACSM_COMPETITION_LIMIT_C = 28.0


@dataclass
class SafetyFlag:
    level: str  # "caution" | "warning"
    message: str


def safety_flags_for_conditions(temp_c: float, humidity_pct: float) -> List[SafetyFlag]:
    wbgt = simplified_wbgt(temp_c, humidity_pct)
    flags = []

    if wbgt >= WBGT_ACSM_COMPETITION_LIMIT_C:
        flags.append(SafetyFlag(
            level="warning",
            message=(
                f"WBGT {wbgt:.1f}C is at or above ACSM's upper limit for "
                f"competition ({WBGT_ACSM_COMPETITION_LIMIT_C}C) -- heat "
                "illness risk is significant regardless of pacing strategy."
            ),
        ))
    elif wbgt >= WBGT_NON_ELITE_START_THRESHOLD_C:
        flags.append(SafetyFlag(
            level="caution",
            message=(
                f"WBGT {wbgt:.1f}C is above the {WBGT_NON_ELITE_START_THRESHOLD_C}C "
                "threshold some race-medical guidance recommends non-elite "
                "races avoid starting above -- expect a real performance "
                "and safety impact from heat."
            ),
        ))

    return flags


# --- Structured plan (no LLM involved) -------------------------------------
#
# Pure serialization of what the deterministic engine already computed.
# This is the "structured JSON output" from the spec -- it exists
# whether or not an LLM is ever called, and the narrative is required to
# be grounded in exactly this, nothing more.

def structured_race_plan(
    segments: List[CourseSegment],
    pace_plans: List[SegmentPacePlan],
    fueling_plan: FuelingPlan,
    weather_source: str,
    safety_flags: List[SafetyFlag],
) -> dict:
    segment_records = []
    cumulative_time_sec = 0.0

    for seg, plan in zip(segments, pace_plans):
        segment_time_sec = plan.target_pace_sec_per_km * seg.distance_km
        cumulative_time_sec += segment_time_sec
        segment_records.append({
            "index": seg.index,
            "start_km": seg.start_km,
            "end_km": seg.end_km,
            "distance_km": seg.distance_km,
            "grade_pct": seg.avg_grade * 100,
            "grade_factor": plan.grade_factor,
            "heat_factor": plan.heat_factor,
            "target_pace_sec_per_km": plan.target_pace_sec_per_km,
            "target_pace": format_pace(plan.target_pace_sec_per_km),
            "segment_time_sec": segment_time_sec,
            "cumulative_time_sec": cumulative_time_sec,
        })

    temp_c = pace_plans[0].temp_c if pace_plans else None
    humidity_pct = pace_plans[0].humidity_pct if pace_plans else None

    return {
        "course": {
            "segments": segment_records,
            "total_distance_km": sum(seg.distance_km for seg in segments),
            "predicted_time_sec": cumulative_time_sec,
        },
        "weather": {
            "temp_c": temp_c,
            "humidity_pct": humidity_pct,
            "wbgt_c": simplified_wbgt(temp_c, humidity_pct) if temp_c is not None else None,
            "source": weather_source,
        },
        "fueling": asdict(fueling_plan),
        "safety_flags": [asdict(f) for f in safety_flags],
    }


# --- Prompt + LLM call -----------------------------------------------------

def build_narrative_prompt(structured_plan: dict) -> str:
    plan_json = json.dumps(structured_plan, indent=2)
    return f"""Here is a deterministically-computed race plan (grade- and \
heat-adjusted pacing per segment, plus a fueling plan) for an upcoming race. \
Every number below was computed by a physics/physiology model, not by you -- \
do not invent, recompute, or restate any pace, time, or fueling number that \
isn't already in this JSON.

{plan_json}

Write a short race-day strategy note (3-5 short paragraphs, plain prose, no \
headers) that:

1. Highlights the 2-4 segments where the combination of grade and heat \
matters most for strategy -- e.g. a downhill segment where heat_factor is \
already elevated, so time "banked" there will likely be lost to heat later, \
or a climb worth being conservative on.
2. Points out anywhere pacing strategy and fueling timing interact (e.g. a \
tough climb shortly after a planned fueling point).
3. If safety_flags is non-empty, open with those -- they're the \
highest-priority thing to communicate, not a footnote.
4. Reminds the runner that fluid/sodium are ranges to drink-to-thirst \
against, not fixed targets -- don't restate them as a single number.

Reference specific segment indices and the exact numbers given when making a \
point, but do not introduce any number not present in the JSON above.
"""


DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # cheapest current model -- this call is short and doesn't need more


def _default_call_llm(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """
    Real Anthropic API call -- costs money, needs ANTHROPIC_API_KEY set.
    Only reached if generate_race_narrative() is called without overriding
    call_llm_fn. Import is lazy so the `anthropic` package isn't required
    just to run this module's tests.
    """
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


@dataclass
class RaceNarrative:
    structured_plan: dict
    narrative_text: str


def generate_race_narrative(
    segments: List[CourseSegment],
    pace_plans: List[SegmentPacePlan],
    fueling_plan: FuelingPlan,
    weather_source: str,
    call_llm_fn: Optional[Callable[[str], str]] = None,
) -> RaceNarrative:
    call_llm_fn = call_llm_fn or _default_call_llm

    temp_c = pace_plans[0].temp_c if pace_plans else None
    humidity_pct = pace_plans[0].humidity_pct if pace_plans else None
    safety_flags = (
        safety_flags_for_conditions(temp_c, humidity_pct) if temp_c is not None else []
    )

    structured_plan = structured_race_plan(
        segments, pace_plans, fueling_plan, weather_source, safety_flags
    )
    prompt = build_narrative_prompt(structured_plan)
    narrative_text = call_llm_fn(prompt)

    return RaceNarrative(structured_plan=structured_plan, narrative_text=narrative_text)
