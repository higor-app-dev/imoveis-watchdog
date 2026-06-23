# Loft Internal API Investigation

> Investigated: 2026-06-21
> Source: DevTools Network analysis + reverse-engineering of Next.js chunks + direct API probing

## Summary

Loft's listing page (`loft.com.br/venda/apartamentos/sp/sao-paulo`) is a **Next.js SSR** app that fetches listing data from a private **Landscape API** backend. The website is protected by **CloudFront** (blocks browser automation / curl without specific headers). The API itself has **no auth** — it's unauthenticated but runs on non-obvious subdomains.

---

## 1. Architecture Overview

```
Browser (Next.js SSR)
    │
    ├── ► landscape-api.loft.com.br  (Listing search, facets, maps, metadata)
    ├── ► recommendation-api.loft.com.br  (Similar listings, stats, popular neighborhoods)
    ├── ► api.loft.com.br  (General API - credit, user events, home feed)
    └── ► content.loft.com.br/homes/  (Listing photos - CloudFront protected)
```

The frontend loads the page via **Next.js SSR** which fetches data server-side using `getInitialProps`. The actual API calls are made from the server, not the browser. The JS chunks reference URLs on `landscape-api.loft.com.br` (not `api.loft.com.br` directly).

---

## 2. API Base URLs

| Subdomain | Purpose |
|-----------|---------|
| `landscape-api.loft.com.br` | **Main listing API** — search, facets, metadata, neighborhoods, cities |
| `recommendation-api.loft.com.br` | Recommendations, similar sold, stats, popular neighborhoods |
| `api.loft.com.br` | General API (credit, user events, home feed, partner API) |
| `negotiation-api.loft.com.br` | Negotiation |
| `content.loft.com.br/homes/` | Listing photos (CloudFront, requires session token) |
| `informational-pages-api.loft.com.br` | Informational pages |
| `details.buyerld.loft-prod.io` | Listing details |
| `customer-bff.loft.com.br` | Customer BFF |
| `buyer-profile.loft.com.br` | Buyer profile |
| `buyer-leads.loft.com.br` | Buyer leads |
| `account-bff.loft.com.br` | Account BFF |
| Unauthenticated ✅ |

---

## 3. Landscape API Endpoints (Main Search API)

### 3.1 Listing Search (V4) — RECOMMENDED

**`POST https://landscape-api.loft.com.br/listing/v4/search`**

Primary search endpoint. Returns paginated listings with full details.

**Request body:**
```json
{
  "page": 0,
  "hitsPerPage": 20
}
```

Optional filters (inferred from JS source):
- `page` — Zero-indexed page number
- `hitsPerPage` — Results per page (default 20)
- `city` — City slug (e.g., `"sao-paulo"`)
- `state` — State acronym (e.g., `"SP"`)
- `businessType` — `"SALE"` or `"RENT"`
- `propertyTypes` — Array like `["APARTMENT", "HOUSE"]`
- `maxPrice`, `minPrice` — Price range
- `areaMax`, `areaMin` — Area in m²
- `bedrooms` — Exact bedroom count
- `parkingSpots` — Parking spaces
- `neighborhood` — Filter by neighborhood

