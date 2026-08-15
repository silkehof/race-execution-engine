"""
Weather ingestion via Open-Meteo (free, no API key required).

The actual HTTP fetch is injected (`fetch_fn`) rather than hardcoded, so
this module is unit-testable with canned responses — no real network
call needed in tests, and no flaky CI dependent on an external API.

Open-Meteo's forecast API only covers ~2 weeks out. For race dates
further out than that, there's no live forecast to fetch yet, so we
fall back to a multi-year historical average for the same calendar
date (month/day) at that location — a reasonable planning estimate
that automatically gets replaced by a live forecast once the race date
moves inside the forecast window (same call, no changes needed by the
caller). `WeatherConditions.source` tells you which one you got.

NOTE: the default fetch function calls api.open-meteo.com and needs
outbound internet access. Run this from your own machine (or wherever
you deploy it) rather than a network-restricted sandbox.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional

import requests

FORECAST_WINDOW_DAYS = 14  # Open-Meteo's forecast API only reliably covers ~2 weeks out
HISTORICAL_AVERAGE_YEARS = 5  # how many past years to average for the estimate fallback


@dataclass
class WeatherConditions:
    temp_c: float
    humidity_pct: float
    source: str  # "forecast" | "archive" | "historical_estimate"


def _default_fetch(lat: float, lon: float, date_iso: str) -> dict:
    """
    Hits Open-Meteo's forecast API (future/recent dates) or archive API
    (historical dates, for backtesting the eval harness against past
    races, or for averaging past years to build an estimate) depending
    on whether date_iso is in the future or past.
    """
    target_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
    is_future = target_date >= date.today()

    base_url = (
        "https://api.open-meteo.com/v1/forecast"
        if is_future
        else "https://archive-api.open-meteo.com/v1/archive"
    )

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date_iso,
        "end_date": date_iso,
        "hourly": "temperature_2m,relative_humidity_2m",
        "timezone": "auto",
    }

    response = requests.get(base_url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _hour_values(data: dict, date_iso: str, start_hour: int):
    """Pulls (temp_c, humidity_pct) for the given hour out of an Open-Meteo-shaped response."""
    hourly = data["hourly"]
    times = hourly["time"]  # e.g. "2026-10-04T08:00"

    target_prefix = f"{date_iso}T{start_hour:02d}:00"
    try:
        idx = times.index(target_prefix)
    except ValueError:
        # Fall back to the closest available hour if the exact string
        # doesn't match (some APIs zero-pad differently).
        idx = min(range(len(times)), key=lambda i: abs(i - start_hour))

    return hourly["temperature_2m"][idx], hourly["relative_humidity_2m"][idx]


def _same_calendar_date_years_ago(target_date: date, years_ago: int) -> date:
    """target_date minus N years, same month/day (Feb 29 falls back to Feb 28)."""
    try:
        return target_date.replace(year=target_date.year - years_ago)
    except ValueError:
        return target_date.replace(year=target_date.year - years_ago, day=28)


def fetch_weather(
    lat: float,
    lon: float,
    date_iso: str,
    start_hour: int = 8,
    fetch_fn: Optional[Callable[[float, float, str], dict]] = None,
) -> WeatherConditions:
    """
    Returns temp + humidity for a race at the given location, date, and
    start hour (0-23, local time to the course).

    - Within the ~2-week forecast window: live forecast (source="forecast").
    - A past date: real historical actuals for that date (source="archive").
    - A future date beyond the forecast window: average of the same
      calendar date over the past `HISTORICAL_AVERAGE_YEARS` years
      (source="historical_estimate") — a planning estimate, not a
      forecast. Re-run the same call once the race date is within the
      forecast window and it'll switch to a live forecast automatically.
    """
    fetch_fn = fetch_fn or _default_fetch
    target_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
    days_out = (target_date - date.today()).days

    if days_out > FORECAST_WINDOW_DAYS:
        temps = []
        humidities = []
        for years_ago in range(1, HISTORICAL_AVERAGE_YEARS + 1):
            past_date = _same_calendar_date_years_ago(target_date, years_ago)
            past_iso = past_date.isoformat()
            data = fetch_fn(lat, lon, past_iso)
            temp_c, humidity_pct = _hour_values(data, past_iso, start_hour)
            temps.append(temp_c)
            humidities.append(humidity_pct)

        return WeatherConditions(
            temp_c=sum(temps) / len(temps),
            humidity_pct=sum(humidities) / len(humidities),
            source="historical_estimate",
        )

    data = fetch_fn(lat, lon, date_iso)
    temp_c, humidity_pct = _hour_values(data, date_iso, start_hour)
    source = "forecast" if days_out >= 0 else "archive"
    return WeatherConditions(temp_c=temp_c, humidity_pct=humidity_pct, source=source)
