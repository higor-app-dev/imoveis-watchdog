"""
notificacao — Sistema de notificação multicanal.

Implementa um Notifier que aceita múltiplos canais de notificação
e os aciona em sequência. Cada canal segue a interface NotifierChannel,
permitindo adicionar novos canais (ex: Telegram real) sem modificar o núcleo.

Uso:
    from notificacao import criar_notifier, ConsoleChannel, FileChannel

    # Monta o notifier com os canais desejados
    notifier = criar_notifier(
        canais=["console", "arquivo"],
        pasta_log="data/logs",
    )

    # Notifica
    notifier.notify_all(
        texto="Relatório de mudanças...",
        dados={"versao": 1, "eventos": [...]},
    )
"""

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ── Interface ──────────────────────────────────────────────────────────────


class NotifierChannel(ABC):
    """Interface que todo canal de notificação deve implementar."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Nome único do canal (ex: 'console', 'arquivo', 'telegram')."""
        ...

    @abstractmethod
    def send(self, texto: str, dados: Optional[dict] = None) -> None:
        """Envia a notificação por este canal.

        Args:
            texto: Texto formatado da notificação (console-ready).
            dados: Dict estruturado opcional (JSON, usado por canais
                   que precisam dos dados crus, como Telegram).
        """
        ...


# ── Canais concretos ──────────────────────────────────────────────────────


class ConsoleChannel(NotifierChannel):
    """Canal que imprime o relatório no console."""

    @property
    def nome(self) -> str:
        return "console"

    def send(self, texto: str, dados: Optional[dict] = None) -> None:
        sep = "─" * 60
        print(f"\n{sep}", file=sys.stdout)
        print("  📋 NOTIFICAÇÃO — Console", file=sys.stdout)
        print(f"{sep}", file=sys.stdout)
        print(texto, file=sys.stdout)
        print(f"{sep}\n", file=sys.stdout)
        sys.stdout.flush()


class FileChannel(NotifierChannel):
    """Canal que salva o relatório em arquivo de log com data/hora.

    Os logs são salvos em ``pasta_log/notificacao_YYYY-MM-DD_HH-MM-SS.log``.
    """

    def __init__(self, pasta_log: str = "data/logs") -> None:
        self._pasta = Path(pasta_log)

    @property
    def nome(self) -> str:
        return "arquivo"

    def send(self, texto: str, dados: Optional[dict] = None) -> None:
        self._pasta.mkdir(parents=True, exist_ok=True)

        agora = datetime.now()
        ts_arquivo = agora.strftime("%Y-%m-%d_%H-%M-%S")
        ts_legivel = agora.strftime("%Y-%m-%d %H:%M:%S")
        caminho = self._pasta / f"notificacao_{ts_arquivo}.log"

        with open(caminho, "w", encoding="utf-8") as f:
            f.write(f"=== Notificação — {ts_legivel} ===\n\n")
            f.write(texto)
            f.write("\n")

            if dados is not None:
                f.write("\n── Dados Estruturados ──────────────────────\n\n")
                json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
                f.write("\n")

        print(f"  📄 Notificação salva em: {caminho}", file=sys.stdout)


class TelegramChannel(NotifierChannel):
    """Canal Telegram — STUB.

    Placeholder para futura integração com Telegram real.
    Por enquanto apenas loga que enviaria a mensagem.
    Para ativar, substitua esta classe por uma implementação
    que use python-telegram-bot, requests, ou similar.
    """

    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self._token = token
        self._chat_id = chat_id

    @property
    def nome(self) -> str:
        return "telegram"

    @property
    def configurado(self) -> bool:
        """True se token e chat_id foram fornecidos."""
        return bool(self._token and self._chat_id)

    def send(self, texto: str, dados: Optional[dict] = None) -> None:
        if not self.configurado:
            print(
                "  ⚠️  Telegram: não configurado (token/chat_id vazios). "
                "Notificação simulada.",
                file=sys.stdout,
            )
        print(
            f"  📨 Telegram enviaria:\n"
            f"     Token: {'***' if self._token else '(vazio)'}\n"
            f"     ChatID: {self._chat_id or '(vazio)'}",
            file=sys.stdout,
        )
        # Exibe as primeiras linhas como preview
        linhas = texto.strip().split("\n")
        preview = "\n".join(linhas[:5])
        if len(linhas) > 5:
            preview += f"\n     ... (+{len(linhas) - 5} linhas)"
        print(f"     Preview:\n{preview}", file=sys.stdout)
        sys.stdout.flush()


