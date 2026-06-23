#!/usr/bin/env python3
"""
pipeline_multi_portal.py — Pipeline watchdog multi-portal.

Orquestra o ciclo completo: extrair → dedup → relatório → notificar.

Uso:
    python scripts/pipeline_multi_portal.py                        # execução normal
    python scripts/pipeline_multi_portal.py --dry-run               # só mostra
    python scripts/pipeline_multi_portal.py --no-notify             # sem Telegram
    python scripts/pipeline_multi_portal.py --force                 # notifica mesmo sem novidades
    python scripts/pipeline_multi_portal.py --reset                 # reseta estado
    python scripts/pipeline_multi_portal.py --save-results          # salva dados extraídos
    python scripts/pipeline_multi_portal.py --list-portais          # lista portais ativos
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "skills"))
sys.path.insert(0, str(Path.home() / ".hermes"))

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pipeline")

# ── Imports da pipeline ────────────────────────────────────────────────────

from scripts.extractor import extract_all, list_portals_info as list_portais_info, load_targets, extract_and_save

from skills.relatorio.oportunidades import (
    gerar_relatorio_oportunidades,
    RelatorioOportunidades,
    SAIDA_CONSOLE,
    SAIDA_ARQUIVO,
    SAIDA_AMBOS,
)

# ── Telegram notifier ──────────────────────────────────────────────────────


def enviar_telegram(summary: str, dry_run: bool = False) -> bool:
    """Envia notificação via Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("  ⚠️  TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não definidos")
        return False

    if dry_run:
        print(f"  [DRY-RUN] Telegram notificado ({len(summary)} chars)")
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
                print(f"  ❌ Telegram API erro: {result}", file=sys.stderr)
                return False
    except Exception as exc:
        print(f"  ❌ Falha ao enviar Telegram: {exc}", file=sys.stderr)
        return False


# ── Pipeline principal ─────────────────────────────────────────────────────


