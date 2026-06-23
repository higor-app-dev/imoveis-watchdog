#!/usr/bin/env python3
"""Check RJ crawl metadata and first item."""
import json

rj_path = '/home/higor/imoveis-watchdog/data/results/emcasa_crawl_rj_20260621_211858.json'
with open(rj_path) as f:
    data = json.load(f)

print("=== Meta data ===")
meta = data.get('meta', {})
for k, v in meta.items():
    print(f"  {k}: {v}")

# Check cities
cities = set()
for item in data['listings']:
    c = item.get('location_city', '')
    if c:
        cities.add(c)
print(f"\n=== Cities ({len(cities)}) ===")
for c in sorted(cities):
    print(f"  {c}")

# Check first item keys
item = data['listings'][0]
print(f"\n=== First item keys vs SP ===")
sp_path = '/home/higor/imoveis-watchdog/data/results/emcasa_crawl_sp_20260621_211400.json'
with open(sp_path) as f:
    sp_item = json.load(f)['listings'][0]
sp_keys = set(sp_item.keys())
rj_keys = set(item.keys())
only_sp = sp_keys - rj_keys
only_rj = rj_keys - sp_keys
if only_sp:
    print(f"  Only in SP: {only_sp}")
if only_rj:
    print(f"  Only in RJ: {only_rj}")
print(f"  Same keys: {len(sp_keys & rj_keys)}")
