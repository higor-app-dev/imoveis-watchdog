"""
oportunidades — Relatório unificado de novas oportunidades entre portais.

Agrega listings deduplicados de todos os portais (QuintoAndar, Loft, etc.)
e produz relatórios de novas propriedades não vistas anteriormente.
Usa o motor de dedup cross-portal (qa_loft_dedup) para garantir que
cada imóvel apareça apenas uma vez no relatório.

Uso:
    from oportunidades import (
        gerar_relatorio_oportunidades,
        RelatorioOportunidades,
    )

    # On-demand
    rel = gerar_relatorio_oportunidades(listings_atuais)
    print(rel.texto)
    # ou salvar
    rel.salvar("relatorio_oportunidades.txt")

    # Com estado anterior (comparação)
    rel = gerar_relatorio_oportunidades(
        listings_atuais,
        estado_path="data/state_snapshots/oportunidades.json",
    )

    # Dedup automático (cross-portal QA ↔ Loft)
    rel = gerar_relatorio_oportunidades(
        listings_atuais,
        aplicar_dedup=True,
    )
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from imovel_schema import Imovel


# ── Constantes ────────────────────────────────────────────────────────────────

ESTADO_FILENAME = "oportunidades_estado.json"
"""Nome padrão do arquivo de estado (previous state)."""

NEW_FLAG_NOVO = "NOVO"
"""Flag indicando imóvel não visto antes."""

NEW_FLAG_EXISTENTE = "EXISTENTE"
"""Flag indicando imóvel já visto em execução anterior."""

SAIDA_CONSOLE = "console"
SAIDA_ARQUIVO = "arquivo"
SAIDA_AMBOS = "ambos"
SAIDAS_VALIDAS = frozenset({SAIDA_CONSOLE, SAIDA_ARQUIVO, SAIDA_AMBOS})


# ── Dataclass de saída ────────────────────────────────────────────────────────


@dataclass
class ItemOportunidade:
    """Um item no relatório de oportunidades.

    Attributes:
        endereco: Endereço completo do imóvel.
        bairro: Bairro.
        preco: Preço principal (venda ou aluguel) em R$.
        area: Área em m².
        portais: Lista de portais onde o imóvel foi encontrado.
        url: URL do anúncio (canônico, do primeiro portal na lista).
        new_flag: "NOVO" se visto pela primeira vez, "EXISTENTE" se já conhecido.
        id: ID do imóvel.
        fonte: Fonte principal.
        data_coleta: Timestamp ISO 8601 da coleta.
    """

    endereco: str = ""
    bairro: str = ""
    preco: Optional[float] = None
    area: Optional[float] = None
    portais: list[str] = field(default_factory=list)
    url: str = ""
    new_flag: str = NEW_FLAG_NOVO
    id: str = ""
    fonte: str = ""
    data_coleta: str = ""

    def preco_formatado(self) -> str:
        """Retorna preço formatado em R$."""
        if self.preco is None:
            return "N/I"
        return f"R$ {self.preco:,.0f}".replace(",", ".")

    def portais_str(self) -> str:
        """Portais formatados como string, ex.: 'quintoandar, loft'."""
        if not self.portais:
            return self.fonte or "desconhecido"
        return ", ".join(sorted(set(self.portais)))

    def to_dict(self) -> dict[str, Any]:
        """Converte para dict serializável."""
        return {
            "id": self.id,
            "endereco": self.endereco,
            "bairro": self.bairro,
            "preco": self.preco,
            "preco_formatado": self.preco_formatado(),
            "area": self.area,
            "portais": self.portais,
            "url": self.url,
            "new_flag": self.new_flag,
            "fonte": self.fonte,
            "data_coleta": self.data_coleta,
        }

    @classmethod
    def from_imovel_dict(cls, d: dict) -> ItemOportunidade:
        """Constrói a partir de um dict Imovel (to_dict())."""
        return cls(
            id=str(d.get("id", d.get("list_id", ""))),
            endereco=str(d.get("endereco", "")),
            bairro=str(d.get("bairro", "")),
            preco=d.get("preco_venda") or d.get("preco_aluguel"),
            area=d.get("area"),
            portais=[str(d.get("fonte", ""))] if d.get("fonte") else [],
            url=str(d.get("url", "")),
            fonte=str(d.get("fonte", "")),
            data_coleta=str(d.get("data_coleta", "")),
        )


@dataclass
class RelatorioOportunidades:
    """Relatório completo de novas oportunidades.

    Attributes:
        items: Lista de itens no relatório, já deduplicados e ordenados.
        total: Total de itens.
        total_novos: Quantos são NOVOS.
        total_existentes: Quantos são EXISTENTES.
        timestamp: Timestamp ISO 8601 da geração.
        texto: Relatório formatado em texto (console-ready).
    """

    items: list[ItemOportunidade] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def total_novos(self) -> int:
        return sum(1 for i in self.items if i.new_flag == NEW_FLAG_NOVO)

    @property
    def total_existentes(self) -> int:
        return sum(1 for i in self.items if i.new_flag == NEW_FLAG_EXISTENTE)

    def _agrupar_por_fonte(self) -> dict[str, list[ItemOportunidade]]:
        """Agrupa itens do relatório por fonte (portal).

        Returns:
            Dict ``{fonte: [items]}`` ordenado por quantidade descendente.
        """
        grupos: dict[str, list[ItemOportunidade]] = {}
        for item in self.items:
            fonte = item.fonte or "desconhecido"
            if fonte not in grupos:
                grupos[fonte] = []
            grupos[fonte].append(item)
        # Ordena: mais items primeiro
        return dict(sorted(grupos.items(), key=lambda kv: -len(kv[1])))

    def _formatar_por_fonte(self) -> str:
        """Gera seção de resumo por fonte (portal) com contagens e exemplos."""
        grupos = self._agrupar_por_fonte()
        if not grupos:
            return ""

        linhas: list[str] = []
        linhas.append("── Resumo por Fonte ─────────────────────────────────")
        linhas.append("")

        for fonte, items in grupos.items():
            novos_count = sum(1 for i in items if i.new_flag == NEW_FLAG_NOVO)
            existentes_count = len(items) - novos_count
            preco_min = min((i.preco for i in items if i.preco), default=None)
            preco_max = max((i.preco for i in items if i.preco), default=None)

            nome_exibicao = {
                "quintoandar": "QuintoAndar",
                "loft": "Loft",
                "emcasa": "EmCasa",
                "zap": "Zap Imóveis",
            }.get(fonte, fonte.capitalize())

            linhas.append(f"  {nome_exibicao} ({fonte})")
            linhas.append(f"    Total: {len(items)} | Novos: {novos_count} | Existentes: {existentes_count}")
            if preco_min is not None and preco_max is not None:
                min_fmt = f"R$ {preco_min:,.0f}".replace(",", ".")
                max_fmt = f"R$ {preco_max:,.0f}".replace(",", ".")
                linhas.append(f"    Faixa de preço: {min_fmt} a {max_fmt}")
            linhas.append("")

            # Exibe até 3 exemplos
            exemplos = sorted(items, key=_parse_preco_para_ordenacao)[:3]
            for ex in exemplos:
                preco = ex.preco_formatado()
                bairro = ex.bairro or "N/I"
                flag = "🆕" if ex.new_flag == NEW_FLAG_NOVO else "✓"
                endereco = (ex.endereco or "N/I")[:40]
                linhas.append(f"    {flag} {preco} — {bairro} — {endereco}")
                if ex.url:
                    linhas.append(f"       🔗 {ex.url}")
            linhas.append("")

        return "\n".join(linhas) + "\n"

    def _formatar(self) -> str:
        """Gera o texto formatado do relatório."""
        linhas: list[str] = []

        # ── Título ─────────────────────────────────────────────────────
        linhas.append("=== Relatório de Oportunidades ===")
        linhas.append(f"Gerado: {self.timestamp}")
        linhas.append("")

        # ── Sumário ────────────────────────────────────────────────────
        linhas.append(f"  Total de imóveis únicos: {self.total}")
        linhas.append(f"  Novos:                  {self.total_novos}")
        linhas.append(f"  Existentes:             {self.total_existentes}")
        linhas.append("")

        if not self.items:
            linhas.append("  Nenhum imóvel encontrado.")
            linhas.append("")
            return "\n".join(linhas)

        # ── Cabeçalho da tabela ────────────────────────────────────────
        linhas.append(f"{'Flag':<12}{'Preço':<16}{'Área':<8}{'Bairro':<20}"
                      f"{'Portais':<25}{'Endereço'}")
        linhas.append("─" * 110)
        linhas.append("")

        for item in self.items:
            flag = f"[{item.new_flag}]"
            preco = item.preco_formatado()
            area = f"{int(item.area)}m²" if item.area else "N/I"
            bairro = item.bairro or "N/I"
            portais = item.portais_str()
            endereco = item.endereco or "N/I"

            linhas.append(
                f"{flag:<12}{preco:<16}{area:<8}{bairro:<20}"
                f"{portais:<25}{endereco}"
            )

            if item.url:
                linhas.append(f"  {'':<12}🔗 {item.url}")

            linhas.append("")  # espaçamento entre linhas

        # ── Resumo por fonte ──────────────────────────────────────────
        linhas.append(self._formatar_por_fonte())

        return "\n".join(linhas) + "\n"

    @property
    def texto(self) -> str:
        """Relatório formatado para console."""
        return self._formatar()

    def exibir(self) -> None:
        """Exibe o relatório no console (stdout)."""
        print(self.texto, end="")
        sys.stdout.flush()

    def salvar(self, caminho: str) -> Path:
        """Salva o relatório formatado em arquivo.

        Args:
            caminho: Caminho do arquivo de saída.

        Returns:
            Path do arquivo salvo.
        """
        caminho_p = Path(caminho)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        caminho_p.write_text(self.texto, encoding="utf-8")
        return caminho_p.resolve()

    def salvar_json(self, caminho: str) -> Path:
        """Salva o relatório em formato JSON estruturado.

        Args:
            caminho: Caminho do arquivo JSON.

        Returns:
            Path do arquivo salvo.
        """
        dados = self.to_dict()
        caminho_p = Path(caminho)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        caminho_p.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return caminho_p.resolve()

    def to_dict(self) -> dict[str, Any]:
        """Converte relatório completo para dict."""
        # Gera breakdown por fonte
        grupos = self._agrupar_por_fonte()
        por_fonte: dict[str, dict[str, Any]] = {}
        for fonte, items in grupos.items():
            nome_exibicao = {
                "quintoandar": "QuintoAndar",
                "loft": "Loft",
                "emcasa": "EmCasa",
                "zap": "Zap Imóveis",
            }.get(fonte, fonte.capitalize())
            por_fonte[fonte] = {
                "nome_exibicao": nome_exibicao,
                "total": len(items),
                "novos": sum(1 for i in items if i.new_flag == NEW_FLAG_NOVO),
                "existentes": sum(1 for i in items if i.new_flag == NEW_FLAG_EXISTENTE),
                "exemplos": [i.to_dict() for i in sorted(items, key=_parse_preco_para_ordenacao)[:3]],
            }

        return {
            "versao": 1,
            "timestamp": self.timestamp,
            "total": self.total,
            "total_novos": self.total_novos,
            "total_existentes": self.total_existentes,
            "items": [i.to_dict() for i in self.items],
            "por_fonte": por_fonte,
        }

    def to_json(self) -> str:
        """Retorna string JSON do relatório."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _merge_portais(items: list[dict]) -> list[str]:
    """Extrai e mescla portais de uma lista de dicts de imóveis.

    Percorre os campos 'fonte' e 'portais' de cada dict,
    coletando portais únicos.
    """
    portais: set[str] = set()
    for item in items:
        fonte = str(item.get("fonte", "")).strip()
        if fonte:
            portais.add(fonte)
        extra = item.get("portais", [])
        if isinstance(extra, list):
            for p in extra:
                p_str = str(p).strip()
                if p_str:
                    portais.add(p_str)
    return sorted(portais)


