"""
diff_imoveis — Diferença estruturada entre duas listas de imóveis.

Compara duas listas de 'Imovel' (atual e anterior) e retorna um diff
identificando por 'id' o que mudou: novos, removidos e alterados.

Funções 100% puras (sem I/O, sem side effects). Única dependência é a
dataclass Imovel (do schema unificado em ~/.hermes/imovel_schema.py).

Uso:
    from diff_imoveis import diff_imoveis, DiffResult

    resultado = diff_imoveis(anterior, atual)
    print(resultado.novos)       # list[Imovel]
    print(resultado.removidos)   # list[Imovel]
    print(resultado.alterados)   # list[Alteracao]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from imovel_schema import Imovel


# ── Campos monitorados para detecção de mudança ──────────────────────────────

# Ordem: preços primeiro, depois características, depois metadados relevantes.
CAMPOS_MONITORADOS: tuple[str, ...] = (
    "preco_venda",
    "preco_aluguel",
    "condominio",
    "iptu",
    "area",
    "quartos",
    "banheiros",
    "vagas",
    "titulo",
    "url",
    "tipo",
    "endereco",
    "bairro",
    "uf",
    "disponivel",
    "status",
    "amenities",
)


# ── Tipos de retorno ──────────────────────────────────────────────────────────


@dataclass
class AlteracaoCampo:
    """Mudança em um campo específico de um imóvel."""

    campo: str
    """Nome do campo que mudou."""

    valor_anterior: Any
    """Valor antes da mudança."""

    valor_novo: Any
    """Valor depois da mudança."""


@dataclass
class Alteracao:
    """Conjunto completo de mudanças em um único imóvel que existe em ambas as listas."""

    id: str
    """ID do imóvel (mesmo em anterior e atual)."""

    anterior: Imovel
    """Estado anterior do imóvel."""

    atual: Imovel
    """Estado atual do imóvel."""

    campos_alterados: list[AlteracaoCampo] = field(default_factory=list)
    """Lista de campos que efetivamente mudaram."""

    @property
    def resumo(self) -> str:
        """Resumo legível das mudanças, ex.: 'preco_venda: 450000 → 420000'."""
        partes = [f"{c.campo}: {_fmt_val(c.valor_anterior)} → {_fmt_val(c.valor_novo)}"
                   for c in self.campos_alterados]
        return f"[{self.id}] " + ", ".join(partes)


@dataclass
class DiffResult:
    """
    Resultado completo da comparação entre duas listas de imóveis.

    Attributes:
        novos: Imóveis presentes na lista 'atual' mas não na 'anterior'.
        removidos: Imóveis presentes na lista 'anterior' mas não na 'atual'.
        alterados: Imóveis em comum que tiveram ao menos um campo alterado.
        total_anterior: Total de imóveis na lista anterior.
        total_atual: Total de imóveis na lista atual.
        mesmo_total: True se len(anterior) == len(atual).
    """

    novos: list[Imovel] = field(default_factory=list)
    removidos: list[Imovel] = field(default_factory=list)
    alterados: list[Alteração] = field(default_factory=list)
    total_anterior: int = 0
    total_atual: int = 0

    # ── Propriedades derivadas ────────────────────────────────────────────────

    @property
    def mesmo_total(self) -> bool:
        """True se os totais são iguais (não garante mesmos itens)."""
        return self.total_anterior == self.total_atual

    @property
    def tem_mudancas(self) -> bool:
        """True se houver qualquer mudança (novos, removidos ou alterados)."""
        return bool(self.novos or self.removidos or self.alterados)

    @property
    def total_novos(self) -> int:
        return len(self.novos)

    @property
    def total_removidos(self) -> int:
        return len(self.removidos)

    @property
    def total_alterados(self) -> int:
        return len(self.alterados)

    # ── Serialização ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """
        Converte o resultado para dict serializável (JSON-safe).

        Útil para logging, persistência ou envio em APIs.
        """
        return {
            "novos": [i.to_dict() for i in self.novos],
            "removidos": [i.to_dict() for i in self.removidos],
            "alterados": [
                {
                    "id": a.id,
                    "anterior": a.anterior.to_dict(),
                    "atual": a.atual.to_dict(),
                    "campos_alterados": [
                        {
                            "campo": c.campo,
                            "valor_anterior": c.valor_anterior,
                            "valor_novo": c.valor_novo,
                        }
                        for c in a.campos_alterados
                    ],
                }
                for a in self.alterados
            ],
            "total_anterior": self.total_anterior,
            "total_atual": self.total_atual,
        }

    def to_json(self) -> str:
        """Retorna string JSON compacta do diff."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def resumo_curto(self) -> str:
        """Resumo de uma linha para notificações rápidas."""
        parts = []
        if self.novos:
            parts.append(f"{self.total_novos} novo(s)")
        if self.removidos:
            parts.append(f"{self.total_removidos} removido(s)")
        if self.alterados:
            parts.append(f"{self.total_alterados} alterado(s)")
        if not parts:
            return "Sem mudanças"
        return ", ".join(parts)

    def __str__(self) -> str:
        return (
            f"DiffResult("
            f"novos={self.total_novos}, "
            f"removidos={self.total_removidos}, "
            f"alterados={self.total_alterados}, "
            f"anterior={self.total_anterior}, "
            f"atual={self.total_atual})"
        )

    def __bool__(self) -> bool:
        """bool(resultado) é True se houver mudanças."""
        return self.tem_mudancas