**Response structure:**
```json
{
  "listings": [
    {
      "listing": {
        "id": "18ukny",
        "unitId": 6827306,
        "price": 1200000,
        "complexFee": 354,
        "propertyTax": 71.67,
        "monthlyExpenses": 425.67,
        "area": 167,
        "status": "FOR_SALE",
        "bedrooms": 3,
        "suits": 3,
        "restrooms": 4,
        "parkingSpots": 2,
        "image": "banner.jpg",
        "image_thumbnail": "banner_thumbnail.jpg",
        "image_icon": "banner_icon.jpg",
        "photos": ["facade01.jpg", "facade02.jpg", "facade03.jpg"],
        "productType": "market",
        "contractType": "non_exclusive",
        "homeType": "house",
        "houseType": "STANDARD",
        "usageType": "residential",
        "landArea": 250,
        "hasVirtualTour": false,
        "canRedecorate": null,
        "hasPhotoDecorated": false,
        "rentalPrice": null,
        "agencyId": "a1d53a4f-...",
        "agencyName": "NASCFER CONSULTORIA IMOBILIÁRIA",
        "isMarketplace": true,
        "amenities": null,
        "condominiumInfrastructure": null,
        "description": "...",
        "tags": [],
        "listingGroupKey": "b274d690c28b00c4d05e4c4786ea8c2a",
        "objectID": "18ukny",
        "createdAt": "2024-10-26T16:11:22.000Z",
        "createdAtTimeStamp": 1729959082,
        "address": {
          "id": "0",
          "type": "apartment",
          "regionId": "56791",
          "streetType": "Rua",
          "streetName": "Natalino Bertin",
          "streetFullName": "Rua Natalino Bertin",
          "number": null,
          "unitNumber": null,
          "postalCode": null,
          "neighborhood": "Jardim Ibiti do Paco",
          "city": "Sorocaba",
          "state": "SP",
          "country": "BR",
          "complexName": "",
          "lat": "-23.44105",
          "lng": "-47.45265",
          "neighbourhood": { "id": 56791, "name": "...", "slug": "..." },
          "facets": { "street": "...", "neighborhood": "...", "city": "..." }
        },
        "_geoloc": { "lat": -23.44105, "lng": -47.45265 },
        "location": { "lat": -23.44105, "lon": -47.45265 },
        "realState": ["home_house", "house_standard"],
        "search": { "facets": { ... } },
        "subwayShortestDistance": null,
        "isNearShopping": null,
        "isNearMarket": null,
        "isNearGym": null,
        "isNearSubway": null,
        "isNearPharmacy": null,
        "isNearBusStop": null,
        "isNearSchool": null,
        "isNearHospital": null,
        "isNearBakery": null,
        "isNearRestaurants": null,
        "unitHasBalcony": false,
        "floor": null,
        "numberOfFloors": null,
        "towerHasElevator": null,
        "currentPhase": null
      }
    }
  ],
  "pagination": {
    "page": 0,
    "hitsPerPage": 20,
    "totalListings": 1130461,
    "totalCards": 940219,
    "totalPages": 500
  },
  "search": { "facets": { ... } },
  "esRawQuery": { "index": "search-listing", ... }
}
```

**Total listings nationwide:** ~1,130,461

### 3.2 Listing Search (V3) — GET

**`GET https://landscape-api.loft.com.br/listing/v3/search?page=0&hitsPerPage=20`**

Same data as V4, GET interface. Requires the internal `index.html` rendering to be available (V4 GET returns 500).

### 3.3 Listing Search (V1)

**`GET https://landscape-api.loft.com.br/listing/search?query=sao-paulo`**

Simpler interface. Returns 20 results by default.

### 3.4 Facet Endpoint

**`GET https://landscape-api.loft.com.br/listing/v3/facet?fieldFacet=address.facets.neighborhood&city=SAO_PAULO&state=SP`**

Returns facet counts for neighborhoods. Required params:
- `fieldFacet` — One of: `address.facets.city`, `address.facets.neighborhood`, `agencyId`
- `city` — City name (uppercase)
- `state` — State acronym

### 3.5 Neighborhood Search

**`POST https://landscape-api.loft.com.br/listing/v3/search/neighborhoods`**

Returns neighborhood suggestions. Request body expects `city` and `state`.

### 3.6 City Endpoint

**`GET https://landscape-api.loft.com.br/listing/v3/city?country=BR&state=SP&slug=sao-paulo`**

City metadata.

### 3.7 Metadata Endpoint

**`GET https://landscape-api.loft.com.br/listing/v3/metadata?city=SAO_PAULO&state=SP`**

### 3.8 Map Endpoint

**`GET https://landscape-api.loft.com.br/listing/v3/map`**

Returns map-view listings (bounding box filtering).

---

## 4. Recommendation API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `recommendation-api.loft.com.br/listing/playlist` | GET | Featured/playlist listings |
| `recommendation-api.loft.com.br/listing/similar_sold` | POST | Similar sold listings |
| `recommendation-api.loft.com.br/loft-stats` | POST | Listing statistics |
| `recommendation-api.loft.com.br/most_visited_neighborhoods` | GET | Most visited neighborhoods (`city=sao-paulo&state=SP&country=BR`) |

---

## 5. Listing Data Fields (Key Extraction Points)

