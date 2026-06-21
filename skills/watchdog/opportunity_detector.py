#!/usr/bin/env python3
"""
opportunity_detector — Detecção de oportunidades de preço no Watchdog.

Consome o campo `priceChangePercent` quando disponível (calculado pelo
portal de origem, ex.: EmCasa) e faz fallback para comparação manual
entre execuções anteriores para portais que não expõem esse dado.

Uso:
    from skills.watchdog.opportunity_detector import detect, Opportunity

    opps = detect(imoveis_atuais, imoveis_anteriores)
    for opp in opps:
        print(f"{opp.tipo}: {opp.imovel.preco_formatado()} ({opp.origem})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# O schema unificado vive em ~/.hermes/
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

logger = logging.getLogger("opportunity_detector")

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.WARNING)
    _handler.setFormatter(logging.Formatter("[opp] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.WARNING)


# ── Tipos de oportunidade ─────────────────────────────────────────────────────

OPORTUNIDADE_NOVO = "novo"
"""Imóvel que não existia na execução anterior (entrou no mercado)."""

OPORTUNIDADE_REMOVIDO = "removido"
"""Imóvel que existia e não está mais (vendeu/alugou/saiu do ar)."""

OPORTUNIDADE_QUEDA_PRECO = "queda_preco"
"""Preço do imóvel caiu (independente da fonte da informação)."""

OPORTUNIDADE_AUMENTO_PRECO = "aumento_preco"
"""Preço do imóvel subiu."""

TIPO_OPORTUNIDADE = frozenset({
    OPORTUNIDADE_NOVO,
    OPORTUNIDADE_REMOVIDO,
    OPORTUNIDADE_QUEDA_PRECO,
    OPORTUNIDADE_AUMENTO_PRECO,
})


# ── Dataclass de resultado ───────────────────────────────────────────────────

@dataclass
class Opportunity:
    """
    Representa uma oportunidade detectada (mudança relevante em um imóvel).

    Attributes:
        tipo: Tipo da oportunidade (OPORTUNIDADE_*).
        imovel: O Imovel atual (ou o anterior para removidos).
        origem: Flag de origem da detecção. 'EmCasa' quando veio do campo
                priceChangePercent do portal. 'watchdog' quando computado
                por diferença entre execuções.
        change_pct: Percentual de variação (None se não aplicável).
        old_price: Preço anterior (None se não aplicável / não informado).
        new_price: Preço novo (None se não aplicável).
        detalhes: Dict com informações extras da detecção.
    """
    tipo: str = ""
    imovel: Optional[Imovel] = None
    origem: str = "watchdog"
    change_pct: Optional[float] = None
    old_price: Optional[float] = None
    new_price: Optional[float] = None
    detalhes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        assert self.tipo in TIPO_OPORTUNIDADE, (
            f"tipo '{self.tipo}' inválido. Válidos: {sorted(TIPO_OPORTUNIDADE)}"
        )

    def resumo(self) -> str:
        """Resumo de uma linha para notificações."""
        if not self.imovel:
            return f"[{self.tipo}] Oportunidade (sem imóvel)"

        base = self.imovel.resumo()
        if self.tipo == OPORTUNIDADE_QUEDA_PRECO and self.change_pct is not None:
            old = f"R$ {self.old_price:,.0f}".replace(",", ".") if self.old_price else "N/I"
            new = f"R$ {self.new_price:,.0f}".replace(",", ".") if self.new_price else "N/I"
            return (
                f"📉 {old} → {new} ({self.change_pct:+.1f}%) "
                f"— {self.imovel.titulo[:50]} ({self.origem})"
            )
        elif self.tipo == OPORTUNIDADE_AUMENTO_PRECO and self.change_pct is not None:
            old = f"R$ {self.old_price:,.0f}".replace(",", ".") if self.old_price else "N/I"
            new = f"R$ {self.new_price:,.0f}".replace(",", ".") if self.new_price else "N/I"
            return (
                f"📈 {old} → {new} ({self.change_pct:+.1f}%) "
                f"— {self.imovel.titulo[:50]} ({self.origem})"
            )
        elif self.tipo == OPORTUNIDADE_NOVO:
            return f"🆕 {base} ({self.origem})"
        elif self.tipo == OPORTUNIDADE_REMOVIDO:
            return f"❌ {base} ({self.origem})"
        return f"[{self.tipo}] {base}"

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dict (JSON-safe)."""
        return {
            "tipo": self.tipo,
            "imovel_id": self.imovel.id if self.imovel else "",
            "origem": self.origem,
            "change_pct": self.change_pct,
            "old_price": self.old_price,
            "new_price": self.new_price,
            "detalhes": self.detalhes,
        }


# ── Core detection ───────────────────────────────────────────────────────────


def _get_extra(imovel: Imovel) -> dict[str, Any]:
    """Retorna o dict _extra do Imovel, ou vazio se não existir."""
    return getattr(imovel, "_extra", {})