# ── Função principal ──────────────────────────────────────────────────────────


def diff_imoveis(
    anterior: list[Imovel],
    atual: list[Imovel],
    *,
    campos: Optional[tuple[str, ...]] = None,
) -> DiffResult:
    """
    Compara duas listas de 'Imovel' e retorna um 'DiffResult' estruturado.

    A identificação é feita pelo campo 'id' de cada Imovel. Imóveis com
    'id' vazio são ignorados no diff (não entram em nenhuma lista).

    Args:
        anterior: Lista de imóveis da execução anterior.
        atual: Lista de imóveis da execução atual.
        campos: Tupla opcional com campos a monitorar. Padrão: CAMPOS_MONITORADOS.

    Returns:
        DiffResult com novos, removidos e alterados.
    """
    if campos is None:
        campos = CAMPOS_MONITORADOS

    # Filtra imóveis sem ID (não comparáveis)
    anteriores = {i.id: i for i in anterior if i.id}
    atuais = {i.id: i for i in atual if i.id}

    ids_anteriores = set(anteriores.keys())
    ids_atuais = set(atuais.keys())

    # — Novos: IDs que estão em 'atual' mas não em 'anterior' —
    novos_ids = ids_atuais - ids_anteriores
    novos = [atuais[i] for i in sorted(novos_ids)]

    # — Removidos: IDs que estão em 'anterior' mas não em 'atual' —
    removidos_ids = ids_anteriores - ids_atuais
    removidos = [anteriores[i] for i in sorted(removidos_ids)]

    # — Alterados: IDs em comum com pelo menos um campo diferente —
    comuns_ids = ids_anteriores & ids_atuais
    alterados: list[Alteração] = []

    for i in sorted(comuns_ids):
        old = anteriores[i]
        new = atuais[i]
        alteracoes = _comparar_campos(old, new, campos)
        if alteracoes:
            alterados.append(
                Alteracao(
                    id=i,
                    anterior=old,
                    atual=new,
                    campos_alterados=alteracoes,
                )
            )

    return DiffResult(
        novos=novos,
        removidos=removidos,
        alterados=alterados,
        total_anterior=len(anterior),
        total_atual=len(atual),
    )


# ── Funções auxiliares ────────────────────────────────────────────────────────


