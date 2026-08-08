#!/usr/bin/env python3
"""Check site 1108 at Killbear for next 7-night booking window."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

SITE_URL = "https://reservations.ontarioparks.ca"
TARGET_NAME = "1108"
MIN_CONSECUTIVE = 7

PARK = {
    "name": "Killbear Provincial Park",
    "transactionLocationId": -2147483596,
    "resourceLocationId": -2147483600,
    "mapId": -2147483428,
}

# Check from now through end of season
DATE_RANGES = [
    ("2026-05-01", "2026-05-31"),
    ("2026-05-31", "2026-06-30"),
    ("2026-06-30", "2026-07-31"),
    ("2026-07-31", "2026-08-31"),
    ("2026-08-31", "2026-09-30"),
    ("2026-09-30", "2026-10-15"),
]


def build_url(map_id, start, end):
    nights = (datetime.strptime(end, "%Y-%m-%d") -
              datetime.strptime(start, "%Y-%m-%d")).days
    params = {
        "transactionLocationId": PARK["transactionLocationId"],
        "resourceLocationId": PARK["resourceLocationId"],
        "mapId": map_id,
        "searchTabGroupId": 0,
        "bookingCategoryId": 0,
        "startDate": start,
        "endDate": end,
        "nights": nights,
        "isReserving": "true",
        "equipmentId": -32768,
        "subEquipmentId": -32768,
        "peopleCapacityCategoryCounts": json.dumps([[-32768, None, 2, None]]),
        "searchTime": datetime.now(timezone.utc).isoformat(),
        "flexibleSearch": json.dumps([False, False, start[:8] + "01", 1]),
    }
    return f"{SITE_URL}/create-booking/results?{urlencode(params)}"


def find_consecutive_windows(days_dict, min_nights):
    """Find all consecutive available windows of at least min_nights."""
    sorted_dates = sorted(days_dict.keys())
    windows = []
    current_start = None
    current_len = 0

    for date_str in sorted_dates:
        if days_dict[date_str]["available"]:
            if current_start is None:
                current_start = date_str
                current_len = 1
            else:
                current_len += 1
        else:
            if current_start and current_len >= min_nights:
                windows.append({
                    "start": current_start,
                    "end": sorted_dates[sorted_dates.index(current_start) + current_len - 1],
                    "nights": current_len,
                })
            current_start = None
            current_len = 0

    # Handle trailing window
    if current_start and current_len >= min_nights:
        windows.append({
            "start": current_start,
            "end": sorted_dates[sorted_dates.index(current_start) + current_len - 1],
            "nights": current_len,
        })

    return windows


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
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
        page = context.new_page()

        # Establish session
        url = build_url(PARK["mapId"], "2026-07-01", "2026-07-05")
        print("Establishing session...", file=sys.stderr)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        # Find resourceId for site 1108
        print(f"Looking up resourceId for site {TARGET_NAME}...", file=sys.stderr)
        raw = page.evaluate("""async (locId) => {
            const resp = await fetch(`/api/resourcelocation/resources?resourceLocationId=${locId}`);
            return await resp.json();
        }""", PARK["resourceLocationId"])

        resource_id = None
        for key, val in raw.items():
            if val is None:
                continue
            localized = val.get("localizedValues", [])
            name = localized[0].get("name", key) if localized else key
            if name == TARGET_NAME:
                resource_id = val.get("resourceId", int(key))
                break

        if resource_id is None:
            print(f"ERROR: Site {TARGET_NAME} not found in Killbear!", file=sys.stderr)
            browser.close()
            sys.exit(1)

        print(f"Site {TARGET_NAME} -> resourceId {resource_id}", file=sys.stderr)

        # Check availability across the full season
        all_days = {}
        for start_str, end_str in DATE_RANGES:
            print(f"Checking {start_str} to {end_str}...", file=sys.stderr)
            try:
                avail = page.evaluate("""async ([resourceId, startDate, endDate]) => {
                    const resp = await fetch(
                        `/api/availability/resourcedailyavailability?resourceId=${resourceId}&startDate=${startDate}&endDate=${endDate}`
                    );
                    return await resp.json();
                }""", [resource_id, start_str, end_str])

                if isinstance(avail, list):
                    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
                    for i, day in enumerate(avail):
                        date = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
                        avail_val = day.get("availability")
                        if avail_val is None:
                            avail_val = -1
                        all_days[date] = {
                            "availability": avail_val,
                            "available": avail_val == 0,
                        }
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)
            time.sleep(0.3)

        browser.close()

        # Analysis
        sorted_dates = sorted(all_days.keys())
        avail_dates = [d for d in sorted_dates if all_days[d]["available"]]
        booked_dates = [d for d in sorted_dates if all_days[d]["availability"] == 1]

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"SITE {TARGET_NAME} — FULL SEASON AVAILABILITY", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"Total days checked: {len(all_days)}", file=sys.stderr)
        print(f"Booked: {len(booked_dates)}", file=sys.stderr)
        print(f"Available: {len(avail_dates)}", file=sys.stderr)

        # Show calendar view
        print(f"\nDay-by-day (. = booked, O = available, ? = other):", file=sys.stderr)
        current_month = None
        line = ""
        for d in sorted_dates:
            month = d[:7]
            if month != current_month:
                if line:
                    print(f"  {current_month}: {line}", file=sys.stderr)
                current_month = month
                line = ""
            if all_days[d]["available"]:
                line += "O"
            elif all_days[d]["availability"] == 1:
                line += "."
            else:
                line += "?"
        if line:
            print(f"  {current_month}: {line}", file=sys.stderr)

        # Find 7+ night windows
        windows = find_consecutive_windows(all_days, MIN_CONSECUTIVE)

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"7+ NIGHT BOOKING WINDOWS:", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        if windows:
            for w in windows:
                print(f"  Check-in {w['start']} → Check-out {w['end']} ({w['nights']} nights available)", file=sys.stderr)
            print(f"\n  NEXT OPPORTUNITY: Check-in {windows[0]['start']}, up to {windows[0]['nights']} nights", file=sys.stderr)
        else:
            print("  No 7+ consecutive night windows found!", file=sys.stderr)

        # JSON output
        output = {
            "site": TARGET_NAME,
            "resourceId": resource_id,
            "total_days": len(all_days),
            "available_days": len(avail_dates),
            "booked_days": len(booked_dates),
            "seven_night_windows": windows,
            "all_available_dates": avail_dates,
        }
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
