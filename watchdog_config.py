"""
watchdog_config — Leitor de configuração do watchdog de imóveis.

Uso:
    from watchdog_config import load_config
    config = load_config()
    for city in config["cities"]:
        print(city["name"])

Procura o YAML nesta ordem:
  1. $HERMES_WATCHDOG_CONFIG (env var)
  2. /etc/hermes/watchdog.yaml
  3. ~/.hermes/watchdog.yaml
  4. ./watchdog.yaml  (cwd)
"""

import os
import yaml
from pathlib import Path

DEFAULT_PATHS = [
    "/etc/hermes/watchdog.yaml",
    Path.home() / ".hermes" / "watchdog.yaml",
    Path.cwd() / "watchdog.yaml",
]


def find_config() -> Path:
    """Retorna o Path do primeiro arquivo de config encontrado."""
    env_path = os.environ.get("HERMES_WATCHDOG_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p.resolve()

    for p in DEFAULT_PATHS:
        if Path(p).exists():
            return Path(p).resolve()

    raise FileNotFoundError(
        "watchdog.yaml não encontrado. "
        "Defina HERMES_WATCHDOG_CONFIG ou coloque o arquivo em um dos paths: "
        + ", ".join(str(x) for x in DEFAULT_PATHS)
    )


def load_config(path: str | Path | None = None) -> dict:
    """Carrega e retorna o dict de configuração do watchdog.

    Args:
        path: Caminho opcional. Se None, busca nos paths padrão.

    Returns:
        Dict com a chave 'watchdog' contendo cities, neighborhoods,
        price_ranges, property_types e options.
    """
    if path is None:
        path = find_config()

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "watchdog" not in data:
        raise ValueError(
            f"Config inválido em {path}: falta a chave 'watchdog'"
        )

    return data["watchdog"]


def list_targets(config: dict | None = None) -> list[dict]:
    """Expande todas as combinações de busca (cidade × bairro × faixa de
    preço × tipo) como targets individuais. Útil para iterar no pipeline.

    Args:
        config: output de load_config(). Se None, carrega do disco.

    Returns:
        Lista de dicts, cada um com city, neighborhood (ou None),
        price_range, e property_type.
    """
    if config is None:
        config = load_config()

    cities = config.get("cities", [])
    neighborhoods = config.get("neighborhoods", [])
    price_ranges = config.get("price_ranges", [])
    property_types = config.get("property_types", ["apartamento"])

    # Agrupa bairros por cidade
    hoods_by_city: dict[str, list[str]] = {}
    for n in neighborhoods:
        hoods_by_city.setdefault(n["city"], []).append(n["name"])

    targets = []
    for city in cities:
        city_name = city["name"]
        hoods = hoods_by_city.get(city_name, [None])

        for hood in hoods:
            for pr in price_ranges:
                for pt in property_types:
                    targets.append({
                        "city": city_name,
                        "state": city.get("state", ""),
                        "neighborhood": hood,
                        "price_min": pr["min"],
                        "price_max": pr["max"],
                        "price_label": pr["label"],
                        "property_type": pt,
                    })

    return targets
