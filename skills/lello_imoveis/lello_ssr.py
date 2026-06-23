"""
lello_ssr — SSR data extraction for Lello Imóveis search pages.

Extracts listing data from Lello's Next.js search pages by fetching the HTML
and parsing the __NEXT_DATA__ JSON embedded in the server-rendered response.
No browser required — works with plain HTTP requests because Lello is an SSR
Next.js (Pages Router) app that embeds all page data inline.

Data source: __NEXT_DATA__ → props.pageProps.dehydratedState.queries[]
  Query key: "paginated-realties"
  State data: { pages, page, limit, total, list: [...], cortizo (bool) }

Each listing item fields:
  idImovel, tipoImovel, subTipoImovel, cidade, regiao, bairro, zona,
  latitude, longitude, enderecoFotoPrincipal,
  quantidadeDormitorios, quantidadeVagas, quantidadeSuites,
  metragemPrincipal, previsaoCondominio, previsaoIptu,
  valorVenda, valorVendaMin, valorCampanhaVenda, valorCampanhaLocacao,
  endereco, quantidadeBanheiros, uf, descricaoFilial, telefoneFilial,
  fotos: [{enderecoFoto, fotoPrincipal, descricaoFoto, ordem}],
  estacoesProximas, dataCadastro, alugueltranquilo, andar, arquitetoDeBolso

Detail page: __NEXT_DATA__ → props.pageProps.realtyDataWithMetatags.imovelDetalheVO
  (adds descricaoImovel, observacaoRegiao, fotos array, pontosReferencia, etc.)

Photos
------
Fonte: ``fotos[].enderecoFoto`` (array de objetos) + ``enderecoFotoPrincipal`` (path simples).

O array ``fotos`` contém URLs absolutas de dois CDNs:
  - **Azure Blob** (``upikblob.blob.core.windows.net/match-uploads/...``) — uploads
    originais em PNG.
  - **CloudFront** (``d2wln4evk52tbc.cloudfront.net/...``) — mesma foto servida via
    CDN otimizado (`.jpg`). Este é o CDN de produção, preferido por performance.

``enderecoFotoPrincipal`` é um path relativo como ``"3491/6984433.jpg"`` que
mapeia para o CloudFront CDN: ``https://d2wln4evk52tbc.cloudfront.net/3491/6984433.jpg``.
Usado apenas como fallback quando ``fotos`` está vazio.

Output fields: ``fotos`` (list[str]) e ``image_urls`` (alias, list[str]),
ambos com URLs absolutas, deduplicadas, foto principal primeiro.

Functions:
    extract_from_ssr(url, timeout, headers) -> list[dict]
    extract_from_html(html, source_url) -> list[dict]
    extract_detail_from_ssr(url, timeout, headers) -> dict | None
    map_listing_to_imovel(item, negociacao) -> dict | None
    build_search_url(tipo, negociacao, bairro, pagina) -> str
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger("lello_ssr")

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.lelloimoveis.com.br"
API_GATEWAY = "https://apigateway.lelloimoveis.com.br"

# Photo CDN bases
PHOTO_BASE = "https://upikblob.blob.core.windows.net/match-uploads"
# CloudFront CDN — serves the same photos as Azure Blob but optimized via CDN.
# Constructed as: {CLOUDFRONT_BASE}/{enderecoFotoPrincipal}
CLOUDFRONT_BASE = "https://d2wln4evk52tbc.cloudfront.net"

# ── Type maps ─────────────────────────────────────────────────────────────────

TIPO_MAP = {
    "apartamento": "apartamento",
    "casa": "casa",
    "cobertura": "cobertura",
    "duplex": "duplex",
    "kitnet": "kitnet",
    "loft": "loft",
    "studio": "studio",
    "flat": "flat",
    "terreno": "terreno",
    "comercial": "comercial",
    "sala": "sala_comercial",
    "predio": "predio",
    "sobrado": "sobrado",
    "conjugado": "conjugado",
}

# negotation type → slug used in URLs
NEGOCIACAO_SLUG = {
    "venda": "venda",
    "aluguel": "aluguel",
}

# negotation type → React Query interest value
NEGOCIACAO_INTEREST = {
    "venda": "buy",
    "aluguel": "rent",
}

# tipo → URL slug
TIPO_SLUG = {
    "apartamento": "apartamento-tipos",
    "casa": "casa-tipos",
    "cobertura": "cobertura-tipos",
    "duplex": "duplex-tipos",
    "kitnet": "kitnet-tipos",
    "loft": "loft-tipos",
    "studio": "studio-tipos",
    "flat": "flat-tipos",
    "terreno": "terreno-tipos",
    "comercial": "comercial-tipos",
    "sala_comercial": "sala-tipos",
    "predio": "predio-tipos",
    "sobrado": "sobrado-tipos",
    "conjugado": "conjugado-tipos",
}

# Inverse mapping for display
TIPO_DISPLAY = {v: k for k, v in TIPO_MAP.items()}


def _normalize_tipo(tipo: str) -> str:
    """Normalize tipo from Lello format to unified format."""
    t = tipo.lower().strip()
    mapped = TIPO_MAP.get(t, t)
    if mapped:
        return mapped
    # Fuzzy matching for composite types
    if "duplex" in t or "cobertura" in t:
        # Handle cases like "Apartamento Duplex" where subTipoImovel exists
        return "apartamento"
    return t


def _build_slug(tipo: str) -> str:
    """Build the URL slug for a property type."""
    t = tipo.lower().strip()
    if t in TIPO_SLUG:
        return TIPO_SLUG[t]
    # Try to map any type to a slug
    for key, slug in TIPO_SLUG.items():
        if key in t:
            return slug
    return "tipos"  # fallback


def _build_detail_url(codigo: int | str, slug: str = "") -> str:
    """Build the detail page URL for a listing."""
    codigo_str = str(codigo)
    if slug:
        return f"{BASE_URL}/imovel/{codigo_str}/{slug}/"
    return f"{BASE_URL}/imovel/{codigo_str}/"


# ── SSR data extraction helpers ────────────────────────────────────────────────


def _extract_next_data_json(html: str) -> dict | None:
    """Extract and parse the __NEXT_DATA__ JSON from HTML.

    Args:
        html: Raw HTML string from a Lello SSR page.

    Returns:
        Parsed __NEXT_DATA__ JSON dict, or None if not found.
    """
    # Standard pattern
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse __NEXT_DATA__ JSON: {e}")
            return None

    # Self-closing script tag pattern
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json"\s*/?>',
        html,
        re.DOTALL,
    )
    if match:
        start = match.end()
        end_match = re.search(r"</script>", html[start:])
        if end_match:
            try:
                return json.loads(html[start : start + end_match.start()])
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse __NEXT_DATA__ (alt pattern): {e}")

    return None


def _extract_search_listings_from_next_data(next_data: dict) -> list[dict]:
    """Extract listings from __NEXT_DATA__ for a search page.

    Navigates through the Next.js dehydrated state to find the
    'paginated-realties' React Query and extract all listings.

    Args:
        next_data: Parsed __NEXT_DATA__ JSON dict.

    Returns:
        List of raw listing dicts from the SSR payload.
    """
    page_props = (next_data.get("props") or {}).get("pageProps")
    if not page_props:
        logger.warning("pageProps not found in __NEXT_DATA__")
        return []

    queries = (page_props.get("dehydratedState") or {}).get("queries") or []
    if not queries:
        logger.warning("No queries in dehydratedState")
        return []

    # Find the paginated-realties query
    search_query = None
    for q in queries:
        query_key = q.get("queryKey")
        if isinstance(query_key, list) and query_key and query_key[0] == "paginated-realties":
            search_query = q
            break

    if not search_query:
        available = [
            q.get("queryKey", [""])[0]
            for q in queries
            if isinstance(q.get("queryKey"), list)
        ]
        logger.warning(
            f"'paginated-realties' query not found. "
            f"Available: {', '.join(available)}"
        )
        return []

    state = search_query.get("state") or {}
    data = state.get("data") or {}
    listings = data.get("list") or []

    if not isinstance(listings, list):
        logger.warning(f"'list' field is not a list: {type(listings)}")
        return []

    # Log pagination info
    total = data.get("total", 0)
    page = data.get("page", 0)
    pages = data.get("pages", 0)
    logger.info(
        f"Search data: page {page}/{pages}, {len(listings)} listings, {total} total"
    )

    return listings


def _extract_detail_from_next_data(next_data: dict) -> dict | None:
    """Extract detail listing from __NEXT_DATA__ for a detail page.

    Args:
        next_data: Parsed __NEXT_DATA__ JSON dict.

    Returns:
        Raw detail listing dict, or None if not found.
    """
    page_props = (next_data.get("props") or {}).get("pageProps")
    if not page_props:
        logger.warning("pageProps not found in __NEXT_DATA__")
        return None

    # Detail page uses realtyDataWithMetatags
    realty = page_props.get("realtyDataWithMetatags")
    if not realty:
        logger.warning("realtyDataWithMetatags not found")
        return None

    detail = realty.get("imovelDetalheVO")
    if not detail:
        logger.warning("imovelDetalheVO not found in realtyData")
        return None

    return detail


# ── Price parsing ─────────────────────────────────────────────────────────────


def _to_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Convert a value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """Convert a value to int safely."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _parse_price(val: Any) -> Optional[float]:
    """Parse a price value from Lello SSR data.

    Lello stores prices as numbers (int or float) or possibly strings
    like "R$ 700.000" in some contexts.

    Args:
        val: Raw price value.

    Returns:
        Float price or None.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        # Remove "R$" and formatting
        cleaned = val.replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── Photo URL construction ────────────────────────────────────────────────────


def _build_photo_urls(fotos: list | None, endereco_foto_principal: str | None = None) -> list[str]:
    """Build full, deduplicated, absolute photo URLs from SSR photo data.

    Lello stores photos in two complementary ways:

    1. **fotos array** (search + detail pages):
       ``{ enderecoFoto: str, fotoPrincipal: bool, descricaoFoto: str, ordem: int }``
       ``enderecoFoto`` is *always* an absolute URL — either Azure Blob
       (``upikblob.blob.core.windows.net/…``) or CloudFront CDN
       (``d2wln4evk52tbc.cloudfront.net/…``).

    2. **enderecoFotoPrincipal** (search page only, simpler path):
       A relative path like ``"3491/6984433.jpg"`` that maps to the CloudFront
       CDN.  When used as fallback, the full URL is:
       ``{CLOUDFRONT_BASE}/{enderecoFotoPrincipal}``

    URL priority:
      1. Photos from ``fotos`` array, sorted by ``ordem``, with
         ``fotoPrincipal=True`` first.
      2. ``enderecoFotoPrincipal`` only as fallback when ``fotos`` is empty.
      3. CloudFront CDN URLs have no size suffix to normalise (unlike
         EmCasa's ``/detail`` → ``/large``), but CloudFront IS the
         high-resolution / optimised CDN.

    Duplicates are removed (first occurrence wins).

    Args:
        fotos: Array of photo objects from SSR data, or None.
        endereco_foto_principal: Relative path to primary photo
            (e.g. ``"3491/6984433.jpg"``), or an absolute URL.

    Returns:
        List of absolute photo URLs, deduplicated, primary first.
    """
    seen: set[str] = set()
    result: list[tuple[int, str]] = []  # (ordem, url)

    # ── Method 1: From fotos array ──────────────────────────────────────
    if fotos and isinstance(fotos, list):
        for foto in fotos:
            if isinstance(foto, dict):
                url = foto.get("enderecoFoto", "")
                is_primary = bool(foto.get("fotoPrincipal"))
                ordem_raw = _to_int(foto.get("ordem"), 999)
                ordem: int = ordem_raw if ordem_raw is not None else 999
            elif isinstance(foto, str):
                url = foto
                is_primary = False
                ordem = 999
            else:
                continue

            if not url or not isinstance(url, str):
                continue

            # Skip relative paths (shouldn't happen in the API, but guard)
            if not url.startswith("http"):
                continue

            # Deduplicate
            normalized = url.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)

            # Primary photo gets ordem=-1 so it sorts first
            effective_ordem: int = -1 if is_primary else ordem
            result.append((effective_ordem, url))

    # ── Method 2: From enderecoFotoPrincipal (fallback) ─────────────────
    if not result and endereco_foto_principal:
        url = str(endereco_foto_principal).strip()
        if not url:
            return result

        # If relative, construct absolute CloudFront URL
        if not url.startswith("http"):
            url = f"{CLOUDFRONT_BASE}/{url.lstrip('/')}"

        normalized = url.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            result.append((-1, url))

    # Sort: primary (-1) first, then by ordem ascending
    result.sort(key=lambda x: (x[0], x[1]))
    return [url for _, url in result]


# ── Main mapping function ─────────────────────────────────────────────────────


def map_listing_to_imovel(
    item: dict,
    negociacao: str = "venda",
    coleta_ts: str | None = None,
) -> dict | None:
    """Convert a single listing dict from Lello SSR data to unified schema.

    Accepts both search page items and detail page items.

    Args:
        item: A listing object from __NEXT_DATA__.
        negociacao: 'venda' or 'aluguel' (inferred from search page context).
        coleta_ts: Collection timestamp. Auto if omitted.

    Returns:
        Dict in unified schema, or None if the item is invalid.
    """
    if not item or not isinstance(item, dict):
        return None

    now = coleta_ts or datetime.now(timezone.utc).isoformat()

    # ── IDs ──
    codigo = item.get("idImovel")
    if codigo is None:
        logger.warning("Listing without idImovel — skipping")
        return None
    codigo_str = str(codigo)
    listing_id = f"lello_{codigo_str}"

    # ── Type ──
    tipo_raw = item.get("tipoImovel") or ""
    sub_tipo_raw = item.get("subTipoImovel") or ""
    if sub_tipo_raw:
        # Composite type: "Apartamento Duplex"
        titulo_tipo = f"{tipo_raw} {sub_tipo_raw}".strip()
    else:
        titulo_tipo = tipo_raw
    tipo_normalized = _normalize_tipo(tipo_raw)

    # ── Prices ──
    valor_venda = _parse_price(item.get("valorVenda"))
    # 0 means "no value" in Lello data, not a free listing
    if valor_venda is not None and valor_venda == 0:
        valor_venda = None
    valor_campanha_venda = _parse_price(item.get("valorCampanhaVenda"))
    if valor_campanha_venda is not None and valor_campanha_venda == 0:
        valor_campanha_venda = None
    # Use campaign price if it's higher/lower? Actually campaign = discounted price
    # valorCampanhaVenda > 0 means there's a special campaign price
    preco_venda = valor_venda

    valor_aluguel = _parse_price(item.get("valorLocacao", item.get("previsaoLocacao")))
    valor_campanha_locacao = _parse_price(item.get("valorCampanhaLocacao"))
    # Campaign values of 0 mean "no campaign"
    if valor_campanha_locacao is not None and valor_campanha_locacao == 0:
        valor_campanha_locacao = None

    preco_aluguel = None
    if negociacao == "aluguel":
        preco_aluguel = valor_aluguel or valor_campanha_locacao
    elif valor_aluguel is not None:
        # Both prices available
        preco_aluguel = valor_aluguel

    # ── Fees ──
    condominio = _to_float(item.get("previsaoCondominio"))
    iptu = _to_float(item.get("previsaoIptu"))

    # ── Area and characteristics ──
    area = _to_float(item.get("metragemPrincipal"))
    quartos = _to_int(item.get("quantidadeDormitorios"))
    suites = _to_int(item.get("quantidadeSuites"))
    banheiros = _to_int(item.get("quantidadeBanheiros"))
    vagas = _to_int(item.get("quantidadeVagas"))
    andar = _to_int(item.get("andar"))

    # ── Location ──
    endereco = item.get("endereco") or ""
    bairro = item.get("bairro") or ""
    regiao = item.get("regiao") or ""
    cidade = item.get("cidade") or "São Paulo"
    uf = item.get("uf") or "SP"
    latitude = _to_float(item.get("latitude"))
    longitude = _to_float(item.get("longitude"))

    # ── Photos ──
    fotos = _build_photo_urls(
        item.get("fotos"),
        item.get("enderecoFotoPrincipal"),
    )

    # ── Description ──
    descricao = item.get("descricaoImovel") or ""
    observacao = item.get("observacaoRegiao") or ""
    if observacao:
        descricao = (descricao + "\n\n" + observacao).strip()

    # ── Metadata ──
    data_cadastro = item.get("dataCadastro") or None  # "2008-11-19"
    descricao_filial = item.get("descricaoFilial") or ""
    disponivel = True
    if "disponivel" in item:
        val = item["disponivel"]
        if isinstance(val, bool):
            disponivel = val
        elif isinstance(val, (int, float)):
            disponivel = bool(val)

    arquiteto_de_bolso = bool(item.get("arquitetoDeBolso"))
    aluguel_tranquilo = bool(item.get("alugueltranquilo"))

    # ── Build title ──
    titulo = f"{titulo_tipo}"
    if quartos:
        titulo += f" {quartos}q"
    if area:
        titulo += f" {int(area)}m²" if area == int(area) else f" {area}m²"
    if bairro:
        titulo += f" em {bairro}"
    if cidade:
        titulo += f"/{uf}" if uf else ""
    titulo = titulo.strip()

    # ── Build URL ──
    bairro_slug = bairro.lower().replace(" ", "-").replace("ç", "c").replace("ã", "a").replace("â", "a").replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o").replace("ô", "o").replace("ú", "u")
    url = _build_detail_url(codigo_str, f"{titulo_tipo.lower().replace(' ', '-')}-{bairro_slug}-sao_paulo-{negociacao}")

    # ── Features / amenities (from detail page) ──
    complementos = item.get("complementos") or []
    dependencias = item.get("dependencias") or []
    features: list[str] = []
    if isinstance(complementos, list):
        for c in complementos:
            if isinstance(c, dict):
                nome = c.get("nomeComplemento") or c.get("descricao") or ""
                if nome:
                    features.append(str(nome).lower().strip())
            elif isinstance(c, str):
                features.append(c.lower().strip())
    if isinstance(dependencias, list):
        for d in dependencias:
            if isinstance(d, dict):
                nome = d.get("nomeDependencia") or d.get("descricao") or ""
                if nome:
                    features.append(str(nome).lower().strip())

    # ── Assemble result ──
    result = {
        # Identification
        "id": listing_id,
        "codigo": codigo_str,
        "titulo": titulo,
        "url": url,
        "fonte": "lelloimoveis",
        "negociacao": negociacao,
        "disponivel": disponivel,

        # Prices
        "preco_venda": preco_venda,
        "preco_aluguel": preco_aluguel,
        "condominio": condominio,
        "iptu": iptu,

        # Characteristics
        "area": float(area) if area is not None else None,
        "quartos": quartos,
        "suites": suites,
        "banheiros": banheiros,
        "vagas": vagas,
        "andar": andar,
        "tipo": tipo_normalized,

        # Location
        "endereco": endereco,
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "latitude": latitude,
        "longitude": longitude,

        # Content
        "descricao": descricao[:5000] if descricao else "",
        "comodidades": features,
        "amenities": features,
        "fotos": fotos,
        "image_urls": fotos,  # alias for normalized absolute URLs

        # Agency
        "agencia": f"Lello Imóveis — {descricao_filial}" if descricao_filial else "Lello Imóveis",
        "origem_id": codigo_str,

        # Metadata
        "data_coleta": now,
        "data_publicacao": data_cadastro,

        # Price drop / extras
        "tem_reducao": False,
        "percentual_reducao": 0.0,

        # Extra Lello fields preserved
        "_extra": {
            "id_original": codigo,
            "sub_tipo": sub_tipo_raw,
            "regiao": regiao,
            "zona": item.get("zona", ""),
            "descricao_filial": descricao_filial,
            "telefone_filial": item.get("telefoneFilial", ""),
            "arquiteto_de_bolso": arquiteto_de_bolso,
            "aluguel_tranquilo": aluguel_tranquilo,
            "valor_campanha_venda": valor_campanha_venda,
            "valor_campanha_locacao": valor_campanha_locacao,
            "valor_venda_min": _parse_price(item.get("valorVendaMin")),
            "data_cadastro": data_cadastro,
            "empreendimento": item.get("empreendimento"),
        },
    }

    # Clean up None values for non-optional fields
    for field in ("preco_venda", "preco_aluguel", "condominio", "iptu",
                  "area", "quartos", "suites", "banheiros", "vagas", "andar"):
        if result[field] is not None:
            result[field] = float(result[field]) if isinstance(result[field], int) else result[field]

    return result


# ── URL builders ──────────────────────────────────────────────────────────────


def build_search_url(
    tipo: str = "apartamento",
    negociacao: str = "venda",
    bairro: str | None = None,
    pagina: int = 1,
) -> str:
    """Build a Lello search page URL.

    URL patterns:
      /{negociacao}/residencial/{tipo}-tipos/{pagina}-pagina/
      /{negociacao}/residencial/{bairro}-sao_paulo-regioes/{pagina}-pagina/

    Args:
        tipo: Property type (apartamento, casa, etc).
        negociacao: 'venda' or 'aluguel'.
        bairro: Optional neighborhood filter.
        pagina: Page number (1-indexed).

    Returns:
        Full search URL.
    """
    neg_slug = NEGOCIACAO_SLUG.get(negociacao, negociacao)
    tipo_slug = _build_slug(tipo)

    if bairro:
        bairro_slug = (
            bairro.lower()
            .replace(" ", "-")
            .replace("ã", "a").replace("â", "a").replace("á", "a")
            .replace("é", "e").replace("ê", "e")
            .replace("í", "i")
            .replace("ó", "o").replace("ô", "o")
            .replace("ú", "u")
            .replace("ç", "c")
            .replace("ñ", "n")
        )
        return f"{BASE_URL}/{neg_slug}/residencial/{bairro_slug}-sao_paulo-regioes/{pagina}-pagina/"

    return f"{BASE_URL}/{neg_slug}/residencial/{tipo_slug}/{pagina}-pagina/"


def build_detail_url(codigo: int | str) -> str:
    """Build a detail page URL for a listing by its code."""
    return _build_detail_url(codigo)


# ── Main extraction entry points ──────────────────────────────────────────────


def extract_from_ssr(
    url: str,
    timeout: int = 30,
    headers: dict | None = None,
) -> tuple[list[dict], dict]:
    """Fetch a Lello search listing page and extract listings from SSR data.

    Performs an HTTP GET on the provided URL, extracts __NEXT_DATA__ from
    the HTML, parses it, and maps all listings to the unified schema.

    Args:
        url: Full URL of a Lello search page.
        timeout: HTTP request timeout in seconds (default: 30).
        headers: Optional dict of extra HTTP headers.

    Returns:
        Tuple of (listings_list, metadata_dict) where metadata includes
        pagination info (total, page, pages, limit).

    Raises:
        requests.RequestException: If the HTTP request itself fails.
    """
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)

    logger.info(f"Fetching: {url}")
    response = requests.get(url, headers=default_headers, timeout=timeout)
    response.raise_for_status()

    html = response.text
    if not html or len(html) < 1000:
        logger.warning(f"Response too short ({len(html)} chars) for {url}")
        return [], {}

    return extract_from_html(html, url)


def extract_from_html(
    html: str,
    source_url: str = "",
) -> tuple[list[dict], dict]:
    """Parse listings from raw Lello SSR HTML.

    Extracts __NEXT_DATA__ from the HTML and maps all listings to the
    unified schema.

    Args:
        html: Raw HTML string from a Lello page.
        source_url: Original URL for context.

    Returns:
        Tuple of (listings_list, metadata_dict).
    """
    metadata: dict[str, Any] = {}
    next_data = _extract_next_data_json(html)
    if not next_data:
        logger.warning("__NEXT_DATA__ not found in HTML")
        return [], metadata

    logger.info("Found __NEXT_DATA__ in HTML")

    # Determine if this is a search page or detail page
    raw_listings = _extract_search_listings_from_next_data(next_data)
    is_search = bool(raw_listings)

    if not raw_listings:
        # Try detail page
        detail = _extract_detail_from_next_data(next_data)
        if detail:
            logger.info("Extracted detail listing from SSR data")
            raw_listings = [detail]
            metadata["page_type"] = "detail"
        else:
            logger.warning("No listings found in SSR data")
            return [], metadata
    else:
        # Extract pagination metadata from search query
        page_props = (next_data.get("props") or {}).get("pageProps") or {}
        queries = (page_props.get("dehydratedState") or {}).get("queries") or []
        for q in queries:
            qk = q.get("queryKey")
            if isinstance(qk, list) and qk and qk[0] == "paginated-realties":
                state_data = (q.get("state") or {}).get("data") or {}
                metadata = {
                    "total": state_data.get("total", 0),
                    "page": state_data.get("page", 0),
                    "pages": state_data.get("pages", 0),
                    "limit": state_data.get("limit", 20),
                    "page_type": "search",
                }
                break

    # Infer negotiation type from URL
    negociacao = "venda"
    if "/aluguel/" in source_url:
        negociacao = "aluguel"

    logger.info(f"Mapping {len(raw_listings)} listings (negociacao={negociacao})")
    mapped = [map_listing_to_imovel(item, negociacao=negociacao) for item in raw_listings]
    mapped = [m for m in mapped if m]

    logger.info(f"Mapped {len(mapped)} listings to unified schema")
    return mapped, metadata


def extract_detail_from_ssr(
    url: str,
    timeout: int = 30,
    headers: dict | None = None,
) -> dict | None:
    """Fetch a single Lello detail page and extract full listing info.

    Detail pages have additional fields like descricaoImovel, observacaoRegiao,
    all fotos, complementos, dependencias.

    Args:
        url: Full URL of a Lello detail page.
        timeout: HTTP request timeout in seconds (default: 30).
        headers: Optional dict of extra HTTP headers.

    Returns:
        Single listing dict in unified schema, or None on failure.
    """
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)

    logger.info(f"Fetching detail: {url}")
    try:
        response = requests.get(url, headers=default_headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch detail page {url}: {e}")
        return None

    html = response.text
    next_data = _extract_next_data_json(html)
    if not next_data:
        logger.warning(f"__NEXT_DATA__ not found in detail page {url}")
        return None

    detail = _extract_detail_from_next_data(next_data)
    if not detail:
        logger.warning(f"Detail data not found in page {url}")
        return None

    # Determine negotiation from URL
    negociacao = "venda" if "/venda/" in url else "aluguel"

    return map_listing_to_imovel(detail, negociacao=negociacao)


# ── CLI entry point ────────────────────────────────────────────────────────────


def main():
    """CLI entry point for testing."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Lello SSR Extractor — extrai listings da Lello via SSR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s search --tipo apartamento --negociacao venda --pagina 1
  %(prog)s detail 43923
  %(prog)s url "https://www.lelloimoveis.com.br/venda/residencial/apartamento-tipos/1-pagina/"
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # search
    p_search = sub.add_parser("search", help="Buscar página de listagem")
    p_search.add_argument("--tipo", default="apartamento", help="Tipo de imóvel")
    p_search.add_argument("--negociacao", default="venda", choices=["venda", "aluguel"])
    p_search.add_argument("--bairro", default=None, help="Bairro (opcional)")
    p_search.add_argument("--pagina", type=int, default=1, help="Número da página")

    # detail
    p_detail = sub.add_parser("detail", help="Extrair detalhe de um imóvel")
    p_detail.add_argument("codigo", type=str, help="Código do imóvel")

    # url
    p_url = sub.add_parser("url", help="Extrair de URL direta")
    p_url.add_argument("url", type=str, help="URL completa")

    # verbose
    parser.add_argument("--verbose", "-v", action="store_true", help="Log detalhado")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s  %(levelname)-8s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s %(message)s")

    if args.command == "search":
        url = build_search_url(
            tipo=args.tipo,
            negociacao=args.negociacao,
            bairro=args.bairro,
            pagina=args.pagina,
        )
        print(f"URL: {url}\n")
        listings, metadata = extract_from_ssr(url)
        print(f"\nMetadata: {json.dumps(metadata, indent=2)}")
        print(f"\nListings: {len(listings)}")
        if listings:
            print(f"\nSample (1st): {json.dumps(listings[0], indent=2, ensure_ascii=False)[:2000]}")

    elif args.command == "detail":
        url = build_detail_url(args.codigo)
        print(f"URL: {url}\n")
        listing = extract_detail_from_ssr(url)
        if listing:
            print(f"Listing: {json.dumps(listing, indent=2, ensure_ascii=False)[:3000]}")
        else:
            print("No listing found")

    elif args.command == "url":
        print(f"Fetching: {args.url}\n")
        listings, metadata = extract_from_ssr(args.url)
        print(f"Metadata: {json.dumps(metadata, indent=2)}")
        print(f"\nListings: {len(listings)}")
        if listings:
            print(f"\nSample (1st): {json.dumps(listings[0], indent=2, ensure_ascii=False)[:2000]}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
