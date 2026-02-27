"""
GPX to Swiss-LV95 "Kroki" converter

Features
--------
* Parses GPX tracks / routes / way-points.
* Converts WGS-84 lat/lon to LV95 (E/N) with pyproj.
* Calculates planar distance & azimuth on LV95 (fast, sufficient for typical routes).
* Optionally fetches missing elevations from the Swisstopo Height API.
* Outputs a nicely formatted route profile ("Kroki") either to stdout or a file.
"""

import argparse
import logging
import requests
import sys

import xml.etree.ElementTree as ET

from pathlib import Path
from pyproj import Transformer, Geod
from typing import List, Tuple, Optional

# --------------------------------------------------------------------------- #
# Logging configuration (stdout, INFO level)
# --------------------------------------------------------------------------- #
logger = logging.getLogger(__name__)
handler = logging.StreamHandler(stream=sys.stdout)
formatter = logging.Formatter("%(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
SWISSTOPO_HEIGHT_API = (
    "https://api3.geo.admin.ch/rest/services/height"
    "?easting={e}&northing={n}&sr=2056"
)

LV95_TRANSFORMER = Transformer.from_crs(
    "EPSG:4326",   # WGS-84
    "EPSG:2056",   # LV95
    always_xy=True,
)

GEOD = Geod(ellps="WGS84")  # Distance/azimuth calculations on geodesic.

# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def fetch_elevation(ele: float | None, e: float, n: float, use_height_api: bool) -> float:
    """
    Resolve the correct elevation.

    If we have a valid elevation, return that. If we don't but we are ok to query the Swisstopo
    height API, we do that. If we can't do either, return 0.0 and log a warning.
    Note, Swisstopo requires LV95 coordinates, so we pass E/N.

    Params:
        ele: The elevation from the GPX file, can be None.
        e: The LV95 E coordinate (for API query if needed).
        n: The LV95 N coordinate (for API query if needed).
        use_height_api: Whether to attempt fetching elevation from the API if ele is None.
    Returns:
        The resolved elevation as a float (0.0 if not available).
    """
    if ele is not None:
        return float(ele)

    if not use_height_api:
        return 0.0

    try:
        resp = requests.get(SWISSTOPO_HEIGHT_API.format(e=e, n=n), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data["height"])
    
    except Exception as exc:
        logger.warning(
            f"Could not fetch elevation for E={e:.2f}, N={n:.2f}: {exc}"
        )
        return 0.0


def parse_gpx(gpx_path: Path) -> List[Tuple[float, float, Optional[float]]]:
    """
    Extract (lat, lon, elevation) triples from a GPX file.
    
    Params:
        gpx_path: Path to the GPX file.
    Returns:
        A list of tuples, each containing (latitude, longitude, elevation).
    """
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    def _extract(elem):
        lat = float(elem.get("lat"))
        lon = float(elem.get("lon"))
        ele_el = elem.find("gpx:ele", ns)
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else None
        return lat, lon, ele

    # Try track points → route points → way-points (first non-empty list wins)
    points = [
        _extract(pt)
        for pt in (
            root.findall(".//gpx:trkpt", ns)
            or root.findall(".//gpx:rtept", ns)
            or root.findall(".//gpx:wpt", ns)
        )
    ]
    return points


def build_profile(
    points: List[Tuple[float, float, Optional[float]]],
    use_height_api: bool = True,
) -> List[dict]:
    """
    Create a list of dicts containing LV95 coords, distance, azimuth, and elevation info for each point.
    Params:
        points: List of (lat, lon, elevation) tuples.
        use_height_api: Whether to attempt fetching elevation from the API if elevation data is missing.
    Returns:
        A list of dicts, each with keys: 'e', 'n', 'ele', 'dist', 'azimuth', 'delta_ele'.
    """
    profile = []
    dist, azim, d_ele = 0.0, 0.0, 0.0

    for idx, (lat, lon, ele) in enumerate(points):
        # Map WGS-84 lat/lon to LV95 E/N
        e, n = LV95_TRANSFORMER.transform(lon, lat)

        # Resolve elevation once – reuse for both current point and delta calc
        resolved_ele = fetch_elevation(ele, e, n, use_height_api)
        
        if idx > 0:
            prev = points[idx - 1]
            azim, _, dist = GEOD.inv(prev[1], prev[0], lon, lat) # Azimuth and distance based on WGS-84 lat/lon
            d_ele = resolved_ele - profile[-1]['ele']  # Elevation change based on resolved elevation

        profile.append(
            {
                "e": e,
                "n": n,
                "ele": resolved_ele,
                "dist": dist,
                "azimuth": azim,
                "delta_ele": d_ele,
            }
        )

    return profile


def format_profile(profile: List[dict]) -> str:
    """
    Render the profile as a human-readable table plus summary stats.

    Params:
        profile: List of dicts with keys: 'e', 'n', 'ele', 'dist', 'azimuth', 'delta_ele'.
    Returns:
        A formatted string representing the route profile.
    """
    header = "=" * 100 + "\nKROKI - Route profile (LV95)\n" + "=" * 100
    col_hdr = (
        f"{'Pt':<4} {'E (m)':>12} {'N (m)':>12} {'Dist (m)':>12} "
        f"{'Elev (m)':>12} {'ΔElev (m)':>12} {'Azim (°)':>12}"
    )
    lines = [header, "", col_hdr, "-" * 100]

    for i, pt in enumerate(profile, start=1):
        elev_str = f"{pt['ele']:.2f}" if pt["ele"] is not None else "N/A"
        lines.append(
            f"{i:<4} {pt['e']:>12.2f} {pt['n']:>12.2f} {pt['dist']:>12.2f} "
            f"{elev_str:>12} {pt['delta_ele']:>12.2f} {pt['azimuth']:>12.2f}"
        )

    lines.append("-" * 100)

    total_dist = sum(p["dist"] for p in profile)
    lines.append(f"\nTotal distance: {total_dist:.2f} m")

    if all(p["ele"] is not None for p in profile):
        ascent = sum(max(0.0, p["delta_ele"]) for p in profile[1:])
        descent = sum(max(0.0, -p["delta_ele"]) for p in profile[1:])
        lines.append(f"Total ascent : {ascent:.2f} m")
        lines.append(f"Total descent: {descent:.2f} m")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI – argparse based entry point
# --------------------------------------------------------------------------- #
def build_arg_parser() -> argparse.ArgumentParser:
    """
    Construct the argument parser for the CLI.

    Returns:
        An argparse.ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="gpx_to_swiss_kroki.py",
        description=(
            "Convert a GPX file to a 'Kroki' (route profile) expressed in Swiss LV95 "
            "(EPSG:2056) coordinates."
        ),
        epilog="If no output file is supplied the report is printed to STDOUT.",
    )
    parser.add_argument(
        "gpx_file",
        type=Path,
        help="Path to the input GPX file.",
    )
    parser.add_argument(
        "output_file",
        nargs="?",
        type=Path,
        default=None,
        help="Optional path for the generated report. If omitted, the report is printed.",
    )
    parser.add_argument(
        "--no-fetch-elev",
        dest="use_height_api",
        action="store_false",
        help="Do **not** query the Swisstopo Height API for missing elevation data.",
    )
    return parser


def main() -> None:
    """
    Main entry point for the script. Parses arguments, processes the GPX file, and outputs the report.

    Raises:
        FileNotFoundError: If the specified GPX file does not exist.
    """
    parser = build_arg_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------- #
    # Core processing
    # ------------------------------------------------------------------- #
    try:
        raw_points = parse_gpx(args.gpx_file)
        if not raw_points:
            raise ValueError("No track/route points found in the GPX file.")

        profile = build_profile(raw_points, use_height_api=args.use_height_api)
        report = format_profile(profile)

        if args.output_file:
            args.output_file.write_text(report, encoding="utf-8")
            logger.info(f"Kroki written to {args.output_file}")
        else:
            print(report)

    except FileNotFoundError:
        logger.error(f"File not found: {args.gpx_file}")
        sys.exit(1)
    except Exception as exc:  # pragma: no cover – unexpected errors
        logger.exception(f"Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    # Ensure UTF-8 output on Windows consoles
    if sys.platform.startswith("win"):
        import os, io

        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", line_buffering=True
        )
        os.system("")  # enables ANSI colours on newer Windows terminals

    main()