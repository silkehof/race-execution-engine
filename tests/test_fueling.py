import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from engine.fueling import (
    carb_target_g_per_hr,
    fluid_target_ml_per_hr,
    sodium_target_mg_per_hr,
    race_fueling_plan,
)


# --- carb_target_g_per_hr ---

def test_short_effort_needs_no_carbs():
    assert carb_target_g_per_hr(0.5) == 0.0


def test_carb_ramps_in_moderate_tier():
    low = carb_target_g_per_hr(1.0)
    mid = carb_target_g_per_hr(1.75)
    high = carb_target_g_per_hr(2.5)
    assert low == pytest.approx(30)
    assert mid == pytest.approx(45)
    assert high == pytest.approx(60)
    assert low < mid < high


def test_carb_ramps_in_long_tier():
    at_2_5 = carb_target_g_per_hr(2.5)
    at_4 = carb_target_g_per_hr(4.0)
    assert at_2_5 == pytest.approx(60)
    assert at_4 == pytest.approx(90)


def test_carb_caps_beyond_four_hours():
    at_4 = carb_target_g_per_hr(4.0)
    at_6 = carb_target_g_per_hr(6.0)
    assert at_4 == at_6 == pytest.approx(90)


def test_half_marathon_duration_lands_in_moderate_tier():
    # ~1h47 goal time -> should land comfortably in the 30-60g/hr tier
    carbs = carb_target_g_per_hr(1.78)
    assert 30 <= carbs <= 60


# --- fluid_target_ml_per_hr ---

def test_cool_temp_uses_baseline_fluid():
    assert fluid_target_ml_per_hr(10, 50) == 500
    assert fluid_target_ml_per_hr(15, 90) == 500  # at onset, still baseline


def test_heat_increases_fluid_need():
    assert fluid_target_ml_per_hr(25, 50) > 500


def test_humidity_compounds_fluid_need():
    dry = fluid_target_ml_per_hr(25, 40)
    humid = fluid_target_ml_per_hr(25, 90)
    assert humid > dry


# --- sodium_target_mg_per_hr ---

def test_cool_temp_uses_baseline_sodium():
    assert sodium_target_mg_per_hr(10, 50) == 400


def test_heat_increases_sodium_need():
    assert sodium_target_mg_per_hr(28, 70) > 400


# --- race_fueling_plan (integration) ---

def test_plan_totals_scale_with_duration():
    plan = race_fueling_plan(duration_hr=1.78, temp_c=18, humidity_pct=55)
    assert plan.total_carbs_g == pytest.approx(plan.carbs_g_per_hr * 1.78)
    assert plan.total_fluid_ml == pytest.approx(plan.fluid_ml_per_hr * 1.78)
    assert plan.total_sodium_mg == pytest.approx(plan.sodium_mg_per_hr * 1.78)


def test_hot_race_plan_has_higher_fluid_than_cool_race():
    cool_plan = race_fueling_plan(duration_hr=1.78, temp_c=12, humidity_pct=50)
    hot_plan = race_fueling_plan(duration_hr=1.78, temp_c=27, humidity_pct=75)
    assert hot_plan.fluid_ml_per_hr > cool_plan.fluid_ml_per_hr
    assert hot_plan.sodium_mg_per_hr > cool_plan.sodium_mg_per_hr
