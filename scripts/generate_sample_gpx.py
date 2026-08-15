"""
Generates a small synthetic GPX course for local testing when you don't
have a real race GPX handy yet. Produces a rolling ~8km out-and-back-ish
route with a mix of flat, climbing, and descending sections so the
pacing/fueling output is actually interesting to look at.

Swap data/sample_race.gpx for your real race's GPX export whenever you
have one (Strava, race organizer sites, and Garmin Connect all let you
export course GPX files).
"""

import gpxpy
import gpxpy.gpx

# Rough path near Berlin (arbitrary — just needs real-ish lat/lon so
# distance math behaves). (lat_offset, lon_offset, elevation_m) per point,
# roughly 100m apart.
START_LAT, START_LON = 52.5200, 13.4050

# (delta_lat, delta_lon, elevation_m) — hand-authored to create a
# believable profile: flat start, a climb, rolling middle, a descent,
# flat finish.
PROFILE = []

import math

def build_profile():
    points = []
    lat, lon = START_LAT, START_LON
    elevation = 34.0  # Berlin-ish baseline

    # ~80 points spaced ~100m apart along a gently curving path = ~8km
    for i in range(80):
        # gentle curve so it's not a dead-straight line
        lat += 0.0009 + 0.00005 * math.sin(i / 8.0)
        lon += 0.0002 * math.cos(i / 6.0)

        # elevation profile: flat(0-15), climb(15-30), rolling(30-50),
        # descent(50-65), flat(65-80)
        if i < 15:
            elevation += 0.0
        elif i < 30:
            elevation += 2.2  # steady climb
        elif i < 50:
            elevation += 1.0 * math.sin(i / 3.0)  # rolling
        elif i < 65:
            elevation -= 3.0  # descent (partly steep)
        else:
            elevation += 0.0

        points.append((lat, lon, round(elevation, 1)))

    return points


def main():
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack(name="Sample 8K Rolling Course")
    gpx.tracks.append(track)
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    for lat, lon, ele in build_profile():
        segment.points.append(gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon, elevation=ele))

    output_path = "data/sample_race.gpx"
    with open(output_path, "w") as f:
        f.write(gpx.to_xml())

    print(f"Wrote {output_path} ({len(segment.points)} points)")


if __name__ == "__main__":
    main()
