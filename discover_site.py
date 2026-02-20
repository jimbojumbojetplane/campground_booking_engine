#!/usr/bin/env python3
"""
Ontario Parks Site Structure Discovery

Launches a browser, navigates the Ontario Parks reservation site, and
extracts the full hierarchy of parks → campgrounds → sites with all IDs.
Saves the result to site_structure.json for reuse by other scripts.

This only needs to be run once (or when you suspect new parks/campgrounds
have been added). The availability checker reads the cached JSON.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    # Discover all parks (fast, ~30 seconds):
    python discover_site.py

    # Discover parks + campgrounds for a specific park:
    python discover_site.py --park "Killbear"

    # Discover parks + campgrounds + all sites (slow, fetches every campground):
    python discover_site.py --park "Killbear" --include-sites

    # Discover everything for all parks (very slow):
    python discover_site.py --all --include-sites

    # Run headed for debugging:
    python discover_site.py --park "Killbear" --include-sites --headed

    # Custom output file:
    python discover_site.py --park "Killbear" --output my_parks.json
"""

import argparse
import json
import os
import sys
import time
import random
from datetime import datetime
from urllib.parse import urlencode

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError:
    print(
        "Error: 'playwright' is required.\n"
        "  pip install playwright\n"
        "  playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SITE_URL = "https://reservations.ontarioparks.ca"
DEFAULT_TIMEOUT = 30_000
API_WAIT = 15_000
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "site_structure.json")

# Dummy dates for URL construction (needed to reach results pages)
DUMMY_START = "2026-07-01"
DUMMY_END = "2026-07-02"


