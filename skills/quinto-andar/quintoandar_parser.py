"""
quintoandar_parser — Converte dados brutos do QuintoAndar para o schema unificado Imovel.

Fontes de dados suportadas:
  1. Next.js data route: /_next/data/{buildId}/.../comprar/.../imovel/...json
     → { pageProps: { initialState: { houses: [...] } } }
  2. API interna: apigw.prod.quintoandar.com.br/house-listing-search/
     → { results: [...] }
  3. Lista direta de houses (já extraída do DOM/state)

Uso:
    from quintoandar_parser import from_quintoandar_listing, from_quintoandar_payload

    imovel = from_quintoandar_listing(raw_listing)
    imoveis = from_quintoandar_payload(nextjs_data)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# O schema unificado vive em ~/.hermes/imovel_schema.py
sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel, TIPOS_VALIDOS


# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("quintoandar_parser")

# Sempre loga warnings, mesmo se o módulo chamador não configurar logging
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.WARNING)
    _handler.setFormatter(logging.Formatter("[quintoandar] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.WARNING)


def log_warning(msg: str) -> None:
    """Emite warning via logging E warnings.warn para visibilidade dupla."""
    logger.warning(msg)
    warnings.warn(msg, stacklevel=2)


# ── Helpers de acesso seguro ──────────────────────────────────────────────────

def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Navega por chaves aninhadas sem crash se obj não for dict ou chave faltar.
    
    Exemplo: _safe_get(listing, "address", "city", default="")
    Retorna obj["address"]["city"] se ambos existirem e obj for dict,
    senão retorna default.
    """
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            log_warning(f"Esperado dict para acessar '{key}', recebeu {type(current).__name__}")
            return default
        if key not in current:
            return default
        current = current[key]
    return current


def _safe_navigate(payload: dict, *paths: str, default: Any = None) -> Any:
    """
    Navega payload tentando múltiplos caminhos alternativos.
    Retorna o primeiro caminho que existe e não é None/"".
    
    Exemplo: _safe_navigate(data, "pageProps.initialState.houses",
                            "results", "data")
    Tenta cada caminho em ordem; retorna o primeiro achado.
    """
    for path in paths:
        parts = path.split(".")
        val = payload
        ok = True
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                ok = False
                break
        if ok and val is not None and val != "":
            return val
    return default


def _as_str(val: Any, default: str = "") -> str:
    """Converte valor para string com segurança. Loga se tipo for inesperado."""
    if val is None:
        return default
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        log_warning(f"Valor não-string inesperado: {type(val).__name__} = {str(val)[:80]}")
        return str(val)[:200]
    return str(val)


# ── Constantes ────────────────────────────────────────────────────────────────

FONTE = "quintoandar"

# Mapeamento de tipos QuintoAndar → schema unificado
TIPO_MAP = {
    "Apartamento": "apartamento",
    "Casa": "casa",
    "Kitnet": "kitnet",
    "Cobertura": "cobertura",
    "Studio": "studio",
    "Flat": "flat",
    "Loft": "loft",
    "Sobrado": "sobrado",
    "Terreno": "terreno",
    "Casa em Condomínio": "casa_condominio",
    "Casa Condomínio": "casa_condominio",
    "Comercial": "comercial",
    "Ponto Comercial": "comercial",
    "Sala Comercial": "comercial",
    "Conjunto Comercial": "comercial",
}

# Campos de endereço que o QuintoAndar pode retornar
ADDRESS_FIELDS = {
    "address", "street", "streetName", "number",
    "complement", "city", "state", "stateCode",
    "neighborhood", "neighbourhood", "zipCode",
}


# ── Conversão principal ────────────────────────────────────────────────────────

