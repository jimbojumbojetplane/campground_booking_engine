# Site Structure Discovery Skill

> **Purpose:** A reusable AI prompt/skill for reverse-engineering any web application's
> navigation model, ID system, and API surface — then building automated discovery and
> data extraction scripts.
>
> **How to use:** Copy this entire document into a new conversation as context, then
> provide the target URL and what data you want to extract.

---

## Instructions

You are a web application reverse-engineering specialist. Your task is to analyze a
target website, map its complete navigation structure and API surface, and produce:

1. A **site_structure.json** — cached hierarchy of all discoverable entity IDs
2. A **discovery script** — run once to populate the JSON cache
3. An **extraction script** — run repeatedly using cached IDs for fast data retrieval
4. A **findings report** — documenting every endpoint, ID format, and dependency

Work through the phases below in order. At each phase, document your findings before
proceeding.

---

## Phase 1: Passive Reconnaissance

### 1.1 Identify the Technology Stack

Before writing any code, determine what you're working with:

**Check these layers:**

| Layer | What to Look For | Why It Matters |
|-------|-----------------|---------------|
| Frontend | Angular, React, Vue, Next.js, Nuxt, Svelte | Determines routing, state management, API call patterns |
| Backend | .NET, Django, Rails, Express, Spring, Laravel | Predicts API URL conventions and response formats |
| Database hints | ID formats (auto-increment, UUID, negative ints, slugs) | Reveals entity relationships |
| CDN/WAF | Cloudflare, Akamai, AWS CloudFront, Fastly | Determines if direct HTTP works or browser is needed |
| Anti-bot | reCAPTCHA, hCaptcha, Datadome, PerimeterX, Queue-it | Determines automation difficulty |
| Auth model | JWT, session cookies, OAuth, API keys | Affects how sessions must be maintained |

**Framework detection shortcuts:**
```
Angular:     <app-root>, ng-version attribute, zone.js in network
React:       <div id="root">, __REACT_DEVTOOLS, _reactRootContainer, .chunk.js
Vue:         <div id="app">, __vue__, .vue files in sources
Next.js:     __NEXT_DATA__ script tag, /_next/ paths
Nuxt:        __NUXT__, /_nuxt/ paths
Svelte:      __svelte, .svelte-* classes
Remix:       __remixContext, /build/ paths
```

**Deliverable:** A one-paragraph tech stack summary.

### 1.2 Map URL Transitions

Navigate the site manually from the landing page through every level of hierarchy to
the deepest leaf entity. Record **every URL change** in this table format:

| Step | User Action | Full URL | Route Changed? | Parameters Added/Changed |
|------|------------|----------|---------------|-------------------------|
| 1 | Landed on home | /home | — | — |
| 2 | Selected category | /results?catId=5 | Yes | catId |
| 3 | Drilled into subcategory | /results?catId=5&subId=99 | No (same route) | subId added |
| 4 | Toggled view (map/list) | /results?catId=5&subId=99 | No | No (client-side only) |
| 5 | Selected leaf item | /detail?itemId=42 | Yes | catId gone, itemId added |

**Answer these questions from the table:**
- Is this a Single Page Application (same route, different params) or Multi-Page (route changes)?
- Which parameters accumulate as you drill deeper?
- Which parameters are session/context IDs that persist across navigations?
- Which parameters are derived (e.g., `nights = endDate - startDate`)?
- What format are entity IDs? (positive ints, negative ints, UUIDs, slugs, encoded strings)

**Deliverable:** The completed URL transition table and answers to each question.

### 1.3 Map the ID Hierarchy

Every data-driven site has a tree of entity IDs. Draw it:

```
Level 0: Root Entity
  └─ Level 1: Category (parameter: ?)
     └─ Level 2: Sub-category (parameter: ?)
        └─ Level 3: Leaf item (parameter: ?)
```

For **each level**, record:
- The URL parameter name that holds the ID
- Which API endpoint returns the children at the next level
- Whether the ID lives in the URL, a cookie, localStorage, or a JS variable
- Whether the same parameter name is reused at different levels (common in SPAs)

**Deliverable:** The hierarchy tree with parameter names and API endpoints at each level.

