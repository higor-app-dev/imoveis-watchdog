#!/usr/bin/env python3
"""
change_detector.py — Detecta mudanças nos dados extraídos dos portais.

Compara o hash do resultado atual com uma baseline armazenada e notifica
quando mudanças são detectadas (ex.: portal mudou formato, parou de retornar
dados, ou novos imóveis surgiram).

Uso:
    python scripts/change_detector.py                           # detect + notify
    python scripts/change_detector.py --check                   # só verifica
    python scripts/change_detector.py --update-baseline         # atualiza baseline
    python scripts/change_detector.py --baseline-dir /path      # dir custom

Integração com pipeline:
    from scripts.change_detector import check_portal_changes
    changed = check_portal_changes()
    if changed:
        print(f"Mudanças detectadas em: {', '.join(changed)}")
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_DIR = REPO_ROOT / "data" / "baselines"
DATA_RESULTS_DIR = REPO_ROOT / "data" / "results"

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("change_detector")


# ── Hashing ────────────────────────────────────────────────────────────────


def compute_listing_hash(listings: list[dict]) -> str:
    """Computa um hash determinístico da lista de listings.

    Usa ID + preço + título de cada listing ordenado para detectar
    mudanças no conteúdo (novos, removidos, alterados).
    """
    sorted_items = sorted(
        listings,
        key=lambda x: str(x.get("id", "") or x.get("list_id", "") or ""),
    )

    hasher = hashlib.sha256()
    for item in sorted_items:
        lid = item.get("id", item.get("list_id", ""))
        price = item.get("preco_venda", item.get("salePrice", item.get("price", 0)))
        title = item.get("titulo", item.get("title", ""))
        url = item.get("url", "")
        fragment = f"{lid}|{price}|{title}|{url}"
        hasher.update(fragment.encode("utf-8"))

    return hasher.hexdigest()


def compute_portal_summary(listings: list[dict]) -> dict:
    """Sumariza os listings por portal para detecção de mudanças."""
    portals: dict[str, dict[str, Any]] = {}
    for item in listings:
        fonte = str(item.get("fonte", "desconhecido"))
        if fonte not in portals:
            portals[fonte] = {
                "count": 0,
                "preco_min": float("inf"),
                "preco_max": 0,
                "hash": hashlib.sha256(),
            }
        p = portals[fonte]
        p["count"] += 1
        price = item.get(
            "preco_venda", item.get("salePrice", item.get("price", 0))
        )
        if price and isinstance(price, (int, float)):
            p["preco_min"] = min(p["preco_min"], price)
            p["preco_max"] = max(p["preco_max"], price)

        lid = item.get("id", item.get("list_id", ""))
        p["hash"].update(f"{lid}".encode("utf-8"))

    result = {}
    for fonte, info in portals.items():
        hash_val = info["hash"].hexdigest()
        min_p = info["preco_min"] if info["preco_min"] != float("inf") else 0
        result[fonte] = {
            "count": info["count"],
            "preco_min": min_p,
            "preco_max": info["preco_max"],
            "hash": hash_val,
        }
    return result


# ── Baseline ───────────────────────────────────────────────────────────────


def load_baseline(baseline_dir: Path) -> dict:
    """Carrega a baseline armazenada."""
    path = baseline_dir / "portal_baseline.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError):
        logger.warning(f"  ⚠️  Baseline corrompida, ignorando")
        return {}


def save_baseline(data: dict, baseline_dir: Path) -> Path:
    """Salva a baseline atual."""
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_dir / "portal_baseline.json"
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def compute_baseline(listings: list[dict]) -> dict:
    """Computa a baseline atual a partir dos listings."""
    overall_hash = compute_listing_hash(listings)
    portal_summary = compute_portal_summary(listings)
    total = len(listings)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_listings": total,
        "overall_hash": overall_hash,
        "portals": portal_summary,
    }


# ── Detecção ───────────────────────────────────────────────────────────────


def find_multi_portal_files() -> list[Path]:
    """Encontra arquivos de resultado multi-portal mais recentes."""
    matches = sorted(DATA_RESULTS_DIR.glob("multi_portal_*.json"))
    if not matches:
        matches = sorted(DATA_RESULTS_DIR.glob("relatorio_oportunidades_*.json"))
    return matches


def load_latest_listings(file_path: Path | None = None) -> list[dict]:
    """Carrega a lista de listings do arquivo mais recente."""
    if file_path is None:
        files = find_multi_portal_files()
        if not files:
            logger.warning("  ⚠️  Nenhum arquivo de resultado encontrado")
            return []
        file_path = files[-1]

    try:
        with open(file_path) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("listings", "results", "imoveis"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            # Tenta relatório
            if "oportunidades" in data and isinstance(data["oportunidades"], list):
                return data["oportunidades"]
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"  ⚠️  Erro lendo {file_path}: {e}")
        return []


def check_portal_changes(
    baseline_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Verifica se houve mudanças em relação à baseline.

    Returns:
        Dict com:
            - changed: True se mudou
            - summary: descrição amigável
            - baseline_atual: baseline recém-computada
            - baseline_anterior: baseline anterior
            - portals_changed: lista de portais com mudança
    """
    if baseline_dir is None:
        baseline_dir = DEFAULT_BASELINE_DIR
    baseline_dir = Path(baseline_dir)

    listings = load_latest_listings()
    if not listings:
        return {
            "changed": False,
            "summary": "Nenhum listing disponível para verificação",
            "baseline_atual": {},
            "baseline_anterior": {},
            "portals_changed": [],
        }

    # Computa baseline atual
    current = compute_baseline(listings)
    previous = load_baseline(baseline_dir)

    if not previous:
        # Primeira execução — salva baseline
        save_baseline(current, baseline_dir)
        total = current["total_listings"]
        return {
            "changed": False,
            "summary": f"✅ Baseline criada: {total} listings de {len(current['portals'])} portais",
            "baseline_atual": current,
            "baseline_anterior": {},
            "portals_changed": [],
        }

    # Compara
    portals_changed = []
    current_portals = current.get("portals", {})
    previous_portals = previous.get("portals", {})

    all_portals = set(current_portals.keys()) | set(previous_portals.keys())

    for portal in sorted(all_portals):
        curr = current_portals.get(portal, {})
        prev = previous_portals.get(portal, {})

        curr_hash = curr.get("hash", "")
        prev_hash = prev.get("hash", "")

        if curr_hash and curr_hash != prev_hash:
            curr_count = curr.get("count", 0)
            prev_count = prev.get("count", 0)
            diff = curr_count - prev_count
            sinal = "+" if diff > 0 else ""
            portals_changed.append(
                f"{portal}: {prev_count} → {curr_count} ({sinal}{diff})"
            )

        # Detecta portal que sumiu
        if not curr and prev:
            portals_changed.append(f"{portal}: DESAPARECEU (tinha {prev.get('count', 0)} listings)")
        # Detecta portal novo
        elif curr and not prev:
            portals_changed.append(f"{portal}: NOVO ({curr.get('count', 0)} listings)")

    total_before = previous.get("total_listings", 0)
    total_now = current["total_listings"]
    overall_changed = current["overall_hash"] != previous.get("overall_hash", "")

    if overall_changed and portals_changed:
        diff = total_now - total_before
        sinal = "+" if diff > 0 else ""
        summary = (
            f"🔄 Mudanças detectadas nos portais!\n"
            f"  Total: {total_before} → {total_now} ({sinal}{diff})\n"
            f"  Portais alterados:\n"
        )
        for p in portals_changed:
            summary += f"    • {p}\n"
    elif overall_changed:
        diff = total_now - total_before
        sinal = "+" if diff > 0 else ""
        summary = (
            f"🔄 Mudança sutil detectada nos dados\n"
            f"  Total: {total_before} → {total_now} ({sinal}{diff})\n"
        )
    else:
        summary = f"✅ Sem mudanças: {total_now} listings, {len(current_portals)} portais"

    return {
        "changed": overall_changed,
        "summary": summary.strip(),
        "baseline_atual": current,
        "baseline_anterior": previous,
        "portals_changed": portals_changed,
        "total_before": total_before,
        "total_now": total_now,
    }