def from_quintoandar_listing(
    listing: dict[str, Any],
    build_id: str = "",
    coleta_ts: str | None = None,
) -> Imovel:
    """
    Converte um único listing do QuintoAndar para o schema Imovel unificado.

    Args:
        listing: Dict do imóvel (vindo de houses[] ou API results[]).
        build_id: Build ID do Next.js para montar URL completa (opcional).
        coleta_ts: Timestamp de coleta. Auto se omitido.

    Returns:
        Instância de Imovel preenchida.
    """
    if not isinstance(listing, dict):
        log_warning(f"from_quintoandar_listing recebeu tipo {type(listing).__name__}, não dict — ignorando")
        return Imovel()

    now = coleta_ts or datetime.now(timezone.utc).isoformat()

    # ─ ID — QuintoAndar usa id string ou int
    raw_id = _safe_get(listing, "id") or _safe_get(listing, "listingId") or ""
    imovel_id = _as_str(raw_id)
    if not imovel_id:
        log_warning("Listing sem id nem listingId — ID vazio")

    # ─ URL do anúncio
    url = _build_url(listing, build_id)

    # ─ Preços
    sale_price = _safe_get(listing, "salePrice")
    rent_price = _safe_get(listing, "rentPrice")
    if sale_price is not None:
        preco_venda = _to_float(sale_price)
    else:
        preco_venda = None
    if rent_price is not None:
        preco_aluguel = _to_float(rent_price)
    else:
        preco_aluguel = None

    # ─ Condomínio e IPTU (vem num objeto {condoFee, iptu} ou direto)
    condominio, iptu = _extract_condo_iptu(listing)

    # ─ Tipo do imóvel
    tipo = _map_tipo(_as_str(_safe_get(listing, "type", default="")))

    # ─ Endereço
    endereco, bairro, cidade, uf = _extract_address(listing)

    # ─ Características
    area = _to_float(
        _safe_get(listing, "area")
        or _safe_get(listing, "usableArea")
        or _safe_get(listing, "totalArea")
    )
    quartos = _to_int(_safe_get(listing, "bedrooms"))
    banheiros = _to_int(_safe_get(listing, "bathrooms"))
    vagas = _to_int(
        _safe_get(listing, "parkingSpots")
        or _safe_get(listing, "garageSpots")
        or _safe_get(listing, "vacancies")
    )

    # ─ Descrição
    descricao = _as_str(
        _safe_get(listing, "description")
        or _safe_get(listing, "shortSaleDescription")
        or ""
    )

    # ─ Amenities
    amenities = _extract_amenities(listing)

    # ─ Fotos
    fotos = _extract_photos(listing)

    # ─ Título
    titulo = _as_str(
        _safe_get(listing, "title")
        or _safe_get(listing, "shortSaleDescription")
        or ""
    )

    # ─ Data de publicação (se disponível)
    data_pub = (
        _safe_get(listing, "publishDate")
        or _safe_get(listing, "createdAt")
        or _safe_get(listing, "createdAtIso")
    )

    return Imovel(
        id=imovel_id[:200],
        titulo=titulo[:500],
        url=url,
        fonte=FONTE,
        endereco=endereco,
        bairro=bairro,
        cidade=cidade,
        uf=uf,
        preco_venda=preco_venda,
        preco_aluguel=preco_aluguel,
        condominio=condominio,
        iptu=iptu,
        area=area,
        quartos=quartos,
        banheiros=banheiros,
        vagas=vagas,
        tipo=tipo,
        descricao=descricao[:5000],
        amenities=amenities,
        fotos=fotos,
        data_coleta=now,
        data_publicacao=_as_str(data_pub) if data_pub else None,
    )


# ── Conversão de payloads estruturados ─────────────────────────────────────────

def from_quintoandar_houses(
    houses: list[dict[str, Any]],
    build_id: str = "",
) -> list[Imovel]:
    """
    Converte uma lista de houses do QuintoAndar para lista de Imovel.

    Útil quando você já extraiu o array houses[] do estado.

    Args:
        houses: Lista de dicts de imóveis.
        build_id: Build ID para montar URLs.

    Returns:
        Lista de Imovel.
    """
    now = datetime.now(timezone.utc).isoformat()
    return [from_quintoandar_listing(h, build_id=build_id, coleta_ts=now) for h in houses]


