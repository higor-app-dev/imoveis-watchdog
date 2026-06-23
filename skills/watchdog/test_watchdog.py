"""
Testes para o módulo watchdog — integração completa do pipeline.

Uso:
    cd /home/higor/imoveis-watchdog
    PYTHONPATH="$HOME/.hermes:skills:skills/quinto-andar" python3 -m pytest skills/watchdog/test_watchdog.py -v

Uso com cobertura:
    PYTHONPATH="$HOME/.hermes:skills:skills/quinto-andar" python3 -m pytest skills/watchdog/test_watchdog.py -v --tb=short
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from imovel_schema import Imovel

# ── Helpers ────────────────────────────────────────────────────────────────


def _criar_imovel(
    id_: str,
    preco_venda: float | None = 500000.0,
    bairro: str = "Vila Mariana",
    fonte: str = "test",
    titulo: str = "Apto teste",
    status: str = "ativo",
    disponivel: bool = True,
    **extra,
) -> Imovel:
    """Cria um Imovel com valores padrão para testes."""
    return Imovel(
        id=id_,
        titulo=titulo,
        url=f"https://exemplo.com/{id_}",
        fonte=fonte,
        bairro=bairro,
        cidade="São Paulo",
        uf="SP",
        preco_venda=preco_venda,
        preco_aluguel=None,
        area=50.0,
        quartos=2,
        banheiros=1,
        vagas=1,
        tipo="apartamento",
        status=status,
        disponivel=disponivel,
        data_coleta=datetime.now(timezone.utc).isoformat(),
        **extra,
    )


# ── Testes do Watchdog ────────────────────────────────────────────────────


class TestWatchdogConstructor:
    """Verifica construção e configuração básica."""

    def test_cria_com_caminhos_padrao(self):
        """Watchdog usa paths padrão quando não especificados."""
        from skills.watchdog import Watchdog

        wd = Watchdog()
        assert wd._state_dir.name == "state_snapshots"
        assert wd._state_path.name == "ultimo_estado.json"
        assert wd._history_dir.name == "logs"
        assert wd._fonte_padrao == "watchdog"

    def test_cria_com_caminhos_personalizados(self):
        """Watchdog aceita paths personalizados."""
        from skills.watchdog import Watchdog

        wd = Watchdog(
            state_dir="/tmp/test_watchdog_state",
            state_file="meu_estado.json",
            history_dir="/tmp/test_watchdog_logs",
            fonte_padrao="quintoandar",
        )
        assert wd._state_dir == Path("/tmp/test_watchdog_state")
        assert wd._state_path == Path("/tmp/test_watchdog_state") / "meu_estado.json"
        assert wd._history_dir == Path("/tmp/test_watchdog_logs")
        assert wd._fonte_padrao == "quintoandar"

    def test_configurar_notifier(self):
        """configurar_notifier aceita um Notifier."""
        from skills.watchdog import Watchdog
        from skills.notificacao import criar_notifier

        wd = Watchdog()
        assert wd._notifier is None

        notifier = criar_notifier(["console"])
        wd.configurar_notifier(notifier)
        assert wd._notifier is not None

    def test_configurar_notifier_padrao(self):
        """configurar_notifier_padrao cria e configura notifier."""
        from skills.watchdog import Watchdog

        wd = Watchdog()
        wd.configurar_notifier_padrao(canais=["console"])

        assert wd._notifier is not None
        canais = wd._notifier.canais_ativos
        assert "console" in canais


class TestWatchdogEstado:
    """Verifica carregamento e salvamento de estado."""

    def test_carregar_estado_inexistente_retorna_vazio(self):
        """Sem arquivo de estado, retorna lista vazia."""
        from skills.watchdog import Watchdog

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir, state_file="nao_existe.json")
            estado = wd._carregar_estado()
            assert estado == []

    def test_salvar_e_carregar_estado(self):
        """Salva estado e carrega de volta, preservando dados."""
        from skills.watchdog import Watchdog

        imoveis = [
            _criar_imovel("id_001", preco_venda=450000.0),
            _criar_imovel("id_002", preco_venda=550000.0, bairro="Pinheiros"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)

            # Salva
            ok = wd._salvar_estado(imoveis)
            assert ok
            assert wd._state_path.exists()

            # Carrega
            carregados = wd._carregar_estado()
            assert len(carregados) == 2
            assert carregados[0].id == "id_001"
            assert carregados[0].preco_venda == 450000.0
            assert carregados[1].bairro == "Pinheiros"

    def test_salvar_estado_cria_diretorio(self):
        """Salva estado cria diretório intermediário se não existir."""
        from skills.watchdog import Watchdog

        imoveis = [_criar_imovel("id_001")]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "subdir" / "nested"
            wd = Watchdog(state_dir=str(state_dir))

            ok = wd._salvar_estado(imoveis)
            assert ok
            assert state_dir.exists()
            assert (state_dir / "ultimo_estado.json").exists()

    def test_carregar_estado_json_corrompido_retorna_vazio(self):
        """Arquivo JSON inválido retorna lista vazia sem crash."""
        from skills.watchdog import Watchdog

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ultimo_estado.json"
            state_path.write_text("json invalido {{{", encoding="utf-8")

            wd = Watchdog(state_dir=tmpdir)
            estado = wd._carregar_estado()
            assert estado == []


class TestWatchdogExecutar:
    """Verifica o pipeline completo: diff → classificação → relatório → notificação."""

    def test_primeira_execucao_sem_estado_anterior(self):
        """Primeira execução: sem estado anterior, tudo é 'novo'."""
        from skills.watchdog import Watchdog

        imoveis = [
            _criar_imovel("id_001"),
            _criar_imovel("id_002"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            resultado = wd.executar(imoveis, salvar_estado=True)

            assert resultado.total_anterior == 0
            assert resultado.total_atual == 2
            assert resultado.total_eventos == 2  # 2 novos
            assert resultado.tem_mudancas
            assert resultado.estado_salvo
            assert "Novos" in resultado.sumario
            assert "2" in resultado.sumario[:50]  # contagem aparece cedo no relatório

    def test_segunda_execucao_sem_mudancas(self):
        """Segunda execução sem mudanças: zero eventos, estado salvo."""
        from skills.watchdog import Watchdog

        imoveis = [
            _criar_imovel("id_001", preco_venda=450000.0),
            _criar_imovel("id_002", preco_venda=550000.0),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)

            # Primeira execução
            r1 = wd.executar(imoveis)
            assert r1.total_eventos == 2
            assert r1.estado_salvo

            # Segunda execução — mesmos dados, sem mudanças
            r2 = wd.executar(imoveis)
            assert r2.total_eventos == 0
            assert not r2.tem_mudancas
            assert r2.estado_salvo
            assert "Total: 0 evento(s)" in r2.sumario

    def test_deteccao_de_novo_imovel(self):
        """Detecta imóvel novo entre execuções."""
        from skills.watchdog import Watchdog

        anteriores = [_criar_imovel("id_001")]
        atuais = [
            _criar_imovel("id_001"),
            _criar_imovel("id_002"),  # novo!
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)

            # Pré-popula estado
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            assert resultado.total_eventos == 1
            assert resultado.total_anterior == 1
            assert resultado.total_atual == 2
            assert "Novos" in resultado.sumario

    def test_deteccao_de_remocao(self):
        """Detecta imóvel removido entre execuções."""
        from skills.watchdog import Watchdog

        anteriores = [
            _criar_imovel("id_001"),
            _criar_imovel("id_002"),
        ]
        atuais = [_criar_imovel("id_001")]  # id_002 removido!

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            assert resultado.total_eventos == 1
            assert resultado.total_anterior == 2
            assert resultado.total_atual == 1
            assert "Removidos" in resultado.sumario

    def test_deteccao_de_reducao_preco(self):
        """Detecta redução de preço (oportunidade)."""
        from skills.watchdog import Watchdog

        anteriores = [_criar_imovel("id_001", preco_venda=500000.0)]
        atuais = [_criar_imovel("id_001", preco_venda=450000.0)]  # -50k

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            assert resultado.total_eventos == 1
            evento = resultado.eventos[0]
            assert evento.tipo == "price_decrease"
            assert evento.campo == "preco_venda"
            assert evento.valor_anterior == 500000.0
            assert evento.valor_novo == 450000.0
            assert "Redução de Preço" in resultado.sumario

    def test_deteccao_de_aumento_preco(self):
        """Detecta aumento de preço."""
        from skills.watchdog import Watchdog

        anteriores = [_criar_imovel("id_001", preco_venda=450000.0)]
        atuais = [_criar_imovel("id_001", preco_venda=500000.0)]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            assert resultado.total_eventos == 1
            assert resultado.eventos[0].tipo == "price_increase"
            assert "Aumento de Preço" in resultado.sumario

    def test_deteccao_de_mudanca_status(self):
        """Detecta mudança de status (disponivel, status)."""
        from skills.watchdog import Watchdog

        anteriores = [_criar_imovel("id_001", status="ativo")]
        atuais = [_criar_imovel("id_001", status="inativo")]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            assert resultado.total_eventos == 1
            assert resultado.eventos[0].tipo == "status_change"
            assert resultado.eventos[0].campo == "status"
            assert "Mudança de Status" in resultado.sumario

    def test_multiplas_mudancas_simultaneas(self):
        """Detecta múltiplos tipos de mudança numa execução."""
        from skills.watchdog import Watchdog

        anteriores = [
            _criar_imovel("id_001", preco_venda=500000.0),
            _criar_imovel("id_002", preco_venda=300000.0),
            _criar_imovel("id_003", preco_venda=400000.0),
        ]
        atuais = [
            _criar_imovel("id_001", preco_venda=450000.0),  # redução
            _criar_imovel("id_003", preco_venda=400000.0),  # igual
            _criar_imovel("id_004", preco_venda=600000.0),  # novo!
        ]
        # id_002 removido, id_004 novo, id_001 redução

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            # 1 removido (id_002) + 1 novo (id_004) + 1 redução (id_001) = 3
            assert resultado.total_eventos == 3
            assert resultado.total_anterior == 3
            assert resultado.total_atual == 3

            tipos = [e.tipo for e in resultado.eventos]
            assert "new" in tipos
            assert "removed" in tipos
            assert "price_decrease" in tipos
            assert "Redução" in resultado.sumario
            assert "Novos" in resultado.sumario
            assert "Removidos" in resultado.sumario

    def test_notificacao_com_notifier_configurado(self):
        """Notificação é enviada quando há mudanças e notifier configurado."""
        from skills.watchdog import Watchdog
        from skills.notificacao import criar_notifier

        anteriores = [_criar_imovel("id_001")]
        atuais = [
            _criar_imovel("id_001"),
            _criar_imovel("id_002"),  # novo
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd.configurar_notifier(criar_notifier(["console"]))
            wd._salvar_estado(anteriores)

            resultado = wd.executar(atuais)
            assert resultado.total_eventos == 1
            assert "console" in resultado.notificacoes
            assert resultado.notificacoes["console"] is True

    def test_forcar_notificacao_sem_mudancas(self):
        """forcar_notificacao=True notifica mesmo sem mudanças."""
        from skills.watchdog import Watchdog
        from skills.notificacao import criar_notifier

        imoveis = [_criar_imovel("id_001")]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd.configurar_notifier(criar_notifier(["console"]))
            wd._salvar_estado(imoveis)

            resultado = wd.executar(imoveis, forcar_notificacao=True)
            assert resultado.total_eventos == 0
            # Ainda notificou porque forcar_notificacao=True
            assert "console" in resultado.notificacoes

    def test_salvar_estado_false_mantem_estado_anterior(self):
        """salvar_estado=False não sobrescreve o arquivo de estado."""
        from skills.watchdog import Watchdog

        anteriores = [_criar_imovel("id_001")]
        atuais = [_criar_imovel("id_002")]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            wd._salvar_estado(anteriores)

            # Executa sem salvar
            resultado = wd.executar(atuais, salvar_estado=False)
            assert resultado.estado_salvo is False

            # Estado anterior ainda é o original
            carregados = wd._carregar_estado()
            assert len(carregados) == 1
            assert carregados[0].id == "id_001"

    def test_salvar_estado_persiste_para_proxima_execucao(self):
        """salvar_estado=True persiste o estado atual."""
        from skills.watchdog import Watchdog

        imoveis_rodada_1 = [_criar_imovel("id_001")]
        imoveis_rodada_2 = [
            _criar_imovel("id_001"),
            _criar_imovel("id_002"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)

            # Rodada 1: 1 imóvel, salva
            r1 = wd.executar(imoveis_rodada_1)
            assert r1.total_eventos == 1  # tudo novo

            # Rodada 2: 2 imóveis, usa estado da rodada 1
            r2 = wd.executar(imoveis_rodada_2)
            assert r2.total_anterior == 1
            assert r2.total_atual == 2
            assert r2.total_eventos == 1  # só id_002 é novo


class TestWatchdogAtalhos:
    """Verifica métodos de conveniência."""

    def test_executar_de_dicts(self):
        """executar_de_dicts aceita listas de dicts."""
        from skills.watchdog import Watchdog

        dicts = [
            {"id": "d_001", "preco_venda": 500000.0, "bairro": "Centro",
             "cidade": "São Paulo", "uf": "SP", "fonte": "test",
             "titulo": "Teste", "url": "https://exemplo.com/1"},
            {"id": "d_002", "preco_venda": 600000.0, "bairro": "Pinheiros",
             "cidade": "São Paulo", "uf": "SP", "fonte": "test",
             "titulo": "Teste 2", "url": "https://exemplo.com/2"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            resultado = wd.executar_de_dicts(dicts)

            assert resultado.total_eventos == 2
            assert resultado.total_atual == 2

    def test_executar_de_dicts_com_fonte(self):
        """executar_de_dicts aceita override de fonte."""
        from skills.watchdog import Watchdog

        dicts = [
            {"id": "d_001", "preco_venda": 500000.0, "bairro": "Centro",
             "cidade": "São Paulo", "uf": "SP", "fonte": "olx",
             "titulo": "Teste", "url": "https://exemplo.com/1"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            wd = Watchdog(state_dir=tmpdir)
            resultado = wd.executar_de_dicts(dicts, fonte="quintoandar")

            assert resultado.total_eventos == 1

    def test_notificar_agora_sem_notifier_retorna_vazio(self):
        """notificar_agora sem notifier configurado retorna dict vazio."""
        from skills.watchdog import Watchdog

        wd = Watchdog()
        resultado = wd.notificar_agora("teste")
        assert resultado == {}

    def test_notificar_agora_com_notifier(self):
        """notificar_agora com notifier envia a mensagem."""
        from skills.watchdog import Watchdog
        from skills.notificacao import criar_notifier

        wd = Watchdog()
        wd.configurar_notifier(criar_notifier(["console"]))
        resultado = wd.notificar_agora("Alerta de teste!")
        assert "console" in resultado
        assert resultado["console"] is True


class TestWatchdogResultado:
    """Verifica o objeto ResultadoWatchdog."""

    def test_tem_mudancas_property(self):
        """tem_mudancas reflete a presença de eventos."""
        from skills.watchdog import ResultadoWatchdog

        r1 = ResultadoWatchdog(total_eventos=3)
        assert r1.tem_mudancas

        r2 = ResultadoWatchdog(total_eventos=0)
        assert not r2.tem_mudancas

    def test_to_dict_serializavel(self):
        """to_dict produz dict JSON-safe."""
        from skills.watchdog import ResultadoWatchdog

        r = ResultadoWatchdog(
            total_anterior=5,
            total_atual=7,
            total_eventos=2,
            sumario="=== Relatório ===",
            notificacoes={"console": True},
            estado_salvo=True,
        )

        d = r.to_dict()
        assert d["total_anterior"] == 5
        assert d["total_atual"] == 7
        assert d["total_eventos"] == 2
        assert d["tem_mudancas"] is True
        assert d["notificacoes"]["console"] is True
        assert d["estado_salvo"] is True

        # Deve ser JSON-serializável
        json_str = json.dumps(d, ensure_ascii=False, default=str)
        recarregado = json.loads(json_str)
        assert recarregado["total_eventos"] == 2
