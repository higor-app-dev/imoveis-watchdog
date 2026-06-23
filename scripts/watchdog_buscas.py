#!/usr/bin/env python3
"""
watchdog_buscas.py — Motor de buscas salvas do Imóveis Watchdog.

Lê critérios de busca da tabela buscas_watchdog (Turso), executa a
extração unificada nos portais aplicáveis, filtra pelos critérios,
salva resultados na tabela imoveis_watchdog e atualiza metadados.

Uso:
    python scripts/watchdog_buscas.py                    # executa todas as buscas ativas
    python scripts/watchdog_buscas.py --busca-id 1       # executa apenas busca ID=1
    python scripts/watchdog_buscas.py --save-results      # salva resultados em JSON
    python scripts/watchdog_buscas.py --dry-run           # só mostra o que faria
    python scripts/watchdog_buscas.py --list-buscas       # lista buscas ativas
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "skills"))
DATA_RESULTS_DIR = REPO_ROOT / "data" / "results"

logging.basicConfig(
    level=logging.INFO, format="%(message)s", stream=sys.stdout,
)
logger = logging.getLogger("watchdog_buscas")


# ── Turso helpers ──────────────────────────────────────────────────────────


def _turso(sql: str) -> list[dict[str, Any]]:
    """Executa SQL no Turso e retorna lista de dicts."""
    url = os.environ["TURSO_HERMES_DATA_DB_URL"]
    tok = os.environ["TURSO_HERMES_DATA_DB_TOKEN"]
    body = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": sql}}]}).encode()
    req = urllib.request.Request(
        url + "/v2/pipeline", data=body,
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
        method="POST")
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if "error" in resp:
        raise RuntimeError(f"Turso error: {resp['error']}")
    result = resp["results"][0]["response"]["result"]
    cols = [c["name"] for c in result["cols"]]
    rows = []
    for row in result["rows"]:
        rows.append(dict(zip(cols, [
            c.get("value") if c["type"] != "null" else None for c in row
        ])))
    return rows


# ── Load searches ──────────────────────────────────────────────────────────


def list_buscas() -> list[dict[str, Any]]:
    """Lista todas as buscas ativas."""
    return _turso("SELECT * FROM buscas_watchdog WHERE ativa=1 ORDER BY id")


def get_busca(busca_id: int) -> dict[str, Any] | None:
    """Retorna uma busca específica."""
    rows = _turso(f"SELECT * FROM buscas_watchdog WHERE id={busca_id} AND ativa=1")
    return rows[0] if rows else None


# ── Target builder ─────────────────────────────────────────────────────────


def build_targets(busca: dict[str, Any]) -> list[dict[str, Any]]:
    """Converte critérios de busca em targets para cada portal.

    Mapeia os critérios humanos para slugs específicos de cada portal.
    """
    modalidades: list[str] = json.loads(busca.get("modalidades", '["compra"]'))
    bairros: list[str] = json.loads(busca.get("bairros", "[]"))
    cidades: list[str] = json.loads(busca.get("cidades", '["São Paulo"]'))
    uf = busca.get("uf", "SP")
    tipos: list[str] = json.loads(busca.get("tipos", "[]"))
    preco_max = busca.get("preco_max")
    preco_min = busca.get("preco_min")
    area_min = busca.get("area_min")
    quartos_min = busca.get("quartos_min")
    vagas_min = busca.get("vagas_min", 0)

    targets: list[dict[str, Any]] = []

    for cidade in cidades:
        # ── QuintoAndar ─────────────────────────────────────────────────
        if "compra" in modalidades:
            cidade_slug = cidade.lower() \
                .replace(" ", "-") \
                .replace("ã", "a").replace("á", "a") \
                .replace("é", "e").replace("ê", "e") \
                .replace("í", "i").replace("ó", "o").replace("ú", "u") \
                .replace("ç", "c") + f"-{uf.lower()}-brasil"

            targets.append({
                "portal": "quinto_andar",
                "modalidade": "compra",
                "cidade": cidade_slug,
                "bairros": bairros if bairros else [],
                "tipos": tipos if tipos else ["apartamento", "casa", "kitnet", "studio"],
                "preco_max": preco_max,
                "preco_min": preco_min,
                "area_min": area_min,
                "quartos_min": quartos_min,
                "vagas_min": vagas_min,
            })

        # ── Loft ────────────────────────────────────────────────────────
        if "compra" in modalidades:
            loft_city = f"{uf.lower()}/{cidade.lower().replace(' ', '-').replace('ã', 'a').replace('á', 'a')}"
            targets.append({
                "portal": "loft",
                "modalidade": "compra",
                "cidade": loft_city,
                "bairros": bairros if bairros else [],
                "tipos": tipos if tipos else ["apartamentos"],
                "preco_max": preco_max,
                "preco_min": preco_min,
                "area_min": area_min,
            })

        # ── EmCasa ──────────────────────────────────────────────────────
        if "compra" in modalidades:
            targets.append({
                "portal": "emcasa",
                "modalidade": "compra",
                "cidade": cidade,
                "uf": uf,
                "bairros": bairros if bairros else [],
                "tipos": tipos if tipos else ["apartamento", "casa", "cobertura", "kitnet", "studio"],
                "preco_max": preco_max,
                "preco_min": preco_min,
                "area_min": area_min,
                "quartos_min": quartos_min,
            })

        # ── Lello ───────────────────────────────────────────────────────
        if "compra" in modalidades:
            targets.append({
                "portal": "lello",
                "modalidade": "compra",
                "cidade": cidade.lower(),
                "uf": uf,
                "bairros": bairros if bairros else [],
                "tipos": tipos if tipos else ["apartamento", "casa", "cobertura", "kitnet", "studio"],
                "preco_max": preco_max,
            })

    # ── Leilões ─────────────────────────────────────────────────────────
    if "leilao" in modalidades:
        for portal_slug in ("sodre_santoro", "zuk", "biasi_leiloes", "mega_leiloes", "caixa_imoveis"):
            targets.append({
                "portal": portal_slug,
                "modalidade": "leilao",
                "uf": uf,
                "tipos": tipos if tipos else ["apartamento", "casa", "terreno", "imovel_residencial"],
                "preco_max": preco_max,
            })

    return targets


# ── Execute search ─────────────────────────────────────────────────────────


def executar_busca(
    busca: dict[str, Any],
    *,
    save_results: bool = True,
    dry_run: bool = False,
) -> int:
    """Executa uma busca: extrai → filtra → salva → atualiza Turso.

    Returns:
        Número de imóveis encontrados.
    """
    nome = busca["nome"]
    busca_id = busca["id"]

    print(f"\n{'='*60}")
    print(f"🔍 Busca #{busca_id}: {nome}")
    print(f"{'='*60}")

    # 1. Build targets
    targets = build_targets(busca)
    print(f"\n📋 Targets gerados: {len(targets)}")
    for t in targets:
        print(f"  • {t['portal']:<20} | {t.get('modalidade','?'):<8} | {t.get('cidade', t.get('uf','?'))}")

    if dry_run:
        print(f"\n  [DRY-RUN] {len(targets)} targets, 0 imóveis extraídos")
        return 0

    # 2. Extrair de todos os portais
    print("\n🔍 Extraindo dados...")
    from scripts.extractor import extract_all, load_targets

    all_listings = extract_all(targets)
    print(f"  Total extraído: {len(all_listings)} listings")

    if not all_listings:
        print("  ⚠️  Nenhum listing encontrado")
        return 0

    # 3. Aplicar filtros da busca (pós-extração)
    print("\n🔎 Filtrando pelos critérios...")
    bairros_set = set(json.loads(busca.get("bairros", "[]")))
    # Turso retorna números como string — converte
    def _num(v):
        if v is None: return None
        try: return float(v)
        except: return None
    def _int(v, default=0):
        if v is None: return default
        try: return int(float(v))
        except: return default

    preco_max = _num(busca.get("preco_max"))
    preco_min = _num(busca.get("preco_min"))
    area_min = _num(busca.get("area_min"))
    vagas_min = _int(busca.get("vagas_min"), 0)
    modalidades_list: list[str] = json.loads(busca.get("modalidades", '["compra"]'))

    filtrados = []
    for item in all_listings:
        # Filtro de bairro
        item_bairro = str(item.get("bairro", item.get("neighbourhood", item.get("location_neighborhood", "")))).strip().lower()
        if bairros_set:
            if not any(b.lower() in item_bairro or item_bairro in b.lower() for b in bairros_set):
                continue

        # Filtro de cidade + UF
        cidades_list: list[str] = json.loads(busca.get("cidades", '["São Paulo"]'))
        uf_busca = str(busca.get("uf", "SP")).strip().upper()
        item_cidade = str(item.get("cidade", item.get("municipality", item.get("location_city", "")))).strip().lower()
        item_uf = str(item.get("uf", item.get("stateCode", item.get("location_state", "")))).strip().upper()
        if cidades_list:
            cidade_match = any(c.lower() in item_cidade or item_cidade in c.lower() for c in cidades_list)
            if not cidade_match:
                continue
        if uf_busca and item_uf and item_uf != uf_busca:
            continue

        # Filtro de preço (tenta todos os nomes de campo conhecidos)
        price = item.get("preco_venda", item.get("salePrice", item.get("price", item.get("askingPrice", 0))))
        if price and isinstance(price, (int, float)):
            if preco_max and price > preco_max:
                continue
            if preco_min and price < preco_min:
                continue
        elif preco_max:
            continue  # sem preço, não consegue filtrar

        # Filtro de área
        area = item.get("area", item.get("area_m2", item.get("usableArea", item.get("property_area_total", 0))))
        if area_min and isinstance(area, (int, float)) and area < area_min:
            continue

        # Filtro de vagas
        vagas = item.get("vagas", item.get("vagas_garagem", item.get("parkingSpots", item.get("parkingSpaces"))))
        if vagas is None:
            vagas = 0
        if vagas_min and vagas < vagas_min:
            continue

        filtrados.append(item)

    print(f"  Listings após filtro: {len(filtrados)}")

    if not filtrados:
        print("  Nenhum imóvel corresponde aos critérios")
        return 0

    # 4. Salvar no Turso (imoveis_watchdog)
    print(f"\n💾 Salvando {len(filtrados)} imóveis no Turso...")
    salvos = 0
    for item in filtrados:
        # Gera ID único: se não existir, cria hash composto
        list_id = str(item.get("id", item.get("list_id", "")))
        if not list_id:
            composite = str(item.get("location_street", item.get("endereco", ""))) + \
                        str(item.get("location_neighborhood", item.get("bairro", ""))) + \
                        str(item.get("propertyTitle", item.get("titulo", ""))) + \
                        str(item.get("price", item.get("preco_venda", "")))
            list_id = "emcasa_" + str(abs(hash(composite)) % 10**9)

        titulo = item.get("propertyTitle", item.get("titulo", item.get("title", "")))
        fonte = item.get("fonte", item.get("portal", ""))
        if not fonte:
            fonte = "emcasa" if list_id.startswith("emcasa_") else "desconhecido"
        url = item.get("url", "")
        endereco = item.get("endereco", item.get("address", {}).get("street", item.get("location_street", "")))
        bairro = item.get("bairro", item.get("neighbourhood", item.get("location_neighborhood", "")))
        cidade = item.get("cidade", item.get("municipality", item.get("location_city", "")))
        uf = item.get("uf", item.get("stateCode", item.get("location_state", "")))
        tipo = item.get("tipo", item.get("type", ""))
        modalidade = busca.get("modalidades", '["compra"]')

        # ─ Preços: fallback para campos do crawl bruto ─
        preco_venda = item.get("askingPrice", item.get("price", item.get("preco_venda", item.get("salePrice"))))
        preco_aluguel = item.get("preco_aluguel", item.get("rentPrice", item.get("rentalPrice")))
        condominio = item.get("condominio", item.get("condoFee"))
        iptu = item.get("iptu", item.get("propertyTax"))
        area = item.get("area", item.get("area_m2", item.get("usableArea", item.get("property_area_total"))))
        quartos = item.get("quartos", item.get("bedrooms"))
        banheiros = item.get("banheiros", item.get("bathrooms"))
        vagas = item.get("vagas", item.get("vagas_garagem", item.get("parkingSpots", item.get("parkingSpaces"))))
        descricao = item.get("descricao", item.get("description", ""))

        # ─ Foto: primeira URL da lista de fotos ─
        fotos_raw = item.get("fotos", item.get("photos", item.get("images", item.get("imageUrls", []))))
        foto_url = ""
        if isinstance(fotos_raw, list) and len(fotos_raw) > 0:
            first = fotos_raw[0]
            if isinstance(first, dict):
                foto_url = first.get("url", "")
            elif isinstance(first, str) and first.startswith("http"):
                foto_url = first
        elif isinstance(fotos_raw, str) and fotos_raw.startswith("http"):
            foto_url = fotos_raw
        if not foto_url:
            primary = item.get("primaryImageUrl", item.get("photo", item.get("image", "")))
            if primary and isinstance(primary, str) and primary.startswith("http"):
                foto_url = primary

        # ─ Coordenadas ─
        latitude, longitude = None, None
        coords = item.get("coordinates")
        # Also check _extra (emcasa parser stores coords there)
        if not coords:
            extra = item.get("_extra", {})
            if isinstance(extra, dict):
                coords = extra.get("coordinates")
        if isinstance(coords, dict):
            latitude = coords.get("lat", coords.get("latitude"))
            longitude = coords.get("lng", coords.get("longitude"))
        elif isinstance(coords, (list, tuple)) and len(coords) >= 2:
            latitude, longitude = coords[0], coords[1]
        elif item.get("latitude") and item.get("longitude"):
            latitude = item.get("latitude")
            longitude = item.get("longitude")

        # Escapa aspas simples no SQL
        def esc(s):
            if s is None:
                return "NULL"
            return "'" + str(s).replace("'", "''") + "'"

        def esc_null(v):
            if v is None:
                return "NULL"
            return str(v)

        sql = f"""
        INSERT INTO imoveis_watchdog (id, titulo, fonte, url, endereco, bairro, cidade, uf,
            tipo, preco_venda, preco_aluguel, condominio, iptu, area_m2, quartos, banheiros,
            vagas, descricao, foto_url, latitude, longitude, data_ultima_vista, removido)
        VALUES ({esc(list_id)}, {esc(titulo)}, {esc(fonte)}, {esc(url)}, {esc(endereco)},
            {esc(bairro)}, {esc(cidade)}, {esc(uf)}, {esc(tipo)},
            {esc_null(preco_venda)}, {esc_null(preco_aluguel)}, {esc_null(condominio)},
            {esc_null(iptu)}, {esc_null(area)}, {esc_null(quartos)},
            {esc_null(banheiros)}, {esc_null(vagas)}, {esc(descricao)},
            {esc(foto_url)}, {esc_null(latitude)}, {esc_null(longitude)},
            datetime('now'), 0)
        ON CONFLICT(id) DO UPDATE SET
            data_ultima_vista=datetime('now'),
            preco_venda=COALESCE(excluded.preco_venda, preco_venda),
            preco_aluguel=COALESCE(excluded.preco_aluguel, preco_aluguel),
            condominio=COALESCE(excluded.condominio, condominio),
            iptu=COALESCE(excluded.iptu, iptu),
            foto_url=COALESCE(excluded.foto_url, foto_url),
            latitude=COALESCE(excluded.latitude, latitude),
            longitude=COALESCE(excluded.longitude, longitude),
            removido=0
        """
        try:
            _turso(sql)
            # Associa imóvel à busca na tabela de junção
            _turso(f"""
                INSERT OR IGNORE INTO imovel_busca (imovel_id, busca_id)
                VALUES ({esc(list_id)}, {busca_id})
            """)
            salvos += 1
        except Exception as e:
            logger.warning(f"  ⚠️  Erro salvando {list_id}: {e}")

    print(f"  ✅ {salvos}/{len(filtrados)} salvos/atualizados no Turso")

    # 5. Atualizar metadados da busca
    _turso(f"""
        UPDATE buscas_watchdog
        SET ultima_execucao=datetime('now'), ultimo_total={len(filtrados)}
        WHERE id={busca_id}
    """)

    # 6. Salvar JSON
    if save_results:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        out_path = DATA_RESULTS_DIR / f"busca_{busca_id}_{timestamp}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "busca_id": busca_id,
            "busca_nome": nome,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(filtrados),
            "listings": filtrados,
        }
        out_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  📄 Resultados salvos: {out_path}")

    # 7. Resumo
    print(f"\n📊 Resumo da busca #{busca_id}:")
    print(f"  Nome:      {nome}")
    print(f"  Imóveis:   {len(filtrados)}")
    print(f"  Portais:   {len(set(i.get('fonte','?') for i in filtrados))}")

    return len(filtrados)


# ── CLI ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Motor de buscas salvas do Imóveis Watchdog"
    )
    parser.add_argument("--busca-id", type=int, help="Executa apenas busca específica")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que faria")
    parser.add_argument("--no-save", action="store_true", help="Não salva resultados")
    parser.add_argument("--list-buscas", action="store_true", help="Lista buscas ativas")
    args = parser.parse_args()

    if args.list_buscas:
        print("📋 Buscas ativas no Watchdog:\n")
        buscas = list_buscas()
        if not buscas:
            print("  Nenhuma busca ativa cadastrada.")
            return 0
        for b in buscas:
            modalidades = json.loads(b.get("modalidades", "[]"))
            bairros = json.loads(b.get("bairros", "[]"))
            ultima = b.get("ultima_execucao", "nunca") or "nunca"
            total = b.get("ultimo_total", "-")
            print(f"  #{b['id']} | {b['nome']}")
            print(f"       Modalidades: {', '.join(modalidades)}")
            print(f"       Bairros:     {', '.join(bairros[:5])}{'...' if len(bairros) > 5 else ''}")
            print(f"       Preço max:   R$ {b['preco_max']:,.0f}" if b.get("preco_max") else "")
            print(f"       Área min:    {b['area_min']} m²" if b.get("area_min") else "")
            print(f"       Última exec: {ultima} ({total} imóveis)")
            print()
        return 0

    # Executa busca(s)
    if args.busca_id:
        busca = get_busca(args.busca_id)
        if not busca:
            print(f"❌ Busca #{args.busca_id} não encontrada ou inativa")
            return 1
        buscas = [busca]
    else:
        buscas = list_buscas()
        if not buscas:
            print("❌ Nenhuma busca ativa cadastrada. Use --list-buscas para ver.")
            return 1

    total_geral = 0
    for busca in buscas:
        total = executar_busca(
            busca,
            save_results=not args.no_save,
            dry_run=args.dry_run,
        )
        total_geral += total

    print(f"\n{'='*60}")
    print(f"✅ Todas as buscas concluídas! Total: {total_geral} imóveis encontrados")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