def from_quintoandar_payload(
    payload: dict[str, Any],
    build_id: str = "",
) -> list[Imovel]:
    """
    Converte o payload completo da Next.js data route do QuintoAndar.

    Aceita tanto o objeto raiz quanto pageProps.initialState.

    Args:
        payload: JSON do data route ou pageProps.initialState.
        build_id: Build ID do Next.js para montar URLs.

    Returns:
        Lista de Imovel.
    """
    if not isinstance(payload, dict):
        log_warning(f"from_quintoandar_payload recebeu tipo {type(payload).__name__}, não dict")
        return []

    # Navega pela estrutura: pageProps → initialState → houses/results/listings
    houses = _safe_navigate(
        payload,
        "pageProps.initialState.houses",
        "pageProps.initialState.results",
        "initialState.houses",
        "houses",
        "results",
        "listings",
        default=[],
    )

    if not isinstance(houses, list):
        log_warning(f"Lista de imóveis não é list: {type(houses).__name__}")
        return []

    now = datetime.now(timezone.utc).isoformat()
    return [from_quintoandar_listing(h, build_id=build_id, coleta_ts=now) for h in houses]


def from_quintoandar_api_response(
    response: dict[str, Any],
) -> list[Imovel]:
    """
    Converte resposta da API interna do QuintoAndar (apigw.prod.quintoandar.com.br).

    Args:
        response: Resposta JSON da API → { results: [...], ... }

    Returns:
        Lista de Imovel.
    """
    if not isinstance(response, dict):
        log_warning(f"from_quintoandar_api_response recebeu tipo {type(response).__name__}, não dict")
        return []

    results = _safe_navigate(response, "results", "data", default=[])
    if not isinstance(results, list):
        log_warning(f"Results da API não é list: {type(results).__name__}")
        return []

    now = datetime.now(timezone.utc).isoformat()
    return [from_quintoandar_listing(h, coleta_ts=now) for h in results]


def from_quintoandar_safe(
    payload: Any,
    build_id: str = "",
) -> list[Imovel]:
    """
    Wrapper à prova de crash que aceita qualquer payload e retorna lista de Imovel.

    Tenta automaticamente:
      1. Next.js data route payload (pageProps → initialState → houses)
      2. API response (results / data)
      3. Lista direta de houses

    Em vez de crashar, loga warning e retorna lista vazia.

    Args:
        payload: Qualquer tipo (dict esperado, mas segura outros).
        build_id: Build ID do Next.js.

    Returns:
        Lista de Imovel (nunca lança exceção).
    """
    try:
        if not isinstance(payload, dict):
            log_warning(f"from_quintoandar_safe recebeu tipo {type(payload).__name__}, não dict")
            return []

        # Tenta Next.js data route
        houses = _safe_navigate(
            payload,
            "pageProps.initialState.houses",
            "pageProps.initialState.results",
            "initialState.houses",
        )
        if isinstance(houses, list) and houses:
            return from_quintoandar_houses(houses, build_id=build_id)
        if isinstance(houses, dict):
            house_list = [h for h in houses.values() if isinstance(h, dict)]
            if house_list:
                logger.info("Houses extraído de dict (chaveado por ID)")
                return from_quintoandar_houses(house_list, build_id=build_id)

        # Tenta API response
        results = _safe_navigate(payload, "results", "data")
        if isinstance(results, list) and results:
            return from_quintoandar_api_response(payload)

        # Tenta lista direta
        for key in ("houses", "listings", "results"):
            val = _safe_get(payload, key)
            if isinstance(val, list) and val:
                log_warning(f"Payload reconhecido via campo direto '{key}'")
                return from_quintoandar_houses(val, build_id=build_id)

        log_warning("Nenhuma estrutura de dados reconhecida no payload")
        return []
    except Exception as exc:
        log_warning(f"Erro inesperado em from_quintoandar_safe: {exc}")
        return []


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_url(listing: dict, build_id: str = "") -> str:
    """Monta URL direta do anúncio no QuintoAndar."""
    if not isinstance(listing, dict):
        log_warning(f"_build_url recebeu tipo {type(listing).__name__}, não dict")
        return ""

    # Se já tem URL, usa
    url = _as_str(
        _safe_get(listing, "url")
        or _safe_get(listing, "shareUrl")
        or _safe_get(listing, "canonicalUrl")
        or ""
    )
    if url:
        # Garante que começa com http
        if url.startswith("/"):
            url = f"https://www.quintoandar.com.br{url}"
        elif not url.startswith("http"):
            url = f"https://www.quintoandar.com.br/{url.lstrip('/')}"
        return url

    # Monta a partir do path
    pid = _as_str(_safe_get(listing, "id") or _safe_get(listing, "listingId") or "")
    slug = _as_str(_safe_get(listing, "slug") or _safe_get(listing, "urlSlug") or "")

    city_slug = _as_str(_safe_get(listing, "citySlug") or "")
    if city_slug:
        city_part = city_slug.replace("/", "-")
    else:
        city_part = "sao-paulo-sp-brasil"

    # Determina compra ou aluguel
    prefix = "comprar"
    for_sale = _safe_get(listing, "forSale")
    if for_sale is False:
        prefix = "alugar"
    if _safe_get(listing, "rentPrice") and not _safe_get(listing, "salePrice"):
        prefix = "alugar"

    path_parts = [p for p in [prefix, "imovel", city_part] if p]
    path = "/".join(path_parts)
    if slug:
        path = f"{path}/{slug}"

    return f"https://www.quintoandar.com.br/{path}/{pid}" if pid else f"https://www.quintoandar.com.br/{path}"