def _parse_preco_para_ordenacao(item: ItemOportunidade) -> float:
    """Retorna valor numérico do preço para ordenação.

    Usa preco_venda primeiro, depois preco_aluguel.
    Itens sem preço vão para o final da ordenação (float('inf')).
    """
    if item.preco is not None and item.preco > 0:
        return item.preco
    return float("inf")


def _carregar_estado(caminho: str) -> tuple[list[dict], str]:
    """Carrega estado anterior do arquivo JSON.

    Args:
        caminho: Caminho para o arquivo de estado.

    Returns:
        (lista de dicts de imóveis, timestamp do estado).
        Se o arquivo não existir, retorna ([], "").
    """
    p = Path(caminho)
    if not p.exists():
        return [], ""

    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        imoveis = dados.get("imoveis", []) if isinstance(dados, dict) else dados
        if isinstance(dados, dict):
            ts = dados.get("timestamp", "")
        else:
            ts = ""
        # Garante que é lista de dicts
        if not isinstance(imoveis, list):
            return [], ts
        return imoveis, ts
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️  Erro ao ler estado anterior '{caminho}': {e}",
              file=sys.stderr)
        return [], ""


def _salvar_estado(
    items: list[ItemOportunidade],
    caminho: str,
) -> bool:
    """Persiste estado atual para próxima execução.

    Args:
        items: Lista de ItemOportunidade atuais.
        caminho: Caminho para salvar.

    Returns:
        True se salvou com sucesso.
    """
    try:
        p = Path(caminho)
        p.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(items),
            "imoveis": [i.to_dict() for i in items],
        }
        p.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return True
    except OSError as e:
        print(f"  ❌ Erro ao salvar estado: {e}", file=sys.stderr)
        return False