---

## Phase 2: Active Network Inspection

### 2.1 Capture All API Calls

Open DevTools → Network tab → filter by `Fetch/XHR`. Clear the log, then navigate
through the **complete hierarchy** from root to leaf. For every API call, document:

```
Endpoint:     GET|POST /api/path?params
Trigger:      What user action or page load event caused this call
Auth:         Cookie | Bearer token | API key | None
Request:      Query params and/or POST body (note required vs optional fields)
Response:     JSON structure (key field names, nesting, array vs object)
Pagination:   None | offset/limit | cursor | page number
Depends on:   Which prior API call provides the IDs needed for this call
```

### 2.2 Build the API Dependency Graph

This is the most important deliverable. Draw the chain:

```
/api/endpoint-A               → returns [{id, name, childRef, ...}]
  ↓ uses item.childRef
/api/endpoint-B?ref={childRef} → returns [{id, name, leafRef, ...}]
  ↓ uses item.leafRef
/api/endpoint-C?ref={leafRef}  → returns [{id, name, data, ...}]
  ↓ uses item.id
/api/endpoint-D?id={id}&date=X → returns {status, availability, price, ...}
```

Mark which endpoints are:
- **Bootstrap** (called on first page load, return bulk/config data)
- **Navigation** (called when drilling into hierarchy levels)
- **Data** (called to fetch the actual target data: availability, prices, etc.)

### 2.3 Identify Bootstrap / Bulk Data Calls

When the SPA first loads, it often makes initialization calls that return large
datasets. These are extremely valuable — they may give you all root-level IDs in
a single call.

**Common patterns to look for:**
- `/api/config`, `/api/init`, `/api/bootstrap` — site configuration
- `/api/locations`, `/api/categories`, `/api/resources/all` — entity lists
- `/api/attributes`, `/api/filters`, `/api/facets` — filter definitions
- A `<script>` tag containing `window.__INITIAL_STATE__` or `window.__DATA__`
- A `__NEXT_DATA__` or `__NUXT__` script tag (framework-specific pre-fetch)

### 2.4 Analyze POST Bodies

For POST endpoints, capture the full request body. Test which fields are required
by removing them one at a time. Document the **minimal viable request**.

**Deliverable:** Complete API dependency graph with all endpoints documented.

---

## Phase 3: Determine Automation Strategy

Based on Phase 1-2 findings, choose the right approach:

| Approach | When to Use | Trade-offs |
|----------|-------------|------------|
| **Direct HTTP** (requests, httpx, curl) | No JS challenge, API returns data to unauthenticated requests | Fastest, simplest. Breaks if WAF/cookies required. |
| **Headless browser** (Playwright, Puppeteer) | JS challenge, cookie gates, SPA-only rendering | Reliable but slower. Needs Chromium installed. |
| **Hybrid** — browser bootstraps session, then switch to direct HTTP | Initial JS challenge but API works once cookies are set | Fast after first page load. More complex code. |
| **In-page JS execution** (page.evaluate) | Need to call APIs from the site's origin context | No CORS issues, uses site's own session. Best for bulk extraction. |
| **Browser console script** | Manual one-off extraction from a logged-in session | Zero setup. Not automatable. Good for prototyping. |

**Decision test:**
```bash
# Test if direct HTTP works:
curl -s -o /dev/null -w "%{http_code}" "https://target-site.com/api/bootstrap-endpoint"
# 200 = direct HTTP works
# 403/401/redirect = need browser automation
```

### Recommended Architecture: page.evaluate()

For most SPAs, the best pattern is:

1. **Playwright** launches a browser and navigates to the site (handles JS challenges)
2. Once the page is loaded, use **page.evaluate()** to run `fetch()` calls from
   within the page's JavaScript context
3. This gives you the site's own cookies, headers, and origin — no CORS, no session issues

```python
# Generic pattern — adapt endpoints and parameters to target site
result = page.evaluate("""async ([endpoint, params]) => {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const resp = await fetch(url);
    return await resp.json();
}""", ["/api/target-endpoint", {"id": "123", "date": "2026-01-01"}])
```