def _extract_condo_iptu(listing: dict) -> tuple[Optional[float], Optional[float]]:
    """Extrai condomínio e IPTU do objeto condoIptu ou campos diretos."""
    if not isinstance(listing, dict):
        log_warning("_extract_condo_iptu recebeu não-dict")
        return None, None

    condo_iptu = _safe_get(listing, "condoIptu") or _safe_get(listing, "condominiumIptu") or {}

    if isinstance(condo_iptu, dict):
        condominio = _to_float(
            _safe_get(condo_iptu, "condoFee")
            or _safe_get(condo_iptu, "condominium")
            or _safe_get(condo_iptu, "condominiumFee")
            or _safe_get(condo_iptu, "condominio")
        )
        iptu = _to_float(
            _safe_get(condo_iptu, "iptu")
            or _safe_get(condo_iptu, "propertyTax")
        )
    else:
        # condoIptu can be an int (total = condominio + iptu directly)
        # or some other type — log at debug level only
        logger.debug(f"condoIptu tipo inesperado: {type(condo_iptu).__name__}={condo_iptu}")
        condominio = None
        iptu = None

    # Fallback: campos diretos no listing
    if condominio is None:
        condominio = _to_float(
            _safe_get(listing, "condoPrice")
            or _safe_get(listing, "condoFee")
            or _safe_get(listing, "condominiumFee")
            or _safe_get(listing, "condominio")
        )
        if condominio is not None:
            log_warning("condominio vindo de campo direto no listing (fallback)")
    if iptu is None:
        iptu = _to_float(
            _safe_get(listing, "iptu")
            or _safe_get(listing, "propertyTax")
        )
        if iptu is not None:
            log_warning("iptu vindo de campo direto no listing (fallback)")

    return condominio, iptu


