#!/usr/bin/env python3
"""
emcasa_parser — Converte dados brutos da API do EmCasa para o schema unificado Imovel.

A EmCasa usa Foundation/Garagem AI (cdn.fndn.ai) como backend de busca.
Cada hit retornado pode ser:
  1. { "document": { ... } } — documento envelopado
  2. { ... } — documento direto (sem wrapper)

Campos extras do EmCasa (previousPrice, priceChangePercent, etc.) são preservados
no atributo _extra do objeto Imovel para uso downstream sem quebrar o schema.

Uso:
    from emcasa_parser import from_emcasa_hit, from_emcasa_api_response

    imovel = from_emcasa_hit(raw_document)
    imoveis = from_emcasa_api_response(api_response)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# O schema unificado vive em ~/.hermes/imovel_schema.py
sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel, TIPOS_VALIDOS


# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("emcasa_parser")

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.WARNING)
    _handler.setFormatter(logging.Formatter("[emcasa] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.WARNING)


def log_warning(msg: str) -> None:
    """Emite warning via logging E warnings.warn para visibilidade dupla."""
    logger.warning(msg)
    warnings.warn(msg, stacklevel=2)


# ── Helpers de acesso seguro ──────────────────────────────────────────────────

def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Navega por chaves aninhadas sem crash."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current


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


def _as_str(val: Any, default: str = "") -> str:
    """Converte valor para string com segurança."""
    if val is None:
        return default
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        log_warning(f"Valor não-string inesperado: {type(val).__name__} = {str(val)[:80]}")
        return str(val)[:200]
    return str(val)


def _as_list(val: Any) -> list:
    """Converte valor para lista com segurança."""
    if isinstance(val, list):
        return val
    if val is None:
        return []
    log_warning(f"Valor não-list inesperado: {type(val).__name__}, retornando []")
    return []


# ── Constantes ────────────────────────────────────────────────────────────────

FONTE = "emcasa"

TIPO_MAP = {
    "apartment": "apartamento",
    "house": "casa",
    "penthouse": "cobertura",
    "flat": "flat",
    "kitnet": "kitnet",
    "loft": "loft",
    "townhouse": "sobrado",
    "studio": "studio",
    "commercial": "comercial",
    "land": "terreno",
}


# ── Conversão principal ──────────────────────────────────────────────────────

def from_emcasa_hit(
    hit: dict[str, Any],
    coleta_ts: str | None = None,
) -> Imovel:
    """
    Converte um único hit da API do EmCasa para o schema Imovel unificado.

    Aceita tanto hits com wrapper ``{document: {...}}`` quanto hits diretos.

    Args:
        hit: Dict do imóvel vindo da API do EmCasa.
        coleta_ts: Timestamp de coleta. Auto se omitido.

    Returns:
        Instância de Imovel preenchida. Campos extras do EmCasa ficam
        disponíveis em ``imovel._extra`` (dict).
    """
    if not isinstance(hit, dict):
        log_warning(f"from_emcasa_hit recebeu tipo {type(hit).__name__}, não dict — ignorando")
        return Imovel()

    now = coleta_ts or datetime.now(timezone.utc).isoformat()

    # O hit pode vir como {document: {...}} ou direto
    d = hit.get("document", hit)
    if not isinstance(d, dict):
        log_warning("documento não é dict após unwrap — ignorando")
        return Imovel()

    # ─ ID ──────────────────────────────────────────────────────────────────
    raw_id = d.get("id") or d.get("unitKey") or d.get("objectID") or ""
    imovel_id = _as_str(raw_id)
    if not imovel_id:
        log_warning("Hit sem id, unitKey nem objectID — ID vazio")

    # ─ Título ──────────────────────────────────────────────────────────────
    titulo = _as_str(
        d.get("unitDescription")
        or d.get("title")
        or d.get("name")
        or ""
    )
    if not titulo:
        # Monta título automático
        tipo_label = _map_tipo(_as_str(d.get("propertyType", "")))
        bairro = _as_str(d.get("neighborhood") or d.get("location_neighborhood") or "")
        qtd = d.get("bedrooms")
        parts = [p for p in [tipo_label, f"{qtd}q" if qtd else "", bairro] if p]
        titulo = " ".join(parts) if parts else "Imóvel EmCasa"

    # ─ URL ─────────────────────────────────────────────────────────────────
    slug = _as_str(d.get("slug") or d.get("unitKey") or imovel_id)
    url = f"https://www.emcasa.com/imovel/{slug}" if slug else ""

    # ─ Preços ──────────────────────────────────────────────────────────────
    preco_venda = _to_float(d.get("askingPrice"))

    # ─ Condomínio e IPTU ───────────────────────────────────────────────────
    # Trata 0 como None — casas sem condomínio ou IPTU não-informado
    condominio = _to_float(d.get("condoFee"))
    if condominio is not None and condominio <= 0:
        condominio = None
    iptu = _to_float(d.get("propertyTax"))
    if iptu is not None and iptu <= 0:
        iptu = None

    # ─ Área ────────────────────────────────────────────────────────────────
    area_total = _to_float(d.get("totalArea"))
    area_util = _to_float(d.get("usableArea"))
    area = area_total or area_util

    # ─ Tipo ────────────────────────────────────────────────────────────────
    tipo_original = _as_str(d.get("propertyType", "")).lower()
    tipo = TIPO_MAP.get(tipo_original, tipo_original)

    # ─ Endereço ────────────────────────────────────────────────────────────
    endereco = _as_str(
        d.get("street")
        or d.get("address")
        or d.get("location_street")
        or ""
    )
    bairro = _as_str(
        d.get("neighborhood")
        or d.get("location_neighborhood")
        or ""
    )
    cidade = _as_str(
        d.get("city")
        or d.get("location_city")
        or ""
    )
    uf_raw = _as_str(
        d.get("state")
        or d.get("location_state")
        or ""
    )
    uf = uf_raw.upper()[:2] if uf_raw else ""

    # ─ Características ────────────────────────────────────────────────────
    quartos = _to_int(d.get("bedrooms"))
    banheiros = _to_int(d.get("bathrooms"))
    vagas = None
    for key in ("parkingSpots", "property_parking_spots", "garageSpots"):
        if key in d and d[key] is not None:
            vagas = _to_int(d[key])
            break

    # ─ Descrição ───────────────────────────────────────────────────────────
    descricao = _as_str(
        d.get("unitDescription")
        or d.get("description")
        or ""
    )

    # ─ Amenities (buildingAmenities + propertyFeatures) ────────────────────
    building_amenities = _as_list(d.get("buildingAmenities", []))
    property_features = _as_list(d.get("propertyFeatures", []))
    all_features_raw = sorted(set(
        [str(a).lower() for a in building_amenities] +
        [str(f).lower() for f in property_features]
    ))
    amenities = [_normalize_amenity(a) for a in all_features_raw if a.strip()]

    # ─ Fotos ───────────────────────────────────────────────────────────────
    fotos = _normalize_photo_urls(d.get("imageUrls", []))

    # primaryImageUrl como primeira foto (se disponível e diferente)
    primary = d.get("primaryImageUrl")
    if primary and isinstance(primary, str) and primary.startswith("http"):
        primary_hr = _normalize_to_high_res(primary)
        if not fotos:
            fotos = [primary_hr]
        elif fotos[0] != primary_hr:
            fotos = [u for u in fotos if u != primary_hr]
            fotos.insert(0, primary_hr)

    # ─ Data de publicação ──────────────────────────────────────────────────
    data_pub = d.get("createdAt") or d.get("createdAtIso") or d.get("publishDate")

    # ─ Preço anterior e variação percentual (EmCasa-specific) ──────────────
    previous_price = _to_float(d.get("previousPrice"))
    price_change_pct = _to_float(d.get("priceChangePercent"))

    # ─ Coordenadas ─────────────────────────────────────────────────────────
    coords = d.get("coordinates", None)
    if isinstance(coords, dict):
        lat = coords.get("lat", coords.get("latitude"))
        lon = coords.get("lng", coords.get("longitude"))
        coords = [lat, lon] if lat is not None and lon is not None else None
    elif isinstance(coords, (list, tuple)) and len(coords) >= 2:
        coords = [coords[0], coords[1]]
    else:
        coords = None

    # ─ Constrói Imovel ────────────────────────────────────────────────────
    imovel = Imovel(
        id=f"emcasa_{imovel_id}" if imovel_id else "",
        titulo=titulo[:500],
        url=url,
        fonte=FONTE,
        endereco=endereco,
        bairro=bairro,
        cidade=cidade,
        uf=uf,
        preco_venda=preco_venda,
        preco_aluguel=None,  # EmCasa não expõe aluguel separadamente
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

    # Preserva campos EmCasa extras sem quebrar o schema
    imovel._extra = {
        "id_original": imovel_id,
        "previousPrice": previous_price,
        "priceChangePercent": price_change_pct,
        "buildingName": d.get("buildingName", d.get("building_name")),
        "floor": d.get("floor"),
        "coordinates": coords,
        "totalArea": area_total,
        "usableArea": area_util,
        "buildingAmenities": [str(a).lower() for a in building_amenities],
        "propertyFeatures": [str(f).lower() for f in property_features],
        "objectID": d.get("objectID"),
        "unitKey": d.get("unitKey"),
    }

    return imovel


# ── Conversão de lotes ───────────────────────────────────────────────────────

def from_emcasa_hits(
    hits: list[dict[str, Any]],
) -> list[Imovel]:
    """
    Converte uma lista de hits da API do EmCasa para lista de Imovel.

    Args:
        hits: Lista de dicts de imóveis (com ou sem wrapper ``document``).

    Returns:
        Lista de Imovel.
    """
    if not isinstance(hits, list):
        log_warning(f"from_emcasa_hits recebeu tipo {type(hits).__name__}, não list")
        return []
    now = datetime.now(timezone.utc).isoformat()
    return [from_emcasa_hit(h, coleta_ts=now) for h in hits]


def from_emcasa_api_response(
    response: dict[str, Any],
) -> list[Imovel]:
    """
    Converte a resposta completa da API de busca do EmCasa para lista de Imovel.

    Aceita:
      - Resposta direta: ``{"found": ..., "hits": [...], ...}``
      - Payload com metadata: ``{"metadata": {...}, "imoveis": [...]}``
      - Lista direta de hits

    Args:
        response: Resposta JSON da API ou payload estruturado.

    Returns:
        Lista de Imovel (nunca lança exceção).
    """
    if not isinstance(response, dict):
        log_warning(f"from_emcasa_api_response recebeu tipo {type(response).__name__}, não dict")
        return []

    # Tenta extrair hits de vários formatos
    hits = (
        response.get("imoveis")  # payload já parseado
        or response.get("hits")  # resposta direta da API
        or response.get("results")  # formato alternativo
    )

    if isinstance(hits, list):
        return from_emcasa_hits(hits)

    log_warning("Nenhuma lista de imóveis reconhecida na resposta da API")
    return []


def from_emcasa_safe(
    payload: Any,
) -> list[Imovel]:
    """
    Wrapper à prova de crash que aceita qualquer payload.

    Tenta automaticamente:
      1. API response {hits: [...]}
      2. Lista direta de hits
      3. Dict único (single hit)

    Args:
        payload: Qualquer tipo (dict ou list esperados, segura outros).

    Returns:
        Lista de Imovel (nunca lança exceção).
    """
    try:
        if isinstance(payload, list):
            return from_emcasa_hits(payload)

        if not isinstance(payload, dict):
            log_warning(f"from_emcasa_safe recebeu tipo {type(payload).__name__}")
            return []

        # Tenta API response
        hits = payload.get("hits") or payload.get("imoveis") or payload.get("results")
        if isinstance(hits, list):
            return from_emcasa_hits(hits)

        # Tenta como hit único
        if "document" in payload or "id" in payload:
            now = datetime.now(timezone.utc).isoformat()
            return [from_emcasa_hit(payload, coleta_ts=now)]

        log_warning("Nenhuma estrutura de dados reconhecida no payload")
        return []

    except Exception as exc:
        log_warning(f"Erro inesperado em from_emcasa_safe: {exc}")
        return []


# ── Backward compatibility alias ──────────────────────────────────────────────

def parse_hit(hit: dict[str, Any]) -> dict:
    """
    Mantido para compatibilidade com emcasa_api.py.
    Retorna dict (não Imovel) — mesmo comportamento da função original.

    Para novo código, prefira ``from_emcasa_hit()`` que retorna Imovel.
    """
    imovel = from_emcasa_hit(hit)
    data = imovel.to_dict()
    extra = getattr(imovel, "_extra", {})
    if extra:
        data["_raw"] = extra
    return data


# ── Helpers ──────────────────────────────────────────────────────────────────

def _map_tipo(raw_type: str) -> str:
    """Mapeia tipo do EmCasa (EN) para o schema unificado."""
    if not raw_type:
        return ""
    mapped = TIPO_MAP.get(raw_type.lower())
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


def _normalize_amenity(name: str) -> str:
    """Normaliza nome de amenity para snake_case (sem acentos)."""
    if not isinstance(name, str):
        return str(name) if name else ""
    name = name.lower().strip()
    # Decompor acentos
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.replace(" ", "_").replace("-", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name


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

    O CDN ``cdn.fndn.ai`` serve imagens com sufixos de tamanho:
      - ``/thumbnail`` (~6KB) — miniatura
      - ``/detail`` (~238KB) — média
      - ``/large`` (~1MB) — alta resolução (target)

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


# ── Processamento de arquivo ─────────────────────────────────────────────────

def process_file(
    path: str,
    output: str | None = None,
) -> list[Imovel]:
    """
    Lê um arquivo JSON de hits do EmCasa e retorna lista de Imovel.

    Args:
        path: Caminho do arquivo JSON.
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

    imoveis = from_emcasa_safe(data)

    if output and imoveis:
        _save_json(imoveis, output)
        log_warning(f"Salvo {len(imoveis)} imóveis em {output}")

    return imoveis


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """CLI: processa arquivo(s) JSON de hits do EmCasa."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse EmCasa listing data to unified Imovel schema"
    )
    parser.add_argument("input", nargs="+",
                        help="Arquivo(s) JSON de entrada (hits da API)")
    parser.add_argument("--output", "-o",
                        help="Arquivo de saída (opcional; stdout se omitido)")
    parser.add_argument("--pretty", action="store_true",
                        help="JSON formatado (indentado)")
    args = parser.parse_args()

    all_imoveis: list[Imovel] = []
    for input_path in args.input:
        imoveis = process_file(input_path)
        all_imoveis.extend(imoveis)
        print(f"📄 {input_path}: {len(imoveis)} imóveis parseados", file=sys.stderr)

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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [i.to_dict() for i in imoveis],
            f, ensure_ascii=False, indent=2, default=str,
        )


if __name__ == "__main__":
    main()
