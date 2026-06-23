#!/usr/bin/env python3
"""Deep dive into image URLs and coordinates format."""
import json

with open('/home/higor/imoveis-watchdog/data/results/emcasa_crawl_sp_20260621_211400.json') as f:
    data = json.load(f)

listings = data['listings']
item = listings[0]

# Image URLs
print("=== imageUrls ===")
urls = item.get('imageUrls', [])
if isinstance(urls, list):
    print(f"Type: list of {len(urls)}")
    for u in urls[:3]:
        print(f"  {type(u).__name__} = {str(u)[:120]}")
    print(f"  ... ({len(urls)} total)")
else:
    print(f"Type: {type(urls).__name__} = {str(urls)[:100]}")

# thumbnailUrls
print("\n=== thumbnailUrls ===")
turls = item.get('thumbnailUrls', [])
if isinstance(turls, list):
    print(f"Type: list of {len(turls)}")
    for u in turls[:3]:
        print(f"  {type(u).__name__} = {str(u)[:120]}")

# Coordinates
print("\n=== coordinates ===")
coords = item.get('coordinates', None)
if isinstance(coords, dict):
    print(f"Keys: {sorted(coords.keys())}")
    for k, v in coords.items():
        print(f"  {k}: {v}")

# buildingAmenities
print("\n=== buildingAmenities ===")
ba = item.get('buildingAmenities', [])
print(f"Type: {type(ba).__name__}")
if isinstance(ba, list):
    print(f"Length: {len(ba)}")
    for a in ba[:5]:
        print(f"  {a}")

# propertyFeatures
print("\n=== propertyFeatures ===")
pf = item.get('propertyFeatures', [])
print(f"Type: {type(pf).__name__}")
if isinstance(pf, list):
    print(f"Length: {len(pf)}")
    for f_ in pf[:5]:
        print(f"  {f_}")

# Check all items for ID/unitKey/objectID/slug/state
print("\n=== ID/State scan (first 50) ===")
id_issues = 0
state_issues = 0
for i, item in enumerate(listings[:1000]):
    has_id = 'id' in item or 'unitKey' in item or 'objectID' in item
    if not has_id:
        id_issues += 1
    has_state = 'state' in item or 'location_state' in item
    if not has_state:
        state_issues += 1
print(f"Items without id/unitKey/objectID (first 1000): {id_issues}")
print(f"Items without state/location_state (first 1000): {state_issues}")

# Check if description or propertyTitle have meaningful values
print("\n=== Description/title sample ===")
for i in range(5):
    item = listings[i]
    desc = item.get('description', '')
    title = item.get('propertyTitle', '')
    print(f"[{i}] title='{title[:60]}' | desc='{desc[:60]}' | price={item.get('askingPrice')}")
