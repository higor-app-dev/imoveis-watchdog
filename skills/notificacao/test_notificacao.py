"""
Testes para notificacao — sistema de notificação multicanal.

Uso:
    cd /home/higor/imoveis-watchdog
    PYTHONPATH="$HOME/.hermes:skills:skills/notificacao" python3 -m pytest \
        skills/notificacao/test_notificacao.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from notificacao import (
    Notifier,
    NotifierChannel,
    ConsoleChannel,
    FileChannel,
    TelegramChannel,
    criar_notifier,
)

# ── Helpers ────────────────────────────────────────────────────────────────

_TEXTO_EXEMPLO = (
    "=== Relatório de Mudanças ===\n"
    "  Novos:            2\n"
    "  Removidos:        1\n"
    "  Redução de Preço: 0\n"
    "  Aumento de Preço: 1\n"
    "  ────────────────────────────────────\n"
    "  Total: 4 evento(s)\n"
    "\n"
    "── Novos (2) ─────────────────────────\n"
    "\n"
    "  [apto_001] Apto Barra — R$ 450.000 — Barra da Tijuca\n"
    "    https://exemplo.com/apto_001\n"
    "\n"
    "  [apto_002] Cobertura Ipanema — R$ 1.200.000 — Ipanema\n"
    "    https://exemplo.com/apto_002\n"
)

_DADOS_EXEMPLO = {
    "versao": 1,
    "resumo": {"novos": 2, "removidos": 1, "price_decrease": 0, "price_increase": 1, "status_change": 0, "total": 4},
    "eventos": [
        {"tipo": "new", "id_imovel": "apto_001"},
        {"tipo": "new", "id_imovel": "apto_002"},
        {"tipo": "removed", "id_imovel": "apto_003"},
        {"tipo": "price_increase", "id_imovel": "apto_004", "campo": "preco_venda", "valor_anterior": 500000, "valor_novo": 550000},
    ],
}


# ── Tests: ConsoleChannel ──────────────────────────────────────────────────


def test_console_channel_nome():
    canal = ConsoleChannel()
    assert canal.nome == "console"


def test_console_channel_send(capsys):
    canal = ConsoleChannel()
    canal.send(_TEXTO_EXEMPLO, _DADOS_EXEMPLO)
    capturado = capsys.readouterr()
    assert "NOTIFICAÇÃO" in capturado.out
    assert "Novos:" in capturado.out
    assert capturado.err == ""


# ── Tests: FileChannel ─────────────────────────────────────────────────────


def test_file_channel_nome():
    canal = FileChannel(pasta_log="/tmp/nao_usado")
    assert canal.nome == "arquivo"


def test_file_channel_send_cria_arquivo():
    with tempfile.TemporaryDirectory() as tmpdir:
        canal = FileChannel(pasta_log=tmpdir)
        canal.send(_TEXTO_EXEMPLO, _DADOS_EXEMPLO)

        # Deve ter criado exatamente um arquivo .log
        arquivos = list(Path(tmpdir).glob("notificacao_*.log"))
        assert len(arquivos) == 1

        conteudo = arquivos[0].read_text(encoding="utf-8")
        assert "=== Notificação" in conteudo
        assert _TEXTO_EXEMPLO.strip() in conteudo
        assert "Dados Estruturados" in conteudo
        assert '"versao": 1' in conteudo


def test_file_channel_send_sem_dados():
    with tempfile.TemporaryDirectory() as tmpdir:
        canal = FileChannel(pasta_log=tmpdir)
        canal.send("apenas texto")

        arquivos = list(Path(tmpdir).glob("notificacao_*.log"))
        assert len(arquivos) == 1
        conteudo = arquivos[0].read_text(encoding="utf-8")
        assert "apenas texto" in conteudo
        assert "Dados Estruturados" not in conteudo


def test_file_channel_cria_pasta_automaticamente():
    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = os.path.join(tmpdir, "sub", "logs")
        canal = FileChannel(pasta_log=subdir)
        canal.send("teste")
        assert Path(subdir).exists()
        arquivos = list(Path(subdir).glob("notificacao_*.log"))
        assert len(arquivos) == 1


# ── Tests: TelegramChannel (stub) ──────────────────────────────────────────


def test_telegram_channel_nome():
    canal = TelegramChannel()
    assert canal.nome == "telegram"


def test_telegram_channel_nao_configurado():
    canal = TelegramChannel()
    assert not canal.configurado


def test_telegram_channel_configurado():
    canal = TelegramChannel(token="abc123", chat_id="-1000000")
    assert canal.configurado


def test_telegram_channel_send_simula(capsys):
    canal = TelegramChannel(token="abc123", chat_id="-1000000")
    canal.send(_TEXTO_EXEMPLO, _DADOS_EXEMPLO)
    capturado = capsys.readouterr()
    assert "Telegram enviaria" in capturado.out
    assert "ChatID: -1000000" in capturado.out
    assert "Preview" in capturado.out


# ── Tests: Notifier (orquestrador) ─────────────────────────────────────────


def test_notifier_vazio():
    n = Notifier()
    assert n.canais_disponiveis == []
    assert n.canais_ativos == []


def test_notifier_registrar_e_ativar():
    n = Notifier()
    n.registrar(ConsoleChannel())
    assert n.canais_disponiveis == ["console"]
    assert n.canais_ativos == []

    n.ativar("console")
    assert n.canais_ativos == ["console"]


def test_notifier_ativar_canal_inexistente():
    n = Notifier()
    with pytest.raises(KeyError):
        n.ativar("nao_existe")


def test_notifier_desativar():
    n = Notifier()
    n.registrar(ConsoleChannel())
    n.ativar("console")
    n.desativar("console")
    assert n.canais_ativos == []


def test_notifier_desativar_nao_registrado_nao_erro():
    """Desativar canal não registrado não deve levantar exceção."""
    n = Notifier()
    n.desativar("console")  # não existe — só discarta
    assert n.canais_ativos == []


def test_notifier_notify_all_console(capsys):
    n = Notifier()
    n.registrar(ConsoleChannel())
    n.ativar("console")

    resultados = n.notify_all(texto=_TEXTO_EXEMPLO, dados=_DADOS_EXEMPLO)
    assert resultados == {"console": True}

    capturado = capsys.readouterr()
    assert "NOTIFICAÇÃO" in capturado.out


def test_notifier_notify_all_multiplos_canais(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        n = Notifier()
        n.registrar(ConsoleChannel())
        n.registrar(FileChannel(pasta_log=tmpdir))
        n.registrar(TelegramChannel(token="t", chat_id="c"))
        n.ativar("console")
        n.ativar("arquivo")

        resultados = n.notify_all(texto=_TEXTO_EXEMPLO, dados=_DADOS_EXEMPLO)
        assert resultados == {"arquivo": True, "console": True}

        capturado = capsys.readouterr()
        assert "NOTIFICAÇÃO" in capturado.out
        assert "Notificação salva em:" in capturado.out

        # Arquivo foi criado
        arquivos = list(Path(tmpdir).glob("notificacao_*.log"))
        assert len(arquivos) >= 1


def test_notifier_notify_all_canal_falha_continua(capsys):
    """Se um canal falha, os outros devem continuar."""

    class CanalQuebrado(NotifierChannel):
        @property
        def nome(self):
            return "quebrado"

        def send(self, texto, dados=None):
            raise RuntimeError("Falha simulada")

    n = Notifier()
    n.registrar(CanalQuebrado())
    n.registrar(ConsoleChannel())
    n.ativar("quebrado")
    n.ativar("console")

    resultados = n.notify_all(texto="teste")
    assert resultados == {"console": True, "quebrado": False}

    capturado = capsys.readouterr()
    # A mensagem de erro vai pra stderr
    assert "Erro no canal 'quebrado'" in capturado.err


# ── Tests: criar_notifier (factory) ────────────────────────────────────────


def test_criar_notifier_default():
    n = criar_notifier()
    assert n.canais_ativos == sorted(["console", "arquivo"])


def test_criar_notifier_canais_personalizados():
    n = criar_notifier(canais=["console"])
    assert n.canais_ativos == ["console"]


def test_criar_notifier_telegram():
    n = criar_notifier(
        canais=["console", "telegram"],
        telegram_token="tok",
        telegram_chat_id="cid",
    )
    assert n.canais_ativos == sorted(["console", "telegram"])


def test_criar_notifier_canal_desconhecido():
    with pytest.raises(ValueError, match="Canal desconhecido"):
        criar_notifier(canais=["whatsapp"])


# ── Testes de integração: notificar após relatório ─────────────────────────


def test_ciclo_completo_console_arquivo(capsys):
    """Simula o fluxo: gerar relatório → notificar (console + arquivo)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        notifier = criar_notifier(
            canais=["console", "arquivo"],
            pasta_log=tmpdir,
        )

        # Ação: notificar com texto formatado e dados estruturados
        resultados = notifier.notify_all(
            texto=_TEXTO_EXEMPLO,
            dados=_DADOS_EXEMPLO,
        )

        # Verifica: console
        capturado = capsys.readouterr()
        assert "NOTIFICAÇÃO" in capturado.out
        assert "Novos:" in capturado.out
        assert "Notificação salva em:" in capturado.out

        # Verifica: arquivo
        arquivos = list(Path(tmpdir).glob("notificacao_*.log"))
        assert len(arquivos) == 1
        conteudo = arquivos[0].read_text(encoding="utf-8")
        assert _TEXTO_EXEMPLO.strip() in conteudo
        assert '"versao": 1' in conteudo

        # Verifica: status
        assert resultados == {"arquivo": True, "console": True}


def test_adicionar_canal_sem_modificar_notifier():
    """Verifica que é possível adicionar um canal novo sem modificar o Notifier."""
    n = Notifier()
    n.registrar(ConsoleChannel())
    n.ativar("console")

    # Adiciona canal no mesmo Notifier — sem modificar classe base
    n.registrar(FileChannel(pasta_log="/tmp"))
    n.ativar("arquivo")
    assert "arquivo" in n.canais_ativos
    assert "console" in n.canais_ativos
