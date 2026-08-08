#!/usr/bin/env python3
"""
Find the next 7-day booking window for target sites.
"""

import sys
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

KILLBEAR_RESOURCE_ID = -2147483600
KILLBEAR_TRANSACTION_ID = -2147483596
KILLBEAR_MAP_ID = -2147483428

TARGET_SITES = {
    "1422": -2147474828,
    "1418": -2147474629,
    "1416": -2147475046,
    "1108": -2147474720,
    "1110": -2147474767,
}

def check_site(page, site_name, resource_id, start_date, end_date):
    """Check if site has 7 consecutive available days."""
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
        
        # Check if all 7 days are available (availability=0)
        if len(data) < 7:
            return False
        
        for day in data[:7]:  # First 7 days
            avail_val = day.get("availability")
            if avail_val != 0:  # 0 = available
                return False
        
        return True
    except:
        return False

def main():
    # Start from tomorrow's window (Feb 22 = July 24)
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    first_check = tomorrow + timedelta(days=152)  # ~5 months
    
    print(f"Scanning from {first_check} onwards for 7-day windows...")
    print(f"(Tomorrow at 7am opens bookings for {first_check})\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Navigate once to establish session
        url = (
            f"https://reservations.ontarioparks.ca/create-booking/results?"
            f"transactionLocationId={KILLBEAR_TRANSACTION_ID}&"
            f"resourceLocationId={KILLBEAR_RESOURCE_ID}&"
            f"mapId={KILLBEAR_MAP_ID}"
        )
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)
        
        results = {}
        
        # Check next 14 days of booking windows
        for day_offset in range(14):
            check_start = first_check + timedelta(days=day_offset)
            check_end = check_start + timedelta(days=7)
            booking_date = tomorrow + timedelta(days=day_offset)
            
            start_str = check_start.strftime("%Y-%m-%d")
            end_str = check_end.strftime("%Y-%m-%d")
            
            print(f"Checking {start_str} to {end_str}...")
            
            for site_name, resource_id in TARGET_SITES.items():
                # Skip if already found
                if site_name in results:
                    continue
                
                if check_site(page, site_name, resource_id, start_str, end_str):
                    results[site_name] = {
                        "dates": f"{start_str} to {end_str}",
                        "book_on": booking_date.strftime("%Y-%m-%d"),
                    }
                    print(f"  ✅ Site {site_name}: AVAILABLE!")
            
            # Stop if all sites found
            if len(results) == len(TARGET_SITES):
                break
        
        browser.close()
        
        # Print results
        print("\n" + "=" * 80)
        print(f"{'Site':<6} {'Dates Available':<25} {'Book On':<15} {'Days Until'}")
        print("=" * 80)
        
        for site_name in TARGET_SITES.keys():
            if site_name in results:
                info = results[site_name]
                booking_date = datetime.strptime(info["book_on"], "%Y-%m-%d").date()
                days_until = (booking_date - today).days
                
                print(f"{site_name:<6} {info['dates']:<25} {info['book_on']:<15} {days_until} days")
            else:
                print(f"{site_name:<6} {'Not found in next 14 days':<25} {'-':<15} -")
        
        print("=" * 80)

if __name__ == "__main__":
    main()
