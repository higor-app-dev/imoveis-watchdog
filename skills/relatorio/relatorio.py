"""
relatorio — Geração de relatórios de mudanças detectadas.

A partir de uma lista de MudancaEvento (do módulo classificador),
produz relatórios em formato legível (console) e estruturado (JSON),
configurável entre sumário e detalhado.

Uso:
    from relatorio import gerar_relatorio_console, gerar_relatorio_json

    # Console (sumário)
    print(gerar_relatorio_console(eventos, formato="summary"))

    # JSON (detalhado)
    rel = gerar_relatorio_json(eventos, formato="detailed")
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

from imovel_schema import Imovel

# ── Constantes ────────────────────────────────────────────────────────────

FORMATOS_VALIDOS = frozenset({"summary", "detailed"})

ETIQUETAS_TIPO = {
    "new": "Novos",
    "removed": "Removidos",
    "price_decrease": "Redução de Preço",
    "price_increase": "Aumento de Preço",
    "status_change": "Mudança de Status",
    "field_change": "Alteração de Característica",
}

CAMPOS_PRECO_NOME = {
    "preco_venda": "Venda",
    "preco_aluguel": "Aluguel",
    "condominio": "Condomínio",
    "iptu": "IPTU",
}

# ── Tipos de saída ────────────────────────────────────────────────────────

Formato = str  # "summary" | "detailed"
LookupFn = Callable[[str], Optional[dict]]


@dataclass
class Contagens:
    """Contagens agregadas por tipo de evento."""

    novos: int = 0
    removidos: int = 0
    price_decrease: int = 0
    price_increase: int = 0
    status_change: int = 0
    field_change: int = 0

    @property
    def total(self) -> int:
        return self.novos + self.removidos + self.price_decrease + self.price_increase + self.status_change + self.field_change

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"total": self.total}


# ── Helpers de extração ───────────────────────────────────────────────────


def _extrair_imovel_dict(evento: Any) -> Optional[dict]:
    """Extrai o dict do Imovel embutido no evento (new/removed), se houver."""
    if evento.tipo == "new":
        return evento.valor_novo if isinstance(evento.valor_novo, dict) else None
    if evento.tipo == "removed":
        return evento.valor_anterior if isinstance(evento.valor_anterior, dict) else None
    return None


def _fmt_preco(val: Any) -> str:
    """Formata valor como preço em R$."""
    if val is None:
        return "N/I"
    try:
        return f"R$ {float(val):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return str(val)


def _fmt_campo_preco(campo: str) -> str:
    """Nome amigável do campo de preço."""
    return CAMPOS_PRECO_NOME.get(campo, campo)


def _extrair_cond_iptu(imovel_dict: dict) -> list[str]:
    """Extrai strings de condomínio e IPTU do dict, se disponíveis."""
    partes: list[str] = []
    cond = imovel_dict.get("condominio")
    if cond is not None:
        try:
            partes.append(f"Cond. {_fmt_preco(cond)}")
        except (ValueError, TypeError):
            pass
    iptu = imovel_dict.get("iptu")
    if iptu is not None:
        try:
            partes.append(f"IPTU {_fmt_preco(iptu)}")
        except (ValueError, TypeError):
            pass
    return partes


def _formatar_evento(evento: Any, lookup: Optional[LookupFn] = None) -> str:
    """Formata um evento individual em uma linha de texto.

    Tenta extrair título, preço, condomínio, IPTU e bairro de:
    1. Dict do Imovel embutido (new/removed)
    2. lookup callback (qualquer tipo)
    3. Fallback: só o ID
    """
    imovel_dict = _extrair_imovel_dict(evento)
    if imovel_dict is None and lookup is not None:
        imovel_dict = lookup(evento.id_imovel)

    if imovel_dict:
        titulo = imovel_dict.get("titulo", "") or ""
        preco = _fmt_preco(imovel_dict.get("preco_venda") or imovel_dict.get("preco_aluguel"))
        bairro = imovel_dict.get("bairro", "") or ""
        url = imovel_dict.get("url", "") or ""
        cond_iptu = _extrair_cond_iptu(imovel_dict)
        partes = [f"[{evento.id_imovel}]"]
        if titulo:
            partes.append(titulo)
        partes.append(preco)
        if cond_iptu:
            partes.extend(cond_iptu)
        if bairro:
            partes.append(bairro)
        linha = " — ".join(partes)
        if url:
            linha += f"\n    {url}"
        return linha

    # Fallback: só o ID
    return f"[{evento.id_imovel}]"


def _formatar_alteracao(evento: Any, lookup: Optional[LookupFn] = None) -> str:
    """Formata um evento de alteração (preço/status) destacando o campo mudado."""
    imovel_dict = _extrair_imovel_dict(evento)
    if imovel_dict is None and lookup is not None:
        imovel_dict = lookup(evento.id_imovel)

    cabecalho = _formatar_evento(evento, lookup)

    if evento.tipo in ("price_decrease", "price_increase"):
        campo_nome = _fmt_campo_preco(evento.campo)
        ant = _fmt_preco(evento.valor_anterior)
        novo = _fmt_preco(evento.valor_novo)
        return f"  {cabecalho}\n    {campo_nome}: {ant} → {novo}"

    if evento.tipo == "status_change":
        ant = str(evento.valor_anterior)
        novo = str(evento.valor_novo)
        return f"  {cabecalho}\n    {evento.campo}: {ant} → {novo}"

    if evento.tipo == "field_change":
        ant = _fmt_val_caracteristica(evento.valor_anterior)
        novo = _fmt_val_caracteristica(evento.valor_novo)
        return f"  {cabecalho}\n    {evento.campo}: {ant} → {novo}"

    return cabecalho


def _fmt_val_caracteristica(val: Any) -> str:
    """Formata valor de característica (amenities, area, etc.) para exibição."""
    if val is None:
        return "N/I"
    if isinstance(val, list):
        if not val:
            return "[]"
        if len(val) <= 5:
            return ", ".join(str(v) for v in val)
        return f"{len(val)} itens"
    if isinstance(val, float):
        if val >= 1000:
            return f"R$ {val:,.0f}".replace(",", ".")
        return f"{val:.2f}"
    return str(val)


# ── Função principal de contagem ──────────────────────────────────────────


def contar_tipos(eventos: list) -> Contagens:
    """Agrega contagens por tipo de evento."""
    cont = Contagens()
    for ev in eventos:
        if ev.tipo == "new":
            cont.novos += 1
        elif ev.tipo == "removed":
            cont.removidos += 1
        elif ev.tipo == "price_decrease":
            cont.price_decrease += 1
        elif ev.tipo == "price_increase":
            cont.price_increase += 1
        elif ev.tipo == "status_change":
            cont.status_change += 1
        elif ev.tipo == "field_change":
            cont.field_change += 1
    return cont


# ── Relatório Console ─────────────────────────────────────────────────────


def gerar_relatorio_console(
    eventos: list,
    *,
    formato: str = "detailed",
    lookup_imovel: Optional[LookupFn] = None,
    titulo: str = "Relatório de Mudanças",
) -> str:
    """Gera relatório em formato texto legível no console.

    Args:
        eventos: Lista de MudancaEvento.
        formato: "summary" (apenas contagens) ou "detailed" (com detalhes).
        lookup_imovel: Callable(id) → dict imovel | None. Opcional, enriquece
                       eventos de alteração com título/preço/bairro.
        titulo: Título do relatório.

    Returns:
        String formatada para exibição no console.
    """
    if formato not in FORMATOS_VALIDOS:
        formato = "detailed"

    cont = contar_tipos(eventos)
    linhas: list[str] = []

    # ── Título ─────────────────────────────────────────────────────────
    linhas.append(f"=== {titulo} ===")
    if eventos:
        ts = getattr(eventos[0], "timestamp", "")
        if ts:
            linhas.append(f"Coleta: {ts}")
    linhas.append("")

    # ── Sumário ────────────────────────────────────────────────────────
    linhas.append(f"  Novos:            {cont.novos}")
    linhas.append(f"  Removidos:        {cont.removidos}")
    linhas.append(f"  Redução de Preço: {cont.price_decrease}")
    linhas.append(f"  Aumento de Preço:  {cont.price_increase}")
    linhas.append(f"  Mudança de Status: {cont.status_change}")
    linhas.append(f"  Alteração de Caract: {cont.field_change}")
    linhas.append(f"  {'─' * 36}")
    linhas.append(f"  Total: {cont.total} evento(s)")
    linhas.append("")

    # ── Detalhamento ───────────────────────────────────────────────────
    if formato == "detailed" and cont.total > 0:
        for tipo, etiqueta in [
            ("new", "Novos"),
            ("removed", "Removidos"),
            ("price_decrease", "Redução de Preço"),
            ("price_increase", "Aumento de Preço"),
            ("status_change", "Mudança de Status"),
            ("field_change", "Alteração de Característica"),
        ]:
            evs = [e for e in eventos if e.tipo == tipo]
            if not evs:
                continue

            linhas.append(f"── {etiqueta} ({len(evs)}) {'─' * max(0, 36 - len(etiqueta) - 4)}")
            linhas.append("")

            for ev in evs:
                if ev.tipo in ("new", "removed"):
                    linhas.append(f"  {_formatar_evento(ev, lookup_imovel)}")
                else:
                    linhas.append(_formatar_alteracao(ev, lookup_imovel))
                linhas.append("")

    return "\n".join(linhas).rstrip("\n") + "\n"


# ── Relatório JSON ───────────────────────────────────────────────────────


def gerar_relatorio_json(
    eventos: list,
    *,
    formato: str = "detailed",
    lookup_imovel: Optional[LookupFn] = None,
) -> dict[str, Any]:
    """Gera relatório em formato JSON estruturado.

    Args:
        eventos: Lista de MudancaEvento.
        formato: "summary" (apenas contagens) ou "detailed" (com eventos).
        lookup_imovel: Callable(id) → dict imovel | None.

    Returns:
        Dict serializável (JSON-safe).
    """
    if formato not in FORMATOS_VALIDOS:
        formato = "detailed"

    cont = contar_tipos(eventos)

    relatorio: dict[str, Any] = {
        "versao": 1,
        "formato": formato,
        "resumo": cont.to_dict(),
    }

    if formato == "detailed":
        eventos_json: list[dict[str, Any]] = []
        for ev in eventos:
            d = {
                "tipo": ev.tipo,
                "id_imovel": ev.id_imovel,
                "timestamp": getattr(ev, "timestamp", ""),
            }

            # Inclui campo e valores quando aplicável
            if ev.campo:
                d["campo"] = ev.campo

            # Tenta enriquecer com dados do imóvel
            imovel_dict = _extrair_imovel_dict(ev)
            if imovel_dict is None and lookup_imovel is not None:
                imovel_dict = lookup_imovel(ev.id_imovel)

            if imovel_dict:
                d["imovel"] = {
                    "titulo": imovel_dict.get("titulo", ""),
                    "preco_venda": imovel_dict.get("preco_venda"),
                    "preco_aluguel": imovel_dict.get("preco_aluguel"),
                    "condominio": imovel_dict.get("condominio"),
                    "iptu": imovel_dict.get("iptu"),
                    "amenities": imovel_dict.get("amenities", []),
                    "bairro": imovel_dict.get("bairro", ""),
                    "cidade": imovel_dict.get("cidade", ""),
                    "url": imovel_dict.get("url", ""),
                    "fonte": imovel_dict.get("fonte", ""),
                }

            # Valores numéricos da alteração
            if ev.valor_anterior is not None:
                d["valor_anterior"] = ev.valor_anterior
            if ev.valor_novo is not None:
                d["valor_novo"] = ev.valor_novo

            eventos_json.append(d)

        relatorio["eventos"] = eventos_json

    return relatorio
