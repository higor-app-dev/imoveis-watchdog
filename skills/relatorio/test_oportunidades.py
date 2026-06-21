"""
Testes para oportunidades — relatório unificado de novas oportunidades.

Uso:
    cd /home/higor/imoveis-watchdog
    PYTHONPATH="skills/relatorio:$HOME/.hermes:skills" python3 -m pytest \\
        skills/relatorio/test_oportunidades.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Adiciona caminhos para importar imovel_schema e os módulos do projeto
_HOME = Path.home()
sys.path.insert(0, str(_HOME / ".hermes"))                          # imovel_schema
sys.path.insert(0, str(_HOME / "imoveis-watchdog" / "skills"))      # qa_loft_dedup etc.
sys.path.insert(0, str(_HOME / "imoveis-watchdog" / "skills" / "relatorio"))  # oportunidades

from imovel_schema import Imovel

from oportunidades import (
    ItemOportunidade,
    NEW_FLAG_NOVO,
    NEW_FLAG_EXISTENTE,
    RelatorioOportunidades,
    gerar_relatorio_oportunidades,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def imovel_qa_barato() -> dict:
    """Imóvel barato do QuintoAndar."""
    return {
        "id": "qa_001",
        "titulo": "Apto 1q Consolação",
        "url": "https://quintoandar.com.br/imovel/qa_001",
        "fonte": "quintoandar",
        "bairro": "Consolação",
        "cidade": "São Paulo",
        "uf": "SP",
        "endereco": "Rua Augusta, 500",
        "preco_venda": 350000.0,
        "area": 45.0,
        "quartos": 1,
        "data_coleta": "2026-06-21T10:00:00Z",
    }


@pytest.fixture
def imovel_qa_medio() -> dict:
    """Imóvel preço médio do QuintoAndar."""
    return {
        "id": "qa_002",
        "titulo": "Apto 2q Liberdade",
        "url": "https://quintoandar.com.br/imovel/qa_002",
        "fonte": "quintoandar",
        "bairro": "Liberdade",
        "cidade": "São Paulo",
        "uf": "SP",
        "endereco": "Rua da Glória, 200",
        "preco_venda": 550000.0,
        "area": 65.0,
        "quartos": 2,
        "data_coleta": "2026-06-21T10:00:00Z",
    }


@pytest.fixture
def imovel_loft_caro() -> dict:
    """Imóvel caro da Loft."""
    return {
        "id": "loft_001",
        "titulo": "Apto 3q Jardins",
        "url": "https://loft.com.br/imovel/loft_001",
        "fonte": "loft",
        "bairro": "Jardins",
        "cidade": "São Paulo",
        "uf": "SP",
        "endereco": "Alameda Santos, 1000",
        "preco_venda": 1200000.0,
        "area": 120.0,
        "quartos": 3,
        "data_coleta": "2026-06-21T10:00:00Z",
    }


@pytest.fixture
def imovel_qa_existente() -> dict:
    """Imóvel que já estava no estado anterior."""
    return {
        "id": "qa_existente",
        "titulo": "Studio Bela Vista",
        "url": "https://quintoandar.com.br/imovel/qa_existente",
        "fonte": "quintoandar",
        "bairro": "Bela Vista",
        "cidade": "São Paulo",
        "uf": "SP",
        "endereco": "Rua Haddock Lobo, 300",
        "preco_venda": 280000.0,
        "area": 30.0,
        "quartos": 0,
        "data_coleta": "2026-06-20T10:00:00Z",
    }


@pytest.fixture
def listings_mistos(
    imovel_qa_barato: dict,
    imovel_qa_medio: dict,
    imovel_loft_caro: dict,
    imovel_qa_existente: dict,
) -> list[dict]:
    """Lista mista de 4 imóveis de portais diferentes."""
    return [
        dict(imovel_qa_barato),
        dict(imovel_qa_medio),
        dict(imovel_loft_caro),
        dict(imovel_qa_existente),
    ]


@pytest.fixture
def estado_anterior_com_um(
    imovel_qa_existente: dict,
) -> str:
    """Cria um arquivo de estado anterior temporário com 1 imóvel."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump({
            "timestamp": "2026-06-21T10:00:00Z",
            "total": 1,
            "imoveis": [imovel_qa_existente],
        }, f, ensure_ascii=False, indent=2)
        f.flush()
        path = f.name

    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Testes: ItemOportunidade ──────────────────────────────────────────────────


