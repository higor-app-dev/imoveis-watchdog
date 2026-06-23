"""
extractor — Extração de listagens do Biasi Leilões (biasileiloes.com.br).

Extrai dados de imóveis em leilão do site Biasi Leilões, que é um site ASP.NET
MVC 5 SSR sem API JSON pública. A extração é feita via scraping de HTML com
requests + BeautifulSoup.

Estratégia:
  1. Scrape páginas de listagem SSR (/leiloes/{parceiro}?pagina=N ou /Home/BuscaImoveis?...)
     para obter cards de imóveis com dados básicos (id, título, preços, status, foto).
  2. Opcionalmente, scrape páginas de detalhe (/sale/detail?id={NUM}) para obter
     dados completos (endereço, descrição, documentos, etc).
  3. Retorna dicts brutos compatíveis com from_biasi_listing() do parser.

Uso:
    from skills.biasi_leiloes.extractor import (
        extract_listings,
        extract_detail,
        extract_all,
    )

    # Extrair lista de imóveis (dados dos cards)
    imoveis = extract_listings(pages=3)

    # Extrair detalhes de um imóvel específico
    detalhe = extract_detail(id=57352)

    # Extrair tudo (lista + detalhes de cada um)
    todos = extract_all(pages=2, fetch_detail=True)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Dependencies ──────────────────────────────────────────────────────────────

try:
    import requests
except ImportError:
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

logger = logging.getLogger("biasi_leiloes_extractor")

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.biasileiloes.com.br"
CDN_BASE = "https://cdn-biasi.blueintra.com/images/lot"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.biasileiloes.com.br/",
}

# Partner bank slugs (used as the slug param for the AJAX search endpoint)
PARTNER_SLUGS = {
    "santander": "santander",
    "itau": "itau",
    "rodobens": "rodobenssa",
    "todos": "",  # All properties — empty slug
}

# AJAX search endpoint (returns HTML partial with listing cards)
AJAX_SEARCH_URL = "/Sale/LotListSearch"

# Items per page (AJAX pagination uses start/limit offset)
ITEMS_PER_PAGE = 48
MAX_PAGES = 50  # Safety cap

# Request timeout
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.3  # Delay between requests (avoid rate limiting)


# ── Session management ────────────────────────────────────────────────────────


def _get_session() -> requests.Session:
    """Create or reuse a requests Session with default headers."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    # Set a short keep-alive timeout
    session.headers["Connection"] = "keep-alive"
    return session


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _fetch_html(url: str, session: requests.Session | None = None) -> str | None:
    """Fetch HTML from a URL with error handling.

    Args:
        url: Full URL to fetch.
        session: Optional requests Session (creates one if not provided).

    Returns:
        HTML text string, or None on failure.
    """
    close_session = False
    if session is None:
        session = _get_session()
        close_session = True

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        # Detect encoding from Content-Type or meta tags
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"Erro ao buscar {url}: {e}")
        return None
    finally:
        if close_session:
            session.close()


# ── Listing page parsing ──────────────────────────────────────────────────────