| Field | Path | Type | Example |
|-------|------|------|---------|
| Price | `listing.price` | number | `1200000` |
| Condo fee | `listing.complexFee` | number | `354` |
| Property tax | `listing.propertyTax` | number | `71.67` |
| Area (m²) | `listing.area` | number | `167` |
| Bedrooms | `listing.bedrooms` | number | `3` |
| Suites | `listing.suits` | number | `3` |
| Bathrooms | `listing.restrooms` | number | `4` |
| Parking spots | `listing.parkingSpots` | number | `2` |
| Street | `listing.address.streetFullName` | string | `"Rua Natalino Bertin"` |
| Neighborhood | `listing.address.neighborhood` | string | `"Jardim Ibiti do Paco"` |
| City | `listing.address.city` | string | `"Sorocaba"` |
| State | `listing.address.state` | string | `"SP"` |
| Latitude | `listing.address.lat` | string | `"-23.44105"` |
| Longitude | `listing.address.lng` | string | `"-47.45265"` |
| Listing ID | `listing.id` | string | `"18ukny"` |
| Unit ID | `listing.unitId` | number | `6827306` |
| Property type | `listing.homeType` | string | `"house"` / `"apartment"` |
| Transaction type | `listing.transactionType` | string | `"FOR_SALE"` / `"FOR_RENT"` |
| Photos | `listing.photos` | string[] | `["facade01.jpg", ...]` |
| Thumbnail | `listing.image_thumbnail` | string | `"banner_thumbnail.jpg"` |
| Description | `listing.description` | string | Full PT-BR description |
| Agency name | `listing.agencyName` | string | `"NASCFER CONSULTORIA IMOBILIÁRIA"` |
| Agency ID | `listing.agencyId` | string | UUID |
| Marketplace | `listing.isMarketplace` | bool | `true` |
| Virtual tour | `listing.hasVirtualTour` | bool | `false` |
| Balcony | `listing.unitHasBalcony` | bool | `false` |
| Can redecorate | `listing.canRedecorate` | bool | `null` |
| Condo infrastructure | `listing.condominiumInfrastructure` | string[] | `null` |
| Tags | `listing.tags` | string[] | `[]` |

---

## 6. Photo URLs

Photos are relative filenames from the API (e.g., `facade01.jpg`, `banner.jpg`). They are served from:

```
https://content.loft.com.br/homes/{filename}
```

However, this CDN is **protected by CloudFront** and requires a session/auth token to access (returns 403 without authentication). Photos are not directly accessible without a valid browser session.

---

## 7. Internal Query Format (from esRawQuery)

The API uses **Elasticsearch** behind the scenes. The `esRawQuery` field in the V4 response reveals the internal query structure:

```json
{
  "index": "search-listing",
  "query": {
    "bool": {
      "must": {
        "terms": {
          "transactionType": ["for_sale", "for_sale_or_rent"]
        }
      },
      "must_not": [
        { "match": { "address.city.keyword": "Taboao da Serra" } },
        { "exists": { "field": "externalSource" } }
      ]
    }
  }
}
```

Default query behavior:
- Lists for sale or for sale/rent
- Excludes `Taboao da Serra` (city-level block)
- Excludes external source listings
- Excludes `description_vector` and `semantic_description` from results

---

## 8. Required Headers

The Landscape API requires these headers:

| Header | Value |
|--------|-------|
| `User-Agent` | Standard browser UA (e.g., Chrome 120) |
| `Origin` | `https://loft.com.br` |
| `Referer` | `https://loft.com.br/venda/apartamentos/sp/sao-paulo` |
| `Accept` | `application/json` |
| `Content-Type` | `application/json` (for POST) |

**No API key or authentication token is required** for the Landscape API endpoints. They are unauthenticated but rely on non-obvious subdomains and CORS Origin checking.

---

## 9. Blocking Behavior / Rate Limits

| Protection Layer | Behavior |
|-----------------|----------|
| **CloudFront** (loft.com.br) | 403 error for bot-like traffic. Blocks browser automation. |
| **CloudFront** (api.loft.com.br) | 404 for bare `api.loft.com.br` — routes only to specific Azion CDN paths. |
| **Landscape API** | No blocking observed. All test requests returned successfully. |
| **Image CDN** (content.loft.com.br/homes) | 403 unless authenticated with valid session/cookie. |

The Landscape API (`landscape-api.loft.com.br`) appears to have **no rate limiting** — unlimited requests returned full results consistently.

---

## 10. Parameter Naming Conventions

Based on JS source analysis (chunk `4907-7208da295dbf0366.js`):