def _extract_address(listing: dict) -> tuple[str, str, str, str]:
    """
    Extrai endereço completo, bairro, cidade e UF.

    QuintoAndar pode devolver endereço como:
      - Objeto: { address: "Rua X, 123", city: "São Paulo", ... }
      - Strings diretas: neighbourhood, city, stateCode
    """
    if not isinstance(listing, dict):
        log_warning("_extract_address recebeu não-dict")
        return "", "", "", ""

    addr_raw = _safe_get(listing, "address")
    addr = addr_raw if isinstance(addr_raw, dict) else {}
    if addr_raw is not None and not isinstance(addr_raw, dict) and not isinstance(addr_raw, str):
        log_warning(f"address tem tipo inesperado: {type(addr_raw).__name__}")

    if isinstance(addr, dict):
        endereco = _as_str(
            _safe_get(addr, "address")
            or _safe_get(addr, "street")
            or _safe_get(addr, "fullAddress")
            or ""
        )
        if not endereco:
            parts = [_as_str(_safe_get(addr, "streetName", default="")),
                     _as_str(_safe_get(addr, "number", default=""))]
            endereco = " ".join(p for p in parts if p).strip()
        cidade = _as_str(_safe_get(addr, "city", default=""))
        uf = _as_str(_safe_get(addr, "stateCode", default="") or _safe_get(addr, "state", default=""))
        if len(uf) > 2:
            uf = ""
        # Bairro vem no addr ou no listing
        bairro = _as_str(
            _safe_get(addr, "neighborhood")
            or _safe_get(addr, "neighbourhood")
            or _safe_get(listing, "neighbourhood")
            or _safe_get(listing, "neighborhood")
            or ""
        )
    elif isinstance(addr_raw, str):
        endereco = addr_raw
        cidade = _as_str(_safe_get(listing, "city", default=""))
        uf = _as_str(_safe_get(listing, "stateCode", default="") or _safe_get(listing, "uf", default=""))
        if len(uf) > 2:
            uf = ""
        bairro = _as_str(
            _safe_get(listing, "neighbourhood")
            or _safe_get(listing, "neighborhood")
            or ""
        )
    else:
        endereco = ""
        cidade = _as_str(_safe_get(listing, "city", default=""))
        uf = _as_str(_safe_get(listing, "stateCode", default="") or _safe_get(listing, "uf", default=""))
        if len(uf) > 2:
            uf = ""
        bairro = ""

    # Fallback: regionName (pode ser o bairro também)
    if not bairro:
        bairro = _as_str(_safe_get(listing, "regionName", default=""))
    # Cidade fallback: extrair do citySlug se disponível (ex: "sao-paulo-sp-brasil")
    if not cidade:
        city_slug = _as_str(_safe_get(listing, "citySlug", default=""))
        if city_slug:
            parts = city_slug.split("-")
            # Últimos 2 são o estado + "brasil"
            city_parts = parts[:-2] if len(parts) > 2 else parts
            cidade = " ".join(city_parts).replace("-", " ").title()

    # UF fallback: extrair do citySlug se tiver (ex: "sao-paulo-sp-brasil")
    if not uf:
        city_slug = _as_str(_safe_get(listing, "citySlug", default=""))
        parts = city_slug.split("-")
        if len(parts) >= 2:
            uf = parts[-2].upper() if len(parts[-2]) == 2 else ""
        if not uf:
            uf = _as_str(_safe_get(listing, "uf", default=""))

    return endereco, bairro, cidade, uf.upper()


def _map_tipo(raw_type: str) -> str:
    """Mapeia tipo do QuintoAndar para o schema unificado."""
    if not raw_type:
        return ""
    mapped = TIPO_MAP.get(raw_type)
    if mapped:
        return mapped
    # Fallback: tentar match parcial
    raw_lower = raw_type.lower()
    for keyword, tipo in [
        ("apartamento", "apartamento"),
        ("casa", "casa"),
        ("kitnet", "kitnet"),
        ("studio", "studio"),
        ("loft", "loft"),
        ("flat", "flat"),
        ("cobertura", "cobertura"),
        ("sobrado", "sobrado"),
        ("terreno", "terreno"),
        ("comercial", "comercial"),
    ]:
        if keyword in raw_lower:
            return tipo
    return raw_lower


