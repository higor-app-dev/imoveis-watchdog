"""
classificador — Classificação semântica de mudanças em imóveis.

A partir de um DiffResult (do módulo diff_imoveis), gera uma lista
plana de MudancaEvento, um para cada mudança semântica detectada.

Tipos de mudança:
  - 'new':             imóvel apareceu na lista atual (não existia antes)
  - 'removed':         imóvel sumiu da lista atual (existia antes)
  - 'price_decrease':  um campo de preço diminuiu
  - 'price_increase':  um campo de preço aumentou
  - 'status_change':   o campo 'disponivel' ou 'status' mudou

Para imóveis com múltiplas mudanças, gera uma entrada para cada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from imovel_schema import Imovel


# ── Campos monitorados por categoria ──────────────────────────────────────────

CAMPOS_PRECO: tuple[str, ...] = (
    "preco_venda",
    "preco_aluguel",
    "condominio",
    "iptu",
)

CAMPOS_STATUS: tuple[str, ...] = (
    "disponivel",
    "status",
)

CAMPOS_CARACTERISTICA: tuple[str, ...] = (
    "area",
    "quartos",
    "banheiros",
    "vagas",
    "amenities",
)


# ── Evento de saída ───────────────────────────────────────────────────────────


@dataclass
class MudancaEvento:
    """Uma única mudança semântica detectada num imóvel.

    Attributes:
        tipo: Categoria da mudança — 'new', 'removed', 'price_decrease',
              'price_increase' ou 'status_change'.
        id_imovel: ID do imóvel que sofreu a mudança.
        campo: Nome do campo que mudou (vazio para 'new'/'removed').
        valor_anterior: Valor anterior do campo (None para 'new').
        valor_novo: Valor novo do campo (None para 'removed').
        timestamp: ISO 8601 do momento da coleta atual.
    """

    tipo: str
    id_imovel: str
    campo: str = ""
    valor_anterior: Any = None
    valor_novo: Any = None
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Converte para dict serializável (JSON-safe)."""
        d: dict[str, Any] = {
            "tipo": self.tipo,
            "id_imovel": self.id_imovel,
            "campo": self.campo,
            "timestamp": self.timestamp,
        }
        # Inclui valores quando aplicável
        if self.valor_anterior is not None:
            d["valor_anterior"] = self.valor_anterior
        if self.valor_novo is not None:
            d["valor_novo"] = self.valor_novo
        return d

    def __str__(self) -> str:
        if self.tipo in ("new", "removed"):
            return f"{self.tipo}: {self.id_imovel}"
        if self.tipo.startswith("price_"):
            return (
                f"{self.tipo}: {self.id_imovel} — "
                f"{self.campo}: {self.valor_anterior} → {self.valor_novo}"
            )
        return (
            f"{self.tipo}: {self.id_imovel} — "
            f"{self.campo}: {self.valor_anterior} → {self.valor_novo}"
        )


# ── Função principal ──────────────────────────────────────────────────────────