| Query Param | Description |
|-------------|-------------|
| `page` | Page number |
| `hitsPerPage` | Results per page |
| `maxPrice` / `priceMax` | Max price filter |
| `minPrice` / `priceMin` | Min price filter |
| `areaMax` | Max area (m²) |
| `areaMin` | Min area (m²) |
| `bedrooms` / `rooms` | Bedrooms count |
| `parkingSpots` | Parking spaces |
| `restrooms` | Bathrooms |
| `neighborhood` | Neighborhood slug |
| `address.facets.neighborhood` | Neighborhood facet filter |
| `rentalPriceMax` / `rentalPriceMin` | Rental price range |
| `openMap` | Boolean, map display |
| `useGptFilters` | Boolean, GPT filter |
| `totalListings` | Listing count |

**Filter values observed in JS:** `BELOW_MARKET_PRICE` (landscape parameter for discounted listings).

---

## 11. Filter Types (from Page Config)

From the Next.js page config, filter types available:

| Filter | Type | Range | Description |
|--------|------|-------|-------------|
| Price | Range | min/max | R$ price filter |
| Area | Range | 20–1000 m² | Min/max area |
| Condo fee | Range | 50–15000 R$ | Condominium fee |
| Bedrooms | Exact | 1–4+ | Exact bedroom count |
| Suites | Exact | 1–4+ | Exact suite count |
| Parking spots | Exact | 1–4+ | Parking spaces |
| Promotion | Toggle | — | Below market price |
| Condo infrastructure | Multi-select | — | Pool, gym, elevator, etc. |
| Near subway | Toggle | — | Proximity to metro |

---

## 12. Image CDN — Further Investigation Required

The photo URLs use relative filenames from the API:
```json
"photos": ["facade01.jpg", "facade02.jpg", "facade03.jpg"]
```

The base CDN is `content.loft.com.br/homes/` but requires authentication. To access listing photos programmatically:

1. First establish a session on `loft.com.br` via browser
2. Extract the session cookie/token
3. Use that token to access `https://content.loft.com.br/homes/{filename}`

Alternatively, the `__NEXT_DATA__` SSR payload in the listing detail page HTML may contain full image URLs with tokens embedded.

---

## 13. All API Services Discovered

| Service | Base URL | Purpose |
|---------|----------|---------|
| Landscape API | `landscape-api.loft.com.br` | Listing search, facets, maps, metadata, cities, neighborhoods |
| Recommendation API | `recommendation-api.loft.com.br` | Similar sold, playlist, stats, popular neigh. |
| API | `api.loft.com.br` | Credit, home feed, user events, partner API |
| Negotiation API | `negotiation-api.loft.com.br` | Negotiation offers/requests |
| Customer BFF | `customer-bff.loft.com.br` | Customer data |
| Buyer Profile | `buyer-profile.loft.com.br` | Buyer profiles |
| Buyer Leads | `buyer-leads.loft.com.br` | Buyer leads |
| Account BFF | `account-bff.loft.com.br` | Account management |
| Details API | `details.buyerld.loft-prod.io` | Listing details |
| Informational Pages | `informational-pages-api.loft.com.br` | Content pages |
| Demand API | `demand-api.loft.com.br` | Demand/projection data |
| SSO | `sso.loft.com.br` | Authentication (Keycloak) |
| Visit Availability | `visit-availability.loft.com.br` | Visit scheduling |
| Mortgage Tracker | `mortgage-tracker.cred.loft.com.br` | Financing tracking |
| Unified Portfolio | `unified-portfolio-manager-public.loft.com.br` | Portfolio management |
| Property Match | `property-match.loft.technology` | Property matching |
| LOFT Places | `loft-places.loft.com.br` | Location/places |
| User Location | `location.loft.com.br` | IP-based geolocation |
| Test Groups | `test-groups-api.loft.com.br` | A/B test assignment |
| Headless CMS | `headless-static-cms.loft.com.br` | Static content CMS |
| Content CDN | `content.loft.com.br` | Static assets + listing photos + agency logos |

---

## Notes

- All API tests were done **without authentication** — the Landscape and Recommendation APIs are unauthenticated
- The listing page (`loft.com.br/...`) is heavily protected by CloudFront WAF
- The API subdomains (`landscape-api`, `recommendation-api`, etc.) are **not** CloudFront-protected
- Photo URLs (`content.loft.com.br/homes/`) **are** CloudFront-protected
- Maximum default results per page: 20 (adjustable via `hitsPerPage`)
- Total listings nationwide: ~1,130,461 (as of 2026-06-21)