def _parse_listing_page(html: str) -> list[dict[str, Any]]:
    """Parse listing cards from a Biasi Leilões SSR listing page.

    Extracts from each card:
      - id (from data-id attribute or URL)
      - titulo (card title)
      - url (detail page URL)
      - lote/number (lot number)
      - valor_primeira_praca (1st auction price)
      - valor_segunda_praca (2nd auction price)
      - status (liberado/não iniciado/vendido)
      - foto_principal (primary photo URL)

    Args:
        html: Full HTML of the listing page.

    Returns:
        List of raw dicts with card-level data.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("a.leilao-lote")
    listings: list[dict[str, Any]] = []

    for card in cards:
        listing: dict[str, Any] = {}

        # ── ID ─────────────────────────────────────────────────────────────
        listing["id"] = card.get("data-id", "")
        href = card.get("href", "")
        if not listing["id"] and href:
            m = re.search(r"id=(\d+)", href)
            if m:
                listing["id"] = m.group(1)

        # ── URL ────────────────────────────────────────────────────────────
        if href:
            listing["url"] = f"{BASE_URL}{href}" if href.startswith("/") else href

        # ── Title ──────────────────────────────────────────────────────────
        title_el = card.select_one("h5.card-title")
        if title_el:
            listing["titulo"] = title_el.get_text(strip=True)

        # ── Lot number ─────────────────────────────────────────────────────
        lot_label = card.select_one(".card-label span span")
        if lot_label:
            listing["lote"] = lot_label.get_text(strip=True)

        # ── Photo ──────────────────────────────────────────────────────────
        img_el = card.select_one(".card-img-cover")
        if img_el:
            style = str(img_el.get("style", ""))
            m = re.search(r"url\(['\"]?(https?://[^)\s\"']+)", style)
            if m:
                listing["foto_principal"] = m.group(1)
            else:
                m = re.search(r"url\(['\"]?([^)\s\"']+)", style)
                if m:
                    listing["foto_principal"] = m.group(1)

        # ── Prices ─────────────────────────────────────────────────────────
        price_spans = card.select(
            ".price-leiloes .price-line-2-pracas"
        )
        if len(price_spans) >= 1:
            listing["valor_primeira_praca"] = price_spans[0].get_text(strip=True)
        if len(price_spans) >= 2:
            listing["valor_segunda_praca"] = price_spans[1].get_text(strip=True)

        # ── Bid count ──────────────────────────────────────────────────────
        bid_el = card.select_one(".fa-gavel + span, .fa-gavel ~ span")
        if bid_el:
            text = bid_el.get_text(strip=True)
            m = re.search(r"(\d+)", text)
            if m:
                listing["num_lances"] = int(m.group(1))

        # ── Status ─────────────────────────────────────────────────────────
        status_el = card.select_one(
            ".label-md.status-green span, "
            ".label-md.status-orange span, "
            ".label-md.status-gray span, "
            "[class*='status-'] span"
        )
        if status_el:
            listing["status"] = status_el.get_text(strip=True)

        # ── Comitente / Partner logo ───────────────────────────────────────
        comitente_img = card.select_one("img.image-comitente")
        if comitente_img:
            src = comitente_img.get("src", "")
            if src:
                listing["comitente_logo"] = src

        # ── Infer partner from comitente ───────────────────────────────────
        partner = _infer_partner(listing)
        if partner:
            listing["nome_leilao"] = partner

        if listing.get("id"):
            listings.append(listing)

    logger.info(
        f"Parseados {len(listings)} cards da página de listagem"
    )
    return listings


def _infer_partner(listing: dict) -> str:
    """Try to infer the auction partner name from card data.

    Uses the comitente logo URL which often contains partner names.
    Falls back to empty string if not identifiable.
    """
    logo = listing.get("comitente_logo", "")
    if not logo:
        return ""

    logo_lower = logo.lower()
    if "santander" in logo_lower:
        return "Leilão Santander"
    elif "itau" in logo_lower or "itau" in logo_lower:
        return "Leilão Itaú"
    elif "rodobens" in logo_lower:
        return "Leilão Rodobens"
    return ""


# ── Detail page parsing ───────────────────────────────────────────────────────


def _parse_detail_page(html: str, listing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a Biasi Leilões property detail page.

    Extracts structured data from the SSR detail page at /sale/detail?id={NUM}.

    Args:
        html: Full HTML of the detail page.
        listing: Optional pre-populated dict from card data to merge with.

    Returns:
        Raw dict with all extractable fields from the detail page.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = listing.copy() if listing else {}

    # ── Title (h1) ─────────────────────────────────────────────────────────
    h1 = soup.select_one("h1")
    if h1:
        result["titulo"] = h1.get_text(strip=True)

    # ── Address subtitle ───────────────────────────────────────────────────
    # The address appears as a subtitle right after the h1
    address_el = h1.find_next_sibling(string=True) if h1 else None
    # Better: look for the address text that has /SP format
    address_texts = []
    for el in soup.select("main .container p, main div p, main span, h1 + *"):
        text = el.get_text(strip=True) if hasattr(el, "get_text") else str(el)
        # Address pattern: "Rua X, N - Bairro, Cidade/UF"
        if "/SP" in text or "/RJ" in text or "/MG" in text:
            address_texts.append(text)

    # Also look for the specific address near the h1
    main = soup.select_one("main")
    if main:
        for el in main.find_all(string=True):
            text = el.strip()
            if re.search(r"\w+/\w{2}$", text) and len(text) > 10 and len(text) < 200:
                address_texts.append(text)
                break

    if address_texts:
        result["endereco_completo"] = address_texts[0]
        # Try to extract structured address
        addr_parts = _parse_address(address_texts[0])
        result.update(addr_parts)

    # ── Auction dates ──────────────────────────────────────────────────────
    for heading in soup.select("h4"):
        text = heading.get_text(strip=True)
        m1 = re.search(r"1[°º]\s*Leilão\s*dia\s*(\d{2}/\d{2}/\d{4})\s*[àa]s\s*(\d{2})h(\d{2})?", text)
        if m1:
            hour = m1.group(2)
            minute = m1.group(3) or "00"
            result["data_primeiro_leilao"] = f"{m1.group(1)} {hour}:{minute}"

        m2 = re.search(r"2[°º]\s*Leilão\s*dia\s*(\d{2}/\d{2}/\d{4})\s*[àa]s\s*(\d{2})h(\d{2})?", text)
        if m2:
            hour = m2.group(2)
            minute = m2.group(3) or "00"
            result["data_segundo_leilao"] = f"{m2.group(1)} {hour}:{minute}"

    # ── Prices (from status section) ───────────────────────────────────────
    # Look for "Lance Inicial" text
    for el in soup.find_all(string=re.compile(r"Lance\s*Inicial")):
        parent = el.parent
        if parent:
            # Get the full text like "Lance Inicial - R$ 329.040,70"
            full_text = parent.get_text(strip=True)
            m = re.search(r"R\$\s*([\d.,]+)", full_text)
            if m:
                if "valor_primeira_praca" not in result:
                    result["valor_primeira_praca"] = m.group(1)

    # Look for "2° Leilão" price in the description text
    for el in soup.find_all(string=re.compile(r"2[°º]\s*Leilão.*Lance\s*Inicial\s*R\$")):
        m = re.search(r"R\$\s*([\d.,]+)", el)
        if m and "valor_segunda_praca" not in result:
            result["valor_segunda_praca"] = m.group(1)

    # ── Status ─────────────────────────────────────────────────────────────
    # Status appears as text with a specific class or near the gavel icon
    for el in soup.find_all(string=re.compile(
        r"Liberado para Lance|Não Iniciado|Vendido|Removido|Em andamento|Encerrado"
    )):
        text = el.strip()
        if len(text) < 40 and text not in ("Em andamento",):
            result["status"] = text
            break

    # ── Description ────────────────────────────────────────────────────────
    # The main description appears in multiple <p> tags with the property details
    desc_parts = []
    for p in soup.select("main p"):
        text = p.get_text(strip=True)
        if text and len(text) > 30 and "O imóvel" in text:
            desc_parts.append(text)

    if desc_parts:
        result["descricao"] = "\n\n".join(desc_parts)

    # ── Occupancy ──────────────────────────────────────────────────────────
    for el in soup.find_all(string=re.compile(
        r"Imóvel Ocupado|Imóvel Desocupado|Ocupado|Desocupado"
    )):
        text = el.strip()
        if text in ("Ocupado", "Desocupado"):
            result["ocupacao"] = text
            break
        elif "Imóvel Ocupado" in text or "imóvel ocupado" in text.lower():
            result["ocupacao"] = "Ocupado"
            break
        elif "Imóvel Desocupado" in text or "desocupado" in text.lower():
            result["ocupacao"] = "Desocupado"
            break

    # ── Cadastro Municipal (IPTU registration) ────────────────────────────
    for el in soup.find_all(string=re.compile(r"Cadastro Municipal")):
        m = re.search(r"Cadastro Municipal:\s*([\d.]+-?\d*)", el)
        if m:
            result["cadastro_municipal"] = m.group(1)

    # ── Matrícula (registration number) ────────────────────────────────────
    for el in soup.find_all(string=re.compile(r"matriculad[oa]")):
        m = re.search(r"n[°º]\s*([\d.]+)", el)
        if m:
            result["matricula"] = m.group(1)

    # ── Related files (edital, matrícula) ──────────────────────────────────
    for a in soup.select("a[href*='.pdf']"):
        href = a.get("href", "")
        text = a.get_text(strip=True).lower()
        if "edital" in text or "edital" in href.lower():
            result["edital_url"] = (
                f"{BASE_URL}{href}" if href.startswith("/") else href
            )
        elif "matrícula" in text or "matricula" in text.lower() or "matricula" in href.lower():
            result["matricula_url"] = (
                f"{BASE_URL}{href}" if href.startswith("/") else href
            )

    # ── WhatsApp number ────────────────────────────────────────────────────
    for a in soup.select("a[href*='wa.me'], a[href*='whatsapp']"):
        href = a.get("href", "")
        if href:
            result["whatsapp"] = href

    # ── Photos from gallery ────────────────────────────────────────────────
    # The main image on the detail page
    main_img = soup.select_one("main img[src*='cdn-biasi']")
    if main_img:
        src = main_img.get("src", "")
        if src and "foto_principal" not in result:
            result["foto_principal"] = src

    # Photo gallery buttons - check for multiple photos
    photos = []
    for img in soup.select("main img[src*='cdn-biasi']"):
        src = img.get("src", "")
        if src and src not in photos:
            photos.append(src)
    if photos:
        result["fotos"] = photos

    # ── Property characteristics from description ─────────────────────────
    desc = result.get("descricao", "")
    if desc:
        # Extract area
        area_m = re.search(r"área\s*(?:privativa|total|útil)?\s*(?:de\s*)?([\d.,]+)\s*m[²2]", desc, re.IGNORECASE)
        if area_m and "area_text" not in result:
            result["area_text"] = area_m.group(0)

        # Bedrooms
        quartos_m = re.search(r"(\d+)\s*(?:dormit[óo]ri[ao]s?|quartos?)", desc, re.IGNORECASE)
        if quartos_m and "quartos" not in result:
            result["quartos"] = int(quartos_m.group(1))

        # Parking
        vagas_m = re.search(r"(\d+)\s*vagas?\s*(?:de\s*garagem)?", desc, re.IGNORECASE)
        if vagas_m and "vagas" not in result:
            result["vagas"] = int(vagas_m.group(1))

        # Bathrooms
        banheiros_m = re.search(r"(\d+)\s*(?:W\.C\.|banheiros?|banh[óo]s?|wc)", desc, re.IGNORECASE)
        if banheiros_m and "banheiros" not in result:
            result["banheiros"] = int(banheiros_m.group(1))

    # ── Property type from title ──────────────────────────────────────────
    titulo = result.get("titulo", "")
    if titulo and "tipo_imovel" not in result:
        tipo = _infer_tipo_from_title(titulo)
        if tipo:
            result["tipo_imovel"] = tipo

    # ── City/State from title or breadcrumb ───────────────────────────────
    if "cidade" not in result or "uf" not in result:
        city_state = _extract_city_uf(titulo, result.get("endereco_completo", ""))
        if city_state:
            result.update(city_state)

    # ── Auction name from breadcrumb ───────────────────────────────────────
    breadcrumb_links = soup.select(".breadcrumb a, nav a, [class*='breadcrumb'] a")
    for link in breadcrumb_links:
        text = link.get_text(strip=True)
        if "Leilão" in text and len(text) > 10 and "nome_leilao" not in result:
            result["nome_leilao"] = text
            break

    # ── Data collection timestamp ─────────────────────────────────────────
    if "data_coleta" not in result:
        result["data_coleta"] = datetime.now(timezone.utc).isoformat()

    return result


def _parse_address(address: str) -> dict[str, str]:
    """Parse a Brazilian address string into structured fields.

    Handles formats like:
      - "Rua Clóvis Lordano, 140, Núcleo Santa Isabel, Hortolândia/SP"
      - "Av. Paulista, 1000, Bela Vista, São Paulo/SP"

    Returns:
        Dict with 'endereco', 'bairro', 'cidade', 'uf' keys.
    """
    result: dict[str, str] = {}

    if not address:
        return result

    # Extract UF and city from the last part: "Cidade/UF"
    uf_match = re.search(r"([\w\sÀ-ÿ-]+)/([A-Z]{2})$", address)
    if uf_match:
        result["cidade"] = uf_match.group(1).strip()
        result["uf"] = uf_match.group(2).strip()
        # Everything before the last "cidade/UF" segment
        before = address[: uf_match.start()].strip().rstrip(",")
    else:
        before = address

    # Split by commas to get street (with number), neighborhood
    parts = [p.strip() for p in before.split(",") if p.strip()]

    if len(parts) >= 1:
        result["endereco"] = parts[0]  # Street name (may not include number)
    if len(parts) >= 2:
        # If the last part is a number (street number), join it with the street
        # Otherwise it's a neighborhood name
        last_part = parts[-1].strip()
        if last_part.isdigit() or re.match(r"^\d+[a-zA-Z]?$", last_part):
            # Last part is a number → join with street, no neighborhood
            result["endereco"] = ", ".join(parts)
        else:
            # Last part is a neighborhood
            result["bairro"] = last_part
            if len(parts) >= 3:
                # Street + number from first 2 parts
                result["endereco"] = ", ".join(parts[:2])

    return result


def _infer_tipo_from_title(title: str) -> str | None:
    """Infer property type from the listing title.

    Args:
        title: Property listing title.

    Returns:
        Normalized property type, or None if not identifiable.
    """
    title_lower = title.lower()

    mappings = [
        ("apartamento", "apartamento"),
        ("casa", "casa"),
        ("kitnet", "kitnet"),
        ("cobertura", "cobertura"),
        ("studio", "studio"),
        ("flat", "flat"),
        ("loft", "loft"),
        ("sobrado", "sobrado"),
        ("terreno", "terreno"),
        ("sala comercial", "comercial"),
        ("sala", "comercial"),
        ("comercial", "comercial"),
        ("galpão", "comercial"),
        ("galpao", "comercial"),
        ("prédio", "comercial"),
        ("predio", "comercial"),
        ("loja", "comercial"),
    ]

    for keyword, tipo in mappings:
        if keyword in title_lower:
            return tipo

    # If the title doesn't contain a keyword, check if it ends with /SP
    # suggesting a generic property
    return None


def _extract_city_uf(
    title: str, address: str = ""
) -> dict[str, str] | None:
    """Extract city and UF from title or address text.

    Titles often end with city/UF format: "... — Cidade/UF" or "...Cidade/UF"
    """
    result: dict[str, str] = {}

    # Try from address first
    if address:
        m = re.search(r"([\w\sÀ-ÿ-]+)/([A-Z]{2})$", address)
        if m:
            result["cidade"] = m.group(1).strip()
            result["uf"] = m.group(2).strip()
            return result

    # Try from title: text before a dash at the end with /UF
    m = re.search(r"(?:—|–|-)\s*([\w\sÀ-ÿ]+)/([A-Z]{2})\s*$", title)
    if m:
        result["cidade"] = m.group(1).strip()
        result["uf"] = m.group(2).strip()
        return result

    # Try simpler: last 5 chars are /UF
    m = re.search(r"/([A-Z]{2})\s*$", title)
    if m:
        result["uf"] = m.group(1).strip()
        # City is the text before the /UF
        before = title[: m.start()].strip()
        # Get the last segment before /UF (could be dash-separated)
        parts = re.split(r"[—–\-]\s*", before)
        if parts:
            result["cidade"] = parts[-1].strip()
        return result

    return None if not result else result


# ── High-level extraction functions ──────────────────────────────────────────


def extract_listings(
    source: str = "santander",
    pages: int = 1,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Extract listing cards from Biasi Leilões SSR listing pages.

    Scrapes the partner-specific listing pages and returns card-level data
    (id, title, prices, status, photo) for each listing.

    Args:
        source: Partner slug ('santander', 'itau', 'rodobens', or 'todos').
        pages: Number of pages to extract (48 items per page).
        session: Optional requests Session for reuse.

    Returns:
        List of raw listing dicts from card data.
    """
    if requests is None or BeautifulSoup is None:
        raise ImportError(
            "Dependências necessárias: requests e beautifulsoup4.\n"
            "Instale com: pip install requests beautifulsoup4"
        )

    slug = PARTNER_SLUGS.get(source, PARTNER_SLUGS["santander"])
    all_listings: list[dict[str, Any]] = []

    close_session = False
    if session is None:
        session = _get_session()
        close_session = True

    # Add AJAX-specific headers
    ajax_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/leiloes/{slug}?pagina=1" if slug else f"{BASE_URL}/",
    }

    try:
        for page in range(1, pages + 1):
            start = (page - 1) * ITEMS_PER_PAGE
            params = {
                "start": start,
                "limit": ITEMS_PER_PAGE,
            }
            if slug:
                params["slug"] = slug

            url = f"{BASE_URL}{AJAX_SEARCH_URL}"
            session.headers.update(ajax_headers)

            logger.info(
                f"Buscando página {page}: start={start}, limit={ITEMS_PER_PAGE}"
            )
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text

            page_listings = _parse_listing_page(html)
            if not page_listings:
                logger.info(
                    f"Nenhum card encontrado na página {page}, "
                    f"fim da paginação"
                )
                break

            all_listings.extend(page_listings)

            # Polite delay between pages
            if page < pages:
                time.sleep(REQUEST_DELAY)

    finally:
        if close_session:
            session.close()

    logger.info(
        f"Extraídos {len(all_listings)} listings de {pages} página(s) "
        f"da fonte '{source}'"
    )
    return all_listings


