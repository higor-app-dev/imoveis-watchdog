"""
portal_registry — Registro central e loader dinâmico de portais.

Carrega configuração de config/portals.yaml, descobre módulos parser
dinamicamente e expõe interface unificada de parsing.

Uso:
    from portal_registry import PortalInfo, get_portal, list_active_portals
    from portal_registry import from_listing, from_payload, call_parser

    # Descobrir portais ativos
    for p in list_active_portals():
        print(p.display_name, p.base_url)

    # Parse uma listagem individual
    portal = get_portal("quinto_andar")
    imovel = from_listing("quinto_andar", raw_listing_dict)

    # Parse um payload de busca
    imoveis = from_payload("loft", api_response)

    # Chamar qualquer função do parser por nome
    url = call_parser("quinto_andar", "build_quintoandar_url", listing)
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("portal_registry")

# ── Config path resolution ──────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "portals.yaml"


# ── PortalInfo dataclass ────────────────────────────────────────────────────


@dataclass
class PortalInfo:
    """Informações descritivas e funcionais de um portal.

    Atributos:
        slug: Chave YAML do portal (ex.: "quinto_andar", "loft").
        name: Valor usado em Imovel.fonte (ex.: "quintoandar").
        display_name: Nome amigável para logs/notificações.
        parser_module: Caminho Python (ex.: "skills.quinto_andar.quintoandar_parser").
        base_url: URL base do portal.
        enabled: Se está ativo no watchdog.
        auth: Dict opcional de credenciais (headers, api_key, etc.).
        functions: Mapeamento nome -> function_name do módulo parser.
    """

    slug: str
    name: str
    display_name: str
    parser_module: str
    base_url: str
    enabled: bool = True
    auth: dict[str, Any] = field(default_factory=dict)
    functions: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.auth, dict) and self.auth.get("_env"):
            # Placeholder para expansão futura de env vars
            pass

    @property
    def can_parse_listing(self) -> bool:
        """True se o parser tem função de conversão de listing individual."""
        return "parse_listing" in self.functions

    @property
    def can_parse_payload(self) -> bool:
        """True se o parser tem função de conversão de payload."""
        return "parse_payload" in self.functions

    @property
    def has_build_url(self) -> bool:
        """True se o parser tem função de construção de URL de busca."""
        return "build_url" in self.functions


# ── Singleton cache ─────────────────────────────────────────────────────────

_PARSER_CACHE: dict[str, Any] = {}  # slug -> módulo importado
_PORTAL_CACHE: dict[str, PortalInfo] | None = None


# ── Load config ─────────────────────────────────────────────────────────────


def load_portals(path: str | Path | None = None) -> dict[str, PortalInfo]:
    """Carrega configuração de portais do YAML.

    Args:
        path: Caminho opcional. Se None, busca config/portals.yaml na raiz do repo.

    Returns:
        Dict slug -> PortalInfo, na ordem definida no YAML.

    Raises:
        FileNotFoundError: Se o YAML não existir.
        ValueError: Se o YAML for inválido ou faltar chave 'portals'.
    """
    global _PORTAL_CACHE

    if path is None:
        path = DEFAULT_CONFIG_PATH

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração de portais não encontrado: {path}\n"
            "Crie config/portals.yaml ou passe um path alternativo."
        )

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "portals" not in data:
        raise ValueError(
            f"Config inválido em {path}: "
            "falta a chave 'portals' no YAML"
        )

    portals: dict[str, PortalInfo] = {}
    for slug, cfg in data["portals"].items():
        portals[slug] = PortalInfo(
            slug=slug,
            name=cfg.get("name", slug),
            display_name=cfg.get("display_name", slug.replace("_", " ").title()),
            parser_module=cfg.get("parser_module", f"skills.{slug}.{slug}_parser"),
            base_url=cfg.get("base_url", ""),
            enabled=cfg.get("enabled", True),
            auth=cfg.get("auth", {}),
            functions=cfg.get("functions", {}),
        )

    _PORTAL_CACHE = portals
    return portals


def get_portal(slug: str) -> PortalInfo:
    """Retorna a configuração de um portal pelo slug.

    Args:
        slug: Chave do portal (ex.: "quinto_andar", "loft").

    Returns:
        PortalInfo correspondente.

    Raises:
        KeyError: Se o slug não existir na config.
    """
    if _PORTAL_CACHE is None:
        load_portals()

    cache = _PORTAL_CACHE
    if cache is None:
        raise RuntimeError("portal cache is None after load — this should not happen")

    if slug not in cache:
        available = ", ".join(sorted(cache.keys()))
        raise KeyError(
            f"Portal '{slug}' não encontrado. Portais disponíveis: {available}"
        )

    return _PORTAL_CACHE[slug]


def list_active_portals() -> list[PortalInfo]:
    """Retorna lista de portais habilitados.

    Returns:
        Lista de PortalInfo com enabled=True.
    """
    if _PORTAL_CACHE is None:
        load_portals()

    cache = _PORTAL_CACHE
    if cache is None:
        return []

    return [p for p in cache.values() if p.enabled]


# ── Dynamic module loading ──────────────────────────────────────────────────


def resolve_parser(slug: str) -> Any:
    """Importa dinamicamente o módulo parser de um portal.

    O resultado é cacheado para evitar imports repetidos.

    O módulo é carregado por caminho de arquivo (suporta diretórios
    com hífens como 'quinto-andar').

    Args:
        slug: Chave do portal.

    Returns:
        Módulo Python importado.

    Raises:
        ImportError: Se o módulo não puder ser importado.
        KeyError: Se o slug não for encontrado.
    """
    if slug in _PARSER_CACHE:
        return _PARSER_CACHE[slug]

    portal = get_portal(slug)

    # O parser_module no YAML é um dotted path relativo ao repo root
    # Ex.: "skills.quinto_andar.quintoandar_parser"
    # Mas o diretório real é "skills/quinto-andar/" (com hífen)
    # Então resolvemos por caminho de arquivo.
    dotted_path = portal.parser_module
    parts = dotted_path.split(".")
    # Converte hífens artificialmente: dotted path não pode ter hífen,
    # mas assumimos que o caminho real pode ter (ex.: quinto_andar → quinto-andar)
    # Estratégia: tenta o dotted path como está, senão busca por arquivo.
    mod_name = parts[-1]  # nome do módulo (ex.: quintoandar_parser)

    # Tentativa 1: importlib padrão (funciona se skills for pacote)
    try:
        module = importlib.import_module(dotted_path)
        _PARSER_CACHE[slug] = module
        return module
    except ModuleNotFoundError:
        pass

    # Tentativa 2: buscar por caminho de arquivo
    # Converte skills.quinto_andar.quintoandar_parser → skills/quinto-andar/quintoandar_parser.py
    # Substitui apenas o último ponto (o nome do módulo fica como está)
    # Mas quinto_andar vira quinto-andar
    package_parts = parts[:-1]  # ["skills", "quinto_andar"]
    file_parts = [p.replace("_", "-") for p in package_parts]
    file_parts.append(mod_name + ".py")
    file_path = REPO_ROOT.joinpath(*file_parts)

    if file_path.exists():
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(
                f"Não foi possível criar spec para {file_path}"
            )
        module = importlib.util.module_from_spec(spec)
        # Adiciona o diretório do módulo ao sys.path para imports relativos
        sys.path.insert(0, str(file_path.parent))
        spec.loader.exec_module(module)
        _PARSER_CACHE[slug] = module
        return module

    raise ImportError(
        f"Não foi possível importar o módulo parser do portal "
        f"'{portal.display_name}' ({slug}):\n"
        f"  Módulo esperado: {portal.parser_module}\n"
        f"  Caminho tentado: {file_path}\n"
        f"\n"
        f"Crie o módulo parser ou ajuste parser_module no YAML."
    )


def invalidate_cache(slug: str | None = None) -> None:
    """Limpa o cache de módulos importados.

    Args:
        slug: Se informado, limpa apenas o cache desse portal.
              Se None, limpa todo o cache (forces reload do YAML também).
    """
    global _PORTAL_CACHE

    if slug:
        _PARSER_CACHE.pop(slug, None)
    else:
        _PARSER_CACHE.clear()
        _PORTAL_CACHE = None


# ── Dynamic function calling ────────────────────────────────────────────────


def get_parser_function(slug: str, function_key: str) -> Any:
    """Obtém uma função do parser de um portal pelo nome lógico.

    Args:
        slug: Chave do portal.
        function_key: Nome lógico da função (ex.: "parse_listing", "build_url").

    Returns:
        A função do módulo parser.

    Raises:
        KeyError: Se a função não estiver configurada no YAML.
        AttributeError: Se a função nomeada não existir no módulo.
    """
    portal = get_portal(slug)

    if function_key not in portal.functions:
        raise KeyError(
            f"Portal '{slug}' não tem a função '{function_key}' configurada. "
            f"Funções disponíveis: {list(portal.functions.keys())}"
        )

    actual_name = portal.functions[function_key]
    module = resolve_parser(slug)

    fn = getattr(module, actual_name, None)
    if fn is None:
        raise AttributeError(
            f"Módulo {portal.parser_module} não possui a função "
            f"'{actual_name}' (esperada para '{function_key}')."
        )

    return fn


def call_parser(slug: str, function_key: str, *args, **kwargs) -> Any:
    """Chama uma função do parser de um portal.

    Args:
        slug: Chave do portal.
        function_key: Nome lógico da função.
        *args, **kwargs: Passados direto para a função.

    Returns:
        Resultado da função chamada.

    Exemplo:
        url = call_parser("quinto_andar", "build_url", listing_data)
        imovel = call_parser("loft", "parse_listing", raw_dict)
    """
    fn = get_parser_function(slug, function_key)
    return fn(*args, **kwargs)


def from_listing(slug: str, raw_data: dict) -> Any:
    """Converte uma listagem bruta de um portal para Imovel.

    Args:
        slug: Chave do portal.
        raw_data: Dict com os dados brutos da listagem.

    Returns:
        Instância de Imovel (ou o que o parser retornar).

    Raises:
        KeyError: Se o portal não tiver parse_listing configurada.
    """
    return call_parser(slug, "parse_listing", raw_data)


def from_payload(slug: str, raw_data: dict) -> list:
    """Converte um payload de busca completo para lista de Imovel.

    Args:
        slug: Chave do portal.
        raw_data: Dict com os dados brutos do payload.

    Returns:
        Lista de Imovel.

    Raises:
        KeyError: Se o portal não tiver parse_payload configurada.
    """
    return call_parser(slug, "parse_payload", raw_data)


def build_search_url(slug: str, **params) -> str:
    """Constrói URL de busca para um portal usando seus parâmetros.

    Args:
        slug: Chave do portal.
        **params: Parâmetros de busca (cidade, bairro, preco_min, etc.).

    Returns:
        URL de busca como string.

    Raises:
        KeyError: Se o portal não tiver build_url configurada.
    """
    return call_parser(slug, "build_url", params)


# ── CLI rápido ──────────────────────────────────────────────────────────────


def main():
    """Exibe portais ativos."""
    print("=" * 60)
    print("PORTAL REGISTRY — Portais Ativos")
    print("=" * 60)

    try:
        load_portals()
    except FileNotFoundError as e:
        print(f"[ERRO] {e}")
        return 1

    cache = _PORTAL_CACHE
    if cache is None:
        print("[INFO] Nenhum portal configurado.")
        return 0

    active = [p for p in cache.values() if p.enabled]
    if not active:
        print("Nenhum portal ativo. Defina enabled: true no YAML.")
        return 0

    for i, p in enumerate(active, 1):
        print(f"\n{i}. {p.display_name} ({p.slug})")
        print(f"   Nome fonte:  {p.name}")
        print(f"   Base URL:    {p.base_url}")
        print(f"   Módulo:      {p.parser_module}")
        if p.functions:
            print(f"   Funções:")
            for key, val in p.functions.items():
                print(f"     • {key} → {val}()")
        if p.auth:
            masked = {k: "***" for k in p.auth}
            print(f"   Auth config: {masked}")

    inactive = [p for p in cache.values() if not p.enabled]
    if inactive:
        print(f"\n--- {len(inactive)} portal(is) desabilitado(s) ---")
        for p in inactive:
            print(f"  • {p.display_name} ({p.slug})")

    print(f"\nTotal: {len(active)} ativo(s), {len(inactive)} inativo(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
