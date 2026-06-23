"""
extractor — Motor de extração multi-portal.

Carrega targets de config/targets.yaml e portais de config/portals.yaml,
usa o portal_registry para descobrir funções de parsing de cada portal,
e produz listas de Imovel para processamento posterior.

Fluxo:
  1. load_targets() — lê config/targets.yaml
  2. get_portal_extractors() — descobre portais ativos + suas funções
  3. extract_all() — para cada portal + target, extrai listings
  4. collect_results() — agrega tudo em uma lista única

Uso:
    from scripts.extractor import extract_all, load_targets

    targets = load_targets()
    listings = extract_all(targets)
    # listings é uma list[dict] no schema Imovel.to_dict()

A extração real depende do método de cada portal:
  - Portais com dados mockados (zap): gera dados sintéticos
  - Portais com dados pré-coletados: lê de data/results/
  - Portais com web scraping: framework para futura implementação
"""

from __future__ import annotations

import json
import logging
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS_PATH = REPO_ROOT / "config" / "targets.yaml"
DATA_RESULTS_DIR = REPO_ROOT / "data" / "results"

# Schema unificado
sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

logger = logging.getLogger("extractor")

# ── Sample / Mock Data ─────────────────────────────────────────────────────

SAMPLE_LISTINGS: dict[str, list[dict]] = {
    "quintoandar": [
        {
            "id": "qa_001",
            "salePrice": 350000,
            "usableArea": 45,
            "bedrooms": 2,
            "bathrooms": 1,
            "parkingSpots": 1,
            "type": "APARTMENT",
            "title": "Apto 2q c/ vaga na Consolação",
            "description": "Apartamento bem localizado próximo à Av. Paulista",
            "address": {
                "street": "Rua Augusta",
                "streetNumber": "500",
                "neighborhood": "Consolação",
                "city": "São Paulo",
                "stateCode": "SP",
            },
        },
        {
            "id": "qa_002",
            "salePrice": 520000,
            "usableArea": 62,
            "bedrooms": 3,
            "bathrooms": 2,
            "parkingSpots": 1,
            "type": "APARTMENT",
            "title": "Apto 3q na Bela Vista",
            "description": "Apartamento com vista panorâmica",
            "address": {
                "street": "Rua da Consolação",
                "streetNumber": "2000",
                "neighborhood": "Bela Vista",
                "city": "São Paulo",
                "stateCode": "SP",
            },
        },
        {
            "id": "qa_003",
            "salePrice": 280000,
            "usableArea": 38,
            "bedrooms": 1,
            "bathrooms": 1,
            "parkingSpots": 0,
            "type": "APARTMENT",
            "title": "Kitnet no Centro SP",
            "description": "Kitnet reformada no centro",
            "address": {
                "street": "Av. São João",
                "streetNumber": "800",
                "neighborhood": "Centro",
                "city": "São Paulo",
                "stateCode": "SP",
            },
        },
    ],
    "loft": [
        {
            "id": "loft_001",
            "salePrice": 345000,
            "usableArea": 44,
            "bedrooms": 2,
            "bathrooms": 1,
            "parkingSpots": 1,
            "type": "APARTMENT",
            "title": "Apto na Consolação com vaga",
            "description": "Apartamento próximo a tudo",
            "address": {
                "street": "Rua Augusta",
                "streetNumber": "520",
                "neighborhood": "Consolação",
                "city": "São Paulo",
                "stateCode": "SP",
            },
        },
        {
            "id": "loft_002",
            "salePrice": 680000,
            "usableArea": 85,
            "bedrooms": 3,
            "bathrooms": 2,
            "parkingSpots": 2,
            "type": "APARTMENT",
            "title": "Apto 3q amplo em Pinheiros",
            "description": "Apartamento espaçoso em Pinheiros",
            "address": {
                "street": "Rua dos Pinheiros",
                "streetNumber": "900",
                "neighborhood": "Pinheiros",
                "city": "São Paulo",
                "stateCode": "SP",
            },
        },
        {
            "id": "loft_003",
            "salePrice": 950000,
            "usableArea": 110,
            "bedrooms": 3,
            "bathrooms": 3,
            "parkingSpots": 2,
            "type": "APARTMENT",
            "title": "Cobertura em Perdizes",
            "description": "Cobertura duplex com varanda gourmet",
            "address": {
                "street": "Rua Cardoso de Almeida",
                "streetNumber": "1500",
                "neighborhood": "Perdizes",
                "city": "São Paulo",
                "stateCode": "SP",
            },
        },
    ],
    "zap": [
        {
            "codigo": "zap_001",
            "titulo": "Apto 2q Centro SP",
            "preco": 290000,
            "area": 40,
            "quartos": 2,
            "banheiros": 1,
            "bairro": "Centro",
            "cidade": "São Paulo",
            "uf": "SP",
        },
        {
            "codigo": "zap_002",
            "titulo": "Apto 3q Consolação",
            "preco": 510000,
            "area": 60,
            "quartos": 3,
            "banheiros": 2,
            "bairro": "Consolação",
            "cidade": "São Paulo",
            "uf": "SP",
        },
    ],
}