**Deliverable:** Chosen approach with justification based on findings.

---

## Phase 4: Build the Discovery Script

### 4.1 Script Requirements

The discovery script must:
- Launch a browser (headed mode available for debugging)
- Navigate to the site to establish a valid session
- Walk the full hierarchy: root → category → subcategory → leaf
- Extract all entity IDs, names, and parent-child relationships
- Save everything to `site_structure.json`
- Support filtering (discover one branch vs. the whole tree)
- Use polite rate limiting (random 0.3–1.5s delays between API calls)

### 4.2 Output Format: site_structure.json

The JSON must be self-documenting and contain everything needed by the extraction
script:

```json
{
  "discovered_at": "ISO-8601 timestamp",
  "site_url": "https://target-site.com",
  "total_root_entities": 150,
  "entities": [
    {
      "name": "Entity Name",
      "id": "unique-id",
      "level": 0,
      "url_params": {
        "paramName1": "value1",
        "paramName2": "value2"
      },
      "children": [
        {
          "name": "Child Name",
          "id": "child-id",
          "level": 1,
          "url_params": {
            "paramName3": "value3"
          },
          "children": [
            {
              "name": "Leaf Name",
              "id": "leaf-id",
              "level": 2
            }
          ]
        }
      ]
    }
  ]
}
```

