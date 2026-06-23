"""
Testes para classificar_mudancas — classificação semântica de mudanças.

Uso:
    cd /home/higor/imoveis-watchdog
    PYTHONPATH="$HOME/.hermes:skills:skills/diff" python3 -m pytest \
        skills/classificador/test_classificador.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Adiciona caminhos para importar imovel_schema, diff (do projeto real)
# e o módulo sob teste
_HERE = Path(__file__).resolve().parent
_SKILLS = _HERE.parent
_IMOVEL_SKILLS = Path.home() / "imoveis-watchdog" / "skills"

sys.path.insert(0, str(Path.home() / ".hermes"))          # imovel_schema
sys.path.insert(0, str(_IMOVEL_SKILLS))                   # diff/ do projeto real
sys.path.insert(0, str(_SKILLS / "classificador"))        # classificador

from imovel_schema import Imovel

from diff.diff_imoveis import (
    Alteracao,
    AlteracaoCampo,
    DiffResult,
    diff_imoveis,
)

from classificador import (
    CAMPOS_PRECO,
    CAMPOS_STATUS,
    MudancaEvento,
    classificar_mudancas,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def imovel_base() -> Imovel:
    return Imovel(
        id="apto_001",
        titulo="Apto 2q Consolação",
        url="https://exemplo.com/apto_001",
        fonte="quintoandar",
        bairro="Consolação",
        cidade="São Paulo",
        uf="SP",
        preco_venda=450000.0,
        preco_aluguel=None,
        condominio=800.0,
        iptu=200.0,
        area=55.0,
        quartos=2,
        banheiros=1,
        vagas=1,
        tipo="apartamento",
        disponivel=True,
        status="ativo",
        data_coleta="2026-06-21T10:00:00Z",
    )


@pytest.fixture
def imovel_outro() -> Imovel:
    return Imovel(
        id="apto_002",
        titulo="Kitnet Pinheiros",
        url="https://exemplo.com/apto_002",
        fonte="quintoandar",
        bairro="Pinheiros",
        cidade="São Paulo",
        uf="SP",
        preco_aluguel=1800.0,
        condominio=400.0,
        area=28.0,
        tipo="kitnet",
        data_coleta="2026-06-21T10:00:00Z",
    )


# ── Testes: MudancaEvento.to_dict ─────────────────────────────────────────────


class TestMudancaEventoDict:
    """Testa serialização do MudancaEvento."""

    def test_new_event(self):
        ev = MudancaEvento(
            tipo="new",
            id_imovel="x1",
            timestamp="2026-06-21T10:00:00Z",
            valor_novo={"id": "x1"},
        )
        d = ev.to_dict()
        assert d["tipo"] == "new"
        assert d["id_imovel"] == "x1"
        assert "valor_anterior" not in d  # new não tem anterior
        assert d["valor_novo"] == {"id": "x1"}

    def test_removed_event(self):
        ev = MudancaEvento(
            tipo="removed",
            id_imovel="x1",
            timestamp="2026-06-21T10:00:00Z",
            valor_anterior={"id": "x1"},
        )
        d = ev.to_dict()
        assert d["tipo"] == "removed"
        assert "valor_novo" not in d  # removed não tem novo
        assert d["valor_anterior"] == {"id": "x1"}

    def test_price_event(self):
        ev = MudancaEvento(
            tipo="price_decrease",
            id_imovel="x1",
            campo="preco_venda",
            valor_anterior=500000.0,
            valor_novo=450000.0,
            timestamp="2026-06-21T10:00:00Z",
        )
        d = ev.to_dict()
        assert d["tipo"] == "price_decrease"
        assert d["valor_anterior"] == 500000.0
        assert d["valor_novo"] == 450000.0
        assert d["campo"] == "preco_venda"

    def test_json_serializable(self):
        ev = MudancaEvento(
            tipo="price_decrease",
            id_imovel="x1",
            campo="preco_venda",
            valor_anterior=500000.0,
            valor_novo=450000.0,
            timestamp="2026-06-21T10:00:00Z",
        )
        j = json.dumps(ev.to_dict(), ensure_ascii=False)
        parsed = json.loads(j)
        assert parsed["tipo"] == "price_decrease"
        assert parsed["valor_anterior"] == 500000.0


# ── Testes: classificar_mudancas — casos básicos ──────────────────────────────


class TestClassificarNovos:
    """Imóveis novos devem gerar eventos 'new'."""

    def test_um_novo(self, imovel_base):
        diff = diff_imoveis([], [imovel_base])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "new"
        assert eventos[0].id_imovel == "apto_001"

    def test_multiplos_novos(self, imovel_base, imovel_outro):
        diff = diff_imoveis([], [imovel_base, imovel_outro])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 2
        tipos = {ev.tipo for ev in eventos}
        assert tipos == {"new"}
        ids = {ev.id_imovel for ev in eventos}
        assert ids == {"apto_001", "apto_002"}

    def test_novo_tem_valor_novo_dict(self, imovel_base):
        diff = diff_imoveis([], [imovel_base])
        eventos = classificar_mudancas(diff)
        assert isinstance(eventos[0].valor_novo, dict)
        assert eventos[0].valor_novo["id"] == "apto_001"
        assert eventos[0].valor_anterior is None


class TestClassificarRemovidos:
    """Imóveis removidos devem gerar eventos 'removed'."""

    def test_um_removido(self, imovel_base):
        diff = diff_imoveis([imovel_base], [])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "removed"
        assert eventos[0].id_imovel == "apto_001"

    def test_removido_tem_valor_anterior_dict(self, imovel_base):
        diff = diff_imoveis([imovel_base], [])
        eventos = classificar_mudancas(diff)
        assert isinstance(eventos[0].valor_anterior, dict)
        assert eventos[0].valor_anterior["id"] == "apto_001"
        assert eventos[0].valor_novo is None


class TestClassificarPriceDecrease:
    """Redução de preço deve gerar 'price_decrease'."""

    def test_preco_venda_diminuiu(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 400000.0
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_decrease"
        assert eventos[0].campo == "preco_venda"
        assert eventos[0].valor_anterior == 450000.0
        assert eventos[0].valor_novo == 400000.0

    def test_condominio_diminuiu(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.condominio = 600.0
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_decrease"
        assert eventos[0].campo == "condominio"

    def test_iptu_diminuiu(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.iptu = 150.0
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_decrease"
        assert eventos[0].campo == "iptu"


class TestClassificarPriceIncrease:
    """Aumento de preço deve gerar 'price_increase'."""

    def test_preco_venda_aumentou(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 480000.0
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_increase"
        assert eventos[0].campo == "preco_venda"
        assert eventos[0].valor_anterior == 450000.0
        assert eventos[0].valor_novo == 480000.0

    def test_preco_aluguel_aumentou(self, imovel_base):
        imovel_base.preco_aluguel = 1500.0
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_aluguel = 1800.0
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_increase"
        assert eventos[0].campo == "preco_aluguel"


class TestClassificarStatusChange:
    """Mudança de disponibilidade ou status deve gerar 'status_change'."""

    def test_disponivel_mudou(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.disponivel = False
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "status_change"
        assert eventos[0].campo == "disponivel"

    def test_status_mudou(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.status = "inativo"
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "status_change"
        assert eventos[0].campo == "status"


# ── Testes: múltiplas mudanças no mesmo imóvel ────────────────────────────────


class TestMultiplasMudancas:
    """Imóvel com várias alterações deve gerar um evento para cada."""

    def test_preco_e_status(self, imovel_base):
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 420000.0  # price_decrease
        novo.status = "inativo"       # status_change
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 2
        tipos = {ev.tipo for ev in eventos}
        assert tipos == {"price_decrease", "status_change"}

    def test_tres_campos_preco(self, imovel_base):
        """Todos os campos de preço mudaram ao mesmo tempo."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 420000.0   # decrease
        novo.condominio = 900.0       # increase
        novo.iptu = 180.0             # decrease
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 3
        decreases = [ev for ev in eventos if ev.tipo == "price_decrease"]
        increases = [ev for ev in eventos if ev.tipo == "price_increase"]
        assert len(decreases) == 2
        assert len(increases) == 1
        campos_dec = {ev.campo for ev in decreases}
        assert campos_dec == {"preco_venda", "iptu"}
        assert increases[0].campo == "condominio"

    def test_preco_e_area(self, imovel_base):
        """Mudança em característica (área) gera evento field_change."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 420000.0   # price_decrease
        novo.area = 58.0              # field_change (agora monitorado)
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 2
        tipos = {ev.tipo for ev in eventos}
        assert tipos == {"price_decrease", "field_change"}
        campo_fc = next(ev for ev in eventos if ev.tipo == "field_change")
        assert campo_fc.campo == "area"
        assert campo_fc.valor_anterior == 55.0
        assert campo_fc.valor_novo == 58.0


# ── Testes: cenários completos (novos + removidos + alterados) ────────────────


class TestCenarioCompleto:
    """Testa combinação de novos, removidos e alterados simultaneamente."""

    def test_mistura_completa(self, imovel_base, imovel_outro):
        """Novo + removido + alterado ao mesmo tempo."""
        imovel_c = Imovel(
            id="apto_003",
            titulo="Casa 3q V. Mariana",
            fonte="quintoandar",
            bairro="Vila Mariana",
            preco_venda=550000.0,
            data_coleta="2026-06-21T10:00:00Z",
        )
        imovel_d = Imovel(
            id="apto_004",
            titulo="Novo na Av. Paulista",
            fonte="quintoandar",
            bairro="Bela Vista",
            preco_venda=600000.0,
            data_coleta="2026-06-21T10:00:00Z",
        )

        # imovel_base foi alterado (preco caiu)
        base_alterado = Imovel.from_dict(imovel_base.to_dict())
        base_alterado.preco_venda = 400000.0

        anterior = [imovel_base, imovel_outro, imovel_c]
        atual = [base_alterado, imovel_c, imovel_d]  # imovel_outro removido

        diff = diff_imoveis(anterior, atual)
        eventos = classificar_mudancas(diff)

        # Deve ter: 1 new (d), 1 removed (imovel_outro), 1 price_decrease (base)
        assert len(eventos) == 3

        tipos = {ev.tipo for ev in eventos}
        assert tipos == {"new", "removed", "price_decrease"}

        ev_new = next(ev for ev in eventos if ev.tipo == "new")
        assert ev_new.id_imovel == "apto_004"

        ev_removed = next(ev for ev in eventos if ev.tipo == "removed")
        assert ev_removed.id_imovel == "apto_002"

        ev_price = next(ev for ev in eventos if ev.tipo == "price_decrease")
        assert ev_price.id_imovel == "apto_001"


# ── Testes: sem mudanças ──────────────────────────────────────────────────────


class TestSemMudancas:
    """Sem mudanças → lista vazia."""

    def test_listas_vazias(self):
        diff = diff_imoveis([], [])
        eventos = classificar_mudancas(diff)
        assert eventos == []

    def test_mesma_lista(self, imovel_base):
        diff = diff_imoveis([imovel_base], [imovel_base])
        eventos = classificar_mudancas(diff)
        assert eventos == []


# ── Testes: ordenação ─────────────────────────────────────────────────────────


class TestOrdenacao:
    """Eventos saem na ordem: novos → removidos → alterados."""

    def test_ordem_correta(self, imovel_base, imovel_outro):
        imovel_c = Imovel(
            id="apto_003",
            titulo="Imóvel C",
            fonte="quintoandar", bairro="Centro",
            preco_venda=300000.0,
        )
        c_alterado = Imovel.from_dict(imovel_c.to_dict())
        c_alterado.preco_venda = 290000.0

        anterior = [imovel_base, imovel_outro, imovel_c]
        atual = [c_alterado, imovel_base]
        # imovel_outro removido, imovel_c alterado, imovel_base sem mudança

        diff = diff_imoveis(anterior, atual)
        eventos = classificar_mudancas(diff)

        assert len(eventos) == 2
        # removido deve vir antes de alterado
        assert eventos[0].tipo == "removed"
        assert eventos[0].id_imovel == "apto_002"
        assert eventos[1].tipo == "price_decrease"


# ── Testes: casos de borda ────────────────────────────────────────────────────


class TestCasosBorda:
    """Casos de borda definidos nos critérios de aceitação."""

    def test_preco_subiu_para_none(self, imovel_base):
        """Preço vai de um valor para None — considerado price_increase?"""
        # Na prática, preço ir para None é incomum, mas devemos tratar
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = None
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        # None vs valor: _as_number retorna None, então não classifica
        # Mas o diff_imoveis ainda detectou a mudança
        # O classificador gera price_increase genérico
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_increase"

    def test_preco_veio_de_none(self, imovel_base):
        """Preço vai de None para um valor."""
        imovel_sem_preco = Imovel.from_dict(imovel_base.to_dict())
        imovel_sem_preco.preco_venda = None

        novo = Imovel.from_dict(imovel_sem_preco.to_dict())
        novo.preco_venda = 450000.0

        diff = diff_imoveis([imovel_sem_preco], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "price_increase"

    def test_preco_estavel_mas_titulo_mudou(self, imovel_base):
        """Mudança de título não gera evento de classificação (campo ignorado)."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.titulo = "Novo título maneiro"
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        # título não é preço nem status → ignorado
        assert eventos == []

    def test_disponivel_mudou_com_preco_igual(self, imovel_base):
        """Só status_change, sem price event."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.disponivel = False  # preco_venda continua 450000
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "status_change"
        assert eventos[0].campo == "disponivel"

    def test_timestamp_do_imovel_usado(self, imovel_base):
        """O timestamp do evento deve vir do Imovel atual quando disponível."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 400000.0
        novo.data_coleta = "2026-06-21T15:30:00Z"
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert eventos[0].timestamp == "2026-06-21T15:30:00Z"

    def test_multiplos_campos_mudaram_eventos_separados(self, imovel_base):
        """Preço caiu E status mudou = 2 eventos separados."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 400000.0
        novo.disponivel = False
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 2
        tipos = sorted(ev.tipo for ev in eventos)
        assert tipos == ["price_decrease", "status_change"]

    def test_imovel_removido_voltou_sem_alteracoes(self, imovel_base):
        """Cenário: imóvel sai em T1, volta em T2 sem alterações.
        Isso é cross-diff (dois ciclos diferentes). O classificador
        só vê UM diff por vez. Se entrou de novo, é 'new'.
        Se saiu, é 'removed'. O teste comprova que não geramos
        eventos duplicados ou incorretos.
        """
        # Ciclo 1: saiu
        diff1 = diff_imoveis([imovel_base], [])
        ev1 = classificar_mudancas(diff1)
        assert len(ev1) == 1
        assert ev1[0].tipo == "removed"

        # Ciclo 2: voltou (como se o anunciante republicou)
        diff2 = diff_imoveis([], [imovel_base])
        ev2 = classificar_mudancas(diff2)
        assert len(ev2) == 1
        assert ev2[0].tipo == "new"
        # O imóvel aparece como novo (não temos como saber que é o mesmo
        # que já existia — isso seria responsabilidade de uma camada
        # de tracking acima, não do classificador)

    def test_amenities_mudou(self, imovel_base):
        """Mudança em amenities gera evento field_change."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.amenities = ["piscina", "academia"]
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "field_change"
        assert eventos[0].campo == "amenities"
        assert eventos[0].valor_anterior == []
        assert eventos[0].valor_novo == ["piscina", "academia"]

    def test_amenities_adicionou_item(self, imovel_base):
        """Adicionar amenity a uma lista existente gera field_change."""
        base = Imovel.from_dict(imovel_base.to_dict())
        base.amenities = ["piscina"]
        novo = Imovel.from_dict(base.to_dict())
        novo.amenities = ["piscina", "academia", "salao_festas"]
        diff = diff_imoveis([base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "field_change"
        assert eventos[0].campo == "amenities"
        assert set(eventos[0].valor_anterior) == {"piscina"}
        assert set(eventos[0].valor_novo) == {"piscina", "academia", "salao_festas"}

    def test_amenities_removeu_item(self, imovel_base):
        """Remover amenity de uma lista existente gera field_change."""
        base = Imovel.from_dict(imovel_base.to_dict())
        base.amenities = ["piscina", "academia", "salao_festas"]
        novo = Imovel.from_dict(base.to_dict())
        novo.amenities = ["piscina"]  # perdeu academia e salao_festas
        diff = diff_imoveis([base], [novo])
        eventos = classificar_mudancas(diff)
        assert len(eventos) == 1
        assert eventos[0].tipo == "field_change"
        assert eventos[0].campo == "amenities"

    def test_diff_vazio_sem_eventos(self):
        """DiffResult vazio não gera eventos."""
        diff = DiffResult(novos=[], removidos=[], alterados=[])
        eventos = classificar_mudancas(diff)
        assert eventos == []

    def test_tipo_valido_sempre(self, imovel_base):
        """Todo evento gerado deve ter tipo em ('new', 'removed',
        'price_decrease', 'price_increase', 'status_change')."""
        novo = Imovel.from_dict(imovel_base.to_dict())
        novo.preco_venda = 400000.0
        novo.disponivel = False
        diff = diff_imoveis([imovel_base], [novo])
        eventos = classificar_mudancas(diff)
        tipos_validos = frozenset({
            "new", "removed", "price_decrease",
            "price_increase", "status_change", "field_change",
        })
        for ev in eventos:
            assert ev.tipo in tipos_validos, f"Tipo inválido: {ev.tipo}"
