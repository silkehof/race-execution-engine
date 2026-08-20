import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.gpx_course import CourseSegment
from engine.pacing import segment_target_pace
from engine.fueling import race_fueling_plan
from reasoning.narrative import structured_race_plan, RaceNarrative
from eval.grounding import check_narrative_grounding, evaluate_race_narrative


def _fake_plan():
    segments = [
        CourseSegment(index=0, start_km=0.0, end_km=1.0, distance_km=1.0,
                      elevation_gain_m=0.0, elevation_loss_m=0.0, avg_grade=0.0),
        CourseSegment(index=1, start_km=1.0, end_km=2.0, distance_km=1.0,
                      elevation_gain_m=42.0, elevation_loss_m=0.0, avg_grade=0.042),
    ]
    pace_plans = [
        segment_target_pace(305, seg.avg_grade, 22, 55) for seg in segments
    ]
    fueling = race_fueling_plan(duration_hr=1.0, temp_c=22, humidity_pct=55)
    return structured_race_plan(segments, pace_plans, fueling, "manual override", [])


# --- clean narrative: no violations ---

def test_clean_narrative_with_no_numeric_claims_is_grounded():
    plan = _fake_plan()
    report = check_narrative_grounding("This course has a tough climb early on. Pace yourself.", plan)
    assert report.is_grounded
    assert report.violations == []


def test_narrative_citing_the_real_target_pace_is_grounded():
    plan = _fake_plan()
    real_pace = plan["course"]["segments"][1]["target_pace"]
    narrative = f"On segment 1, aim for roughly {real_pace} given the climb."
    report = check_narrative_grounding(narrative, plan)
    assert report.is_grounded
    assert real_pace.replace("/km", "") in report.checked_pace_mentions


def test_narrative_citing_the_real_predicted_time_is_grounded():
    plan = _fake_plan()
    from eval.grounding import _format_hms
    real_time = _format_hms(plan["course"]["predicted_time_sec"])
    narrative = f"You're on track to finish in about {real_time}."
    report = check_narrative_grounding(narrative, plan)
    assert report.is_grounded


def test_narrative_citing_fueling_numbers_within_range_is_grounded():
    plan = _fake_plan()
    carbs = plan["fueling"]["carbs_g_per_hr"]
    narrative = f"Aim for about {carbs:.0f} g/hr of carbs."
    report = check_narrative_grounding(narrative, plan)
    assert report.is_grounded


def test_narrative_citing_real_grade_is_grounded():
    plan = _fake_plan()
    narrative = "That segment climbs at 4.2%, so ease off a little."
    report = check_narrative_grounding(narrative, plan)
    assert report.is_grounded


# --- fabricated numbers: violations caught ---

def test_fabricated_pace_is_flagged():
    plan = _fake_plan()
    narrative = "Push hard and hold 3:10/km on that stretch."
    report = check_narrative_grounding(narrative, plan)
    assert not report.is_grounded
    assert any(v.kind == "pace" and "3:10" in v.mentioned for v in report.violations)


def test_fabricated_total_time_is_flagged():
    plan = _fake_plan()
    narrative = "You should finish comfortably under 0:59:59."
    report = check_narrative_grounding(narrative, plan)
    assert not report.is_grounded
    assert any(v.kind == "total_time" for v in report.violations)


def test_fueling_number_outside_range_is_flagged():
    plan = _fake_plan()
    # way beyond any plausible carb target for a 1hr effort
    narrative = "Take in 500 g/hr of carbs to be safe."
    report = check_narrative_grounding(narrative, plan)
    assert not report.is_grounded
    assert any(v.kind == "fueling" for v in report.violations)


def test_fabricated_grade_is_flagged():
    plan = _fake_plan()
    narrative = "Watch out, that hill hits 12.0% at the steepest point."
    report = check_narrative_grounding(narrative, plan)
    assert not report.is_grounded
    assert any(v.kind == "grade" for v in report.violations)


def test_multiple_violations_are_all_reported():
    plan = _fake_plan()
    narrative = "Hold 3:10/km, you'll finish in 0:10:00, and the grade is 99.0%."
    report = check_narrative_grounding(narrative, plan)
    kinds = {v.kind for v in report.violations}
    assert kinds == {"pace", "total_time", "grade"}


# --- evaluate_race_narrative convenience wrapper ---

def test_evaluate_race_narrative_wraps_check_narrative_grounding():
    plan = _fake_plan()
    result = RaceNarrative(structured_plan=plan, narrative_text="Hold 3:10/km throughout.")
    report = evaluate_race_narrative(result)
    assert not report.is_grounded
    assert report.violations[0].kind == "pace"