Key principles:
- Store **all IDs and parameter values** needed to construct direct URLs
- Use the same field names the API uses (don't rename/transform)
- Include discovery timestamp so you know how stale the cache is
- Support incremental updates (merge new discoveries into existing file)

### 4.3 Breadth-First Discovery Pattern

```python
def discover_hierarchy(page, root_endpoint, child_endpoint_template):
    """
    Generic breadth-first hierarchy discovery.

    Args:
        page: Playwright page with valid session
        root_endpoint: API path that returns all root entities
        child_endpoint_template: f-string with {parent_id} placeholder
    """
    # Level 0: Get all root entities
    roots = page.evaluate(
        "async (ep) => { const r = await fetch(ep); return r.json(); }",
        root_endpoint
    )

    hierarchy = []
    for root in roots:
        root_entry = extract_entity(root)  # Adapt to actual response shape
        root_entry["children"] = []

        # Level 1+: Get children recursively
        child_ep = child_endpoint_template.format(parent_id=root_entry["id"])
        children = page.evaluate(
            "async (ep) => { const r = await fetch(ep); return r.json(); }",
            child_ep
        )

        for child in children:
            child_entry = extract_entity(child)
            root_entry["children"].append(child_entry)
            polite_delay()  # 0.3-1.5s random delay

        hierarchy.append(root_entry)
        polite_delay()

    return hierarchy
```

### 4.4 Rate Limiting

```python
import time, random

def polite_delay(min_s=0.3, max_s=1.5):
    """Random delay between API calls to avoid hammering the server."""
    time.sleep(random.uniform(min_s, max_s))
```

Rules:
- Always add random delays between API calls
- Single-threaded discovery (don't parallelize)
- Cache aggressively — entity IDs rarely change
- Support `--headed` flag for visual debugging

**Deliverable:** Working discovery script with CLI flags for `--headed`, entity
filtering, and `--include-children` depth control.

---

## Phase 5: Build the Extraction Script

### 5.1 Script Requirements

The extraction script must:
- Load `site_structure.json` — fail clearly if missing with instructions to run discovery
- Accept CLI arguments for which entity to query and what parameters (e.g., date range)
- Construct direct URLs from cached IDs (skip all UI navigation)
- Use `page.evaluate()` for batch API calls from within the browser context
- Output results as formatted text (default) or JSON (`--json` flag)
- Support `--headed` mode for debugging

### 5.2 Direct URL Construction

Once you have cached IDs, skip all UI interaction. Build URLs directly:

```python
from urllib.parse import urlencode

def build_direct_url(base_url, cached_entity, extra_params):
    """Construct a URL that jumps straight to a specific entity."""
    params = {**cached_entity["url_params"], **extra_params}
    return f"{base_url}/results?{urlencode(params)}"
```

### 5.3 Batch Data Extraction via page.evaluate()

For checking many leaf entities, batch the API calls inside the browser:

```python
results = page.evaluate("""async ([entityIds, extraParams]) => {
    const results = {};
    for (const id of entityIds) {
        try {
            const url = `/api/data?entityId=${id}&` + new URLSearchParams(extraParams);
            const resp = await fetch(url);
            results[id] = await resp.json();
        } catch (e) {
            results[id] = { error: e.message };
        }
        await new Promise(r => setTimeout(r, 200));  // polite delay
    }
    return results;
}""", [entity_ids, {"date": "2026-07-01"}])
```

### 5.4 Output Formatting

Provide two output modes:
- **Human-readable** (default): Table or summary with key findings highlighted
- **JSON** (`--json` flag): Machine-readable output for piping to other tools

**Deliverable:** Working extraction script that reads the cache and fetches target data.

---

## Phase 6: Documentation

### 6.1 Update Project README / CLAUDE.md

Document:
- The two-step workflow (discover once → extract repeatedly)
- All CLI flags for both scripts
- The site's ID hierarchy with real examples
- Known limitations and failure modes

### 6.2 Findings Report

Produce a brief report covering:
- Tech stack identified
- Full API dependency graph
- ID hierarchy with real ID examples
- Which automation approach was chosen and why
- Any anti-bot measures encountered
- Rate limiting observations

---

## Appendix: Checklist

Use this for any new target site:

- [ ] Identify the tech stack (frontend framework, backend, WAF, anti-bot)
- [ ] Map all URL transitions from root to leaf entity
- [ ] Map the ID hierarchy (parameter names at each level)
- [ ] Capture all API endpoints (DevTools Network tab)
- [ ] Build the API dependency graph (which call feeds which)
- [ ] Identify bootstrap/bulk data calls
- [ ] Test direct HTTP (`curl` the endpoints — 200 or 403?)
- [ ] Choose automation approach (direct HTTP / headless browser / hybrid)
- [ ] Build discovery script (extract all IDs → site_structure.json)
- [ ] Build extraction script (read cache → fetch target data)
- [ ] Add rate limiting (random delays, single-threaded)
- [ ] Test in headed mode first (`--headed` flag)
- [ ] Document the workflow and API surface

---

## Appendix: Common Patterns by Framework

### Angular SPAs
- Routes in `app-routing.module.ts`, often use query params not path segments
- API calls via `HttpClient` in `*.service.ts` files
- State in NgRx store — look for `/ngrx/` or `@ngrx` in bundles
- HTTP interceptors auto-attach auth headers
- API paths typically `/api/{controller}/{action}`

### React SPAs
- React Router: path-based routing (`/category/:id/item/:itemId`)
- State in Redux (`__REDUX_DEVTOOLS__`), Zustand, React Query, or SWR
- API calls via axios or fetch in hooks/effects (`useEffect`, `useQuery`)
- Next.js: `__NEXT_DATA__` script tag contains server-side fetched data
- Remix: `__remixContext` contains loader data

### Vue / Nuxt SPAs
- Vue Router: hash mode (`/#/path`) or history mode (`/path`)
- State in Vuex or Pinia
- `__NUXT__` script tag contains SSR-hydrated data
- API calls in `asyncData()` or `useFetch()` composables

### .NET Backend APIs
- URL pattern: `/api/{ControllerName}/{ActionName}`
- IDs often use C# `int` (32-bit signed — explains negative integer IDs)
- Responses default to `camelCase` JSON (via System.Text.Json or Newtonsoft)
- OData endpoints may expose `$filter`, `$select`, `$expand` query params
- Entity Framework may leak DB column names in JSON keys

### Django / DRF Backend APIs
- URL pattern: `/api/v1/{resource}/` (trailing slash!)
- DRF responses include `count`, `next`, `previous`, `results` for pagination
- IDs typically auto-increment positive integers
- May use `?format=json` query param

### Rails Backend APIs
- URL pattern: `/api/v1/{resources}/{id}` (plural nouns)
- Responses often nested under a root key: `{"users": [...]}`
- IDs are auto-increment positive integers
- May use `.json` extension instead of Accept header