def extract_detail(
    listing_id: str | int,
    card_data: dict[str, Any] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    """Extract full detail of a single property from its detail page.

    Args:
        listing_id: Numeric ID of the listing (from card data or URL).
        card_data: Optional pre-populated card data to merge with.
        session: Optional requests Session for reuse.

    Returns:
        Raw dict with full property details, or None on failure.
    """
    if requests is None or BeautifulSoup is None:
        raise ImportError(
            "Dependências necessárias: requests e beautifulsoup4.\n"
            "Instale com: pip install requests beautifulsoup4"
        )

    url = f"{BASE_URL}/sale/detail?id={listing_id}"

    close_session = False
    if session is None:
        session = _get_session()
        close_session = True

    try:
        html = _fetch_html(url, session)
        if html is None:
            logger.warning(f"Falha ao buscar detalhe do imóvel {listing_id}")
            return None

        result = _parse_detail_page(html, card_data)
        result["id"] = str(listing_id)
        logger.info(
            f"Detalhe extraído: {result.get('titulo', 'N/A')} "
            f"[{listing_id}]"
        )
        return result

    finally:
        if close_session:
            session.close()


def extract_all(
    source: str = "santander",
    pages: int = 2,
    fetch_detail: bool = False,
    max_detail_workers: int = 5,
) -> list[dict[str, Any]]:
    """Full extraction: listing cards → optional detail pages.

    Args:
        source: Partner slug or 'todos'.
        pages: Number of listing pages to scrape.
        fetch_detail: If True, also fetch detail pages for richer data.
        max_detail_workers: Max concurrent detail fetches.

    Returns:
        List of raw listing dicts (with detail data if fetch_detail=True).
    """
    if requests is None or BeautifulSoup is None:
        raise ImportError(
            "Dependências necessárias: requests e beautifulsoup4.\n"
            "Instale com: pip install requests beautifulsoup4"
        )

    logger.info(
        f"Iniciando extração Biasi Leilões (fonte={source}, "
        f"páginas={pages}, detalhes={fetch_detail})"
    )

    session = _get_session()
    try:
        # Step 1: Get listing cards
        listings = extract_listings(source=source, pages=pages, session=session)
        logger.info(f"Cards extraídos: {len(listings)}")

        if not fetch_detail:
            return listings

        # Step 2: Enrich with detail page data
        enriched: list[dict[str, Any]] = []
        for i, listing in enumerate(listings):
            listing_id = listing.get("id")
            if not listing_id:
                enriched.append(listing)
                continue

            detail = extract_detail(listing_id, card_data=listing, session=session)
            if detail:
                enriched.append(detail)
            else:
                enriched.append(listing)

            # Polite delay between detail fetches
            if i < len(listings) - 1:
                time.sleep(REQUEST_DELAY)

        logger.info(f"Extração completa: {len(enriched)} imóveis enriquecidos")
        return enriched

    finally:
        session.close()


# ── Convenience: extract all Imóveis (categoria=1) ────────────────────────────


def extract_imoveis(
    pages: int = 2,
    fetch_detail: bool = False,
) -> list[dict[str, Any]]:
    """Convenience wrapper: extract only 'Imóveis' category.

    Biasi categorias: 1=Imóveis, 2=Veículos, 3=Diversos.
    Imóveis are in the 'santander', 'itau', and 'rodobens' partner pages.

    This function extracts from all three partner sources and merges results.

    Args:
        pages: Pages per source.
        fetch_detail: If True, enrich with detail page data.

    Returns:
        Combined list of property listings from all partner sources.
    """
    all_listings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    sources = ["santander", "itau", "rodobens"]

    for source in sources:
        listings = extract_all(
            source=source, pages=pages, fetch_detail=fetch_detail
        )
        for listing in listings:
            lid = listing.get("id", "")
            if lid and lid not in seen_ids:
                seen_ids.add(lid)
                all_listings.append(listing)
            elif not lid:
                all_listings.append(listing)

    logger.info(
        f"Total de {len(all_listings)} imóveis únicos extraídos de "
        f"{len(sources)} fontes"
    )
    return all_listings


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for testing the extractor directly."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Biasi Leilões Extractor — extração SSR de imóveis"
    )
    sub = parser.add_subparsers(dest="command")

    # list: extract listing cards
    list_parser = sub.add_parser(
        "list", help="Extrai cards de listagem"
    )
    list_parser.add_argument(
        "--source", default="santander",
        choices=list(PARTNER_SLUGS.keys()),
        help="Fonte (parceiro)",
    )
    list_parser.add_argument(
        "--pages", type=int, default=2, help="Número de páginas"
    )
    list_parser.add_argument(
        "--output", "-o", help="Salvar resultado em arquivo JSON"
    )

    # detail: extract detail page
    detail_parser = sub.add_parser(
        "detail", help="Extrai detalhe de um imóvel"
    )
    detail_parser.add_argument("id", help="ID do imóvel")

    # all: extract + enrich
    all_parser = sub.add_parser(
        "all", help="Extrai cards + detalhes"
    )
    all_parser.add_argument(
        "--source", default="santander",
        choices=list(PARTNER_SLUGS.keys()),
        help="Fonte (parceiro)",
    )
    all_parser.add_argument(
        "--pages", type=int, default=2, help="Número de páginas"
    )
    all_parser.add_argument(
        "--output", "-o", help="Salvar resultado em arquivo JSON"
    )

    # imoveis: extract only properties from all partners
    imoveis_parser = sub.add_parser(
        "imoveis", help="Extrai imóveis de todos os parceiros"
    )
    imoveis_parser.add_argument(
        "--pages", type=int, default=1, help="Páginas por parceiro"
    )
    imoveis_parser.add_argument(
        "--detail", action="store_true", help="Incluir dados de detalhe"
    )
    imoveis_parser.add_argument(
        "--output", "-o", help="Salvar resultado em arquivo JSON"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )

    if args.command == "list":
        listings = extract_listings(
            source=args.source, pages=args.pages
        )
        print(f"\nExtraídos {len(listings)} cards de '{args.source}'")
        if listings:
            print(f"  Amostra: {listings[0].get('titulo', 'N/A')}")
            print(f"  Preços: 1ª={listings[0].get('valor_primeira_praca', 'N/A')}")
        if args.output:
            _save_json(listings, args.output)

    elif args.command == "detail":
        detail = extract_detail(args.id)
        if detail:
            print(json.dumps(detail, indent=2, ensure_ascii=False))
        else:
            print(f"Erro: não foi possível extrair detalhe do imóvel {args.id}")
            sys.exit(1)

    elif args.command == "all":
        listings = extract_all(
            source=args.source, pages=args.pages, fetch_detail=True
        )
        print(
            f"\nExtraídos {len(listings)} imóveis de '{args.source}' "
            f"com detalhes"
        )
        if listings:
            sample = listings[0]
            print(f"  Amostra: {sample.get('titulo', 'N/A')}")
            print(
                f"  Cidade: {sample.get('cidade', 'N/A')}/"
                f"{sample.get('uf', 'N/A')}"
            )
        if args.output:
            _save_json(listings, args.output)

    elif args.command == "imoveis":
        listings = extract_imoveis(
            pages=args.pages, fetch_detail=args.detail
        )
        print(f"\nExtraídos {len(listings)} imóveis únicos")
        if listings:
            precos = [
                _parse_price(l.get("valor_primeira_praca", ""))
                for l in listings
                if l.get("valor_primeira_praca")
            ]
            if precos:
                precos_f = [p for p in precos if p is not None]
                if precos_f:
                    print(
                        f"  Preços: R$ {min(precos_f):.0f} ~ "
                        f"R$ {max(precos_f):.0f}"
                    )
        if args.output:
            _save_json(listings, args.output)

    else:
        parser.print_help()


def _parse_price(price_str: str) -> float | None:
    """Parse a Brazilian price string to float."""
    if not price_str or not isinstance(price_str, str):
        return None
    s = re.sub(r"R\$\s*", "", price_str).strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _save_json(data: Any, path: str) -> None:
    """Save data to a JSON file."""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(path_obj, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Salvo em: {path_obj.resolve()}")


if __name__ == "__main__":
    main()
