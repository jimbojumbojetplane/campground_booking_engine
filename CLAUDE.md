# CLAUDE.md — Campground Booking Engine

## Project Overview

Tools for checking campsite availability on Ontario Parks (reservations.ontarioparks.ca). The Ontario Parks reservation system does not offer a public API — these scripts work by calling internal endpoints discovered via browser network inspection.

## Repository Structure

```
campground_booking_engine/
├── CLAUDE.md                                  # This file — project context for AI assistants
├── discover_site.py                           # Step 1: discover park/campground/site IDs → JSON
├── site_structure.json                        # Cached IDs (created by discover_site.py, gitignored)
├── check_availability_playwright.py           # Step 2: check availability using cached IDs
├── check_availability.py                      # Legacy: direct HTTP (may be blocked by WAF)
├── check_availability_browser.js              # Browser console script (paste into DevTools)
├── discover_site_structure_navigation.md      # Reusable methodology for reverse-engineering sites
└── requirements.txt                           # Python dependencies
```

## How to Run

### Python CLI (`check_availability.py`)

```bash
pip install -r requirements.txt

# List all parks:
python check_availability.py --list-parks

# List campgrounds in a park:
python check_availability.py --park "Killbear" --list-campgrounds

# Check a specific site:
python check_availability.py --park "Killbear" --campground "Lighthouse Point B" \
    --site 1422 --start 2026-07-01 --end 2026-07-05

# Find all available sites in a campground:
python check_availability.py --park "Killbear" --campground "Lighthouse Point B" \
    --start 2026-07-01 --end 2026-07-05
```

### Recommended: Two-Step Workflow (Playwright)

**Step 1: Discover IDs** (run once, saves to `site_structure.json`):

```bash
pip install -r requirements.txt
playwright install chromium

# Discover all parks:
python discover_site.py

# Discover campgrounds + site IDs for Killbear:
python discover_site.py --park "Killbear" --include-sites

# Discover everything for all parks (slow):
python discover_site.py --all --include-sites
```

**Step 2: Check availability** (uses cached IDs, fast):

```bash
# Check all sites in a campground:
python check_availability_playwright.py --park "Killbear" \
    --campground "Lighthouse Point B" --start 2026-07-19 --end 2026-08-01

# Check a specific site:
python check_availability_playwright.py --park "Killbear" \
    --campground "Lighthouse Point B" --site 1422 \
    --start 2026-07-19 --end 2026-08-01

# List cached parks/campgrounds:
python check_availability_playwright.py --list-parks
python check_availability_playwright.py --park "Killbear" --list-campgrounds

# Run headed for debugging:
python check_availability_playwright.py --headed --park "Killbear" \
    --campground "Lighthouse Point B" --start 2026-07-19 --end 2026-08-01
```

### Browser Console Script (`check_availability_browser.js`)

1. Navigate to reservations.ontarioparks.ca
2. Search for your park/campground with desired dates
3. Get to the campground MAP view
4. Open browser DevTools (F12) → Console tab
5. Paste the script and press Enter

## Key Technical Details

### Ontario Parks API Endpoints (Undocumented)

These are internal endpoints — they may change without notice:

- `GET /api/resourcelocation/rootmaps` — List all parks
- `GET /api/resourcelocation/resources?resourceLocationId={id}` — List sites in a campground
- `GET /api/attribute/filterable` — Site attribute definitions
- `GET /api/availability/resourcestatus?resourceId={id}&startDate={date}&endDate={date}` — Check single site availability (availabilityType == 0 means available)
- `GET /api/availability/resourcedailyavailability?resourceId={id}&startDate={date}&endDate={date}` — Day-by-day availability
- `POST /api/availability/map` — Map-based availability data

### Site Architecture

The site is a **Single Page Application (SPA)** powered by **Camis Inc.**
(Canadian company, acquired by Banyan Software). The frontend is **Angular** with a
**.NET/C#** backend and **SQL Server** database. The same platform powers Parks Canada.

All booking views share the route `/create-booking/results` — map,
list, and calendar views are client-side toggles with the same URL. Availability data
is loaded via JS `fetch()` calls after page load, not server-rendered in HTML.

The site returns **403 to direct HTTP requests** — it requires JavaScript execution
to obtain a session cookie. There is no CAPTCHA, no commercial WAF (Cloudflare/Akamai),
and no Queue-it waiting room (unlike Parks Canada which uses the same Camis platform).
Once a browser bootstraps the page, API calls work freely.

### ID Hierarchy

IDs use large negative 32-bit integers. The navigation hierarchy is:

```
transactionLocationId   (park billing entity, e.g. -2147483596 for Killbear)
└─ resourceLocationId   (park resource root, e.g. -2147483600 for Killbear)
   └─ mapId             (park-level map, e.g. -2147483428 — shows campground areas)
      └─ mapId          (campground map, e.g. -2147483419 — Lighthouse Point B)
         └─ site IDs    (individual campsites, e.g. "1422")
```

### URL Structure

Full booking results URL with all parameters:
```
https://reservations.ontarioparks.ca/create-booking/results?
  transactionLocationId={id}
  &resourceLocationId={id}
  &mapId={id}                          # changes when drilling into campgrounds
  &searchTabGroupId=0
  &bookingCategoryId=0                 # 0 = camping
  &startDate=YYYY-MM-DD
  &endDate=YYYY-MM-DD
  &nights={n}
  &isReserving=true
  &equipmentId=-32768                  # -32768 = tent
  &subEquipmentId=-32768               # -32768 = single tent
  &peopleCapacityCategoryCounts=[[-32768,null,{partySize},null]]
  &searchTime={ISO timestamp}
  &flexibleSearch=[false,false,"YYYY-MM-01",1]
  &filterData={...}                    # attribute filters, added when drilling down
```

### Known Limitations

- The API is not officially public and may block requests or change endpoints at any time.
- Direct HTTP requests return 403 — browser automation (Playwright) or the browser console script are required.
- Browser console script works within the site's origin, avoiding CORS/cookie issues.
- Rate limiting may apply — avoid hammering the API.
- Parks Canada (same Camis platform) uses Queue-it waiting rooms; Ontario Parks does not currently, but this could change.

## Dependencies

- Python 3.7+
- `requests` library (for `check_availability.py`)
- `playwright` library + Chromium (for `check_availability_playwright.py`)

## Development Guidelines for AI Assistants

### General Principles
- Read existing code before modifying it.
- Keep changes minimal and focused on what was requested.
- Do not add features or "improvements" beyond what was asked.

### Git Workflow
- Use clear, descriptive commit messages.
- Do not push to `main` or `master` without explicit permission.
- Work on feature branches as directed.

### Code Quality
- Follow existing conventions in the codebase.
- Do not introduce security vulnerabilities.
- Avoid storing credentials or API keys in source files.