SAMPLE_IMOVEIS: dict[str, list[dict]] = {
    "quintoandar": [
        Imovel(
            id="qa_001",
            titulo="Apto 2q c/ vaga na Consolação",
            fonte="quintoandar",
            endereco="Rua Augusta, 500",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            preco_venda=350000.0,
            area=45.0,
            quartos=2,
            banheiros=1,
            vagas=1,
            tipo="apartamento",
            url="https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/qa_001",
            descricao="Apartamento bem localizado próximo à Av. Paulista",
        ).to_dict(),
        Imovel(
            id="qa_002",
            titulo="Apto 3q na Bela Vista",
            fonte="quintoandar",
            endereco="Rua da Consolação, 2000",
            bairro="Bela Vista",
            cidade="São Paulo",
            uf="SP",
            preco_venda=520000.0,
            area=62.0,
            quartos=3,
            banheiros=2,
            vagas=1,
            tipo="apartamento",
            url="https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/qa_002",
            descricao="Apartamento com vista panorâmica",
        ).to_dict(),
        Imovel(
            id="qa_003",
            titulo="Kitnet no Centro SP",
            fonte="quintoandar",
            endereco="Av. São João, 800",
            bairro="Centro",
            cidade="São Paulo",
            uf="SP",
            preco_venda=280000.0,
            area=38.0,
            quartos=1,
            banheiros=1,
            vagas=0,
            tipo="kitnet",
            url="https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/qa_003",
        ).to_dict(),
    ],
    "loft": [
        Imovel(
            id="loft_001",
            titulo="Apto na Consolação com vaga",
            fonte="loft",
            endereco="Rua Augusta, 520",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            preco_venda=345000.0,
            area=44.0,
            quartos=2,
            banheiros=1,
            vagas=1,
            tipo="apartamento",
            url="https://loft.com.br/imovel/apartamento-consolacao/loft_001",
        ).to_dict(),
        Imovel(
            id="loft_002",
            titulo="Apto 3q amplo em Pinheiros",
            fonte="loft",
            endereco="Rua dos Pinheiros, 900",
            bairro="Pinheiros",
            cidade="São Paulo",
            uf="SP",
            preco_venda=680000.0,
            area=85.0,
            quartos=3,
            banheiros=2,
            vagas=2,
            tipo="apartamento",
            url="https://loft.com.br/imovel/apartamento-pinheiros/loft_002",
        ).to_dict(),
        Imovel(
            id="loft_003",
            titulo="Cobertura em Perdizes",
            fonte="loft",
            endereco="Rua Cardoso de Almeida, 1500",
            bairro="Perdizes",
            cidade="São Paulo",
            uf="SP",
            preco_venda=950000.0,
            area=110.0,
            quartos=3,
            banheiros=3,
            vagas=2,
            tipo="cobertura",
            url="https://loft.com.br/imovel/cobertura-perdizes/loft_003",
        ).to_dict(),
    ],
    "zap": [
        Imovel(
            id="zap_001",
            titulo="Apto 2q Centro SP",
            fonte="zap",
            endereco="Centro",
            bairro="Centro",
            cidade="São Paulo",
            uf="SP",
            preco_venda=290000.0,
            area=40.0,
            quartos=2,
            banheiros=1,
            vagas=0,
            tipo="apartamento",
        ).to_dict(),
        Imovel(
            id="zap_002",
            titulo="Apto 3q Consolação",
            fonte="zap",
            endereco="Consolação",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            preco_venda=510000.0,
            area=60.0,
            quartos=3,
            banheiros=2,
            vagas=0,
            tipo="apartamento",
        ).to_dict(),
    ],
    "emcasa": [
        Imovel(
            id="emcasa_001",
            titulo="Apto 2q na Vila Mariana",
            fonte="emcasa",
            endereco="Rua Domingos de Morais, 1000",
            bairro="Vila Mariana",
            cidade="São Paulo",
            uf="SP",
            preco_venda=850000.0,
            condominio=1200.0,
            iptu=300.0,
            area=72.0,
            quartos=2,
            banheiros=2,
            vagas=1,
            tipo="apartamento",
            url="https://www.emcasa.com/imovel/apto-vila-mariana-sp",
            descricao="Apartamento na Vila Mariana próximo ao metrô",
        ).to_dict(),
        Imovel(
            id="emcasa_002",
            titulo="Cobertura nos Jardins",
            fonte="emcasa",
            endereco="Alameda Lorena, 500",
            bairro="Jardins",
            cidade="São Paulo",
            uf="SP",
            preco_venda=2500000.0,
            condominio=3500.0,
            iptu=800.0,
            area=150.0,
            quartos=4,
            banheiros=3,
            vagas=3,
            tipo="cobertura",
            url="https://www.emcasa.com/imovel/cobertura-jardins-sp",
            descricao="Cobertura duplex nos Jardins com vista panorâmica",
        ).to_dict(),
        Imovel(
            id="emcasa_003",
            titulo="Studio na Consolação",
            fonte="emcasa",
            endereco="Rua da Consolação, 1500",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            preco_venda=400000.0,
            condominio=600.0,
            area=32.0,
            quartos=1,
            banheiros=1,
            vagas=0,
            tipo="studio",
            url="https://www.emcasa.com/imovel/studio-consolacao-sp",
            descricao="Studio compacto na Consolação",
        ).to_dict(),
    ],
}


