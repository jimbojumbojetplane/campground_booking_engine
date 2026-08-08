#!/usr/bin/env python3
"""
Check availability for ALL target sites - WORKING VERSION
Scans multiple sites to find first available booking window.
"""

import sys
import json
import os
import argparse
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# Hardcoded Killbear IDs
KILLBEAR_RESOURCE_ID = -2147483600
KILLBEAR_TRANSACTION_ID = -2147483596
KILLBEAR_MAP_ID = -2147483428

# Load site mappings from extracted site map
SITE_MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "killbear-site-map.json")
with open(SITE_MAP_PATH) as f:
    _SITE_MAP = json.load(f)

# Default target sites — matches SKILL.md priority order (can be overridden via --sites flag)
DEFAULT_TARGETS = ["1418", "1416", "1422", "1108", "1110", "1037", "1038"]
TARGET_SITES = {name: _SITE_MAP[name]["resourceId"] for name in DEFAULT_TARGETS}

def check_all_sites(start_date, end_date, headed=False):
    """Check all target sites for availability."""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()
        
        # Navigate to establish session
        url = (
            f"https://reservations.ontarioparks.ca/create-booking/results?"
            f"transactionLocationId={KILLBEAR_TRANSACTION_ID}&"
            f"resourceLocationId={KILLBEAR_RESOURCE_ID}&"
            f"mapId={KILLBEAR_MAP_ID}&"
            f"startDate={start_date}&"
            f"endDate={end_date}"
        )
        
        print(f"Loading Ontario Parks...", file=sys.stderr)
        page.goto(url, timeout=30000)
        page.wait_for_timeout(5000)
        
        results = {}
        
        # Check each site
        for site_name, resource_id in TARGET_SITES.items():
            print(f"Checking site {site_name}...", file=sys.stderr)
            
            try:
                data = page.evaluate(
                    """async ([resourceId, start, end]) => {
                        const resp = await fetch(
                            `/api/availability/resourcedailyavailability?resourceId=${resourceId}&startDate=${start}&endDate=${end}`
                        );
                        return await resp.json();
                    }""",
                    [resource_id, start_date, end_date]
                )
                
                # Parse positional array
                start = datetime.strptime(start_date, "%Y-%m-%d")
                availability = []
                
                for i, day in enumerate(data):
                    date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
                    avail_val = day.get("availability")
                    
                    if avail_val is None:
                        avail_val = -1
                    
                    is_available = (avail_val == 0)
                    availability.append((date, is_available))
                
                results[site_name] = availability
                
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)
                results[site_name] = None
        
        browser.close()
        return results

def main():
    global TARGET_SITES
    parser = argparse.ArgumentParser(description="Check all target sites")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--sites", help="Comma-separated site numbers (default: target sites)")
    parser.add_argument("--headed", action="store_true", help="Show browser")
    args = parser.parse_args()

    if args.sites:
        site_names = [s.strip() for s in args.sites.split(",")]
        TARGET_SITES = {}
        for name in site_names:
            if name not in _SITE_MAP:
                print(f"ERROR: Unknown site {name}", file=sys.stderr)
                sys.exit(1)
            TARGET_SITES[name] = _SITE_MAP[name]["resourceId"]

    results = check_all_sites(args.start, args.end, args.headed)
    
    # Print results
    print(f"\n{'Site':<6} {'Dates Available':<50} {'Status'}")
    print("=" * 80)
    
    for site_name in TARGET_SITES.keys():
        availability = results.get(site_name)
        
        if not availability:
            print(f"{site_name:<6} {'ERROR':<50} ❌")
            continue
        
        available_dates = [date for date, avail in availability if avail]
        total_days = len(availability)
        avail_count = len(available_dates)
        
        if avail_count == total_days:
            status = "✅ FULLY AVAILABLE"
            dates_str = f"All {total_days} days"
        elif avail_count > 0:
            dates_str = f"{avail_count}/{total_days} days: " + ", ".join(available_dates[:5])
            if avail_count > 5:
                dates_str += f" (+{avail_count-5} more)"
            status = "⚠️  PARTIAL"
        else:
            dates_str = f"0/{total_days} days"
            status = "❌ NOT AVAILABLE"
        
        print(f"{site_name:<6} {dates_str:<50} {status}")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
