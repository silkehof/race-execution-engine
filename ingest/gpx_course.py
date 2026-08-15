"""
GPX course ingestion.

Split deliberately into two layers:

1. segment_course_from_profile() — a pure function over plain distance/
   elevation lists. No GPX, no geo library. Exactly testable with hand-
   built synthetic data.
2. segment_course_from_gpx() — a thin wrapper that parses a real .gpx
   file and hands the resulting profile to (1). This is the part that
   depends on gpxpy and real-world course files; it's tested with an
   integration-style "does this look sane" check rather than exact
   numbers, since real GPS traces are noisy.

Keeping the geometry math separate from the file parsing is what makes
this layer testable at all — GPX round-trip tests would otherwise be
fighting floating-point GPS noise instead of checking logic.
"""

import math
from dataclasses import dataclass
from typing import List

import gpxpy


@dataclass
class CourseSegment:
    index: int
    start_km: float
    end_km: float
    distance_km: float
    elevation_gain_m: float
    elevation_loss_m: float
    avg_grade: float  # decimal, e.g. 0.03 = 3% average uphill


# --- Pure profile segmentation (exactly testable) ------------------------

def interpolate_elevation_at_distance(
    cum_dist_km: List[float], elevations: List[float], target_km: float
) -> float:
    """Linearly interpolate elevation at an arbitrary distance along the course."""
    if target_km <= cum_dist_km[0]:
        return elevations[0]
    if target_km >= cum_dist_km[-1]:
        return elevations[-1]

    for j in range(1, len(cum_dist_km)):
        if cum_dist_km[j] >= target_km:
            d0, d1 = cum_dist_km[j - 1], cum_dist_km[j]
            e0, e1 = elevations[j - 1], elevations[j]
            if d1 == d0:
                return e1
            frac = (target_km - d0) / (d1 - d0)
            return e0 + frac * (e1 - e0)

    return elevations[-1]


def segment_course_from_profile(
    cum_dist_km: List[float],
    elevations: List[float],
    segment_length_km: float = 1.0,
) -> List[CourseSegment]:
    """
    Bucket a (cumulative distance, elevation) profile into fixed-length
    segments (last segment may be shorter — the course rarely divides
    evenly). Elevation at each segment boundary is interpolated, so this
    doesn't depend on a course point landing exactly on a km mark.
    """
    if len(cum_dist_km) != len(elevations):
        raise ValueError("cum_dist_km and elevations must be the same length")
    if len(cum_dist_km) < 2:
        raise ValueError("Need at least 2 points to segment a course")

    total_km = cum_dist_km[-1]
    num_segments = math.ceil(total_km / segment_length_km)
    segments = []

    for i in range(num_segments):
        seg_start = i * segment_length_km
        seg_end = min((i + 1) * segment_length_km, total_km)
        distance_km = seg_end - seg_start
        if distance_km <= 0:
            continue

        e_start = interpolate_elevation_at_distance(cum_dist_km, elevations, seg_start)
        e_end = interpolate_elevation_at_distance(cum_dist_km, elevations, seg_end)
        elevation_change = e_end - e_start

        gain = max(0.0, elevation_change)
        loss = max(0.0, -elevation_change)
        avg_grade = elevation_change / (distance_km * 1000)

        segments.append(
            CourseSegment(
                index=i,
                start_km=seg_start,
                end_km=seg_end,
                distance_km=distance_km,
                elevation_gain_m=gain,
                elevation_loss_m=loss,
                avg_grade=avg_grade,
            )
        )

    return segments


# --- GPX file wrapper (real-world, integration-tested) -------------------

def load_track_points(gpx_path: str):
    with open(gpx_path, "r") as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            points.extend(segment.points)

    if len(points) < 2:
        raise ValueError(f"{gpx_path} has fewer than 2 track points — can't build a course from it")

    return points


def cumulative_distance_km(points) -> List[float]:
    """Cumulative 3D distance (accounts for elevation change) along the track, in km."""
    cum_km = [0.0]
    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        d_m = gpxpy.geo.distance(
            prev.latitude, prev.longitude, prev.elevation,
            curr.latitude, curr.longitude, curr.elevation,
            haversine=False,  # use the more accurate ellipsoidal distance, elevation-aware
        )
        cum_km.append(cum_km[-1] + d_m / 1000.0)
    return cum_km


def segment_course_from_gpx(gpx_path: str, segment_length_km: float = 1.0) -> List[CourseSegment]:
    points = load_track_points(gpx_path)
    cum_km = cumulative_distance_km(points)
    elevations = [p.elevation or 0.0 for p in points]
    return segment_course_from_profile(cum_km, elevations, segment_length_km)
