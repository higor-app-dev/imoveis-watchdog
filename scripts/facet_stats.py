#!/usr/bin/env python3
"""
facet_stats — Compute facet statistics from collected listing datasets.

Usage:
    python scripts/facet_stats.py                          # all datasets
    python scripts/facet_stats.py data/results/zuk_*.json   # specific files
    python scripts/facet_stats.py --output data/facets.json # save as JSON
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def load_listings(patterns: list[str] | None = None) -> list[dict]:
    """Load listing dicts from JSON files in data/results/."""
    data_dir = Path(__file__).resolve().parent.parent / "data" / "results"
    
    if patterns:
        import glob
        files = []
        for p in patterns:
            files.extend(glob.glob(p))
    else:
        files = sorted(data_dir.glob("*.json"))
    
    listings = []
    for fpath in files:
        try:
            with open(fpath) as f:
                data = json.load(f)

            def extract(obj, collected):
                if isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict):
                            if item.get("fonte") or item.get("titulo") or item.get("preco_venda") is not None:
                                collected.append(item)
                            else:
                                extract(item, collected)
                elif isinstance(obj, dict):
                    if obj.get("fonte") or obj.get("titulo") or obj.get("preco_venda") is not None:
                        collected.append(obj)
                    for key in ("regions", "results", "listings", "imoveis", "data", "hits"):
                        sub = obj.get(key)
                        if isinstance(sub, list):
                            for item in sub:
                                if isinstance(item, dict):
                                    extract(item, collected)
                        elif isinstance(sub, dict):
                            for rkey, rval in sub.items():
                                if isinstance(rval, dict):
                                    extract(rval, collected)
                return collected

            listings.extend(extract(data, []))
        except (json.JSONDecodeError, OSError):
            pass
    
    return listings


def compute_facets(listings: list[dict]) -> dict[str, Any]:
    """Compute facet statistics from a list of listing dicts."""
    fonte = Counter()
    cidade = Counter()
    uf = Counter()
    tipo = Counter()
    bairro = Counter()
    precos: list[float] = []
    areas: list[float] = []
    quartos: list[int] = []
    fotos_total = 0
    
    for l in listings:
        f = l.get("fonte") or "quintoandar"
        fonte[f] += 1
        
        cid = l.get("cidade", "")
        if cid:
            cidade[cid] += 1
        
        u = l.get("uf", "")
        if u:
            uf[u.upper()] += 1
        
        t = l.get("tipo", "")
        if t:
            tipo[t] += 1
        
        b = l.get("bairro", "")
        if b:
            bairro[b] += 1
        
        p = l.get("preco_venda")
        if p is not None:
            try:
                precos.append(float(p))
            except (ValueError, TypeError):
                pass
        
        a = l.get("area")
        if a is not None:
            try:
                areas.append(float(a))
            except (ValueError, TypeError):
                pass
        
        q = l.get("quartos")
        if q is not None:
            try:
                quartos.append(int(q))
            except (ValueError, TypeError):
                pass
        
        fotos = l.get("fotos", []) or []
        fotos_total += len(fotos) if isinstance(fotos, list) else 0
    
    precio_ord = sorted(precos) if precos else []
    
    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {}
        s = sorted(vals)
        n = len(s)
        return {
            "min": s[0],
            "max": s[-1],
            "avg": round(sum(s) / n, 2),
            "median": s[n // 2],
            "count": n,
        }
    
    return {
        "total_listings": len(listings),
        "total_fotos": fotos_total,
        "fontes": dict(fonte.most_common()),
        "ufs": dict(uf.most_common()),
        "cidades": dict(cidade.most_common(50)),
        "bairros": dict(bairro.most_common(50)),
        "tipos": dict(tipo.most_common(20)),
        "num_cidades": len(cidade),
        "num_bairros": len(bairro),
        "precos": _stats(precos),
        "areas": _stats(areas),
        "quartos": dict(Counter(quartos).most_common()),
    }


def format_report(facets: dict) -> str:
    """Format facets as a human-readable report."""
    lines = []
    lines.append(f"📊 **Facet Stats — {facets['total_listings']} listings**\n")
    
    lines.append("🏷️ **Por fonte:**")
    for f, c in facets["fontes"].items():
        lines.append(f"   • {f}: {c}")
    
    lines.append(f"\n📍 **Por UF:** ({facets['num_cidades']} cidades, {facets['num_bairros']} bairros)")
    for u, c in facets["ufs"].items():
        lines.append(f"   • {u}: {c}")
    
    lines.append("\n🏘️ **Por tipo:**")
    for t, c in facets["tipos"].items():
        lines.append(f"   • {t}: {c}")
    
    if facets["precos"]:
        p = facets["precos"]
        lines.append(f"\n💰 **Preços (R$):**")
        lines.append(f"   Min: R$ {p['min']:,.2f}")
        lines.append(f"   Max: R$ {p['max']:,.2f}")
        lines.append(f"   Média: R$ {p['avg']:,.2f}")
        lines.append(f"   Mediana: R$ {p['median']:,.2f}")
    
    if facets["areas"]:
        a = facets["areas"]
        lines.append(f"\n📐 **Área (m²):**")
        lines.append(f"   Min: {a['min']:.0f}")
        lines.append(f"   Max: {a['max']:.0f}")
        lines.append(f"   Média: {a['avg']:.0f}")
    
    if facets["quartos"]:
        lines.append(f"\n🛏️ **Quartos:**")
        for q, c in facets["quartos"].items():
            lines.append(f"   {q}qt: {c}")
    
    lines.append(f"\n📸 **Total fotos:** {facets['total_fotos']}")
    
    return "\n".join(lines)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Compute facet stats from listing datasets")
    parser.add_argument("files", nargs="*", help="Specific JSON files to analyze")
    parser.add_argument("--output", "-o", help="Save facets as JSON")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted report")
    
    args = parser.parse_args()
    
    listings = load_listings(args.files or None)
    if not listings:
        print("Nenhum listing encontrado nos arquivos especificados.")
        return 1
    
    facets = compute_facets(listings)
    
    if args.json or args.output:
        output = json.dumps(facets, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output)
            print(f"💾 Saved to {args.output}")
        else:
            print(output)
    else:
        print(format_report(facets))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
