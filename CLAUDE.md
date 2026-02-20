# CLAUDE.md — Campground Booking Engine

## Project Overview

Tools for checking campsite availability on Ontario Parks (reservations.ontarioparks.ca). The Ontario Parks reservation system does not offer a public API — these scripts work by calling internal endpoints discovered via browser network inspection.

## Repository Structure

```
campground_booking_engine/
├── CLAUDE.md                       # This file — project context for AI assistants
├── check_availability.py           # Python CLI tool for availability checking
├── check_availability_browser.js   # Browser console script (paste into DevTools)
└── requirements.txt                # Python dependencies
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

### ID Format

Park and campground IDs use large negative integers (e.g., `-2147483467`). These appear to be based on 32-bit integer ranges.

### URL Structure

Direct booking URLs follow this pattern:
```
https://reservations.ontarioparks.ca/create-booking/results?resourceLocationId={id}&mapId={id}&bookingCategoryId={id}&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&isReserving=true&partySize=1
```

### Known Limitations

- The API is not officially public and may block requests or change endpoints at any time.
- Browser console script works within the site's origin, avoiding CORS issues.
- Python script requires browser-like User-Agent headers to work.
- Rate limiting may apply — avoid hammering the API.

## Dependencies

- Python 3.7+
- `requests` library

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
