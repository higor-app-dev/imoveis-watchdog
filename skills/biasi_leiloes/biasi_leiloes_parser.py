"""
biasi_leiloes_parser — Parser for Biasi Leilões (biasileiloes.com.br) listings.

Converts data extracted from Biasi Leilões SSR HTML pages (auction detail pages,
search result pages, AJAX partials) into the unified Imovel schema used by the
watchdog pipeline.

Site structure:
    - ASP.NET MVC 4.x SSR on GoCache CDN (no Cloudflare, no bot protection)
    - AJAX-loaded partials: GET /Sale/LotListSearch?start=0&limit=20&categoria=1
    - Detail page: /sale/detail?id={NUM}
    - Auction listing pages: /leilao/{id}/{slug}
    - Bank-specific pages: /leiloes/santander, /leiloes/itau, /leiloes/rodobenssa
    - Pagination: ?pagina=N

Image CDN:
    - Base: https://cdn-biasi.blueintra.com/images/lot/{XX}/{YY}/{size}/{imageId}.jpg
    - Sizes: 250, 500, 1000 (use 1000 for high-res)
    - Partition: {XX} = first 2 chars of imageId, {YY} = chars 3-4 of imageId
    - Example: id=1564035 → XX=15, YY=64 → /images/lot/15/64/1000/1564035.jpg

Functions:
    from_biasi_listing(dict) -> dict | None
        Convert a single detail-page dict to unified schema.
    from_biasi_payload(dict|list) -> list[dict]
        Convert bulk data (list of listings) to list of unified dicts.
    run_scraper(...) -> list[dict]
        Run extraction and return parsed results.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Schema import ────────────────────────────────────────────────────────────

_hermes_path = Path.home() / ".hermes"
if str(_hermes_path) not in sys.path:
    sys.path.insert(0, str(_hermes_path))

try:
    from imovel_schema import Imovel
except ImportError:
    Imovel = None  # Fallback: return dict if Imovel is not available

logger = logging.getLogger("biasi_leiloes_parser")

# ── Constants ────────────────────────────────────────────────────────────────

FONTE = "biasileiloes"

CDN_BASE = "https://cdn-biasi.blueintra.com/images/lot"

# Standard sizes available on the CDN
PHOTO_SIZES = {"thumb": 250, "medium": 500, "large": 1000}
DEFAULT_PHOTO_SIZE = 1000

# Auction status strings (Portuguese)
STATUS_LIBERADO = "Liberado para Lance"
STATUS_NAO_INICIADO = "Não Iniciado"
STATUS_VENDIDO = "Vendido"
STATUS_REMOVIDO = "Removido"

# Property type keywords from description text
TIPO_KEYWORDS = [
    ("apartamento", "apartamento"),
    ("casa", "casa"),
    ("kitnet", "kitnet"),
    ("cobertura", "cobertura"),
    ("studio", "studio"),
    ("flat", "flat"),
    ("loft", "loft"),
    ("sobrado", "sobrado"),
    ("terreno", "terreno"),
    ("casa em condomínio", "casa_condominio"),
    ("casa em condominio", "casa_condominio"),
    ("comercial", "comercial"),
    ("sala comercial", "comercial"),
    ("ponto comercial", "comercial"),
    ("galpão", "comercial"),
    ("galpao", "comercial"),
    ("prédio", "comercial"),
    ("predio", "comercial"),
]

# ── Photo URL helpers ────────────────────────────────────────────────────────


def _derive_partition(image_id: str) -> tuple[str, str]:
    """Derive the CDN partition (XX/YY) from an image ID.

    Partition logic:
        XX = first 2 characters of image_id
        YY = characters 3-4 of image_id (zero-padded if needed)

    Args:
        image_id: Numeric image ID string (e.g. '1564035').

    Returns:
        Tuple of (xx, yy) partition components.
    """
    image_id = str(image_id).strip()
    # Pad with leading zeros to at least 4 chars for partition derivation
    padded = image_id.zfill(4)
    xx = padded[:2]
    yy = padded[2:4]
    return xx, yy


def _normalize_photo_url(
    url: Any,
    size: int = DEFAULT_PHOTO_SIZE,
) -> str | None:
    """Normalize a raw photo value to an absolute CDN URL.

    Handles:
      - Already absolute HTTP(S) URL → pass through
      - Numeric image ID → construct CDN URL with partition
      - String with only digits → treat as image ID
      - Dict with 'url' or 'src' key
      - None / empty → return None

    Args:
        url: Raw photo value from detail page data.
        size: CDN size variant (250, 500, or 1000).

    Returns:
        Absolute CDN URL string, or None if invalid.
    """
    if not url:
        return None

    # Dict format (e.g. {"url": "1564035"})
    if isinstance(url, dict):
        url = url.get("url") or url.get("src") or url.get("id") or None
        if not url:
            return None

    if not isinstance(url, (str, int, float)):
        return None

    url_str = str(url).strip()

    if not url_str:
        return None

    # Already absolute HTTP(S) URL
    if url_str.startswith("http://") or url_str.startswith("https://"):
        return url_str

    # If it looks like a numeric image ID, construct CDN URL
    if url_str.isdigit():
        image_id = url_str
        xx, yy = _derive_partition(image_id)
        return f"{CDN_BASE}/{xx}/{yy}/{size}/{image_id}.jpg"

    # Otherwise treat as a relative path or filename
    return url_str


def _collect_photos(
    raw: dict,
    size: int = DEFAULT_PHOTO_SIZE,
) -> list[str]:
    """Collect and normalize all photo URLs from a raw listing dict.

    Sources (in priority order):
      1. `og_image` — from <meta property="og:image"> on detail page
      2. `fotos` — array of image IDs or URLs
      3. `images` — array (alternative field)
      4. `foto_principal` — single primary photo
      5. `imagem_principal` — single primary photo (alternative name)

    Returns:
        Deduplicated list of absolute CDN URLs.
    """
    seen: set[str] = set()
    urls: list[str] = []

    candidates: list[str] = []

    # Source 1: OG image (cover)
    og_image = raw.get("og_image") or raw.get("ogImage") or raw.get("meta_og_image")
    og_normalized = _normalize_photo_url(og_image, size=size)

    # Source 2: fotos[] array
    raw_fotos = raw.get("fotos") or raw.get("photos") or []
    if isinstance(raw_fotos, list):
        for p in raw_fotos:
            normalized = _normalize_photo_url(p, size=size)
            if normalized:
                candidates.append(normalized)
    elif isinstance(raw_fotos, str) and raw_fotos.strip():
        # Single foto as string
        normalized = _normalize_photo_url(raw_fotos, size=size)
        if normalized:
            candidates.append(normalized)

    # Source 3: images[] (alternative field)
    raw_images = raw.get("images") or raw.get("imagens") or []
    if isinstance(raw_images, list):
        for p in raw_images:
            normalized = _normalize_photo_url(p, size=size)
            if normalized:
                candidates.append(normalized)

    # Source 4: individual photo fields
    for key in ("foto_principal", "imagem_principal", "foto_capa", "cover_image"):
        val = raw.get(key)
        if val:
            normalized = _normalize_photo_url(val, size=size)
            if normalized:
                candidates.append(normalized)

    # Build final list: OG image first, then deduped rest
    if og_normalized:
        urls.append(og_normalized)
        seen.add(og_normalized)

    for url in candidates:
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def _generate_all_resolutions(foto_url: str) -> dict[str, str] | None:
    """Generate all available CDN resolutions for a photo URL.

    The Biasi CDN has 3 pre-rendered sizes:
      - large: 1000px (default, ~317KB)
      - medium: 500px (~112KB)
      - thumb: 250px (~35KB)

    Works with both absolute CDN URLs and numeric image IDs.
    Returns None if the input can't be parsed.

    Args:
        foto_url: Absolute CDN URL or numeric image ID.

    Returns:
        Dict with 'original', 'large', 'medium', 'thumb' keys,
        or None if unparseable.
    """
    if not foto_url:
        return None

    url_str = str(foto_url).strip()
    if not url_str:
        return None

    # Build the base URL for large (1000) — or use as-is if already absolute
    if url_str.startswith("http://") or url_str.startswith("https://"):
        # Extract the image ID from the URL pattern
        m = re.search(r"/images/lot/\d+/\d+/\d+/(\d+)\.jpg", url_str)
        if m:
            image_id = m.group(1)
        else:
            # Can't parse — return just the original URL
            return {"original": url_str}
    elif url_str.isdigit():
        image_id = url_str
    else:
        return None

    xx, yy = _derive_partition(image_id)

    result: dict[str, str] = {
        "original": f"{CDN_BASE}/{xx}/{yy}/1000/{image_id}.jpg",
    }
    for size_name, size_val in PHOTO_SIZES.items():
        result[size_name] = (
            f"{CDN_BASE}/{xx}/{yy}/{size_val}/{image_id}.jpg"
        )
    return result


# ── Text parsing helpers ─────────────────────────────────────────────────────


def _parse_area_text(text: str | None) -> float | None:
    """Extract area in m² from a description string.

    Handles formats:
      - '73,7600 m²'
      - '73.7600 m²'
      - '73,76 m²'
      - '120 m²'
      - 'área total de 150m²'
      - '150,00m²'

    Portuguese decimal comma is normalized to dot.

    Args:
        text: Description text or area string to parse.

    Returns:
        Area in m² as float, or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    # Pattern: number followed by optional whitespace and m²/m2
    # The number can use comma as decimal separator (Portuguese convention)
    # or dot. The integer part may use dots as thousands separators.
    patterns = [
        # "73,7600 m²" or "73.7600 m2"
        r"(\d{1,3}(?:[.,]\d{3})*(?:[,.]\d+)?)\s*m[²2]",
        # "150m²" without space
        r"(\d{1,3}(?:[.,]\d{3})*(?:[,.]\d+)?)m[²2]",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Take the last match (often most specific)
            raw = matches[-1]
            # Normalize: remove thousands separators, convert comma to dot
            # First, if there's a comma used as decimal, handle it
            if "," in raw:
                # Could be "1.500,00" (Brazilian) or "73,7600"
                # Strategy: remove all dots first (thousands separators in PT-BR),
                # then replace remaining comma with dot
                if "." in raw:
                    # "1.500,00" → remove dots → "1500,00" → replace comma → "1500.00"
                    raw = raw.replace(".", "")
                raw = raw.replace(",", ".")
            elif "." in raw and raw.count(".") > 1:
                # "1.500.00" or "73.7600" - ambiguous
                # If more than one dot, could be thousands separators
                # Try removing all dots. If result makes sense, use it.
                no_dots = raw.replace(".", "")
                if no_dots.isdigit():
                    raw = no_dots
                # Otherwise leave as-is
            try:
                return float(raw)
            except (ValueError, TypeError):
                continue

    return None


def _parse_bedrooms_text(text: str | None) -> int | None:
    """Extract number of bedrooms from a description string.

    Handles formats:
      - '03 dormitórios'
      - '3 dormitorios'
      - '03 Dormitórios'
      - '2 quartos'
      - '1 suíte + 2 dormitórios' → returns 3 (total bedrooms)
      - 'suíte máster + 2 dormitórios'

    Args:
        text: Description text to parse.

    Returns:
        Number of bedrooms as int, or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    text_lower = text.lower()

    total = 0
    found = False

    # Pattern 1: N dormitórios or N dormitorios
    matches = re.findall(r"(\d+)\s*dormit[óo]ri[ao]s?", text_lower)
    for m in matches:
        total += int(m)
        found = True

    # Pattern 2: N quartos
    matches = re.findall(r"(\d+)\s*quartos?", text_lower)
    for m in matches:
        if int(m) > total:  # "quartos" might be broader than "dormitórios"
            total = int(m)
            found = True

    # Pattern 3: N suítes + N dormitórios → sum them
    # Already handled by patterns above if both appear

    return total if found else None


def _extract_vagas_text(text: str | None) -> int | None:
    """Extract number of parking spots from description.

    Handles formats:
      - '2 vagas'
      - '03 vagas de garagem'
      - '1 vaga'

    Args:
        text: Description text to parse.

    Returns:
        Number of parking spots as int, or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    text_lower = text.lower()

    matches = re.findall(r"(\d+)\s*vagas?\s*(?:de\s*garagem)?", text_lower)
    if matches:
        return int(matches[-1])  # Last match is usually most specific

    return None


def _infer_tipo(text: str | None, titulo: str | None = None) -> str:
    """Infer property type from description text and/or title.

    Args:
        text: Description body text.
        titulo: Listing title.

    Returns:
        Normalized property type string (e.g. 'apartamento', 'casa').
    """
    combined = ""
    if titulo:
        combined += titulo.lower() + " "
    if text:
        combined += text.lower()

    for keyword, tipo in TIPO_KEYWORDS:
        if keyword in combined:
            return tipo

    return "apartamento"  # Default for auctions (most common)


def _parse_money_br(raw: Any) -> float | None:
    """Parse Brazilian currency value from string or number.

    Handles:
      - 'R$ 450.000,00'
      - '350000,00'
      - '450000'
      - 450000 (int)
      - 'R$ 1.200.000,00'

    Args:
        raw: Raw currency value.

    Returns:
        Float value, or None if unparseable.
    """
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        return float(raw)

    if not isinstance(raw, str) or not raw.strip():
        return None

    s = raw.strip()

    # Remove 'R$' prefix, any whitespace
    s = re.sub(r"^R\$\s*", "", s).strip()

    # If empty after cleanup
    if not s:
        return None

    # Try parsing as-is (might already be a plain number)
    try:
        return float(s)
    except ValueError:
        pass

    # Brazilian format: "1.200.000,00" or "450.000,00"
    # Remove dots (thousands separators), replace comma with dot
    # Strategy: if there's a comma, it's the decimal separator
    if "," in s:
        s = s.replace(".", "")  # Remove thousands separators
        s = s.replace(",", ".")  # Convert decimal comma to dot
        try:
            return float(s)
        except ValueError:
            return None

    # Plain number with dots as thousand separators (e.g. "1.200.000")
    if "." in s:
        # If it has more than one dot, use as thousand separators
        parts = s.split(".")
        if len(parts) > 2:
            s = "".join(parts)
            try:
                return float(s)
            except ValueError:
                return None

    try:
        return float(s)
    except ValueError:
        return None



def _extract_cidade_uf_from_titulo(titulo: str) -> tuple[str, str]:
    """Extract cidade and UF from a Biasi title string.

    Biasi titles follow the pattern ``... - Cidade/UF`` or ``... em Cidade/UF``.
    This function handles both cases by first trying to split on `` - `` and
    falling back to matching the last preposition before ``/UF``.

    Args:
        titulo: Raw title from the listing (e.g. ``"Casa no Centro - Cachoeira Do Sul/RS"``).

    Returns:
        Tuple of (cidade, uf). Both are empty strings if extraction fails.
    """
    if not titulo:
        return "", ""

    m = re.search(r"/([A-Z]{2})\s*$", titulo)
    if not m:
        return "", ""

    uf = m.group(1)
    before_uf = titulo[: m.start()].strip()

    # Strategy 1: split on ' - ' (dash-space, most common)
    parts = before_uf.split(" - ")
    if len(parts) > 1:
        cidade = parts[-1].strip()
        cidade = re.sub(
            r"^(?:em |de |no |na |do |da |dos |das )",
            "",
            cidade,
            flags=re.IGNORECASE,
        ).strip()
        if cidade and len(cidade) > 2:
            return cidade, uf

    # Strategy 2: match the LAST preposition before /UF (titles without dash)
    m2 = re.search(
        r".*\b(?:em |de |no |na |do |da |dos |das )\s*"
        r"([A-Za-z\xc0-\xff][A-Za-z\xc0-\xff ]*?)\s*$",
        before_uf,
    )
    if m2:
        cidade = m2.group(1).strip()
        if cidade and len(cidade) > 2:
            return cidade, uf

    # Fallback: return the full string before /UF
    return before_uf, uf


def _parse_date_br(date_str: str | None) -> str | None:
    """Parse a Brazilian date/time string to ISO 8601.

    Handles:
      - '21/06/2026 14:30'
      - '21/06/2026'
      - '21/06/2026 às 14:30'

    Args:
        date_str: Raw date string in Brazilian format.

    Returns:
        ISO 8601 datetime string, or None if unparseable.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    s = date_str.strip()

    # Remove "às" separator
    s = re.sub(r"\s*[àa]s\s*", " ", s).strip()

    # Try with time: DD/MM/YYYY HH:MM
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}):(\d{2})", s)
    if m:
        day, month, year, hour, minute = m.groups()
        try:
            dt = datetime(
                int(year), int(month), int(day),
                int(hour), int(minute),
                tzinfo=timezone.utc if False else None,
            )
            return dt.isoformat()
        except ValueError:
            pass

    # Try date only: DD/MM/YYYY
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        day, month, year = m.groups()
        try:
            dt = datetime(int(year), int(month), int(day), tzinfo=timezone.utc if False else None)
            return dt.isoformat()
        except ValueError:
            pass

    return None


# ── Field mapping: detail page -> Imovel ─────────────────────────────────────

FIELD_MAP = {
    # Direct field mappings (raw key → destination key)
    "id": "id",
    "titulo": "titulo",
    "url": "url",
    "descricao": "descricao",
    "endereco": "endereco",
    "bairro": "bairro",
    "cidade": "cidade",
    "uf": "uf",
    "cep": "cep",
    "preco_venda": "preco_venda",
    "preco_anterior": "preco_anterior",
    "status": "status",
    "tipo": "tipo",
    "area": "area",
    "quartos": "quartos",
    "vagas": "vagas",
    "banheiros": "banheiros",
    "fotos": "fotos",
    "agencia": "agencia",
    "data_coleta": "data_coleta",
    "data_publicacao": "data_publicacao",
    "disponivel": "disponivel",
    "origem_id": "origem_id",
    "raw_id": "raw_id",
}

# ── Main conversion functions ────────────────────────────────────────────────


def _make_id(raw: dict) -> str:
    """Build a unique id for the listing.

    Priority:
      1. 'id' field (already set)
      2. 'lote' (lot number) or 'codigo'
      3. 'id_leilao' + 'id_lote'
      4. 'url' hash
    """
    listing_id = raw.get("id")
    if listing_id:
        return str(listing_id)

    lote = raw.get("lote") or raw.get("codigo") or raw.get("lot_number")
    if lote:
        return f"biasi_{lote}"

    leilao_id = raw.get("id_leilao") or raw.get("auction_id")
    lote_id = raw.get("id_lote") or raw.get("lot_id")
    if leilao_id and lote_id:
        return f"biasi_{leilao_id}_{lote_id}"

    url = raw.get("url", "")
    if url:
        # Use last path segment as id
        m = re.search(r"id=(\d+)", url)
        if m:
            return f"biasi_{m.group(1)}"

    return ""


def _make_url(raw: dict) -> str:
    """Build the detail page URL if not already present."""
    url = raw.get("url", "")
    if url:
        return url

    listing_id = raw.get("id") or raw.get("lote") or raw.get("codigo")
    if listing_id:
        return f"https://www.biasileiloes.com.br/sale/detail?id={listing_id}"

    return ""


def from_biasi_listing(raw: dict) -> dict | Any | None:
    """Convert a raw Biasi Leilões detail page dict to the unified schema.

    Accepts structured data extracted from:
      - SSR HTML detail page (/sale/detail?id={NUM})
      - AJAX partial HTML (/Sale/LotListSearch?...)
      - Any structured dict with Biasi field names

    Args:
        raw: Dict with listing fields extracted from the Biasi page.

    Returns:
        Dict in the unified Imovel schema (or Imovel instance if available).
        None if input is invalid.
    """
    if raw is None or not isinstance(raw, dict):
        return None

    mapped: dict[str, Any] = {}

    # ── Direct field mapping ──────────────────────────────────────────────
    for src_key, dst_key in FIELD_MAP.items():
        if src_key in raw and raw[src_key] is not None:
            mapped[dst_key] = raw[src_key]

    # ── Id ─────────────────────────────────────────────────────────────────
    mapped["id"] = _make_id(raw)

    # ── URL ────────────────────────────────────────────────────────────────
    mapped["url"] = _make_url(raw)

    # ── Title ──────────────────────────────────────────────────────────────
    if "titulo" not in mapped:
        mapped["titulo"] = raw.get("title") or raw.get("titulo_anuncio") or ""

    # ── Source / fonte ─────────────────────────────────────────────────────
    mapped["fonte"] = FONTE

    # ── Description ────────────────────────────────────────────────────────
    descricao = mapped.get("descricao", "")
    if not descricao:
        descricao = raw.get("descricao") or raw.get("description") or raw.get("texto") or ""
    mapped["descricao"] = str(descricao) if descricao else ""

    # ── Address ────────────────────────────────────────────────────────────
    endereco = mapped.get("endereco", "")
    if not endereco:
        endereco = (
            raw.get("endereco")
            or raw.get("address")
            or raw.get("logradouro")
            or ""
        )
    mapped["endereco"] = str(endereco) if endereco else ""

    bairro = mapped.get("bairro", "")
    if not bairro:
        bairro = raw.get("bairro") or raw.get("neighborhood") or raw.get("bairro_imovel") or ""
    mapped["bairro"] = str(bairro) if bairro else ""

    cidade = mapped.get("cidade", "")
    if not cidade:
        cidade = raw.get("cidade") or raw.get("city") or raw.get("cidade_imovel") or ""
    if not cidade:
        # Fallback: extract from title (Biasi titles end with "Cidade/UF")
        titulo = mapped.get("titulo", "")
        cidade, uf_from_tit = _extract_cidade_uf_from_titulo(titulo)
        if cidade:
            mapped["uf"] = uf_from_tit
    mapped["cidade"] = str(cidade) if cidade else ""

    uf = mapped.get("uf", "")
    if not uf:
        uf = raw.get("uf") or raw.get("state") or raw.get("estado") or ""
    if not uf:
        # Fallback: extract from title
        titulo = mapped.get("titulo", "")
        _, uf_from_tit = _extract_cidade_uf_from_titulo(titulo)
        if uf_from_tit:
            uf = uf_from_tit
    mapped["uf"] = str(uf).upper() if uf else ""

    # ── Auction-specific fields ───────────────────────────────────────────
    mapped["nome_leilao"] = raw.get("nome_leilao") or raw.get("auction_name") or raw.get("nome") or ""
    mapped["numero_lote"] = raw.get("lote") or raw.get("lot_number") or raw.get("num_lote") or ""
    mapped["leilao_url"] = raw.get("leilao_url") or raw.get("auction_url") or ""

    # ── Auction dates ─────────────────────────────────────────────────────
    mapped["data_primeiro_leilao"] = _parse_date_br(
        raw.get("data_primeiro_leilao")
        or raw.get("first_auction_date")
        or raw.get("data_1_leilao")
    ) or ""
    mapped["data_segundo_leilao"] = _parse_date_br(
        raw.get("data_segundo_leilao")
        or raw.get("second_auction_date")
        or raw.get("data_2_leilao")
    ) or ""

    # ── Prices ────────────────────────────────────────────────────────────
    # Starting bid (1st auction)
    mapped["preco_venda"] = _parse_money_br(
        raw.get("preco_venda")
        or raw.get("lance_inicial")
        or raw.get("starting_bid")
        or raw.get("valor_primeiro_leilao")
        or raw.get("valor_primeira_praca")
        or raw.get("preco")
    )

    # 2nd auction starting bid
    mapped["preco_segundo_leilao"] = _parse_money_br(
        raw.get("preco_segundo_leilao")
        or raw.get("lance_inicial_2")
        or raw.get("second_auction_bid")
        or raw.get("valor_segundo_leilao")
        or raw.get("valor_segunda_praca")
    )

    # ── Status ────────────────────────────────────────────────────────────
    status = mapped.get("status", "")
    if not status:
        status = raw.get("status") or raw.get("situacao") or raw.get("badge") or ""
    mapped["status"] = str(status) if status else ""

    if "disponivel" not in mapped:
        # Infer from status
        s = mapped.get("status", "").lower()
        mapped["disponivel"] = not any(
            kw in s for kw in ("vendido", "removido", "cancelado", "inativo")
        )

    # ── Occupancy ─────────────────────────────────────────────────────────
    mapped["ocupacao"] = raw.get("ocupacao") or raw.get("occupancy") or raw.get("ocupado") or ""

    # ── Property characteristics (from description or direct fields) ─────
    desc_text = mapped.get("descricao", "")

    # Area
    if "area" not in mapped or not mapped["area"]:
        mapped["area"] = _parse_area_text(
            raw.get("area_text") or raw.get("area")
        )
    if not mapped.get("area"):
        mapped["area"] = _parse_area_text(desc_text)

    # Bedrooms
    if "quartos" not in mapped or mapped["quartos"] is None:
        mapped["quartos"] = (
            _parse_int(raw.get("quartos"))
            or _parse_int(raw.get("dormitorios"))
            or _parse_int(raw.get("bedrooms"))
        )
    if mapped["quartos"] is None:
        mapped["quartos"] = _parse_bedrooms_text(desc_text)

    # Parking
    if "vagas" not in mapped or mapped["vagas"] is None:
        mapped["vagas"] = (
            _parse_int(raw.get("vagas"))
            or _parse_int(raw.get("garagem"))
            or _parse_int(raw.get("parking_spots"))
        )
    if mapped["vagas"] is None:
        mapped["vagas"] = _extract_vagas_text(desc_text)

    # Bathrooms
    if "banheiros" not in mapped or mapped["banheiros"] is None:
        mapped["banheiros"] = (
            _parse_int(raw.get("banheiros"))
            or _parse_int(raw.get("bathrooms"))
        )

    # Property type
    if "tipo" not in mapped or not mapped["tipo"]:
        mapped["tipo"] = (
            raw.get("tipo")
            or raw.get("tipo_imovel")
            or raw.get("property_type")
            or ""
        )
    if not mapped.get("tipo"):
        mapped["tipo"] = _infer_tipo(desc_text, mapped.get("titulo"))
    # Normalize to lowercase for Imovel schema compatibility
    if mapped.get("tipo"):
        mapped["tipo"] = mapped["tipo"].lower().strip()

    # ── Registration / legal fields ────────────────────────────────────────
    mapped["cadastro_municipal"] = (
        raw.get("cadastro_municipal")
        or raw.get("cadastro_municipal_imovel")
        or raw.get("sql")
        or ""
    )
    mapped["matricula"] = (
        raw.get("matricula")
        or raw.get("registration")
        or raw.get("numero_matricula")
        or ""
    )

    # ── Edital PDF ─────────────────────────────────────────────────────────
    mapped["edital_url"] = (
        raw.get("edital_url")
        or raw.get("edital_pdf")
        or raw.get("edital")
        or ""
    )

    # ── WhatsApp contact ───────────────────────────────────────────────────
    mapped["whatsapp"] = (
        raw.get("whatsapp")
        or raw.get("whatsapp_contact")
        or raw.get("whatsapp_link")
        or ""
    )

    # ── Photos ─────────────────────────────────────────────────────────────
    mapped["fotos"] = _collect_photos(raw)
    mapped["image_urls"] = []
    for foto_url in mapped["fotos"]:
        resolutions = _generate_all_resolutions(foto_url)
        if resolutions:
            mapped["image_urls"].append(resolutions)

    # Vehicle-specific fields (not always applicable to property auctions)
    mapped["placa"] = raw.get("placa") or raw.get("plate") or ""
    mapped["ano_fabricacao"] = raw.get("ano_fabricacao") or raw.get("year") or ""
    mapped["km"] = raw.get("km") or raw.get("quilometragem") or ""

    # ── Amenities ──────────────────────────────────────────────────────────
    amenities = mapped.get("amenities", [])
    if not amenities:
        amenities = raw.get("amenities") or raw.get("comodidades") or []
        if isinstance(amenities, str):
            amenities = [a.strip() for a in amenities.split(",") if a.strip()]
    mapped["amenities"] = list(amenities) if isinstance(amenities, (list, tuple)) else []

    # ── Data collection timestamp ─────────────────────────────────────────
    if "data_coleta" not in mapped or not mapped["data_coleta"]:
        mapped["data_coleta"] = datetime.now(timezone.utc).isoformat()

    # ── Type conversions ──────────────────────────────────────────────────
    for num_field in ["preco_venda", "preco_segundo_leilao", "area"]:
        val = mapped.get(num_field)
        if val is not None and not isinstance(val, float):
            try:
                mapped[num_field] = float(val)
            except (ValueError, TypeError):
                mapped[num_field] = None

    for int_field in ["quartos", "banheiros", "vagas", "ano_fabricacao"]:
        val = mapped.get(int_field)
        if val is not None and not isinstance(val, int):
            try:
                mapped[int_field] = int(val)
            except (ValueError, TypeError):
                mapped[int_field] = None

    # ── Imovel construction ───────────────────────────────────────────────
    # Build result dict: start with Imovel's known fields, then overlay
    # Biasi-specific extra fields that Imovel doesn't know about.
    if Imovel is not None:
        try:
            # Get only the fields that Imovel knows about
            imovel_known = {
                k: v for k, v in mapped.items()
                if k in Imovel.__dataclass_fields__
            }
            imovel_obj = Imovel.from_dict(imovel_known)
            result = imovel_obj.to_dict()
        except Exception as e:
            logger.warning(f"Erro ao criar Imovel: {e}")
            result = dict(mapped)
    else:
        result = dict(mapped)

    # Overlay Biasi-specific extra fields (not in Imovel dataclass)
    extra_keys = [
        "preco_segundo_leilao", "nome_leilao", "numero_lote",
        "leilao_url", "data_primeiro_leilao", "data_segundo_leilao",
        "ocupacao", "cadastro_municipal", "matricula",
        "edital_url", "whatsapp", "placa", "ano_fabricacao", "km",
        "image_urls",
    ]
    for key in extra_keys:
        if key in mapped and mapped[key] is not None and mapped[key] != "":
            result[key] = mapped[key]
        elif key not in result:
            # Ensure key exists to avoid KeyError in tests
            result[key] = mapped.get(key, "" if key in (
                "nome_leilao", "numero_lote", "leilao_url",
                "data_primeiro_leilao", "data_segundo_leilao",
                "ocupacao", "cadastro_municipal", "matricula",
                "edital_url", "whatsapp", "placa", "km",
            ) else None)

    return result


def from_biasi_payload(raw: Any) -> list[dict]:
    """Convert bulk Biasi Leilões data to a list of unified-schema dicts.

    Accepts:
      - List of listing dicts
      - Dict with 'listings' or 'data' key
      - Dict with 'results' or 'items' key
      - String containing JSON
      - Dict with 'lotes' key (auction lots)

    Args:
        raw: Raw payload from extraction (list, dict, or JSON string).

    Returns:
        List of unified-schema listing dicts.
    """
    # Accept JSON string
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Payload inválido: não é JSON válido")
            return []

    # Accept dict with known container keys
    if isinstance(raw, dict):
        raw = (
            raw.get("listings")
            or raw.get("lotes")
            or raw.get("lots")
            or raw.get("results")
            or raw.get("items")
            or raw.get("data")
            or raw.get("records")
            or raw
        )

    if not isinstance(raw, list):
        logger.warning(
            f"Payload inesperado: esperava list, recebeu {type(raw).__name__}"
        )
        return []

    imoveis = []
    for item in raw:
        imovel = from_biasi_listing(item)
        if imovel:
            imoveis.append(imovel)

    logger.info(f"Parsed {len(imoveis)} listings from Biasi Leilões payload")
    return imoveis


# ── Helper: parse int ────────────────────────────────────────────────────────


def _parse_int(val: Any) -> int | None:
    """Safely parse a value to int.

    Args:
        val: Value to parse (str, int, float, etc.).

    Returns:
        Integer, or None if unparseable.
    """
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ── Scraper execution ────────────────────────────────────────────────────────

SCRAPER_DIR = (
    Path(__file__).resolve().parent.parent.parent / "scrapers" / "biasi_leiloes"
)
SCRAPER_SCRIPT = SCRAPER_DIR / "scrape_biasi.js"


def run_scraper(
    url: str = "https://www.biasileiloes.com.br/",
    pages: int = 1,
    timeout: int = 120,
) -> list[dict]:
    """Execute the Node.js scraper (if available) and parse results.

    Args:
        url: URL to start scraping from.
        pages: Number of pages to extract.
        timeout: Timeout in seconds for the subprocess.

    Returns:
        List of unified-schema listing dicts.

    Raises:
        RuntimeError: If the scraper script is not found.
    """
    import subprocess

    if not SCRAPER_SCRIPT.exists():
        raise RuntimeError(
            f"Scraper não encontrado: {SCRAPER_SCRIPT}\n"
            f"Crie o scraper Node.js primeiro."
        )

    if not (SCRAPER_DIR / "node_modules").exists():
        raise RuntimeError(
            f"Dependências não instaladas em {SCRAPER_DIR}\n"
            f"Execute: cd {SCRAPER_DIR} && npm install"
        )

    cmd = [
        "node",
        str(SCRAPER_SCRIPT),
        "--url", url,
        "--pages", str(pages),
        "--json",
    ]

    logger.info(f"Executando: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SCRAPER_DIR),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Scraper excedeu o tempo limite de {timeout}s")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Erro desconhecido"
        raise RuntimeError(
            f"Scraper falhou (exit={result.returncode}): {error_msg[:500]}"
        )

    stdout = result.stdout.strip()

    # Try to find JSON in output
    json_start = stdout.rfind("── JSON ──")
    if json_start >= 0:
        json_str = stdout[json_start + len("── JSON ──"):].strip()
    else:
        json_str = stdout

    try:
        raw_listings = json.loads(json_str)
    except json.JSONDecodeError:
        logger.error(
            f"Não foi possível parsear o JSON do scraper ({len(json_str)} chars)."
        )
        raise RuntimeError("Scraper retornou JSON inválido")

    return from_biasi_payload(raw_listings)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    """CLI entry point for testing the parser directly."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Biasi Leilões Parser — teste e conversão de dados"
    )
    sub = parser.add_subparsers(dest="command")

    # run: execute scraper (if available)
    run_parser = sub.add_parser(
        "run", help="Executa o scraper Node.js e parseia resultados"
    )
    run_parser.add_argument(
        "--url",
        default="https://www.biasileiloes.com.br/",
        help="URL inicial para scraping",
    )
    run_parser.add_argument(
        "--pages", type=int, default=1, help="Número de páginas"
    )
    run_parser.add_argument(
        "--output", help="Salvar JSON em arquivo"
    )

    # parse: parse a raw JSON file
    parse_parser = sub.add_parser(
        "parse", help="Parseia um arquivo JSON com dados brutos"
    )
    parse_parser.add_argument(
        "input_file", help="Caminho do arquivo JSON"
    )
    parse_parser.add_argument(
        "--output", "-o", help="Salvar resultado em arquivo JSON"
    )

    # parse-listing: parse a single listing dict from stdin or inline
    listing_parser = sub.add_parser(
        "parse-listing", help="Parseia um único listing (dict JSON)"
    )
    listing_parser.add_argument(
        "json_str", nargs="?", help="JSON string do listing"
    )

    # debug-photo: test photo URL construction
    photo_parser = sub.add_parser(
        "debug-photo", help="Testa construção de URL de foto CDN"
    )
    photo_parser.add_argument("image_id", help="ID da imagem")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )

    if args.command == "run":
        imoveis = run_scraper(args.url, args.pages)
        print(f"\nExtraídos {len(imoveis)} imóveis via scraper")
        if imoveis:
            precos = [
                i["preco_venda"]
                for i in imoveis
                if i.get("preco_venda") is not None
            ]
            if precos:
                print(
                    f"  Preços: R$ {min(precos):.0f} ~ R$ {max(precos):.0f}"
                )
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(imoveis, f, indent=2, ensure_ascii=False)
            print(f"  Salvo em: {args.output}")

    elif args.command == "parse":
        with open(args.input_file, encoding="utf-8") as f:
            data = json.load(f)
        imoveis = from_biasi_payload(data)
        print(
            f"Parseados {len(imoveis)} imóveis de {args.input_file}"
        )
        if imoveis:
            print(
                f"  Amostra: {imoveis[0]['titulo']} — "
                f"R$ {imoveis[0].get('preco_venda', 'N/A')}"
            )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(imoveis, f, indent=2, ensure_ascii=False)
            print(f"  Salvo em: {args.output}")

    elif args.command == "parse-listing":
        json_str = args.json_str
        if not json_str:
            json_str = sys.stdin.read().strip()
        if not json_str:
            print("Erro: forneça uma string JSON ou pipe para stdin")
            sys.exit(1)
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"Erro: JSON inválido — {e}")
            sys.exit(1)
        imovel = from_biasi_listing(raw)
        if imovel:
            print(json.dumps(imovel, indent=2, ensure_ascii=False))
        else:
            print("Erro: não foi possível parsear o listing")
            sys.exit(1)

    elif args.command == "debug-photo":
        image_id = args.image_id
        xx, yy = _derive_partition(image_id)
        print(f"Image ID:  {image_id}")
        print(f"Partition: {xx}/{yy}")
        for size_name, size_val in sorted(PHOTO_SIZES.items()):
            url = _normalize_photo_url(image_id, size=size_val)
            print(f"  {size_name} ({size_val}px): {url}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
