"""
validacao — Validação em lote de imóveis para o Watchdog.

Oferece:
  - validar_imovel(imovel)       → valida um único Imovel, retorna lista de erros
  - validar_lote(imoveis)        → valida uma lista, retorna relatório estruturado
  - relatorio_resumido(lote)     → sumário legível para logs/notificações

Integração:
    from validacao import validar_lote, relatorio_resumido

    imoveis = from_quintoandar_payload(data)
    lote = validar_lote(imoveis)
    print(relatorio_resumido(lote))
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel


# ── Tipos de saída ──────────────────────────────────────────────────────────────


@dataclass
class ResultadoValidacao:
    """Resultado da validação de um único Imovel."""

    indice: int
    """Índice do imóvel na lista original."""

    imovel: dict[str, Any]
    """Representação do imóvel (to_dict()) para referência."""

    valido: bool
    """True se passou em todas as regras."""

    erros: list[str] = field(default_factory=list)
    """Lista de mensagens de erro (vazia se válido)."""


@dataclass
class RelatorioValidacao:
    """Relatório completo de uma validação em lote."""

    total: int
    """Total de imóveis processados."""

    validos: int
    """Quantos passaram sem erros."""

    invalidos: int
    """Quantos têm pelo menos um erro."""

    resultados: list[ResultadoValidacao] = field(default_factory=list)
    """Resultados individuais, na ordem original."""


# ── Funções principais ──────────────────────────────────────────────────────────


def validar_imovel(imovel: Imovel, indice: int = 0) -> ResultadoValidacao:
    """
    Valida um único Imovel contra todas as regras do schema.

    Args:
        imovel: Instância de Imovel.
        indice: Índice na lista original (para rastreio).

    Returns:
        ResultadoValidacao com erros (vazio se OK).
    """
    erros = imovel.validate()
    return ResultadoValidacao(
        indice=indice,
        imovel=imovel.to_dict(),
        valido=len(erros) == 0,
        erros=erros,
    )


def validar_lote(imoveis: list[Imovel]) -> RelatorioValidacao:
    """
    Valida uma lista de Imovel e retorna relatório completo.

    Args:
        imoveis: Lista de Imovel a validar.

    Returns:
        RelatorioValidacao com total, contagem e resultados individuais.
    """
    if not imoveis:
        return RelatorioValidacao(total=0, validos=0, invalidos=0, resultados=[])

    resultados: list[ResultadoValidacao] = []
    validos = 0
    invalidos = 0

    for i, imovel in enumerate(imoveis):
        r = validar_imovel(imovel, indice=i)
        resultados.append(r)
        if r.valido:
            validos += 1
        else:
            invalidos += 1

    return RelatorioValidacao(
        total=len(imoveis),
        validos=validos,
        invalidos=invalidos,
        resultados=resultados,
    )


# ── Utilitários de saída ────────────────────────────────────────────────────────


def relatorio_resumido(relatorio: RelatorioValidacao) -> str:
    """
    Gera string legível com resumo do relatório.

    Args:
        relatorio: RelatorioValidacao de validar_lote().

    Returns:
        String formatada para console/log.
    """
    if relatorio.total == 0:
        return "📋 Nenhum imóvel para validar."

    linhas = [
        f"📋 Validação: {relatorio.total} imóveis",
        f"   ✅ {relatorio.validos} válidos",
        f"   ❌ {relatorio.invalidos} inválidos",
    ]

    if relatorio.invalidos > 0:
        linhas.append("")
        linhas.append("   Detalhes dos inválidos:")
        for r in relatorio.resultados:
            if not r.valido:
                imv = r.imovel
                ident = imv.get("id") or imv.get("titulo") or f"#{r.indice}"
                for err in r.erros:
                    linhas.append(f"     - [{ident}] {err}")

    return "\n".join(linhas)


def relatorio_json(relatorio: RelatorioValidacao) -> dict[str, Any]:
    """
    Retorna o relatório como dict serializável (JSON-safe).

    Args:
        relatorio: RelatorioValidacao de validar_lote().

    Returns:
        Dict com total, validos, invalidos e lista de resultados.
    """
    return {
        "total": relatorio.total,
        "validos": relatorio.validos,
        "invalidos": relatorio.invalidos,
        "resultados": [
            {
                "indice": r.indice,
                "id": r.imovel.get("id", ""),
                "valido": r.valido,
                "erros": r.erros,
            }
            for r in relatorio.resultados
        ],
    }


# ── Main (CLI) ──────────────────────────────────────────────────────────────────


def main():
    """
    CLI: valida um JSON de imóveis (output do parser) e exibe relatório.

    Uso:
        python validacao.py data/resultado.json
        python validacao.py data/resultado.json --json   # saída JSON
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Valida arquivo JSON de imóveis contra o schema unificado."
    )
    parser.add_argument("input", help="Arquivo JSON com lista de imóveis")
    parser.add_argument("--json", action="store_true", help="Saída em JSON")
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Erro ao ler '{args.input}': {e}", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, dict):
        data = [data]

    imoveis = [Imovel.from_dict(item) for item in data]
    relatorio = validar_lote(imoveis)

    if args.json:
        import json as _json
        print(_json.dumps(relatorio_json(relatorio), ensure_ascii=False, indent=2))
    else:
        print(relatorio_resumido(relatorio))

    sys.exit(0 if relatorio.invalidos == 0 else 1)


if __name__ == "__main__":
    main()
