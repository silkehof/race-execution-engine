"""
Deterministic pacing engine.

This is intentionally NOT an LLM call. Grade-adjusted pacing and heat
de-rating are well-understood physiological effects — they belong in
plain, testable Python. The LLM's job (in reasoning.py, later) is to sit
on top of this and turn the numbers into a strategy and a narrative, not
to reinvent the math.

Core idea: hold *effort* roughly constant across a course by adjusting
target pace per segment for grade and heat, instead of naively holding
one flat goal pace and blowing up on the first hill.
"""

import math
from dataclasses import dataclass


# --- Grade adjustment -------------------------------------------------
#
# grade is a decimal: 0.05 = 5% uphill, -0.03 = 3% downhill.
#
# Uses the metabolic-cost-of-running-vs-grade curve from:
#   Minetti AE, Moia C, Roi GS, Susta D, Ferretti G. "Energy cost of
#   walking and running at extreme uphill and downhill slopes."
#   J Appl Physiol 93(3):1039-46, 2002.
# (This is also the physiological basis Strava's original Grade
# Adjusted Pace was built on.) Fit from treadmill VO2 data across
# -45% to +45% grade in 10 trained runners: uphill cost rises
# steeply and convexly with grade; downhill cost drops to a minimum
# around -18% grade (running at -18% costs about half what flat
# running costs) then rises again as braking/eccentric-load costs
# take over, crossing back above flat-ground cost around -40%.
#
# Note: Minetti's curve is the *theoretical minimum metabolic cost* --
# the pace at which effort per km is held exactly constant. In practice
# this is too aggressive to be an actionable per-km target: on a real
# course (e.g. a +4.2%/-3.4% rolling profile) it swings pace by upwards
# of 2 minutes/km around goal pace, which no one can or should actually
# chase km-by-km -- cardiovascular effort has inertia, and hammering
# the theoretical-minimum-cost pace on a short descent is exactly the
# "banking time you'll lose to fatigue/heat later" mistake this project
# is supposed to help avoid, not encourage. This is the same practical
# gap Strava found in their own real-world, heart-rate-calibrated GAP
# model: real runners don't extract the full theoretical downhill
# benefit on steep descents (control, footing, injury risk) or fully
# commit to the theoretical uphill slowdown either.
#
# grade_adjustment_factor() therefore *damps* the raw Minetti ratio
# toward flat pace by default (GRADE_DAMPING_RATIO) rather than
# applying it in full -- pass damping_ratio=1.0 to get the pure,
# undamped Minetti curve back (exposed via race_plan.py
# --raw-grade-model). Unlike the Minetti curve itself, the damping
# ratio isn't from a citation -- there's no published "how much do real
# racers under-adjust vs. the theoretical optimum" number to fit to.
# 0.5 is a documented, tunable starting heuristic: half the theoretical
# swing is still clearly hill-aware pacing, but stays within a range a
# runner can actually execute. Applied symmetrically to uphill and
# downhill for now, though Strava's own finding was downhill-specific --
# worth revisiting if this needs more precision later.
#
# Neither curve captures eccentric muscle-damage accumulation from a
# long descent early in a race (legs trashed by mile 20) — that's a
# fatigue effect, not an instantaneous metabolic cost, and belongs in
# the reasoning/coaching layer, not here.

MINETTI_GRADE_CLAMP = 0.45  # curve is only validated across -45% to +45% grade
GRADE_DAMPING_RATIO = 0.5   # default: half the theoretical Minetti swing -- see note above


def minetti_energy_cost(grade: float) -> float:
    """Metabolic cost of running at this grade, in J/kg/m (Minetti et al. 2002)."""
    i = grade
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


def grade_adjustment_factor(grade: float, damping_ratio: float = GRADE_DAMPING_RATIO) -> float:
    """
    Returns a multiplier to apply to flat-ground pace for this grade.
    1.0 = no change, >1.0 = slower, <1.0 = faster.

    damping_ratio blends the raw Minetti-derived ratio toward 1.0 (flat
    pace): 1.0 = the full, undamped theoretical-effort-equivalent curve;
    0.5 (default) = half that swing, a more practically executable
    target; 0.0 = no grade adjustment at all.
    """
    clamped_grade = max(-MINETTI_GRADE_CLAMP, min(MINETTI_GRADE_CLAMP, grade))
    raw_ratio = minetti_energy_cost(clamped_grade) / minetti_energy_cost(0.0)
    return 1 + damping_ratio * (raw_ratio - 1)