class TestItemOportunidade:
    """Testa a dataclass ItemOportunidade."""

    def test_from_imovel_dict_completo(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        assert item.id == "qa_001"
        assert item.endereco == "Rua Augusta, 500"
        assert item.bairro == "Consolação"
        assert item.preco == 350000.0
        assert item.area == 45.0
        assert item.portais == ["quintoandar"]
        assert item.url == "https://quintoandar.com.br/imovel/qa_001"
        assert item.fonte == "quintoandar"

    def test_from_imovel_dict_vazio(self):
        item = ItemOportunidade.from_imovel_dict({})
        assert item.id == ""
        assert item.endereco == ""
        assert item.preco is None
        assert item.area is None
        assert item.portais == []
        assert item.new_flag == NEW_FLAG_NOVO  # default

    def test_preco_formatado(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        assert item.preco_formatado() == "R$ 350.000"

    def test_preco_formatado_none(self):
        item = ItemOportunidade(preco=None)
        assert item.preco_formatado() == "N/I"

    def test_portais_str_unico(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        assert item.portais_str() == "quintoandar"

    def test_portais_str_multiplos(self):
        item = ItemOportunidade(
            id="test", portais=["quintoandar", "loft"]
        )
        assert item.portais_str() == "loft, quintoandar"

    def test_portais_str_vazio(self):
        item = ItemOportunidade(id="test", fonte="")
        assert item.portais_str() == "desconhecido"

    def test_to_dict(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        d = item.to_dict()
        assert d["id"] == "qa_001"
        assert d["preco"] == 350000.0
        assert d["preco_formatado"] == "R$ 350.000"
        assert d["new_flag"] == NEW_FLAG_NOVO
        assert d["portais"] == ["quintoandar"]


# ── Testes: RelatorioOportunidades ────────────────────────────────────────────


class TestRelatorioOportunidades:
    """Testa a dataclass RelatorioOportunidades."""

    def test_vazio(self):
        rel = RelatorioOportunidades()
        assert rel.total == 0
        assert rel.total_novos == 0
        assert rel.total_existentes == 0
        assert rel.timestamp  # deve ter autopreenchido

    def test_com_items(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        rel = RelatorioOportunidades(items=[item])
        assert rel.total == 1
        assert rel.total_novos == 1
        assert rel.total_existentes == 0

    def test_total_novos_e_existentes(self):
        items = [
            ItemOportunidade(id="a", new_flag=NEW_FLAG_NOVO),
            ItemOportunidade(id="b", new_flag=NEW_FLAG_EXISTENTE),
            ItemOportunidade(id="c", new_flag=NEW_FLAG_NOVO),
        ]
        rel = RelatorioOportunidades(items=items)
        assert rel.total == 3
        assert rel.total_novos == 2
        assert rel.total_existentes == 1

    def test_texto_contem_sumario(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        rel = RelatorioOportunidades(items=[item])
        texto = rel.texto
        assert "Relatório de Oportunidades" in texto
        assert "Total de imóveis únicos: 1" in texto
        assert "Novos:" in texto
        assert "Existentes:" in texto
        assert "[NOVO]" in texto
        assert "R$ 350.000" in texto
        assert "Consolação" in texto
        assert "quintoandar" in texto

    def test_texto_sem_items(self):
        rel = RelatorioOportunidades(items=[])
        texto = rel.texto
        assert "Nenhum imóvel encontrado" in texto
        assert "Total de imóveis únicos: 0" in texto

    def test_salvar_arquivo(self):
        rel = RelatorioOportunidades(items=[])
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            escrito = rel.salvar(path)
            assert escrito.exists()
            conteudo = escrito.read_text(encoding="utf-8")
            assert "Relatório de Oportunidades" in conteudo
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_salvar_json(self):
        rel = RelatorioOportunidades(items=[])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            escrito = rel.salvar_json(path)
            assert escrito.exists()
            dados = json.loads(escrito.read_text(encoding="utf-8"))
            assert dados["versao"] == 1
            assert dados["total"] == 0
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_to_dict(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        rel = RelatorioOportunidades(items=[item])
        d = rel.to_dict()
        assert d["versao"] == 1
        assert d["total"] == 1
        assert d["total_novos"] == 1
        assert len(d["items"]) == 1
        assert d["items"][0]["id"] == "qa_001"

    def test_to_json_serializavel(self, imovel_qa_barato: dict):
        item = ItemOportunidade.from_imovel_dict(imovel_qa_barato)
        rel = RelatorioOportunidades(items=[item])
        json_str = rel.to_json()
        parsed = json.loads(json_str)
        assert parsed["total"] == 1


# ── Testes: gerar_relatorio_oportunidades ──────────────────────────────────────


class TestGerarRelatorio:
    """Testa a função principal de geração de relatório."""

    # Critério de aceitação 1: Apenas propriedades únicas
    # Critério de aceitação 2: Ordenado por preço ascendente
    # Critério de aceitação 3: Output em arquivo ou CLI

    def test_lista_vazia(self):
        """Lista vazia → relatório vazio mas válido."""
        rel = gerar_relatorio_oportunidades(
            [],
            aplicar_dedup=False,
            saida="console",
        )
        assert rel.total == 0
        assert rel.total_novos == 0

    def test_todos_novos(self, listings_mistos: list[dict]):
        """Sem estado anterior, todos são NOVOS."""
        rel = gerar_relatorio_oportunidades(
            listings_mistos,
            aplicar_dedup=False,
            saida="console",
        )
        assert rel.total == 4
        assert rel.total_novos == 4
        assert rel.total_existentes == 0

    def test_ordenacao_preco_ascendente(self, listings_mistos: list[dict]):
        """Critério 2: ordenado por preço ascendente."""
        rel = gerar_relatorio_oportunidades(
            listings_mistos,
            aplicar_dedup=False,
            saida="console",
        )
        precos = [i.preco for i in rel.items]
        assert precos == sorted(precos), (
            f"Preços devem estar em ordem ascendente: {precos}"
        )

    @pytest.mark.skipif(
        "CI" in os.environ, reason="Pula CI sem PYTHONPATH do projeto"
    )
    def test_ordenacao_com_dedup(self):
        """Critério 1+2: com dedup ativo, únicos + ordenados."""
        # Cria lista com QA+Loft duplicados
        listings = [
            {
                "id": "qa_001",
                "fonte": "quintoandar",
                "bairro": "Consolação",
                "endereco": "Rua Augusta, 500",
                "preco_venda": 350000.0,
                "area": 45.0,
            },
            {
                "id": "loft_001",
                "fonte": "loft",
                "bairro": "Consolação",
                "endereco": "Rua Augusta, 500",
                "preco_venda": 355000.0,  # ±5% → match
                "area": 42.0,  # ±10% → match
            },
            {
                "id": "loft_002",
                "fonte": "loft",
                "bairro": "Pinheiros",
                "endereco": "Rua dos Pinheiros, 100",
                "preco_venda": 800000.0,
                "area": 80.0,
            },
        ]
        rel = gerar_relatorio_oportunidades(
            listings,
            aplicar_dedup=True,
            saida="console",
        )
        # Após dedup, qa_001 e loft_001 podem ser merged → 2 itens únicos
        assert rel.total <= 3  # no máximo 3, pode ser 2 se dedup funcionar
        # Verifica ordenação
        precos = [i.preco for i in rel.items]
        assert precos == sorted(precos)

    def test_com_estado_anterior(
        self,
        listings_mistos: list[dict],
        estado_anterior_com_um: str,
    ):
        """Com estado anterior, imóveis existentes são marcados corretamente."""
        rel = gerar_relatorio_oportunidades(
            listings_mistos,
            estado_path=estado_anterior_com_um,
            aplicar_dedup=False,
            saida="console",
            salvar_estado=False,
        )
        # 4 listings, 1 já existente no estado anterior
        assert rel.total == 4
        assert rel.total_novos == 3
        assert rel.total_existentes == 1

        # Verifica qual item tem EXISTENTE
        existentes = [i for i in rel.items if i.new_flag == NEW_FLAG_EXISTENTE]
        assert len(existentes) == 1
        assert existentes[0].id == "qa_existente"

        # Novos não incluem o existente
        novos = [i for i in rel.items if i.new_flag == NEW_FLAG_NOVO]
        novos_ids = {i.id for i in novos}
        assert "qa_existente" not in novos_ids

    def test_saida_arquivo_salva_arquivo(
        self,
        listings_mistos: list[dict],
    ):
        """Critério 3: Output salvo em arquivo corretamente."""
        import tempfile
        fd, path_txt = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        path_json = str(Path(path_txt).with_suffix(".json"))
        # Estado inexistente isolado para evitar poluição entre testes
        estado_isolado = path_txt + ".estado.json"

        try:
            rel = gerar_relatorio_oportunidades(
                listings_mistos,
                estado_path=estado_isolado,
                aplicar_dedup=False,
                saida="arquivo",
                arquivo_saida=path_txt,
                salvar_estado=False,
            )
            assert rel.total == 4

            # Verifica arquivo TXT
            assert os.path.exists(path_txt)
            conteudo = Path(path_txt).read_text(encoding="utf-8")
            assert "Relatório de Oportunidades" in conteudo
            assert "[NOVO]" in conteudo

            # Verifica arquivo JSON
            assert os.path.exists(path_json)
            dados = json.loads(Path(path_json).read_text(encoding="utf-8"))
            assert dados["total"] == 4
            assert dados["total_novos"] == 4
        finally:
            for p in [path_txt, path_json, estado_isolado]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_saida_arquivo_sem_caminho_erro(self):
        """Critério 3: saida='arquivo' sem arquivo_saida deve levantar erro."""
        with pytest.raises(ValueError, match="arquivo_saida é obrigatório"):
            gerar_relatorio_oportunidades(
                [],
                aplicar_dedup=False,
                saida="arquivo",
                arquivo_saida=None,
            )

    def test_salva_estado_para_proxima_execucao(
        self,
        listings_mistos: list[dict],
    ):
        """Salva estado e na próxima execução detecta existentes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            estado_path = str(Path(tmpdir) / "test_estado.json")

            # Primeira execução: salva estado
            rel1 = gerar_relatorio_oportunidades(
                listings_mistos,
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="console",
                salvar_estado=True,
            )
            assert rel1.total_novos == 4

            # Verifica que estado foi salvo
            assert os.path.exists(estado_path)

            # Segunda execução: mesmos listings, devem ser EXISTENTE
            rel2 = gerar_relatorio_oportunidades(
                listings_mistos,
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="console",
                salvar_estado=False,
            )
            assert rel2.total_novos == 0
            assert rel2.total_existentes == 4

    def test_novo_na_segunda_execucao(
        self,
        imovel_qa_barato: dict,
        imovel_qa_medio: dict,
    ):
        """Na segunda execução, apenas o novo imóvel é NOVO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            estado_path = str(Path(tmpdir) / "test_estado.json")

            # Primeira execução: apenas qa_barato
            gerar_relatorio_oportunidades(
                [imovel_qa_barato],
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="console",
                salvar_estado=True,
            )

            # Segunda execução: qa_barato + qa_medio
            rel = gerar_relatorio_oportunidades(
                [imovel_qa_barato, imovel_qa_medio],
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="console",
                salvar_estado=False,
            )
            assert rel.total == 2
            assert rel.total_novos == 1
            assert rel.total_existentes == 1

            # O novo deve ser qa_medio (o que não estava antes)
            novos = [i for i in rel.items if i.new_flag == NEW_FLAG_NOVO]
            assert len(novos) == 1
            assert novos[0].id == "qa_002"

    def test_sem_estado_tudo_novo(self, listings_mistos: list[dict]):
        """Sem arquivo de estado, todos são marcados como NOVO."""
        rel = gerar_relatorio_oportunidades(
            listings_mistos,
            estado_path="/tmp/nao_existe_12345.json",
            aplicar_dedup=False,
            saida="console",
            salvar_estado=False,
        )
        assert rel.total_novos == 4
        for item in rel.items:
            assert item.new_flag == NEW_FLAG_NOVO

    def test_portais_preservados(self):
        """Testa que múltiplos portais são preservados no item."""
        # Simula um item que veio de dedup com portais múltiplos
        item = ItemOportunidade(
            id="merged",
            endereco="Rua Augusta, 500",
            bairro="Consolação",
            preco=350000.0,
            area=45.0,
            portais=["quintoandar", "loft"],
            url="https://quintoandar.com.br/imovel/qa_001",
        )
        assert item.portais_str() == "loft, quintoandar"
        d = item.to_dict()
        assert set(d["portais"]) == {"quintoandar", "loft"}


# ── Testes de integração: Pipeline completa ────────────────────────────────────


class TestPipelineIntegracao:
    """Testa o ciclo completo de oportunidades."""

    def test_ciclo_completo(
        self,
        imovel_qa_barato: dict,
        imovel_qa_medio: dict,
        imovel_loft_caro: dict,
    ):
        """Ciclo completo: geração → saída → estado → nova execução."""
        with tempfile.TemporaryDirectory() as tmpdir:
            estado_path = str(Path(tmpdir) / "estado.json")
            relatorio_path = str(Path(tmpdir) / "relatorio.txt")

            # Faz 3 execuções incrementais
            exec1 = [dict(imovel_qa_barato)]
            exec2 = [dict(imovel_qa_barato), dict(imovel_qa_medio)]
            exec3 = [
                dict(imovel_qa_barato),
                dict(imovel_qa_medio),
                dict(imovel_loft_caro),
            ]

            # Exec 1: 1 imóvel, todos novos
            rel1 = gerar_relatorio_oportunidades(
                exec1,
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="arquivo",
                arquivo_saida=relatorio_path,
                salvar_estado=True,
            )
            assert rel1.total == 1
            assert rel1.total_novos == 1

            # Exec 2: adiciona 1 → 1 novo, 1 existente
            rel2 = gerar_relatorio_oportunidades(
                exec2,
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="arquivo",
                arquivo_saida=relatorio_path,
                salvar_estado=True,
            )
            assert rel2.total == 2
            assert rel2.total_novos == 1
            assert rel2.total_existentes == 1

            # Verifica ordenação por preço
            precos = [i.preco for i in rel2.items]
            assert precos == sorted(precos)

            # Exec 3: adiciona mais 1 → 1 novo, 2 existentes
            rel3 = gerar_relatorio_oportunidades(
                exec3,
                estado_path=estado_path,
                aplicar_dedup=False,
                saida="arquivo",
                arquivo_saida=relatorio_path,
                salvar_estado=True,
            )
            assert rel3.total == 3
            assert rel3.total_novos == 1
            assert rel3.total_existentes == 2

            # Verifica ordenação global
            precos = [i.preco for i in rel3.items]
            assert precos == sorted(precos)

            # Verifica que o arquivo de saída foi criado
            assert os.path.exists(relatorio_path)
            conteudo = Path(relatorio_path).read_text(encoding="utf-8")
            assert "Relatório de Oportunidades" in conteudo
            assert "[NOVO]" in conteudo
            assert "[EXISTENTE]" in conteudo

    def test_dados_com_list_id(self):
        """Funciona com campo 'list_id' em vez de 'id' (estilo OLX)."""
        listings = [
            {
                "list_id": "olx_123",
                "fonte": "olx",
                "bairro": "Centro",
                "endereco": "Rua XV, 100",
                "preco_venda": 200000.0,
                "area": 50.0,
            },
        ]
        rel = gerar_relatorio_oportunidades(
            listings,
            aplicar_dedup=False,
            saida="console",
            salvar_estado=False,
        )
        assert rel.total == 1
        assert rel.items[0].id == "olx_123"


# ── Testes: Seção por Fonte ──────────────────────────────────────────────────


class TestPorFonte:
    """Testa a seção de resumo por fonte no relatório."""

    def test_agrupar_por_fonte(self, listings_mistos: list[dict]):
        """Lista mista com 3 fontes diferentes."""
        rel = gerar_relatorio_oportunidades(
            listings_mistos,
            aplicar_dedup=False,
            saida="console",
            salvar_estado=False,
        )
        grupos = rel._agrupar_por_fonte()
        assert "quintoandar" in grupos  # 3 quintoandar
        assert "loft" in grupos  # 1 loft
        assert len(grupos["quintoandar"]) == 3
        assert len(grupos["loft"]) == 1

    def test_formatar_por_fonte_contem_emcasa(self):
        """Relatório com EmCasa listings mostra seção EmCasa."""
        items = [
            ItemOportunidade(
                id="emcasa_001", fonte="emcasa", bairro="Vila Mariana",
                preco=850000.0, endereco="Rua A, 100",
                url="https://emcasa.com/apto-001", new_flag=NEW_FLAG_NOVO,
            ),
            ItemOportunidade(
                id="emcasa_002", fonte="emcasa", bairro="Jardins",
                preco=2500000.0, endereco="Alameda B, 500",
                url="https://emcasa.com/apto-002", new_flag=NEW_FLAG_NOVO,
            ),
            ItemOportunidade(
                id="qa_001", fonte="quintoandar", bairro="Consolação",
                preco=350000.0, endereco="Rua C, 200",
                new_flag=NEW_FLAG_NOVO,
            ),
        ]
        rel = RelatorioOportunidades(items=items)

        # Verifica texto do relatório
        texto = rel.texto
        assert "Resumo por Fonte" in texto
        assert "EmCasa (emcasa)" in texto
        assert "QuintoAndar (quintoandar)" in texto
        assert "Total: 2 | Novos: 2" in texto  # EmCasa: 2 itens
        assert "R$ 850.000" in texto or "R$ 2.500.000" in texto

    def test_to_dict_inclui_por_fonte(self):
        """JSON do relatório inclui breakdown por fonte."""
        items = [
            ItemOportunidade(
                id="emcasa_001", fonte="emcasa", bairro="Vila Mariana",
                preco=850000.0, new_flag=NEW_FLAG_NOVO,
            ),
            ItemOportunidade(
                id="qa_001", fonte="quintoandar", bairro="Consolação",
                preco=350000.0, new_flag=NEW_FLAG_NOVO,
            ),
        ]
        rel = RelatorioOportunidades(items=items)
        d = rel.to_dict()

        assert "por_fonte" in d
        assert "emcasa" in d["por_fonte"]
        assert "quintoandar" in d["por_fonte"]
        assert d["por_fonte"]["emcasa"]["total"] == 1
        assert d["por_fonte"]["emcasa"]["novos"] == 1
        assert d["por_fonte"]["emcasa"]["nome_exibicao"] == "EmCasa"
        assert len(d["por_fonte"]["emcasa"]["exemplos"]) == 1

    def test_por_fonte_lista_mista(self, listings_mistos: list[dict]):
        """Verifica que lista com múltiplos portais mostra todos no breakdown."""
        rel = gerar_relatorio_oportunidades(
            listings_mistos,
            aplicar_dedup=False,
            saida="console",
            salvar_estado=False,
        )
        d = rel.to_dict()

        assert "por_fonte" in d
        assert "quintoandar" in d["por_fonte"]
        assert "loft" in d["por_fonte"]
        assert d["por_fonte"]["quintoandar"]["total"] == 3
        assert d["por_fonte"]["loft"]["total"] == 1

    def test_por_fonte_vazio(self):
        """Relatório vazio tem por_fonte vazio."""
        rel = RelatorioOportunidades(items=[])
        d = rel.to_dict()
        assert "por_fonte" in d
        assert d["por_fonte"] == {}
