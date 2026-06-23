#!/usr/bin/env python3
"""
algolia_parser — Converte um hit bruto do Algolia (EmCasa) para o schema unificado.

A EmCasa indexa seus imóveis no Algolia via Foundation/Garagem AI.
Cada "hit" do Algolia contém dezenas de campos. Esta função extrai
apenas os campos do schema unificado e aplica transformações:

  - priceChangePercent: computado se previousPrice != price
  - propertyFeatures + buildingAmenities: merged como listas de strings
  - coordinates: normalizado para dict {"lat": ..., "lng": ...}
  - Fallback: campos ausentes ficam como None / [] / "" sem crash

Uso:
    from algolia_parser import parse_hit

    result = parse_hit(raw_algolia_hit)
    # result é um dict com todas as chaves do schema unificado
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("algolia_parser")

# ── Chaves obrigatórias do schema unificado ──────────────────────────────────

SCHEMA_KEYS = frozenset({
    "askingPrice",
    "price",
    "previousPrice",
    "priceChangePercent",
    "bedrooms",
    "bathrooms",
    "parkingSpaces",
    "suites",
    "property_area_total",
    "property_type",
    "location_neighborhood",
    "location_city",
    "location_street",
    "condoFee",
    "propertyTax",
    "propertyFeatures",
    "buildingAmenities",
    "imageUrls",
    "thumbnailUrls",
    "listing_type",
    "propertyTitle",
    "description",
    "coordinates",
    "floor",
    "buildingName",
    "photoCount",
    "videoCount",
    "status",
})


# ── Helpers de acesso seguro ─────────────────────────────────────────────────

def _safe_get(hit: dict, *keys: str, default: Any = None) -> Any:
    """Retorna o primeiro valor não-None encontrado na ordem de keys."""
    for key in keys:
        val = hit.get(key)
        if val is not None:
            return val
    return default


def _to_int(val: Any) -> int | None:
    """Converte valor para int ou None."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _to_float(val: Any) -> float | None:
    """Converte valor para float ou None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_str(val: Any, default: str = "") -> str:
    """Converte valor para string com segurança."""
    if val is None:
        return default
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    return str(val) if val else default


def _to_list(val: Any) -> list:
    """Converte valor para lista com segurança."""
    if isinstance(val, list):
        return val
    if val is None:
        return []
    # Pode ser uma string separada por vírgula
    if isinstance(val, str):
        return [s.strip() for s in val.split(",") if s.strip()]
    return []


# ── Computa priceChangePercent ────────────────────────────────────────────────

def _compute_price_change_percent(price: float | None, previous_price: float | None) -> float | None:
    """
    Computa a variação percentual de preço.

    Fórmula: ((price - previousPrice) / previousPrice) * 100

    Retorna None se não for possível calcular (preço anterior ausente/zero).
    """
    if previous_price is None or previous_price == 0:
        return None
    if price is None:
        return None
    if price == previous_price:
        return 0.0
    return round(((price - previous_price) / previous_price) * 100, 2)


# ── Normaliza coordenadas ────────────────────────────────────────────────────

def _normalize_coordinates(hit: dict) -> dict | None:
    """
    Extrai coordenadas normalizadas.

    Aceita formatos:
      - {"coordinates": [lat, lng]}
      - {"coordinates": {"lat": ..., "lng": ...}}
      - {"coordinates": {"latitude": ..., "longitude": ...}}
      - {"latitude": ..., "longitude": ...}  (campos raiz)
    """
    coords = hit.get("coordinates")

    if isinstance(coords, list) and len(coords) >= 2:
        lat, lng = coords[0], coords[1]
        if lat is not None and lng is not None:
            return {"lat": _to_float(lat), "lng": _to_float(lng)}

    if isinstance(coords, dict):
        lat = coords.get("lat") or coords.get("latitude")
        lng = coords.get("lng") or coords.get("longitude")
        if lat is not None and lng is not None:
            return {"lat": _to_float(lat), "lng": _to_float(lng)}

    # Fallback: campos raiz
    lat = hit.get("latitude") or hit.get("lat")
    lng = hit.get("longitude") or hit.get("lng") or hit.get("lon")
    if lat is not None and lng is not None:
        return {"lat": _to_float(lat), "lng": _to_float(lng)}

    return None


# ── Normalização de URLs de fotos ─────────────────────────────────────────────

CDN_FNDN_AI = "cdn.fndn.ai"
HIGH_RES_MAP = {
    "/detail": "/large",
    "/thumbnail": "/large",
    "/thumb": "/large",
}


def _normalize_to_high_res(url: str) -> str:
    """
    Converte URLs de imagens do CDN da EmCasa para alta resolução.
    Retorna ``/large`` sempre que detecta um sufixo conhecido.
    Para URLs de outros CDNs, retorna a URL original.
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return url
    for old_suffix, new_suffix in HIGH_RES_MAP.items():
        if old_suffix in url:
            return url.replace(old_suffix, new_suffix)
    return url


