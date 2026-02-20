#!/usr/bin/env python3
"""
Ontario Parks Campground Availability Checker — Playwright Edition

Uses a real browser (headed or headless) to check campsite availability.
Reads cached park/campground/site IDs from site_structure.json (created by
discover_site.py) to skip discovery and navigate directly.

If site_structure.json is missing, falls back to live discovery.

Requirements:
    pip install playwright
    playwright install chromium

Setup (run once):
    python discover_site.py --park "Killbear" --include-sites

Usage:
    # Check all sites in a campground:
    python check_availability_playwright.py --park "Killbear" \
        --campground "Lighthouse Point B" --start 2026-07-19 --end 2026-08-01

    # Check a specific site:
    python check_availability_playwright.py --park "Killbear" \
        --campground "Lighthouse Point B" --site 1422 \
        --start 2026-07-19 --end 2026-08-01

    # List what's cached:
    python check_availability_playwright.py --list-parks
    python check_availability_playwright.py --park "Killbear" --list-campgrounds

    # Run headed (visible browser) for debugging:
    python check_availability_playwright.py --headed --park "Killbear" \
        --campground "Lighthouse Point B" --start 2026-07-19 --end 2026-08-01

    # Force live discovery instead of cache:
    python check_availability_playwright.py --no-cache --park "Killbear" \
        --list-campgrounds
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlencode, urlparse, parse_qs

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
API_WAIT_MS = 15_000

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "site_structure.json")

# Default search parameters (tent camping, 2 people)
DEFAULT_EQUIPMENT_ID = -32768
DEFAULT_SUB_EQUIPMENT_ID = -32768
DEFAULT_PARTY_SIZE = 2


# ---------------------------------------------------------------------------
# Cache: load saved IDs from site_structure.json
# ---------------------------------------------------------------------------

def load_cache(cache_file=CACHE_FILE):
    """Load the cached site structure JSON. Returns None if missing."""
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def find_park_in_cache(cache, park_name):
    """Find a park by partial name match in the cache."""
    if not cache:
        return None
    name_lower = park_name.lower()
    matches = [p for p in cache.get("parks", [])
               if name_lower in p["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Multiple parks match '{park_name}':", file=sys.stderr)
        for m in matches:
            print(f"  - {m['name']}", file=sys.stderr)
        sys.exit(1)
    return None


def find_campground_in_cache(park, campground_name):
    """Find a campground by partial name match in cached park data."""
    campgrounds = park.get("campgrounds", [])
    if not campgrounds:
        return None
    name_lower = campground_name.lower()
    matches = [c for c in campgrounds if name_lower in c["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Multiple campgrounds match '{campground_name}':", file=sys.stderr)
        for m in matches:
            print(f"  - {m['name']}", file=sys.stderr)
        sys.exit(1)
    return None


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_search_url(park, map_id, start_date, end_date,
                     party_size=DEFAULT_PARTY_SIZE):
    """Build a direct URL to the booking results page from cached IDs."""
    nights = (datetime.strptime(end_date, "%Y-%m-%d") -
              datetime.strptime(start_date, "%Y-%m-%d")).days
    params = {
        "transactionLocationId": park.get("transactionLocationId",
                                           park["resourceLocationId"]),
        "resourceLocationId": park["resourceLocationId"],
        "mapId": map_id,
        "searchTabGroupId": 0,
        "bookingCategoryId": park.get("bookingCategoryId", 0),
        "startDate": start_date,
        "endDate": end_date,
        "nights": nights,
        "isReserving": "true",
        "equipmentId": DEFAULT_EQUIPMENT_ID,
        "subEquipmentId": DEFAULT_SUB_EQUIPMENT_ID,
        "peopleCapacityCategoryCounts": json.dumps([
            [DEFAULT_EQUIPMENT_ID, None, party_size, None]
        ]),
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


def wait_for_condition(page, check_fn, timeout_ms=API_WAIT_MS):
    """Wait until check_fn() returns True or timeout."""
    deadline = time.time() + timeout_ms / 1000
    while not check_fn() and time.time() < deadline:
        page.wait_for_timeout(500)
    return check_fn()


# ---------------------------------------------------------------------------
# Live discovery fallback (when cache is missing)
# ---------------------------------------------------------------------------

def live_discover_parks(page):
    """Capture parks from the rootmaps API when the home page loads."""
    parks = []

    def on_response(response):
        if "/api/resourcelocation/rootmaps" in response.url and response.status == 200:
            try:
                data = response.json()
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
    page.goto(SITE_URL, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    wait_for_condition(page, lambda: len(parks) > 0)
    page.remove_listener("response", on_response)
    parks.sort(key=lambda p: p["name"])
    return parks


def live_discover_campgrounds(page, park):
    """Navigate to a park page and capture campgrounds from the resources API."""
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
                            "id": key,
                        })
            except Exception:
                pass

    url = build_search_url(park, park["mapId"], "2026-07-01", "2026-07-02")
    page.on("response", on_response)
    page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    wait_for_condition(page, lambda: len(campgrounds) > 0)
    page.remove_listener("response", on_response)
    campgrounds.sort(key=lambda c: c["name"])
    return campgrounds


# ---------------------------------------------------------------------------
# Availability checking
# ---------------------------------------------------------------------------

def check_availability(park, campground, start_date, end_date,
                       site_filter=None, headed=False, timeout=DEFAULT_TIMEOUT):
    """
    Navigate to a campground page and check availability for all (or one) sites.

    Uses cached IDs from site_structure.json to navigate directly.
    Falls back to page.evaluate() API calls for per-site availability.
    """
    cg_map_id = campground.get("mapId") or campground.get("id")
    cached_sites = campground.get("sites", [])

    with sync_playwright() as pw:
        browser, context = create_browser(pw, headed)
        page = context.new_page()

        # Navigate to the campground page to establish a session
        cg_url = build_search_url(park, cg_map_id, start_date, end_date)
        print(f"Loading {campground['name']}...", file=sys.stderr)
        page.goto(cg_url, timeout=timeout, wait_until="domcontentloaded")

        # Wait for the page to settle (Angular SPA needs time to bootstrap)
        page.wait_for_timeout(3000)

        # If we don't have cached sites, discover them now via page.evaluate
        sites = cached_sites
        if not sites:
            print("No cached sites — discovering via API...", file=sys.stderr)
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
                if isinstance(data, dict):
                    for key, val in data.items():
                        if val is None:
                            continue
                        localized = val.get("localizedValues", [])
                        name = localized[0].get("name", key) if localized else key
                        sites.append({"name": name, "id": key})
                elif isinstance(data, list):
                    for item in data:
                        localized = item.get("localizedValues", [])
                        name = localized[0].get("name", "Unknown") if localized else "Unknown"
                        site_id = (item.get("resourceLocationId")
                                   or item.get("mapId")
                                   or item.get("id"))
                        sites.append({"name": name, "id": site_id})
            except Exception as e:
                print(f"Error discovering sites: {e}", file=sys.stderr)

        if not sites:
            print("No sites found.", file=sys.stderr)
            browser.close()
            return None

        # Filter to specific site if requested
        if site_filter:
            site_filter_str = str(site_filter)
            filtered = [s for s in sites
                        if s["name"] == site_filter_str
                        or site_filter_str in s["name"]]
            if not filtered:
                print(f"Site '{site_filter}' not found. Available sites:",
                      file=sys.stderr)
                for s in sorted(sites, key=lambda x: x["name"]):
                    print(f"  - {s['name']}", file=sys.stderr)
                browser.close()
                return None
            sites = filtered

        # Check availability for each site using page.evaluate
        # This runs fetch() from within the browser's origin context
        print(f"Checking availability for {len(sites)} site(s)...", file=sys.stderr)

        results = {
            "park": park["name"],
            "campground": campground["name"],
            "start_date": start_date,
            "end_date": end_date,
            "sites": [],
        }

        # Batch the checks in JavaScript for speed
        batch_size = 20
        for batch_start in range(0, len(sites), batch_size):
            batch = sites[batch_start:batch_start + batch_size]
            site_ids = [s["id"] for s in batch]

            try:
                batch_results = page.evaluate(
                    """async ([siteIds, startDate, endDate]) => {
                        const results = {};
                        for (const id of siteIds) {
                            try {
                                const resp = await fetch(
                                    `/api/availability/resourcestatus` +
                                    `?resourceId=${id}` +
                                    `&startDate=${startDate}` +
                                    `&endDate=${endDate}`
                                );
                                results[id] = await resp.json();
                            } catch (e) {
                                results[id] = {error: e.message};
                            }
                            // Small delay to be polite
                            await new Promise(r => setTimeout(r, 200));
                        }
                        return results;
                    }""",
                    [site_ids, start_date, end_date],
                )
            except Exception as e:
                print(f"  Batch error: {e}", file=sys.stderr)
                batch_results = {}

            for site in batch:
                site_result = batch_results.get(str(site["id"]),
                                                 batch_results.get(site["id"], {}))
                avail_type = site_result.get("availabilityType", -1)
                results["sites"].append({
                    "name": site["name"],
                    "id": site["id"],
                    "available": avail_type == 0,
                    "availability_type": avail_type,
                })

            checked = min(batch_start + batch_size, len(sites))
            print(f"  Checked {checked}/{len(sites)} sites...", file=sys.stderr)

        browser.close()
        return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_parks(parks, as_json=False):
    if as_json:
        out = [{"name": p["name"],
                "resourceLocationId": p.get("resourceLocationId"),
                "mapId": p.get("mapId"),
                "transactionLocationId": p.get("transactionLocationId"),
                "has_campgrounds": "campgrounds" in p}
               for p in parks]
        print(json.dumps(out, indent=2))
    else:
        print(f"\n{'Park Name':<50} {'ResourceLocationId':<20} {'MapId':<15} {'Cached'}")
        print("-" * 95)
        for p in parks:
            cached = "yes" if "campgrounds" in p else ""
            print(f"{p['name']:<50} "
                  f"{str(p.get('resourceLocationId', '')):<20} "
                  f"{str(p.get('mapId', '')):<15} "
                  f"{cached}")


def print_campgrounds(campgrounds, as_json=False):
    if as_json:
        out = [{"name": c["name"],
                "mapId": c.get("mapId"),
                "site_count": len(c.get("sites", []))}
               for c in campgrounds]
        print(json.dumps(out, indent=2))
    else:
        print(f"\n{'Campground Name':<50} {'MapId':<20} {'Sites Cached'}")
        print("-" * 80)
        for c in campgrounds:
            site_count = len(c.get("sites", []))
            sites_str = str(site_count) if site_count else "not cached"
            print(f"{c['name']:<50} {str(c.get('mapId', '')):<20} {sites_str}")


def print_availability(results, as_json=False):
    if not results:
        print("No results.", file=sys.stderr)
        return

    if as_json:
        print(json.dumps(results, indent=2))
        return

    print(f"\n{'='*60}")
    print(f"  {results['park']} -- {results['campground']}")
    print(f"  {results['start_date']} to {results['end_date']}")
    print(f"{'='*60}")

    available = [s for s in results["sites"] if s.get("available") is True]
    unavailable = [s for s in results["sites"] if s.get("available") is False]
    unknown = [s for s in results["sites"]
               if s.get("available") is None or s.get("availability_type", -1) == -1]

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
        for s in unknown[:5]:
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
            "Check Ontario Parks availability using browser automation.\n"
            "Uses cached IDs from site_structure.json (run discover_site.py first)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list-parks", action="store_true",
                        help="List all parks (from cache or live)")
    parser.add_argument("--list-campgrounds", action="store_true",
                        help="List campgrounds in a park")
    parser.add_argument("--park", type=str,
                        help="Park name (partial match)")
    parser.add_argument("--campground", type=str,
                        help="Campground name (partial match)")
    parser.add_argument("--site", type=str,
                        help="Specific site name/number (e.g. '1422')")
    parser.add_argument("--start", type=str,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--headed", action="store_true",
                        help="Run with visible browser (for debugging)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip cache, discover live from the site")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Page load timeout in ms (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    # Load cache
    cache = None if args.no_cache else load_cache()
    if cache:
        print(f"Using cached data from {CACHE_FILE} "
              f"(discovered {cache.get('discovered_at', 'unknown')})",
              file=sys.stderr)
    else:
        print("No cache found — will discover live from the site.", file=sys.stderr)

    # --- List parks ---
    if args.list_parks:
        if cache:
            print_parks(cache["parks"], as_json=args.json)
        else:
            with sync_playwright() as pw:
                browser, context = create_browser(pw, args.headed)
                page = context.new_page()
                parks = live_discover_parks(page)
                browser.close()
                if parks:
                    print_parks(parks, as_json=args.json)
                else:
                    print("Could not discover parks. Try --headed.", file=sys.stderr)
                    sys.exit(1)
        return

    # --- Need a park from here on ---
    if not args.park:
        parser.print_help()
        sys.exit(1)

    # Resolve park
    park = None
    if cache:
        park = find_park_in_cache(cache, args.park)
    if not park:
        if cache and not args.no_cache:
            print(f"Park '{args.park}' not in cache. Run: "
                  f"python discover_site.py --park \"{args.park}\"",
                  file=sys.stderr)
            sys.exit(1)
        # Live discovery
        with sync_playwright() as pw:
            browser, context = create_browser(pw, args.headed)
            page = context.new_page()
            parks = live_discover_parks(page)
            name_lower = args.park.lower()
            matches = [p for p in parks if name_lower in p["name"].lower()]
            if not matches:
                print(f"No park matching '{args.park}'.", file=sys.stderr)
                browser.close()
                sys.exit(1)
            park = matches[0]
            # Also discover campgrounds while we have the browser open
            campgrounds = live_discover_campgrounds(page, park)
            park["campgrounds"] = campgrounds
            browser.close()

    print(f"Park: {park['name']}", file=sys.stderr)

    # --- List campgrounds ---
    if args.list_campgrounds:
        campgrounds = park.get("campgrounds", [])
        if campgrounds:
            print_campgrounds(campgrounds, as_json=args.json)
        else:
            print(f"No campgrounds cached for {park['name']}. Run: "
                  f"python discover_site.py --park \"{park['name']}\"",
                  file=sys.stderr)
            sys.exit(1)
        return

    # --- Availability check ---
    if not args.campground:
        print("--campground is required for availability checks.", file=sys.stderr)
        sys.exit(1)
    if not args.start or not args.end:
        print("--start and --end dates are required.", file=sys.stderr)
        sys.exit(1)

    campground = find_campground_in_cache(park, args.campground)
    if not campground:
        print(f"Campground '{args.campground}' not found in {park['name']}.",
              file=sys.stderr)
        campgrounds = park.get("campgrounds", [])
        if campgrounds:
            print("Available campgrounds:", file=sys.stderr)
            for c in campgrounds:
                print(f"  - {c['name']}", file=sys.stderr)
        sys.exit(1)

    print(f"Campground: {campground['name']}", file=sys.stderr)

    results = check_availability(
        park=park,
        campground=campground,
        start_date=args.start,
        end_date=args.end,
        site_filter=args.site,
        headed=args.headed,
        timeout=args.timeout,
    )
    print_availability(results, as_json=args.json)


if __name__ == "__main__":
    main()
