#!/usr/bin/env python3
"""
Check availability for a single Ontario Parks site - WORKING VERSION
Based on Claude Code's fixes for the API changes.
"""

import sys
import json
import os
import argparse
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# Hardcoded Killbear IDs (stable)
KILLBEAR_RESOURCE_ID = -2147483600
KILLBEAR_TRANSACTION_ID = -2147483596
KILLBEAR_MAP_ID = -2147483428

# Load site mappings from extracted site map (886 sites across all campgrounds)
SITE_MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "killbear-site-map.json")
with open(SITE_MAP_PATH) as f:
    _SITE_MAP = json.load(f)
SITE_MAPPINGS = {name: entry["resourceId"] for name, entry in _SITE_MAP.items()}

def check_site_availability(site_name, start_date, end_date, headed=False):
    """
    Check availability for a specific site.
    
    Args:
        site_name: Site display name (e.g. "1422")
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        headed: Show browser window
    
    Returns:
        List of (date, is_available) tuples
    """
    
    # Get resourceId for site
    resource_id = SITE_MAPPINGS.get(site_name)
    if not resource_id:
        print(f"ERROR: Unknown site {site_name}", file=sys.stderr)
        print(f"Known sites: {list(SITE_MAPPINGS.keys())}", file=sys.stderr)
        return None
    
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
        page.wait_for_timeout(5000)  # Let session establish
        
        # Call availability API using REAL resourceId
        print(f"Checking site {site_name} (resourceId: {resource_id})...", file=sys.stderr)
        
        try:
            result = page.evaluate(
                """async ([resourceId, start, end]) => {
                    const resp = await fetch(
                        `/api/availability/resourcedailyavailability?resourceId=${resourceId}&startDate=${start}&endDate=${end}`
                    );
                    return await resp.json();
                }""",
                [resource_id, start_date, end_date]
            )
        except Exception as e:
            print(f"ERROR: API call failed: {e}", file=sys.stderr)
            browser.close()
            return None
        
        browser.close()
        
        # Parse results (positional array, no date field)
        start = datetime.strptime(start_date, "%Y-%m-%d")
        availability = []
        
        for i, day in enumerate(result):
            date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            avail_val = day.get("availability")
            
            # CRITICAL: availability=0 means AVAILABLE but is falsy!
            if avail_val is None:
                avail_val = -1  # Unknown
            
            is_available = (avail_val == 0)
            availability.append((date, is_available))
        
        return availability

def main():
    parser = argparse.ArgumentParser(description="Check Ontario Parks site availability")
    parser.add_argument("--site", required=True, help="Site name (e.g. 1422)")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--headed", action="store_true", help="Show browser")
    args = parser.parse_args()
    
    results = check_site_availability(args.site, args.start, args.end, args.headed)
    
    if not results:
        sys.exit(1)
    
    # Print results
    print(f"\n{'Date':<12} {'Available':<10}")
    print("=" * 25)
    
    available_count = 0
    for date, is_available in results:
        status = "✅ YES" if is_available else "❌ NO"
        print(f"{date:<12} {status:<10}")
        if is_available:
            available_count += 1
    
    print("=" * 25)
    print(f"Available: {available_count}/{len(results)} days")
    
    # Exit code: 0 if all days available, 1 if some unavailable, 2 if none available
    if available_count == len(results):
        sys.exit(0)
    elif available_count > 0:
        sys.exit(1)
    else:
        sys.exit(2)

if __name__ == "__main__":
    main()
