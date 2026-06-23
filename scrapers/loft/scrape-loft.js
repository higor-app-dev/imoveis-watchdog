#!/usr/bin/env node
/**
 * scrape-loft.js — Local Playwright with stealth for Loft scraping
 *
 * Extracts listing data from loft.com.br via SSR __NEXT_DATA__ (page 0)
 * and Landscape API for pagination.
 *
 * Usage:
 *   node scrape-loft.js [options]
 *
 * Options:
 *   --url       Base URL (default: https://loft.com.br/venda/apartamentos/sp/sao-paulo/)
 *   --headed    Run in headed mode (default: headless)
 *   --pages N   Number of pages to scrape (default: 1)
 *   --all       Scrape ALL available pages
 *   --output    Output directory
 *   --json      Output structured listings as JSON to stdout
 */

const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const path = require('path');
const fs = require('fs');

chromium.use(StealthPlugin());

// ── Configuration ──────────────────────────────────────────────────────────

const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
];

const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
  { width: 1536, height: 864 },
  { width: 1440, height: 900 },
];

const LOCALES = ['pt-BR', 'pt', 'en-US'];
function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function timestamp() { return new Date().toISOString().replace(/[:.]/g, '-'); }

// ── Schema mapping ──────────────────────────────────────────────────────────

const PROPERTY_TYPE_MAP = {
  apartment: 'apartamento',
  rooftop: 'cobertura',
  house: 'casa',
  studio: 'kitnet',
  duplex: 'duplex',
  triplex: 'triplex',
  garden: 'casa_condominio',
  conjugado: 'conjugado',
  penthouse: 'cobertura',
  flat: 'flat',
};

function mapListing(l) {
  if (!l) return null;
  const address = l.address || {};
  const neighborhood = address.neighborhood || (address.neighbourhood && address.neighbourhood.name) || '';
  const streetParts = [
    address.streetFullName || `${address.streetType || ''} ${address.streetName || ''}`.trim(),
    address.number,
  ].filter(Boolean);
  const endereco = streetParts.join(', ') || neighborhood;
  const propertyType = PROPERTY_TYPE_MAP[l.homeType || l.propertyType || ''] || (l.homeType || l.propertyType || 'apartamento');
  const isSale = l.transactionType === 'FOR_SALE' || l.status === 'FOR_SALE';
  const photoUrls = Array.isArray(l.photos) ? l.photos.map(p => {
    const filename = (typeof p === 'string' ? p : (p.url || '')).trim();
    if (!filename) return '';
    // Already absolute URL
    if (filename.startsWith('http://') || filename.startsWith('https://')) return filename;
    // Relative filename → CDN absolute URL
    return `https://content.loft.com.br/homes/${filename.replace(/^\//, '')}`;
  }).filter(Boolean) : [];
  const amenities = [...(l.unitFeatures || []), ...(l.condominiumInfrastructure || []), ...(l.condominiumLeisure || [])].filter(Boolean);
  return {
    id: l.id || l.objectID || '',
    titulo: `${propertyType} em ${neighborhood}`.trim() || propertyType,
    descricao: l.description || '',
    fonte: 'loft',
    preco_venda: isSale ? l.price : null,
    preco_anterior: isSale ? (l.previousPrice || null) : null,
    data_atualizacao_preco: l.priceUpdatedAt || null,
    preco_aluguel: !isSale ? (l.rentalPrice || l.price) : null,
    condominio: l.complexFee || null,
    iptu: l.propertyTax || null,
    area: l.area || null,
    quartos: l.bedrooms || null,
    suites: l.suits || null,
    banheiros: l.restrooms || null,
    vagas: l.parkingSpots || null,
    andar: l.floor || null,
    tipo: propertyType,
    uso: l.usageType || 'residential',
    endereco,
    bairro: neighborhood,
    cidade: address.city || 'São Paulo',
    uf: address.state || 'SP',
    cep: address.postalCode || null,
    latitude: l._geoloc ? l._geoloc.lat : (parseFloat(address.lat) || null),
    longitude: l._geoloc ? l._geoloc.lng : (parseFloat(address.lng) || null),
    url: l.url || (l.id ? `https://loft.com.br/imovel/${l.id}` : ''),
    origem_id: l.unitId || null,
    imagens: photoUrls,
    comodidades: amenities,
    agencia: l.agencyName || '',
    data_criacao: l.createdAt || null,
    tem_reducao: !!(l.previousPrice && l.price && l.previousPrice > l.price),
    percentual_reducao: l.previousPrice && l.price && l.previousPrice > l.price
      ? Math.round((1 - l.price / l.previousPrice) * 10000) / 100 : 0,
    raw_id: l.id || l.objectID,
    listingGroupKey: l.listingGroupKey || null,
  };
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function saveJson(dir, name, data) {
  const p = path.join(dir, name);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 2));
  const size = Buffer.byteLength(JSON.stringify(data), 'utf8');
  console.log(`  ✓ ${path.relative(dir, p)} (${(size / 1024).toFixed(0)} KB)`);
  return p;
}

