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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# O schema unificado vive em ~/.hermes/imovel_schema.py
sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel, TIPOS_VALIDOS


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
    now = coleta_ts or datetime.now(timezone.utc).isoformat()

    # ─ ID — QuintoAndar usa id string ou int
    raw_id = listing.get("id") or listing.get("listingId") or ""
    imovel_id = str(raw_id)

    # ─ URL do anúncio
    url = _build_url(listing, build_id)

    # ─ Preços
    sale_price = listing.get("salePrice")
    rent_price = listing.get("rentPrice")
    if sale_price is not None:
        preco_venda = float(sale_price)
    else:
        preco_venda = None
    if rent_price is not None:
        preco_aluguel = float(rent_price)
    else:
        preco_aluguel = None

    # ─ Condomínio e IPTU (vem num objeto {condoFee, iptu} ou direto)
    condominio, iptu = _extract_condo_iptu(listing)

    # ─ Tipo do imóvel
    tipo = _map_tipo(listing.get("type", ""))

    # ─ Endereço
    endereco, bairro, cidade, uf = _extract_address(listing)

    # ─ Características
    area = _to_float(listing.get("area") or listing.get("usableArea") or listing.get("totalArea"))
    quartos = _to_int(listing.get("bedrooms"))
    banheiros = _to_int(listing.get("bathrooms"))
    vagas = _to_int(listing.get("parkingSpots") or listing.get("garageSpots") or listing.get("vacancies"))

    # ─ Descrição
    descricao = listing.get("description") or listing.get("shortSaleDescription") or ""

    # ─ Amenities
    amenities = _extract_amenities(listing)

    # ─ Fotos
    fotos = _extract_photos(listing)

    # ─ Título
    titulo = listing.get("title") or listing.get("shortSaleDescription") or ""

    # ─ Data de publicação (se disponível)
    data_pub = listing.get("publishDate") or listing.get("createdAt") or listing.get("createdAtIso")

    return Imovel(
        id=imovel_id,
        titulo=str(titulo)[:500],
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
        descricao=str(descricao)[:5000],
        amenities=amenities,
        fotos=fotos,
        data_coleta=now,
        data_publicacao=str(data_pub) if data_pub else None,
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
    # Navega pela estrutura: pageProps → initialState → houses
    data = payload
    if "pageProps" in data:
        data = data["pageProps"]
    if "initialState" in data:
        data = data["initialState"]

    houses = data.get("houses") or data.get("results") or data.get("listings") or []

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
    results = response.get("results") or response.get("data") or []
    now = datetime.now(timezone.utc).isoformat()
    return [from_quintoandar_listing(h, coleta_ts=now) for h in results]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_url(listing: dict, build_id: str = "") -> str:
    """Monta URL direta do anúncio no QuintoAndar."""
    # Se já tem URL, usa
    url = listing.get("url") or listing.get("shareUrl") or listing.get("canonicalUrl") or ""
    if url:
        # Garante que começa com http
        if url.startswith("/"):
            url = f"https://www.quintoandar.com.br{url}"
        elif not url.startswith("http"):
            url = f"https://www.quintoandar.com.br/{url.lstrip('/')}"
        return url

    # Monta a partir do path
    pid = listing.get("id") or listing.get("listingId") or ""
    slug = listing.get("slug") or listing.get("urlSlug") or ""

    city_slug = listing.get("citySlug") or ""
    if city_slug:
        city_part = city_slug.replace("/", "-")
    else:
        city_part = "sao-paulo-sp-brasil"

    # Determina compra ou aluguel
    prefix = "comprar"
    for_sale = listing.get("forSale")
    if for_sale is False:
        prefix = "alugar"
    if listing.get("rentPrice") and not listing.get("salePrice"):
        prefix = "alugar"

    path_parts = [p for p in [prefix, "imovel", city_part] if p]
    path = "/".join(path_parts)
    if slug:
        path = f"{path}/{slug}"

    return f"https://www.quintoandar.com.br/{path}/{pid}" if pid else f"https://www.quintoandar.com.br/{path}"


def _extract_condo_iptu(listing: dict) -> tuple[Optional[float], Optional[float]]:
    """Extrai condomínio e IPTU do objeto condoIptu ou campos diretos."""
    condo_iptu = listing.get("condoIptu") or listing.get("condominiumIptu") or {}

    if isinstance(condo_iptu, dict):
        condominio = _to_float(condo_iptu.get("condoFee") or condo_iptu.get("condominium") or
                               condo_iptu.get("condominiumFee") or condo_iptu.get("condominio"))
        iptu = _to_float(condo_iptu.get("iptu") or condo_iptu.get("propertyTax"))
    else:
        condominio = None
        iptu = None

    # Fallback: campos diretos no listing
    if condominio is None:
        condominio = _to_float(listing.get("condoPrice") or listing.get("condoFee") or
                               listing.get("condominiumFee") or listing.get("condominio"))
    if iptu is None:
        iptu = _to_float(listing.get("iptu") or listing.get("propertyTax"))

    return condominio, iptu


def _extract_address(listing: dict) -> tuple[str, str, str, str]:
    """
    Extrai endereço completo, bairro, cidade e UF.

    QuintoAndar pode devolver endereço como:
      - Objeto: { address: "Rua X, 123", city: "São Paulo", ... }
      - Strings diretas: neighbourhood, city, stateCode
    """
    addr = listing.get("address") or {}
    if isinstance(addr, dict):
        endereco = addr.get("address") or addr.get("street") or addr.get("fullAddress") or ""
        if not endereco:
            parts = [addr.get("streetName", ""), addr.get("number", "")]
            endereco = " ".join(p for p in parts if p).strip()
        cidade = addr.get("city", "")
        uf = addr.get("stateCode") or addr.get("state", "")
        if len(uf) > 2:
            uf = ""
        # Bairro vem no addr ou no listing
        bairro = (addr.get("neighborhood") or addr.get("neighbourhood") or
                  listing.get("neighbourhood") or listing.get("neighborhood") or "")
    else:
        endereco = str(addr) if addr else ""
        cidade = listing.get("city", "")
        uf = listing.get("stateCode") or listing.get("uf", "")
        if len(uf) > 2:
            uf = ""
        bairro = listing.get("neighbourhood") or listing.get("neighborhood") or ""

    # Fallback: regionName (pode ser o bairro também)
    if not bairro:
        bairro = listing.get("regionName", "")
    # Cidade fallback: extrair do citySlug se disponível (ex: "sao-paulo-sp-brasil")
    if not cidade:
        city_slug = listing.get("citySlug", "")
        if city_slug:
            parts = city_slug.split("-")
            # Últimos 2 são o estado + "brasil"
            city_parts = parts[:-2] if len(parts) > 2 else parts
            cidade = " ".join(city_parts).replace("-", " ").title()

    # UF fallback: extrair do citySlug se tiver (ex: "sao-paulo-sp-brasil")
    if not uf:
        city_slug = listing.get("citySlug", "")
        parts = city_slug.split("-")
        if len(parts) >= 2:
            uf = parts[-2].upper() if len(parts[-2]) == 2 else ""
        if not uf and listing.get("uf"):
            uf = listing.get("uf", "")

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
    amenities = listing.get("amenities") or listing.get("amenitiesList") or listing.get("features") or []

    if isinstance(amenities, list):
        result = []
        for a in amenities:
            if isinstance(a, dict):
                a = a.get("name") or a.get("label") or a.get("value") or str(a)
            if isinstance(a, str) and a.strip():
                result.append(_normalize_amenity(a.strip()))
            elif isinstance(a, str):
                continue
        return result

    if isinstance(amenities, str):
        return [_normalize_amenity(a.strip()) for a in amenities.split(",") if a.strip()]

    return []


def _normalize_amenity(name: str) -> str:
    """Normaliza nome de amenity para snake_case (sem acentos)."""
    import unicodedata
    name = name.lower().strip()
    # Decompor acentos: "são" → "sa\u0303o"
    name = unicodedata.normalize("NFKD", name)
    # Remover marcas diacríticas (acentos, cedilha, etc.)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.replace(" ", "_").replace("-", "_").replace(":", "")
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name


def _extract_photos(listing: dict) -> list[str]:
    """Extrai lista de URLs de fotos."""
    photos = listing.get("photos") or listing.get("images") or listing.get("photoUrls") or listing.get("pictures") or []

    urls = []
    if isinstance(photos, list):
        for p in photos:
            if isinstance(p, dict):
                url = (p.get("url") or p.get("src") or p.get("image") or
                       p.get("largeUrl") or p.get("mediumUrl") or p.get("smallUrl"))
                if url:
                    urls.append(url)
            elif isinstance(p, str) and p.startswith("http"):
                urls.append(p)

    # Também pode vir como campo url direto
    main_photo = listing.get("mainPhoto") or listing.get("coverPhoto") or listing.get("thumbnail")
    if isinstance(main_photo, dict):
        url = main_photo.get("url") or main_photo.get("src")
        if url and url not in urls:
            urls.insert(0, url)
    elif isinstance(main_photo, str) and main_photo.startswith("http") and main_photo not in urls:
        urls.insert(0, main_photo)

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

    Args:
        path: Caminho do arquivo JSON (Next.js data route ou API response).
        build_id: Build ID opcional.
        output: Se informado, salva o resultado como JSON.

    Returns:
        Lista de Imovel.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    imoveis = from_quintoandar_payload(data, build_id=build_id)

    if output:
        _save_json(imoveis, output)

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
    validos = [i for i in all_imoveis if i.is_valid()]
    invalidos = [i for i in all_imoveis if not i.is_valid()]
    if invalidos:
        print(f"⚠️  {len(invalidos)} imóveis com erros de validação:", file=sys.stderr)
        for inv in invalidos:
            print(f"   - {inv.id}: {inv.validate()}", file=sys.stderr)

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