# ── Função principal ─────────────────────────────────────────────────────────


def _try_dedup(listings: list[dict]) -> list[dict]:
    """Tenta aplicar cross-portal dedup (qa_loft_dedup).

    Se o módulo não estiver disponível, retorna os listings originais
    com campo 'duplicate_ids' básico.

    Args:
        listings: Lista de dicts de imóveis (schema Imovel).

    Returns:
        Lista deduplicada (ou original se dedup não disponível).
    """
    try:
        # Tenta importar de skills/detect-duplicates (caminho do projeto)
        import importlib

        mod = None
        candidates = [
            "qa_loft_dedup",
            "detect_duplicates.qa_loft_dedup",
            "skills.detect_duplicates.qa_loft_dedup",
        ]
        for cand in candidates:
            try:
                mod = importlib.import_module(cand)
                break
            except ImportError:
                continue

        if mod is None:
            # Tenta inserir o diretório no path
            _HERE = Path(__file__).resolve().parent.parent
            dedup_dir = str(_HERE / "detect-duplicates")
            if dedup_dir not in sys.path:
                sys.path.insert(0, dedup_dir)
            mod = importlib.import_module("qa_loft_dedup")

        dedup_fn = getattr(mod, "dedup_cross_portal", None)
        if dedup_fn is None:
            return listings

        return dedup_fn(listings)

    except (ImportError, AttributeError) as e:
        print(f"  ℹ️  Dedup não disponível ({e}), usando listings originais.",
              file=sys.stderr)
        return listings


