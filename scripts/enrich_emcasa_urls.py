#!/usr/bin/env python3
"""Enriquece imóveis do EmCasa no Turso com URLs dos anúncios originais.

O EmCasa usa a plataforma Foundation/Garagem AI (cdn.fndn.ai).
O crawl não salvou listingCode, mas ele é necessário para construir a URL.
Este script consulta a API Foundation por bairro, extrai listingCode + street,
combina com os dados no Turso e atualiza as URLs.

Suporta múltiplas cidades (não apenas São Paulo).
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
    u = token = ""
    for line in env.split("\n"):
        if "TURSO_HERMES_DATA_DB_URL" in line and "=" in line:
            u = line.split("=", 1)[1].strip()
        if "TURSO_HERMES_DATA_DB_TOKEN" in line and "=" in line:
            token = line.split("=", 1)[1].strip()
    return u, token

def turso(sql):
    u, token = _get_turso_creds()
    payload = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": sql}}]}).encode()
    req = urllib.request.Request(u + "/v2/pipeline", data=payload,
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
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s).strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s

def build_emcasa_url(uf, cidade, bairro, rua, listing_code):
    """Constrói URL do anúncio original no EmCasa."""
    uf_slug = slug(uf) or "sp"
    cidade_slug = slug(cidade) or "sao-paulo"
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

def fetch_all_pages(filter_by):
    """Busca TODAS as páginas para um filtro, retornando todos os hits."""
    all_hits = []
    page = 1
    while True:
        try:
            hits, found, nb_pages = search_foundation(filter_by, page=page)
            all_hits.extend(hits)
            if page >= nb_pages:
                break
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"    ⚠️  Erro na página {page}: {e}")
            break
    return all_hits

# ── Main ───────────────────────────────────────────────────────────────

def main():
    print("🔍 Buscando imóveis EmCasa no Turso...")
    imoveis = turso(
        "SELECT id, bairro, endereco, cidade, uf, preco_venda, url FROM imoveis_watchdog WHERE fonte='emcasa'"
    )
    print(f"  {len(imoveis)} imóveis EmCasa encontrados")

    # Filtra apenas os que precisam de correção
    imoveis_pendentes = [
        i for i in imoveis
        if not i.get("url") or "/imovel/" in (i.get("url") or "")
    ]
    print(f"  {len(imoveis_pendentes)} pendentes (sem URL ou com formato inválido)")

    # Agrupa por {uf, cidade, bairro}
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for im in imoveis_pendentes:
        key = (
            (im.get("uf") or "SP").strip().upper(),
            (im.get("cidade") or "São Paulo").strip(),
            (im.get("bairro") or "").strip().title(),
        )
        if key not in groups:
            groups[key] = []
        groups[key].append(im)

    print(f"  {len(groups)} grupos (UF/Cidade/Bairro) únicos\n")

    updated = 0
    not_found = 0

    for (uf_g, cidade_g, bairro_g), imoveis_g in sorted(groups.items()):
        print(f"📌 {uf_g}/{cidade_g}/{bairro_g} ({len(imoveis_g)} imóveis)")

        # Busca da Foundation API
        filter_by = f"location_state:={uf_g} && location_city:={cidade_g} && location_neighborhood:={bairro_g}"
        all_hits = fetch_all_pages(filter_by)

        if not all_hits:
            # Tenta sem bairro (busca geral na cidade)
            print(f"    ⚠️  Nenhum hit para {bairro_g}, tentando busca geral na cidade...")
            filter_by = f"location_state:={uf_g} && location_city:={cidade_g}"
            all_hits = fetch_all_pages(filter_by)

        if not all_hits:
            print(f"    ❌ Nada encontrado na Foundation para {cidade_g}/{bairro_g}")
            not_found += len(imoveis_g)
            continue

        # Indexa hits por {rua_normalizada}: {listingCode}
        index: dict[str, int] = {}
        for hit in all_hits:
            doc = hit.get("document", hit)
            lc = doc.get("listingCode")
            street = doc.get("location_street", doc.get("street", ""))
            if lc and street:
                index[slug(street)] = lc

        print(f"    Indexados {len(index)} ruas de {len(all_hits)} hits")

        # Match com cada imóvel
        group_updated = 0
        for im in imoveis_g:
            rua = (im.get("endereco") or "").strip()
            rua_key = slug(rua)
            lc = index.get(rua_key)

            if not lc:
                # Fallback: match parcial (sem o prefixo "Rua"/"Avenida")
                for key, val in index.items():
                    if rua_key and (rua_key in key or key in rua_key):
                        lc = val
                        break

            if not lc:
                # Fallback: match por primeiras letras
                for key, val in index.items():
                    if rua_key and len(rua_key) > 5:
                        if rua_key[:8] in key or key[:8] in rua_key:
                            lc = val
                            break

            if lc:
                url = build_emcasa_url(uf_g, cidade_g, bairro_g, rua, lc)
                try:
                    eid = im["id"].replace("'", "''")
                    turso(f"UPDATE imoveis_watchdog SET url='{url}' WHERE id='{eid}'")
                    print(f"    ✅ {im['id'][:30]:30} → {url}")
                    group_updated += 1
                except Exception as e:
                    print(f"    ❌ Erro salvando {im['id']}: {e}")
            else:
                # Último fallback: matching por tamanho de rua + bairro
                # (pula se não achou nada mesmo depois de todos os fallbacks)
                print(f"    ⚠️  Sem listingCode para {im['id'][:30]:30} ({rua})")
                not_found += 1

        updated += group_updated
        print(f"    Grupo: {group_updated}/{len(imoveis_g)} atualizados\n")

    print(f"\n{'='*50}")
    print(f"✅ {updated} URLs atualizadas")
    print(f"❌ {not_found} imóveis sem correspondência na Foundation API")
    return 0

if __name__ == "__main__":
    sys.exit(main())
