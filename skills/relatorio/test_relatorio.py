"""
Testes para relatorio — geração de relatórios de mudanças detectadas.

Uso:
    cd /home/higor/imoveis-watchdog
    PYTHONPATH="$HOME/.hermes:skills:skills/diff:skills/classificador:skills/relatorio" python3 -m pytest \
        skills/relatorio/test_relatorio.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Adiciona caminhos para importar imovel_schema e os módulos do projeto
_HOME = Path.home()
sys.path.insert(0, str(_HOME / ".hermes"))                                    # imovel_schema
sys.path.insert(0, str(_HOME / "imoveis-watchdog" / "skills"))                # diff/ do projeto
sys.path.insert(0, str(_HOME / "imoveis-watchdog" / "skills" / "classificador"))  # classificador

from imovel_schema import Imovel

from diff.diff_imoveis import diff_imoveis, DiffResult
from classificador import classificar_mudancas, MudancaEvento
from relatorio import (
    Contagens,
    contar_tipos,
    gerar_relatorio_console,
    gerar_relatorio_json,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def imovel_a() -> Imovel:
    return Imovel(
        id="apto_001",
        titulo="Apto 2q Consolação",
        url="https://exemplo.com/apto_001",
        fonte="quintoandar",
        bairro="Consolação",
        cidade="São Paulo",
        uf="SP",
        preco_venda=450000.0,
        condominio=800.0,
        area=55.0,
        quartos=2,
        data_coleta="2026-06-21T10:00:00Z",
    )


@pytest.fixture
def imovel_b() -> Imovel:
    return Imovel(
        id="apto_002",
        titulo="Kitnet Liberdade",
        url="https://exemplo.com/apto_002",
        fonte="quintoandar",
        bairro="Liberdade",
        cidade="São Paulo",
        uf="SP",
        preco_aluguel=2500.0,
        area=30.0,
        quartos=1,
        data_coleta="2026-06-21T10:00:00Z",
    )


@pytest.fixture
def imovel_c() -> Imovel:
    return Imovel(
        id="apto_003",
        titulo="Cobertura Jardins",
        url="https://exemplo.com/apto_003",
        fonte="quintoandar",
        bairro="Jardins",
        cidade="São Paulo",
        uf="SP",
        preco_venda=1200000.0,
        condominio=2500.0,
        area=120.0,
        quartos=3,
        data_coleta="2026-06-21T10:00:00Z",
    )


@pytest.fixture
def imovel_a_alterado() -> Imovel:
    """Imovel A com preco_venda reduzido e status alterado."""
    return Imovel(
        id="apto_001",
        titulo="Apto 2q Consolação",
        url="https://exemplo.com/apto_001",
        fonte="quintoandar",
        bairro="Consolação",
        cidade="São Paulo",
        uf="SP",
        preco_venda=420000.0,  # redução: 450k → 420k
        condominio=800.0,
        area=55.0,
        quartos=2,
        status="inativo",      # mudança de status
        disponivel=False,      # mudança de disponibilidade
        data_coleta="2026-06-21T14:00:00Z",
    )


@pytest.fixture
def eventos_completos(
    imovel_a: Imovel,
    imovel_b: Imovel,
    imovel_c: Imovel,
    imovel_a_alterado: Imovel,
) -> list[MudancaEvento]:
    """Cenário completo: 1 novo + 1 removido + alterações no apto_001."""
    diff = diff_imoveis(
        anterior=[imovel_a, imovel_c],     # antes: A e C
        atual=[imovel_b, imovel_a_alterado],  # depois: B e A (alterado)
    )
    return classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")


@pytest.fixture
def eventos_vazios() -> list[MudancaEvento]:
    """Nenhum evento."""
    return []


@pytest.fixture
def apenas_novos(imovel_a: Imovel) -> list[MudancaEvento]:
    """Apenas 1 imóvel novo."""
    diff = diff_imoveis(
        anterior=[],
        atual=[imovel_a],
    )
    return classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")


# ── Testes: Contagens ─────────────────────────────────────────────────────────


class TestContarTipos:
    """Testa a função contar_tipos."""

    def test_contagens_cenario_completo(self, eventos_completos: list[MudancaEvento]):
        cont = contar_tipos(eventos_completos)
        # C: removido, B: novo, A: price_decrease (preco_venda) + status_change (disponivel) + status_change (status)
        assert cont.novos == 1       # apto_002
        assert cont.removidos == 1   # apto_003
        assert cont.price_decrease == 1  # preco_venda: 450k → 420k
        assert cont.price_increase == 0
        assert cont.status_change == 2   # disponivel + status
        assert cont.total == 5

    def test_vazio(self, eventos_vazios: list[MudancaEvento]):
        cont = contar_tipos(eventos_vazios)
        assert cont.novos == 0
        assert cont.removidos == 0
        assert cont.price_decrease == 0
        assert cont.price_increase == 0
        assert cont.status_change == 0
        assert cont.total == 0

    def test_apenas_novos(self, apenas_novos: list[MudancaEvento]):
        cont = contar_tipos(apenas_novos)
        assert cont.novos == 1
        assert cont.total == 1

    def test_contagens_to_dict(self, eventos_completos: list[MudancaEvento]):
        cont = contar_tipos(eventos_completos)
        d = cont.to_dict()
        assert d["novos"] == 1
        assert d["total"] == 5
        assert "price_decrease" in d


# ── Testes: Relatório Console ─────────────────────────────────────────────────


class TestRelatorioConsole:
    """Testa a geração de relatório em formato console."""

    def test_summary_vazio(self, eventos_vazios: list[MudancaEvento]):
        saida = gerar_relatorio_console(eventos_vazios, formato="summary")
        assert "Novos:" in saida
        assert "Removidos:" in saida
        assert "Total: 0" in saida
        assert "0" in saida

    def test_summary_com_eventos(self, eventos_completos: list[MudancaEvento]):
        saida = gerar_relatorio_console(eventos_completos, formato="summary")
        assert "Novos:            1" in saida
        assert "Removidos:        1" in saida
        assert "Redução de Preço: 1" in saida
        assert "Aumento de Preço:  0" in saida
        assert "Mudança de Status: 2" in saida
        assert "Alteração de Caract: 0" in saida
        assert "Total: 5" in saida
        # Modo summary NÃO deve ter detalhamento
        assert "Apto 2q Consolação" not in saida
        assert "apto_001" not in saida

    def test_detailed_com_eventos(self, eventos_completos: list[MudancaEvento]):
        saida = gerar_relatorio_console(eventos_completos, formato="detailed")
        # Deve ter contagens
        assert "Novos:            1" in saida
        assert "Total: 5" in saida
        # Deve ter detalhamento por seção
        assert "── Novos (1)" in saida
        assert "── Removidos (1)" in saida
        assert "── Redução de Preço (1)" in saida
        assert "── Mudança de Status (2)" in saida
        # IDs devem aparecer
        assert "apto_001" in saida
        assert "apto_002" in saida
        assert "apto_003" in saida
        # Timestamp deve aparecer (do imóvel do primeiro evento)
        assert "Coleta: 2026-06-21T10:00:00Z" in saida

    def test_detailed_com_lookup(self, eventos_completos: list[MudancaEvento], imovel_a: Imovel):
        """Lookup callback enriquece eventos de alteração com título/preço."""
        lookup = {"apto_001": imovel_a.to_dict()}.get

        saida = gerar_relatorio_console(
            eventos_completos,
            formato="detailed",
            lookup_imovel=lookup,
        )
        # Evento de redução de preço deve mostrar título
        assert "Apto 2q Consolação" in saida
        assert "Venda: R$ 450.000 → R$ 420.000" in saida
        # URL deve aparecer
        assert "https://exemplo.com/apto_001" in saida

    def test_apenas_novos(self, apenas_novos: list[MudancaEvento]):
        saida = gerar_relatorio_console(apenas_novos, formato="detailed")
        assert "Novos:            1" in saida
        assert "── Novos (1)" in saida
        assert "── Aumento de Preço" not in saida  # não deve ter seção vazia
        assert "── Redução de Preço" not in saida
        assert "── Mudança de Status" not in saida

    def test_novo_com_cond_iptu(self, imovel_a: Imovel):
        """Imóvel novo com condomínio e IPTU deve exibir no console."""
        diff = diff_imoveis([], [imovel_a])
        eventos = classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")
        saida = gerar_relatorio_console(eventos, formato="detailed")
        assert "Cond. R$ 800" in saida
        assert "IPTU N/I" not in saida  # imovel_a não tem iptu (None)
        assert "R$ 450.000" in saida

    def test_novo_com_cond_iptu_ambos(self):
        """Imóvel novo com condomínio E IPTU deve exibir ambos."""
        imovel = Imovel(
            id="apto_completo",
            titulo="Apto Completo",
            fonte="emcasa",
            bairro="Centro",
            preco_venda=350000.0,
            condominio=600.0,
            iptu=150.0,
            data_coleta="2026-06-21T14:00:00Z",
        )
        diff = diff_imoveis([], [imovel])
        eventos = classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")
        saida = gerar_relatorio_console(eventos, formato="detailed")
        assert "Cond. R$ 600" in saida
        assert "IPTU R$ 150" in saida

    def test_novo_sem_cond_iptu_nao_exibe(self):
        """Imóvel novo sem condomínio/IPTU não deve mostrar esses campos."""
        imovel = Imovel(
            id="apto_simples",
            titulo="Apto Simples",
            fonte="emcasa",
            bairro="Centro",
            preco_venda=200000.0,
            data_coleta="2026-06-21T14:00:00Z",
        )
        diff = diff_imoveis([], [imovel])
        eventos = classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")
        saida = gerar_relatorio_console(eventos, formato="detailed")
        assert "Cond." not in saida
        assert "IPTU" not in saida

    def test_titulo_personalizado(self, eventos_vazios: list[MudancaEvento]):
        saida = gerar_relatorio_console(eventos_vazios, formato="summary", titulo="Meu Relatório")
        assert "=== Meu Relatório ===" in saida

    def test_formato_invalido_fallback(self, eventos_completos: list[MudancaEvento]):
        """Formato inválido deve cair como detailed."""
        saida = gerar_relatorio_console(eventos_completos, formato="invalid")
        assert "── Novos (1)" in saida


# ── Testes: Relatório JSON ────────────────────────────────────────────────────


class TestRelatorioJSON:
    """Testa a geração de relatório em formato JSON."""

    def test_summary_vazio(self, eventos_vazios: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_vazios, formato="summary")
        assert rel["versao"] == 1
        assert rel["formato"] == "summary"
        assert rel["resumo"]["total"] == 0
        assert "eventos" not in rel

    def test_summary_com_eventos(self, eventos_completos: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_completos, formato="summary")
        assert rel["resumo"]["novos"] == 1
        assert rel["resumo"]["price_decrease"] == 1
        assert rel["resumo"]["total"] == 5
        # Summary não deve incluir eventos individuais
        assert "eventos" not in rel

    def test_detailed_tem_eventos(self, eventos_completos: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_completos, formato="detailed")
        assert rel["formato"] == "detailed"
        assert len(rel["eventos"]) == 5
        assert rel["resumo"]["novos"] == 1

    def test_detailed_evento_new(self, eventos_completos: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_completos, formato="detailed")
        novos = [e for e in rel["eventos"] if e["tipo"] == "new"]
        assert len(novos) == 1
        ev = novos[0]
        assert ev["id_imovel"] == "apto_002"
        assert "imovel" in ev
        assert ev["imovel"]["titulo"] == "Kitnet Liberdade"

    def test_detailed_evento_removed(self, eventos_completos: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_completos, formato="detailed")
        removidos = [e for e in rel["eventos"] if e["tipo"] == "removed"]
        assert len(removidos) == 1
        ev = removidos[0]
        assert ev["id_imovel"] == "apto_003"
        assert "imovel" in ev

    def test_detailed_evento_price_decrease(self, eventos_completos: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_completos, formato="detailed")
        decreases = [e for e in rel["eventos"] if e["tipo"] == "price_decrease"]
        assert len(decreases) == 1
        ev = decreases[0]
        assert ev["id_imovel"] == "apto_001"
        assert ev["campo"] == "preco_venda"
        assert ev["valor_anterior"] == 450000.0
        assert ev["valor_novo"] == 420000.0

    def test_detailed_com_lookup(self, eventos_completos: list[MudancaEvento], imovel_a: Imovel):
        """Lookup callback enriquece eventos de alteração no JSON."""
        lookup = {"apto_001": imovel_a.to_dict()}.get
        rel = gerar_relatorio_json(eventos_completos, formato="detailed", lookup_imovel=lookup)

        decreases = [e for e in rel["eventos"] if e["tipo"] == "price_decrease"]
        ev = decreases[0]
        assert ev["imovel"]["titulo"] == "Apto 2q Consolação"
        assert ev["imovel"]["url"] == "https://exemplo.com/apto_001"

    def test_detailed_eh_serializavel(self, eventos_completos: list[MudancaEvento]):
        """O JSON gerado deve ser serializável sem erros."""
        rel = gerar_relatorio_json(eventos_completos, formato="detailed")
        json_str = json.dumps(rel, ensure_ascii=False, default=str)
        parsed = json.loads(json_str)
        assert parsed["resumo"]["total"] == 5

    def test_detailed_json_inclui_condominio(self, imovel_a: Imovel):
        """JSON detailed com condomínio deve incluir o campo."""
        diff = diff_imoveis([], [imovel_a])
        eventos = classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")
        rel = gerar_relatorio_json(eventos, formato="detailed")
        assert len(rel["eventos"]) == 1
        ev = rel["eventos"][0]
        assert ev["imovel"]["condominio"] == 800.0
        assert ev["imovel"]["iptu"] is None  # imovel_a não tem IPTU

    def test_detailed_json_inclui_cond_iptu_ambos(self):
        """JSON detailed deve incluir condominio e iptu quando presentes."""
        imovel = Imovel(
            id="apto_completo",
            titulo="Apto Completo",
            fonte="emcasa",
            bairro="Centro",
            preco_venda=350000.0,
            condominio=600.0,
            iptu=150.0,
            data_coleta="2026-06-21T14:00:00Z",
        )
        diff = diff_imoveis([], [imovel])
        eventos = classificar_mudancas(diff, timestamp="2026-06-21T14:00:00Z")
        rel = gerar_relatorio_json(eventos, formato="detailed")
        ev = rel["eventos"][0]
        assert ev["imovel"]["condominio"] == 600.0
        assert ev["imovel"]["iptu"] == 150.0

    def test_formato_invalido_fallback(self, eventos_completos: list[MudancaEvento]):
        rel = gerar_relatorio_json(eventos_completos, formato="invalid")
        assert "eventos" in rel  # fallback = detailed
