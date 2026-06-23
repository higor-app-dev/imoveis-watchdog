#!/usr/bin/env python3
"""Check data quality in Turso"""
import os, json, urllib.request

env = open(os.path.expanduser("~/.hermes/.env")).read()
url = token = ""
for line in env.split("\n"):
    if "TURSO_HERMES_DATA_DB_URL" in line and "=" in line:
        url = line.split("=", 1)[1].strip()
    if "TURSO_HERMES_DATA_DB_TOKEN" in line and "=" in line:
        token = line.split("=", 1)[1].strip()

def q(sql):
    payload = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": sql}}]}).encode()
    req = urllib.request.Request(url + "/v2/pipeline", data=payload,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    r = resp["results"][0]
    if r["type"] == "error":
        print(f"ERROR: {r['error']}")
        return []
    cols = r["response"]["result"]["cols"]
    rows = r["response"]["result"]["rows"]
    result = []
    for row in rows:
        vals = {}
        for i, c in enumerate(cols):
            v = row[i]["value"] if row[i]["type"] != "null" else None
            vals[c["name"]] = v
        result.append(vals)
    return result

total = int(q("SELECT COUNT(*) as c FROM imoveis_watchdog")[0]["c"])
com_preco = int(q("SELECT COUNT(*) as c FROM imoveis_watchdog WHERE preco_venda IS NOT NULL")[0]["c"])
sem_foto = int(q("SELECT COUNT(*) as c FROM imoveis_watchdog WHERE foto_url IS NULL OR foto_url = ''")[0]["c"])
com_coord = int(q("SELECT COUNT(*) as c FROM imoveis_watchdog WHERE latitude IS NOT NULL")[0]["c"])
com_area = int(q("SELECT COUNT(*) as c FROM imoveis_watchdog WHERE area_m2 IS NOT NULL")[0]["c"])

print(f"Total:      {total}")
print(f"Com preco:  {com_preco} ({100*com_preco//total}%)")
print(f"Sem foto:   {sem_foto} ({100-100*sem_foto//total}% com foto)")
print(f"Com coord:  {com_coord} ({100*com_coord//total}%)")
print(f"Com area:   {com_area} ({100*com_area//total}%)")

precos = q("SELECT MIN(preco_venda) as min, MAX(preco_venda) as max, ROUND(AVG(preco_venda),0) as med FROM imoveis_watchdog")
print(f"Precos: R$ {float(precos[0]['min']):,.0f} ~ R$ {float(precos[0]['max']):,.0f} (media R$ {float(precos[0]['med']):,.0f})")

bairros = q("SELECT bairro, COUNT(*) as c FROM imoveis_watchdog GROUP BY bairro ORDER BY c DESC")
bairros_str = ", ".join(f'{row["bairro"]} ({row["c"]})' for row in bairros)
print(f"Bairros: {bairros_str}")

foto = q("SELECT foto_url FROM imoveis_watchdog WHERE foto_url != '' LIMIT 1")
if foto:
    print(f"Exemplo foto: {foto[0]['foto_url'][:80]}...")
