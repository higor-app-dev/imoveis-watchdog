"""relatorio — Geração de relatórios de mudanças detectadas e oportunidades."""

from .relatorio import (
    Contagens,
    gerar_relatorio_console,
    gerar_relatorio_json,
    contar_tipos,
)
from .oportunidades import (
    ItemOportunidade,
    RelatorioOportunidades,
    gerar_relatorio_oportunidades,
)

__all__ = [
    "Contagens",
    "gerar_relatorio_console",
    "gerar_relatorio_json",
    "contar_tipos",
    "ItemOportunidade",
    "RelatorioOportunidades",
    "gerar_relatorio_oportunidades",
]
