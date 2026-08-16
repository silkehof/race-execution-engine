import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest

from ingest.gpx_course import CourseSegment
from engine.pacing import segment_target_pace
from engine.fueling import race_fueling_plan
from reasoning.narrative import (
    safety_flags_for_conditions,
    structured_race_plan,
    build_narrative_prompt,
    generate_race_narrative,
    RaceNarrative,
    WBGT_NON_ELITE_START_THRESHOLD_C,
    WBGT_ACSM_COMPETITION_LIMIT_C,
)


def _fake_segments():
    return [
        CourseSegment(index=0, start_km=0.0, end_km=1.0, distance_km=1.0,
                      elevation_gain_m=0.0, elevation_loss_m=0.0, avg_grade=0.0),
        CourseSegment(index=1, start_km=1.0, end_km=2.0, distance_km=1.0,
                      elevation_gain_m=0.0, elevation_loss_m=50.0, avg_grade=-0.05),
    ]


def _fake_pace_plans(segments, temp_c=22, humidity_pct=55, base_pace=305):
    return [
        segment_target_pace(base_pace, seg.avg_grade, temp_c, humidity_pct)
        for seg in segments
    ]


# --- safety_flags_for_conditions ---

def test_no_safety_flags_in_cool_conditions():
    assert safety_flags_for_conditions(10, 50) == []


def test_caution_flag_above_non_elite_threshold():
    # WBGT(21, 50) sits just above the 20.5C non-elite threshold
    flags = safety_flags_for_conditions(21, 50)
    assert len(flags) == 1
    assert flags[0].level == "caution"
    assert str(WBGT_NON_ELITE_START_THRESHOLD_C) in flags[0].message


def test_warning_flag_above_acsm_hard_limit():
    flags = safety_flags_for_conditions(30, 70)
    assert len(flags) == 1
    assert flags[0].level == "warning"
    assert str(WBGT_ACSM_COMPETITION_LIMIT_C) in flags[0].message


# --- structured_race_plan ---

def test_structured_plan_has_expected_top_level_keys():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)

    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", [])

    assert set(plan.keys()) == {"course", "weather", "fueling", "safety_flags"}
    assert len(plan["course"]["segments"]) == 2
    assert plan["weather"]["temp_c"] == 22
    assert plan["weather"]["source"] == "manual override"


def test_structured_plan_cumulative_time_matches_sum_of_segment_times():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)

    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", [])

    expected_total = sum(s["segment_time_sec"] for s in plan["course"]["segments"])
    assert plan["course"]["predicted_time_sec"] == pytest.approx(expected_total)
    assert plan["course"]["segments"][-1]["cumulative_time_sec"] == pytest.approx(expected_total)


def test_structured_plan_is_json_serializable():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)
    flags = safety_flags_for_conditions(22, 55)

    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", flags)

    # should not raise
    json.dumps(plan)


def test_structured_plan_includes_safety_flags_verbatim():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments, temp_c=30, humidity_pct=70)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=30, humidity_pct=70)
    flags = safety_flags_for_conditions(30, 70)

    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", flags)

    assert len(plan["safety_flags"]) == 1
    assert plan["safety_flags"][0]["level"] == "warning"


# --- build_narrative_prompt ---

def test_prompt_embeds_the_structured_plan_json():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)
    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", [])

    prompt = build_narrative_prompt(plan)

    # the exact target pace for segment 1 (the descent) should be
    # traceable in the prompt -- this is what "grounding" depends on
    assert str(plan["course"]["segments"][1]["target_pace_sec_per_km"]) in prompt or \
        plan["course"]["segments"][1]["target_pace"] in prompt


def test_prompt_instructs_against_inventing_numbers():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)
    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", [])

    prompt = build_narrative_prompt(plan)
    assert "do not invent" in prompt.lower()


def test_prompt_instructs_to_open_with_safety_flags_when_present():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)
    plan = structured_race_plan(segments, pace_plans, fueling, "manual override", [])

    prompt = build_narrative_prompt(plan)
    assert "safety_flags" in prompt


# --- generate_race_narrative (injected call_llm_fn -- no real API call) ---

def test_generate_race_narrative_returns_canned_response():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)

    def canned_llm(prompt: str) -> str:
        return "This is a canned coaching narrative."

    result = generate_race_narrative(segments, pace_plans, fueling, "manual override", call_llm_fn=canned_llm)

    assert isinstance(result, RaceNarrative)
    assert result.narrative_text == "This is a canned coaching narrative."


def test_generate_race_narrative_never_touches_the_network():
    # If this test ever calls the real Anthropic API instead of the
    # injected fn, it should fail loudly (missing package/key) rather
    # than silently succeed -- proving call_llm_fn is actually used.
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)

    seen_prompts = []

    def spy_llm(prompt: str) -> str:
        seen_prompts.append(prompt)
        return "narrative"

    generate_race_narrative(segments, pace_plans, fueling, "manual override", call_llm_fn=spy_llm)

    assert len(seen_prompts) == 1
    assert "course" in seen_prompts[0]  # the structured plan JSON was embedded


def test_generate_race_narrative_passes_structured_plan_through():
    segments = _fake_segments()
    pace_plans = _fake_pace_plans(segments)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)

    result = generate_race_narrative(
        segments, pace_plans, fueling, "manual override", call_llm_fn=lambda p: "x"
    )

    assert result.structured_plan["weather"]["source"] == "manual override"
    assert len(result.structured_plan["course"]["segments"]) == 2


def test_generate_race_narrative_computes_safety_flags_from_conditions():
    segments = _fake_segments()
    hot_pace_plans = _fake_pace_plans(segments, temp_c=30, humidity_pct=70)
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=30, humidity_pct=70)

    result = generate_race_narrative(
        segments, hot_pace_plans, fueling, "manual override", call_llm_fn=lambda p: "x"
    )

    assert len(result.structured_plan["safety_flags"]) == 1
    assert result.structured_plan["safety_flags"][0]["level"] == "warning"