def _get_price_change_pct(imovel: Imovel) -> Optional[float]:
    """
    Retorna priceChangePercent do _extra, se disponível.

    Apenas portais que já calculam a variação (ex.: EmCasa) preenchem
    este campo. Retorna None se não disponível.
    """
    extra = _get_extra(imovel)
    pct = extra.get("priceChangePercent")
    if pct is not None:
        return float(pct)
    return None


def _get_previous_price(imovel: Imovel) -> Optional[float]:
    """Retorna previousPrice do _extra, se disponível."""
    extra = _get_extra(imovel)
    pp = extra.get("previousPrice")
    if pp is not None:
        return float(pp)
    return None


def detect(
    current: list[Imovel],
    previous: list[Imovel] | None = None,
) -> list[Opportunity]:
    """
    Detecta oportunidades comparando lista atual com anterior.

    Fluxo de decisão para queda de preço:
      1. Se o imóvel tem ``priceChangePercent`` no ``_extra`` (EmCasa),
         usa esse valor direto — origem = 'EmCasa'.
      2. Se tem ``previousPrice`` no ``_extra``, calcula a variação.
      3. Se ambos os anteriores não existem, compara com o estado
         anterior (se fornecido) — origem = 'watchdog'.
      4. Se não há estado anterior nem dados do portal, o imóvel
         é considerado "novo" se não existia antes.

    Args:
        current: Lista de Imovel da coleta atual (com _extra preservado).
        previous: Lista de Imovel da coleta anterior, ou None se é a
                  primeira execução.

    Returns:
        Lista de Opportunity (ordenada: quedas primeiro, depois aumentos,
        depois novos, depois removidos).
    """
    opps: list[Opportunity] = []

    # Índices por id
    current_by_id: dict[str, Imovel] = {im.id: im for im in current if im.id}
    previous_by_id: dict[str, Imovel] = (
        {im.id: im for im in previous if im.id} if previous else {}
    )

    current_ids = set(current_by_id.keys())
    previous_ids = set(previous_by_id.keys())

    # ─ Imóveis novos (não existiam antes) ────────────────────────────────
    new_ids = current_ids - previous_ids
    for im_id in new_ids:
        im = current_by_id[im_id]
        extra = _get_extra(im)
        source = extra.get("fonte_origem", im.fonte) if extra else im.fonte
        opps.append(Opportunity(
            tipo=OPORTUNIDADE_NOVO,
            imovel=im,
            origem=source.capitalize() if source else "Watchdog",
            detalhes={
                "fonte": im.fonte,
                "bairro": im.bairro,
                "cidade": im.cidade,
            },
        ))

    # ─ Imóveis removidos (não estão mais no ar) ──────────────────────────
    removed_ids = previous_ids - current_ids
    for im_id in removed_ids:
        im = previous_by_id[im_id]
        extra = _get_extra(im)
        source = extra.get("fonte_origem", im.fonte) if extra else im.fonte
        opps.append(Opportunity(
            tipo=OPORTUNIDADE_REMOVIDO,
            imovel=im,
            origem=source.capitalize() if source else "Watchdog",
            detalhes={
                "fonte": im.fonte,
                "ultimo_preco": im.preco_venda,
                "bairro": im.bairro,
                "cidade": im.cidade,
            },
        ))

    # ─ Imóveis que permaneceram — detectar mudança de preço ──────────────
    stable_ids = current_ids & previous_ids
    for im_id in stable_ids:
        im_cur = current_by_id[im_id]
        im_prev = previous_by_id[im_id]

        cur_price = im_cur.preco_venda or im_cur.preco_aluguel
        prev_price = im_prev.preco_venda or im_prev.preco_aluguel

        # PRIORIDADE 1: priceChangePercent do portal (EmCasa)
        # Verifica ANTES da comparação de preços — o portal já calculou
        # a variação e é a fonte mais confiável.
        pct = _get_price_change_pct(im_cur)
        if pct is not None and pct != 0:
            origin = "EmCasa" if im_cur.fonte == "emcasa" else im_cur.fonte.capitalize()
            opps.append(Opportunity(
                tipo=OPORTUNIDADE_QUEDA_PRECO if pct < 0 else OPORTUNIDADE_AUMENTO_PRECO,
                imovel=im_cur,
                origem=origin,
                change_pct=round(pct, 2),
                old_price=_get_previous_price(im_cur) or prev_price,
                new_price=cur_price,
                detalhes={
                    "fonte": im_cur.fonte,
                    "origem_calc": "priceChangePercent",
                    "prev_price_from": "portal",
                },
            ))
            continue

        # PRIORIDADE 2: previousPrice no _extra
        prev_extra = _get_previous_price(im_cur)
        if prev_extra is not None and prev_extra != cur_price:
            pct_calc = ((cur_price - prev_extra) / prev_extra) * 100 if prev_extra else 0
            origin = "EmCasa" if im_cur.fonte == "emcasa" else im_cur.fonte.capitalize()
            opps.append(Opportunity(
                tipo=OPORTUNIDADE_QUEDA_PRECO if pct_calc < 0 else OPORTUNIDADE_AUMENTO_PRECO,
                imovel=im_cur,
                origem=origin,
                change_pct=round(pct_calc, 2),
                old_price=prev_extra,
                new_price=cur_price,
                detalhes={
                    "fonte": im_cur.fonte,
                    "origem_calc": "previousPrice",
                    "prev_price_from": "portal",
                },
            ))
            continue

        # PRIORIDADE 3: Fallback — compara com estado anterior
        if prev_price is not None and cur_price is not None and prev_price != cur_price:
            pct_calc = ((cur_price - prev_price) / prev_price) * 100
            opps.append(Opportunity(
                tipo=OPORTUNIDADE_QUEDA_PRECO if pct_calc < 0 else OPORTUNIDADE_AUMENTO_PRECO,
                imovel=im_cur,
                origem="Watchdog",
                change_pct=round(pct_calc, 2),
                old_price=prev_price,
                new_price=cur_price,
                detalhes={
                    "fonte": im_cur.fonte,
                    "origem_calc": "diff_state",
                    "prev_price_from": "previous_state",
                },
            ))
            continue

        # Se chegou aqui com preços diferentes, emite com warning
        # (dados de portal insuficientes, provavelmente fonte sem _extra)
        if prev_price is not None and cur_price is not None and prev_price != cur_price:
            logger.warning(
                f"Imóvel {im_id}: preço mudou ({prev_price} → {cur_price}) "
                f"mas sem dados para calcular variação"
            )
            if cur_price < prev_price:
                tipo = OPORTUNIDADE_QUEDA_PRECO
            else:
                tipo = OPORTUNIDADE_AUMENTO_PRECO
            opps.append(Opportunity(
                tipo=tipo,
                imovel=im_cur,
                origem="Watchdog",
                detalhes={
                    "fonte": im_cur.fonte,
                    "origem_calc": "unknown",
                    "old_price_raw": prev_price,
                    "new_price_raw": cur_price,
                },
            ))

    # Ordena: quedas primeiro (mais relevantes), depois aumentos,
    # depois novos, depois removidos
    tipo_order = {
        OPORTUNIDADE_QUEDA_PRECO: 0,
        OPORTUNIDADE_AUMENTO_PRECO: 1,
        OPORTUNIDADE_NOVO: 2,
        OPORTUNIDADE_REMOVIDO: 3,
    }
    opps.sort(key=lambda o: (tipo_order.get(o.tipo, 99), o.change_pct or 0))

    return opps


