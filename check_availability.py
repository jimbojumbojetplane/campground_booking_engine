#!/usr/bin/env python3
"""
Ontario Parks Campground Availability Checker

Queries the Ontario Parks reservation system API to check site availability
for a given campground and date range.

Usage:
    # Check a specific site by name/number:
    python check_availability.py --park "Killbear" --campground "Lighthouse Point B" --site 1422 \
        --start 2026-07-01 --end 2026-07-05

    # List all parks:
    python check_availability.py --list-parks

    # List campgrounds in a park (use resourceLocationId from --list-parks):
    python check_availability.py --list-campgrounds --park-id -2147483000

    # Show all available sites in a campground for a date range:
    python check_availability.py --park "Killbear" --campground "Lighthouse Point B" \
        --start 2026-07-01 --end 2026-07-05

Requirements:
    pip install requests

Note: The Ontario Parks reservation system (reservations.ontarioparks.ca) does not
publish a public API. These endpoints were discovered via browser network inspection
and may change without notice. This script is for personal use to check availability.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("Error: 'requests' library is required. Install with: pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://reservations.ontarioparks.ca"

API_ENDPOINTS = {
    "root_maps": f"{BASE_URL}/api/resourcelocation/rootmaps",
    "sub_maps": f"{BASE_URL}/api/resourcelocation/resources",
    "resource_location": f"{BASE_URL}/api/resourceLocation",
    "attributes": f"{BASE_URL}/api/attribute/filterable",
    "map_data": f"{BASE_URL}/api/availability/map",
    "resource_status": f"{BASE_URL}/api/availability/resourcestatus",
    "resource_details": f"{BASE_URL}/api/resource/details",
    "daily_availability": f"{BASE_URL}/api/availability/resourcedailyavailability",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Referer": f"{BASE_URL}/",
    "Origin": BASE_URL,
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update(HEADERS)


def api_get(url, params=None):
    """Make a GET request to the Ontario Parks API."""
    resp = session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(url, payload):
    """Make a POST request to the Ontario Parks API."""
    resp = session.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Discovery: parks, campgrounds, sites
# ---------------------------------------------------------------------------

def list_parks():
    """Fetch the top-level list of parks (resource locations / root maps)."""
    data = api_get(API_ENDPOINTS["root_maps"])
    parks = []
    for item in data:
        name = item.get("localizedValues", [{}])[0].get("name", "Unknown")
        park_id = item.get("resourceLocationId") or item.get("mapId")
        parks.append({"name": name, "id": park_id, "raw": item})
    parks.sort(key=lambda p: p["name"])
    return parks


def list_campgrounds(park_resource_location_id):
    """Fetch the campgrounds (sub-maps) within a park."""
    params = {"resourceLocationId": park_resource_location_id}
    data = api_get(API_ENDPOINTS["sub_maps"], params=params)
    campgrounds = []
    if isinstance(data, dict):
        for key, val in data.items():
            if val is None:
                continue
            name = val.get("localizedValues", [{}])[0].get("name", key)
            campgrounds.append({"name": name, "id": key, "raw": val})
    elif isinstance(data, list):
        for item in data:
            name = item.get("localizedValues", [{}])[0].get("name", "Unknown")
            cg_id = item.get("resourceLocationId") or item.get("mapId")
            campgrounds.append({"name": name, "id": cg_id, "raw": item})
    campgrounds.sort(key=lambda c: c["name"])
    return campgrounds


def get_sites_for_location(resource_location_id):
    """Fetch all sites (resources) in a campground / resource location."""
    params = {"resourceLocationId": resource_location_id}
    data = api_get(API_ENDPOINTS["sub_maps"], params=params)
    sites = []
    if isinstance(data, dict):
        for key, val in data.items():
            if val is None:
                continue
            name = val.get("localizedValues", [{}])[0].get("name", key)
            sites.append({"name": name, "longId": key, "raw": val})
    elif isinstance(data, list):
        for item in data:
            name = item.get("localizedValues", [{}])[0].get("name", "Unknown")
            site_id = item.get("resourceLocationId") or item.get("mapId") or item.get("id")
            sites.append({"name": name, "longId": site_id, "raw": item})
    return sites


# ---------------------------------------------------------------------------
# Availability checking
# ---------------------------------------------------------------------------

def check_site_availability(resource_id, start_date, end_date):
    """
    Check whether a single site is available for the given date range.

    Returns a dict with:
        available (bool): True if site is fully available for the range
        availability_type (int): 0 = available, other = unavailable
        raw: full API response
    """
    params = {
        "resourceId": resource_id,
        "startDate": start_date,
        "endDate": end_date,
    }
    data = api_get(API_ENDPOINTS["resource_status"], params=params)
    avail_type = data.get("availabilityType", -1)
    return {
        "available": avail_type == 0,
        "availability_type": avail_type,
        "raw": data,
    }


def check_daily_availability(resource_id, start_date, end_date):
    """
    Get day-by-day availability for a site over a date range.

    Returns a list of dicts with date and availability status per day.
    """
    params = {
        "resourceId": resource_id,
        "startDate": start_date,
        "endDate": end_date,
    }
    data = api_get(API_ENDPOINTS["daily_availability"], params=params)
    return data


def find_available_sites(resource_location_id, start_date, end_date):
    """
    Check all sites in a campground and return available ones.

    This calls the resource status endpoint for each site, so it can be slow
    for large campgrounds. A progress indicator is printed to stderr.
    """
    sites = get_sites_for_location(resource_location_id)
    available = []
    total = len(sites)
    for i, site in enumerate(sites, 1):
        print(f"\r  Checking site {i}/{total}: {site['name']}...", end="", file=sys.stderr)
        try:
            result = check_site_availability(site["longId"], start_date, end_date)
            if result["available"]:
                available.append(site)
        except Exception as e:
            print(f"\n  Warning: could not check site {site['name']}: {e}", file=sys.stderr)
    print(file=sys.stderr)  # newline after progress
    return available


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def find_park_by_name(name):
    """Search parks by partial name match (case-insensitive)."""
    parks = list_parks()
    name_lower = name.lower()
    matches = [p for p in parks if name_lower in p["name"].lower()]
    return matches


def find_campground_by_name(park_id, name):
    """Search campgrounds within a park by partial name match."""
    campgrounds = list_campgrounds(park_id)
    name_lower = name.lower()
    matches = [c for c in campgrounds if name_lower in c["name"].lower()]
    return matches


def find_site_by_name(resource_location_id, site_name):
    """Find a specific site by its name/number within a campground."""
    sites = get_sites_for_location(resource_location_id)
    site_name_str = str(site_name)
    for site in sites:
        if site["name"] == site_name_str:
            return site
    # Partial match fallback
    for site in sites:
        if site_name_str in site["name"]:
            return site
    return None


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_reservation_url(resource_location_id, map_id, start_date, end_date,
                          booking_category_id=0, party_size=1):
    """Build a direct URL to the Ontario Parks reservation map page."""
    params = {
        "resourceLocationId": resource_location_id,
        "mapId": map_id,
        "bookingCategoryId": booking_category_id,
        "startDate": start_date,
        "endDate": end_date,
        "nights": (datetime.strptime(end_date, "%Y-%m-%d") -
                   datetime.strptime(start_date, "%Y-%m-%d")).days,
        "isReserving": "true",
        "partySize": party_size,
        "filterData": "{}",
        "searchTime": datetime.utcnow().isoformat(),
    }
    return f"{BASE_URL}/create-booking/results?{urlencode(params)}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check campsite availability on Ontario Parks (reservations.ontarioparks.ca)"
    )
    parser.add_argument("--list-parks", action="store_true",
                        help="List all parks and their IDs")
    parser.add_argument("--list-campgrounds", action="store_true",
                        help="List campgrounds in a park (requires --park-id or --park)")
    parser.add_argument("--list-sites", action="store_true",
                        help="List all sites in a campground (requires --campground-id)")
    parser.add_argument("--park", type=str,
                        help="Park name (partial match, e.g. 'Killbear')")
    parser.add_argument("--park-id", type=str,
                        help="Park resource location ID (use --list-parks to find)")
    parser.add_argument("--campground", type=str,
                        help="Campground name (partial match, e.g. 'Lighthouse Point B')")
    parser.add_argument("--campground-id", type=str,
                        help="Campground resource location ID")
    parser.add_argument("--site", type=str,
                        help="Specific site name/number (e.g. '1422')")
    parser.add_argument("--start", type=str,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()

    # --- List parks ---
    if args.list_parks:
        print("Fetching parks...")
        parks = list_parks()
        if args.json:
            print(json.dumps([{"name": p["name"], "id": p["id"]} for p in parks], indent=2))
        else:
            print(f"\n{'Park Name':<50} {'ID'}")
            print("-" * 70)
            for p in parks:
                print(f"{p['name']:<50} {p['id']}")
        return

    # --- Resolve park ---
    park_id = args.park_id
    if not park_id and args.park:
        matches = find_park_by_name(args.park)
        if not matches:
            print(f"No park found matching '{args.park}'.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(f"Multiple parks match '{args.park}':", file=sys.stderr)
            for m in matches:
                print(f"  - {m['name']} (ID: {m['id']})", file=sys.stderr)
            print("Use --park-id to specify one.", file=sys.stderr)
            sys.exit(1)
        park_id = matches[0]["id"]
        print(f"Park: {matches[0]['name']} (ID: {park_id})")

    # --- List campgrounds ---
    if args.list_campgrounds:
        if not park_id:
            print("--list-campgrounds requires --park or --park-id", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching campgrounds for park {park_id}...")
        campgrounds = list_campgrounds(park_id)
        if args.json:
            print(json.dumps([{"name": c["name"], "id": c["id"]} for c in campgrounds], indent=2))
        else:
            print(f"\n{'Campground Name':<50} {'ID'}")
            print("-" * 70)
            for c in campgrounds:
                print(f"{c['name']:<50} {c['id']}")
        return

    # --- Resolve campground ---
    campground_id = args.campground_id
    if not campground_id and args.campground and park_id:
        matches = find_campground_by_name(park_id, args.campground)
        if not matches:
            print(f"No campground found matching '{args.campground}' in park {park_id}.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(f"Multiple campgrounds match '{args.campground}':", file=sys.stderr)
            for m in matches:
                print(f"  - {m['name']} (ID: {m['id']})", file=sys.stderr)
            print("Use --campground-id to specify one.", file=sys.stderr)
            sys.exit(1)
        campground_id = matches[0]["id"]
        print(f"Campground: {matches[0]['name']} (ID: {campground_id})")

    # --- List sites ---
    if args.list_sites:
        if not campground_id:
            print("--list-sites requires --campground-id or (--park + --campground)", file=sys.stderr)
            sys.exit(1)
        sites = get_sites_for_location(campground_id)
        if args.json:
            print(json.dumps([{"name": s["name"], "id": s["longId"]} for s in sites], indent=2))
        else:
            print(f"\n{'Site Name':<30} {'ID'}")
            print("-" * 60)
            for s in sites:
                print(f"{s['name']:<30} {s['longId']}")
        return

    # --- Availability check requires dates ---
    if not args.start or not args.end:
        if not any([args.list_parks, args.list_campgrounds, args.list_sites]):
            print("--start and --end dates are required for availability checks.", file=sys.stderr)
            parser.print_help()
            sys.exit(1)
        return

    start_date = args.start
    end_date = args.end
    print(f"Date range: {start_date} to {end_date}")

    # --- Check specific site ---
    if args.site and campground_id:
        site = find_site_by_name(campground_id, args.site)
        if not site:
            print(f"Site '{args.site}' not found in campground {campground_id}.", file=sys.stderr)
            sys.exit(1)
        print(f"Checking availability for site {site['name']}...")
        result = check_site_availability(site["longId"], start_date, end_date)
        if args.json:
            print(json.dumps({"site": site["name"], "id": site["longId"], **result}, indent=2))
        else:
            status = "AVAILABLE" if result["available"] else "NOT AVAILABLE"
            print(f"\n  Site {site['name']}: {status}")
            if result["available"]:
                print(f"  Book at: {BASE_URL}")
        return

    # --- Check all sites in campground ---
    if campground_id:
        print(f"Checking all sites in campground {campground_id}...")
        available = find_available_sites(campground_id, start_date, end_date)
        if args.json:
            print(json.dumps([{"name": s["name"], "id": s["longId"]} for s in available], indent=2))
        else:
            if available:
                print(f"\n  {len(available)} available site(s):")
                for s in available:
                    print(f"    - Site {s['name']}")
            else:
                print("\n  No available sites found for the given dates.")
        return

    print("Please specify --park/--campground or use --list-parks to get started.", file=sys.stderr)
    parser.print_help()


if __name__ == "__main__":
    main()
