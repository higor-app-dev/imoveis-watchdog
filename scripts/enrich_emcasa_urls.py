#!/usr/bin/env python3
"""Enriquece imóveis do EmCasa no Turso com URLs dos anúncios originais.

O EmCasa usa a plataforma Foundation/Garagem AI (cdn.fndn.ai).
O crawl não salvou listingCode, mas ele é necessário para construir a URL.
Este script consulta a API Foundation por bairro, extrai listingCode + street,
combina com os dados no Turso e atualiza as URLs.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SITE_ID = "ab158f8f-0a75-4f9f-8a9b-54b834aa2698"
API_URL = f"https://cdn.fndn.ai/site/api/sites/{SITE_ID}/search"
PER_PAGE = 250

# ── Turso ──────────────────────────────────────────────────────────────

def _get_turso_creds():
    env = open(os.path.expanduser("~/.hermes/.env")).read()
    url = token = ""
    for line in env.split("\n"):
        if "TURSO_HERMES_DATA_DB_URL" in line and "=" in line:
            url = line.split("=", 1)[1].strip()
        if "TURSO_HERMES_DATA_DB_TOKEN" in line and "=" in line:
            token = line.split("=", 1)[1].strip()
    return url, token

def turso(sql):
    url, token = _get_turso_creds()
    payload = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": sql}}]}).encode()
    req = urllib.request.Request(url + "/v2/pipeline", data=payload,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    r = resp["results"][0]
    if r["type"] == "error":
        raise RuntimeError(f"Turso error: {r['error']}")
    cols = [c["name"] for c in r["response"]["result"]["cols"]]
    rows = []
    for row in r["response"]["result"]["rows"]:
        rows.append(dict(zip(cols, [c.get("value") if c["type"] != "null" else None for c in row])))
    return rows

# ── Helpers ────────────────────────────────────────────────────────────

def slug(s):
    """Converte string para slug usada nas URLs do EmCasa."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s).strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s

def build_emcasa_url(uf, cidade, bairro, rua, listing_code):
    """Constrói URL do anúncio original no EmCasa."""
    uf_slug = slug(uf)
    cidade_slug = slug(cidade)
    bairro_slug = slug(bairro)
    rua_slug = slug(rua)
    return f"https://www.emcasa.com/imoveis/{uf_slug}/{cidade_slug}/{bairro_slug}/{rua_slug}/id-{listing_code}"

def search_foundation(filter_by, page=1):
    """Busca uma página na API Foundation."""
    payload = json.dumps({
        "q": "*", "per_page": PER_PAGE, "page": page,
        "filter_by": filter_by,
    }).encode()
    req = urllib.request.Request(API_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://www.emcasa.com",
            "Referer": "https://www.emcasa.com/",
        }, method="POST")
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    hits = resp.get("hits", [])
    found = resp.get("found", len(hits))
    nb_pages = max(1, -(-found // PER_PAGE))
    return hits, found, nb_pages

# ── Main ───────────────────────────────────────────────────────────────

def main():
    print("🔍 Buscando imóveis EmCasa no Turso...")
    imoveis = turso(
        "SELECT id, bairro, endereco, cidade, uf, preco_venda, url FROM imoveis_watchdog WHERE fonte='emcasa'"
    )
    print(f"  {len(imoveis)} imóveis EmCasa encontrados")

    # Agrupa por bairro para fazer menos chamadas à API
    by_bairro: dict[str, list[dict]] = {}
    for imovel in imoveis:
        bairro = (imovel.get("bairro") or "").strip()
        if not bairro:
            continue
        # Normaliza bairro para o formato da API
        bairro_key = bairro.title().strip()
        if bairro_key not in by_bairro:
            by_bairro[bairro_key] = []
        by_bairro[bairro_key].append(imovel)

    print(f"  {len(by_bairro)} bairros únicos: {', '.join(by_bairro.keys())}")
    print()

    updated = 0
    errors = 0

    for bairro_nome, imoveis_do_bairro in sorted(by_bairro.items()):
        print(f"📌 Bairro: {bairro_nome} ({len(imoveis_do_bairro)} imóveis)")

        # Busca TODAS as páginas para este bairro
        filter_by = f"location_state:=SP && location_city:=São Paulo && location_neighborhood:={bairro_nome}"

        all_hits = []
        page = 1
        while True:
            try:
                hits, found, nb_pages = search_foundation(filter_by, page=page)
                all_hits.extend(hits)
                print(f"    Página {page}/{nb_pages} ({len(hits)} hits, total acumulado: {len(all_hits)})")
                if page >= nb_pages:
                    break
                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"    ⚠️  Erro na página {page}: {e}")
                break

        if not all_hits:
            print(f"    ⚠️  Nenhum hit encontrado para {bairro_nome}")
            continue

        # Indexa por {rua_normalizada}: {listingCode}
        index: dict[str, int] = {}
        for hit in all_hits:
            doc = hit.get("document", hit)
            lc = doc.get("listingCode")
            street = doc.get("location_street", doc.get("street", ""))
            if lc and street:
                key = slug(street)
                index[key] = lc

        # Para cada imóvel, busca o listingCode pela rua
        for imovel in imoveis_do_bairro:
            rua = (imovel.get("endereco") or "").strip()
            rua_key = slug(rua)
            lc = index.get(rua_key)

            if not lc:
                # Tenta match parcial
                for key, val in index.items():
                    if rua_key in key or key in rua_key:
                        lc = val
                        break

            if lc:
                # Constrói URL
                cidade = imovel.get("cidade", "São Paulo")
                uf = imovel.get("uf", "SP")
                url = build_emcasa_url(uf, cidade, bairro_nome, rua, lc)
                try:
                    eid = imovel["id"].replace("'", "''")
                    turso(f"UPDATE imoveis_watchdog SET url='{url}' WHERE id='{eid}'")
                    print(f"    ✅ {imovel['id'][:20]:20} → {url}")
                    updated += 1
                except Exception as e:
                    print(f"    ❌ Erro salvando {imovel['id']}: {e}")
                    errors += 1
            else:
                print(f"    ⚠️  Sem listingCode para {imovel['id'][:20]:20} ({rua})")
                errors += 1

    print(f"\n{'='*50}")
    print(f"✅ {updated} URLs atualizadas, {errors} erros")
    return 0

if __name__ == "__main__":
    sys.exit(main())
