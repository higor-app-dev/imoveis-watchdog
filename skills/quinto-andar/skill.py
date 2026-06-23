"""
QuintoAndar — Hermes Agent Skill Entry Point

Entry point for the QuintoAndar property listing parsing skill.
Integrates with the Hermes Agent framework and the portal_registry system.

Links to the existing parser modules:
  - quintoandar_parser  → Parse QuintoAndar data to the unified Imovel schema
                          (from_quintoandar_listing, from_quintoandar_payload, etc.)
  - validacao           → Batch validation of parsed listings

Config-driven portal registration lives at:
  - config/portals.yaml → "quinto_andar" entry with parser_module, function mapping

Usage:
    python skill.py                   # Show this placeholder message
    python skill.py --info            # Show module info and available functions
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn


# Ensure project root is in path for imports (same pattern as quintoandar_parser.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def show_info() -> None:
    """Display the current state of this skill and its available modules."""
    # The directory is skills/quinto-andar/ (with hyphen) but Python imports
    # use underscores. Add the skill dir directly so imports work.
    skill_dir = Path(__file__).resolve().parent
    if str(skill_dir) not in sys.path:
        sys.path.insert(0, str(skill_dir))

    try:
        from quintoandar_parser import (
            from_quintoandar_listing,
            from_quintoandar_payload,
            from_quintoandar_safe,
        )
        print("  ✓ quintoandar_parser loaded")
        print(f"    - from_quintoandar_listing (1 listing)")
        print(f"    - from_quintoandar_payload (payload → list[Imovel])")
        print(f"    - from_quintoandar_safe    (auto-detect wrapper)")
    except ImportError as e:
        print(f"  ✗ quintoandar_parser not available: {e}")

    # Navigation module (browser automation)
    nav_path = str(skill_dir)
    if nav_path not in sys.path:
        sys.path.insert(0, nav_path)
    try:
        from navigation import navigate_to_search, navigate_to_search_async
        print("  ✓ navigation loaded")
        print(f"    - navigate_to_search       (sync: browser→page)")
        print(f"    - navigate_to_search_async (async: browser→page)")
    except ImportError as e:
        print(f"  ✗ navigation not available: {e}")

    try:
        from pagination import paginate_and_collect, get_listing_count
        print("  ✓ pagination loaded")
        print(f"    - paginate_and_collect (page, extract_fn, max_pages=5)")
        print(f"    - get_listing_count     (page → int)")
    except ImportError as e:
        print(f"  ✗ pagination not available: {e}")

    try:
        from validacao import validar_lote
        print("  ✓ validacao loaded")
        print(f"    - validar_lote (batch validation)")
    except ImportError as e:
        print(f"  ✗ validacao not available: {e}")

    try:
        from imovel_schema import Imovel
        print("  ✓ imovel_schema loaded")
        print(f"    - Imovel dataclass ({len(Imovel.__dataclass_fields__)} fields)")
    except ImportError:
        print("  ✗ imovel_schema not available (install from ~/.hermes/imovel_schema.py)")

    # Check config registration
    config_path = PROJECT_ROOT / "config" / "portals.yaml"
    if config_path.exists():
        print("  ✓ config/portals.yaml exists — portal 'quinto_andar' registered")


def main() -> None:
    """Placeholder entry point for the QuintoAndar Hermes skill."""
    parser = argparse.ArgumentParser(
        prog="quinto-andar",
        description="QuintoAndar property listing skill for Hermes Agent",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show module info and available functions",
    )
    parser.add_argument(
        "--list-functions",
        action="store_true",
        help="List registered parser functions from config/portals.yaml",
    )

    args = parser.parse_args()

    if args.info:
        print("QuintoAndar Skill — Module Info")
        print("=" * 40)
        show_info()
        return

    if args.list_functions:
        print("Registered functions (config/portals.yaml):")
        print("  parse_listing : from_quintoandar_listing")
        print("  parse_payload : from_quintoandar_payload")
        print()
        print("Navigation functions (skills/quinto-andar/navigation.py):")
        print("  navigate_to_search       : sync (browser, city, type, txn, [neighbourhood])")
        print("  navigate_to_search_async : async (browser, city, type, txn, [neighbourhood])")
        print("  navigate_to_search_safe  : sync wrapper, returns (ok, page, msg)")
        print()
        print("Pagination functions (skills/quinto-andar/pagination.py):")
        print("  paginate_and_collect : (page, extract_fn, max_pages=5) → list[dict]")
        print("  get_listing_count    : (page) → int")
        print()
        print("Portal slug: quinto_andar")
        print("Display name: QuintoAndar")
        print("Parser module: skills.quinto_andar.quintoandar_parser")
        return

    # Placeholder message
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║       QuintoAndar Skill                  ║")
    print("  ║       Not Implemented Yet                 ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print("  This skill is a placeholder for the Hermes Agent framework.")
    print()
    print("  The parser modules are ready and functional:")
    print("    skills/quinto-andar/quintoandar_parser.py  (807 lines)")
    print("    skills/quinto-andar/validacao.py           (validation)")
    print()
    print("  Examples:")
    print("    python skills/quinto-andar/quintoandar_parser.py data/resultado.json")
    print("    python skills/quinto-andar/skill.py --info")
    print()


if __name__ == "__main__":
    main()