def classificar_mudancas(
    diff_result: Any,
    *,
    timestamp: Optional[str] = None,
) -> list[MudancaEvento]:
    """Classifica as mudanças de um DiffResult em eventos semânticos.

    Gera uma lista plana de MudancaEvento, um para cada mudança
    detectada. Imóveis com múltiplas alterações geram múltiplos eventos.

    Args:
        diff_result: Instância de DiffResult (diff_imoveis).
        timestamp: Timestamp ISO 8601 opcional. Se omitido, usa o momento
                   atual (UTC). Quando disponível, usa o timestamp do
                   imóvel 'atual' de cada alteração.

    Returns:
        Lista de MudancaEvento, ordenada: novos → removidos → alterados.
    """
    eventos: list[MudancaEvento] = []

    now_iso = timestamp or datetime.now(timezone.utc).isoformat()

    # ── 1. Imóveis novos ──────────────────────────────────────────────
    for imovel in diff_result.novos:
        ts = imovel.data_coleta or now_iso
        eventos.append(
            MudancaEvento(
                tipo="new",
                id_imovel=imovel.id,
                campo="",
                valor_anterior=None,
                valor_novo=imovel.to_dict(),
                timestamp=ts,
            )
        )

    # ── 2. Imóveis removidos ──────────────────────────────────────────
    for imovel in diff_result.removidos:
        ts = imovel.data_coleta or now_iso
        eventos.append(
            MudancaEvento(
                tipo="removed",
                id_imovel=imovel.id,
                campo="",
                valor_anterior=imovel.to_dict(),
                valor_novo=None,
                timestamp=ts,
            )
        )

    # ── 3. Imóveis alterados → desmembrar por campo ───────────────────
    for alteracao in diff_result.alterados:
        id_ = alteracao.id
        # Tenta extrair timestamp do estado atual
        ts = (
            getattr(alteracao.atual, "data_coleta", None)
            or now_iso
        )

        for campo_alt in alteracao.campos_alterados:
            campo = campo_alt.campo
            val_ant = campo_alt.valor_anterior
            val_novo = campo_alt.valor_novo

            evento = _classificar_alteracao_campo(
                id_=id_,
                campo=campo,
                valor_anterior=val_ant,
                valor_novo=val_novo,
                timestamp=ts,
            )
            if evento is not None:
                eventos.append(evento)

    return eventos


# ── Funções auxiliares ────────────────────────────────────────────────────────


def _classificar_alteracao_campo(
    id_: str,
    campo: str,
    valor_anterior: Any,
    valor_novo: Any,
    timestamp: str,
) -> Optional[MudancaEvento]:
    """Classifica uma alteração de campo único em um MudancaEvento.

    Returns:
        MudancaEvento classificado, ou None se o campo não for
        reconhecido como monitorado.
    """
    # ─ Preço diminuiu ─────────────────────────────────────────────
    if campo in CAMPOS_PRECO:
        # Tenta comparar numericamente
        ant_num = _as_number(valor_anterior)
        novo_num = _as_number(valor_novo)

        if ant_num is not None and novo_num is not None:
            if novo_num < ant_num:
                return MudancaEvento(
                    tipo="price_decrease",
                    id_imovel=id_,
                    campo=campo,
                    valor_anterior=valor_anterior,
                    valor_novo=valor_novo,
                    timestamp=timestamp,
                )
            elif novo_num > ant_num:
                return MudancaEvento(
                    tipo="price_increase",
                    id_imovel=id_,
                    campo=campo,
                    valor_anterior=valor_anterior,
                    valor_novo=valor_novo,
                    timestamp=timestamp,
                )
            # Igual dentro da tolerância → não gera evento
            return None
        # Não numérico → cai como price_increase genérico
        return MudancaEvento(
            tipo="price_increase",
            id_imovel=id_,
            campo=campo,
            valor_anterior=valor_anterior,
            valor_novo=valor_novo,
            timestamp=timestamp,
        )

    # ─ Status mudou (disponivel, status) ─────────────────────────────
    if campo in CAMPOS_STATUS:
        return MudancaEvento(
            tipo="status_change",
            id_imovel=id_,
            campo=campo,
            valor_anterior=valor_anterior,
            valor_novo=valor_novo,
            timestamp=timestamp,
        )

    # ─ Característica mudou (area, quartos, amenities, etc.) ────────
    if campo in CAMPOS_CARACTERISTICA:
        return MudancaEvento(
            tipo="field_change",
            id_imovel=id_,
            campo=campo,
            valor_anterior=valor_anterior,
            valor_novo=valor_novo,
            timestamp=timestamp,
        )

    # Campos não monitorados para classificação semântica são ignorados
    return None


def _as_number(val: Any) -> Optional[float]:
    """Tenta converter um valor para número (float).

    Trata None, bool, int, float e strings numéricas.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return None  # bool False == 0 numericamente, mas não queremos
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    return None
