# Discovering Website Structure for Smart Navigation & Data Extraction

A reusable methodology for reverse-engineering any web application's architecture,
navigation model, ID system, and API surface — to build automated data extraction
scripts.

---

## Phase 1: Passive Reconnaissance

### 1.1 Technology Stack Identification

Before touching the site, identify what you're dealing with.

**Tools:**
- BuiltWith (builtwith.com) or Wappalyzer browser extension
- Browser DevTools → Sources tab (look at JS bundle names)
- `curl -sI <url>` to inspect response headers (`X-Powered-By`, `Server`, etc.)

**What to identify:**

| Layer | Look For | Why It Matters |
|-------|----------|---------------|
| Frontend framework | Angular, React, Vue, Next.js, Nuxt | Determines how routing/state works |
| Backend framework | .NET, Django, Rails, Express, Spring | Predicts API patterns |
| CSS framework | Bootstrap, Tailwind, Material | Helps with DOM selectors |
| CDN/WAF | Cloudflare, Akamai, AWS CloudFront | Determines bot-detection difficulty |
| Anti-bot | reCAPTCHA, hCaptcha, Datadome, PerimeterX | May require browser automation |
| Auth | JWT, session cookies, OAuth | Affects how to maintain sessions |

**Framework detection shortcuts:**
```
Angular:    <app-root>, ng-version attribute, zone.js in network, /assets/
React:      <div id="root">, __REACT_DEVTOOLS, _reactRootContainer, .chunk.js
Vue:        <div id="app">, __vue__, .vue files in sources
Next.js:    __NEXT_DATA__ script tag, /_next/ paths
Nuxt:       __NUXT__, /_nuxt/ paths
```

### 1.2 URL Structure Analysis

Navigate the site manually and record every URL transition. This is the single most
valuable step.

**Record this table for every page transition:**

| Step | Action | URL | What Changed | New Parameters |
|------|--------|-----|-------------|----------------|
| 1 | Landed on home | /home | — | — |
| 2 | Selected category | /results?catId=5 | Route changed | catId added |
| 3 | Drilled into item | /results?catId=5&itemId=99 | Same route | itemId added |
| 4 | Changed view | /results?catId=5&itemId=99 | Nothing! | Client-side only |

**Key questions to answer:**
- Does the route change, or only the query parameters? (SPA vs MPA)
- Which parameters are added/changed at each navigation step?
- Which parameters stay constant throughout? (session/context IDs)
- Are there parameters that are derived (e.g., `nights = endDate - startDate`)?
- What format are IDs in? (integers, UUIDs, slugs, negative ints, etc.)

### 1.3 ID Hierarchy Mapping

Most data-driven sites have a tree of entity IDs. Map it:

```
Root Entity (e.g., Organization)
└─ Category (e.g., Region/Park)
   └─ Sub-category (e.g., Campground/Section)
      └─ Leaf item (e.g., Site/Product/Room)
```

For each level, record:
- The parameter name that holds the ID (e.g., `resourceLocationId`, `mapId`)
- Which API endpoint returns the children at the next level
- Whether the ID is in the URL, a cookie, or a JS variable

---

## Phase 2: Active Network Inspection

### 2.1 Intercept API Calls

Open DevTools → Network tab → filter by `Fetch/XHR`. Navigate through the site and
record every API call.

**For each API call, document:**

```
Endpoint:    GET /api/resources?parentId={id}
Trigger:     Page load / User click on "X" / Scroll to bottom
Request:     Headers (auth tokens?), Query params, Body (if POST)
Response:    JSON structure, Key fields, Pagination format
Depends on:  Must have {parentId} from previous /api/parents call
```

**Build an API dependency graph:**

```
/api/parks              → returns [{id, name, mapId, ...}]
  ↓ uses park.id
/api/campgrounds?parkId → returns [{id, name, mapId, ...}]
  ↓ uses campground.mapId
/api/sites?mapId        → returns [{id, name, attributes, ...}]
  ↓ uses site.id
/api/availability?siteId&startDate&endDate → returns {status}
```

### 2.2 Identify the "Bootstrap" Calls

When the SPA first loads, it makes initialization calls. These are gold — they often
return bulk data (all parks, all categories, config, feature flags).

**Common bootstrap patterns:**
- `/api/config` or `/api/init` — site-wide configuration
- `/api/resources/root` or `/api/locations/all` — top-level entity list
- `/api/attributes` or `/api/filters` — filter/facet definitions
- A large JSON blob in a `<script>` tag (e.g., `window.__INITIAL_STATE__`)

