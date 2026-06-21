"""
detect_duplicates — Detect duplicate listings across runs and sources.

Matching strategy (tiered, highest-first):

  TIER 1 — EXACT_URL (score 1.0)
    URL normalizada idêntica. Comparação após strip de protocolo, www,
    trailing slash e lower(). Definitivo — se bater, não prossegue.

  TIER 2 — EXACT_ID (score 1.0)
    Mesmo ID na mesma fonte (ex.: list_id da OLX, id do QuintoAndar).
    Só válido quando `fonte` é idêntica. Definitivo.

  TIER 3 — STRUCTURAL (score até 0.85)
    Combinação de bairro + cidade + UF + área + quartos + banheiros +
    vagas + preço. Ponderado por peso. Preço tolera ±5%, área tolera ±5m².
    Score ≥ 0.80 ativa este tier.

  TIER 4 — FUZZY_TITLE (score até 0.70)
    Token-set ratio no título. Quer dizer: "Apto 2q Consolação" e
    "Apartamento 2 quartos Consolação" têm alta similaridade.
    Threshold: 0.80.

  TIER 5 — FUZZY_ADDRESS (score até 0.70)
    Token-set ratio no endereço (ou bairro como fallback).
    Threshold: 0.75.

  TIER 6 — FUZZY_DESCRIPTION (score até 0.60)
    SequenceMatcher char-level na descrição (primeiros 500 chars).
    Só ativado se descrições tiverem > 20 chars. Threshold: 0.65.
    Fallback para quando os tiers anteriores não pegarem.

Cada par (i, j) recebe o MATCH DE MAIOR SCORE entre todos os tiers.
EXACT_URL e EXACT_ID interrompem a avaliação daquele par (são definitivos).

Uso:
    from detect_duplicates import find_duplicates, dedup_list

    current = [imovel.to_dict() for imovel in imoveis_atuais]
    reference = [imovel.to_dict() for imovel in imoveis_anteriores]

    matches = find_duplicates(current, reference)
    novos_unicos, matches = dedup_list(current, reference)
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Constants ──────────────────────────────────────────────────────────────────

# Score contributions per tier
SCORE_EXACT_URL = 1.0
SCORE_EXACT_ID = 1.0
SCORE_STRUCTURAL = 0.85
SCORE_FUZZY_TITLE = 0.80
SCORE_FUZZY_ADDRESS = 0.70
SCORE_FUZZY_DESCRIPTION = 0.60

# Thresholds for fuzzy matching tiers
FUZZY_TITLE_THRESHOLD = 0.40       # token-set ratio
FUZZY_ADDRESS_THRESHOLD = 0.60     # token-set ratio (full address only)
FUZZY_DESCRIPTION_THRESHOLD = 0.65

# Structural match tolerances
STRUCTURAL_MIN_SCORE = 0.80       # minimum structural similarity to activate tier
STRUCTURAL_MIN_WEIGHT = 0.40      # minimum total weight for structural to be valid
PRICE_TOLERANCE = 0.05            # ±5%
AREA_TOLERANCE = 5                # ±5 m²

# Default minimum score to return a match
DEFAULT_MIN_SCORE = 0.60


# ── Output types ──────────────────────────────────────────────────────────────


@dataclass
class MatchResult:
    """
    Resultado de uma comparação entre dois imóveis.

    Attributes:
        idx_a: Índice do imóvel na lista "current".
        idx_b: Índice do imóvel na lista "reference".
        imovel_a_id: ID do imóvel atual (para rastreabilidade).
        imovel_b_id: ID do imóvel de referência.
        score: Similaridade final (0.0–1.0), arredondada para 4 casas.
        match_type: Nome do tier que produziu o match.
        details: Dict com informações adicionais (scores parciais).
    """
    idx_a: int
    idx_b: int
    imovel_a_id: str
    imovel_b_id: str
    score: float
    match_type: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.score = round(self.score, 4)


# ── Helpers ───────────────────────────────────────────────────────────────────


def normalize_url(url: str) -> str:
    """
    Normaliza URL para comparação.

    - Remove protocolo (http://, https://)
    - Remove www.
    - Remove trailing slash
    - Lowercase
    - Remove fragmentos (#...)
    """
    if not url:
        return ""
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.rstrip("/")
    url = re.sub(r"#.*$", "", url)
    return url


def token_set_ratio(a: str, b: str) -> float:
    """
    Similaridade baseada em interseção de tokens (palavras).

    Extrai tokens alfanuméricos de ambas as strings, calcula
    |intersecção| / |união|. Ignora maiúsculas/minúsculas.

    Args:
        a, b: Strings a comparar.

    Returns:
        Float entre 0.0 e 1.0.
    """
    if not a or not b:
        return 0.0

    tokens_a = set(re.findall(r"\w+", a.lower()))
    tokens_b = set(re.findall(r"\w+", b.lower()))

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def seq_match_ratio(a: str, b: str) -> float:
    """
    Similaridade char-level via SequenceMatcher.

    Útil para strings longas com pequenas diferenças (descrições).

    Args:
        a, b: Strings a comparar.

    Returns:
        Float entre 0.0 e 1.0.
    """
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _structural_similarity(
    a: dict[str, Any],
    b: dict[str, Any],
) -> float:
    """
    Calcula similaridade estrutural entre dois imóveis.

    Pesos (total 1.0):
      cidade=0.25  bairro=0.20  uf=0.10
      area=0.15    quartos=0.10 banheiros=0.05  vagas=0.05  preco=0.10

    Args:
        a, b: Dicts de imóvel (schema Imovel ou parse_ad).

    Returns:
        Float entre 0.0 e 1.0.
    """
    weights = {
        "cidade": 0.25,
        "bairro": 0.20,
        "uf": 0.10,
        "area": 0.15,
        "quartos": 0.10,
        "banheiros": 0.05,
        "vagas": 0.05,
        "preco_venda": 0.10,
    }

    score = 0.0
    total_weight = 0.0

    for field, weight in weights.items():
        if field == "preco_venda":
            pa = a.get("preco_venda") or a.get("price")
            pb = b.get("preco_venda") or b.get("price")
            if pa is not None and pb is not None and pa > 0 and pb > 0:
                ratio = min(abs(pa), abs(pb)) / max(abs(pa), abs(pb))
                if ratio >= 1.0 - PRICE_TOLERANCE:
                    score += weight * ratio
                total_weight += weight
            continue

        if field == "area":
            va = a.get("area") or a.get("area_m2")
            vb = b.get("area") or b.get("area_m2")
            if va is not None and vb is not None and va > 0 and vb > 0:
                diff = abs(float(va) - float(vb))
                if diff <= AREA_TOLERANCE:
                    score += weight
                total_weight += weight
            continue

        if field in ("quartos", "banheiros", "vagas"):
            va = a.get(field) or a.get(_olx_field(field))
            vb = b.get(field) or b.get(_olx_field(field))
            if va is not None and vb is not None:
                if int(va) == int(vb):
                    score += weight
                total_weight += weight
            continue

        # String fields: bairro, cidade, uf
        va = (a.get(field) or "").strip().lower()
        vb = (b.get(field) or "").strip().lower()
        if va and vb:
            if va == vb:
                score += weight
            elif token_set_ratio(va, vb) >= 0.80:
                score += weight * 0.8
            total_weight += weight

    if total_weight == 0:
        return 0.0
    if total_weight < STRUCTURAL_MIN_WEIGHT:
        return 0.0
    return score / total_weight


def _olx_field(field: str) -> str:
    """Mapeia campo do schema Imovel para o campo OLX parse_ad()."""
    mapping = {
        "quartos": "rooms",
        "banheiros": "bathrooms",
        "vagas": "garage_spaces",
        "area": "area_m2",
        "bairro": "neighbourhood",
        "cidade": "municipality",
        "preco_venda": "price",
    }
    return mapping.get(field, field)


# ── Core dedup engine ─────────────────────────────────────────────────────────


def find_duplicates(
    current: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[MatchResult]:
    """
    Encontra duplicatas entre duas listas de imóveis.

    Aplica matching em 6 tiers (EXACT_URL → EXACT_ID → STRUCTURAL →
    FUZZY_TITLE → FUZZY_ADDRESS → FUZZY_DESCRIPTION). Cada par (i, j)
    recebe o match de maior score. EXACT_URL e EXACT_ID interrompem
    a avaliação (são definitivos).

    Args:
        current: Lista atual de imóveis (dicts no schema Imovel
                 ou formato parse_ad do OLX).
        reference: Lista de referência (execuções anteriores).
        min_score: Score mínimo (0.0–1.0) para incluir no resultado.
                   Padrão: 0.60.

    Returns:
        Lista de MatchResult, ordenada por score decrescente.
        Cada MatchResult tem o par (idx_a, idx_b) e o tier que venceu.
    """
    matches: list[MatchResult] = []
    seen_pairs: set[tuple[int, int]] = set()

    for i, item in enumerate(current):
        item_url = normalize_url(item.get("url", ""))
        item_id = str(item.get("id", item.get("list_id", "")))
        item_fonte = item.get("fonte", "")

        best: Optional[MatchResult] = None

        for j, ref_item in enumerate(reference):
            pair = (i, j)
            if pair in seen_pairs:
                continue

            ref_url = normalize_url(ref_item.get("url", ""))
            ref_id = str(ref_item.get("id", ref_item.get("list_id", "")))
            ref_fonte = ref_item.get("fonte", "")

            # ── Tier 1: EXACT_URL ─────────────────────────────────────
            if item_url and ref_url and item_url == ref_url:
                best = MatchResult(
                    idx_a=i, idx_b=j,
                    imovel_a_id=item_id or item_url,
                    imovel_b_id=ref_id or ref_url,
                    score=SCORE_EXACT_URL,
                    match_type="EXACT_URL",
                    details={"normalized_url": item_url},
                )
                break  # URL exacta é definitiva — sai do loop ref

            # ── Tier 2: EXACT_ID (mesma fonte) ────────────────────────
            if (item_id and ref_id and item_id == ref_id
                    and item_id != ""
                    and item_fonte and ref_fonte
                    and item_fonte == ref_fonte
                    and item_fonte.strip()
                    and ref_fonte.strip()):
                best = MatchResult(
                    idx_a=i, idx_b=j,
                    imovel_a_id=item_id,
                    imovel_b_id=ref_id,
                    score=SCORE_EXACT_ID,
                    match_type="EXACT_ID",
                    details={"fonte": item_fonte, "id": item_id},
                )
                break  # ID exacto na mesma fonte é definitivo

            # ── Tier 3: STRUCTURAL ────────────────────────────────────
            struct_score = _structural_similarity(item, ref_item)
            if struct_score >= STRUCTURAL_MIN_SCORE:
                result = MatchResult(
                    idx_a=i, idx_b=j,
                    imovel_a_id=item_id,
                    imovel_b_id=ref_id,
                    score=SCORE_STRUCTURAL * struct_score,
                    match_type="STRUCTURAL",
                    details={"structural_score": round(struct_score, 4)},
                )
                if best is None or result.score > best.score:
                    best = result

            # ── Tier 4: FUZZY_TITLE ────────────────────────────────────
            title_a = item.get("titulo", item.get("title", ""))
            title_b = ref_item.get("titulo", ref_item.get("title", ""))
            if title_a and title_b:
                title_score = token_set_ratio(title_a, title_b)
                if title_score >= FUZZY_TITLE_THRESHOLD:
                    result = MatchResult(
                        idx_a=i, idx_b=j,
                        imovel_a_id=item_id,
                        imovel_b_id=ref_id,
                        score=SCORE_FUZZY_TITLE * title_score,
                        match_type="FUZZY_TITLE",
                        details={"token_set_ratio": round(title_score, 4)},
                    )
                    if best is None or result.score > best.score:
                        best = result

            # ── Tier 5: FUZZY_ADDRESS ─────────────────────────────────
            addr_a = item.get("endereco", "")
            addr_b = ref_item.get("endereco", "")
            if addr_a and addr_b:
                addr_score = token_set_ratio(addr_a, addr_b)
                if addr_score >= FUZZY_ADDRESS_THRESHOLD:
                    result = MatchResult(
                        idx_a=i, idx_b=j,
                        imovel_a_id=item_id,
                        imovel_b_id=ref_id,
                        score=SCORE_FUZZY_ADDRESS * addr_score,
                        match_type="FUZZY_ADDRESS",
                        details={"token_set_ratio": round(addr_score, 4)},
                    )
                    if best is None or result.score > best.score:
                        best = result

            # ── Tier 6: FUZZY_DESCRIPTION ─────────────────────────────
            if best is None or best.score < SCORE_FUZZY_DESCRIPTION:
                desc_a = item.get("descricao", "")
                desc_b = ref_item.get("descricao", "")
                if (desc_a and desc_b
                        and len(desc_a) > 20 and len(desc_b) > 20):
                    desc_score = seq_match_ratio(desc_a[:500], desc_b[:500])
                    if desc_score >= FUZZY_DESCRIPTION_THRESHOLD:
                        result = MatchResult(
                            idx_a=i, idx_b=j,
                            imovel_a_id=item_id,
                            imovel_b_id=ref_id,
                            score=SCORE_FUZZY_DESCRIPTION * desc_score,
                            match_type="FUZZY_DESCRIPTION",
                            details={"seq_match": round(desc_score, 4)},
                        )
                        if best is None or result.score > best.score:
                            best = result

        if best and best.score >= min_score:
            seen_pairs.add((i, best.idx_b))
            matches.append(best)

    # Ordena por score decrescente
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


# ── Batch processing ──────────────────────────────────────────────────────────


def dedup_list(
    current: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> tuple[list[dict[str, Any]], list[MatchResult]]:
    """
    Filtra itens duplicados de uma lista de imóveis.

    Args:
        current: Lista atual de imóveis.
        reference: Lista de referência (execuções anteriores).
        min_score: Score mínimo para considerar duplicata.

    Returns:
        Tuple (novos_unicos, matches_encontrados).
          - novos_unicos: sublista de `current` sem os duplicados.
          - matches: lista de MatchResult com os pares encontrados.
    """
    matches = find_duplicates(current, reference, min_score=min_score)
    duplicate_indices = {m.idx_a for m in matches}

    novos = [
        item for i, item in enumerate(current)
        if i not in duplicate_indices
    ]

    return novos, matches


def fingerprint(listings: list[dict[str, Any]]) -> str:
    """
    Hash rápido dos IDs para detectar mudanças sem re-analisar.

    Args:
        listings: Lista de imóveis (dicts).

    Returns:
        SHA-256 hex digest (primeiros 16 chars) dos IDs ordenados.
    """
    ids = sorted(str(item.get("id", item.get("list_id", "")))
                 for item in listings)
    raw = ",".join(ids)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Resumo dos matches ────────────────────────────────────────────────────────


def summarize_matches(matches: list[MatchResult]) -> dict[str, Any]:
    """
    Gera resumo estatístico dos matches encontrados.

    Args:
        matches: Lista de MatchResult.

    Returns:
        Dict com total, média de score, distribuição por tier.
    """
    if not matches:
        return {"total": 0, "avg_score": 0.0, "by_tier": {}}

    by_tier: dict[str, list[float]] = {}
    for m in matches:
        by_tier.setdefault(m.match_type, []).append(m.score)

    return {
        "total": len(matches),
        "avg_score": round(sum(m.score for m in matches) / len(matches), 4),
        "by_tier": {
            tier: {
                "count": len(scores),
                "avg_score": round(sum(scores) / len(scores), 4),
            }
            for tier, scores in sorted(by_tier.items())
        },
    }
