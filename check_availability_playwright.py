#!/usr/bin/env python3
"""
Ontario Parks Campground Availability Checker — Playwright Edition

Uses a real browser (headed or headless) to navigate the Ontario Parks
reservation site, intercept API responses, and extract availability data.
This bypasses the 403 / cookie / JS-challenge issues that block plain HTTP
requests.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    # Discover all parks (intercepts the park list API call):
    python check_availability_playwright.py --list-parks

    # Discover campgrounds in a park:
    python check_availability_playwright.py --park "Killbear" --list-campgrounds

    # Check availability for a specific campground + date range:
    python check_availability_playwright.py --park "Killbear" --campground "Lighthouse Point B" \
        --start 2026-07-19 --end 2026-08-01

    # Check a specific site:
    python check_availability_playwright.py --park "Killbear" --campground "Lighthouse Point B" \
        --site 1422 --start 2026-07-19 --end 2026-08-01

    # Run headed (visible browser window) for debugging:
    python check_availability_playwright.py --headed --park "Killbear" --list-campgrounds

    # Output as JSON:
    python check_availability_playwright.py --park "Killbear" --list-campgrounds --json
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlencode, urlparse, parse_qs

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError:
    print(
        "Error: 'playwright' is required.\n"
        "Install with:\n"
        "  pip install playwright\n"
        "  playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SITE_URL = "https://reservations.ontarioparks.ca"
DEFAULT_TIMEOUT = 30_000  # 30 seconds for page loads
API_INTERCEPT_TIMEOUT = 15_000  # 15 seconds to wait for API responses

# Default search parameters (tent camping, 2 people)
DEFAULT_EQUIPMENT_ID = -32768
DEFAULT_SUB_EQUIPMENT_ID = -32768
DEFAULT_PARTY_SIZE = 2
DEFAULT_BOOKING_CATEGORY_ID = 0


# ---------------------------------------------------------------------------
# URL builder — construct direct booking URLs from known IDs
# ---------------------------------------------------------------------------

def build_search_url(transaction_location_id, resource_location_id, map_id,
                     start_date, end_date, equipment_id=DEFAULT_EQUIPMENT_ID,
                     sub_equipment_id=DEFAULT_SUB_EQUIPMENT_ID,
                     party_size=DEFAULT_PARTY_SIZE,
                     booking_category_id=DEFAULT_BOOKING_CATEGORY_ID):
    """Build a direct URL to the Ontario Parks booking results page."""
    nights = (datetime.strptime(end_date, "%Y-%m-%d") -
              datetime.strptime(start_date, "%Y-%m-%d")).days
    params = {
        "transactionLocationId": transaction_location_id,
        "resourceLocationId": resource_location_id,
        "mapId": map_id,
        "searchTabGroupId": 0,
        "bookingCategoryId": booking_category_id,
        "startDate": start_date,
        "endDate": end_date,
        "nights": nights,
        "isReserving": "true",
        "equipmentId": equipment_id,
        "subEquipmentId": sub_equipment_id,
        "peopleCapacityCategoryCounts": json.dumps([
            [DEFAULT_EQUIPMENT_ID, None, party_size, None]
        ]),
        "searchTime": datetime.utcnow().isoformat(),
        "flexibleSearch": json.dumps([False, False, start_date[:8] + "01", 1]),
    }
    return f"{SITE_URL}/create-booking/results?{urlencode(params)}"


# ---------------------------------------------------------------------------
# API response interceptors
# ---------------------------------------------------------------------------

class ApiCapture:
    """Captures API responses intercepted from the browser's network traffic."""

    def __init__(self):
        self.parks = []             # from /api/resourcelocation/rootmaps
        self.campgrounds = []       # from /api/resourcelocation/resources
        self.sites = []             # from /api/resourcelocation/resources (site-level)
        self.availability = {}      # from /api/availability/* endpoints
        self.map_data = {}          # from /api/availability/map
        self.raw_responses = {}     # all captured API responses keyed by URL path

    def handle_response(self, response):
        """Playwright response handler — captures API JSON responses."""
        url = response.url
        if "/api/" not in url:
            return

        # Only process successful JSON responses
        if response.status != 200:
            return

        try:
            data = response.json()
        except Exception:
            return

        # Store raw response keyed by API path
        path = urlparse(url).path
        self.raw_responses[path] = data

        # Parse specific endpoints
        if "/api/resourcelocation/rootmaps" in url:
            self._parse_parks(data)
        elif "/api/resourcelocation/resources" in url:
            self._parse_resources(data)
        elif "/api/availability/map" in url:
            self._parse_map_availability(data)
        elif "/api/availability/resourcestatus" in url:
            self._parse_resource_status(url, data)
        elif "/api/availability/resourcedailyavailability" in url:
            self._parse_daily_availability(url, data)

    def _parse_parks(self, data):
        """Parse the rootmaps response into a park list."""
        if not isinstance(data, list):
            return
        self.parks = []
        for item in data:
            name = "Unknown"
            localized = item.get("localizedValues", [])
            if localized:
                name = localized[0].get("name", "Unknown")
            park_id = item.get("resourceLocationId") or item.get("mapId")
            self.parks.append({
                "name": name,
                "resourceLocationId": item.get("resourceLocationId"),
                "mapId": item.get("mapId"),
                "transactionLocationId": item.get("transactionLocationId"),
                "bookingCategoryId": item.get("bookingCategoryId", 0),
                "raw": item,
            })
        self.parks.sort(key=lambda p: p["name"])

    def _parse_resources(self, data):
        """Parse the resources response (campgrounds or sites)."""
        resources = []
        if isinstance(data, dict):
            for key, val in data.items():
                if val is None:
                    continue
                localized = val.get("localizedValues", [])
                name = localized[0].get("name", key) if localized else key
                resources.append({
                    "name": name,
                    "id": key,
                    "resourceLocationId": val.get("resourceLocationId"),
                    "mapId": val.get("mapId"),
                    "raw": val,
                })
        elif isinstance(data, list):
            for item in data:
                localized = item.get("localizedValues", [])
                name = localized[0].get("name", "Unknown") if localized else "Unknown"
                item_id = (item.get("resourceLocationId")
                           or item.get("mapId")
                           or item.get("id"))
                resources.append({
                    "name": name,
                    "id": item_id,
                    "resourceLocationId": item.get("resourceLocationId"),
                    "mapId": item.get("mapId"),
                    "raw": item,
                })
        resources.sort(key=lambda r: r["name"])

        # Heuristic: if resources have sub-maps, they're campgrounds;
        # if they're leaf nodes, they're sites
        if resources and resources[0].get("raw", {}).get("mapId"):
            self.campgrounds = resources
        else:
            self.sites = resources

    def _parse_map_availability(self, data):
        """Parse map availability response."""
        self.map_data = data

    def _parse_resource_status(self, url, data):
        """Parse single resource status response."""
        qs = parse_qs(urlparse(url).query)
        resource_id = qs.get("resourceId", [None])[0]
        if resource_id:
            self.availability[resource_id] = {
                "available": data.get("availabilityType", -1) == 0,
                "availability_type": data.get("availabilityType", -1),
                "raw": data,
            }

    def _parse_daily_availability(self, url, data):
        """Parse daily availability response."""
        qs = parse_qs(urlparse(url).query)
        resource_id = qs.get("resourceId", [None])[0]
        if resource_id:
            self.availability.setdefault(resource_id, {})
            self.availability[resource_id]["daily"] = data


