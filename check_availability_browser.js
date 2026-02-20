/**
 * Ontario Parks Campsite Availability Checker — Browser Console Script
 *
 * HOW TO USE:
 * 1. Go to https://reservations.ontarioparks.ca
 * 2. Navigate to your desired park and campground (e.g. Killbear → Lighthouse Point B)
 * 3. Set your desired dates, party size, and equipment type in the search form
 * 4. Once you see the campground MAP view with site markers, open DevTools (F12)
 * 5. Paste this entire script into the Console tab and press Enter
 *
 * The script will:
 * - Fetch all site details and attributes for the current campground
 * - Check availability for each site using your selected date range
 * - Print a summary of available sites to the console
 * - Highlight available sites on the map in green
 *
 * To check a SPECIFIC site (e.g. site 1422), change the SITE_FILTER below.
 */

// ── Configuration ──────────────────────────────────────────────────────
// Set to a site name/number to check only that site. Set to null to check all.
const SITE_FILTER = null; // e.g. "1422" or null for all sites

// Optional: filter by site attributes. Set to null to skip attribute filtering.
// Available attributes vary by park — run once with SHOW_ATTRIBUTES = true to see them.
const SHOW_ATTRIBUTES = true;

// ── Main ───────────────────────────────────────────────────────────────

(async function checkAvailability() {
  const urlParams = new URLSearchParams(window.location.search);
  const locationId = urlParams.get("resourceLocationId");
  const startDate = urlParams.get("startDate");
  const endDate = urlParams.get("endDate");

  if (!locationId) {
    console.error(
      "Could not find resourceLocationId in the URL.\n" +
      "Make sure you are on the campground MAP view at:\n" +
      "https://reservations.ontarioparks.ca/create-booking/results?..."
    );
    return;
  }

  console.log(`Location ID: ${locationId}`);
  console.log(`Date range: ${startDate} → ${endDate}`);
  console.log("Fetching site data...\n");

  // 1. Fetch filterable attributes (site quality, pad type, etc.)
  let attrs = {};
  try {
    const attrResp = await fetch(
      "https://reservations.ontarioparks.ca/api/attribute/filterable"
    );
    attrs = await attrResp.json();
  } catch (e) {
    console.warn("Could not fetch attributes:", e.message);
  }

  // 2. Fetch all sites in this campground
  const sitesResp = await fetch(
    `https://reservations.ontarioparks.ca/api/resourcelocation/resources?resourceLocationId=${locationId}`
  );
  const sitesData = await sitesResp.json();

  // 3. Parse site info
  const sites = [];
  for (const [id, val] of Object.entries(sitesData)) {
    if (!val) continue;
    const name = val.localizedValues?.[0]?.name ?? id;

    // Parse attributes
    const siteAttrs = {};
    if (val.definedAttributes && Object.keys(attrs).length > 0) {
      for (const da of val.definedAttributes) {
        const attrDef = attrs[da.attributeDefinitionId];
        if (!attrDef) continue;
        const attrName = attrDef.localizedValues?.[0]?.displayName ?? da.attributeDefinitionId;
        if (da.value !== undefined && da.value !== null) {
          siteAttrs[attrName] = da.value;
        } else if (da.values && attrDef.values) {
          siteAttrs[attrName] = da.values
            .map((v) => attrDef.values[v]?.localizedValues?.[0]?.displayName ?? v)
            .join(", ");
        }
      }
    }

    sites.push({ name, longId: id, attrs: siteAttrs });
  }

  console.log(`Found ${sites.length} sites in this campground.\n`);

  if (SHOW_ATTRIBUTES && sites.length > 0) {
    const allAttrNames = new Set();
    sites.forEach((s) => Object.keys(s.attrs).forEach((k) => allAttrNames.add(k)));
    console.log("Available attributes:", [...allAttrNames].sort().join(", "));
    console.log("Sample site attributes:", sites[0].attrs);
    console.log("");
  }

  // 4. Filter to specific site if requested
  const sitesToCheck = SITE_FILTER
    ? sites.filter((s) => s.name === String(SITE_FILTER) || s.name.includes(String(SITE_FILTER)))
    : sites;

  if (SITE_FILTER && sitesToCheck.length === 0) {
    console.error(`Site "${SITE_FILTER}" not found. Available sites: ${sites.map((s) => s.name).join(", ")}`);
    return;
  }

  console.log(`Checking availability for ${sitesToCheck.length} site(s)...\n`);

  // 5. Check availability for each site
  const available = [];
  const unavailable = [];

  for (let i = 0; i < sitesToCheck.length; i++) {
    const site = sitesToCheck[i];
    try {
      const statusResp = await fetch(
        `https://reservations.ontarioparks.ca/api/availability/resourcestatus` +
        `?resourceId=${site.longId}&startDate=${startDate}&endDate=${endDate}`
      );
      const status = await statusResp.json();

      if (status.availabilityType === 0) {
        available.push(site);
      } else {
        unavailable.push(site);
      }
    } catch (e) {
      console.warn(`Error checking site ${site.name}:`, e.message);
    }

    // Progress log every 10 sites
    if ((i + 1) % 10 === 0 || i === sitesToCheck.length - 1) {
      console.log(`  Checked ${i + 1}/${sitesToCheck.length} sites...`);
    }
  }

  // 6. Print results
  console.log("\n" + "=".repeat(60));
  console.log(`RESULTS: ${available.length} available / ${sitesToCheck.length} total`);
  console.log("=".repeat(60));

  if (available.length > 0) {
    console.log("\n✓ AVAILABLE SITES:");
    available
      .sort((a, b) => {
        const na = parseInt(a.name, 10);
        const nb = parseInt(b.name, 10);
        return isNaN(na) || isNaN(nb) ? a.name.localeCompare(b.name) : na - nb;
      })
      .forEach((s) => {
        let info = `  Site ${s.name}`;
        if (s.attrs.Quality) info += ` (Quality: ${s.attrs.Quality})`;
        console.log(info);
      });
  } else {
    console.log("\nNo available sites found for the selected dates.");
  }

  // 7. Highlight available sites on the map
  let highlighted = 0;
  for (const site of available) {
    try {
      const xpath = `//div[text()='${site.name}']`;
      const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
      if (el) {
        const svgIcon = el.parentElement?.previousSibling?.firstChild;
        if (svgIcon) {
          svgIcon.style.fill = "#00FF00";
          svgIcon.style.stroke = "#006600";
          svgIcon.style.strokeWidth = "2.5";
          highlighted++;
        }
      }
    } catch (_) { /* ignore DOM manipulation errors */ }
  }
  if (highlighted > 0) {
    console.log(`\nHighlighted ${highlighted} available site(s) in green on the map.`);
  }

  console.log("\n" + "=".repeat(60));
})();
