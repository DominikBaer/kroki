#!/usr/bin/env python3
"""
GPX to Swiss Coordinates Kroki Converter

This script converts GPX files to a route profile (Kroki) with Swiss LV95 coordinates.
For each point, it calculates:
- Point number
- Swiss coordinates (E, N)
- Horizontal distance from previous point
- Elevation
- Elevation difference from previous point
- Azimuth from previous point

If elevation data is missing from the GPX file, it can automatically fetch it from
the swisstopo Height API.
"""

import xml.etree.ElementTree as ET
import math
import sys
import urllib.request
import urllib.parse
import json
import time
from typing import List, Tuple, Optional


def fetch_elevation_swisstopo(e: float, n: float) -> Optional[float]:
    """
    Fetch elevation data from swisstopo Height API for given LV95 coordinates.
    
    Args:
        e: Easting coordinate (LV95)
        n: Northing coordinate (LV95)
    
    Returns:
        Elevation in meters above sea level, or None if request fails
    """
    try:
        # swisstopo Height API endpoint
        url = f"https://api3.geo.admin.ch/rest/services/height?easting={e}&northing={n}&sr=2056"
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if 'height' in data:
                return float(data['height'])
    except Exception as ex:
        print(f"Warning: Could not fetch elevation for E={e:.2f}, N={n:.2f}: {ex}", file=sys.stderr)
    
    return None


def wgs84_to_lv95(lat: float, lon: float) -> Tuple[float, float]:
    """
    Convert WGS84 coordinates (lat/lon) to Swiss LV95 coordinates (E/N).
    
    Uses the approximate formulas from swisstopo for coordinate transformation.
    Reference: https://www.swisstopo.admin.ch/en/knowledge-facts/surveying-geodesy/reference-systems/map-projections.html
    
    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
    
    Returns:
        Tuple of (E, N) in Swiss LV95 coordinates (meters)
    """
    # Convert to auxiliary values (unit: 10000")
    lat_aux = (lat * 3600 - 169028.66) / 10000
    lon_aux = (lon * 3600 - 26782.5) / 10000
    
    # Calculate Swiss coordinates (LV95)
    E = (2600072.37 + 
         211455.93 * lon_aux - 
         10938.51 * lon_aux * lat_aux - 
         0.36 * lon_aux * lat_aux**2 - 
         44.54 * lon_aux**3)
    
    N = (1200147.07 + 
         308807.95 * lat_aux + 
         3745.25 * lon_aux**2 + 
         76.63 * lat_aux**2 - 
         194.56 * lon_aux**2 * lat_aux + 
         119.79 * lat_aux**3)
    
    return E, N


def calculate_distance(e1: float, n1: float, e2: float, n2: float) -> float:
    """
    Calculate horizontal distance between two points in meters.
    
    Args:
        e1, n1: First point coordinates (E, N)
        e2, n2: Second point coordinates (E, N)
    
    Returns:
        Distance in meters
    """
    return math.sqrt((e2 - e1)**2 + (n2 - n1)**2)


def calculate_azimuth(e1: float, n1: float, e2: float, n2: float) -> float:
    """
    Calculate azimuth (bearing) from point 1 to point 2 in degrees.
    
    Azimuth is measured clockwise from North (0°).
    
    Args:
        e1, n1: First point coordinates (E, N)
        e2, n2: Second point coordinates (E, N)
    
    Returns:
        Azimuth in degrees (0-360)
    """
    delta_e = e2 - e1
    delta_n = n2 - n1
    
    # Calculate angle in radians, then convert to degrees
    azimuth_rad = math.atan2(delta_e, delta_n)
    azimuth_deg = math.degrees(azimuth_rad)
    
    # Normalize to 0-360 range
    if azimuth_deg < 0:
        azimuth_deg += 360
    
    return azimuth_deg


def parse_gpx(gpx_file: str) -> List[Tuple[float, float, Optional[float]]]:
    """
    Parse GPX file and extract track/route points with coordinates and elevation.
    
    Args:
        gpx_file: Path to GPX file
    
    Returns:
        List of tuples (latitude, longitude, elevation)
    """
    tree = ET.parse(gpx_file)
    root = tree.getroot()
    
    # Handle XML namespace
    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}
    
    points = []
    
    # Try to find track points (trkpt)
    for trkpt in root.findall('.//gpx:trkpt', ns):
        lat_str = trkpt.get('lat')
        lon_str = trkpt.get('lon')
        if lat_str is None or lon_str is None:
            continue
        lat = float(lat_str)
        lon = float(lon_str)
        ele_elem = trkpt.find('gpx:ele', ns)
        ele = float(ele_elem.text) if ele_elem is not None and ele_elem.text else None
        points.append((lat, lon, ele))
    
    # If no track points, try route points (rtept)
    if not points:
        for rtept in root.findall('.//gpx:rtept', ns):
            lat_str = rtept.get('lat')
            lon_str = rtept.get('lon')
            if lat_str is None or lon_str is None:
                continue
            lat = float(lat_str)
            lon = float(lon_str)
            ele_elem = rtept.find('gpx:ele', ns)
            ele = float(ele_elem.text) if ele_elem is not None and ele_elem.text else None
            points.append((lat, lon, ele))
    
    # If still no points, try waypoints (wpt)
    if not points:
        for wpt in root.findall('.//gpx:wpt', ns):
            lat_str = wpt.get('lat')
            lon_str = wpt.get('lon')
            if lat_str is None or lon_str is None:
                continue
            lat = float(lat_str)
            lon = float(lon_str)
            ele_elem = wpt.find('gpx:ele', ns)
            ele = float(ele_elem.text) if ele_elem is not None and ele_elem.text else None
            points.append((lat, lon, ele))
    
    return points