# ── Load config ────────────────────────────────────────────────────────────


def load_targets(path: str | Path | None = None) -> list[dict]:
    """Carrega alvos de busca de config/targets.yaml.

    Returns:
        Lista de targets, cada um com: portal, modalidade, cidade,
        bairros, tipos, preco_max, quartos_min.
    """
    if path is None:
        path = TARGETS_PATH
    path = Path(path)

    if not path.exists():
        logger.warning(f"Targets config não encontrado: {path}")
        return _default_targets()

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        return _default_targets()

    targets = []
    for portal_slug, modalidades in data.items():
        if portal_slug == "geral":
            continue
        if not isinstance(modalidades, dict):
            continue
        for modalidade, entries in modalidades.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                targets.append({
                    "portal": portal_slug,
                    "modalidade": modalidade,
                    "cidade": entry.get("cidade", ""),
                    "bairros": entry.get("bairros", []),
                    "tipos": entry.get("tipos", []),
                    "preco_max": entry.get("preco_max"),
                    "quartos_min": entry.get("quartos_min"),
                })

    if not targets:
        return _default_targets()

    return targets


def _default_targets() -> list[dict]:
    """Retorna targets padrão quando config não encontrada."""
    return [
        {
            "portal": "quinto_andar",
            "modalidade": "compra",
            "cidade": "sao-paulo-sp-brasil",
            "bairros": [],
            "tipos": ["apartamento"],
            "preco_max": None,
            "quartos_min": None,
        },
        {
            "portal": "loft",
            "modalidade": "compra",
            "cidade": "sp/sao-paulo",
            "bairros": [],
            "tipos": ["apartamentos"],
            "preco_max": None,
            "quartos_min": None,
        },
    ]


# ── Portal discovery ───────────────────────────────────────────────────────


