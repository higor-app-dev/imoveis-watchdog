#!/usr/bin/env python3
"""Test emcasa_parser against real crawl data."""
import sys
import json
sys.path.insert(0, '/home/higor/imoveis-watchdog/skills/emcasa')
sys.path.insert(0, str(__import__('pathlib').Path.home() / '.hermes'))

from emcasa_parser import from_emcasa_hit, from_emcasa_hits

with open('/home/higor/imoveis-watchdog/data/results/emcasa_crawl_sp_20260621_211400.json') as f:
    data = json.load(f)

listings = data['listings']
print(f"Total listings in crawl: {len(listings)}")

# Parse first 100 items
sample = listings[:100]
results = from_emcasa_hits(sample)
print(f"Parsed: {len(results)} / {len(sample)}")

# Check for issues
empty_id = sum(1 for r in results if not r.id)
empty_title = sum(1 for r in results if not r.titulo)
empty_url = sum(1 for r in results if not r.url)
empty_tipo = sum(1 for r in results if not r.tipo)
empty_uf = sum(1 for r in results if not r.uf)
empty_price = sum(1 for r in results if r.preco_venda is None)
empty_fotos = sum(1 for r in results if not r.fotos)
empty_coords = sum(1 for r in results if not getattr(r, '_extra', {}) or not r._extra.get('coordinates'))
empty_cidade = sum(1 for r in results if not r.cidade)
empty_bairro = sum(1 for r in results if not r.bairro)

print(f"\n--- Quality report (first 100 items) ---")
print(f"Empty id:     {empty_id}/100")
print(f"Empty title:  {empty_title}/100")
print(f"Empty url:    {empty_url}/100")
print(f"Empty tipo:   {empty_tipo}/100")
print(f"Empty uf:     {empty_uf}/100")
print(f"Empty preco:  {empty_price}/100")
print(f"Empty fotos:  {empty_fotos}/100")
print(f"Empty coords: {empty_coords}/100")
print(f"Empty cidade: {empty_cidade}/100")
print(f"Empty bairro: {empty_bairro}/100")

# Show first parsed item details
print(f"\n--- First parsed item ---")
r = results[0]
d = r.to_dict()
for k, v in sorted(d.items()):
    if isinstance(v, str) and len(v) > 80:
        v = v[:80] + '...'
    elif isinstance(v, list) and len(v) > 3:
        v = f"list[{len(v)}]: {v[:3]}..."
    print(f"  {k}: {v}")
extra = getattr(r, '_extra', {})
if extra:
    print(f"\n  _extra:")
    for k, v in sorted(extra.items()):
        if v is not None:
            print(f"    {k}: {str(v)[:80]}")