def polite_delay(min_s=0.3, max_s=0.8):
    """Random delay to avoid hammering the server."""
    time.sleep(random.uniform(min_s, max_s))


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_results_url(transaction_location_id, resource_location_id, map_id,
                      start_date=DUMMY_START, end_date=DUMMY_END):
    nights = (datetime.strptime(end_date, "%Y-%m-%d") -
              datetime.strptime(start_date, "%Y-%m-%d")).days
    params = {
        "transactionLocationId": transaction_location_id,
        "resourceLocationId": resource_location_id,
        "mapId": map_id,
        "searchTabGroupId": 0,
        "bookingCategoryId": 0,
        "startDate": start_date,
        "endDate": end_date,
        "nights": nights,
        "isReserving": "true",
        "equipmentId": -32768,
        "subEquipmentId": -32768,
        "peopleCapacityCategoryCounts": json.dumps([[-32768, None, 2, None]]),
        "searchTime": datetime.utcnow().isoformat(),
        "flexibleSearch": json.dumps([False, False, start_date[:8] + "01", 1]),
    }
    return f"{SITE_URL}/create-booking/results?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def create_browser(pw, headed=False):
    browser = pw.chromium.launch(
        headless=not headed,
        args=["--disable-blink-features=AutomationControlled"],
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


def wait_for_api(page, capture_list, timeout_ms=API_WAIT):
    """Wait until capture_list has data or timeout."""
    deadline = time.time() + timeout_ms / 1000
    while not capture_list and time.time() < deadline:
        page.wait_for_timeout(500)
    return len(capture_list) > 0


# ---------------------------------------------------------------------------
# Discovery functions
# ---------------------------------------------------------------------------

def discover_parks(page):
    """Navigate to home page and capture the parks list from rootmaps API."""
    parks = []

    def on_response(response):
        if "/api/resourcelocation/rootmaps" in response.url and response.status == 200:
            try:
                data = response.json()
                if isinstance(data, list):
                    for item in data:
                        localized = item.get("localizedValues", [])
                        name = localized[0].get("name", "Unknown") if localized else "Unknown"
                        parks.append({
                            "name": name,
                            "transactionLocationId": item.get("transactionLocationId"),
                            "resourceLocationId": item.get("resourceLocationId"),
                            "mapId": item.get("mapId"),
                            "bookingCategoryId": item.get("bookingCategoryId", 0),
                        })
            except Exception:
                pass

    page.on("response", on_response)
    print("  Loading home page to discover parks...", file=sys.stderr)
    page.goto(SITE_URL, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    wait_for_api(page, parks)

    if not parks:
        # Try triggering the search form
        print("  Parks not auto-loaded, trying to trigger form...", file=sys.stderr)
        try:
            page.click("text=Search", timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

    page.remove_listener("response", on_response)
    parks.sort(key=lambda p: p["name"])
    return parks


def discover_campgrounds(page, park):
    """Navigate to a park's results page and capture campgrounds."""
    campgrounds = []

    def on_response(response):
        if "/api/resourcelocation/resources" in response.url and response.status == 200:
            try:
                data = response.json()
                if isinstance(data, dict):
                    for key, val in data.items():
                        if val is None:
                            continue
                        localized = val.get("localizedValues", [])
                        name = localized[0].get("name", key) if localized else key
                        campgrounds.append({
                            "name": name,
                            "mapId": val.get("mapId"),
                            "resourceLocationId": val.get("resourceLocationId"),
                            "id": key,
                        })
                elif isinstance(data, list):
                    for item in data:
                        localized = item.get("localizedValues", [])
                        name = localized[0].get("name", "Unknown") if localized else "Unknown"
                        campgrounds.append({
                            "name": name,
                            "mapId": item.get("mapId"),
                            "resourceLocationId": item.get("resourceLocationId"),
                            "id": item.get("resourceLocationId") or item.get("mapId"),
                        })
            except Exception:
                pass

    page.on("response", on_response)

    url = build_results_url(
        transaction_location_id=park.get("transactionLocationId",
                                          park["resourceLocationId"]),
        resource_location_id=park["resourceLocationId"],
        map_id=park["mapId"],
    )
    print(f"  Loading park page for {park['name']}...", file=sys.stderr)
    page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    wait_for_api(page, campgrounds)

    page.remove_listener("response", on_response)
    campgrounds.sort(key=lambda c: c["name"])
    return campgrounds


def discover_sites(page, park, campground):
    """Navigate to a campground page and capture individual site IDs."""
    cg_map_id = campground.get("mapId") or campground.get("id")
    if not cg_map_id:
        return []

    # Use page.evaluate to call the API from within the page context.
    # This avoids an extra navigation and is faster.
    print(f"    Fetching sites for {campground['name']}...", file=sys.stderr)
    polite_delay()

    try:
        data = page.evaluate(
            """async (mapId) => {
                const resp = await fetch(
                    `/api/resourcelocation/resources?resourceLocationId=${mapId}`
                );
                return await resp.json();
            }""",
            cg_map_id,
        )
    except Exception as e:
        print(f"    Error fetching sites: {e}", file=sys.stderr)
        return []

    sites = []
    if isinstance(data, dict):
        for key, val in data.items():
            if val is None:
                continue
            localized = val.get("localizedValues", [])
            name = localized[0].get("name", key) if localized else key
            sites.append({
                "name": name,
                "id": key,
            })
    elif isinstance(data, list):
        for item in data:
            localized = item.get("localizedValues", [])
            name = localized[0].get("name", "Unknown") if localized else "Unknown"
            site_id = (item.get("resourceLocationId")
                       or item.get("mapId")
                       or item.get("id"))
            sites.append({
                "name": name,
                "id": site_id,
            })

    sites.sort(key=lambda s: s["name"])
    return sites


# ---------------------------------------------------------------------------
# Main discovery orchestration
# ---------------------------------------------------------------------------

def run_discovery(park_filter=None, include_sites=False, discover_all=False,
                  headed=False, output_file=OUTPUT_FILE):
    with sync_playwright() as pw:
        browser, context = create_browser(pw, headed)
        page = context.new_page()

        # Step 1: Discover all parks
        parks = discover_parks(page)
        if not parks:
            print("ERROR: Could not discover any parks. Try --headed to debug.",
                  file=sys.stderr)
            browser.close()
            sys.exit(1)

        print(f"  Found {len(parks)} parks.", file=sys.stderr)

        # Step 2: Filter parks if requested
        parks_to_expand = []
        if park_filter:
            filter_lower = park_filter.lower()
            parks_to_expand = [p for p in parks if filter_lower in p["name"].lower()]
            if not parks_to_expand:
                print(f"  No park matching '{park_filter}'.", file=sys.stderr)
                print("  Available parks:", file=sys.stderr)
                for p in parks:
                    print(f"    - {p['name']}", file=sys.stderr)
                browser.close()
                sys.exit(1)
        elif discover_all:
            parks_to_expand = parks

        # Step 3: Discover campgrounds for selected parks
        for park in parks_to_expand:
            campgrounds = discover_campgrounds(page, park)
            park["campgrounds"] = campgrounds
            print(f"  Found {len(campgrounds)} campgrounds in {park['name']}.",
                  file=sys.stderr)
            polite_delay()

            # Step 4: Discover sites within each campground
            if include_sites and campgrounds:
                # We need to be on a park results page to use page.evaluate
                # (the page should already be there from discover_campgrounds)
                for cg in campgrounds:
                    sites = discover_sites(page, park, cg)
                    cg["sites"] = sites
                    print(f"    Found {len(sites)} sites in {cg['name']}.",
                          file=sys.stderr)

        browser.close()

        # Build output structure
        output = {
            "discovered_at": datetime.utcnow().isoformat() + "Z",
            "site_url": SITE_URL,
            "park_count": len(parks),
            "parks": parks,
        }

        # Load existing file and merge if it exists
        if os.path.exists(output_file):
            try:
                with open(output_file, "r") as f:
                    existing = json.load(f)
                # Merge: update parks we just discovered, keep others
                existing_parks = {p["resourceLocationId"]: p
                                  for p in existing.get("parks", [])}
                for park in parks:
                    existing_parks[park["resourceLocationId"]] = park
                output["parks"] = sorted(existing_parks.values(),
                                         key=lambda p: p["name"])
                output["park_count"] = len(output["parks"])
            except (json.JSONDecodeError, KeyError):
                pass  # Overwrite if file is corrupt

        # Write output
        with open(output_file, "w") as f:
            json.dump(output, f, indent=2)

        print(f"\n  Saved to {output_file}", file=sys.stderr)
        return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Discover Ontario Parks site structure and save IDs to JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--park", type=str,
                        help="Discover campgrounds (and optionally sites) for this park")
    parser.add_argument("--all", action="store_true",
                        help="Discover campgrounds for ALL parks (slow)")
    parser.add_argument("--include-sites", action="store_true",
                        help="Also discover individual site IDs within each campground")
    parser.add_argument("--headed", action="store_true",
                        help="Run with visible browser window")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE,
                        help=f"Output JSON file (default: {OUTPUT_FILE})")
    args = parser.parse_args()

    result = run_discovery(
        park_filter=args.park,
        include_sites=args.include_sites,
        discover_all=args.all,
        headed=args.headed,
        output_file=args.output,
    )

    # Print summary
    expanded = [p for p in result["parks"] if "campgrounds" in p]
    print(f"\nDiscovered {result['park_count']} parks.")
    for park in expanded:
        cgs = park["campgrounds"]
        print(f"  {park['name']}: {len(cgs)} campgrounds")
        for cg in cgs:
            sites = cg.get("sites", [])
            if sites:
                print(f"    {cg['name']}: {len(sites)} sites")
            else:
                print(f"    {cg['name']} (mapId: {cg.get('mapId')})")


if __name__ == "__main__":
    main()
