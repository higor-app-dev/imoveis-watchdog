"""
watchdog — Integração do ciclo completo de watchdog de imóveis.

Orquestra o pipeline: diff → classificação → relatório → notificação,
encadeando os módulos skills/diff, skills/classificador, skills/relatorio e
skills/notificacao sem depender de fonte de dados específica (OLX, QuintoAndar, etc.).

O Watchdog é agnóstico à fonte de extração — recebe uma lista de Imovel
já coletada e processa o ciclo de detecção de mudanças.

Uso:
    from skills.watchdog import Watchdog
    from skills.notificacao import criar_notifier

    wd = Watchdog(state_dir="data/state_snapshots")
    wd.configurar_notifier(criar_notifier(["console", "arquivo"]))

    resultado = wd.executar(imoveis_atuais)
    print(resultado["sumario"])
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from imovel_schema import Imovel, from_olx_parse


# ── Import dos módulos skills (resolvidos via PYTHONPATH) ────────────────

def _try_import(*candidates):
    """Tenta importar símbolos de múltiplos caminhos de módulo possíveis.

    Suporta duas topologias:
    1. skills/ está em PYTHONPATH → from diff.diff_imoveis import ...
    2. skills/ é um pacote → from skills.diff.diff_imoveis import ...

    A primeira que funcionar vence.
    """
    import importlib

    errors = []
    for module_path, symbols in candidates:
        try:
            mod = importlib.import_module(module_path)
            return tuple(getattr(mod, s) for s in symbols)
        except (ImportError, AttributeError) as e:
            errors.append(f"  {module_path}: {e}")
    raise ImportError(
        "Nenhum dos caminhos de import funcionou:\n" + "\n".join(errors)
    )


_MODULES_CACHE: dict[str, tuple] = {}


def _import_diff():
    """Importa módulo de diff com fallback amigável."""
    key = "diff"
    if key not in _MODULES_CACHE:
        _MODULES_CACHE[key] = _try_import(
            ("diff.diff_imoveis", ("diff_imoveis", "DiffResult")),
            ("skills.diff.diff_imoveis", ("diff_imoveis", "DiffResult")),
        )
    return _MODULES_CACHE[key]


def _import_classificador():
    """Importa módulo de classificação com fallback amigável."""
    key = "classificador"
    if key not in _MODULES_CACHE:
        _MODULES_CACHE[key] = _try_import(
            ("classificador.classificador", ("classificar_mudancas", "MudancaEvento")),
            ("skills.classificador.classificador", ("classificar_mudancas", "MudancaEvento")),
        )
    return _MODULES_CACHE[key]


def _import_relatorio():
    """Importa módulo de relatório com fallback amigável."""
    key = "relatorio"
    if key not in _MODULES_CACHE:
        _MODULES_CACHE[key] = _try_import(
            ("relatorio.relatorio", ("gerar_relatorio_console", "gerar_relatorio_json")),
            ("skills.relatorio.relatorio", ("gerar_relatorio_console", "gerar_relatorio_json")),
        )
    return _MODULES_CACHE[key]


def _import_notificacao():
    """Importa módulo de notificação com fallback amigável."""
    key = "notificacao"
    if key not in _MODULES_CACHE:
        _MODULES_CACHE[key] = _try_import(
            ("notificacao.notificacao", ("criar_notifier", "Notifier")),
            ("skills.notificacao.notificacao", ("criar_notifier", "Notifier")),
        )
    return _MODULES_CACHE[key]


# ── Tipos de resultado ────────────────────────────────────────────────────


@dataclass
class ResultadoWatchdog:
    """Resultado completo de uma execução do watchdog.

    Attributes:
        total_anterior: Quantidade de imóveis na execução anterior.
        total_atual: Quantidade de imóveis na execução atual.
        total_eventos: Quantos eventos de mudança foram detectados.
        sumario: Texto do relatório formatado (formato detailed).
        dados_json: Dict do relatório JSON (formato detailed).
        notificacoes: Dict {nome_canal: sucesso(bool)} com resultado das notificações.
        diff_result: Objeto DiffResult bruto (para inspeção programática).
        eventos: Lista de MudancaEvento (para inspeção programática).
        estado_salvo: True se o estado atual foi persistido com sucesso.
    """

    total_anterior: int = 0
    total_atual: int = 0
    total_eventos: int = 0
    sumario: str = ""
    dados_json: dict[str, Any] = field(default_factory=dict)
    notificacoes: dict[str, bool] = field(default_factory=dict)
    diff_result: Any = None
    eventos: list = field(default_factory=list)
    estado_salvo: bool = False

    @property
    def tem_mudancas(self) -> bool:
        """True se houve ao menos uma mudança detectada."""
        return self.total_eventos > 0

    def to_dict(self) -> dict[str, Any]:
        """Converte para dict serializável (JSON-safe)."""
        return {
            "total_anterior": self.total_anterior,
            "total_atual": self.total_atual,
            "total_eventos": self.total_eventos,
            "tem_mudancas": self.tem_mudancas,
            "sumario": self.sumario,
            "notificacoes": self.notificacoes,
            "estado_salvo": self.estado_salvo,
        }


# ── Watchdog principal ────────────────────────────────────────────────────


class Watchdog:
    """Orquestrador do pipeline de detecção e notificação de mudanças.

    Responsabilidades:
      - Carregar estado anterior de um arquivo JSON.
      - Executar diff entre estado anterior e atual.
      - Classificar as mudanças (novos, removidos, preço, status).
      - Gerar relatório formatado (console + JSON).
      - Notificar via canais configurados.
      - Salvar estado atual como novo estado anterior.

    Attributes:
        state_dir: Diretório onde o estado anterior é persistido.
        state_file: Nome do arquivo de estado (padrão: ultimo_estado.json).
        history_dir: Diretório para logs históricos.
        fonte_padrao: Nome da fonte usado ao persistir estado (padrão: 'watchdog').
    """

    def __init__(
        self,
        state_dir: str = "data/state_snapshots",
        state_file: str = "ultimo_estado.json",
        history_dir: str = "data/logs",
        fonte_padrao: str = "watchdog",
    ) -> None:
        self._state_dir = Path(state_dir)
        self._state_path = self._state_dir / state_file
        self._history_dir = Path(history_dir)
        self._fonte_padrao = fonte_padrao
        self._notifier: Any = None  # Notifier or None

        # Import modules lazily
        self._diff_fn, self._DiffResult = _import_diff()
        self._classificar_fn, self._MudancaEvento = _import_classificador()
        self._gerar_relatorio_console, self._gerar_relatorio_json = _import_relatorio()
        self._criar_notifier, self._Notifier = _import_notificacao()

    # ── Configuração ─────────────────────────────────────────────────────

    def configurar_notifier(self, notifier: Any) -> None:
        """Configura o Notifier multicanal para notificações.

        Args:
            notifier: Instância de Notifier (criar_notifier()) já configurada.
        """
        self._notifier = notifier

    def configurar_notifier_padrao(
        self,
        canais: Optional[list[str]] = None,
        pasta_log: str = "",
        telegram_token: str = "",
        telegram_chat_id: str = "",
    ) -> None:
        """Configura notifier com parâmetros simples (factory).

        Args:
            canais: Lista de canais a ativar (padrão: ['console', 'arquivo']).
            pasta_log: Diretório para logs do FileChannel.
            telegram_token: Token do bot Telegram.
            telegram_chat_id: Chat ID do Telegram.
        """
        pasta_log = pasta_log or str(self._history_dir)
        self._notifier = self._criar_notifier(
            canais=canais,
            pasta_log=pasta_log,
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
        )

    # ── Gestão de estado ─────────────────────────────────────────────────

    def _carregar_estado(self) -> list[Imovel]:
        """Carrega a lista de Imovel do estado anterior."""
        if not self._state_path.exists():
            return []

        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠️  Erro ao ler estado anterior: {e}. Iniciando do zero.",
                  file=sys.stderr)
            return []

        imoveis_raw = data if isinstance(data, list) else data.get("imoveis", [])
        return [Imovel.from_dict(d) for d in imoveis_raw]

    def _salvar_estado(self, imoveis: list[Imovel]) -> bool:
        """Persiste a lista atual de Imovel como estado para a próxima execução.

        Returns:
            True se salvou com sucesso.
        """
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)

            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fonte": self._fonte_padrao,
                "total": len(imoveis),
                "imoveis": [i.to_dict() for i in imoveis],
            }

            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)

            return True
        except OSError as e:
            print(f"  ❌ Erro ao salvar estado: {e}", file=sys.stderr)
            return False

    # ── Pipeline principal ───────────────────────────────────────────────

    def executar(
        self,
        imoveis_atuais: list[Imovel],
        *,
        titulo_relatorio: str = "Watchdog de Imóveis",
        formato_relatorio: str = "detailed",
        forcar_notificacao: bool = False,
        salvar_estado: bool = True,
    ) -> ResultadoWatchdog:
        """Executa o pipeline completo: diff → classificação → relatório → notificação.

        Args:
            imoveis_atuais: Lista de Imovel coletados na execução atual.
            titulo_relatorio: Título do relatório (padrão: 'Watchdog de Imóveis').
            formato_relatorio: 'summary' ou 'detailed' (padrão: 'detailed').
            forcar_notificacao: Se True, notifica mesmo sem mudanças.
            salvar_estado: Se True (padrão), persiste o estado para próxima execução.

        Returns:
            ResultadoWatchdog com sumário, notificações e metadados.
        """
        # 1. Carrega estado anterior
        imoveis_anterior = self._carregar_estado()

        # 2. Executa diff
        diff_result = self._diff_fn(imoveis_anterior, imoveis_atuais)

        # 3. Classifica mudanças
        eventos = self._classificar_fn(diff_result)

        # 4. Gera relatórios
        lookup = {i.id: i.to_dict() for i in imoveis_atuais}
        sumario = self._gerar_relatorio_console(
            eventos,
            formato=formato_relatorio,
            lookup_imovel=lookup.get,
            titulo=titulo_relatorio,
        )
        dados_json = self._gerar_relatorio_json(
            eventos,
            formato=formato_relatorio,
            lookup_imovel=lookup.get,
        )

        # 5. Notifica
        notificacoes: dict[str, bool] = {}
        tem_eventos = len(eventos) > 0

        if self._notifier is not None and (tem_eventos or forcar_notificacao):
            notificacoes = self._notifier.notify_all(
                texto=sumario,
                dados=dados_json,
            )
        elif self._notifier is not None and not tem_eventos and not forcar_notificacao:
            print("  ℹ️  Sem mudanças — notificação suprimida "
                  "(use forcar_notificacao=True para forçar).")

        # 6. Salva estado para próxima execução
        estado_salvo = False
        if salvar_estado:
            estado_salvo = self._salvar_estado(imoveis_atuais)

        return ResultadoWatchdog(
            total_anterior=len(imoveis_anterior),
            total_atual=len(imoveis_atuais),
            total_eventos=len(eventos),
            sumario=sumario,
            dados_json=dados_json,
            notificacoes=notificacoes,
            diff_result=diff_result,
            eventos=eventos,
            estado_salvo=estado_salvo,
        )

    # ── Atalhos ──────────────────────────────────────────────────────────

    def executar_de_dicts(
        self,
        dicts_atuais: list[dict[str, Any]],
        *,
        fonte: str = "",
        **kwargs: Any,
    ) -> ResultadoWatchdog:
        """Atalho: recebe lista de dicts e converte para Imovel antes de executar.

        Args:
            dicts_atuais: Lista de dicts no formato Imovel (to_dict()).
            fonte: Nome da fonte (ex.: 'olx', 'quintoandar'). Sobrescreve
                   o campo fonte de cada Imovel.
            **kwargs: Repassados para executar().

        Returns:
            ResultadoWatchdog.
        """
        imoveis = [Imovel.from_dict(d) for d in dicts_atuais]
        if fonte:
            for imovel in imoveis:
                imovel.fonte = fonte
        return self.executar(imoveis, **kwargs)

    def notificar_agora(
        self,
        texto: str,
        dados: Optional[dict] = None,
    ) -> dict[str, bool]:
        """Atalho para notificar um texto arbitrário via canais configurados.

        Útil para alertas manuais (ex.: erro na coleta, manutenção).

        Args:
            texto: Texto da notificação.
            dados: Dict estruturado opcional.

        Returns:
            Dict {nome_canal: sucesso(bool)}.
        """
        if self._notifier is None:
            print("  ⚠️  Nenhum notifier configurado. Use configurar_notifier().",
                  file=sys.stderr)
            return {}
        return self._notifier.notify_all(texto=texto, dados=dados)
