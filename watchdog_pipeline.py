#!/usr/bin/env python3
"""
watchdog_pipeline.py — Pipeline de watchdog de imóveis.

Lê config (watchdog.yaml), busca anúncios no OLX para cada cidade + faixa de
preço, compara com execução anterior, gera resumo e notifica via Telegram.

Idempotente: múltiplas execuções no mesmo período produzem o mesmo resultado
(se os dados não mudaram, não notifica).

Uso:
    python watchdog_pipeline.py                          # execução normal
    python watchdog_pipeline.py --force                   # notifica mesmo sem novidades
    python watchdog_pipeline.py --no-notify               # só loga, não envia Telegram
    python watchdog_pipeline.py --dry-run                 # só mostra o que faria
    python watchdog_pipeline.py --reset                   # redefine estado anterior

Requer:
    - cloudscraper (pip install cloudscraper)
    - ~/.hermes/watchdog.yaml (ou HERMES_WATCHDOG_CONFIG)
    - TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (env vars) para notificações
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── imports com fallback amigável ─────────────────────────────────────────────
try:
    import cloudscraper
except ImportError:
    sys.exit(
        "cloudscraper não instalado. Rode: pip install cloudscraper"
    )

try:
    from watchdog_config import load_config, list_targets
except ImportError:
    # Tenta importar de ~/.hermes/
    sys.path.insert(0, str(Path.home() / ".hermes"))
    try:
        from watchdog_config import load_config, list_targets
    except ImportError:
        sys.exit(
            "watchdog_config.py não encontrado. "
            "Copie watchdog_config.py para ~/.hermes/ ou ajuste o PYTHONPATH."
        )

# ── constantes ────────────────────────────────────────────────────────────────

STATE_SLUGS = {
    "SP": "estado-sp",
    "RJ": "estado-rj",
    "MG": "estado-mg",
}

# Mapeamento cidade → região OLX (slug de URL + valor do filtro)
CITY_REGION = {
    "São Paulo": {
        "slug": "sao-paulo-e-regiao",
        "state_id": "1",
        "region_id": "11",
    },
    "Rio de Janeiro": {
        "slug": "rio-de-janeiro-e-regiao",
        "state_id": "3",
        "region_id": "21",
    },
    "Belo Horizonte": {
        "slug": "belo-horizonte-e-regiao",
        "state_id": "2",
        "region_id": "31",
    },
}

DATA_DIR = Path.home() / ".hermes" / "watchdog"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "pipeline_state.json"       # último resultado completo
HISTORY_DIR = DATA_DIR / "history"                   # logs timestampados
HISTORY_DIR.mkdir(exist_ok=True)

MAX_RESULTS_PER_FETCH = 50
PAGINATION_LIMIT = 2  # max páginas por busca (cada página = 50 anúncios)

# ── utilitários ───────────────────────────────────────────────────────────────


def build_olx_url(city: str, uf: str, price_min: int, price_max: int) -> str:
    """Constrói URL de busca OLX para uma cidade + faixa de preço."""
    state_slug = STATE_SLUGS.get(uf, f"estado-{uf.lower()}")
    region = CITY_REGION.get(city, {})
    region_slug = region.get("slug", city.lower().replace(" ", "-"))
    return (
        f"https://www.olx.com.br/imoveis/venda/"
        f"{state_slug}/{region_slug}"
        f"?ps={price_min}&pe={price_max}"
    )


def parse_ad(ad: dict) -> dict:
    """Extrai campos padronizados de um anúncio OLX."""
    props = {p["name"]: p["value"] for p in ad.get("properties", [])}
    loc = ad.get("locationDetails") or {}

    def _extract_int(name: str) -> int | None:
        raw = props.get(name, "")
        m = re.search(r"\d+", str(raw))
        return int(m.group()) if m else None

    def _extract_price(val: str) -> int | None:
        if not val:
            return None
        m = re.search(r"[\d.]+", str(val).replace(".", ""))
        return int(m.group()) if m else None

    return {
        "list_id": ad["listId"],
        "title": ad.get("subject", "").strip(),
        "url": ad.get("url", ""),
        "price_raw": ad.get("priceValue", ""),
        "price": _extract_price(ad.get("priceValue", "")),
        "category": ad.get("categoryName", ""),
        "municipality": loc.get("municipality", ""),
        "neighbourhood": loc.get("neighbourhood", ""),
        "uf": loc.get("uf", ""),
        "area_m2": _extract_int("size"),
        "rooms": _extract_int("rooms"),
        "bathrooms": _extract_int("bathrooms"),
        "garage_spaces": _extract_int("garage_spaces"),
        "condominio_fee": ad.get("condominio", ""),
        "date": ad.get("date", 0),
        "image_count": ad.get("imageCount", 0),
    }


def fetch_listings(url: str, scraper: cloudscraper.CloudScraper) -> list[dict]:
    """Busca anúncios do OLX via cloudscraper e retorna lista padronizada."""
    ads_raw = []
    for page in range(1, PAGINATION_LIMIT + 1):
        page_url = url if page == 1 else f"{url}&pageIndex={page}"
        try:
            r = scraper.get(page_url, timeout=30)
            r.raise_for_status()
        except Exception as exc:
            print(f"  [AVISO] Erro ao buscar {page_url}: {exc}", file=sys.stderr)
            break

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL
        )
        if not match:
            print(f"  [AVISO] Sem __NEXT_DATA__ em {page_url}", file=sys.stderr)
            break

        try:
            data = json.loads(match.group(1))
            page_ads = data.get("props", {}).get("pageProps", {}).get("ads", [])
            # Filtra apenas anúncios reais (ads têm listId; placements não)
            real_ads = [a for a in page_ads if "listId" in a]
            ads_raw.extend(real_ads)
            if len(real_ads) < MAX_RESULTS_PER_FETCH:
                break  # última página
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"  [AVISO] Erro parseando {page_url}: {exc}", file=sys.stderr)
            break

    return [parse_ad(a) for a in ads_raw]


def fingerprint(listings: list[dict]) -> str:
    """Hash dos list_ids para detectar mudanças rapidamente."""
    ids = sorted(a["list_id"] for a in listings)
    import hashlib

    return hashlib.sha256(",".join(str(i) for i in ids).encode()).hexdigest()[:16]


def diff_lists(
    old: list[dict], new: list[dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Compara duas listas de anúncios.

    Returns:
        (new_items, removed_items, changed_items)
    """
    old_by_id = {a["list_id"]: a for a in old}
    new_by_id = {a["list_id"]: a for a in new}

    old_ids = set(old_by_id.keys())
    new_ids = set(new_by_id.keys())

    new_items = [new_by_id[i] for i in new_ids - old_ids]
    removed_items = [old_by_id[i] for i in old_ids - new_ids]

    # Itens que mudaram de preço
    changed_items = []
    for i in old_ids & new_ids:
        op = old_by_id[i].get("price")
        np = new_by_id[i].get("price")
        if op != np:
            changed_items.append({"old": old_by_id[i], "new": new_by_id[i]})

    return new_items, removed_items, changed_items


