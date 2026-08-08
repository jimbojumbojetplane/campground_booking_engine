#!/usr/bin/env python3
"""List all sites at Killbear with their name and resourceId."""
import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

SITE_URL = "https://reservations.ontarioparks.ca"
PARK = {
    "transactionLocationId": -2147483596,
    "resourceLocationId": -2147483600,
    "mapId": -2147483428,
}


def build_url():
    params = {
        "transactionLocationId": PARK["transactionLocationId"],
        "resourceLocationId": PARK["resourceLocationId"],
        "mapId": PARK["mapId"],
        "searchTabGroupId": 0,
        "bookingCategoryId": 0,
        "startDate": "2026-07-01",
        "endDate": "2026-07-02",
        "nights": 1,
        "isReserving": "true",
        "equipmentId": -32768,
        "subEquipmentId": -32768,
        "peopleCapacityCategoryCounts": json.dumps([[-32768, None, 2, None]]),
        "searchTime": datetime.now(timezone.utc).isoformat(),
        "flexibleSearch": json.dumps([False, False, "2026-07-01", 1]),
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

        print("Establishing session...", file=sys.stderr)
        page.goto(build_url(), timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        print("Fetching all sites...", file=sys.stderr)
        raw = page.evaluate("""async (locId) => {
            const resp = await fetch(`/api/resourcelocation/resources?resourceLocationId=${locId}`);
            return await resp.json();
        }""", PARK["resourceLocationId"])

        sites = []
        for key, val in raw.items():
            if val is None:
                continue
            localized = val.get("localizedValues", [])
            name = localized[0].get("name", key) if localized else key
            sites.append({
                "site_name": name,
                "resourceId": val.get("resourceId", int(key)),
            })

        # Sort by site name (numeric sort where possible)
        def sort_key(s):
            try:
                return (0, int(s["site_name"]))
            except ValueError:
                return (1, s["site_name"])

        sites.sort(key=sort_key)
        browser.close()

        print(f"\nFound {len(sites)} sites at Killbear Provincial Park\n", file=sys.stderr)
        print(f"{'Site Name':<20} {'resourceId':<20}")
        print("-" * 40)
        for s in sites:
            print(f"{s['site_name']:<20} {s['resourceId']:<20}")

        # Also save as JSON
        with open("killbear_sites.json", "w") as f:
            json.dump(sites, f, indent=2)
        print(f"\nSaved to killbear_sites.json", file=sys.stderr)


if __name__ == "__main__":
    main()
