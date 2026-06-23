"""
qa_loft_dedup — Dedup engine for QuintoAndar ↔ Loft cross-portal matching.

Identifica imóveis duplicados anunciados em ambos os portais usando
matching fuzzy em 4 dimensões:

  1. RUA (+ número) — 30% do score
  2. BAIRRO — 25%
  3. ÁREA (±10%) — 25%
  4. PREÇO (±5%) — 20%

O score combinado mínimo para considerar duplicata é 0.60.

Uso:
    from qa_loft_dedup import dedup_cross_portal, match_cross_portal

    imoveis = [Imovel(...), Imovel(...)]  # misto QuintoAndar + Loft
    deduped = dedup_cross_portal(imoveis)
    # cada item em deduped tem um campo 'duplicate_ids' com os IDs
    # dos imóveis mesclados

    # Ou apenas encontrar matches sem dedup:
    matches = match_cross_portal(imoveis)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Tolerâncias do matching
AREA_TOLERANCE = 0.10        # ±10%
PRICE_TOLERANCE = 0.05       # ±5%
MIN_MATCH_SCORE = 0.60       # score mínimo para considerar duplicata

# Pesos de cada dimensão (total = 1.0)
WEIGHT_RUA = 0.30
WEIGHT_BAIRRO = 0.25
WEIGHT_AREA = 0.25
WEIGHT_PRECO = 0.20

# Fontes alvo
FONTES = frozenset({"quintoandar", "loft"})


# ── Helpers de normalização ──────────────────────────────────────────────


_STREET_PREFIXES = re.compile(
    r"^(rua|av|avenida|travessa|praça|alameda|rodovia|estrada|"
    r"dr|doutor|prof|professor|padre|são|santo|santa|"
    r"eng|engenheiro|major|capitão|general|"
    r"dom|dona|vila)\s+",
    re.IGNORECASE,
)


def _normalize_street(street: str) -> str:
    """Normaliza nome de rua: remove prefixos comuns, lowercase, tokens.

    Extrai apenas o nome da rua (antes de vírgula, hífen ou número),
    depois remove prefixos como Rua, Avenida, etc.

    'Rua Augusta, 1500' → 'augusta'
    'Avenida Paulista, 1000 - Bela Vista' → 'paulista'
    'Av. São João' → 'são joão'
    'Rua 15 de Novembro' → '15 de novembro'
    """
    if not street:
        return ""
    s = street.strip()
    # Extrai só o nome da rua (antes da primeira vírgula ou hífen)
    for sep in (",", "-", "–", "nº", "n°", "n."):
        if sep in s:
            s = s.split(sep)[0]
            break
    s = s.strip().lower()
    # Remove pontuação ANTES de remover prefixo (senão "Av." não vira "av")
    s = re.sub(r"[^\w\s]", " ", s)
    s = _STREET_PREFIXES.sub("", s).strip()
    # Remove números solitários no final (ex.: 'augusta 1500' → 'augusta')
    s = re.sub(r"\s+\d+\s*$", "", s).strip()
    return s


def _extract_number(endereco: str) -> str:
    """Extrai número do endereço: 'Rua Augusta, 1500 - Consolação' → '1500'.

    Retorna string vazia se não encontrar.
    """
    if not endereco:
        return ""
    # Tenta após vírgula: "Rua X, 123" ou "Rua X, 123 - Bairro"
    m = re.search(r",\s*(\d+)\s*(?:-|$|\s)", endereco)
    if m:
        return m.group(1)
    # Tenta "nº 123" ou "n. 123"
    m = re.search(r"(?:n[º°]?|n[úu]mero)\s*\.?\s*(\d+)", endereco, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _token_set_ratio(a: str, b: str) -> float:
    """Similaridade baseada em interseção de tokens (palavras)."""
    if not a or not b:
        return 0.0
    tokens_a = set(re.findall(r"\w+", a.lower()))
    tokens_b = set(re.findall(r"\w+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _is_same_fonte(a: dict, b: dict) -> bool:
    """True se ambos vieram da mesma fonte."""
    fa = str(a.get("fonte", "")).strip().lower()
    fb = str(b.get("fonte", "")).strip().lower()
    return fa == fb and fa in FONTES


def _str_field(d: dict, *keys: str, default: str = "") -> str:
    """Pega primeiro campo não-vazio de uma lista de chaves."""
    for k in keys:
        val = d.get(k)
        if val and isinstance(val, str):
            return val
    return default


def _float_field(d: dict, *keys: str) -> Optional[float]:
    """Pega primeiro campo numérico não-None de uma lista de chaves."""
    for k in keys:
        val = d.get(k)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


# ── Scorers individuais ──────────────────────────────────────────────────


def _score_address(a: dict, b: dict) -> float:
    """Score de endereço: rua normalizada (70%) + número (30%)."""
    # Rua: tenta endereco, depois street, depois fallback vazio
    street_a_raw = _str_field(a, "endereco", "street", "rua")
    street_b_raw = _str_field(b, "endereco", "street", "rua")
    street_a = _normalize_street(street_a_raw)
    street_b = _normalize_street(street_b_raw)

    if not street_a or not street_b:
        # Fallback: tenta bairro se street não disponível (imóvel sem endereço completo)
        return 0.0

    ratio = _token_set_ratio(street_a, street_b)

    # Se a rua não bater nada, o endereço falha
    if ratio < 0.50:
        return 0.0

    # Número
    num_a = _extract_number(street_a_raw)
    num_b = _extract_number(street_b_raw)
    num_ok = num_a and num_b and num_a == num_b

    # Score final: 70% street match + 30% number match
    score = 0.70 * ratio + (0.30 if num_ok else 0.0)
    return score


def _score_neighborhood(a: dict, b: dict) -> float:
    """Score de bairro: token-set ratio."""
    bairro_a = _str_field(a, "bairro", "neighbourhood", "neighborhood")
    bairro_b = _str_field(b, "bairro", "neighbourhood", "neighborhood")
    return _token_set_ratio(bairro_a, bairro_b)


def _score_area(a: dict, b: dict) -> float:
    """Score de área: 1.0 se ±10%, 0.0 se fora ou sem dado."""
    area_a = _float_field(a, "area", "area_m2", "area_util", "usableArea")
    area_b = _float_field(b, "area", "area_m2", "area_util", "usableArea")
    if area_a is None or area_b is None or area_a <= 0 or area_b <= 0:
        return 0.0
    diff = abs(area_a - area_b) / max(area_a, area_b)
    if diff <= AREA_TOLERANCE:
        return 1.0
    return 0.0


def _score_price(a: dict, b: dict) -> float:
    """Score de preço: 1.0 se ±5%, 0.0 se fora ou sem dado."""
    price_a = _float_field(a, "preco_venda", "preco_aluguel", "price", "salePrice")
    price_b = _float_field(b, "preco_venda", "preco_aluguel", "price", "salePrice")
    if price_a is None or price_b is None or price_a <= 0 or price_b <= 0:
        return 0.0
    diff = abs(price_a - price_b) / max(price_a, price_b)
    if diff <= PRICE_TOLERANCE:
        return 1.0
    return 0.0


# ── Match Result ──────────────────────────────────────────────────────────


@dataclass
class CrossPortalMatch:
    """Resultado de match entre um imóvel QuintoAndar e um Loft.

    Attributes:
        idx_a: Índice no array original.
        idx_b: Índice no array original.
        score: Score combinado (0.0–1.0).
        details: Scores parciais de cada dimensão.
    """
    idx_a: int
    idx_b: int
    score: float
    details: dict[str, float] = field(default_factory=dict)


# ── Engine principal ─────────────────────────────────────────────────────


def match_cross_portal(
    listings: list[dict[str, Any]],
    min_score: float = MIN_MATCH_SCORE,
) -> list[CrossPortalMatch]:
    """Encontra duplicatas entre QuintoAndar e Loft na mesma lista.

    Compara apenas pares de fontes diferentes (QA ↔ Loft).
    Ignora pares da mesma fonte.

    Args:
        listings: Lista de dicts de imóveis (schema Imovel).
        min_score: Score mínimo para considerar match.

    Returns:
        Lista de CrossPortalMatch, ordenada por score decrescente.
    """
    matches: list[CrossPortalMatch] = []
    seen_indices: set[int] = set()

    for i, a in enumerate(listings):
        fonte_a = str(a.get("fonte", "")).strip().lower()
        if fonte_a not in FONTES:
            continue

        for j, b in enumerate(listings):
            if j <= i:
                continue  # evita comparar consigo mesmo e pares duplicados

            fonte_b = str(b.get("fonte", "")).strip().lower()
            if fonte_b not in FONTES:
                continue
            if fonte_a == fonte_b:
                continue  # mesma fonte — sem cross-portal

            # Scores parciais
            addr_score = _score_address(a, b)
            neigh_score = _score_neighborhood(a, b)
            area_score = _score_area(a, b)
            price_score = _score_price(a, b)

            # Score combinado
            combined = (
                WEIGHT_RUA * addr_score
                + WEIGHT_BAIRRO * neigh_score
                + WEIGHT_AREA * area_score
                + WEIGHT_PRECO * price_score
            )

            if combined >= min_score:
                matches.append(CrossPortalMatch(
                    idx_a=i,
                    idx_b=j,
                    score=round(combined, 4),
                    details={
                        "address": round(addr_score, 4),
                        "neighborhood": round(neigh_score, 4),
                        "area": round(area_score, 4),
                        "price": round(price_score, 4),
                    },
                ))

    # Ordena por score decrescente
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def dedup_cross_portal(
    listings: list[dict[str, Any]],
    min_score: float = MIN_MATCH_SCORE,
) -> list[dict[str, Any]]:
    """Dedup lista de imóveis entre QuintoAndar e Loft.

    Para cada par duplicado, mescla em um único item com campo
    'duplicate_ids' contendo os IDs de todos os imóveis agrupados.

    Args:
        listings: Lista de dicts de imóveis (schema Imovel).
        min_score: Score mínimo para considerar match.

    Returns:
        Lista deduplicada, cada item com 'duplicate_ids'.
    """
    matches = match_cross_portal(listings, min_score=min_score)

    # Constrói componentes conectados (grafos de duplicatas)
    n = len(listings)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for m in matches:
        union(m.idx_a, m.idx_b)

    # Agrupa por raiz
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    # Constrói resultado deduplicado
    result: list[dict[str, Any]] = []
    for indices in groups.values():
        # Pega o primeiro item como canônico
        canonical = dict(listings[indices[0]])
        # Coleta todos os IDs duplicados (inclusive o próprio)
        all_ids = []
        for idx in indices:
            item = listings[idx]
            item_id = str(item.get("id", item.get("list_id", "")))
            if item_id:
                all_ids.append(item_id)
        canonical["duplicate_ids"] = all_ids
        # Atualiza outros campos se houver mais dados (ex.: preencher
        # campos faltantes com dados de outra fonte)
        for idx in indices[1:]:
            item = listings[idx]
            for field in ("preco_venda", "preco_aluguel", "area",
                          "quartos", "banheiros", "vagas", "endereco",
                          "bairro", "descricao", "titulo"):
                if not canonical.get(field) and item.get(field):
                    canonical[field] = item[field]
        result.append(canonical)

    return result


# ── Utilitários ──────────────────────────────────────────────────────────


def summarize_matches(matches: list[CrossPortalMatch]) -> dict[str, Any]:
    """Gera resumo estatístico dos matches."""
    if not matches:
        return {"total": 0, "avg_score": 0.0, "by_dimension": {}}

    dims = ["address", "neighborhood", "area", "price"]
    by_dim: dict[str, list[float]] = {d: [] for d in dims}
    for m in matches:
        for d in dims:
            by_dim[d].append(m.details.get(d, 0.0))

    return {
        "total": len(matches),
        "avg_score": round(sum(m.score for m in matches) / len(matches), 4),
        "by_dimension": {
            dim: {
                "avg": round(sum(v) / len(v), 4) if v else 0.0,
                "non_zero": sum(1 for x in v if x > 0),
            }
            for dim, v in by_dim.items()
        },
    }