def _aplicar_dedup_com_portais(
    listings: list[dict],
) -> list[dict]:
    """Aplica dedup preservando portais antes da mesclagem.

    1. Coleta portais de cada listing ANTES do dedup.
    2. Aplica dedup_cross_portal.
    3. Merga portais dos itens agrupados.

    Args:
        listings: Lista de dicts de imóveis.

    Returns:
        Lista deduplicada, cada item com campo 'portais' (list[str]).
    """
    if not listings:
        return []

    # Coleta fontes individuais antes do dedup
    fontes_por_idx: dict[int, str] = {}
    for i, item in enumerate(listings):
        fonte = str(item.get("fonte", "")).strip()
        if fonte:
            fontes_por_idx[i] = fonte

    # Aplica dedup
    deduped = _try_dedup(listings)

    # Adiciona portais aos itens deduplicados
    for item in deduped:
        if "portais" not in item or not item["portais"]:
            # Tenta inferir do duplicate_ids
            # Como não temos rastreamento direto idx → fonte pós-dedup,
            # usamos a fonte do próprio item + fontes dos canônicos agrupados
            fonte_atual = str(item.get("fonte", "")).strip()
            item["portais"] = [fonte_atual] if fonte_atual else []
        else:
            # Garante que é lista de strings
            item["portais"] = [str(p) for p in item["portais"] if p]

    return deduped


