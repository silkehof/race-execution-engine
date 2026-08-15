import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.weather import fetch_weather, WeatherConditions, FORECAST_WINDOW_DAYS, HISTORICAL_AVERAGE_YEARS


def _fake_fetch(lat, lon, date_iso):
    """Canned Open-Meteo-shaped response, standing in for the real API call."""
    return {
        "hourly": {
            "time": [
                f"{date_iso}T06:00",
                f"{date_iso}T07:00",
                f"{date_iso}T08:00",
                f"{date_iso}T09:00",
                f"{date_iso}T10:00",
            ],
            "temperature_2m": [14.0, 15.5, 17.0, 19.5, 22.0],
            "relative_humidity_2m": [80, 75, 68, 60, 52],
        }
    }


def _fake_fetch_by_year(lat, lon, date_iso):
    """Canned response whose temp/humidity vary by year, to exercise averaging."""
    year = int(date_iso[:4])
    base_temp = 10.0 + (year % 10)
    base_humidity = 50 + (year % 10)
    return {
        "hourly": {
            "time": [f"{date_iso}T08:00"],
            "temperature_2m": [base_temp],
            "relative_humidity_2m": [base_humidity],
        }
    }


# --- within the forecast window ---

def test_fetch_weather_picks_correct_hour():
    near_future = (date.today() + timedelta(days=5)).isoformat()
    conditions = fetch_weather(lat=52.5, lon=13.4, date_iso=near_future, start_hour=8, fetch_fn=_fake_fetch)
    assert isinstance(conditions, WeatherConditions)
    assert conditions.temp_c == 17.0
    assert conditions.humidity_pct == 68
    assert conditions.source == "forecast"


def test_fetch_weather_different_start_hour():
    near_future = (date.today() + timedelta(days=5)).isoformat()
    conditions = fetch_weather(lat=52.5, lon=13.4, date_iso=near_future, start_hour=6, fetch_fn=_fake_fetch)
    assert conditions.temp_c == 14.0
    assert conditions.humidity_pct == 80


def test_fetch_weather_passes_through_lat_lon_date_to_fetch_fn():
    seen = {}
    near_future = (date.today() + timedelta(days=3)).isoformat()

    def spy_fetch(lat, lon, date_iso):
        seen["lat"] = lat
        seen["lon"] = lon
        seen["date_iso"] = date_iso
        return _fake_fetch(lat, lon, date_iso)

    fetch_weather(lat=48.1, lon=11.6, date_iso=near_future, start_hour=9, fetch_fn=spy_fetch)
    assert seen == {"lat": 48.1, "lon": 11.6, "date_iso": near_future}


def test_fetch_weather_at_forecast_window_boundary_is_still_forecast():
    boundary = (date.today() + timedelta(days=FORECAST_WINDOW_DAYS)).isoformat()
    conditions = fetch_weather(lat=52.5, lon=13.4, date_iso=boundary, start_hour=8, fetch_fn=_fake_fetch)
    assert conditions.source == "forecast"


# --- a past date: real historical actuals ---

def test_fetch_weather_past_date_uses_archive_source():
    past = (date.today() - timedelta(days=10)).isoformat()
    conditions = fetch_weather(lat=52.5, lon=13.4, date_iso=past, start_hour=8, fetch_fn=_fake_fetch)
    assert conditions.source == "archive"
    assert conditions.temp_c == 17.0


# --- beyond the forecast window: historical average estimate ---

def test_fetch_weather_beyond_window_falls_back_to_historical_estimate():
    far_future = (date.today() + timedelta(days=FORECAST_WINDOW_DAYS + 1)).isoformat()
    conditions = fetch_weather(lat=52.5, lon=13.4, date_iso=far_future, start_hour=8, fetch_fn=_fake_fetch)
    assert conditions.source == "historical_estimate"
    # canned fetch returns the same values regardless of year, so the average
    # should equal that single value
    assert conditions.temp_c == 17.0
    assert conditions.humidity_pct == 68


def test_fetch_weather_historical_estimate_averages_across_years():
    far_future = date.today() + timedelta(days=FORECAST_WINDOW_DAYS + 30)
    target_month_day = (far_future.month, far_future.day)

    conditions = fetch_weather(
        lat=52.5, lon=13.4, date_iso=far_future.isoformat(), start_hour=8, fetch_fn=_fake_fetch_by_year
    )

    expected_years = [far_future.year - n for n in range(1, HISTORICAL_AVERAGE_YEARS + 1)]
    expected_temp = sum(10.0 + (y % 10) for y in expected_years) / HISTORICAL_AVERAGE_YEARS
    expected_humidity = sum(50 + (y % 10) for y in expected_years) / HISTORICAL_AVERAGE_YEARS

    assert conditions.source == "historical_estimate"
    assert conditions.temp_c == expected_temp
    assert conditions.humidity_pct == expected_humidity
    # sanity: the fallback still targets the same calendar day, just past years
    assert (far_future.month, far_future.day) == target_month_day


def test_fetch_weather_historical_estimate_queries_n_past_years():
    seen_dates = []
    far_future = (date.today() + timedelta(days=FORECAST_WINDOW_DAYS + 60)).isoformat()

    def spy_fetch(lat, lon, date_iso):
        seen_dates.append(date_iso)
        return _fake_fetch(lat, lon, date_iso)

    fetch_weather(lat=52.5, lon=13.4, date_iso=far_future, start_hour=8, fetch_fn=spy_fetch)
    assert len(seen_dates) == HISTORICAL_AVERAGE_YEARS
    assert len(set(seen_dates)) == HISTORICAL_AVERAGE_YEARS  # all distinct years
    for d in seen_dates:
        assert date.fromisoformat(d) < date.today()


def test_fetch_weather_historical_estimate_handles_leap_day():
    # Find the next Feb 29 out beyond the forecast window so at least one
    # of the past 5 years it maps to is a non-leap year (needs Feb 28 fallback).
    year = date.today().year
    while True:
        try:
            candidate = date(year, 2, 29)
        except ValueError:
            year += 1
            continue
        if (candidate - date.today()).days > FORECAST_WINDOW_DAYS:
            break
        year += 1

    conditions = fetch_weather(
        lat=52.5, lon=13.4, date_iso=candidate.isoformat(), start_hour=8, fetch_fn=_fake_fetch
    )
    assert conditions.source == "historical_estimate"