# --- Heat de-rate -------------------------------------------------------
#
# Indexed by WBGT (wet-bulb globe temperature), not raw dry-bulb temp,
# per the actual marathon-heat research:
#   Ely MR, Cheuvront SN, Roberts WO, Montain SJ. "Impact of weather on
#   marathon-running performance." Med Sci Sports Exerc 39(3):487-93,
#   2007. (7 major marathons, 6-36 years of race data each.)
#   El Helou N, et al. "Impact of Environmental Parameters on Marathon
#   Running Performance." PLOS ONE 7(5):e37407, 2012. (~1.8M finisher
#   performances, independent confirmation of the WBGT relationship.)
#
# Full WBGT needs wind speed and solar radiation, neither of which this
# project ingests. Uses ACSM's simplified WBGT instead (air temp +
# humidity only — Lemke & Kjellstrom, "Calculating Workplace WBGT from
# Meteorological Data").
#
# Ely's data shows a *progressive* slowdown starting from the coolest
# studied band (~5°C WBGT) — there's no real "no-effect zone" the way a
# simple onset-threshold model assumes. It also shows slowdown scales
# with how long a runner is exposed: back-of-pack finishers were
# roughly 3-4x more heat-sensitive than elites (~3.2%/5°C WBGT vs.
# ~0.9%/5°C). This implementation uses a single mid-pack/recreational
# slope (~100th-place finisher, ~1.8%/5°C — matches this project's own
# demo persona, a ~1:47 half marathoner) rather than tiering by
# expected pace. Tiering would need the runner's *goal* pace threaded
# in as a proxy for effort level (predicted finish time isn't known yet
# at this point in the pipeline — total time depends on this factor, so
# using it directly here would be circular).

WBGT_BASELINE_C = 5.0            # Ely's coolest studied WBGT band — the
                                   # lowest point with real data, not a
                                   # true zero-effect threshold
HEAT_K_PER_DEGREE_WBGT = 0.0036  # ~1.8% slower per 5°C WBGT (100th-place / recreational slope)


def simplified_wbgt(temp_c: float, humidity_pct: float) -> float:
    """
    ACSM's simplified WBGT estimate from air temp + relative humidity
    alone. Full WBGT also factors in wind speed and solar radiation.
    """
    vapor_pressure_hpa = (humidity_pct / 100.0) * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    return 0.567 * temp_c + 0.393 * vapor_pressure_hpa + 3.94


def heat_derate_factor(
    temp_c: float,
    humidity_pct: float,
    baseline_wbgt_c: float = WBGT_BASELINE_C,
    k_per_degree_wbgt: float = HEAT_K_PER_DEGREE_WBGT,
) -> float:
    """
    Returns a multiplier >= 1.0 to apply on top of the grade-adjusted
    pace, based on WBGT above a baseline (not raw temperature).
    """
    wbgt = simplified_wbgt(temp_c, humidity_pct)
    wbgt_excess = max(0.0, wbgt - baseline_wbgt_c)
    return 1 + k_per_degree_wbgt * wbgt_excess


# --- Combined segment target pace ---------------------------------------

@dataclass
class SegmentPacePlan:
    base_pace_sec_per_km: float
    grade: float
    temp_c: float
    humidity_pct: float
    grade_factor: float
    heat_factor: float
    target_pace_sec_per_km: float


def segment_target_pace(
    base_pace_sec_per_km: float,
    grade: float,
    temp_c: float,
    humidity_pct: float,
    grade_damping_ratio: float = GRADE_DAMPING_RATIO,
) -> SegmentPacePlan:
    """
    Combines grade adjustment and heat de-rate into a single target pace
    (seconds per km) for one course segment. grade_damping_ratio=1.0
    uses the raw, undamped Minetti curve -- see grade_adjustment_factor().
    """
    grade_factor = grade_adjustment_factor(grade, damping_ratio=grade_damping_ratio)
    heat_factor = heat_derate_factor(temp_c, humidity_pct)
    target = base_pace_sec_per_km * grade_factor * heat_factor

    return SegmentPacePlan(
        base_pace_sec_per_km=base_pace_sec_per_km,
        grade=grade,
        temp_c=temp_c,
        humidity_pct=humidity_pct,
        grade_factor=grade_factor,
        heat_factor=heat_factor,
        target_pace_sec_per_km=target,
    )


def format_pace(sec_per_km: float) -> str:
    """e.g. 305.4 -> '5:05/km'"""
    minutes = int(sec_per_km // 60)
    seconds = round(sec_per_km % 60)
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}/km"


def parse_pace(pace_str: str) -> float:
    """'5:05' -> 305.0 (seconds per km). Inverse of format_pace (minus the '/km')."""
    minutes_str, seconds_str = pace_str.strip().replace("/km", "").split(":")
    return int(minutes_str) * 60 + int(seconds_str)