def get_enabled_portals() -> list[dict]:
    """Descobre portais ativos via portal_registry.

    Returns:
        Lista de dicts com slug, name, display_name, e funções do parser.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "skills"))
        from portal_registry import list_active_portals, get_parser_function

        portals_info = list_active_portals()
        result = []
        for p in portals_info:
            portal_dict = {
                "slug": p.slug,
                "name": p.name,
                "display_name": p.display_name,
                "parser_module": p.parser_module,
                "base_url": p.base_url,
                "can_parse_listing": p.can_parse_listing,
                "can_parse_payload": p.can_parse_payload,
                "has_build_url": p.has_build_url,
            }
            result.append(portal_dict)
        return result
    except ImportError as e:
        logger.warning(f"portal_registry não disponível ({e}) — usando fallback")
        return [
            {"slug": "quinto_andar", "name": "quintoandar", "display_name": "QuintoAndar"},
            {"slug": "loft", "name": "loft", "display_name": "Loft"},
        ]


# ── Extraction runners ─────────────────────────────────────────────────────


def _extract_leilao_live(portal_slug: str, target: dict) -> list[dict]:
    """Tenta extração ao vivo para portais de leilão com fetch direto.

    Portais com API pública aberta (Sodré Santoro, Zuk) podem ser
    extraídos sob demanda sem browser.
    """
    import logging as _lg
    _lg.getLogger("sodre_santoro_parser").setLevel(_lg.WARNING)
    _lg.getLogger("zuk_parser").setLevel(_lg.WARNING)

    try:
        if portal_slug == "sodre_santoro":
            sys.path.insert(0, str(REPO_ROOT / "skills" / "sodre_santoro"))
            from sodre_santoro_parser import fetch_listings
            imoveis = fetch_listings(max_pages=1)
            return [i for i in imoveis if i]

        elif portal_slug == "zuk":
            sys.path.insert(0, str(REPO_ROOT / "skills" / "zuk"))
            from zuk_parser import crawl_listing
            pages = crawl_listing(
                start_url="https://www.portalzuk.com.br/leilao-de-imoveis?page=1",
                pages=2,
                rate_limit=1.0,
                timeout=60,
            )
            raw = pages[0] if isinstance(pages, (list, tuple)) and len(pages) > 0 else []
            if not raw:
                return []
            # Convert raw listings to unified schema via from_zuk_payload
            from zuk_parser import from_zuk_payload
            return from_zuk_payload(raw)

        elif portal_slug == "biasi_leiloes":
            # Biasi has parser but no direct live fetch — fall through to pre-coletados
            return []

        elif portal_slug == "mega_leiloes":
            return []

        elif portal_slug == "caixa_imoveis":
            return []

        elif portal_slug == "lello_imoveis":
            return []

    except ImportError as e:
        _lg.getLogger("extractor").debug(f"  _extract_leilao_live({portal_slug}): {e}")
        return []
    except Exception as e:
        _lg.getLogger("extractor").warning(f"  _extract_leilao_live({portal_slug}) erro: {e}")
        return []

    return []


def extract_portal(
    portal_slug: str,
    target: dict,
) -> list[dict]:
    """Extrai listings de um portal específico.

    Fluxo:
      1. Tenta ler dados pré-coletados de data/results/
      2. Se não existir, usa sample/mock data
      3. Tenta usar o parser do portal via portal_registry
      4. Fallback: usa sample data pré-parseado

    Args:
        portal_slug: Slug do portal (ex.: "quinto_andar").
        target: Dict do target de busca.

    Returns:
        Lista de dicts no schema Imovel (to_dict()).
    """
    # 1. Tenta extração ao vivo para portais de leilão
    live = _extract_leilao_live(portal_slug, target)
    if live:
        logger.info(f"  {portal_slug}: {len(live)} listings (live extraction)")
        return live

    # 2. Tenta dados pré-coletados
    pre_coletados = _load_pre_coletados(portal_slug)
    if pre_coletados:
        logger.info(f"  {portal_slug}: {len(pre_coletados)} listings pré-coletados")
        return pre_coletados

    # Tenta usar o parser do portal com sample data
    parser_imoveis = _try_parse_sample(portal_slug)
    if parser_imoveis:
        logger.info(f"  {portal_slug}: {len(parser_imoveis)} listings via parser")
        return parser_imoveis

    # Fallback: sample data pré-parseado
    sample = SAMPLE_IMOVEIS.get(portal_slug.replace("_", ""), [])
    if portal_slug == "quinto_andar":
        sample = SAMPLE_IMOVEIS.get("quintoandar", [])
    elif portal_slug == "zap":
        sample = SAMPLE_IMOVEIS.get("zap", [])

    if sample:
        logger.info(f"  {portal_slug}: {len(sample)} listings (fallback)")
    else:
        logger.warning(f"  {portal_slug}: sem dados disponíveis")
    return sample


def _load_pre_coletados(portal_slug: str) -> list[dict]:
    """Tenta carregar dados pré-coletados de data/results/.

    Procura por arquivos no formato:
      - {portal}_results_*.json   (extração completa)
      - {portal}_*.json           (qualquer arquivo do portal)
    """
    portal_name = portal_slug.replace("_", "")  # quinto_andar → quintoandar
    pattern = f"{portal_name}_*.json"
    matches = sorted(DATA_RESULTS_DIR.glob(pattern))

    if not matches:
        # Tenta também com hífen
        portal_hyphen = portal_slug.replace("_", "-")
        pattern2 = f"{portal_hyphen}_*.json"
        matches = sorted(DATA_RESULTS_DIR.glob(pattern2))

    if not matches:
        return []

    # Pega o mais recente
    latest = matches[-1]
    try:
        with open(latest) as f:
            data = json.load(f)
        # Arquivo é uma lista direta
        if isinstance(data, list):
            return data
        # Arquivo é dict com chave listings/results/imoveis
        listings = data.get("listings", data.get("results", data.get("imoveis", [])))
        if isinstance(listings, list):
            return listings
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"  Erro lendo {latest}: {e}")
        return []


def _try_parse_sample(portal_slug: str) -> list[dict]:
    """Tenta usar o parser real do portal com sample data.

    Usa from_listing() do portal_registry para converter
    sample data bruta em Imovel via o parser real.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "skills"))
        from portal_registry import from_listing, invalidate_cache

        # Pega o nome real do portal
        portal_name = portal_slug.replace("_", "")
        if portal_slug == "quinto_andar":
            portal_name = "quintoandar"
            slug_for_registry = "quinto_andar"
        elif portal_slug == "loft":
            slug_for_registry = "loft"
        else:
            slug_for_registry = portal_slug

        # Verifica se o portal está no registry
        sample_data = SAMPLE_LISTINGS.get(portal_name)
        if not sample_data:
            return []

        # Tenta converter cada sample via parser real
        imoveis = []
        for raw in sample_data:
            try:
                imovel = from_listing(slug_for_registry, raw)
                imoveis.append(imovel.to_dict())
            except (KeyError, AttributeError, ImportError) as e:
                logger.warning(f"  from_listing({slug_for_registry}) falhou: {e}")
                return []

        return imoveis

    except ImportError as e:
        logger.debug(f"  portal_registry não disponível: {e}")
        return []


