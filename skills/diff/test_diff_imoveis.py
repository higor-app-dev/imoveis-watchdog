"""
Testes para diff_imoveis — lógica de diff entre duas listas de imóveis.

Uso:
    cd /home/higor/imoveis-watchdog
    PYTHONPATH="$HOME/.hermes:skills:skills/quinto-andar" python3 -m pytest skills/diff/test_diff_imoveis.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Adiciona caminhos para importar imovel_schema e o módulo sob teste
_HERE = Path(__file__).resolve().parent
_SKILLS = _HERE.parent
_PROJECT = _SKILLS.parent
sys.path.insert(0, str(Path.home() / ".hermes"))         # imovel_schema
sys.path.insert(0, str(_SKILLS))                         # diff
sys.path.insert(0, str(_SKILLS / "quinto-andar"))        # validacao etc.

from imovel_schema import Imovel

from diff.diff_imoveis import (
    Alteracao,
    AlteracaoCampo,
    CAMPOS_MONITORADOS,
    DiffResult,
    _comparar_campos,
    _fmt_val,
    _valores_diferentes,
    diff_imoveis,
    diff_por_fonte,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def imovel_a() -> Imovel:
    return Imovel(
        id="a1",
        titulo="Apto 2q Consolação",
        url="https://olx.com.br/a1",
        fonte="olx",
        bairro="Consolação",
        cidade="São Paulo",
        uf="SP",
        preco_venda=450000.0,
        area=55.0,
        quartos=2,
        tipo="apartamento",
    )


@pytest.fixture
def imovel_b() -> Imovel:
    return Imovel(
        id="a2",
        titulo="Kitnet Pinheiros",
        url="https://olx.com.br/a2",
        fonte="olx",
        bairro="Pinheiros",
        cidade="São Paulo",
        uf="SP",
        preco_aluguel=1800.0,
        condominio=400.0,
        area=28.0,
        tipo="kitnet",
    )


@pytest.fixture
def imovel_c() -> Imovel:
    return Imovel(
        id="a3",
        titulo="Casa 3q Vila Mariana",
        url="https://olx.com.br/a3",
        fonte="olx",
        bairro="Vila Mariana",
        cidade="São Paulo",
        uf="SP",
        preco_venda=550000.0,
        area=120.0,
        quartos=3,
        banheiros=2,
        vagas=2,
        tipo="casa",
    )


# ── Testes: _valores_diferentes ───────────────────────────────────────────────


class TestValoresDiferentes:
    """Testa a lógica de comparação de valores."""

    def test_ambos_none_sao_iguais(self):
        assert not _valores_diferentes(None, None)

    def test_none_vs_valor_sao_diferentes(self):
        assert _valores_diferentes(None, 50000.0)
        assert _valores_diferentes(50000.0, None)

    def test_float_diferente_acima_tolerancia(self):
        assert _valores_diferentes(100.0, 101.0)

    def test_float_igual_dentro_tolerancia(self):
        assert not _valores_diferentes(100.0, 100.001)  # dentro de 1e-2
        assert not _valores_diferentes(100.001, 100.0)

    def test_float_exato(self):
        assert not _valores_diferentes(100.0, 100.0)

    def test_int_float_mesmo_valor(self):
        assert not _valores_diferentes(100, 100.0)
        assert not _valores_diferentes(100.0, 100)

    def test_int_float_diferente(self):
        assert _valores_diferentes(100, 101.0)

    def test_strings_diferentes(self):
        assert _valores_diferentes("abc", "def")

    def test_strings_iguais(self):
        assert not _valores_diferentes("abc", "abc")

    def test_listas_strings_ordem_diferente(self):
        """Listas de strings comparam como set — ordem não importa."""
        assert not _valores_diferentes(
            ["piscina", "academia"], ["academia", "piscina"]
        )

    def test_listas_strings_conteudo_diferente(self):
        assert _valores_diferentes(
            ["piscina", "academia"], ["piscina"]
        )

    def test_listas_mistas_ordem_importa(self):
        """Listas não-string comparam ordenadamente."""
        assert not _valores_diferentes([1, 2, 3], [1, 2, 3])
        assert _valores_diferentes([1, 2], [2, 1])

    def test_listas_vazias_iguais(self):
        assert not _valores_diferentes([], [])

    def test_tipos_diferentes(self):
        assert _valores_diferentes("450000", 450000)

    def test_zero_vs_false(self):
        assert _valores_diferentes(0, False)  # tipos diferentes


# ── Testes: _comparar_campos ──────────────────────────────────────────────────


class TestCompararCampos:
    """Testa a comparação campo a campo entre dois Imovel."""

    def test_sem_diferencas(self, imovel_a):
        clone = Imovel.from_dict(imovel_a.to_dict())
        diffs = _comparar_campos(imovel_a, clone, CAMPOS_MONITORADOS)
        assert diffs == []

    def test_preco_mudou(self, imovel_a):
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 420000.0
        diffs = _comparar_campos(imovel_a, novo, CAMPOS_MONITORADOS)
        assert len(diffs) == 1
        assert diffs[0].campo == "preco_venda"
        assert diffs[0].valor_anterior == 450000.0
        assert diffs[0].valor_novo == 420000.0

    def test_multiplos_campos_mudaram(self, imovel_a):
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 420000.0
        novo.area = 58.0
        novo.quartos = 3
        diffs = _comparar_campos(imovel_a, novo, CAMPOS_MONITORADOS)
        assert len(diffs) == 3
        campos = {d.campo for d in diffs}
        assert campos == {"preco_venda", "area", "quartos"}

    def test_campos_filtrados(self, imovel_a):
        """Deve comparar apenas os campos passados explicitamente."""
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 420000.0
        novo.area = 58.0
        # Só monitora preco_venda e titulo
        diffs = _comparar_campos(imovel_a, novo, ("preco_venda", "titulo"))
        assert len(diffs) == 1
        assert diffs[0].campo == "preco_venda"

    def test_campo_inexistente_ignorado(self, imovel_a):
        """Campos que não existem na dataclass são ignorados sem erro."""
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 420000.0
        diffs = _comparar_campos(
            imovel_a, novo, ("preco_venda", "campo_inexistente")
        )
        assert len(diffs) == 1
        assert diffs[0].campo == "preco_venda"


# ── Testes: diff_imoveis (função principal) ───────────────────────────────────


class TestDiffImoveis:
    """Testa a função principal de diff entre listas."""

    def test_listas_vazias(self):
        result = diff_imoveis([], [])
        assert not result.tem_mudancas
        assert result.novos == []
        assert result.removidos == []
        assert result.alterados == []
        assert result.total_anterior == 0
        assert result.total_atual == 0
        assert result.mesmo_total

    def test_sem_mudancas(self, imovel_a, imovel_b):
        result = diff_imoveis([imovel_a, imovel_b], [imovel_a, imovel_b])
        assert not result.tem_mudancas
        assert result.novos == []
        assert result.removidos == []
        assert result.alterados == []

    def test_novos_imoveis(self, imovel_a, imovel_b):
        result = diff_imoveis([imovel_a], [imovel_a, imovel_b])
        assert result.tem_mudancas
        assert len(result.novos) == 1
        assert result.novos[0].id == "a2"
        assert result.removidos == []
        assert result.alterados == []

    def test_removidos_imoveis(self, imovel_a, imovel_b):
        result = diff_imoveis([imovel_a, imovel_b], [imovel_a])
        assert result.tem_mudancas
        assert result.novos == []
        assert len(result.removidos) == 1
        assert result.removidos[0].id == "a2"
        assert result.alterados == []

    def test_imovel_alterado(self, imovel_a):
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 420000.0
        result = diff_imoveis([imovel_a], [novo])
        assert result.tem_mudancas
        assert result.novos == []
        assert result.removidos == []
        assert len(result.alterados) == 1
        alt = result.alterados[0]
        assert alt.id == "a1"
        assert len(alt.campos_alterados) == 1
        assert alt.campos_alterados[0].campo == "preco_venda"

    def test_mistura_completa(self, imovel_a, imovel_b, imovel_c):
        """Testa novos + removidos + alterados simultaneamente."""
        a_alterado = Imovel.from_dict(imovel_a.to_dict())
        a_alterado.preco_venda = 420000.0

        nova_d = Imovel(
            id="a4", titulo="Novo", fonte="olx", bairro="Higienópolis",
            preco_venda=600000.0, area=70.0,
        )

        anterior = [imovel_a, imovel_b, imovel_c]
        atual = [a_alterado, imovel_c, nova_d]  # a_alterado, c mantido, d novo; b removido

        result = diff_imoveis(anterior, atual)

        assert result.total_novos == 1
        assert result.novos[0].id == "a4"

        assert result.total_removidos == 1
        assert result.removidos[0].id == "a2"

        assert result.total_alterados == 1
        assert result.alterados[0].id == "a1"
        assert result.alterados[0].campos_alterados[0].campo == "preco_venda"

        assert result.total_anterior == 3
        assert result.total_atual == 3

    def test_imoveis_sem_id_sao_ignorados(self):
        """Imóveis com id vazio não participam do diff."""
        sem_id = Imovel(titulo="Sem ID", fonte="olx")
        com_id = Imovel(id="x1", titulo="Com ID", fonte="olx", bairro="Centro")
        result = diff_imoveis([sem_id], [com_id])
        # sem_id é ignorado, então com_id aparece como novo
        assert result.total_novos == 1
        assert result.novos[0].id == "x1"
        assert result.total_removidos == 0

    def test_mesmo_total_mas_conteudo_diferente(self):
        """mesmo_total=True não significa mesmos itens."""
        a = Imovel(id="a1", titulo="A", fonte="olx", bairro="A")
        b = Imovel(id="b1", titulo="B", fonte="olx", bairro="B")
        result = diff_imoveis([a], [b])
        assert result.mesmo_total  # ambos com 1
        assert result.tem_mudancas  # mas conteúdo diferente

    def test_bool_resultado(self, imovel_a):
        result = diff_imoveis([], [])
        assert not bool(result)

        result = diff_imoveis([imovel_a], [])
        assert bool(result)

        result = diff_imoveis([], [imovel_a])
        assert bool(result)

        a_alterado = Imovel.from_dict(imovel_a.to_dict())
        a_alterado.preco_venda = 420000.0
        result = diff_imoveis([imovel_a], [a_alterado])
        assert bool(result)

    def test_mesma_lista(self, imovel_a, imovel_b):
        result = diff_imoveis([imovel_a, imovel_b], [imovel_a, imovel_b])
        assert not result.tem_mudancas
        assert result.mesmo_total


# ── Testes: Alteracao.resumo ──────────────────────────────────────────────────


class TestAlteracaoResumo:
    def test_uma_mudanca(self):
        ant = Imovel(id="x1", titulo="Antigo", fonte="olx", bairro="Centro")
        atu = Imovel(id="x1", titulo="Novo", fonte="olx", bairro="Centro")
        alt = Alteracao(
            id="x1",
            anterior=ant,
            atual=atu,
            campos_alterados=[AlteracaoCampo("titulo", "Antigo", "Novo")],
        )
        assert "titulo: Antigo → Novo" in alt.resumo

    def test_multiplas_mudancas(self):
        ant = Imovel(id="x1", preco_venda=500000.0, titulo="Antigo",
                      area=50.0, fonte="olx", bairro="Centro")
        atu = Imovel(id="x1", preco_venda=450000.0, titulo="Novo",
                      area=55.0, fonte="olx", bairro="Centro")
        alt = Alteracao(
            id="x1",
            anterior=ant,
            atual=atu,
            campos_alterados=[
                AlteracaoCampo("preco_venda", 500000.0, 450000.0),
                AlteracaoCampo("titulo", "Antigo", "Novo"),
                AlteracaoCampo("area", 50.0, 55.0),
            ],
        )
        for campo in ("preco_venda", "titulo", "area"):
            assert campo in alt.resumo


# ── Testes: DiffResult.serialização ───────────────────────────────────────────


class TestDiffResultSerializacao:
    def test_to_dict(self, imovel_a):
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 420000.0
        result = diff_imoveis([imovel_a], [novo])
        d = result.to_dict()

        assert "novos" in d
        assert "removidos" in d
        assert "alterados" in d
        assert "total_anterior" in d
        assert "total_atual" in d
        assert len(d["alterados"]) == 1
        assert d["alterados"][0]["id"] == "a1"
        assert d["alterados"][0]["campos_alterados"][0]["campo"] == "preco_venda"

    def test_to_json_serializavel(self, imovel_a, imovel_b):
        result = diff_imoveis([imovel_a], [imovel_a, imovel_b])
        j = result.to_json()
        parsed = json.loads(j)
        assert len(parsed["novos"]) == 1
        assert len(parsed["alterados"]) == 0

    def test_resumo_curto(self, imovel_a, imovel_b, imovel_c):
        a_alt = Imovel.from_dict(imovel_a.to_dict())
        a_alt.preco_venda = 420000.0
        result = diff_imoveis([imovel_a, imovel_b], [a_alt, imovel_c])
        assert "1 novo(s)" in result.resumo_curto()
        assert "1 removido(s)" in result.resumo_curto()
        assert "1 alterado(s)" in result.resumo_curto()

    def test_resumo_sem_mudancas(self):
        result = diff_imoveis([], [])
        assert result.resumo_curto() == "Sem mudanças"

    def test_str_method(self, imovel_a):
        result = diff_imoveis([], [imovel_a])
        s = str(result)
        assert "novos=1" in s
        assert "removidos=0" in s


# ── Testes: diff_por_fonte ────────────────────────────────────────────────────


class TestDiffPorFonte:
    def test_agrupa_por_fonte(self, imovel_a, imovel_b):
        """Deve agrupar novos/removidos/alterados por fonte."""
        qa_a = Imovel(
            id="q1", titulo="QA Apto",
            fonte="quintoandar", bairro="Centro",
            preco_venda=500000.0,
        )
        atual = [imovel_a, qa_a]
        result = diff_imoveis([imovel_a], atual)
        grupos = diff_por_fonte(result)

        # imovel_a está em ambas (fonte='olx') e não mudou → sem grupo
        assert "olx" not in grupos
        # quintoandar tem um novo
        assert "quintoandar" in grupos
        assert len(grupos["quintoandar"]["novos"]) == 1
        assert grupos["quintoandar"]["novos"][0].id == "q1"

    def test_fonte_desconhecida(self):
        """Imóvel sem fonte vai para 'desconhecida'."""
        sem_fonte = Imovel(
            id="z1", titulo="Sem fonte", bairro="Centro", preco_venda=100000.0,
        )
        result = diff_imoveis([], [sem_fonte])
        grupos = diff_por_fonte(result)
        assert "desconhecida" in grupos
        assert len(grupos["desconhecida"]["novos"]) == 1


# ── Testes: _fmt_val ──────────────────────────────────────────────────────────


class TestFmtVal:
    def test_none(self):
        assert _fmt_val(None) == "N/I"

    def test_float_alto(self):
        assert "R$" in _fmt_val(450000.0)

    def test_float_baixo(self):
        assert _fmt_val(12.5) == "12.50"

    def test_lista_vazia(self):
        assert _fmt_val([]) == "[]"

    def test_lista_curta(self):
        assert _fmt_val(["a", "b"]) == "a, b"

    def test_lista_longa(self):
        assert _fmt_val(["a", "b", "c", "d"]) == "4 itens"

    def test_string(self):
        assert _fmt_val("qualquer") == "qualquer"


# ── Testes de comportamento com dados reais ───────────────────────────────────


class TestComportamentoReal:
    """Testes que simulam cenários reais do watchdog."""

    def test_nenhum_preco_na_primeira_execucao(self):
        """Primeira execução: anterior vazia, atual com dados → tudo é novo."""
        imoveis = [
            Imovel(id=f"olx_{i}", titulo=f"Imóvel {i}",
                   fonte="olx", bairro="Centro",
                   preco_venda=float(300_000 + i * 1000))
            for i in range(5)
        ]
        result = diff_imoveis([], imoveis)
        assert result.total_novos == 5
        assert result.total_removidos == 0
        assert result.total_alterados == 0

    def test_preco_abaixou(self, imovel_a):
        """Imóvel fica mais barato."""
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 400000.0  # reduziu R$ 50k
        result = diff_imoveis([imovel_a], [novo])
        assert result.total_alterados == 1
        alt = result.alterados[0]
        assert alt.campos_alterados[0].valor_anterior == 450000.0
        assert alt.campos_alterados[0].valor_novo == 400000.0

    def test_preco_subiu(self, imovel_a):
        """Imóvel fica mais caro."""
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.preco_venda = 480000.0  # subiu R$ 30k
        result = diff_imoveis([imovel_a], [novo])
        assert result.total_alterados == 1

    def test_campos_extras_nao_monitorados(self, imovel_a):
        """Mudança em campo não monitorado não gera alteração."""
        novo = Imovel.from_dict(imovel_a.to_dict())
        novo.data_coleta = "2099-01-01T00:00:00Z"  # muda, mas não está em CAMPOS_MONITORADOS
        result = diff_imoveis([imovel_a], [novo])
        assert result.total_alterados == 0

    def test_muitos_imoveis_sem_explodir(self):
        """Diff com 1000 imóveis é rápido e não explode."""
        anterior = [
            Imovel(id=f"olx_{i}", titulo=f"Imóvel {i}",
                   fonte="olx", bairro="Centro",
                   preco_venda=float(300_000 + i))
            for i in range(1000)
        ]
        atual = [
            Imovel(id=f"olx_{i}", titulo=f"Imóvel {i}",
                   fonte="olx", bairro="Centro",
                   preco_venda=float(300_000 + i + (1 if i % 3 == 0 else 0)))
            for i in range(999)
        ]
        import time
        start = time.time()
        result = diff_imoveis(anterior, atual)
        elapsed = time.time() - start
        assert elapsed < 2.0  # deve ser sub-segundo
        assert result.total_novos == 0
        assert result.total_removidos == 1
        assert result.total_alterados > 0