def _extract_amenities(listing: dict) -> list[str]:
    """Extrai lista de amenities do listing."""
    if not isinstance(listing, dict):
        log_warning("_extract_amenities recebeu não-dict")
        return []

    amenities = (
        _safe_get(listing, "amenities")
        or _safe_get(listing, "amenitiesList")
        or _safe_get(listing, "features")
        or []
    )

    if isinstance(amenities, list):
        result = []
        for a in amenities:
            if isinstance(a, dict):
                a = _safe_get(a, "name") or _safe_get(a, "label") or _safe_get(a, "value") or str(a)
            if isinstance(a, str) and a.strip():
                result.append(_normalize_amenity(a.strip()))
            elif not isinstance(a, str):
                log_warning(f"Amenity com tipo inesperado: {type(a).__name__}")
                continue
        return result

    if isinstance(amenities, str):
        tokens = [a.strip() for a in amenities.split(",") if a.strip()]
        if tokens:
            log_warning("Amenities em formato string (não-list) — convertendo")
        return [_normalize_amenity(t) for t in tokens]

    if amenities:
        log_warning(f"Amenities em formato inesperado: {type(amenities).__name__}")
    return []


def _normalize_amenity(name: str) -> str:
    """Normaliza nome de amenity para snake_case (sem acentos)."""
    if not isinstance(name, str):
        log_warning(f"_normalize_amenity recebeu tipo {type(name).__name__}, não str")
        return str(name) if name else ""
    import unicodedata
    name = name.lower().strip()
    # Decompor acentos: "são" → "sa\u0303o"
    name = unicodedata.normalize("NFKD", name)
    # Remover marcas diacríticas (acentos, cedilha, etc.)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.replace(" ", "_").replace("-", "_").replace(":", "")
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name


QUINTOANDAR_IMG_BASE = "https://www.quintoandar.com.br/img/med/"


def _normalize_photo_url(url: str) -> str:
    """Normaliza URL de foto para URL absoluta acessível.

    O QuintoAndar retorna URLs relativas (apenas o nome do arquivo)
    nos seus dados SSR/API.  A CDN de imagens vive em:

        https://www.quintoandar.com.br/img/{size}/{filename}

    Onde ``size`` = ``med`` é o único tamanho que serve conteúdo
    actualmente (``large``, ``orig``, etc. retornam 404).

    Estratégia:
      1. URL já absoluta (http/https) → mantém como está
      2. Caminho absoluto (/img/...) → prefixa com o domínio
      3. Apenas nome de arquivo (``originalXXX.jpg``) → prefixa com base
    """
    if not url or not isinstance(url, str):
        return url

    url = url.strip()

    # Já é absoluta
    if url.startswith("http"):
        return url

    # Caminho absoluto (ex.: /img/med/foto.jpg)
    if url.startswith("/"):
        return f"https://www.quintoandar.com.br{url}"

    # Relativo — só o nome do arquivo (caso mais comum na SSR)
    return f"{QUINTOANDAR_IMG_BASE}{url}"


def _extract_photos(listing: dict) -> list[str]:
    """Extrai lista de URLs absolutas de fotos.

    Fontes testadas (Next.js SSR / API):
      - ``photos[].url`` — string relativa (ex.: ``original123.jpg``)
      - ``photos[].src``, ``photos[].image`` (fallback)
      - ``mainPhoto``, ``coverPhoto``, ``thumbnail`` (como dict ou string)

    Todas as URLs são normalizadas para absolutas via
    ``_normalize_photo_url()`` e a lista é deduplicada.
    """
    if not isinstance(listing, dict):
        log_warning("_extract_photos recebeu não-dict")
        return []

    photos = (
        _safe_get(listing, "photos")
        or _safe_get(listing, "images")
        or _safe_get(listing, "photoUrls")
        or _safe_get(listing, "pictures")
        or []
    )

    seen: set[str] = set()
    urls: list[str] = []

    def _add(url: str | None) -> None:
        """Adiciona url normalizada, evitando duplicatas."""
        if not url or not isinstance(url, str):
            return
        normalized = _normalize_photo_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    if isinstance(photos, list):
        for p in photos:
            if isinstance(p, dict):
                # Prioridade: largeUrl > url > mediumUrl > src > image > smallUrl
                _add(_safe_get(p, "largeUrl"))
                _add(_safe_get(p, "url"))
                _add(_safe_get(p, "mediumUrl"))
                _add(_safe_get(p, "src"))
                _add(_safe_get(p, "image"))
                _add(_safe_get(p, "smallUrl"))
            elif isinstance(p, str):
                _add(p)

    # Foto principal / capa (inserida no início)
    main_photo = _safe_get(listing, "mainPhoto") or _safe_get(listing, "coverPhoto") or _safe_get(listing, "thumbnail")
    if isinstance(main_photo, dict):
        _add(_safe_get(main_photo, "largeUrl"))
        _add(_safe_get(main_photo, "url"))
        _add(_safe_get(main_photo, "src"))
    elif isinstance(main_photo, str):
        _add(main_photo)

    # Se adicionamos a main/cover e ela não veio primeiro em urls,
    # a _add() já a coloca no final via append.  Reordenamos.
    # A main/cover deve ser a primeira se existir e estiver na lista.
    if main_photo and urls and len(urls) > 1:
        main_url = _normalize_photo_url(
            _safe_get(main_photo, "largeUrl")
            or _safe_get(main_photo, "url")
            or _safe_get(main_photo, "src")
        ) if isinstance(main_photo, dict) else _normalize_photo_url(main_photo)
        if main_url in seen and urls[0] != main_url:
            urls.remove(main_url)
            urls.insert(0, main_url)

    return urls