def build_summary(
    city: str,
    price_label: str,
    new_items: list[dict],
    removed_items: list[dict],
    changed_items: list[dict],
    total_new: int,
) -> str:
    """Gera texto de resumo formatado para notificação."""
    lines = [f"🏠 *{city} — {price_label}*"]
    total_text = f"Total de anúncios ativos: {total_new}"
    lines.append(total_text)

    if new_items:
        lines.append(f"\n🆕 *Novos ({len(new_items)}):*")
        for a in new_items[:5]:
            hood = f" - {a['neighbourhood']}" if a["neighbourhood"] else ""
            price = a["price_raw"] or "N/I"
            rooms = f"{a['rooms']}q" if a["rooms"] else ""
            area = f"{a['area_m2']}m²" if a["area_m2"] else ""
            detail = f" ({rooms}, {area})" if rooms or area else ""
            lines.append(f"  • {price} — {a['title'][:50]}{hood}{detail}")
        if len(new_items) > 5:
            lines.append(f"  ... +{len(new_items) - 5} novos")

    if removed_items:
        lines.append(f"\n🗑 *Removidos ({len(removed_items)}):*")
        for a in removed_items[:3]:
            price = a.get("price_raw") or "N/I"
            lines.append(f"  • {price} — {a['title'][:40]}")
        if len(removed_items) > 3:
            lines.append(f"  ... +{len(removed_items) - 3} removidos")

    if changed_items:
        lines.append(f"\n💰 *Mudaram de preço ({len(changed_items)}):*")
        for c in changed_items[:3]:
            op = c["old"].get("price_raw", "N/I")
            np = c["new"].get("price_raw", "N/I")
            lines.append(f"  • {op} → {np} — {c['new']['title'][:40]}")
        if len(changed_items) > 3:
            lines.append(f"  ... +{len(changed_items) - 3} alterações")

    return "\n".join(lines)