# ── Notifier (orquestrador) ────────────────────────────────────────────────


class Notifier:
    """Orquestrador de canais de notificação.

    Mantém um registro de canais disponíveis e um conjunto de canais ativos.
    ``notify_all`` itera sobre os canais ativos e chama ``send`` em cada um.
    """

    def __init__(self) -> None:
        self._canais: dict[str, NotifierChannel] = {}
        self._ativos: set[str] = set()

    # ── Gerenciamento de canais ──────────────────────────────────────────

    def registrar(self, canal: NotifierChannel) -> None:
        """Registra um canal no notifier (disponível mas não necessariamente ativo)."""
        self._canais[canal.nome] = canal

    def ativar(self, nome: str) -> None:
        """Ativa um canal registrado pelo nome."""
        if nome not in self._canais:
            raise KeyError(
                f"Canal '{nome}' não registrado. "
                f"Registrados: {list(self._canais.keys())}"
            )
        self._ativos.add(nome)

    def desativar(self, nome: str) -> None:
        """Desativa um canal."""
        self._ativos.discard(nome)

    @property
    def canais_disponiveis(self) -> list[str]:
        """Lista de nomes de canais registrados."""
        return list(self._canais.keys())

    @property
    def canais_ativos(self) -> list[str]:
        """Lista de nomes de canais atualmente ativos."""
        return sorted(self._ativos)

    # ── Notificação ──────────────────────────────────────────────────────

    def notify_all(
        self,
        texto: str,
        dados: Optional[dict] = None,
    ) -> dict[str, bool]:
        """Aciona todos os canais ativos e retorna dict com status.

        Args:
            texto: Texto formatado da notificação.
            dados: Dict estruturado opcional.

        Returns:
            Dict ``{nome_canal: sucesso(bool)}``.
        """
        resultados: dict[str, bool] = {}
        for nome in sorted(self._ativos):
            canal = self._canais[nome]
            try:
                canal.send(texto, dados)
                resultados[nome] = True
            except Exception as e:
                print(
                    f"  ❌ Erro no canal '{nome}': {e}",
                    file=sys.stderr,
                )
                resultados[nome] = False
        return resultados


# ── Factory ────────────────────────────────────────────────────────────────


def criar_notifier(
    canais: Optional[list[str]] = None,
    pasta_log: str = "data/logs",
    telegram_token: str = "",
    telegram_chat_id: str = "",
) -> Notifier:
    """Cria um Notifier configurado com os canais especificados.

    Args:
        canais: Lista de nomes de canais a ativar.
                Padrão: ['console', 'arquivo'].
                Opções: 'console', 'arquivo', 'telegram'.
        pasta_log: Diretório para logs do FileChannel.
        telegram_token: Token do bot Telegram (para canal telegram).
        telegram_chat_id: Chat ID do Telegram (para canal telegram).

    Returns:
        Notifier configurado.
    """
    if canais is None:
        canais = ["console", "arquivo"]

    notifier = Notifier()

    # Registra todos os canais disponíveis
    notifier.registrar(ConsoleChannel())
    notifier.registrar(FileChannel(pasta_log=pasta_log))
    notifier.registrar(TelegramChannel(token=telegram_token, chat_id=telegram_chat_id))

    # Ativa os solicitados
    for nome in canais:
        if nome not in ("console", "arquivo", "telegram"):
            raise ValueError(
                f"Canal desconhecido: '{nome}'. "
                f"Opções: 'console', 'arquivo', 'telegram'."
            )
        notifier.ativar(nome)

    return notifier
