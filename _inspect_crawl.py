#!/usr/bin/env python3
"""Inspect the EmCasa crawl data structure."""
import json

with open('/home/higor/imoveis-watchdog/data/results/emcasa_crawl_sp_20260621_211400.json') as f:
    data = json.load(f)

listings = data['listings']
print(f"Total listings: {len(listings)}")

# Check a few items
for idx in range(min(5, len(listings))):
    item = listings[idx]
    print(f"\n--- Item {idx} ---")
    print(f"Keys: {sorted(item.keys())}")
    for key in sorted(item.keys()):
        val = item[key]
        if isinstance(val, str) and len(val) > 80:
            val = val[:80] + '...'
        elif isinstance(val, list):
            val = f"list[{len(val)}]"
            if val == "list[0]":
                val = "list[0]"
            elif len(val) > 0 and isinstance(val[0], str):
                val = f"list[{len(val)}]: first={val[0][:80]}"
            elif len(val) > 0 and isinstance(val[0], dict):
                val = f"list[{len(val)}]: first keys={list(val[0].keys())}"
            else:
                val = f"list[{len(val)}]"
        elif isinstance(val, dict):
            val = f"dict({sorted(val.keys())})"
        print(f"  {key}: {type(val).__name__} = {val}")
