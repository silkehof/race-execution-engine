"""
Deterministic fueling engine.

Same philosophy as pacing.py: carbohydrate, fluid, and sodium targets
during endurance exercise follow well-established sports-nutrition
guidance — they belong in plain, testable Python, not an LLM call. The
reasoning layer later turns these numbers into a *schedule* ("gel at
km 6, 8, 10...") and explains tradeoffs; it doesn't invent the
underlying rates.

Fluid and sodium are reported as low-high ranges, not single numbers.
Unlike carb burn rate (fairly consistent across individuals for a given
duration), sweat rate and sweat sodium concentration vary enormously
between people — a point estimate implies a precision that isn't
there, and worse, that's the exact failure mode the sports-medicine
literature has been actively correcting: prescriptive fixed fluid
targets are a documented cause of exercise-associated hyponatremia
(EAH) from overdrinking beyond actual losses. See range_band.py-style
citations inline below.
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


# --- Fluid target (center estimate) ----------------------------------------
#
# Baseline ~500ml/hr in cool conditions is a common starting estimate;
# sweat rate climbs with heat and humidity, same shape as the pacing
# engine's heat de-rate. ACSM's position stand on exercise and fluid
# replacement (Sawka MN, et al. Med Sci Sports Exerc 39(2):377-90,
# 2007) reports marathon sweat rates ranging from ~0.4 to >2 L/hr
# depending on the individual and their pace — this formula's output
# is a condition-adjusted center estimate within that real range, not
# a personal measurement. See fluid_target_ml_per_hr_range() below for
# the range this center anchors.

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


# --- Sodium target (center estimate) ------------------------------------
#
# Sodium losses scale with sweat rate, so this rides the same heat curve
# as fluid, off a moderate baseline. Real sweat sodium concentration
# varies enormously between individuals (~10-90 mmol/L, i.e. roughly
# 230-2070 mg/L — Baker LB, "Sweating Rate and Sweat Sodium
# Concentration in Athletes," Sports Med 47(Suppl 1):111-128, 2017),
# which combined with sweat-rate variance produces reported per-hour
# losses anywhere from ~600 to 6000+ mg/hr in "salty sweaters" (Baker
# LB, et al. J Appl Physiol, 2023). This formula's output is a
# condition-adjusted center estimate for a *typical* sweater, not a
# personal measurement — no formula substitutes for an actual sweat
# test if you're a known heavy/salty sweater.

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


# --- Fluid/sodium ranges --------------------------------------------------
#
# Individual variability in both fluid and sodium loss is too large for
# a single number to be honest (see citations above) — so both are
# reported as a low-high band around the condition-adjusted center
# estimate, not a point target.
#
# The +-33% band width isn't the full clinical extreme (that would be
# ~0.4-2+ L/hr for fluid, ~600-6000+ mg/hr for sodium — far too wide to
# be practically actionable for a single race plan). It's derived from
# ACSM's own commonly-cited *generic* sodium replacement guidance
# (300-600 mg/hr during exercise >2hr, i.e. +-33% around a 450 mg/hr
# midpoint), applied uniformly to both fluid and sodium as a practical
# "typical variation" band around this model's estimate. Real
# individual variation can still exceed this band, especially for
# heavy/salty sweaters — a sweat test or a pre/post-run weigh-in is the
# only way to get a real personal number, which no formula replaces.

RANGE_BAND_RATIO = 1.0 / 3.0  # +-33%, see derivation above


def _as_range(center: float, band_ratio: float = RANGE_BAND_RATIO):
    return center * (1 - band_ratio), center * (1 + band_ratio)


def fluid_target_ml_per_hr_range(temp_c: float, humidity_pct: float):
    """Returns (low, high) ml/hr -- see module docstring for the band derivation."""
    return _as_range(fluid_target_ml_per_hr(temp_c, humidity_pct))


def sodium_target_mg_per_hr_range(temp_c: float, humidity_pct: float):
    """Returns (low, high) mg/hr -- see module docstring for the band derivation."""
    return _as_range(sodium_target_mg_per_hr(temp_c, humidity_pct))


# --- Combined plan -------------------------------------------------------

@dataclass
class FuelingPlan:
    duration_hr: float
    temp_c: float
    humidity_pct: float
    carbs_g_per_hr: float
    fluid_ml_per_hr_low: float
    fluid_ml_per_hr_high: float
    sodium_mg_per_hr_low: float
    sodium_mg_per_hr_high: float
    total_carbs_g: float
    total_fluid_ml_low: float
    total_fluid_ml_high: float
    total_sodium_mg_low: float
    total_sodium_mg_high: float


def race_fueling_plan(duration_hr: float, temp_c: float, humidity_pct: float) -> FuelingPlan:
    carbs = carb_target_g_per_hr(duration_hr)
    fluid_low, fluid_high = fluid_target_ml_per_hr_range(temp_c, humidity_pct)
    sodium_low, sodium_high = sodium_target_mg_per_hr_range(temp_c, humidity_pct)

    return FuelingPlan(
        duration_hr=duration_hr,
        temp_c=temp_c,
        humidity_pct=humidity_pct,
        carbs_g_per_hr=carbs,
        fluid_ml_per_hr_low=fluid_low,
        fluid_ml_per_hr_high=fluid_high,
        sodium_mg_per_hr_low=sodium_low,
        sodium_mg_per_hr_high=sodium_high,
        total_carbs_g=carbs * duration_hr,
        total_fluid_ml_low=fluid_low * duration_hr,
        total_fluid_ml_high=fluid_high * duration_hr,
        total_sodium_mg_low=sodium_low * duration_hr,
        total_sodium_mg_high=sodium_high * duration_hr,
    )
