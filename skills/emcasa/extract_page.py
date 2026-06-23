#!/usr/bin/env python3
"""
extract_page — Extrai o JSON do Algolia embutido nas páginas HTML do EmCasa.

A EmCasa (Garagem AI) renderiza os dados de busca no lado servidor via Next.js
e embute o resultado do Algolia em:

    window[Symbol.for("InstantSearchInitialResults")] = { ... }

Esta função baixa o HTML da página de busca, extrai esse JSON usando regex
+ brace-matching, e retorna o dict parseado.

Uso:
    from extract_page import extract_page

    data = extract_page("sp", 0)      # página 0 de São Paulo
    data = extract_page("rj", 2)      # página 2 do Rio de Janeiro

    if data:
        hits = data["properties"]["results"][0]["hits"]
        print(f"{len(hits)} imóveis")
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Optional

logger = logging.getLogger("extract_page")

# ── Constantes ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.emcasa.com/comprar/{city}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)

# Mapa city code → nome da cidade (para validação)
VALID_CITIES = {"sp": "São Paulo", "rj": "Rio de Janeiro"}


# ── Extração principal ─────────────────────────────────────────────────────────

def extract_page(city: str, page: int = 0) -> Optional[dict[str, Any]]:
    """
    Baixa a página de busca do EmCasa e extrai o JSON do Algolia.

    Args:
        city: Código da cidade ('sp' ou 'rj').
        page: Número da página (0-indexed, padrão 0).

    Returns:
        Dict com a estrutura completa do Algolia contendo:
            properties.results[0].hits  — lista de imóveis
            properties.results[0].facets — facets com contagens
            properties.results[0].nbHits — total de resultados
        Ou None em caso de erro.
    """
    city = city.lower().strip()
    if city not in VALID_CITIES:
        logger.error(f"Cidade inválida: '{city}'. Use: {', '.join(VALID_CITIES)}")
        return None

    url = f"{BASE_URL.format(city=city)}?page={page}"

    # ── 1. Baixar o HTML ──────────────────────────────────────────────────
    html = _fetch_html(url)
    if html is None:
        return None

    # ── 2. Extrair o JSON do Algolia ──────────────────────────────────────
    raw_json = _extract_algolia_json(html)
    if raw_json is None:
        return None

    # ── 3. Parsear JSON ───────────────────────────────────────────────────
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao fazer parse do JSON extraído: {e}")
        return None

    return data


def extract_page_results(city: str, page: int = 0) -> Optional[list[dict[str, Any]]]:
    """
    Atalho que retorna apenas a lista de hits (imóveis) da página.

    Args:
        city: Código da cidade ('sp' ou 'rj').
        page: Número da página (0-indexed).

    Returns:
        Lista de dicts de imóveis, ou None em caso de erro.
    """
    data = extract_page(city, page)
    if data is None:
        return None
    results = data.get("properties", {}).get("results", [])
    if not results:
        logger.warning(f"Nenhum 'results' encontrado na resposta de {city} p.{page}")
        return []
    return results[0].get("hits", [])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fetch_html(url: str) -> Optional[str]:
    """Baixa o HTML da URL usando curl (subprocess)."""
    try:
        result = subprocess.run(
            [
                "curl", "-s", url,
                "-H", f"User-Agent: {USER_AGENT}",
                "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "-H", "Accept-Language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"curl falhou (exit {result.returncode}): {result.stderr.strip()}")
            return None
        html = result.stdout
        if not html:
            logger.error("HTML vazio retornado pelo servidor")
            return None
        return html
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout ao baixar {url}")
        return None
    except OSError as e:
        logger.error(f"Erro ao executar curl: {e}")
        return None


def _extract_algolia_json(html: str) -> Optional[str]:
    """
    Extrai o JSON do Algolia a partir do HTML.

    Procura pelo padrão:
        window[Symbol.for("InstantSearchInitialResults")] = {...}

    e usa brace-matching para isolar o JSON, removendo
    caracteres de controle inválidos (literais \\n, \\r dentro de strings).
    """
    marker = 'window[Symbol.for("InstantSearchInitialResults")]'
    idx = html.find(marker)
    if idx < 0:
        logger.error("Marcador InstantSearchInitialResults não encontrado no HTML")
        return None

    # Encontra o início do JSON (primeiro { após o marcador)
    try:
        json_start = html.index("{", idx)
    except ValueError:
        logger.error("'{' não encontrado após marcador InstantSearchInitialResults")
        return None

    # Pega o bloco restante a partir do {
    raw_block = html[json_start:]

    # Remove caracteres de controle inválidos para JSON
    # Mantém apenas tabs, newlines, carriage returns (são válidos fora de strings)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", raw_block)

    # Brace-matching para encontrar o } de fechamento
    depth = 0
    in_string = False
    escape = False
    json_end = 0

    for i, ch in enumerate(cleaned):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not in_string:
            in_string = True
            continue
        if ch == '"' and in_string:
            in_string = False
            continue
        if not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break

    if json_end == 0:
        logger.error("Não foi possível encontrar o } de fechamento do JSON")
        return None

    return cleaned[:json_end]


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    """Ponto de entrada para linha de comando."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Extrai dados do Algolia das páginas do EmCasa."
    )
    parser.add_argument(
        "cidade",
        choices=list(VALID_CITIES.keys()),
        help="Código da cidade (sp, rj)",
    )
    parser.add_argument(
        "-p", "--pagina",
        type=int,
        default=0,
        help="Número da página (0-indexed, padrão: 0)",
    )
    parser.add_argument(
        "--hits",
        action="store_true",
        help="Mostra apenas a contagem e primeiros hits",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Salva o JSON bruto em um arquivo",
    )

    args = parser.parse_args()

    data = extract_page(args.cidade, args.pagina)

    if data is None:
        print("Falha ao extrair dados.", file=sys.stderr)
        sys.exit(1)

    results = data.get("properties", {}).get("results", [{}])[0]
    hits = results.get("hits", [])
    nb_hits = results.get("nbHits", 0)
    nb_pages = results.get("nbPages", 0)

    if args.hits:
        print(f"Cidade: {VALID_CITIES[args.cidade]}")
        print(f"Página: {args.pagina} / {nb_pages}")
        print(f"Total de imóveis: {nb_hits}")
        print(f"Imóveis nesta página: {len(hits)}")
        print()
        for i, h in enumerate(hits[:5], 1):
            title = h.get("title", "Sem título")
            price = h.get("price", "N/A")
            bairro = h.get("location_neighborhood", "")
            area = h.get("property_area_total", "N/A")
            print(f"  {i}. {title} — R$ {price} — {bairro} — {area}m²")
        if len(hits) > 5:
            print(f"  ... e mais {len(hits) - 5} imóveis")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])

    if args.raw:
        fname = f"emcasa_{args.cidade}_p{args.pagina:04d}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"\nJSON salvo em: {fname}")


if __name__ == "__main__":
    main()