# ── Telegram notification ──────────────────────────────────────────────────


def enviar_telegram(message: str, dry_run: bool = False) -> bool:
    """Envia notificação via Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("  ⚠️  TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não definidos")
        return False

    if dry_run:
        print(f"  [DRY-RUN] Telegram notificado ({len(message)} chars)")
        return True

    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
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
                print(f"  ❌ Telegram API erro: {result}", file=sys.stderr)
                return False
    except Exception as exc:
        print(f"  ❌ Falha ao enviar Telegram: {exc}", file=sys.stderr)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Detecta mudanças nos dados extraídos dos portais"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Só verifica, não notifica nem atualiza baseline"
    )
    parser.add_argument(
        "--update-baseline", action="store_true",
        help="Atualiza a baseline sem notificar"
    )
    parser.add_argument(
        "--baseline-dir", type=str, default=str(DEFAULT_BASELINE_DIR),
        help="Diretório da baseline (default: data/baselines/)"
    )
    parser.add_argument(
        "--input", type=str, default=None,
        help="Arquivo de entrada específico (default: mais recente)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Mostra o que faria sem enviar notificação"
    )
    parser.add_argument(
        "--no-notify", action="store_true",
        help="Não envia notificação Telegram"
    )

    args = parser.parse_args()
    baseline_dir = Path(args.baseline_dir)

    print("=" * 60)
    print("🔍 Detector de Mudanças nos Portais")
    print(f"Início: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # ── Apenas atualizar baseline ──────────────────────────────────────
    if args.update_baseline:
        listings = load_latest_listings(
            Path(args.input) if args.input else None
        )
        if not listings:
            print("❌ Nenhum listing para atualizar baseline")
            return 1

        baseline = compute_baseline(listings)
        path = save_baseline(baseline, baseline_dir)
        print(f"\n✅ Baseline atualizada: {path}")
        print(f"   Total: {baseline['total_listings']} listings")
        print(f"   Portais: {len(baseline['portals'])}")
        for portal, info in baseline["portals"].items():
            print(f"     • {portal}: {info['count']} listings")
        return 0

    # ── Verificar mudanças ─────────────────────────────────────────────
    print("\n📊 Verificando mudanças...")
    result = check_portal_changes(baseline_dir)

    print(f"\n{result['summary']}")

    if args.check:
        # Só verificar, sem alterar baseline nem notificar
        return 0 if not result.get("changed") else 1

    # ── Notificar se houver mudança ────────────────────────────────────
    if result.get("changed"):
        if not args.no_notify:
            print("\n📨 Enviando notificação...")
            enviar_telegram(result["summary"], dry_run=args.dry_run)

        # Atualiza baseline após notificar
        save_baseline(result["baseline_atual"], baseline_dir)
        print("✅ Baseline atualizada")
    else:
        # Mesmo sem mudanças, atualiza timestamp da baseline
        if not args.check:
            save_baseline(result["baseline_atual"], baseline_dir)

    print(f"\n{'=' * 60}")
    print(f"Concluído: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 60}")
    return 0 if not result.get("changed") else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
