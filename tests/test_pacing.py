import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.pacing import (
    grade_adjustment_factor,
    minetti_energy_cost,
    heat_derate_factor,
    simplified_wbgt,
    segment_target_pace,
    format_pace,
    parse_pace,
    MINETTI_GRADE_CLAMP,
)


# --- grade_adjustment_factor ---
#
# Expected ratios below are the Minetti et al. 2002 polynomial evaluated
# directly (155.4i^5 - 30.4i^4 - 43.3i^3 + 46.3i^2 + 19.5i + 3.6),
# normalized against flat ground (i=0). See engine/pacing.py for the
# citation and the shape of the curve.

def test_flat_grade_is_neutral():
    assert grade_adjustment_factor(0.0) == 1.0


def test_uphill_slows_pace():
    factor = grade_adjustment_factor(0.05)  # 5% uphill
    assert factor == pytest_approx(1.30144, rel=1e-4)
    assert factor > 1.0


def test_uphill_ten_percent_matches_published_ratio():
    # Minetti's own anchor point: 10% grade costs ~66% more than flat,
    # not the ~33% a naive linear model would predict.
    factor = grade_adjustment_factor(0.10)
    assert factor == pytest_approx(1.65784, rel=1e-4)


def test_gentle_downhill_speeds_pace():
    factor = grade_adjustment_factor(-0.05)  # 5% downhill
    assert factor == pytest_approx(0.76276, rel=1e-4)
    assert factor < 1.0


def test_downhill_benefit_continues_past_ten_percent():
    # Real physiology: -20% grade is still *cheaper* than -10% (the
    # theoretical minimum-cost point is around -18%). The old
    # piecewise-linear model incorrectly started reversing the benefit
    # at -10% -- this is the regression test for that bug.
    at_ten = grade_adjustment_factor(-0.10)
    at_twenty = grade_adjustment_factor(-0.20)
    assert at_twenty < at_ten


def test_downhill_minimum_cost_is_near_eighteen_percent():
    at_minimum = grade_adjustment_factor(-0.18)
    assert at_minimum == pytest_approx(0.49482, rel=1e-3)
    # neighbors should both be (slightly) worse -- confirms it's near
    # the actual minimum of the curve, not just "some low value"
    assert grade_adjustment_factor(-0.10) > at_minimum
    assert grade_adjustment_factor(-0.30) > at_minimum


def test_steep_downhill_never_flips_worse_than_flat_within_typical_race_grades():
    # This is the sign-flip bug regression test: -20%, -25%, -30% all
    # remain *easier* than flat ground under every source checked (the
    # old model predicted -20% was already harder than flat).
    for grade in (-0.20, -0.25, -0.30, -0.35):
        assert grade_adjustment_factor(grade) < 1.0


def test_extreme_downhill_beyond_forty_percent_exceeds_flat():
    # Braking/eccentric-load cost overtakes the downhill benefit
    # somewhere around -40% grade, per Minetti's measured data.
    assert grade_adjustment_factor(-0.45) > 1.0


def test_grade_is_clamped_to_validated_range():
    beyond_clamp = grade_adjustment_factor(-0.60)
    at_clamp = grade_adjustment_factor(-MINETTI_GRADE_CLAMP)
    assert beyond_clamp == at_clamp

    beyond_clamp_up = grade_adjustment_factor(0.60)
    at_clamp_up = grade_adjustment_factor(MINETTI_GRADE_CLAMP)
    assert beyond_clamp_up == at_clamp_up


def test_steeper_uphill_is_worse_than_gentler_uphill():
    gentle = grade_adjustment_factor(0.02)
    steep = grade_adjustment_factor(0.08)
    assert steep > gentle


def test_minetti_energy_cost_matches_flat_ground_baseline():
    # EC(0) is just the polynomial's constant term.
    assert minetti_energy_cost(0.0) == pytest_approx(3.6, rel=1e-6)


