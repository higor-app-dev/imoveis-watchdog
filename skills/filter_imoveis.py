"""
filter_imoveis — Filter listings by type, negotiation, and neighborhood.

Takes a list of items in the unified Imovel schema and returns a filtered
sublist. Each filter parameter can be None (skip that criterion).

Filter parameters:
    tipo        — 'apartamento', 'casa', 'cobertura', etc. (matches item["tipo"])
    negociacao  — 'venda' (preco_venda is set) or 'aluguel' (preco_aluguel is set)
    bairro      — neighborhood name, case-insensitive match (matches item["bairro"])

Usage:
    from skills.filter_imoveis import filter_imoveis

    # Get only apartments for sale in Moema
    aptos_venda_moema = filter_imoveis(
        items,
        tipo="apartamento",
        negociacao="venda",
        bairro="Moema",
    )

    # Get everything for rent, regardless of type or neighborhood
    alugueis = filter_imoveis(items, negociacao="aluguel")
"""

from __future__ import annotations

from typing import Any, Optional


def _get_negociacao(item: dict) -> str | None:
    """Determine the negotiation type from an item's price fields.

    Returns 'venda' if preco_venda is set, 'aluguel' if preco_aluguel is set,
    or None if neither (or both) are set.
    """
    venda = item.get("preco_venda") is not None
    aluguel = item.get("preco_aluguel") is not None

    if venda and not aluguel:
        return "venda"
    if aluguel and not venda:
        return "aluguel"
    return None  # ambiguous: neither or both


def filter_imoveis(
    items: list[dict],
    tipo: str | None = None,
    negociacao: str | None = None,
    bairro: str | None = None,
) -> list[dict]:
    """Filter a list of Imovel items by type, negotiation, and neighborhood.

    Args:
        items: List of dicts in the unified Imovel schema.
        tipo: Property type to filter by (e.g., 'apartamento', 'casa').
              Case-insensitive. None = skip.
        negociacao: Negotiation type ('venda' or 'aluguel').
                    None = skip.
        bairro: Neighborhood to filter by (e.g., 'Moema', 'Vila Mariana').
                Case-insensitive substring match. None = skip.

    Returns:
        Filtered sublist of items matching ALL provided criteria.
    """
    result: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        match = True

        # Filter by tipo
        if match and tipo is not None:
            item_tipo = (item.get("tipo") or "").strip().lower()
            if item_tipo != tipo.strip().lower():
                match = False

        # Filter by negociacao
        if match and negociacao is not None:
            item_neg = _get_negociacao(item)
            if item_neg != negociacao.strip().lower():
                match = False

        # Filter by bairro (case-insensitive)
        if match and bairro is not None:
            item_bairro = (item.get("bairro") or "").strip().lower()
            filter_bairro = bairro.strip().lower()
            if filter_bairro not in item_bairro:
                match = False

        if match:
            result.append(item)

    return result