### 2.3 POST Body Analysis

For POST endpoints (especially map/search), capture the request body:

```json
{
  "mapId": -2147483419,
  "bookingCategoryId": 0,
  "startDate": "2026-07-26",
  "endDate": "2026-08-01",
  "getDailyAvailability": false,
  "isReserving": true,
  "filterData": {},
  "bopiPartySize": 2
}
```

Note which fields are required vs optional. Try removing fields one at a time to find
the minimal request.

---

## Phase 3: Browser Automation Strategy

### 3.1 Choose Your Approach

| Approach | When to Use | Pros | Cons |
|----------|-------------|------|------|
| **Direct HTTP** (requests/httpx) | No JS challenge, no cookies needed | Fast, low resource | Blocked by WAF/SPA |
| **Headless browser** (Playwright) | JS challenge, cookies, SPA rendering | Bypasses all protections | Slower, needs Chromium |
| **Hybrid**: browser bootstraps, then HTTP | Initial cookie gate, then clean API | Fast after bootstrap | More complex |
| **Browser extension** | Need to run within user's session | Full access, no CORS | Manual, not scriptable |

### 3.2 Playwright Network Interception Pattern

This is the most reliable pattern for SPAs. The browser handles all auth/cookies/JS
challenges, and you simply listen to the API responses.

```python
from playwright.sync_api import sync_playwright

class ApiCapture:
    def __init__(self):
        self.responses = {}

    def handle_response(self, response):
        if "/api/" in response.url and response.status == 200:
            try:
                self.responses[response.url] = response.json()
            except:
                pass

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context()
    capture = ApiCapture()
    page = context.new_page()
    page.on("response", capture.handle_response)

    # Navigate — the SPA will make API calls, we capture them all
    page.goto("https://example.com/search?category=5")
    page.wait_for_timeout(5000)

    # Now capture.responses has all the API data
    for url, data in capture.responses.items():
        print(f"{url}: {len(str(data))} bytes")
```

### 3.3 In-Page JavaScript Execution

Once the browser has a valid session, you can make API calls directly from within the
page context — no CORS, no cookie issues:

```python
result = page.evaluate("""async ([endpoint, params]) => {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const resp = await fetch(url);
    return await resp.json();
}""", ["/api/availability/status", {"resourceId": "123", "startDate": "2026-07-01"}])
```

This is the **most powerful technique** — it runs fetch() from the site's own origin
with the site's own cookies and headers. It's exactly what the browser console scripts
do, but automated.

### 3.4 Cookie/Session Extraction for Hybrid Approach

If you want speed after the initial browser bootstrap:

```python
# After browser loads the page and passes any JS challenges:
cookies = context.cookies()
# Transfer cookies to a requests session:
import requests
session = requests.Session()
for cookie in cookies:
    session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"])
# Now use session for fast direct HTTP calls
resp = session.get("https://example.com/api/data")
```

---

## Phase 4: Full Hierarchy Extraction

### 4.1 Recursive Discovery Pattern

For tree-structured data (parks → campgrounds → sites), use a breadth-first crawl:

```python
def discover_hierarchy(page):
    """Discover the full entity hierarchy via API interception."""

    # Level 0: Get all root entities
    roots = page.evaluate("() => fetch('/api/roots').then(r => r.json())")

    hierarchy = {}
    for root in roots:
        hierarchy[root["id"]] = {
            "name": root["name"],
            "meta": root,
            "children": {}
        }

        # Level 1: Get children for each root
        children = page.evaluate(
            "([id]) => fetch(`/api/children?parentId=${id}`).then(r => r.json())",
            [root["id"]]
        )

        for child in children:
            hierarchy[root["id"]]["children"][child["id"]] = {
                "name": child["name"],
                "meta": child,
                "children": {}  # Level 2 if needed
            }

    return hierarchy
```

### 4.2 Output: Site Structure JSON

Save the discovered hierarchy as a structured JSON file for reuse:

```json
{
  "discovered_at": "2026-02-20T12:00:00Z",
  "site_url": "https://example.com",
  "hierarchy": {
    "-2147483600": {
      "name": "Killbear Provincial Park",
      "transactionLocationId": -2147483596,
      "resourceLocationId": -2147483600,
      "mapId": -2147483428,
      "campgrounds": {
        "-2147483419": {
          "name": "Lighthouse Point B",
          "mapId": -2147483419,
          "sites": {
            "1422": {"name": "1422"},
            "1423": {"name": "1423"}
          }
        }
      }
    }
  }
}
```

