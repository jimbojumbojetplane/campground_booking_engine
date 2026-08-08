#!/usr/bin/env python3
"""Extract the full site → campground → mapId mapping for Killbear."""

import json
import sys
from playwright.sync_api import sync_playwright

# Skip non-campsite maps (lodge, bear boxes, bus permits, day use)
SKIP_MAPS = {"Lodge", "Other", "Killbear", "Day Use Facility"}

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()

        url = (
            "https://reservations.ontarioparks.ca/create-booking/results?"
            "transactionLocationId=-2147483596&resourceLocationId=-2147483600"
            "&mapId=-2147483428&startDate=2026-07-26&endDate=2026-07-27"
        )
        page.goto(url, timeout=30000)
        page.wait_for_timeout(5000)

        maps_data = page.evaluate("""() => {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "/api/maps?resourceLocationId=-2147483600", false);
            xhr.send();
            return JSON.parse(xhr.responseText);
        }""")

        resources_data = page.evaluate("""() => {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "/api/resourcelocation/resources?resourceLocationId=-2147483600", false);
            xhr.send();
            return JSON.parse(xhr.responseText);
        }""")

        browser.close()

    output = {}
    for m in maps_data:
        lv = m.get("localizedValues", [{}])
        campground = lv[0].get("title", "") if lv else ""
        if campground in SKIP_MAPS or not campground:
            continue
        for r in m.get("mapResources", []):
            rid = r["resourceId"]
            res = resources_data.get(str(rid), {})
            lv = res.get("localizedValues", [{}])
            name = lv[0].get("name", str(rid)) if lv else str(rid)
            output[name] = {
                "resourceId": rid,
                "campground": campground,
                "mapId": m["mapId"],
            }

    # Sort by site number
    sorted_output = dict(
        sorted(output.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)
    )

    print(json.dumps(sorted_output, indent=2))


if __name__ == "__main__":
    main()
