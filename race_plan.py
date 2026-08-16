#!/usr/bin/env python3
"""
race_plan.py — MVP CLI. Given a GPX course + a goal pace + weather
(fetched live or supplied manually), prints a segment-by-segment pacing
plan and a fueling summary.

The pacing/fueling numbers are always fully deterministic, no LLM
involved. Pass --narrative to additionally turn that plan into a
coaching narrative via the reasoning/ layer -- this is the one thing
in the whole project that costs money (a real Anthropic API call), so
it's opt-in, off by default.

Usage examples:

  # Manual weather override (works anywhere, no internet needed):
  python race_plan.py --gpx data/sample_race.gpx --goal-pace 5:05 \\
      --temp 18 --humidity 55

  # Live weather fetch (needs internet + real race lat/lon/date):
  python race_plan.py --gpx data/sample_race.gpx --goal-pace 5:05 \\
      --lat 52.52 --lon 13.405 --date 2026-10-04 --start-hour 9

  # Add a coaching narrative (needs ANTHROPIC_API_KEY, costs a small
  # amount -- everything above this flag is free and deterministic):
  python race_plan.py --gpx data/sample_race.gpx --goal-pace 5:05 \\
      --temp 18 --humidity 55 --narrative
"""

import argparse
import sys

from engine.pacing import segment_target_pace, format_pace, parse_pace
from engine.fueling import race_fueling_plan
from ingest.gpx_course import segment_course_from_gpx
from ingest.weather import fetch_weather, HISTORICAL_AVERAGE_YEARS
from reasoning.narrative import generate_race_narrative

WEATHER_SOURCE_LABELS = {
    "forecast": "live forecast",
    "archive": "historical actuals",
    "historical_estimate": f"ESTIMATE — {HISTORICAL_AVERAGE_YEARS}-year historical average, not a forecast",
}


def get_weather(args):
    if args.temp is not None and args.humidity is not None:
        return args.temp, args.humidity, "manual override"

    if args.lat is not None and args.lon is not None and args.date is not None:
        conditions = fetch_weather(args.lat, args.lon, args.date, start_hour=args.start_hour)
        return conditions.temp_c, conditions.humidity_pct, WEATHER_SOURCE_LABELS[conditions.source]

    print(
        "Need weather info: either --temp and --humidity (manual), "
        "or --lat, --lon, and --date (live fetch, needs internet).",
        file=sys.stderr,
    )
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Generate a race-day pacing and fueling plan.")
    parser.add_argument("--gpx", required=True, help="Path to the course GPX file")
    parser.add_argument("--goal-pace", required=True, help="Goal flat/cool pace, e.g. '5:05'")
    parser.add_argument("--segment-length", type=float, default=1.0, help="Segment length in km (default 1.0)")

    parser.add_argument("--temp", type=float, help="Manual temperature override (Celsius)")
    parser.add_argument("--humidity", type=float, help="Manual humidity override (%%)")

    parser.add_argument("--lat", type=float, help="Race latitude (for live weather fetch)")
    parser.add_argument("--lon", type=float, help="Race longitude (for live weather fetch)")
    parser.add_argument("--date", help="Race date, YYYY-MM-DD (for live weather fetch)")
    parser.add_argument("--start-hour", type=int, default=8, help="Race start hour, local time (default 8)")

    parser.add_argument(
        "--narrative", action="store_true",
        help="Also generate a coaching narrative via the reasoning layer. "
             "Needs ANTHROPIC_API_KEY and the anthropic package -- costs a small amount. Off by default.",
    )

    args = parser.parse_args()

    base_pace_sec = parse_pace(args.goal_pace)
    temp_c, humidity_pct, weather_label = get_weather(args)

    segments = segment_course_from_gpx(args.gpx, segment_length_km=args.segment_length)

    print(f"Course: {args.gpx}  ({len(segments)} segments @ {args.segment_length}km)")
    print(f"Goal pace: {args.goal_pace}/km   Conditions: {temp_c:.0f}C, {humidity_pct:.0f}% humidity  [{weather_label}]")
    print()
    print(f"{'Seg':>4} {'Dist':>6} {'Grade':>7}   Target pace   Segment time")
    print("-" * 55)

    total_time_sec = 0.0
    total_distance_km = 0.0
    pace_plans = []

    for seg in segments:
        plan = segment_target_pace(base_pace_sec, seg.avg_grade, temp_c, humidity_pct)
        pace_plans.append(plan)
        seg_time_sec = plan.target_pace_sec_per_km * seg.distance_km
        total_time_sec += seg_time_sec
        total_distance_km += seg.distance_km

        seg_min = int(seg_time_sec // 60)
        seg_sec = int(seg_time_sec % 60)

        print(
            f"{seg.index:>4} {seg.distance_km:>5.2f}k {seg.avg_grade:>6.1%}   "
            f"{format_pace(plan.target_pace_sec_per_km):>11}   {seg_min}:{seg_sec:02d}"
        )

    total_hr = total_time_sec / 3600
    total_h = int(total_time_sec // 3600)
    total_m = int((total_time_sec % 3600) // 60)
    total_s = int(total_time_sec % 60)

    print("-" * 55)
    print(f"Total distance: {total_distance_km:.2f}km   Predicted time: {total_h}:{total_m:02d}:{total_s:02d}")

    fp = race_fueling_plan(duration_hr=total_hr, temp_c=temp_c, humidity_pct=humidity_pct)
    print()
    print("Fueling plan:")
    print(f"  Carbs:  {fp.carbs_g_per_hr:.0f} g/hr          -> {fp.total_carbs_g:.0f} g total")
    print(
        f"  Fluid:  {fp.fluid_ml_per_hr_low:.0f}-{fp.fluid_ml_per_hr_high:.0f} ml/hr    "
        f"-> {fp.total_fluid_ml_low:.0f}-{fp.total_fluid_ml_high:.0f} ml total"
    )
    print(
        f"  Sodium: {fp.sodium_mg_per_hr_low:.0f}-{fp.sodium_mg_per_hr_high:.0f} mg/hr   "
        f"-> {fp.total_sodium_mg_low:.0f}-{fp.total_sodium_mg_high:.0f} mg total"
    )
    print()
    print("  Fluid/sodium are ranges, not targets -- real sweat rate and sweat")
    print("  sodium loss vary far more between individuals than weather alone")
    print("  predicts. Drink to thirst, don't force intake to hit a number --")
    print("  overdrinking beyond your losses is a real risk (exercise-")
    print("  associated hyponatremia). A sweat test or a pre/post long-run")
    print("  weigh-in is the only way to calibrate your own real numbers.")

    if args.narrative:
        print()
        print("Generating coaching narrative (real API call)...")
        try:
            result = generate_race_narrative(segments, pace_plans, fp, weather_label)
        except ImportError:
            print(
                "  Skipped: the `anthropic` package isn't installed. "
                "Run `pip install anthropic` and set ANTHROPIC_API_KEY to use --narrative.",
                file=sys.stderr,
            )
        else:
            print()
            print(result.narrative_text)


if __name__ == "__main__":
    main()
