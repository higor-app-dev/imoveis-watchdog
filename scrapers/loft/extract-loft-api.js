#!/usr/bin/env node
/**
 * extract-loft-api.js — Direct API extraction from Loft Landscape API
 *
 * Calls the unauthenticated Landscape API V3 GET endpoint directly (no browser).
 * Filtered to São Paulo by default via cities[]=sao paulo, sp.
 * Handles both flat and nested listing shapes.
 *
 * Usage:
 *   node extract-loft-api.js [options]
 *
 * Options:
 *   --pages N       Pages to fetch (default: 10, 0 = all)
 *   --hits N        Results per page (default: 200, max ~500)
 *   --city "NAME"   City filter (default: "sao paulo, sp")
 *   --output PATH   Output file (default: ./listings.json)
 *   --no-progress   Suppress progress output
 */

const API_BASE = 'https://landscape-api.loft.com.br/listing/v3/search';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  'Origin': 'https://loft.com.br',
  'Referer': 'https://loft.com.br/venda/apartamentos/sp/sao-paulo/',
  'Accept': 'application/json',
};

// ── Unified schema mapper ──────────────────────────────────────────────────

function mapListing(raw) {
  if (!raw) return null;
  const addr = raw.address || {};
  const neighborhood = addr.neighborhood || (addr.neighbourhood && addr.neighbourhood.name) || '';
  const streetParts = [
    addr.streetFullName || `${addr.streetType || ''} ${addr.streetName || ''}`.trim(),
    addr.number,
  ].filter(Boolean);
  const endereco = streetParts.join(', ') || neighborhood;

  // Photos are relative filenames from content.loft.com.br/homes/
  const photoFilenames = Array.isArray(raw.photos) ? raw.photos.filter(Boolean) : [];

  return {
    // Core unified schema fields
    price: raw.price ?? null,
    area_m2: raw.area ?? null,
    bedrooms: raw.bedrooms ?? null,
    parking_spots: raw.parkingSpots ?? null,

    // Full address
    full_address: endereco,
    neighborhood,
    city: addr.city || '',
    state: addr.state || '',
    postal_code: addr.postalCode || null,
    latitude: raw._geoloc ? raw._geoloc.lat : (addr.lat ? parseFloat(addr.lat) : null),
    longitude: raw._geoloc ? raw._geoloc.lng : (addr.lng ? parseFloat(addr.lng) : null),

    // Photo filenames (CDN at content.loft.com.br/homes/ — requires auth)
    photo_filenames: photoFilenames,

    // Metadata
    id: raw.id || raw.objectID || '',
    unit_id: raw.unitId ?? null,
    property_type: raw.homeType || '',
    usage_type: raw.usageType || 'residential',
    suites: raw.suits ?? null,
    bathrooms: raw.restrooms ?? null,
    condo_fee: raw.complexFee ?? null,
    property_tax: raw.propertyTax ?? null,
    description: (raw.description || '').slice(0, 500),
    agency_name: raw.agencyName || '',
    agency_id: raw.agencyId || '',
    is_marketplace: raw.isMarketplace ?? false,
    has_virtual_tour: raw.hasVirtualTour ?? false,
    has_balcony: raw.unitHasBalcony ?? false,
    floor: raw.floor ?? null,
    total_floors: raw.numberOfFloors ?? null,
    has_elevator: raw.towerHasElevator ?? null,
    land_area: raw.landArea ?? null,
    listing_group_key: raw.listingGroupKey || null,
    created_at: raw.createdAt || null,

    // Price reductions
    previous_price: raw.previousPrice ?? null,
    price_reduced: !!(raw.previousPrice && raw.price && raw.previousPrice > raw.price),
    price_reduction_pct: raw.previousPrice && raw.price && raw.previousPrice > raw.price
      ? Math.round((1 - raw.price / raw.previousPrice) * 10000) / 100 : 0,

    // Tags and features
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    unit_features: Array.isArray(raw.unitFeatures) ? raw.unitFeatures : [],

    // Source
    source: 'loft',
    extracted_at: new Date().toISOString(),
  };
}

// ── API caller ─────────────────────────────────────────────────────────────