### 4.3 Rate Limiting and Politeness

When crawling all entities:

```python
import time
import random

def polite_delay(min_seconds=0.5, max_seconds=1.5):
    """Random delay to avoid hammering the server."""
    time.sleep(random.uniform(min_seconds, max_seconds))
```

Rules:
- Add random delays between API calls (0.5–1.5 seconds)
- Don't parallelize aggressively — 1 request at a time for discovery
- Cache aggressively — park/campground IDs rarely change
- Run discovery once, store results, reuse for availability checks

---

## Phase 5: Building the Navigation Script

### 5.1 Two-Script Architecture

**Script 1: Discovery (run once/rarely)**
- Launches browser
- Navigates site hierarchy
- Extracts all entity IDs
- Saves to `site_structure.json`

**Script 2: Data extraction (run frequently)**
- Loads `site_structure.json`
- Launches browser, navigates directly to target entities using known IDs
- Extracts the dynamic data (availability, prices, etc.)
- No discovery overhead

### 5.2 Direct URL Construction

Once you have IDs, skip all UI navigation. Construct URLs directly:

```python
def build_url(ids, params):
    """Construct a direct URL to any page using known IDs."""
    base = "https://example.com/results"
    query = urlencode({**ids, **params})
    return f"{base}?{query}"

# Jump straight to Lighthouse Point B with dates:
url = build_url(
    ids={"locationId": -2147483600, "mapId": -2147483419},
    params={"startDate": "2026-07-26", "endDate": "2026-08-01"}
)
```

### 5.3 page.evaluate() for Bulk Data Extraction

The fastest approach for checking many items: run JavaScript directly in the page
context in a loop:

```python
results = page.evaluate("""async (siteIds, startDate, endDate) => {
    const results = {};
    for (const id of siteIds) {
        try {
            const resp = await fetch(
                `/api/availability?resourceId=${id}&startDate=${startDate}&endDate=${endDate}`
            );
            results[id] = await resp.json();
        } catch (e) {
            results[id] = {error: e.message};
        }
        // Small delay to be polite
        await new Promise(r => setTimeout(r, 200));
    }
    return results;
}""", [site_ids, "2026-07-26", "2026-08-01"])
```

This runs all requests from within the browser — no CORS, no extra sessions, no
cookie management.

---

## Appendix: Checklist

Use this checklist for any new site:

- [ ] **Identify the tech stack** (framework, backend, WAF)
- [ ] **Map all URL transitions** (record parameter changes at each step)
- [ ] **Map the ID hierarchy** (root → category → subcategory → leaf)
- [ ] **Capture all API endpoints** (DevTools Network tab during full navigation)
- [ ] **Build the API dependency graph** (which call needs data from which prior call)
- [ ] **Identify bootstrap calls** (bulk data loaded on first page load)
- [ ] **Test direct HTTP** (does `curl` or `requests` work, or do you need a browser?)
- [ ] **Choose automation approach** (direct HTTP, headless browser, or hybrid)
- [ ] **Build discovery script** (extract all IDs, save to JSON)
- [ ] **Build extraction script** (use cached IDs, direct URL construction, page.evaluate)
- [ ] **Add rate limiting** (random delays, single-threaded discovery)
- [ ] **Test headed first** (use `--headed` flag to watch and debug)

---

## Appendix: Common SPA Patterns

### Angular SPAs
- Routes defined in `app-routing.module.ts`
- API calls typically via `HttpClient` in services
- State often in NgRx store — look for `/ngrx/` in bundles
- Interceptors handle auth headers automatically

### React SPAs
- Look for React Router (`/react-router/` in bundles)
- State in Redux, Zustand, or React Query
- API calls via axios or fetch in hooks/effects
- `__NEXT_DATA__` script tag if Next.js (contains pre-fetched data)

### .NET + Angular (e.g., Camis / Ontario Parks pattern)
- API routes follow `/api/{controller}/{action}` convention
- IDs often use C# `int` (32-bit signed, explains negative IDs)
- Endpoints return `camelCase` JSON by default
- Look for `/api/resourcelocation/`, `/api/availability/` patterns
