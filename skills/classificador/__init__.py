"""classificador — Classificação de mudanças em imóveis a partir de um DiffResult.

A partir do diff gerado por diff_imoveis(), classifica cada mudança
em categorias semânticas: 'new', 'removed', 'price_decrease',
'price_increase', 'status_change'.

Uso:
    from classificador import classificar_mudancas, MudancaEvento

    eventos = classificar_mudancas(diff_result)
    for ev in eventos:
        print(f"{ev.tipo}: {ev.id_imovel}")
"""

from .classificador import (
    CAMPOS_PRECO,
    CAMPOS_STATUS,
    MudancaEvento,
    classificar_mudancas,
)

__all__ = [
    "CAMPOS_PRECO",
    "CAMPOS_STATUS",
    "MudancaEvento",
    "classificar_mudancas",
]
