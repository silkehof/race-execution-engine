"""
Deterministic fueling engine.

Same philosophy as pacing.py: carbohydrate and fluid targets during
endurance exercise follow well-established sports-nutrition guidance —
they belong in plain, testable Python, not an LLM call. The reasoning
layer later turns these numbers into a *schedule* ("gel at km 6, 8, 10...")
and explains tradeoffs; it doesn't invent the underlying rates.
"""

from dataclasses import dataclass


# --- Carbohydrate target --------------------------------------------------
#
# Widely-used endurance nutrition tiers by event duration:
#   < 1hr        : minimal benefit, no real carb need
#   1hr - 2.5hr  : ramps from ~30 to ~60 g/hr
#   > 2.5hr      : ramps from ~60 up to ~90 g/hr (needs multiple carb
#                  sources — e.g. glucose + fructose — to absorb that much)
#
# These are population-level heuristics, not a personal prescription —
# tune the anchor values against what actually works for your own gut
# once you have real long-run data.

def carb_target_g_per_hr(duration_hr: float) -> float:
    if duration_hr < 1.0:
        return 0.0

    if duration_hr <= 2.5:
        t = (duration_hr - 1.0) / (2.5 - 1.0)
        return 30 + t * (60 - 30)

    t = min((duration_hr - 2.5) / (4.0 - 2.5), 1.0)
    return 60 + t * (90 - 60)


# --- Fluid target ----------------------------------------------------------
#
# Baseline ~500ml/hr in cool conditions is a common starting estimate;
# sweat rate climbs with heat and humidity, same shape as the pacing
# engine's heat de-rate. This is a *starting point* — real sweat rate is
# highly individual and best calibrated by weighing yourself pre/post a
# long run.

FLUID_BASELINE_ML_PER_HR = 500
FLUID_HEAT_ONSET_C = 15.0
FLUID_ML_PER_DEGREE = 15.0
FLUID_HUMIDITY_BASELINE_PCT = 50


def fluid_target_ml_per_hr(
    temp_c: float,
    humidity_pct: float,
    baseline_ml_per_hr: float = FLUID_BASELINE_ML_PER_HR,
) -> float:
    if temp_c <= FLUID_HEAT_ONSET_C:
        return baseline_ml_per_hr

    temp_excess = temp_c - FLUID_HEAT_ONSET_C
    humidity_excess = max(0.0, humidity_pct - FLUID_HUMIDITY_BASELINE_PCT)
    humidity_multiplier = 1 + humidity_excess / 100.0

    extra = temp_excess * FLUID_ML_PER_DEGREE * humidity_multiplier
    return baseline_ml_per_hr + extra


# --- Sodium target -----------------------------------------------------
#
# Sodium losses scale with sweat rate, so this rides the same heat curve
# as fluid, off a moderate baseline. Individual sweat sodium concentration
# varies a lot (salty sweaters need more) — this is a reasonable default,
# not a personalized measurement.

SODIUM_BASELINE_MG_PER_HR = 400
SODIUM_MG_PER_DEGREE = 12.0


def sodium_target_mg_per_hr(
    temp_c: float,
    humidity_pct: float,
    baseline_mg_per_hr: float = SODIUM_BASELINE_MG_PER_HR,
) -> float:
    if temp_c <= FLUID_HEAT_ONSET_C:
        return baseline_mg_per_hr

    temp_excess = temp_c - FLUID_HEAT_ONSET_C
    humidity_excess = max(0.0, humidity_pct - FLUID_HUMIDITY_BASELINE_PCT)
    humidity_multiplier = 1 + humidity_excess / 100.0

    extra = temp_excess * SODIUM_MG_PER_DEGREE * humidity_multiplier
    return baseline_mg_per_hr + extra


# --- Combined plan -------------------------------------------------------

@dataclass
class FuelingPlan:
    duration_hr: float
    temp_c: float
    humidity_pct: float
    carbs_g_per_hr: float
    fluid_ml_per_hr: float
    sodium_mg_per_hr: float
    total_carbs_g: float
    total_fluid_ml: float
    total_sodium_mg: float


def race_fueling_plan(duration_hr: float, temp_c: float, humidity_pct: float) -> FuelingPlan:
    carbs = carb_target_g_per_hr(duration_hr)
    fluid = fluid_target_ml_per_hr(temp_c, humidity_pct)
    sodium = sodium_target_mg_per_hr(temp_c, humidity_pct)

    return FuelingPlan(
        duration_hr=duration_hr,
        temp_c=temp_c,
        humidity_pct=humidity_pct,
        carbs_g_per_hr=carbs,
        fluid_ml_per_hr=fluid,
        sodium_mg_per_hr=sodium,
        total_carbs_g=carbs * duration_hr,
        total_fluid_ml=fluid * duration_hr,
        total_sodium_mg=sodium * duration_hr,
    )