def extract_all(
    targets: list[dict] | None = None,
) -> list[dict]:
    """Extrai listings de todos os portais ativos.

    Args:
        targets: Lista de targets (de load_targets()). Se None, carrega.

    Returns:
        Lista consolidada de dicts no schema Imovel (to_dict()).
        Cada item tem também o campo 'portal' original para o dedup.
    """
    if targets is None:
        targets = load_targets()

    all_listings: list[dict] = []
    seen_portals: set[str] = set()

    for target in targets:
        portal_slug = target.get("portal", "")
        if not portal_slug:
            continue

        if portal_slug not in seen_portals:
            seen_portals.add(portal_slug)
            listings = extract_portal(portal_slug, target)
            all_listings.extend(listings)

    logger.info(f"Total extraído: {len(all_listings)} listings de {len(seen_portals)} portais")
    return all_listings


# ── Helpers ────────────────────────────────────────────────────────────────


def extract_and_save(
    output_path: str | Path | None = None,
) -> Path:
    """Extrai dados de todos os portais e salva em JSON.

    Args:
        output_path: Caminho para salvar. Se None, gera em data/results/.

    Returns:
        Path do arquivo salvo.
    """
    targets = load_targets()
    listings = extract_all(targets)

    if output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        output_path = DATA_RESULTS_DIR / f"multi_portal_{timestamp}.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(listings),
        "targets": targets,
        "listings": listings,
    }
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(f"Dados salvos em: {output_path}")
    return output_path.resolve()


def list_portals_info() -> list[dict]:
    """Exibe informações dos portais ativos."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "skills"))
        from portal_registry import list_active_portals

        portals = list_active_portals()
        info = []
        for p in portals:
            info.append({
                "slug": p.slug,
                "name": p.name,
                "display_name": p.display_name,
                "enabled": p.enabled,
                "has_listing_parser": p.can_parse_listing,
                "has_payload_parser": p.can_parse_payload,
                "has_build_url": p.has_build_url,
            })
        return info
    except ImportError:
        return [{"slug": "quinto_andar", "name": "quintoandar", "display_name": "QuintoAndar"},
                {"slug": "loft", "name": "loft", "display_name": "Loft"}]