def run_pipeline(
    *,
    force: bool = False,
    no_notify: bool = False,
    dry_run: bool = False,
    reset: bool = False,
    save_results: bool = True,
) -> int:
    """Executa o pipeline multi-portal completo.

    Pipeline:
      1. Lista portais ativos
      2. Extrai listings de todos os portais
      3. Aplica dedup cross-portal
      4. Compara com estado anterior → new_flag
      5. Gera relatório unificado
      6. (Opcional) Notifica via Telegram
      7. (Opcional) Salva estado e resultados
    """
    print("=" * 60)
    print("🏠 Pipeline Watchdog Multi-Portal")
    print(f"Início: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # ── 1. Portais ativos ──────────────────────────────────────────────
    print("\n📋 Portais ativos:")
    portais_info = list_portais_info()
    if not portais_info:
        print("  Nenhum portal ativo encontrado.")
        return 0 if dry_run else 1

    for p in portais_info:
        status = "✅" if p.get("enabled", True) else "⏸️"
        print(f"  {status} {p['display_name']} ({p['slug']})")

    # ── 2. Extração ─────────────────────────────────────────────────────
    print("\n🔍 Extraindo dados dos portais...")
    targets = load_targets()
    if dry_run:
        print(f"  [DRY-RUN] {len(targets)} targets de busca")
        for t in targets:
            portal_nome = t["portal"]
            cidade = t["cidade"][:30]
            print(f"    • {portal_nome}: {cidade}")
        return 0

    try:
        listings = extract_all(targets)
    except Exception as exc:
        print(f"  ❌ Erro na extração: {exc}", file=sys.stderr)
        return 1

    if not listings:
        print("  ⚠️  Nenhum listing encontrado.")
        return 0

    print(f"\n📊 Total de listings: {len(listings)}")

    # Contagem por portal
    fontes: dict[str, int] = {}
    for item in listings:
        fonte = str(item.get("fonte", "desconhecido"))
        fontes[fonte] = fontes.get(fonte, 0) + 1
    for fonte, count in sorted(fontes.items()):
        print(f"  • {fonte}: {count}")

    # ── 3. Dedup + Relatório unificado ──────────────────────────────────
    print("\n🔄 Gerando relatório unificado de oportunidades...")

    try:
        relatorio = gerar_relatorio_oportunidades(
            listings,
            aplicar_dedup=True,
            saida=SAIDA_CONSOLE,
            salvar_estado=not dry_run,
        )
    except Exception as exc:
        print(f"  ❌ Erro ao gerar relatório: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    print(f"\n📊 Resumo:")
    print(f"  Total imóveis únicos: {relatorio.total}")
    print(f"  Novos:                {relatorio.total_novos}")
    print(f"  Existentes:           {relatorio.total_existentes}")

    # ── 4. Notificação ──────────────────────────────────────────────────
    if no_notify:
        print("\n📨 Notificação desabilitada (--no-notify)")
    else:
        tem_novos = relatorio.total_novos > 0
        if tem_novos or force:
            print("\n📨 Enviando notificação...")
            summary = relatorio.texto
            enviar_telegram(summary, dry_run=dry_run)
        else:
            print("\n📨 Sem novidades — notificação suprimida (use --force para forçar)")

    # ── 5. Salva resultados ─────────────────────────────────────────────
    if save_results and not dry_run:
        print("\n💾 Salvando resultados...")

        # Salva relatório formatado
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        rel_path = REPO_ROOT / "data" / "results" / f"relatorio_oportunidades_{timestamp}.txt"
        rel_path.parent.mkdir(parents=True, exist_ok=True)
        relatorio.salvar(str(rel_path))
        print(f"  📄 Relatório: {rel_path}")

        # Salva relatório JSON
        json_path = REPO_ROOT / "data" / "results" / f"relatorio_oportunidades_{timestamp}.json"
        relatorio.salvar_json(str(json_path))
        print(f"  📄 Dados JSON: {json_path}")

        # Salva listings brutos
        extract_path = REPO_ROOT / "data" / "results" / f"multi_portal_{timestamp}.json"
        raw_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(listings),
            "total_unicos": relatorio.total,
            "total_novos": relatorio.total_novos,
            "listings": listings,
        }
        extract_path.write_text(
            json.dumps(raw_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  📄 Listings brutos: {extract_path}")

    # ── Fim ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Pipeline concluída: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 60}")

    return 0


# ── CLI ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline watchdog multi-portal: extrai, dedup, notifica"
    )
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que faria sem executar")
    parser.add_argument("--no-notify", action="store_true", help="Não envia notificação Telegram")
    parser.add_argument("--force", action="store_true", help="Notifica mesmo sem novidades")
    parser.add_argument("--reset", action="store_true", help="Reseta estado anterior")
    parser.add_argument("--no-save", action="store_true", help="Não salva resultados")
    parser.add_argument("--list-portais", action="store_true", help="Lista portais ativos e sai")
    parser.add_argument("--save-only", action="store_true", help="Só extrai e salva, sem relatório")

    args = parser.parse_args()

    if args.list_portais:
        print("Portais ativos:")
        for p in list_portais_info():
            status = "✅" if p.get("enabled", True) else "⏸️"
            print(f"  {status} {p['display_name']} ({p['slug']})")
            if "has_listing_parser" in p:
                flags = []
                if p.get("has_listing_parser"): flags.append("parse_listing")
                if p.get("has_payload_parser"): flags.append("parse_payload")
                if p.get("has_build_url"): flags.append("build_url")
                if flags:
                    print(f"       Funções: {', '.join(flags)}")
        return 0

    if args.save_only:
        print("Extraindo e salvando dados...")
        path = extract_and_save()
        print(f"Dados salvos em: {path}")
        return 0

    result = run_pipeline(
        force=args.force,
        no_notify=args.no_notify,
        dry_run=args.dry_run,
        reset=args.reset,
        save_results=not args.no_save,
    )
    sys.exit(result or 0)


if __name__ == "__main__":
    main()