def _comparar_campos(
    old: Imovel,
    new: Imovel,
    campos: tuple[str, ...],
) -> list[AlteracaoCampo]:
    """
    Compara dois Imovel campo a campo e retorna lista de diferenças.

    Args:
        old: Versão anterior do imóvel.
        new: Versão atual do imóvel.
        campos: Campos a verificar.

    Returns:
        Lista de AlteracaoCampo com as diferenças encontradas.
        Vazia se todos os campos monitorados forem iguais.
    """
    alteracoes: list[AlteracaoCampo] = []

    for campo in campos:
        # Só compara campos que existem na dataclass
        if not hasattr(old, campo) or not hasattr(new, campo):
            continue

        val_old = getattr(old, campo)
        val_new = getattr(new, campo)

        if not _valores_diferentes(val_old, val_new):
            continue

        alteracoes.append(
            AlteracaoCampo(
                campo=campo,
                valor_anterior=val_old,
                valor_novo=val_new,
            )
        )

    return alteracoes


def _valores_diferentes(a: Any, b: Any) -> bool:
    """
    Verifica se dois valores são efetivamente diferentes.

    Considerações:
    - None vs None → iguais (ambos não informados)
    - None vs 0 ou 0 vs None → diferentes (um foi informado/preenchido)
    - float/int: compara com tolerância de centavos (1e-2) para evitar
      falsos positivos por ponto flutuante
    - listas: compara ordenadamente (ignora ordem não importa para
      amenities/fotos nesse contexto, mas ordem pode mudar sem
      significado real — usamos set para amenities, lista para fotos)
    - str: case-sensitive
    """
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True

    # Python trata bool como int (False==0, True==1): força separação
    if isinstance(a, bool) != isinstance(b, bool):
        return True

    if isinstance(a, float) and isinstance(b, (float, int)):
        return abs(a - float(b)) > 1e-2  # tolerância de centavos
    if isinstance(a, (int, float)) and isinstance(b, float):
        return abs(float(a) - b) > 1e-2

    # Listas: compara como sets para amenities, ordenada para fotos
    if isinstance(a, list) and isinstance(b, list):
        if a and b and all(isinstance(x, str) for x in a + b):
            # Strings → compara como set (ordem não importa)
            return set(a) != set(b)
        return a != b

    return a != b


def _fmt_val(val: Any) -> str:
    """Formata valor para exibição em resumo."""
    if val is None:
        return "N/I"
    if isinstance(val, float):
        if val >= 1000:
            return f"R$ {val:,.0f}".replace(",", ".")
        return f"{val:.2f}"
    if isinstance(val, list):
        if not val:
            return "[]"
        if len(val) <= 3:
            return ", ".join(val)
        return f"{len(val)} itens"
    return str(val)


# ── Funções auxiliares de conveniência ────────────────────────────────────────


def diff_por_fonte(resultado: DiffResult) -> dict[str, dict[str, Any]]:
    """
    Agrupa as mudanças por fonte (fonte do imóvel).

    Útil para notificações segmentadas por portal.

    Args:
        resultado: DiffResult completo.

    Returns:
        Dict com chave = nome da fonte, valor = dict com novos/removidos/alterados.
    """
    grupos: dict[str, dict[str, list]] = {}

    for imovel in resultado.novos:
        f = imovel.fonte or "desconhecida"
        grupos.setdefault(f, {"novos": [], "removidos": [], "alterados": []})
        grupos[f]["novos"].append(imovel)

    for imovel in resultado.removidos:
        f = imovel.fonte or "desconhecida"
        grupos.setdefault(f, {"novos": [], "removidos": [], "alterados": []})
        grupos[f]["removidos"].append(imovel)

    for alteracao in resultado.alterados:
        f = alteracao.atual.fonte or "desconhecida"
        grupos.setdefault(f, {"novos": [], "removidos": [], "alterados": []})
        grupos[f]["alterados"].append(alteracao)

    return grupos