def _to_float(val: Any) -> Optional[float]:
    """Converte valor para float ou None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> Optional[int]:
    """Converte valor para int ou None."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ── Main: processar arquivo(s) JSON ───────────────────────────────────────────

def process_file(
    path: str,
    build_id: str = "",
    output: str | None = None,
) -> list[Imovel]:
    """
    Lê um arquivo JSON do QuintoAndar e retorna lista de Imovel.

    Nunca lança exceção — loga warning e retorna lista vazia em caso de erro.

    Args:
        path: Caminho do arquivo JSON (Next.js data route ou API response).
        build_id: Build ID opcional.
        output: Se informado, salva o resultado como JSON.

    Returns:
        Lista de Imovel.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as exc:
        log_warning(f"Erro ao ler arquivo '{path}': {exc}")
        return []

    imoveis = from_quintoandar_safe(data, build_id=build_id)

    if output and imoveis:
        _save_json(imoveis, output)
        log_warning(f"Salvo {len(imoveis)} imóveis em {output}")

    return imoveis


def main():
    """CLI: processa arquivo(s) JSON do QuintoAndar."""
    import argparse

    parser = argparse.ArgumentParser(description="Parse QuintoAndar listing data to unified Imovel schema")
    parser.add_argument("input", nargs="+", help="Arquivo(s) JSON de entrada (Next.js data route ou API)")
    parser.add_argument("--build-id", default="", help="Build ID do Next.js (para montar URLs)")
    parser.add_argument("--output", "-o", help="Arquivo de saída (opcional; stdout se omitido)")
    parser.add_argument("--pretty", action="store_true", help="JSON formatado (indentado)")
    args = parser.parse_args()

    all_imoveis: list[Imovel] = []
    for input_path in args.input:
        imoveis = process_file(input_path, build_id=args.build_id)
        all_imoveis.extend(imoveis)
        print(f"📄 {input_path}: {len(imoveis)} imóveis parseados", file=sys.stderr)

    # Validação
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from validacao import validar_lote, relatorio_resumido

    lote = validar_lote(all_imoveis)
    print(relatorio_resumido(lote), file=sys.stderr)

    # Saída
    indent = 2 if args.pretty else None
    output_data = [i.to_dict() for i in all_imoveis]

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=indent, default=str)
        print(f"✅ Salvo: {args.output} ({len(all_imoveis)} imóveis)", file=sys.stderr)
    else:
        print(json.dumps(output_data, ensure_ascii=False, indent=indent, default=str))


def _save_json(imoveis: list[Imovel], path: str):
    """Salva lista de Imovel como JSON."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [i.to_dict() for i in imoveis],
            f, ensure_ascii=False, indent=2, default=str,
        )


# ── Quando executado diretamente ──────────────────────────────────────────────

if __name__ == "__main__":
    main()