def gerar_relatorio_oportunidades(
    listings: list[dict],
    *,
    estado_path: Optional[str] = None,
    aplicar_dedup: bool = True,
    ordenar_por: str = "preco",
    ascending: bool = True,
    saida: str = SAIDA_CONSOLE,
    arquivo_saida: Optional[str] = None,
    salvar_estado: bool = True,
) -> RelatorioOportunidades:
    """Gera relatório de novas oportunidades a partir de listings de todos os portais.

    Pipeline:
        1. (Opcional) Dedup cross-portal → imóveis únicos
        2. Carrega estado anterior (se disponível) → determina new_flag
        3. Ordena por preço ascendente
        4. Gera relatório formatado
        5. (Opcional) Salva estado para próxima execução
        6. (Opcional) Exibe/salva saída

    Args:
        listings: Lista de dicts de imóveis (schema Imovel.to_dict()).
                  Pode conter listings de múltiplos portais.
        estado_path: Caminho para arquivo JSON de estado anterior.
                     Se None, procura em data/state_snapshots/oportunidades_estado.json
                     relativo ao cwd.
        aplicar_dedup: Se True (padrão), aplica dedup cross-portal para
                       evitar duplicatas entre QuintoAndar e Loft.
        ordenar_por: Campo de ordenação. 'preco' é o único suportado.
        ascending: Se True (padrão), ordena do menor para o maior preço.
        saida: 'console' (exibe no terminal), 'arquivo' (salva),
               'ambos' (console + arquivo).
        arquivo_saida: Caminho para salvar o relatório (obrigatório se
                       saida for 'arquivo' ou 'ambos').
        salvar_estado: Se True (padrão), persiste o estado atual para
                       detecção de novidades na próxima execução.

    Returns:
        RelatorioOportunidades com items, texto formatado e metadados.

    Raises:
        ValueError: Se saida='arquivo' e arquivo_saida não for fornecido.

    Acceptance criteria:
        1. Report contém apenas propriedades únicas (dedup)
        2. Report ordenado por preço ascendente
        3. Output pode ser salvo em arquivo ou exibido via CLI
    """
    # ── Validação ──────────────────────────────────────────────────────
    if saida not in SAIDAS_VALIDAS:
        saida = SAIDA_CONSOLE
    if saida in (SAIDA_ARQUIVO, SAIDA_AMBOS) and not arquivo_saida:
        raise ValueError(
            f"arquivo_saida é obrigatório quando saida='{saida}'"
        )

    # ── 1. Dedup ───────────────────────────────────────────────────────
    if aplicar_dedup and listings:
        processed = _aplicar_dedup_com_portais(listings)
    else:
        processed = list(listings)
        # Adiciona portais básico se não existir
        for item in processed:
            if "portais" not in item or not item["portais"]:
                fonte = str(item.get("fonte", "")).strip()
                item["portais"] = [fonte] if fonte else []

    # ── 2. Carrega estado anterior ─────────────────────────────────────
    if estado_path is None:
        estado_path = str(
            Path.cwd() / "data" / "state_snapshots" / ESTADO_FILENAME
        )

    estado_anterior, _ = _carregar_estado(estado_path)
    ids_anteriores: set[str] = set()
    for item in estado_anterior:
        item_id = str(item.get("id", item.get("list_id", "")))
        if item_id:
            ids_anteriores.add(item_id)

    # ── 3. Constrói items ──────────────────────────────────────────────
    items: list[ItemOportunidade] = []
    for d in processed:
        item = ItemOportunidade.from_imovel_dict(d)

        # Portais: usa o que veio do dedup (enriquecido)
        portais = d.get("portais", [])
        if isinstance(portais, list):
            item.portais = [str(p) for p in portais if p]
        else:
            item.portais = [str(d.get("fonte", ""))] if d.get("fonte") else []

        # New flag baseada em ID
        if item.id and item.id in ids_anteriores:
            item.new_flag = NEW_FLAG_EXISTENTE
        else:
            item.new_flag = NEW_FLAG_NOVO

        items.append(item)

    # ── 4. Ordena por preço ascendente ─────────────────────────────────
    items.sort(key=_parse_preco_para_ordenacao, reverse=not ascending)

    # ── 5. Constrói relatório ──────────────────────────────────────────
    relatorio = RelatorioOportunidades(items=items)

    # ── 6. Saída ───────────────────────────────────────────────────────
    if saida in (SAIDA_CONSOLE, SAIDA_AMBOS):
        relatorio.exibir()

    if saida in (SAIDA_ARQUIVO, SAIDA_AMBOS) and arquivo_saida:
        path_escrito = relatorio.salvar(arquivo_saida)
        print(f"  📄 Relatório salvo em: {path_escrito}", file=sys.stdout)

        # Também salva JSON
        json_path = str(path_escrito.with_suffix(".json"))
        relatorio.salvar_json(json_path)
        print(f"  📄 Dados JSON salvos em: {json_path}", file=sys.stdout)

    # ── 7. Salva estado para próxima execução ──────────────────────────
    if salvar_estado:
        _salvar_estado(items, estado_path)

    return relatorio