# --- heat_derate_factor ---
#
# Indexed by simplified WBGT (ACSM formula: 0.567*Ta + 0.393*e + 3.94),
# not raw dry-bulb temperature -- see engine/pacing.py for the Ely et
# al. 2007 / El Helou et al. 2012 citations. There's no true "no-effect"
# temperature the way the old onset-threshold model assumed: even mild
# conditions carry a small progressive penalty above the ~5C WBGT
# baseline (Ely's coolest studied band).

def test_freezing_and_dry_is_effectively_neutral():
    # WBGT itself has a floor even at 0C (dominated by the constant
    # term), but it should land right at the baseline -- negligible effect.
    factor = heat_derate_factor(0, 50)
    assert factor == pytest_approx(1.0005, rel=1e-2)


def test_mild_conditions_still_carry_a_small_penalty():
    # Old model treated 10C/50% as perfectly neutral; real WBGT-indexed
    # research shows a small but real penalty even here.
    factor = heat_derate_factor(10, 50)
    assert 1.0 < factor < 1.05


def test_demo_conditions_match_expected_wbgt_slowdown():
    # The project's own demo/README conditions (18C, 55% RH).
    factor = heat_derate_factor(18, 55)
    assert factor == pytest_approx(1.0490, rel=1e-3)


def test_heat_slows_pace():
    factor = heat_derate_factor(25, 50)
    assert factor > 1.0


def test_humidity_compounds_heat_effect():
    dry = heat_derate_factor(25, 40)
    humid = heat_derate_factor(25, 90)
    assert humid > dry


def test_hotter_is_worse_than_cooler_at_same_humidity():
    warm = heat_derate_factor(20, 60)
    hot = heat_derate_factor(30, 60)
    assert hot > warm


def test_simplified_wbgt_matches_acsm_formula_at_known_point():
    # 18C / 55% RH -> WBGT ~18.6C, computed directly from the ACSM formula.
    assert simplified_wbgt(18, 55) == pytest_approx(18.597, rel=1e-3)


# --- segment_target_pace (integration) ---

def test_flat_cold_dry_segment_equals_base_pace():
    # Cold/dry enough that WBGT sits below the baseline (clamped to 0
    # excess), so heat_factor is exactly 1.0 -- a genuinely neutral point.
    plan = segment_target_pace(base_pace_sec_per_km=300, grade=0.0, temp_c=0, humidity_pct=20)
    assert plan.target_pace_sec_per_km == pytest_approx(300)


def test_hot_uphill_segment_is_slower_than_base():
    plan = segment_target_pace(base_pace_sec_per_km=300, grade=0.06, temp_c=28, humidity_pct=80)
    assert plan.target_pace_sec_per_km > 300
    assert plan.grade_factor > 1.0
    assert plan.heat_factor > 1.0


def test_cool_gentle_downhill_segment_is_faster_than_base():
    plan = segment_target_pace(base_pace_sec_per_km=300, grade=-0.04, temp_c=10, humidity_pct=40)
    assert plan.target_pace_sec_per_km < 300


# --- format_pace ---

def test_format_pace_basic():
    assert format_pace(305) == "5:05/km"


def test_format_pace_rounds_seconds_correctly():
    assert format_pace(299.6) == "5:00/km"


def test_format_pace_pads_single_digit_seconds():
    assert format_pace(301) == "5:01/km"


def test_parse_pace_basic():
    assert parse_pace("5:05") == 305


def test_parse_pace_round_trips_with_format_pace():
    for pace_str in ["4:30", "5:05", "6:12"]:
        assert format_pace(parse_pace(pace_str)) == f"{pace_str}/km"


# --- tiny helper so this file has no external pytest.approx import churn ---

def pytest_approx(value, rel=1e-6):
    import pytest as _pytest
    return _pytest.approx(value, rel=rel)


import pytest  # noqa: E402  (kept at bottom to keep the top import block clean)