def send_telegram(summary: str, dry_run: bool = False):
    """Envia notificação via Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("  [AVISO] TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não definidos",
              file=sys.stderr)
        return False

    if dry_run:
        print(f"  [DRY-RUN] Telegram notificado:\n{summary}\n")
        return True

    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": summary,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload).encode()

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("  ✓ Telegram enviado")
                return True
            else:
                print(f"  [ERRO] Telegram API: {result}", file=sys.stderr)
                return False
    except Exception as exc:
        print(f"  [ERRO] Falha ao enviar Telegram: {exc}", file=sys.stderr)
        return False


def save_state(all_results: dict[str, dict], path: Path = STATE_FILE):
    """Salva estado atual da pipeline."""
    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": all_results,
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Estado salvo em {path}")


def load_state(path: Path = STATE_FILE) -> dict | None:
    """Carrega estado anterior, se existir."""
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_history(city: str, price_label: str, listings: list[dict]):
    """Salva resultados detalhados em arquivo timestampado."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    safe_city = city.lower().replace(" ", "_")
    filename = f"{safe_city}_{price_label}_{ts}.json"
    path = HISTORY_DIR / filename
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "city": city,
        "price_label": price_label,
        "total": len(listings),
        "listings": listings,
    }
    with open(path, "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return path


def rotate_history(max_files: int = 200):
    """Remove logs mais antigos se exceder o limite."""
    files = sorted(HISTORY_DIR.glob("*.json"))
    if len(files) > max_files:
        for f in files[: len(files) - max_files]:
            f.unlink()


def needs_notification(
    all_results: dict, previous: dict | None,
) -> tuple[bool, list[tuple[str, str, list, list, list, int]]]:
    """Compara resultados atuais com anteriores e decide se notifica.

    Returns:
        (has_changes, summaries_info)
    """
    summaries_info = []

    for city_key, result in all_results.items():
        city = result["city"]
        price_label = result["price_label"]
        new_listings = result["listings"]

        prev_listings = []
        if previous:
            prev_result = previous.get("results", {}).get(city_key, {})
            prev_listings = prev_result.get("listings", [])
            if isinstance(prev_listings, list) and prev_listings:
                # converte de dict pra dict (já está no formato)
                pass

        new_items, removed_items, changed_items = diff_lists(
            prev_listings, new_listings
        )
        summaries_info.append(
            (city, price_label, new_items, removed_items, changed_items, len(new_listings))
        )

    has_changes = any(
        n or r or c for _, _, n, r, c, _ in summaries_info
    )

    return has_changes, summaries_info


def run_pipeline(
    force: bool = False,
    no_notify: bool = False,
    dry_run: bool = False,
    reset: bool = False,
):
    """Executa o pipeline completo."""
    print("=" * 60)
    print("Watchdog Pipeline — Imóveis")
    print(f"Início: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # 1. Carrega config
    print("\n📋 Lendo configuração...")
    try:
        config = load_config()
        targets = list_targets(config)
        options = config.get("options", {})
        print(f"  ✓ {len(targets)} targets expandidos")
    except Exception as exc:
        print(f"  ✗ Erro ao carregar config: {exc}", file=sys.stderr)
        return 1

    if reset:
        print("\n🔄 Resetando estado anterior...")
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print("  ✓ Estado resetado")
        else:
            print("  - Nenhum estado anterior encontrado")
        return 0 if not force else None  # se --force, continua

    # 2. Inicializa scraper
    print("\n🌐 Inicializando scraper...")
    scraper = cloudscraper.create_scraper()
    print("  ✓ cloudscraper pronto")

    # 3. Agrupa targets por cidade + faixa de preço (evita duplicatas)
    print("\n🔍 Buscando anúncios...")
    city_price_groups: dict[str, dict] = {}
    for t in targets:
        key = f"{t['city']}|{t['price_label']}"
        if key not in city_price_groups:
            city_price_groups[key] = {
                "city": t["city"],
                "state": t["state"],
                "uf": t.get("state", ""),
                "price_min": t["price_min"],
                "price_max": t["price_max"],
                "price_label": t["price_label"],
                "municipality": t["city"],
            }

    all_results: dict[str, dict] = {}
    total_listings = 0

    for key, group in sorted(city_price_groups.items()):
        city = group["city"]
        price_min = group["price_min"]
        price_max = group["price_max"]
        price_label = group["price_label"]
        uf = group.get("uf", "SP")

        url = build_olx_url(city, uf, price_min, price_max)
        print(f"\n  {city} ({price_label}):")

        if dry_run:
            print(f"    [DRY-RUN] URL: {url}")
            all_results[key] = {
                "city": city,
                "price_label": price_label,
                "listings": [],
            }
            continue

        try:
            listings = fetch_listings(url, scraper)
            print(f"    ✓ {len(listings)} anúncios encontrados")

            # Filtra por bairro se configurado
            neighborhoods_config = config.get("neighborhoods", [])
            hoods_for_city = [
                n["name"] for n in neighborhoods_config if n.get("city") == city
            ]
            if hoods_for_city:
                filtered = [
                    a for a in listings
                    if a["neighbourhood"] in hoods_for_city
                ]
                print(f"    ↪ Filtrado: {len(filtered)} anúncios nos bairros alvo")
                listings = filtered

            # Validação dos anúncios (converte para schema Imovel, filtra inválidos)
            try:
                sys.path.insert(0, str(Path.home() / ".hermes"))
                from imovel_schema import from_olx_parse
                sys.path.insert(0, str(Path(__file__).resolve().parent / "skills" / "quinto-andar"))
                from validacao import validar_lote
                imoveis_v = [from_olx_parse(a) for a in listings]
                lote = validar_lote(imoveis_v)
                if lote.invalidos > 0:
                    print(f"    ⚠️  {lote.invalidos} anúncios inválidos ignorados:")
                    for r in lote.resultados:
                        if not r.valido:
                            aid = r.imovel.get("id", "?")
                            for err in r.erros:
                                print(f"       - [{aid}] {err}")
                    listings = [a for i, a in enumerate(listings) if lote.resultados[i].valido]
                    print(f"    ✓ {len(listings)} anúncios válidos após validação")
            except ImportError:
                pass  # validação é opcional na pipeline

            all_results[key] = {
                "city": city,
                "price_label": price_label,
                "listings": listings,
            }
            total_listings += len(listings)

        except Exception as exc:
            print(f"    ✗ Erro: {exc}", file=sys.stderr)
            all_results[key] = {
                "city": city,
                "price_label": price_label,
                "listings": [],
            }

    print(f"\n📊 Total: {total_listings} anúncios únicos em {len(all_results)} grupos")

    # 4. Compara com execução anterior
    print("\n🔄 Comparando com execução anterior...")
    previous = load_state()

    has_changes, summaries_info = needs_notification(all_results, previous)

    if not has_changes and not force:
        print("  ✓ Sem novidades — pipeline concluído sem notificação")
        if not dry_run:
            save_state(all_results)
        return 0

    # 5. Gera sumário
    print("\n📝 Gerando resumo...")
    summary_parts = []
    summary_parts.append(
        f"🏠 *Watchdog Imóveis* — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    summary_parts.append(f"Total de anúncios: {total_listings}")

    for city, price_label, new_items, removed_items, changed_items, total_new in summaries_info:
        city_key = f"{city}|{price_label}"
        result = all_results.get(city_key, {})
        n_new = len(new_items)
        n_removed = len(removed_items)
        n_changed = len(changed_items)

        if n_new or n_removed or n_changed or force:
            block = build_summary(
                city, price_label, new_items, removed_items, changed_items, total_new
            )
            summary_parts.append("")
            summary_parts.append(block)

    full_summary = "\n".join(summary_parts)

    # 6. Notifica via Telegram
    if no_notify:
        print("  — Notificação desabilitada (--no-notify)")
    else:
        print("\n📨 Enviando notificação Telegram...")
        send_telegram(full_summary, dry_run=dry_run)

    # 7. Salva histórico e estado
    if not dry_run:
        print("\n💾 Salvando dados...")
        for key, result in all_results.items():
            save_history(
                result["city"], result["price_label"], result["listings"]
            )
        save_state(all_results)
        rotate_history()
    else:
        print("\n[DRY-RUN] Estado e histórico NÃO salvos")

    print(f"\n{'=' * 60}")
    print(f"Pipeline concluída: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 60}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Watchdog de imóveis — pipeline de busca, comparação e notificação"
    )
    parser.add_argument(
        "--force", action="store_true", help="Notifica mesmo sem novidades"
    )
    parser.add_argument(
        "--no-notify", action="store_true", help="Não envia notificação Telegram"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Mostra o que faria sem executar"
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reseta estado anterior"
    )
    args = parser.parse_args()

    result = run_pipeline(
        force=args.force,
        no_notify=args.no_notify,
        dry_run=args.dry_run,
        reset=args.reset,
    )
    sys.exit(result or 0)


if __name__ == "__main__":
    main()
