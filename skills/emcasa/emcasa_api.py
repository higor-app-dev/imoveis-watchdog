#!/usr/bin/env python3
"""
emcasa_api — Cliente da API de busca do EmCasa.

A EmCasa usa a plataforma Foundation/Garagem AI (cdn.fndn.ai) como backend
de busca, que por sua vez indexa dados do Algolia. A API é pública (sem auth)
e retorna dados JSON estruturados.

API: POST https://cdn.fndn.ai/site/api/sites/{site_id}/search
Site ID (fixo): ab158f8f-0a75-4f9f-8a9b-54b834aa2698

Uso:
    export PYTHONPATH=skills/emcasa:$PYTHONPATH
    python emcasa_api.py --cidade "São Paulo" --paginas 0-5
    python emcasa_api.py --cidade "São Paulo" --todas  # todas as páginas
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger("emcasa_api")

# ── Constantes ─────────────────────────────────────────────────────────────────

SITE_ID = "ab158f8f-0a75-4f9f-8a9b-54b834aa2698"
API_URL = f"https://cdn.fndn.ai/site/api/sites/{SITE_ID}/search"
DEFAULT_PER_PAGE = 12  # default da API
MAX_PER_PAGE = 250     # máximo que a API aceita (testado empiricamente)
DEFAULT_DELAY = 0.5    # segundos entre requisições (rate limiting)
MAX_RETRIES = 3

# Caminho do schema (importa do projeto pai)
SCHEMA_PATH = os.environ.get(
    "IMOVEL_SCHEMA_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "shared", "imovel_schema.py"),
)

# ── Tipos ──────────────────────────────────────────────────────────────────────

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

UF_MAP = {
    "SP": "SP", "RJ": "RJ", "MG": "MG", "ES": "ES",
    "PR": "PR", "SC": "SC", "RS": "RS",
    "BA": "BA", "PE": "PE", "CE": "CE", "RN": "RN", "PB": "PB", "AL": "AL",
    "MA": "MA", "PI": "PI", "SE": "SE",
    "DF": "DF", "GO": "GO", "MT": "MT", "MS": "MS",
    "AM": "AM", "PA": "PA", "RO": "RO", "AC": "AC", "RR": "RR", "AP": "AP",
    "TO": "TO",
}


# ── Erro customizado ───────────────────────────────────────────────────────────

class EmCasaAPIError(Exception):
    """Erro na comunicação com a API do EmCasa."""
    pass


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class EmCasaSearchResult:
    """Resposta da API de busca do EmCasa."""
    found: int                     # total de resultados
    page: int                      # página atual (1-indexed)
    per_page: int                  # resultados por página
    hits: list[dict]               # lista de imóveis
    facet_counts: list[dict]       # contagem de facets
    out_of: Optional[int] = None   # total no índice (pode ser > found com filtros)
    search_time_ms: Optional[int] = None

    @property
    def nb_pages(self) -> int:
        """Número total de páginas (arredondado para cima)."""
        if self.found == 0:
            return 0
        return max(1, -(-self.found // self.per_page))  # ceiling division

    @property
    def has_more(self) -> bool:
        return self.page < self.nb_pages


# ── Cache simples ──────────────────────────────────────────────────────────────

class PageCache:
    """Cache local de páginas já baixadas (evita re-baixar)."""

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir is None:
            cache_dir = os.environ.get(
                "EMCASA_CACHE_DIR",
                os.path.join(os.path.dirname(__file__), "..", "..", "data", "emcasa_cache"),
            )
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_key(self, filter_by: str, page: int, per_page: int) -> str:
        """Gera nome de arquivo único para a consulta."""
        import hashlib
        key = f"{filter_by}:p{page}:pp{per_page}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        return f"{h}_p{page:04d}.json"

    def get(self, filter_by: str, page: int, per_page: int) -> Optional[list[dict]]:
        """Retorna hits cacheados ou None."""
        fname = self._cache_key(filter_by, page, per_page)
        fpath = os.path.join(self.cache_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r") as f:
                    data = json.load(f)
                logger.debug(f"Cache HIT: {fname} ({len(data)} hits)")
                return data
            except (json.JSONDecodeError, OSError):
                logger.warning(f"Cache corrompido: {fname}, ignorando")
                return None
        return None

    def put(self, filter_by: str, page: int, per_page: int, hits: list[dict]):
        """Salva hits no cache."""
        fname = self._cache_key(filter_by, page, per_page)
        fpath = os.path.join(self.cache_dir, fname)
        try:
            with open(fpath, "w") as f:
                json.dump(hits, f, ensure_ascii=False)
            logger.debug(f"Cache WRITE: {fname}")
        except OSError as e:
            logger.warning(f"Erro ao escrever cache {fname}: {e}")

    def clear(self):
        """Limpa todo o cache."""
        import shutil
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        logger.info(f"Cache limpo: {self.cache_dir}")


# ── Cliente da API ─────────────────────────────────────────────────────────────

class EmCasaClient:
    """Cliente HTTP para a API de busca do EmCasa (Foundation/Garagem AI)."""

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        cache: Optional[PageCache] = None,
        user_agent: str = "imoveis-watchdog/1.0",
    ):
        self.delay = delay
        self.cache = cache
        self.user_agent = user_agent
        self._last_request = 0.0
        self._stats = {"requests": 0, "cache_hits": 0, "errors": 0}

    def _rate_limit(self):
        """Aguarda o delay mínimo entre requisições."""
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _build_search_payload(
        self,
        filter_by: str,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
        fetch_facets: bool = False,
    ) -> dict:
        """Monta o payload da requisição POST."""
        payload: dict[str, Any] = {
            "q": "*",
            "per_page": per_page,
            "page": page,
            "filter_by": filter_by,
        }
        if fetch_facets:
            payload["facet_by"] = (
                "buildingAmenities,listing_type,location_city,"
                "location_neighborhood,location_state,location_street,"
                "price,propertyFeatures,property_area_total,"
                "property_bathrooms,property_bedrooms,"
                "property_parking_spots,property_type"
            )
            payload["max_facet_values"] = 100
        return payload

    def search_page(
        self,
        filter_by: str,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
        fetch_facets: bool = False,
    ) -> EmCasaSearchResult:
        """
        Busca uma página de resultados.

        Args:
            filter_by: Filtro no formato "campo:=valor && campo2:=valor2"
                       Ex.: "location_state:=SP && location_city:=São Paulo"
            page: Número da página (1-indexed).
            per_page: Resultados por página (máx 250).
            fetch_facets: Se True, retorna facets na resposta.

        Returns:
            EmCasaSearchResult com os resultados.
        """
        # Verifica cache primeiro
        if self.cache:
            cached = self.cache.get(filter_by, page, per_page)
            if cached is not None:
                self._stats["cache_hits"] += 1
                # Retorna um resultado sintético (sem found/nbPages do cache)
                return EmCasaSearchResult(
                    found=0, page=page, per_page=per_page,
                    hits=cached, facet_counts=[], out_of=0,
                )

        self._rate_limit()
        self._stats["requests"] += 1

        payload = self._build_search_payload(filter_by, page, per_page, fetch_facets)
        body = json.dumps(payload).encode("utf-8")

        req = Request(
            API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
                "Origin": "https://www.emcasa.com",
                "Referer": "https://www.emcasa.com/",
            },
            method="POST",
        )

        for attempt in range(MAX_RETRIES):
            try:
                with urlopen(req, timeout=30) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                break
            except (HTTPError, URLError, OSError) as e:
                self._stats["errors"] += 1
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Erro na requisição (tentativa {attempt+1}): {e}. "
                                   f"Re-tentando em {wait}s...")
                    time.sleep(wait)
                else:
                    raise EmCasaAPIError(
                        f"Falha após {MAX_RETRIES} tentativas: {e}"
                    ) from e

        result = EmCasaSearchResult(
            found=raw.get("found", 0),
            page=raw.get("page", page),
            per_page=per_page,
            hits=raw.get("hits", []),
            facet_counts=raw.get("facet_counts", []),
            out_of=raw.get("out_of"),
            search_time_ms=raw.get("search_time_ms"),
        )

        # Salva no cache
        if self.cache:
            self.cache.put(filter_by, page, per_page, result.hits)

        return result

    def search_all(
        self,
        filter_by: str,
        per_page: int = DEFAULT_PER_PAGE,
        max_pages: Optional[int] = None,
        on_progress: Optional[callable] = None,
    ) -> list[dict]:
        """
        Itera por TODAS as páginas e retorna todos os hits.

        A primeira chamada descobre o total (found) e nb_pages.
        As páginas subsequentes são iteradas em sequência.

        A primeira página SEMPRE bate na API real (ignora cache)
        para descobrir o total de resultados corretamente.

        Args:
            filter_by: Filtro de busca.
            per_page: Resultados por página.
            max_pages: Máximo de páginas (None = todas).
            on_progress: Callback(page, nb_pages, hits_acumulados) para progresso.

        Returns:
            Lista completa de todos os hits (dicts de imóvel).
        """
        # Primeira página — descobre total e nb_pages (SEMPRE via API)
        # Guarda cache original para restaurar depois
        orig_cache = self.cache
        self.cache = None
        try:
            first = self.search_page(filter_by, page=1, per_page=per_page)
        finally:
            self.cache = orig_cache

        # Salva no cache após a chamada real (se cache ativo)
        if orig_cache:
            orig_cache.put(filter_by, 1, per_page, first.hits)

        all_hits = list(first.hits)
        nb_pages = first.nb_pages
        found = first.found

        logger.info(f"Total: {found} imóveis em {nb_pages} páginas "
                     f"(per_page={per_page})")

        if nb_pages <= 1:
            return all_hits

        if max_pages is not None:
            nb_pages = min(nb_pages, max_pages)
            logger.info(f"Limitado a {nb_pages} páginas (max_pages={max_pages})")

        if on_progress:
            on_progress(page=1, nb_pages=nb_pages, total=found, hits=len(all_hits))

        # Páginas restantes (2..nb_pages)
        for page in range(2, nb_pages + 1):
            try:
                result = self.search_page(filter_by, page=page, per_page=per_page)
                all_hits.extend(result.hits)

                if on_progress:
                    on_progress(page=page, nb_pages=nb_pages, total=found,
                                hits=len(all_hits))

            except EmCasaAPIError as e:
                logger.error(f"Erro na página {page}: {e}")
                # Continua para a próxima página
                continue

        return all_hits

    def get_stats(self) -> dict:
        """Retorna estatísticas do cliente."""
        return dict(self._stats)


# ── Filtros helpers ────────────────────────────────────────────────────────────

def filter_city(cidade: str, uf: str = "SP") -> str:
    """Monta filtro para buscar por cidade."""
    return f"location_state:={uf} && location_city:={cidade}"


def filter_city_type(cidade: str, tipo: str, uf: str = "SP") -> str:
    """Monta filtro para cidade + tipo de imóvel."""
    tipo_en = _tipo_para_en(tipo)
    return f"location_state:={uf} && location_city:={cidade} && property_type:={tipo_en}"


def filter_neighborhood(bairro: str, cidade: str, uf: str = "SP") -> str:
    """Monta filtro para bairro específico."""
    return f"location_state:={uf} && location_city:={cidade} && location_neighborhood:={bairro}"


def _tipo_para_en(tipo_br: str) -> str:
    """Converte tipo BR para EN (formato da API)."""
    inv_map = {v: k for k, v in TIPO_MAP.items()}
    t = tipo_br.lower().strip()
    return inv_map.get(t, t)


# ── Parser: Documento API → dict normalizado ──────────────────────────────────

def parse_hit(doc: dict) -> dict:
    """
    Converte um hit da API do EmCasa para o schema normalizado.

    Retorna dict no formato do schema Imovel:
        id, titulo, url, fonte, endereco, bairro, cidade, uf,
        preco_venda, preco_aluguel, condominio, iptu,
        area, quartos, banheiros, vagas, tipo,
        descricao, amenities, fotos, data_coleta
    """
    now = datetime.now(timezone.utc).isoformat()
    d = doc.get("document", doc)  # hits podem ser {document: {...}} ou diretos

    # ID
    raw_id = d.get("id", d.get("unitKey", d.get("objectID", "")))
    listing_id = str(raw_id) if raw_id else ""

    # Título
    titulo = d.get("unitDescription", d.get("title", d.get("name", ""))) or ""
    if not titulo:
        tipo = d.get("propertyType", "")
        bairro = d.get("neighborhood", d.get("location_neighborhood", ""))
        quartos = d.get("bedrooms", 0)
        parts = [p for p in [tipo, f"{quartos}q" if quartos else "", bairro] if p]
        titulo = " ".join(parts) if parts else "Imóvel EmCasa"

    # URL
    slug = d.get("slug", d.get("unitKey", listing_id))
    url = f"https://www.emcasa.com/imovel/{slug}" if slug else ""

    # Preços
    preco_venda = d.get("askingPrice")
    if preco_venda is not None:
        preco_venda = float(preco_venda)

    condominio = d.get("condoFee")
    if condominio is not None:
        condominio = float(condominio)

    iptu = d.get("propertyTax")
    if iptu is not None:
        iptu = float(iptu)

    # Área
    area_total = d.get("totalArea")
    area_util = d.get("usableArea")
    area_m2 = None
    if area_total is not None:
        area_m2 = float(area_total)
    elif area_util is not None:
        area_m2 = float(area_util)

    # Tipo
    tipo_original = d.get("propertyType", "").lower()
    tipo = TIPO_MAP.get(tipo_original, tipo_original)

    # Amenities
    amenities = d.get("buildingAmenities", []) or []
    if isinstance(amenities, list):
        amenities = [str(a).lower() for a in amenities]
    else:
        amenities = []

    # Características do imóvel (features)
    features = d.get("propertyFeatures", []) or []
    if isinstance(features, list):
        features = [str(f).lower() for f in features]
    else:
        features = []

    all_features = sorted(set(amenities + features))

    # Fotos
    fotos = d.get("imageUrls", []) or []
    if isinstance(fotos, list):
        fotos = [str(u) for u in fotos if str(u).startswith("http")]
    else:
        fotos = []

    # Coordenadas
    coords = d.get("coordinates", [None, None])
    if isinstance(coords, dict):
        lat = coords.get("lat", coords.get("latitude"))
        lon = coords.get("lng", coords.get("longitude"))
        coords = [lat, lon]

    return {
        "id": f"emcasa_{listing_id}",
        "titulo": titulo,
        "url": url,
        "fonte": "emcasa",
        "endereco": d.get("street", d.get("address", d.get("location_street", ""))) or "",
        "bairro": d.get("neighborhood", d.get("location_neighborhood", "")) or "",
        "cidade": d.get("city", d.get("location_city", "")) or "",
        "uf": d.get("state", d.get("location_state", "")) or "SP",
        "preco_venda": preco_venda,
        "preco_aluguel": None,
        "condominio": condominio,
        "iptu": iptu,
        "area": area_m2,
        "quartos": d.get("bedrooms"),
        "banheiros": d.get("bathrooms"),
        "vagas": d.get("parkingSpots", d.get("property_parking_spots")),
        "tipo": tipo,
        "descricao": d.get("unitDescription", d.get("description", "")) or "",
        "amenities": all_features,
        "fotos": fotos,
        "data_coleta": now,
        "_raw": {
            "id": listing_id,
            "buildingName": d.get("buildingName", d.get("building_name")),
            "floor": d.get("floor"),
            "coordinates": coords,
            "condoFee": condominio,
            "propertyTax": iptu,
            "totalArea": area_total,
            "usableArea": area_util,
            "createdAt": d.get("createdAt"),
            "buildingAmenities": amenities,
            "propertyFeatures": features,
        },
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Cliente da API de busca do EmCasa (Foundation/Garagem AI)"
    )
    parser.add_argument("--cidade", default="São Paulo",
                        help="Cidade para buscar (default: São Paulo)")
    parser.add_argument("--uf", default="SP",
                        help="UF (default: SP)")
    parser.add_argument("--bairro", default=None,
                        help="Bairro para filtrar (opcional)")
    parser.add_argument("--tipo", default=None,
                        help="Tipo de imóvel (apartamento, casa, cobertura...)")
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE,
                        help=f"Resultados por página (default: {DEFAULT_PER_PAGE})")
    parser.add_argument("--paginas", default=None,
                        help="Faixa de páginas (ex: 0-5, 10-20)")
    parser.add_argument("--todas", action="store_true",
                        help="Iterar todas as páginas da cidade")
    parser.add_argument("--max-paginas", type=int, default=None,
                        help="Máximo de páginas para iterar (com --todas)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Delay entre requisições em segundos (default: {DEFAULT_DELAY})")
    parser.add_argument("--no-cache", action="store_true",
                        help="Desabilitar cache")
    parser.add_argument("--cache-dir", default=None,
                        help="Diretório de cache")
    parser.add_argument("--output", "-o", default=None,
                        help="Arquivo de saída JSON")
    parser.add_argument("--pretty", action="store_true",
                        help="JSON formatado (indentado)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Log verbose")
    parser.add_argument("--apenas-info", action="store_true",
                        help="Apenas mostrar info da cidade (total, facets)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Cache
    cache = None
    if not args.no_cache:
        cache = PageCache(cache_dir=args.cache_dir)

    client = EmCasaClient(delay=args.delay, cache=cache)

    # Monta filtro
    if args.bairro:
        filter_by = filter_neighborhood(args.bairro, args.cidade, args.uf)
    elif args.tipo:
        filter_by = filter_city_type(args.cidade, args.tipo, args.uf)
    else:
        filter_by = filter_city(args.cidade, args.uf)

    logger.info(f"Filtro: {filter_by}")

    if args.apenas_info:
        # Busca apenas a primeira página para info
        result = client.search_page(filter_by, page=1, per_page=1, fetch_facets=True)
        print(json.dumps({
            "cidade": args.cidade,
            "uf": args.uf,
            "total": result.found,
            "paginas": result.nb_pages,
            "por_pagina": args.per_page,
            "facets": result.facet_counts,
        }, ensure_ascii=False, indent=2))
        return

    if args.todas:
        # Todas as páginas
        def progress(page, nb_pages, total, hits):
            pct = page / nb_pages * 100
            sys.stderr.write(f"\r  Página {page}/{nb_pages} ({pct:.0f}%) — "
                             f"{hits} imóveis baixados    ")
            sys.stderr.flush()

        all_hits = client.search_all(
            filter_by,
            per_page=args.per_page,
            max_pages=args.max_paginas,
            on_progress=progress,
        )
        sys.stderr.write("\n")
        logger.info(f"Total baixado: {len(all_hits)} imóveis")
        data = all_hits

    elif args.paginas:
        # Faixa específica
        parts = args.paginas.split("-")
        start = int(parts[0])
        end = int(parts[1]) if len(parts) > 1 else start
        data = []
        for page in range(start, end + 1):
            try:
                result = client.search_page(filter_by, page=page, per_page=args.per_page)
                data.extend(result.hits)
                logger.info(f"Página {page}: {len(result.hits)} hits "
                            f"(acumulado: {len(data)})")
            except EmCasaAPIError as e:
                logger.error(f"Erro na página {page}: {e}")

    else:
        # Apenas uma página
        page = 1
        result = client.search_page(filter_by, page=page, per_page=args.per_page,
                                     fetch_facets=True)
        logger.info(f"Página {page}: {len(result.hits)} hits de {result.found} total")
        data = [parse_hit(h) for h in result.hits]

    # Converte para schema normalizado
    if isinstance(data, list) and data and not isinstance(data[0], dict) or \
       (isinstance(data, list) and data and "document" in (data[0] if isinstance(data[0], dict) else {})):
        parsed = [parse_hit(h) for h in data]
    else:
        parsed = data if isinstance(data, list) else []

    # Estatísticas
    stats = client.get_stats()
    logger.info(f"Requisições: {stats['requests']}, "
                f"Cache hits: {stats['cache_hits']}, "
                f"Erros: {stats['errors']}")

    # Gera output
    output = {
        "metadata": {
            "cidade": args.cidade,
            "uf": args.uf,
            "filtro": filter_by,
            "total_found": None,
            "total_hits": len(parsed),
            "stats": stats,
            "data_coleta": datetime.now(timezone.utc).isoformat(),
        },
        "imoveis": parsed,
    }

    output_json = json.dumps(output, ensure_ascii=False,
                             indent=2 if args.pretty else None)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        logger.info(f"Salvo em: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