// ── Main scraper ────────────────────────────────────────────────────────────

async function scrapeLoft(options = {}) {
  const {
    url = 'https://loft.com.br/venda/apartamentos/sp/sao-paulo/',
    headless = true,
    pages = 1,
    outputDir = null,
  } = options;

  const userAgent = pick(USER_AGENTS);
  const viewport = pick(VIEWPORTS);
  const locale = pick(LOCALES);
  const out = outputDir || path.join(__dirname, 'output', timestamp());

  console.log(`── Loft Scraper ──`);
  console.log(`  URL:       ${url}`);
  console.log(`  Headless:  ${headless}`);
  console.log(`  UA:        ${userAgent.slice(0, 60)}...`);
  console.log(`  Viewport:  ${viewport.width}x${viewport.height}`);
  console.log(`  Output:    ${out}\n`);

  const browser = await chromium.launch({
    headless,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-sandbox', '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-features=IsolateOrigins,site-per-process',
    ],
  });

  const context = await browser.newContext({
    userAgent,
    viewport,
    locale,
    geolocation: { latitude: -23.5505, longitude: -46.6333 },
    permissions: ['geolocation'],
    timezoneId: 'America/Sao_Paulo',
  });

  const page = await context.newPage();

  // ── Anti-detection ──────────────────────────────────────────────────────
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
    window.chrome = { runtime: {} };
    if (navigator.permissions && navigator.permissions.query) {
      const originalQuery = navigator.permissions.query.bind(navigator.permissions);
      navigator.permissions.query = (params) => {
        if (params.name === 'notifications') return Promise.resolve({ state: 'denied' });
        return originalQuery(params);
      };
    }
  });

  const allListings = [];
  let searchParams = null;
  let totalPages = 0;
  let totalListings = 0;
  let hitsPerPage = 38;

  try {
    // ── Step 1: Load page & extract SSR data ──────────────────────────
    console.log('  Loading page...');
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#__NEXT_DATA__', { state: 'attached', timeout: 15000 });
    await page.waitForTimeout(2000);

    // Read __NEXT_DATA__
    const ndText = await page.evaluate(() => {
      const el = document.getElementById('__NEXT_DATA__');
      return el ? el.textContent : null;
    });

    if (!ndText || ndText.length < 1000) {
      throw new Error(`__NEXT_DATA__ not found (len=${ndText ? ndText.length : 0})`);
    }

    const nextData = JSON.parse(ndText);
    const pp = nextData.props && nextData.props.pageProps;
    if (!pp || !pp.dehydratedState || !pp.dehydratedState.queries) {
      throw new Error(`dehydratedState missing (props keys: ${Object.keys(nextData.props || {}).join(',')})`);
    }

    const searchQuery = pp.dehydratedState.queries.find(q =>
      q.queryKey && q.queryKey[0] === 'Listing:Search'
    );
    if (!searchQuery) {
      const names = pp.dehydratedState.queries.map(q => q.queryKey[0]).join(', ');
      throw new Error(`Listing:Search missing. Available: ${names}`);
    }

    // Extract pagination info
    searchParams = searchQuery.queryKey[1];
    const pagination = searchQuery.state && searchQuery.state.data && searchQuery.state.data.pagination;
    if (pagination) {
      totalPages = pagination.totalPages || 0;
      totalListings = pagination.totalListings || 0;
      hitsPerPage = pagination.hitsPerPage || 38;
    }

    // Map page 0 listings
    const raw = searchQuery.state.data && searchQuery.state.data.listings;
    if (!raw || raw.length === 0) {
      console.log('  ⚠ No raw listings found in SSR data');
    } else {
      for (const item of raw) {
        // Handle both shapes: {listing: {...}} (nested) and direct flat object
        const listing = item.listing || item;
        if (listing) {
          const mapped = mapListing(listing);
          if (mapped) allListings.push(mapped);
        }
      }
      console.log(`  ✓ SSR: ${allListings.length} listings from page 1`);
    }

    // ── Step 2: Fetch more pages via API ───────────────────────────────
    const pagesToFetch = options.all ? totalPages : Math.min(pages, totalPages);

    if (pagesToFetch > 1 && searchParams) {
      console.log(`  Fetching ${pagesToFetch - 1} more page(s) via Landscape API...\n`);
    }

    const apiBaseUrl = `https://landscape-api.loft.com.br/listing/v3/search?${searchParams}`;

    for (let p = 1; p < pagesToFetch; p++) {
      const apiUrl = `${apiBaseUrl}&page=${p}`;

      let apiResult = null;
      for (let attempt = 0; attempt < 2; attempt++) {
        apiResult = await page.evaluate(async (url) => {
          try {
            const resp = await fetch(url, { headers: { Accept: 'application/json' } });
            return { status: resp.status, body: await resp.text() };
          } catch (err) {
            return { status: 0, error: err.message };
          }
        }, apiUrl);

        if (apiResult.status === 200) break;
        console.log(`  ⚠ API page ${p + 1} attempt ${attempt + 1}: ${apiResult.status} — retry`);
        await page.waitForTimeout(2000);
      }

      if (!apiResult || apiResult.status !== 200) {
        console.log(`  ⚠ Page ${p + 1} skipped (API ${apiResult ? apiResult.status : 'error'})`);
        break;
      }

      let apiData;
      try { apiData = JSON.parse(apiResult.body); } catch { break; }

      const apiListings = (apiData.listings || []).filter(l => l).map(l => {
        const listing = l.listing || l;
        return mapListing(listing);
      }).filter(Boolean);
      allListings.push(...apiListings);
      console.log(`  ✓ API page ${p + 1}: ${apiListings.length} listings`);
      await new Promise(r => setTimeout(r, 300));
    }

    // ── Save ─────────────────────────────────────────────────────────
    saveJson(out, 'listings.json', allListings);

    console.log(`\n── Summary ──`);
    console.log(`  Pages:           ${Math.ceil(allListings.length / Math.max(hitsPerPage, 1))}`);
    console.log(`  Listings:        ${allListings.length}`);
    console.log(`  Available:       ${totalListings.toLocaleString() || '?'}`);
    console.log(`  Output:          ${out}/listings.json`);

    const reduct = allListings.filter(l => l.tem_reducao);
    if (reduct.length > 0) {
      const avg = reduct.reduce((s, l) => s + l.percentual_reducao, 0) / reduct.length;
      const maxR = Math.max(...reduct.map(l => l.percentual_reducao));
      console.log(`\n  Price drops:     ${reduct.length} listings`);
      console.log(`  Avg reduction:   ${avg.toFixed(1)}%`);
      console.log(`  Max reduction:   ${maxR.toFixed(1)}%`);
    }

    return { success: true, listingCount: allListings.length, outputDir: out };

  } catch (err) {
    console.error(`\n  ✗ ${err.message}`);
    return { success: false, error: err.message };
  } finally {
    await browser.close();
    console.log('  Browser closed.');
  }
}

// ── CLI ─────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const url = args.find(a => a.startsWith('http')) || 'https://loft.com.br/venda/apartamentos/sp/sao-paulo/';
  const headless = !args.includes('--headed');
  const jsonFlag = args.includes('--json');
  const allFlag = args.includes('--all');
  const pagesIdx = args.indexOf('--pages');
  const pages = pagesIdx >= 0 ? parseInt(args[pagesIdx + 1]) || 1 : (allFlag ? 9999 : 1);
  const outIdx = args.indexOf('--output');
  const outputDir = outIdx >= 0 ? args[outIdx + 1] : null;

  const result = await scrapeLoft({ url, headless, pages, all: allFlag, outputDir });

  if (jsonFlag && result.success && result.outputDir) {
    const p = path.join(result.outputDir, 'listings.json');
    console.log('\n── JSON ──\n' + fs.readFileSync(p, 'utf-8'));
  }

  process.exit(result.success ? 0 : 1);
}

main();
