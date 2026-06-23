"""
loft_parser — Parser for Loft listings extracted via Playwright.

Converts the structured JSON output from scrapers/loft/scrape-loft.js
into the unified Imovel schema used by the watchdog pipeline.

Functions:
    from_loft_listing(dict) -> Imovel | None
        Convert a single listing dict from the scraper's output.

    from_loft_payload(dict|list) -> list[Imovel]
        Convert a scraper output (list of listings) to list of Imovel.

    run_scraper(url: str, pages: int) -> list[Imovel]
        Run the Node.js scraper via subprocess and return parsed results.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Schema import ────────────────────────────────────────────────────────────

# Imovel schema lives at ~/.hermes/imovel_schema.py
_hermes_path = Path.home() / ".hermes"
if str(_hermes_path) not in sys.path:
    sys.path.insert(0, str(_hermes_path))

try:
    from imovel_schema import Imovel
except ImportError:
    Imovel = None  # Fallback: retorna dict se Imovel não estiver disponível

logger = logging.getLogger("loft_parser")

# ── Photo CDN ─────────────────────────────────────────────────────────────────

PHOTO_BASE = "https://content.loft.com.br/homes"


def _normalize_photo_url(url: Any) -> str | None:
    """Normalize a photo URL to absolute CDN URL.

    Handles:
    - Relative filename (e.g. 'facade01.jpg') → prepend CDN base
    - Dict with 'url' key (e.g. {'url': 'facade01.jpg'})
    - Already absolute HTTP URL → pass through
    - None / empty → return None

    Args:
        url: Raw photo value from API/SSR data.

    Returns:
        Absolute URL string, or None if invalid.
    """
    if not url:
        return None
    # Dict format (e.g. {'url': 'facade01.jpg', 'subtitle': 'Sala'})
    if isinstance(url, dict):
        url = url.get("url") or url.get("src") or None
        if not url:
            return None
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    # Already absolute HTTP(S) URL
    if url.startswith("http://") or url.startswith("https://"):
        return url
    # Relative filename → CDN absolute URL
    # Strip leading slash if present
    filename = url.lstrip("/")
    return f"{PHOTO_BASE}/{filename}"


def _collect_photos(raw: dict) -> list[str]:
    """Collect and normalize all photo URLs from a raw listing dict.

    Sources (in priority order):
    1. `photos` — array of filenames or dicts with `url` key (SSR/API/scraper)
    2. `imagens` — fallback for legacy scraper output
    3. `mainPhoto` — prioritized as index 0 (cover image)

    Returns:
        Deduplicated list of absolute CDN URLs.
    """
    seen: set[str] = set()
    urls: list[str] = []

    # Collect candidate URLs from all sources
    candidates: list[str] = []

    # Source 1: photos[] (SSR format: array of strings or {url, ...})
    raw_photos = raw.get("photos") or []
    if isinstance(raw_photos, list):
        for p in raw_photos:
            normalized = _normalize_photo_url(p)
            if normalized:
                candidates.append(normalized)

    # Source 2: imagens (legacy scraper format: array of strings)
    raw_imagens = raw.get("imagens") or raw.get("fotos") or []
    if isinstance(raw_imagens, list):
        for p in raw_imagens:
            normalized = _normalize_photo_url(p)
            if normalized:
                candidates.append(normalized)

    # Prioritize mainPhoto as index 0 (cover/first image)
    main_photo = raw.get("mainPhoto") or raw.get("coverPhoto")
    main_normalized = _normalize_photo_url(main_photo)

    # Build final list: mainPhoto first, then deduped rest
    if main_normalized:
        urls.append(main_normalized)
        seen.add(main_normalized)

    for url in candidates:
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


# ── Field mapping: scraper output -> Imovel ──────────────────────────────────

# Mapeamento direto dos campos do JSON do scraper para o schema Imovel
FIELD_MAP = {
    "id": "id",
    "titulo": "titulo",
    "descricao": "descricao",
    "fonte": "fonte",
    "preco_venda": "preco_venda",
    "preco_anterior": "preco_anterior",
    "data_atualizacao_preco": "data_atualizacao_preco",
    "preco_aluguel": "preco_aluguel",
    "condominio": "condominio",
    "iptu": "iptu",
    "area": "area",
    "quartos": "quartos",
    "suites": "suites",
    "banheiros": "banheiros",
    "vagas": "vagas",
    "andar": "andar",
    "tipo": "tipo",
    "uso": "uso",
    "endereco": "endereco",
    "bairro": "bairro",
    "cidade": "cidade",
    "uf": "uf",
    "cep": "cep",
    "latitude": "latitude",
    "longitude": "longitude",
    "url": "url",
    "origem_id": "origem_id",
    "imagens": "fotos",
    "photos": "fotos",
    "comodidades": "comodidades",
    "agencia": "agencia",
    "data_criacao": "data_criacao",
    "tem_reducao": "tem_reducao",
    "percentual_reducao": "percentual_reducao",
    "raw_id": "raw_id",
    "listingGroupKey": "listingGroupKey",
}


def from_loft_listing(raw: dict) -> dict | Any | None:
    """Converte uma listagem bruta do scraper para dict ou Imovel.

    Args:
        raw: Dict individual do array listings.json.

    Returns:
        Imovel (se disponível) ou dict com os campos mapeados.
        None se o input for inválido.
    """
    if not raw or not isinstance(raw, dict):
        return None

    # Já está no formato do scraper, só mapear
    mapped = {}
    for src_key, dst_key in FIELD_MAP.items():
        if src_key in raw:
            mapped[dst_key] = raw[src_key]

    # ── Secondary field mapping (web_extract / API format) ──────────────
    # Also handles direct keys when not nested in an address object
    ALT_FIELDS = {
        "title": "titulo",
        "description": "descricao",
        "salePrice": "preco_venda",
        "rentPrice": "preco_aluguel",
        "condominiumFee": "condominio",
        "propertyTax": "iptu",
        "bedrooms": "quartos",
        "bathrooms": "banheiros",
        "parkingSpots": "vagas",
        "publishDate": "data_publicacao",
        "disponivel": "disponivel",
        "neighborhood": "bairro",
        "city": "cidade",
        "stateCode": "uf",
    }
    for src_key, dst_key in ALT_FIELDS.items():
        if src_key in raw and src_key not in mapped:
            mapped[dst_key] = raw[src_key]

    # Handle address dict (nested)
    address = raw.get("address", {})
    if isinstance(address, dict):
        ADDR_MAP = {
            "street": "endereco",
            "neighborhood": "bairro",
            "city": "cidade",
            "stateCode": "uf",
        }
        for src_key, dst_key in ADDR_MAP.items():
            if src_key in address and dst_key not in mapped:
                mapped[dst_key] = address[src_key]

    # Handle area (field exists in both formats, may have been mapped already)
    if "area" in raw and "area" not in mapped:
        mapped["area"] = raw["area"]

    # Handle type → tipo with normalization (from "type" key)
    if "type" in raw:
        raw_tipo = str(raw["type"]).strip().lower()
        if raw_tipo:
            mapped["tipo"] = raw_tipo

    # Normalize tipo (in case it came from FIELD_MAP uppercase)
    if "tipo" in mapped and isinstance(mapped["tipo"], str):
        mapped["tipo"] = mapped["tipo"].strip().lower()

    # Handle amenities
    if "amenities" in raw and "amenities" not in mapped:
        mapped["amenities"] = raw["amenities"]

    # Normalize disponivel: string "true"/"false" or int 1/0 -> bool
    if "disponivel" in mapped and not isinstance(mapped["disponivel"], bool):
        v = str(mapped["disponivel"]).strip().lower()
        mapped["disponivel"] = v in ("true", "1", "yes")

    # ── Photo URL normalization ──────────────────────────────────────────
    # Collect, normalize and deduplicate photo URLs from all sources
    # (photos[], imagens[], mainPhoto, coverPhoto)
    mapped["fotos"] = _collect_photos(raw)

    # Garantir campos obrigatórios
    mapped.setdefault("fonte", "loft")
    mapped.setdefault("cidade", "São Paulo")
    mapped.setdefault("uf", "SP")

    # Converter tipos
    for num_field in ["preco_venda", "preco_anterior", "condominio", "iptu",
                       "area", "latitude", "longitude", "percentual_reducao"]:
        if num_field in mapped and mapped[num_field] is not None:
            try:
                mapped[num_field] = float(mapped[num_field])
            except (ValueError, TypeError):
                mapped[num_field] = None

    for int_field in ["quartos", "suites", "banheiros", "vagas", "andar"]:
        if int_field in mapped and mapped[int_field] is not None:
            try:
                mapped[int_field] = int(mapped[int_field])
            except (ValueError, TypeError):
                mapped[int_field] = None

    # Se tem_reducao não veio, computar
    if "tem_reducao" not in mapped or mapped["tem_reducao"] is None:
        prev = mapped.get("preco_anterior")
        curr = mapped.get("preco_venda")
        mapped["tem_reducao"] = bool(prev and curr and prev > curr)
        if mapped["tem_reducao"]:
            mapped["percentual_reducao"] = round((1 - curr / prev) * 100, 2)

    # Se Imovel está disponível, cria instância (ignora campos extras)
    if Imovel is not None:
        try:
            return Imovel.from_dict(mapped).to_dict()
        except Exception as e:
            logger.warning(f"Erro ao criar Imovel: {e}")
            return mapped

    return mapped


def from_loft_payload(raw: Any) -> list[dict]:
    """Converte o output do scraper (array de listings) para lista de Imovel.

    Args:
        raw: Pode ser:
            - Lista de dicts (listings.json)
            - Dict com chave "listings" (output raw do Node script)
            - String contendo JSON

    Returns:
        Lista de Imovel (ou dicts) no schema unificado.
    """
    # Aceitar string JSON
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Payload inválido: não é JSON válido")
            return []

    # Aceitar dict com "listings" (formato do raw API response)
    if isinstance(raw, dict):
        # Try nested payloads: pageProps → listings, data → listings, or direct listings
        if "pageProps" in raw and isinstance(raw["pageProps"], dict):
            raw = raw["pageProps"].get("listings", raw)
        elif "data" in raw and isinstance(raw["data"], dict):
            raw = raw["data"].get("listings", raw)
        else:
            raw = raw.get("listings", raw)

    if not isinstance(raw, list):
        logger.warning(f"Payload inesperado: esperava list, recebeu {type(raw).__name__}")
        return []

    imoveis = []
    for item in raw:
        imovel = from_loft_listing(item)
        if imovel:
            imoveis.append(imovel)

    logger.info(f"Parsed {len(imoveis)} listings from Loft payload")
    return imoveis


# ── Python wrapper to call the Node.js scraper ───────────────────────────────

SCRAPER_DIR = Path(__file__).resolve().parent.parent.parent / "scrapers" / "loft"
SCRAPER_SCRIPT = SCRAPER_DIR / "scrape-loft.js"


def run_scraper(
    url: str = "https://loft.com.br/venda/apartamentos/sp/sao-paulo/",
    pages: int = 1,
    timeout: int = 120,
) -> list[dict]:
    """Executa o scraper Node.js via Playwright e retorna listings parseadas.

    Args:
        url: URL base da página de busca.
        pages: Número de páginas a extrair.
        timeout: Timeout em segundos para o subprocesso.

    Returns:
        Lista de Imovel (ou dicts) no schema unificado.

    Raises:
        RuntimeError: Se o scraper falhar ou o script não existir.
    """
    if not SCRAPER_SCRIPT.exists():
        raise RuntimeError(
            f"Scraper não encontrado: {SCRAPER_SCRIPT}\n"
            f"Execute 'cd {SCRAPER_DIR} && npm install' primeiro."
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
        raise RuntimeError(
            f"Scraper excedeu o tempo limite de {timeout}s"
        )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Erro desconhecido"
        raise RuntimeError(f"Scraper falhou (exit={result.returncode}): {error_msg[:500]}")

    # Extrair o JSON do output — procura entre "── JSON ──" e o final
    stdout = result.stdout.strip()

    # Estratégia 1: Ler o arquivo listings.json do diretório de output
    # O Node script imprime "Output:          /path/to/output/listings.json"
    import re
    output_match = re.search(r'Output:\s+(.+?/listings\.json)', stdout)
    if output_match:
        output_path = output_match.group(1).strip()
        logger.info(f"Lendo arquivo de output: {output_path}")
        with open(output_path) as f:
            json_str = f.read()
    else:
        # Estratégia 2: extrair do stdout (fallback para output pequeno)
        json_start = stdout.rfind("\n── JSON ──\n")
        if json_start >= 0:
            json_str = stdout[json_start + len("\n── JSON ──\n"):]
        else:
            json_str = stdout

        json_str = json_str.strip()

    try:
        raw_listings = json.loads(json_str)
    except json.JSONDecodeError:
        logger.error(f"Não foi possível parsear o JSON do scraper ({len(json_str)} chars).")
        if output_match:
            logger.error(f"Arquivo pode estar corrompido: {output_path}")
        else:
            logger.error(f"Primeiros 300 chars: {json_str[:300]}")
        raise RuntimeError("Scraper retornou JSON inválido")

    return from_loft_payload(raw_listings)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    """CLI para testar o parser diretamente."""
    import argparse

    parser = argparse.ArgumentParser(description="Loft Parser — teste e execução")
    sub = parser.add_subparsers(dest="command")

    # run: executa o scraper
    run_parser = sub.add_parser("run", help="Executa o scraper Node.js e parseia")
    run_parser.add_argument("--url", default="https://loft.com.br/venda/apartamentos/sp/sao-paulo/")
    run_parser.add_argument("--pages", type=int, default=1)
    run_parser.add_argument("--output", help="Salvar JSON em arquivo")

    # parse: parseia um arquivo JSON já extraído
    parse_parser = sub.add_parser("parse", help="Parseia um arquivo JSON do scraper")
    parse_parser.add_argument("input_file", help="Caminho do listings.json")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "run":
        imoveis = run_scraper(args.url, args.pages)
        print(f"\nExtraídos {len(imoveis)} imóveis via scraper")
        if imoveis:
            print(f"  Preços: R$ {min(i['preco_venda'] for i in imoveis if i.get('preco_venda')):.0f} ~ "
                  f"R$ {max(i['preco_venda'] for i in imoveis if i.get('preco_venda')):.0f}")
            reducoes = [i for i in imoveis if i.get('tem_reducao')]
            if reducoes:
                print(f"  Reduções: {len(reducoes)} imóveis")
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(imoveis, f, indent=2, ensure_ascii=False)
            print(f"  Salvo em: {args.output}")

    elif args.command == "parse":
        with open(args.input_file) as f:
            data = json.load(f)
        imoveis = from_loft_payload(data)
        print(f"Parseados {len(imoveis)} imóveis de {args.input_file}")
        if imoveis:
            print(f"  Amostra: {imoveis[0]['titulo']} — "
                  f"R$ {imoveis[0].get('preco_venda', 'N/A')}")

    else:
        parser.print_help()


# ── SSR Extraction (no browser needed) ──────────────────────────────────────


def extract_ssr(
    url: str = "https://loft.com.br/venda/apartamentos/sp/sao-paulo/",
    timeout: int = 30,
) -> list[dict]:
    """Extract listings from a Loft SSR page via HTTP (no browser required).

    Fetches the Loft search page with a plain HTTP request and extracts
    listing data from the embedded __NEXT_DATA__ JSON. This is faster and
    more lightweight than the Playwright-based Node.js scraper.

    Args:
        url: Full URL of a Loft search listing page.
        timeout: HTTP request timeout in seconds (default: 30).

    Returns:
        List of dicts in the unified Imovel schema.

    Raises:
        RuntimeError: If the SSR extractor module is not found.
        requests.RequestException: If the HTTP request itself fails.
    """
    try:
        from skills.loft.loft_ssr import extract_from_ssr as _do_extract
    except ImportError:
        raise RuntimeError(
            "SSR extractor module not found. "
            "Ensure skills/loft/loft_ssr.py exists and the repo root "
            "is in sys.path."
        )

    return _do_extract(url, timeout=timeout)


if __name__ == "__main__":
    main()