# ---------------------------------------------------------------------------
# Browser automation
# ---------------------------------------------------------------------------

def create_browser(playwright, headed=False):
    """Launch a browser instance with realistic settings."""
    browser = playwright.chromium.launch(
        headless=not headed,
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        locale="en-US",
    )
    return browser, context


def discover_parks(headed=False, timeout=DEFAULT_TIMEOUT):
    """
    Navigate to the home page and intercept the parks API call.

    The SPA loads the park list to populate the search dropdown.
    We capture that response to get all park IDs.
    """
    with sync_playwright() as pw:
        browser, context = create_browser(pw, headed)
        capture = ApiCapture()
        page = context.new_page()
        page.on("response", capture.handle_response)

        print("Navigating to Ontario Parks home page...", file=sys.stderr)
        page.goto(SITE_URL, timeout=timeout, wait_until="domcontentloaded")

        # Wait for the park list API call, or timeout
        print("Waiting for park data to load...", file=sys.stderr)
        deadline = time.time() + API_INTERCEPT_TIMEOUT / 1000
        while not capture.parks and time.time() < deadline:
            page.wait_for_timeout(500)

        if not capture.parks:
            # Try triggering the search form to force the API call
            print("Park list not auto-loaded, trying to trigger search form...",
                  file=sys.stderr)
            try:
                # Click on the search/park selector to trigger data load
                page.click("text=Search", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(3000)

        if not capture.parks:
            # Last resort: check all captured API responses
            print("Checking all intercepted API responses...", file=sys.stderr)
            for path, data in capture.raw_responses.items():
                print(f"  Captured: {path}", file=sys.stderr)

        browser.close()
        return capture.parks


def discover_campgrounds(park_name, headed=False, timeout=DEFAULT_TIMEOUT):
    """
    Search for a park and intercept campground data.

    Strategy: Navigate to home page, use the search form to select the park,
    then capture the resulting page's API calls for campground data.
    """
    with sync_playwright() as pw:
        browser, context = create_browser(pw, headed)
        capture = ApiCapture()
        page = context.new_page()
        page.on("response", capture.handle_response)

        # Step 1: Load home page and wait for parks to load
        print("Loading home page...", file=sys.stderr)
        page.goto(SITE_URL, timeout=timeout, wait_until="domcontentloaded")

        deadline = time.time() + API_INTERCEPT_TIMEOUT / 1000
        while not capture.parks and time.time() < deadline:
            page.wait_for_timeout(500)

        # Step 2: Find the matching park
        park_name_lower = park_name.lower()
        matches = [p for p in capture.parks
                   if park_name_lower in p["name"].lower()]

        if not matches:
            print(f"No park found matching '{park_name}'.", file=sys.stderr)
            if capture.parks:
                print("Available parks:", file=sys.stderr)
                for p in capture.parks[:20]:
                    print(f"  - {p['name']}", file=sys.stderr)
            browser.close()
            return None, []

        if len(matches) > 1:
            print(f"Multiple parks match '{park_name}':", file=sys.stderr)
            for m in matches:
                print(f"  - {m['name']}", file=sys.stderr)
            browser.close()
            return None, []

        park = matches[0]
        print(f"Found park: {park['name']}", file=sys.stderr)

        # Step 3: Navigate to the park's booking page to get campgrounds
        # We need to construct a search URL or interact with the form
        # Try clicking the park in the search dropdown
        try:
            # Type the park name into the search input
            search_input = page.locator(
                "input[placeholder*='park' i], "
                "input[placeholder*='search' i], "
                "input[placeholder*='location' i], "
                "input[aria-label*='park' i], "
                "input[aria-label*='location' i]"
            ).first
            search_input.click(timeout=5000)
            search_input.fill(park_name, timeout=5000)
            page.wait_for_timeout(1000)

            # Click the matching suggestion
            suggestion = page.locator(
                f"text=/{re.escape(park['name'])}/i"
            ).first
            suggestion.click(timeout=5000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Could not interact with search form: {e}", file=sys.stderr)
            print("Trying direct URL navigation...", file=sys.stderr)

        # Step 4: If we have park IDs, navigate directly to the park results
        if park.get("resourceLocationId") and park.get("mapId"):
            # Use a dummy date range just to see campground structure
            dummy_start = "2026-07-01"
            dummy_end = "2026-07-02"
            direct_url = build_search_url(
                transaction_location_id=park.get("transactionLocationId",
                                                  park["resourceLocationId"]),
                resource_location_id=park["resourceLocationId"],
                map_id=park["mapId"],
                start_date=dummy_start,
                end_date=dummy_end,
            )
            print(f"Navigating to park results page...", file=sys.stderr)
            capture.campgrounds = []  # reset
            page.goto(direct_url, timeout=timeout, wait_until="domcontentloaded")

            # Wait for campground data
            deadline = time.time() + API_INTERCEPT_TIMEOUT / 1000
            while not capture.campgrounds and time.time() < deadline:
                page.wait_for_timeout(500)

        browser.close()
        return park, capture.campgrounds


def check_availability(park_name, campground_name, start_date, end_date,
                       site_filter=None, headed=False, timeout=DEFAULT_TIMEOUT):
    """
    Full flow: find park → find campground → navigate to campground →
    intercept availability data.
    """
    with sync_playwright() as pw:
        browser, context = create_browser(pw, headed)
        capture = ApiCapture()
        page = context.new_page()
        page.on("response", capture.handle_response)

        # Step 1: Load home page to discover park IDs
        print("Loading Ontario Parks...", file=sys.stderr)
        page.goto(SITE_URL, timeout=timeout, wait_until="domcontentloaded")

        deadline = time.time() + API_INTERCEPT_TIMEOUT / 1000
        while not capture.parks and time.time() < deadline:
            page.wait_for_timeout(500)

        # Step 2: Find the park
        park_name_lower = park_name.lower()
        matches = [p for p in capture.parks
                   if park_name_lower in p["name"].lower()]
        if not matches:
            print(f"No park found matching '{park_name}'.", file=sys.stderr)
            browser.close()
            return None
        park = matches[0]
        print(f"Park: {park['name']}", file=sys.stderr)

        # Step 3: Navigate to park results page
        park_url = build_search_url(
            transaction_location_id=park.get("transactionLocationId",
                                              park["resourceLocationId"]),
            resource_location_id=park["resourceLocationId"],
            map_id=park["mapId"],
            start_date=start_date,
            end_date=end_date,
        )
        print("Loading park results...", file=sys.stderr)
        capture.campgrounds = []
        page.goto(park_url, timeout=timeout, wait_until="domcontentloaded")

        deadline = time.time() + API_INTERCEPT_TIMEOUT / 1000
        while not capture.campgrounds and time.time() < deadline:
            page.wait_for_timeout(500)

        # Step 4: Find the campground
        cg_name_lower = campground_name.lower()
        cg_matches = [c for c in capture.campgrounds
                      if cg_name_lower in c["name"].lower()]
        if not cg_matches:
            print(f"No campground matching '{campground_name}'.", file=sys.stderr)
            if capture.campgrounds:
                print("Available campgrounds:", file=sys.stderr)
                for c in capture.campgrounds:
                    print(f"  - {c['name']}", file=sys.stderr)
            browser.close()
            return None
        campground = cg_matches[0]
        print(f"Campground: {campground['name']}", file=sys.stderr)

        # Step 5: Navigate to the campground map to trigger site/availability load
        cg_map_id = campground.get("mapId") or campground.get("id")
        cg_url = build_search_url(
            transaction_location_id=park.get("transactionLocationId",
                                              park["resourceLocationId"]),
            resource_location_id=park["resourceLocationId"],
            map_id=cg_map_id,
            start_date=start_date,
            end_date=end_date,
        )
        print("Loading campground map...", file=sys.stderr)
        capture.sites = []
        capture.availability = {}
        page.goto(cg_url, timeout=timeout, wait_until="domcontentloaded")

        # Wait for site data and availability to load
        print("Waiting for availability data...", file=sys.stderr)
        deadline = time.time() + API_INTERCEPT_TIMEOUT / 1000
        while time.time() < deadline:
            page.wait_for_timeout(500)
            # Check if we have site data AND some availability data
            if capture.sites and (capture.map_data or capture.availability):
                # Give a bit more time for remaining responses
                page.wait_for_timeout(2000)
                break

        # Step 6: If we got map availability data, use it
        results = {
            "park": park["name"],
            "campground": campground["name"],
            "start_date": start_date,
            "end_date": end_date,
            "sites": [],
        }

        if capture.map_data:
            print(f"Got map availability data.", file=sys.stderr)
            results["map_data"] = capture.map_data

        if capture.sites:
            print(f"Found {len(capture.sites)} sites.", file=sys.stderr)
            for site in capture.sites:
                site_info = {
                    "name": site["name"],
                    "id": site["id"],
                }
                # Check if we have availability for this site
                if site["id"] in capture.availability:
                    avail = capture.availability[site["id"]]
                    site_info["available"] = avail.get("available")
                    site_info["availability_type"] = avail.get("availability_type")
                results["sites"].append(site_info)

        # Step 7: If we need per-site availability and didn't get it from
        # the map endpoint, request it for each site (or just the filtered one)
        sites_to_check = results["sites"]
        if site_filter:
            site_filter_str = str(site_filter)
            sites_to_check = [
                s for s in sites_to_check
                if s["name"] == site_filter_str or site_filter_str in s["name"]
            ]
            if not sites_to_check:
                print(f"Site '{site_filter}' not found.", file=sys.stderr)
                print("Available sites:", file=sys.stderr)
                for s in results["sites"][:20]:
                    print(f"  - {s['name']}", file=sys.stderr)
                browser.close()
                return results

        # For sites without availability data, fetch it via the page's JS context
        sites_needing_check = [
            s for s in sites_to_check if "available" not in s
        ]
        if sites_needing_check:
            print(f"Fetching availability for {len(sites_needing_check)} site(s)...",
                  file=sys.stderr)
            for i, site in enumerate(sites_needing_check):
                try:
                    # Use page.evaluate to make fetch() calls from within
                    # the page's origin — same as the browser console script
                    avail_data = page.evaluate(
                        """async ([resourceId, startDate, endDate]) => {
                            const resp = await fetch(
                                `/api/availability/resourcestatus` +
                                `?resourceId=${resourceId}` +
                                `&startDate=${startDate}` +
                                `&endDate=${endDate}`
                            );
                            return await resp.json();
                        }""",
                        [site["id"], start_date, end_date],
                    )
                    site["available"] = avail_data.get("availabilityType", -1) == 0
                    site["availability_type"] = avail_data.get("availabilityType", -1)
                except Exception as e:
                    print(f"  Error checking site {site['name']}: {e}",
                          file=sys.stderr)
                    site["available"] = None

                if (i + 1) % 10 == 0 or i == len(sites_needing_check) - 1:
                    print(f"  Checked {i + 1}/{len(sites_needing_check)}...",
                          file=sys.stderr)

        browser.close()

        # Filter results if site_filter was specified
        if site_filter:
            results["sites"] = sites_to_check

        return results

    return None


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_parks(parks, as_json=False):
    if as_json:
        print(json.dumps([
            {"name": p["name"],
             "resourceLocationId": p["resourceLocationId"],
             "mapId": p["mapId"],
             "transactionLocationId": p.get("transactionLocationId")}
            for p in parks
        ], indent=2))
    else:
        print(f"\n{'Park Name':<50} {'ResourceLocationId':<20} {'MapId'}")
        print("-" * 90)
        for p in parks:
            print(f"{p['name']:<50} {str(p['resourceLocationId']):<20} {p['mapId']}")


def print_campgrounds(campgrounds, as_json=False):
    if as_json:
        print(json.dumps([
            {"name": c["name"], "id": c["id"],
             "mapId": c.get("mapId")}
            for c in campgrounds
        ], indent=2))
    else:
        print(f"\n{'Campground Name':<50} {'ID / MapId'}")
        print("-" * 70)
        for c in campgrounds:
            display_id = c.get("mapId") or c.get("id")
            print(f"{c['name']:<50} {display_id}")


def print_availability(results, as_json=False):
    if not results:
        print("No results.", file=sys.stderr)
        return

    if as_json:
        # Clean out raw data for JSON output
        clean = {
            "park": results["park"],
            "campground": results["campground"],
            "start_date": results["start_date"],
            "end_date": results["end_date"],
            "sites": [
                {k: v for k, v in s.items() if k != "raw"}
                for s in results["sites"]
            ],
        }
        print(json.dumps(clean, indent=2))
        return

    print(f"\n{'='*60}")
    print(f"  {results['park']} — {results['campground']}")
    print(f"  {results['start_date']} to {results['end_date']}")
    print(f"{'='*60}")

    available = [s for s in results["sites"] if s.get("available") is True]
    unavailable = [s for s in results["sites"] if s.get("available") is False]
    unknown = [s for s in results["sites"] if s.get("available") is None]

    if available:
        print(f"\n  AVAILABLE ({len(available)} sites):")
        for s in sorted(available, key=lambda x: x["name"]):
            print(f"    Site {s['name']}")

    if unavailable:
        print(f"\n  NOT AVAILABLE ({len(unavailable)} sites):")
        for s in sorted(unavailable, key=lambda x: x["name"])[:10]:
            print(f"    Site {s['name']}")
        if len(unavailable) > 10:
            print(f"    ... and {len(unavailable) - 10} more")

    if unknown:
        print(f"\n  COULD NOT CHECK ({len(unknown)} sites):")
        for s in sorted(unknown, key=lambda x: x["name"])[:5]:
            print(f"    Site {s['name']}")

    total = len(results["sites"])
    print(f"\n  Summary: {len(available)} available / {total} total sites")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Check Ontario Parks campsite availability using browser automation.\n"
            "Navigates the real site with Playwright to bypass API restrictions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list-parks", action="store_true",
                        help="Discover all parks and their IDs")
    parser.add_argument("--list-campgrounds", action="store_true",
                        help="List campgrounds in a park (requires --park)")
    parser.add_argument("--park", type=str,
                        help="Park name (partial match, e.g. 'Killbear')")
    parser.add_argument("--campground", type=str,
                        help="Campground name (partial match, e.g. 'Lighthouse Point B')")
    parser.add_argument("--site", type=str,
                        help="Specific site name/number (e.g. '1422')")
    parser.add_argument("--start", type=str,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--headed", action="store_true",
                        help="Run with visible browser window (for debugging)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Page load timeout in ms (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    # --- List parks ---
    if args.list_parks:
        parks = discover_parks(headed=args.headed, timeout=args.timeout)
        if parks:
            print_parks(parks, as_json=args.json)
        else:
            print("Could not discover parks. Try --headed to debug.",
                  file=sys.stderr)
            sys.exit(1)
        return

    # --- List campgrounds ---
    if args.list_campgrounds:
        if not args.park:
            print("--list-campgrounds requires --park", file=sys.stderr)
            sys.exit(1)
        park, campgrounds = discover_campgrounds(
            args.park, headed=args.headed, timeout=args.timeout)
        if campgrounds:
            print(f"Park: {park['name']}")
            print_campgrounds(campgrounds, as_json=args.json)
        else:
            print("Could not discover campgrounds. Try --headed to debug.",
                  file=sys.stderr)
            sys.exit(1)
        return

    # --- Availability check ---
    if not args.park or not args.campground:
        print("Availability check requires --park and --campground.",
              file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    if not args.start or not args.end:
        print("Availability check requires --start and --end dates.",
              file=sys.stderr)
        sys.exit(1)

    results = check_availability(
        park_name=args.park,
        campground_name=args.campground,
        start_date=args.start,
        end_date=args.end,
        site_filter=args.site,
        headed=args.headed,
        timeout=args.timeout,
    )
    print_availability(results, as_json=args.json)


if __name__ == "__main__":
    main()
