#!/usr/bin/env python3
"""Check crawl metadata for state info."""
import json

with open('/home/higor/imoveis-watchdog/data/results/emcasa_crawl_sp_20260621_211400.json') as f:
    data = json.load(f)

print("=== Meta data ===")
meta = data.get('meta', {})
for k, v in meta.items():
    print(f"  {k}: {v}")

# Check unique cities
cities = set()
for item in data['listings']:
    c = item.get('location_city', '')
    if c:
        cities.add(c)
print(f"\n=== Cities in SP crawl ({len(cities)}) ===")
for c in sorted(cities):
    print(f"  {c}")