def generate_kroki(gpx_file: str, output_file: Optional[str] = None, fetch_elevation: bool = True):
    """
    Generate Kroki (route profile) from GPX file with Swiss coordinates.
    
    Args:
        gpx_file: Path to input GPX file
        output_file: Optional path to output file (if None, prints to stdout)
        fetch_elevation: If True, fetch missing elevation data from swisstopo API
    """
    # Parse GPX file
    points = parse_gpx(gpx_file)
    
    if not points:
        print("Error: No points found in GPX file", file=sys.stderr)
        return
    
    # Convert to Swiss coordinates and fetch elevation if needed
    swiss_points = []
    missing_elevation = any(ele is None for _, _, ele in points)
    
    if missing_elevation and fetch_elevation:
        print("Fetching elevation data from swisstopo API...", file=sys.stderr)
    
    for i, (lat, lon, ele) in enumerate(points):
        e, n = wgs84_to_lv95(lat, lon)
        
        # Fetch elevation if missing and requested
        if ele is None and fetch_elevation:
            ele = fetch_elevation_swisstopo(e, n)
            if ele is not None:
                print(f"  Point {i+1}: Elevation fetched: {ele:.2f} m", file=sys.stderr)
            # Add small delay to respect API rate limits
            time.sleep(0.1)
        
        swiss_points.append((e, n, ele))
    
    if missing_elevation and fetch_elevation:
        print("", file=sys.stderr)
    
    # Prepare output
    output_lines = []
    output_lines.append("=" * 100)
    output_lines.append("KROKI - Route Profile with Swiss LV95 Coordinates")
    output_lines.append("=" * 100)
    output_lines.append("")
    output_lines.append(f"{'Punkt':<6} {'E (m)':<12} {'N (m)':<12} {'Dist (m)':<12} {'Hoehe (m)':<12} {'Delta H (m)':<12} {'Azimuth (°)':<12}")
    output_lines.append("-" * 100)
    
    # Process each point
    for i, (e, n, ele) in enumerate(swiss_points, start=1):
        if i == 1:
            # First point - no previous point for comparison
            dist = 0.0
            delta_ele = 0.0
            azimuth = 0.0
            ele_str = f"{ele:.2f}" if ele is not None else "N/A"
            output_lines.append(f"{i:<6} {e:<12.2f} {n:<12.2f} {dist:<12.2f} {ele_str:<12} {delta_ele:<12.2f} {azimuth:<12.2f}")
        else:
            # Calculate values relative to previous point
            prev_e, prev_n, prev_ele = swiss_points[i-2]
            
            dist = calculate_distance(prev_e, prev_n, e, n)
            azimuth = calculate_azimuth(prev_e, prev_n, e, n)
            
            if ele is not None and prev_ele is not None:
                delta_ele = ele - prev_ele
                ele_str = f"{ele:.2f}"
            else:
                delta_ele = 0.0
                ele_str = "N/A"
            
            output_lines.append(f"{i:<6} {e:<12.2f} {n:<12.2f} {dist:<12.2f} {ele_str:<12} {delta_ele:<12.2f} {azimuth:<12.2f}")
    
    output_lines.append("-" * 100)
    
    # Calculate totals
    total_dist = sum(calculate_distance(swiss_points[i-1][0], swiss_points[i-1][1], 
                                       swiss_points[i][0], swiss_points[i][1]) 
                    for i in range(1, len(swiss_points)))
    
    if all(p[2] is not None for p in swiss_points):
        total_ascent = sum(max(0, swiss_points[i][2] - swiss_points[i-1][2]) 
                          for i in range(1, len(swiss_points)))
        total_descent = sum(max(0, swiss_points[i-1][2] - swiss_points[i][2]) 
                           for i in range(1, len(swiss_points)))
        output_lines.append(f"\nTotal Distance: {total_dist:.2f} m")
        output_lines.append(f"Total Ascent: {total_ascent:.2f} m")
        output_lines.append(f"Total Descent: {total_descent:.2f} m")
    else:
        output_lines.append(f"\nTotal Distance: {total_dist:.2f} m")
    
    output_lines.append("")
    
    # Output results
    output_text = "\n".join(output_lines)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"Kroki saved to: {output_file}")
    else:
        print(output_text)


def main():
    """Main entry point for the script."""
    # Set UTF-8 encoding for stdout on Windows
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    if len(sys.argv) < 2:
        print("Usage: python gpx_to_swiss_kroki.py <gpx_file> [output_file] [--no-fetch-elevation]")
        print("\nArguments:")
        print("  gpx_file              Path to GPX file")
        print("  output_file           Optional: Path to output file (default: print to console)")
        print("  --no-fetch-elevation  Optional: Disable automatic elevation fetching from swisstopo API")
        print("\nExamples:")
        print("  python gpx_to_swiss_kroki.py route.gpx")
        print("  python gpx_to_swiss_kroki.py route.gpx output.txt")
        print("  python gpx_to_swiss_kroki.py route.gpx output.txt --no-fetch-elevation")
        sys.exit(1)
    
    gpx_file = sys.argv[1]
    output_file = None
    fetch_elevation = True
    
    # Parse remaining arguments
    for arg in sys.argv[2:]:
        if arg == '--no-fetch-elevation':
            fetch_elevation = False
        elif output_file is None:
            output_file = arg
    
    try:
        generate_kroki(gpx_file, output_file, fetch_elevation)
    except FileNotFoundError:
        print(f"Error: File '{gpx_file}' not found", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

# Made with Bob
