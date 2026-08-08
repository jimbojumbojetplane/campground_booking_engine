#!/usr/bin/env python3
"""
Check availability for target sites 1418, 1422, 1030, 1118 at Killbear.
Fixes: uses resourceId mapping, positional dates, proper falsy handling.
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

SITE_URL = "https://reservations.ontarioparks.ca"
TARGET_SITES = ["1418", "1422", "1030", "1118"]

PARK = {
    "name": "Killbear Provincial Park",
    "transactionLocationId": -2147483596,
    "resourceLocationId": -2147483600,
    "mapId": -2147483428,
}

# Weekly windows across summer 2026
DATE_RANGES = [
    ("2026-06-26", "2026-07-03"),
    ("2026-07-03", "2026-07-10"),
    ("2026-07-10", "2026-07-17"),
    ("2026-07-17", "2026-07-24"),
    ("2026-07-24", "2026-07-31"),
    ("2026-07-31", "2026-08-07"),
    ("2026-08-07", "2026-08-14"),
    ("2026-08-14", "2026-08-21"),
    ("2026-08-21", "2026-08-28"),
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

        # Map site names to resourceIds
        print("Mapping site names to resourceIds...", file=sys.stderr)
        raw = page.evaluate("""async (locId) => {
            const resp = await fetch(`/api/resourcelocation/resources?resourceLocationId=${locId}`);
            return await resp.json();
        }""", PARK["resourceLocationId"])

        site_map = {}
        for key, val in raw.items():
            if val is None:
                continue
            localized = val.get("localizedValues", [])
            name = localized[0].get("name", key) if localized else key
            if name in TARGET_SITES:
                site_map[name] = val.get("resourceId", int(key))

        print(f"Mapped {len(site_map)} target sites:", file=sys.stderr)
        for name, rid in sorted(site_map.items()):
            print(f"  Site {name} -> resourceId {rid}", file=sys.stderr)

        # Check availability across all date ranges
        results = {}
        for site_name in TARGET_SITES:
            if site_name not in site_map:
                print(f"\nSite {site_name}: NOT FOUND", file=sys.stderr)
                continue

            resource_id = site_map[site_name]
            results[site_name] = {
                "resourceId": resource_id,
                "days": {},
            }

            print(f"\nSite {site_name} (resourceId={resource_id}):", file=sys.stderr)

            for start_str, end_str in DATE_RANGES:
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

                            # IMPORTANT: use None check, not truthiness.
                            # availability=0 means AVAILABLE but is falsy in Python.
                            avail_val = day.get("availability")
                            if avail_val is None:
                                avail_val = day.get("availabilityType")
                            if avail_val is None:
                                avail_val = -1  # unknown

                            is_avail = avail_val == 0
                            results[site_name]["days"][date] = {
                                "availability": avail_val,
                                "available": is_avail,
                            }

                            marker = "  <-- AVAILABLE!" if is_avail else ""
                            print(f"  {date}: availability={avail_val}{marker}", file=sys.stderr)

                except Exception as e:
                    print(f"  {start_str}-{end_str}: Error: {e}", file=sys.stderr)

                time.sleep(0.3)

        # Summary
        print(f"\n{'='*70}", file=sys.stderr)
        print("AVAILABILITY SUMMARY (June 26 - August 28, 2026)", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)

        for site_name in TARGET_SITES:
            if site_name not in results:
                print(f"\n  Site {site_name}: NOT FOUND", file=sys.stderr)
                continue

            days = results[site_name]["days"]
            avail_dates = sorted([d for d, v in days.items() if v["available"]])
            booked_dates = sorted([d for d, v in days.items() if v["availability"] == 1])
            other_dates = sorted([d for d, v in days.items()
                                  if not v["available"] and v["availability"] != 1])
            total = len(days)

            print(f"\n  Site {site_name} (resourceId={results[site_name]['resourceId']}):", file=sys.stderr)
            print(f"    Total days checked: {total}", file=sys.stderr)
            print(f"    Booked (type=1): {len(booked_dates)}", file=sys.stderr)
            print(f"    Available (type=0): {len(avail_dates)}", file=sys.stderr)
            print(f"    Other status: {len(other_dates)}", file=sys.stderr)

            if avail_dates:
                print(f"    Available dates:", file=sys.stderr)
                for d in avail_dates:
                    print(f"      {d}", file=sys.stderr)

            if other_dates:
                # Show what other statuses exist
                other_types = set(days[d]["availability"] for d in other_dates)
                print(f"    Other availability types seen: {other_types}", file=sys.stderr)
                print(f"    Dates with other status:", file=sys.stderr)
                for d in other_dates[:10]:
                    print(f"      {d}: type={days[d]['availability']}", file=sys.stderr)
                if len(other_dates) > 10:
                    print(f"      ... and {len(other_dates) - 10} more", file=sys.stderr)

        # Full JSON output
        print(json.dumps(results, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
