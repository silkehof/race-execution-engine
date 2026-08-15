import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ingest.gpx_course import (
    interpolate_elevation_at_distance,
    segment_course_from_profile,
    segment_course_from_gpx,
)

SAMPLE_GPX_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_race.gpx")


# --- interpolate_elevation_at_distance ---

def test_interpolation_at_exact_known_point():
    cum_km = [0.0, 1.0, 2.0]
    elevations = [100.0, 110.0, 105.0]
    assert interpolate_elevation_at_distance(cum_km, elevations, 1.0) == 110.0


def test_interpolation_midway_between_points():
    cum_km = [0.0, 2.0]
    elevations = [100.0, 120.0]
    assert interpolate_elevation_at_distance(cum_km, elevations, 1.0) == pytest.approx(110.0)


def test_interpolation_clamps_before_start():
    cum_km = [0.0, 1.0]
    elevations = [100.0, 110.0]
    assert interpolate_elevation_at_distance(cum_km, elevations, -5.0) == 100.0


def test_interpolation_clamps_after_end():
    cum_km = [0.0, 1.0]
    elevations = [100.0, 110.0]
    assert interpolate_elevation_at_distance(cum_km, elevations, 50.0) == 110.0


# --- segment_course_from_profile ---

def test_flat_course_has_zero_grade():
    cum_km = [0.0, 1.0, 2.0, 3.0]
    elevations = [50.0, 50.0, 50.0, 50.0]
    segments = segment_course_from_profile(cum_km, elevations, segment_length_km=1.0)
    assert len(segments) == 3
    for seg in segments:
        assert seg.avg_grade == pytest.approx(0.0)
        assert seg.distance_km == pytest.approx(1.0)


def test_steady_climb_has_expected_positive_grade():
    # 3km course, climbs 30m per km -> 3% grade throughout
    cum_km = [0.0, 1.0, 2.0, 3.0]
    elevations = [0.0, 30.0, 60.0, 90.0]
    segments = segment_course_from_profile(cum_km, elevations, segment_length_km=1.0)
    for seg in segments:
        assert seg.avg_grade == pytest.approx(0.03)
        assert seg.elevation_gain_m == pytest.approx(30.0)
        assert seg.elevation_loss_m == pytest.approx(0.0)


def test_descent_has_expected_negative_grade():
    cum_km = [0.0, 1.0, 2.0]
    elevations = [100.0, 80.0, 60.0]
    segments = segment_course_from_profile(cum_km, elevations, segment_length_km=1.0)
    for seg in segments:
        assert seg.avg_grade == pytest.approx(-0.02)
        assert seg.elevation_loss_m == pytest.approx(20.0)
        assert seg.elevation_gain_m == pytest.approx(0.0)


def test_last_segment_can_be_shorter_than_segment_length():
    # 2.5km course with 1km segments -> 3 segments, last one 0.5km
    cum_km = [0.0, 1.0, 2.0, 2.5]
    elevations = [0.0, 10.0, 20.0, 25.0]
    segments = segment_course_from_profile(cum_km, elevations, segment_length_km=1.0)
    assert len(segments) == 3
    assert segments[0].distance_km == pytest.approx(1.0)
    assert segments[1].distance_km == pytest.approx(1.0)
    assert segments[2].distance_km == pytest.approx(0.5)


def test_segment_indices_and_boundaries_are_sequential():
    cum_km = [0.0, 1.0, 2.0, 3.0]
    elevations = [0.0, 5.0, 0.0, 5.0]
    segments = segment_course_from_profile(cum_km, elevations, segment_length_km=1.0)
    for i, seg in enumerate(segments):
        assert seg.index == i
        assert seg.start_km == pytest.approx(float(i))
        assert seg.end_km == pytest.approx(float(i + 1))


def test_rejects_mismatched_list_lengths():
    with pytest.raises(ValueError):
        segment_course_from_profile([0.0, 1.0], [100.0], segment_length_km=1.0)


def test_rejects_too_few_points():
    with pytest.raises(ValueError):
        segment_course_from_profile([0.0], [100.0], segment_length_km=1.0)


# --- segment_course_from_gpx (real file, "does this look sane" checks) ---
#
# Unlike the tests above, this exercises the actual gpxpy parsing + 3D
# distance math against data/sample_race.gpx (~8km synthetic rolling
# course, see scripts/generate_sample_gpx.py). We check shape and sign,
# not exact floats — real GPX distance math has enough floating-point/
# GPS-trace noise that pinning exact numbers here would make the test
# brittle to regenerating the sample file, not useful for catching bugs.

def test_segment_course_from_gpx_produces_sane_segment_count_and_distance():
    segments = segment_course_from_gpx(SAMPLE_GPX_PATH, segment_length_km=1.0)

    # ~8km course with 1km segments -> 8 full segments + 1 short leftover
    assert len(segments) == 9

    total_distance_km = sum(seg.distance_km for seg in segments)
    assert 8.0 < total_distance_km < 8.1

    # last segment is the leftover remainder, shorter than a full km
    assert segments[-1].distance_km < 1.0


def test_segment_course_from_gpx_segments_are_sequential():
    segments = segment_course_from_gpx(SAMPLE_GPX_PATH, segment_length_km=1.0)
    for i, seg in enumerate(segments):
        assert seg.index == i
        assert seg.start_km == pytest.approx(float(i))
        assert seg.elevation_gain_m >= 0.0
        assert seg.elevation_loss_m >= 0.0


def test_segment_course_from_gpx_climb_segment_has_positive_grade():
    # scripts/generate_sample_gpx.py climbs steadily from km 1 to km 3
    segments = segment_course_from_gpx(SAMPLE_GPX_PATH, segment_length_km=1.0)
    assert segments[2].avg_grade > 0.015


def test_segment_course_from_gpx_descent_segment_has_negative_grade():
    # scripts/generate_sample_gpx.py descends from km 5 to km 6.5
    segments = segment_course_from_gpx(SAMPLE_GPX_PATH, segment_length_km=1.0)
    assert segments[5].avg_grade < -0.02
