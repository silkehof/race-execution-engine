"""
Quick sanity check — not a real course yet, just a handful of made-up
segments to see the engine produce a believable plan end to end.
Swap this for real GPX-derived segments once ingest/ exists.
"""

from engine.pacing import segment_target_pace, format_pace
from engine.fueling import race_fueling_plan

# (segment label, grade, temp_c, humidity_pct)
sample_segments = [
    ("km 1 - flat start",        0.00, 16, 55),
    ("km 2 - gentle climb",      0.03, 16, 55),
    ("km 3 - steady climb",      0.06, 17, 55),
    ("km 4 - rolling",          -0.01, 17, 55),
    ("km 5 - gentle downhill",  -0.05, 18, 55),
    ("km 6 - steep descent",    -0.15, 18, 55),
    ("km 7 - flat, warming up",  0.00, 22, 65),
    ("km 8 - hot uphill grind",  0.07, 24, 70),
]

BASE_GOAL_PACE_SEC_PER_KM = 305  # 5:05/km goal pace, flat & cool

print(f"{'Segment':<26} {'Grade':>7} {'Temp':>6} {'Hum':>5}   Target pace")
print("-" * 65)

for label, grade, temp_c, humidity in sample_segments:
    plan = segment_target_pace(BASE_GOAL_PACE_SEC_PER_KM, grade, temp_c, humidity)
    print(
        f"{label:<26} {grade:>6.0%} {temp_c:>5.0f}C {humidity:>4.0f}%   "
        f"{format_pace(plan.target_pace_sec_per_km)}"
    )

print()
print("Fueling plan — half marathon @ 5:05/km goal pace (~1:47), 18C / 55% humidity")
print("-" * 65)
fp = race_fueling_plan(duration_hr=1.78, temp_c=18, humidity_pct=55)
print(f"  Carbs:  {fp.carbs_g_per_hr:.0f} g/hr          -> {fp.total_carbs_g:.0f} g total")
print(f"  Fluid:  {fp.fluid_ml_per_hr_low:.0f}-{fp.fluid_ml_per_hr_high:.0f} ml/hr    -> {fp.total_fluid_ml_low:.0f}-{fp.total_fluid_ml_high:.0f} ml total")
print(f"  Sodium: {fp.sodium_mg_per_hr_low:.0f}-{fp.sodium_mg_per_hr_high:.0f} mg/hr   -> {fp.total_sodium_mg_low:.0f}-{fp.total_sodium_mg_high:.0f} mg total")