async function fetchPage(page, hitsPerPage, city) {
  const params = new URLSearchParams();
  params.set('hitsPerPage', String(hitsPerPage));
  params.set('page', String(page));
  params.set('cities[]', city || 'sao paulo, sp');
  params.set('transactionType[]', 'for_sale');

  const url = `${API_BASE}?${params.toString()}`;
  const response = await fetch(url, { headers: HEADERS });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API error ${response.status}: ${text.slice(0, 200)}`);
  }

  return response.json();
}

// ── Main ────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);

  function getArg(name, def) {
    const eq = args.find(a => a.startsWith(`${name}=`));
    if (eq) return eq.split('=')[1];
    const idx = args.indexOf(name);
    return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : def;
  }

  const pagesArg = getArg('--pages', null);
  const hitsArg = getArg('--hits', '200');
  const city = getArg('--city', 'sao paulo, sp');
  const outputPath = getArg('--output', './listings.json');
  const noProgress = args.includes('--no-progress');

  const maxPages = pagesArg !== null ? parseInt(pagesArg) : 10;
  const hitsPerPage = Math.min(Math.max(parseInt(hitsArg) || 200, 10), 500);

  const log = noProgress ? () => {} : msg => console.error(msg);

  log(`\n── Loft Direct API Extraction ──`);
  log(`  Endpoint:  GET ${API_BASE}`);
  log(`  City:      ${city}`);
  log(`  Hits/page: ${hitsPerPage}`);
  log(`  Pages:     ${maxPages === 0 ? 'ALL' : maxPages}`);
  log(`  Output:    ${outputPath}\n`);

  // ── Fetch first page to get total ──────────────────────────────────────

  let data;
  try {
    data = await fetchPage(0, hitsPerPage, city);
  } catch (err) {
    console.error(`✗ Failed to fetch first page: ${err.message}`);
    process.exit(1);
  }

  const pagination = data.pagination;
  if (!pagination) {
    console.error('✗ No pagination in response');
    process.exit(1);
  }

  // V3 uses 'total' instead of V4's 'totalListings'
  const totalAvailable = pagination.total || pagination.totalListings || 0;
  const totalApiPages = pagination.totalPages || 0;

  // API caps accessible pages around ~50 at 200hpp / ~200 at 50hpp
  const maxAccessiblePages = Math.min(totalApiPages, 200);
  const pagesToFetch = maxPages === 0 ? maxAccessiblePages : Math.min(maxPages, maxAccessiblePages);

  log(`  Total listings: ${totalAvailable.toLocaleString()}`);
  log(`  Total pages:    ${totalApiPages} (accessible: ${maxAccessiblePages})`);
  log(`  Fetching:       ${pagesToFetch} page(s)\n`);

  // ── Collect listings ────────────────────────────────────────────────────

  const allListings = [];
  let lastProgress = 0;

  // Helper: extract listing from either shape
  const extract = (item) => {
    // V4 nested shape: { listing: {...} }
    // V3 flat shape: {...} directly
    return item.listing || item;
  };

  // Process page 0
  for (const item of data.listings || []) {
    const mapped = mapListing(extract(item));
    if (mapped) allListings.push(mapped);
  }
  log(`  ✓ Page 1: ${allListings.length} listings`);

  // Process remaining pages
  for (let p = 1; p < pagesToFetch; p++) {
    let retries = 0;
    let success = false;

    while (retries < 3 && !success) {
      try {
        data = await fetchPage(p, hitsPerPage, city);
        success = true;
      } catch (err) {
        retries++;
        if (retries >= 3) {
          log(`  ✗ Page ${p + 1} failed after 3 retries: ${err.message}`);
          break;
        }
        log(`  ⚠ Page ${p + 1} retry ${retries}: ${err.message}`);
        await new Promise(r => setTimeout(r, 1000 * retries));
      }
    }

    if (!success) break;

    for (const item of data.listings || []) {
      const mapped = mapListing(extract(item));
      if (mapped) allListings.push(mapped);
    }

    // Progress reporting
    const pct = Math.round(((p + 1) / pagesToFetch) * 100);
    if (pct >= lastProgress + 10 || p === pagesToFetch - 1) {
      log(`  ${Math.min(pct, 100)}% — Page ${p + 1}/${pagesToFetch} (${allListings.length.toLocaleString()} listings)`);
      lastProgress = pct;
    }
  }

  log(`\n  Total extracted: ${allListings.length.toLocaleString()} listings`);

  // ── Deduplicate by id ──────────────────────────────────────────────────

  const seen = new Set();
  const deduped = [];
  for (const item of allListings) {
    const key = item.id || `${item.full_address}_${item.price}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(item);
    }
  }

  if (deduped.length < allListings.length) {
    log(`  Dedup removed: ${allListings.length - deduped.length}`);
  }

  // ── Write output ────────────────────────────────────────────────────────

  const fs = require('fs');
  const path = require('path');
  const outDir = path.dirname(outputPath);
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(deduped, null, 2));

  const fileSize = fs.statSync(outputPath).size;
  log(`\n── Done ──`);
  log(`  Output: ${outputPath}`);
  log(`  Size:   ${(fileSize / 1024 / 1024).toFixed(1)} MB`);
  log(`  Items:  ${deduped.length.toLocaleString()}`);
  log(`  City:   ${city}`);

  // Summary stats
  const prices = deduped.filter(l => l.price).map(l => l.price);
  const areas = deduped.filter(l => l.area_m2).map(l => l.area_m2);
  const reductions = deduped.filter(l => l.price_reduced);

  log(`\n── Stats ──`);
  if (prices.length) {
    log(`  Price range: R$ ${Math.min(...prices).toLocaleString()} ~ R$ ${Math.max(...prices).toLocaleString()}`);
    log(`  Avg price:   R$ ${Math.round(prices.reduce((a, b) => a + b, 0) / prices.length).toLocaleString()}`);
  }
  if (areas.length) {
    log(`  Area range:  ${Math.min(...areas)} ~ ${Math.max(...areas)} m²`);
    log(`  Avg area:    ${Math.round(areas.reduce((a, b) => a + b, 0) / areas.length)} m²`);
  }
  if (reductions.length) {
    log(`  Reductions:  ${reductions.length} (${(reductions.reduce((s, l) => s + l.price_reduction_pct, 0) / reductions.length).toFixed(1)}% avg)`);
  }

  // Output the file path on stdout for piping
  console.log(outputPath);
}

main().catch(err => {
  console.error(`\n✗ Fatal: ${err.message}`);
  process.exit(1);
});