def _normalize_photo_urls(raw_list: list) -> list[str]:
    """
    Normaliza uma lista de URLs de fotos: converte para alta resolução,
    filtra apenas URLs HTTP(S) absolutas, remove duplicatas.
    """
    if not isinstance(raw_list, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for u in raw_list:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        high_res = _normalize_to_high_res(u)
        if high_res not in seen:
            seen.add(high_res)
            result.append(high_res)
    return result


# ── Função principal ──────────────────────────────────────────────────────────

def parse_hit(hit: dict) -> dict:
    """
    Converte um hit bruto do Algolia (EmCasa) para o schema unificado.

    Args:
        hit: Dict cru do Algolia, conforme retornado por extract_page().

    Returns:
        Dict com todas as chaves do schema unificado.
        Campos ausentes recebem fallbacks seguros (None, [], "").

    Raises:
        TypeError: se hit não for dict.
    """
    if not isinstance(hit, dict):
        raise TypeError(f"parse_hit espera dict, recebeu {type(hit).__name__}")

    # ── Preços ──────────────────────────────────────────────────────────────
    asking_price = _to_float(_safe_get(hit, "askingPrice"))
    price = _to_float(_safe_get(hit, "price", "askingPrice"))
    previous_price = _to_float(_safe_get(hit, "previousPrice"))

    # Tenta usar o valor já computado pelo Algolia, senão computa
    price_change_raw = hit.get("priceChangePercent")
    price_change_pct: float | None = _to_float(price_change_raw)
    if price_change_pct is None:
        price_change_pct = _compute_price_change_percent(price, previous_price)

    # ── Características numéricas ───────────────────────────────────────────
    bedrooms = _to_int(_safe_get(hit, "bedrooms", "property_bedrooms"))
    bathrooms = _to_int(_safe_get(hit, "bathrooms", "property_bathrooms"))
    parking_spaces = _to_int(_safe_get(hit, "parkingSpaces", "property_parking_spots", "parkingSpots"))
    suites = _to_int(_safe_get(hit, "suites", "property_suites"))

    # ── Área ────────────────────────────────────────────────────────────────
    property_area_total = _to_int(_safe_get(hit, "property_area_total", "totalArea"))

    # ── Tipo ────────────────────────────────────────────────────────────────
    property_type = _to_str(_safe_get(hit, "property_type", "propertyType"))

    # ── Localização ─────────────────────────────────────────────────────────
    neighborhood = _to_str(_safe_get(hit, "location_neighborhood", "neighborhood"))
    city = _to_str(_safe_get(hit, "location_city", "city"))
    street = _to_str(_safe_get(hit, "location_street", "street"))

    # ── Condomínio / IPTU ───────────────────────────────────────────────────
    condo_fee = _to_float(_safe_get(hit, "condoFee"))
    property_tax = _to_float(_safe_get(hit, "propertyTax"))

    # ── Features / Amenities ────────────────────────────────────────────────
    building_amenities = _to_list(hit.get("buildingAmenities"))
    property_features = _to_list(hit.get("propertyFeatures"))

    # Merge: sorted + dedup + lowercase
    all_features = sorted({
        str(a).lower().strip()
        for a in building_amenities + property_features
        if a and str(a).strip()
    })

    # ── Mídia ───────────────────────────────────────────────────────────────
    image_urls = _normalize_photo_urls(hit.get("imageUrls", []))
    thumbnail_urls = _normalize_photo_urls(hit.get("thumbnailUrls", []))
    primary_image_url = _normalize_to_high_res(hit.get("primaryImageUrl", ""))

    # primaryImageUrl como primeira foto (se disponível)
    if primary_image_url and primary_image_url.startswith("http"):
        if not image_urls:
            image_urls = [primary_image_url]
        elif image_urls[0] != primary_image_url:
            image_urls = [u for u in image_urls if u != primary_image_url]
            image_urls.insert(0, primary_image_url)

    # ── Listing type / Title / Description ──────────────────────────────────
    listing_type = _to_str(_safe_get(hit, "listing_type", "type"))
    property_title = _to_str(_safe_get(hit, "propertyTitle", "title"))
    description = _to_str(_safe_get(hit, "description", "unitDescription"))

    # ── Coordenadas ─────────────────────────────────────────────────────────
    coordinates = _normalize_coordinates(hit)

    # ── Metadados diversos ──────────────────────────────────────────────────
    floor = _to_str(_safe_get(hit, "floor", "property_floor"))
    building_name = _to_str(_safe_get(hit, "buildingName", "building_name"))
    photo_count = _to_int(_safe_get(hit, "photoCount", "buildingPhotoCount"))
    video_count = _to_int(_safe_get(hit, "videoCount", "externalVideoCount"))
    status = _to_str(_safe_get(hit, "status", "stage"), default="available")

    # ── Monta resultado ────────────────────────────────────────────────────
    return {
        "askingPrice": asking_price,
        "price": price,
        "previousPrice": previous_price,
        "priceChangePercent": price_change_pct,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "parkingSpaces": parking_spaces,
        "suites": suites,
        "property_area_total": property_area_total,
        "property_type": property_type,
        "location_neighborhood": neighborhood,
        "location_city": city,
        "location_street": street,
        "condoFee": condo_fee,
        "propertyTax": property_tax,
        "propertyFeatures": [str(f).lower() for f in property_features],
        "buildingAmenities": [str(a).lower() for a in building_amenities],
        "imageUrls": image_urls,
        "thumbnailUrls": thumbnail_urls,
        "listing_type": listing_type,
        "propertyTitle": property_title,
        "description": description,
        "coordinates": coordinates,
        "floor": floor,
        "buildingName": building_name,
        "photoCount": photo_count,
        "videoCount": video_count,
        "status": status,
    }


# ── Batch convenience ────────────────────────────────────────────────────────

def parse_hits(hits: list[dict]) -> list[dict]:
    """
    Converte uma lista de hits do Algolia para schema unificado.

    Args:
        hits: Lista de dicts de hits.

    Returns:
        Lista de dicts no schema unificado.
    """
    if not isinstance(hits, list):
        logger.warning(f"parse_hits espera list, recebeu {type(hits).__name__}")
        return []
    return [parse_hit(h) for h in hits]