def detect_from_dicts(
    current_dicts: list[dict[str, Any]],
    previous_dicts: list[dict[str, Any]] | None = None,
) -> list[Opportunity]:
    """
    Wrapper que aceita dicts (serializados via Imovel.to_dict) e
    reconstrói os Imovel + _extra antes de detectar.

    Útil quando os dados vêm de arquivos JSON (estado salvo em disco).

    Args:
        current_dicts: Lista de dicts da coleta atual (podem ter chave
                       '_extra' para campos extras).
        previous_dicts: Lista de dicts da coleta anterior, ou None.

    Returns:
        Lista de Opportunity.
    """
    def _reconstroi(d: dict) -> Imovel:
        extra = d.pop("_extra", {})
        im = Imovel.from_dict(d)
        if extra:
            im._extra = extra
        return im

    current = [_reconstroi(d) for d in current_dicts]
    previous = [_reconstroi(d) for d in previous_dicts] if previous_dicts else None
    return detect(current, previous)


# ── Agrupamento por fonte ────────────────────────────────────────────────────

def group_by_fonte(
    opportunities: list[Opportunity],
) -> dict[str, list[Opportunity]]:
    """
    Agrupa oportunidades pela fonte do imóvel.

    Returns:
        Dict com fonte → lista de oportunidades.
    """
    groups: dict[str, list[Opportunity]] = {}
    for opp in opportunities:
        fonte = opp.imovel.fonte if opp.imovel else "desconhecido"
        groups.setdefault(fonte, []).append(opp)
    return groups


# ── Sumarização para notificações ───────────────────────────────────────────

def build_notification_text(
    opportunities: list[Opportunity],
    title: str = "🏠 Watchdog — Oportunidades Detectadas",
) -> str:
    """
    Gera texto formatado para notificação (Telegram/Markdown).

    Args:
        opportunities: Lista de oportunidades detectadas.
        title: Título da notificação.

    Returns:
        String formatada em Markdown para envio.
    """
    if not opportunities:
        return f"{title}\n\nSem oportunidades no momento."

    lines = [title, ""]

    grouped = group_by_fonte(opportunities)
    for fonte, opps in sorted(grouped.items()):
        lines.append(f"*{fonte.capitalize()} — {len(opps)} oportunidade(s)*")
        for opp in opps:
            lines.append(f"  {opp.resumo()}")
        lines.append("")

    lines.append(f"🔍 {len(opportunities)} oportunidade(s) no total")
    return "\n".join(lines)
