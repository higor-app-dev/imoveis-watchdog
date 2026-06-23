#!/usr/bin/env python3
"""Testes para o cliente da API do EmCasa."""

import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

# Add parent dirs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skills.emcasa.emcasa_api import (
    EmCasaClient,
    EmCasaSearchResult,
    EmCasaAPIError,
    PageCache,
    parse_hit,
    filter_city,
    filter_city_type,
    filter_neighborhood,
    TIPO_MAP,
    API_URL,
    DEFAULT_PER_PAGE,
)


class TestEmCasaSearchResult(unittest.TestCase):
    def test_nb_pages_zero(self):
        r = EmCasaSearchResult(found=0, page=1, per_page=12, hits=[], facet_counts=[])
        self.assertEqual(r.nb_pages, 0)
        self.assertFalse(r.has_more)

    def test_nb_pages_exact(self):
        r = EmCasaSearchResult(found=12, page=1, per_page=12, hits=[], facet_counts=[])
        self.assertEqual(r.nb_pages, 1)
        self.assertFalse(r.has_more)

    def test_nb_pages_round_up(self):
        r = EmCasaSearchResult(found=13, page=1, per_page=12, hits=[], facet_counts=[])
        self.assertEqual(r.nb_pages, 2)
        self.assertTrue(r.has_more)

    def test_nb_pages_large(self):
        r = EmCasaSearchResult(found=12800, page=1, per_page=12, hits=[], facet_counts=[])
        # 12800 / 12 = 1066.66 → ceil = 1067
        self.assertEqual(r.nb_pages, 1067)
        self.assertTrue(r.has_more)

    def test_nb_pages_last_page(self):
        r = EmCasaSearchResult(found=12800, page=1067, per_page=12, hits=[], facet_counts=[])
        self.assertEqual(r.nb_pages, 1067)
        self.assertFalse(r.has_more)


class TestFilterHelpers(unittest.TestCase):
    def test_filter_city(self):
        result = filter_city("São Paulo", "SP")
        self.assertEqual(result, "location_state:=SP && location_city:=São Paulo")

    def test_filter_city_type(self):
        result = filter_city_type("São Paulo", "apartamento", "SP")
        self.assertEqual(result, "location_state:=SP && location_city:=São Paulo && property_type:=apartment")

    def test_filter_neighborhood(self):
        result = filter_neighborhood("Vila Madalena", "São Paulo", "SP")
        self.assertEqual(result, "location_state:=SP && location_city:=São Paulo && location_neighborhood:=Vila Madalena")


class TestParseHit(unittest.TestCase):
    def test_parse_minimal(self):
        """Testa parse de hit mínimo."""
        hit = {"document": {"id": "abc123"}}
        parsed = parse_hit(hit)
        self.assertEqual(parsed["id"], "emcasa_abc123")
        self.assertEqual(parsed["fonte"], "emcasa")
        self.assertIsNone(parsed["preco_venda"])

    def test_parse_full(self):
        """Testa parse de hit completo."""
        hit = {
            "document": {
                "id": "xyz789",
                "askingPrice": 450000,
                "condoFee": 800,
                "propertyTax": 1500,
                "bedrooms": 2,
                "bathrooms": 1,
                "parkingSpots": 1,
                "propertyType": "apartment",
                "totalArea": 76.0,
                "usableArea": 65.0,
                "city": "São Paulo",
                "state": "SP",
                "neighborhood": "Bela Vista",
                "street": "Av. Nove de Julho",
                "unitDescription": "Apto 2q Bela Vista",
                "buildingAmenities": ["piscina", "academia", "portaria24h"],
                "propertyFeatures": ["sacada", "armarioEmbutido"],
                "imageUrls": [
                    "https://cdn.fndn.ai/images/abc/def/detail",
                    "https://cdn.fndn.ai/images/abc/ghi/detail",
                ],
                "floor": "12",
                "buildingName": "Edificio Dos Estados",
                "coordinates": [-23.5505, -46.6445],
                "slug": "bela-vista/av-nove-de-julho/xyz789",
            }
        }
        parsed = parse_hit(hit)

        self.assertEqual(parsed["id"], "emcasa_xyz789")
        self.assertEqual(parsed["titulo"], "Apto 2q Bela Vista")
        self.assertEqual(parsed["preco_venda"], 450000.0)
        self.assertEqual(parsed["condominio"], 800.0)
        self.assertEqual(parsed["iptu"], 1500.0)
        self.assertEqual(parsed["quartos"], 2)
        self.assertEqual(parsed["banheiros"], 1)
        self.assertEqual(parsed["vagas"], 1)
        self.assertEqual(parsed["tipo"], "apartamento")
        self.assertEqual(parsed["area"], 76.0)
        self.assertEqual(parsed["cidade"], "São Paulo")
        self.assertEqual(parsed["uf"], "SP")
        self.assertEqual(parsed["bairro"], "Bela Vista")
        self.assertEqual(parsed["endereco"], "Av. Nove de Julho")
        self.assertEqual(len(parsed["fotos"]), 2)
        self.assertEqual(parsed["url"], "https://www.emcasa.com/imovel/bela-vista/av-nove-de-julho/xyz789")
        self.assertIn("piscina", parsed["amenities"])
        self.assertIn("sacada", parsed["amenities"])

    def test_parse_raw_doc(self):
        """Testa parse quando o hit é o documento direto (sem wrapper 'document')."""
        hit = {
            "id": "dir_doc_1",
            "askingPrice": 300000,
            "bedrooms": 1,
            "propertyType": "studio",
            "city": "Rio de Janeiro",
            "state": "RJ",
        }
        parsed = parse_hit(hit)
        self.assertEqual(parsed["id"], "emcasa_dir_doc_1")
        self.assertEqual(parsed["preco_venda"], 300000.0)
        self.assertEqual(parsed["tipo"], "studio")
        self.assertEqual(parsed["cidade"], "Rio de Janeiro")
        self.assertEqual(parsed["uf"], "RJ")

    def test_parse_null_values(self):
        """Testa que valores None são tratados corretamente."""
        hit = {"document": {"id": "null_test"}}
        parsed = parse_hit(hit)
        self.assertIsNone(parsed["preco_venda"])
        self.assertIsNone(parsed["condominio"])
        self.assertIsNone(parsed["iptu"])
        self.assertIsNone(parsed["area"])
        self.assertEqual(parsed["fotos"], [])
        self.assertEqual(parsed["amenities"], [])

    def test_parse_image_urls_normalized_to_large(self):
        """Verifica que URLs /detail são normalizadas para /large."""
        hit = {
            "document": {
                "id": "img_test_1",
                "imageUrls": [
                    "https://cdn.fndn.ai/images/abc/def/detail",
                    "https://cdn.fndn.ai/images/abc/ghi/detail",
                ],
            }
        }
        parsed = parse_hit(hit)
        fotos = parsed["fotos"]
        self.assertEqual(len(fotos), 2)
        for url in fotos:
            self.assertTrue(url.endswith("/large"),
                            f"URL deve terminar em /large, mas termina em ...{url[-20:]}")
        # Verify primaryImageUrl is prioritized when present
        hit2 = {
            "document": {
                "id": "img_test_2",
                "imageUrls": [
                    "https://cdn.fndn.ai/images/abc/second/detail",
                    "https://cdn.fndn.ai/images/abc/third/detail",
                ],
                "primaryImageUrl": "https://cdn.fndn.ai/images/abc/first/detail",
            }
        }
        parsed2 = parse_hit(hit2)
        fotos2 = parsed2["fotos"]
        self.assertEqual(len(fotos2), 3)
        self.assertIn("/large", fotos2[0])
        self.assertIn("first", fotos2[0], "primaryImageUrl deve ser a primeira foto")

    def test_parse_image_urls_deduplication(self):
        """Verifica que URLs duplicadas são removidas."""
        hit = {
            "document": {
                "id": "img_dedup",
                "imageUrls": [
                    "https://cdn.fndn.ai/images/abc/same/detail",
                    "https://cdn.fndn.ai/images/abc/same/detail",  # duplicata
                    "https://cdn.fndn.ai/images/abc/other/detail",
                ],
            }
        }
        parsed = parse_hit(hit)
        self.assertEqual(len(parsed["fotos"]), 2,
                         "Duplicatas devem ser removidas")

    def test_parse_image_urls_thumbnail_also_large(self):
        """Verifica que thumbnail também vira /large."""
        hit = {
            "document": {
                "id": "img_thumb",
                "imageUrls": [
                    "https://cdn.fndn.ai/images/abc/thumb/thumbnail",
                ],
            }
        }
        parsed = parse_hit(hit)
        self.assertEqual(len(parsed["fotos"]), 1)
        self.assertIn("/large", parsed["fotos"][0])

    def test_parse_image_urls_non_cdn_preserved(self):
        """Verifica que URLs de outros CDNs não são alteradas."""
        hit = {
            "document": {
                "id": "img_ext",
                "imageUrls": [
                    "https://images.example.com/photo.jpg",
                    "https://cdn.other.com/img/abc",
                ],
            }
        }
        parsed = parse_hit(hit)
        fotos = parsed["fotos"]
        self.assertEqual(len(fotos), 2)
        self.assertEqual(fotos[0], "https://images.example.com/photo.jpg")
        self.assertEqual(fotos[1], "https://cdn.other.com/img/abc")

    def test_parse_tipo_map(self):
        """Testa mapeamento de todos os tipos."""
        for en, br in TIPO_MAP.items():
            hit = {
                "document": {
                    "id": f"tipo_{en}",
                    "propertyType": en,
                }
            }
            parsed = parse_hit(hit)
            self.assertEqual(parsed["tipo"], br, f"Tipo {en} → {br}")


class TestPageCache(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.cache = PageCache(cache_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cache_miss(self):
        result = self.cache.get("SP_São Paulo", 1, 12)
        self.assertIsNone(result)

    def test_cache_roundtrip(self):
        hits = [{"id": "test1", "price": 100}]
        self.cache.put("SP_São Paulo", 1, 12, hits)
        result = self.cache.get("SP_São Paulo", 1, 12)
        self.assertEqual(result, hits)

    def test_cache_diff_page(self):
        hits_page1 = [{"id": "p1"}]
        hits_page2 = [{"id": "p2"}]
        self.cache.put("SP_São Paulo", 1, 12, hits_page1)
        self.cache.put("SP_São Paulo", 2, 12, hits_page2)
        self.assertEqual(self.cache.get("SP_São Paulo", 1, 12), hits_page1)
        self.assertEqual(self.cache.get("SP_São Paulo", 2, 12), hits_page2)

    def test_clear(self):
        self.cache.put("SP_São Paulo", 1, 12, [{"id": "test"}])
        self.cache.clear()
        self.assertIsNone(self.cache.get("SP_São Paulo", 1, 12))

    def test_cache_diff_filter(self):
        hits_sp = [{"id": "sp"}]
        hits_rj = [{"id": "rj"}]
        self.cache.put("SP_São Paulo", 1, 12, hits_sp)
        self.cache.put("RJ_Rio de Janeiro", 1, 12, hits_rj)
        self.assertEqual(self.cache.get("SP_São Paulo", 1, 12), hits_sp)
        self.assertEqual(self.cache.get("RJ_Rio de Janeiro", 1, 12), hits_rj)


class TestEmCasaClient(unittest.TestCase):
    @patch("skills.emcasa.emcasa_api.urlopen")
    def test_search_page_success(self, mock_urlopen):
        """Testa chamada bem-sucedida à API."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "found": 12800,
            "page": 1,
            "hits": [{"document": {"id": "test1", "askingPrice": 450000}}],
            "facet_counts": [],
            "out_of": 96784,
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = EmCasaClient(delay=0)
        result = client.search_page("location_state:=SP && location_city:=São Paulo")

        self.assertEqual(result.found, 12800)
        self.assertEqual(result.page, 1)
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.nb_pages, 1067)

    @patch("skills.emcasa.emcasa_api.urlopen")
    def test_search_page_with_cache(self, mock_urlopen):
        """Testa que resultados em cache não chamam a API."""
        cache = PageCache(cache_dir="/tmp/test_cache_emcasa")
        cache.put("SP_São Paulo", 1, 12, [{"id": "cached"}])

        client = EmCasaClient(delay=0, cache=cache)
        result = client.search_page("SP_São Paulo", page=1, per_page=12)

        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0]["id"], "cached")
        mock_urlopen.assert_not_called()

    @patch("skills.emcasa.emcasa_api.urlopen")
    def test_search_page_retry(self, mock_urlopen):
        """Testa retry em caso de erro HTTP (MAX_RETRIES=3)."""
        mock_urlopen.side_effect = [
            HTTPError("http://error", 502, "Bad Gateway", {}, None),
            HTTPError("http://error", 503, "Service Unavailable", {}, None),
            HTTPError("http://error", 504, "Gateway Timeout", {}, None),
        ]

        client = EmCasaClient(delay=0)
        with self.assertRaises(EmCasaAPIError):
            client.search_page("SP_São Paulo")

        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("skills.emcasa.emcasa_api.urlopen")
    def test_search_page_eventual_success(self, mock_urlopen):
        """Testa que retry eventualmente succeede."""
        mock_error = HTTPError("http://error", 502, "Bad Gateway", {}, None)

        mock_success = MagicMock()
        mock_success.read.return_value = json.dumps({
            "found": 100,
            "page": 1,
            "hits": [{"document": {"id": "retry_success"}}],
            "facet_counts": [],
        }).encode()
        mock_success.__enter__.return_value = mock_success

        # MAX_RETRIES=3, so we need 2 errors + 1 success
        mock_urlopen.side_effect = [mock_error, mock_error, mock_success]

        client = EmCasaClient(delay=0)
        result = client.search_page("SP_São Paulo")

        self.assertEqual(len(result.hits), 1)
        self.assertEqual(mock_urlopen.call_count, 3)


# ── Teste de integração (opcional, requer rede) ────────────────────────────────

@unittest.skipUnless(os.environ.get("EMCASA_INTEGRATION"), "Pule EMCASA_INTEGRATION=1 para testar API real")
class TestIntegration(unittest.TestCase):
    """Testes de integração com a API real. Roda apenas com EMCASA_INTEGRATION=1."""

    def test_real_search_city(self):
        """Busca real em São Paulo — verifica estrutura."""
        client = EmCasaClient(delay=1)
        result = client.search_page(
            "location_state:=SP && location_city:=São Paulo",
            page=1,
            per_page=12,
        )
        self.assertGreater(result.found, 0, "Deveria encontrar imóveis em SP")
        self.assertGreaterEqual(len(result.hits), 1, "Deveria ter ao menos 1 hit")
        self.assertGreater(result.nb_pages, 1, "Deveria ter múltiplas páginas")

        # Verifica estrutura do documento
        first = result.hits[0]
        doc = first.get("document", first)
        self.assertIn("id", doc, "Hit deve ter id")
        self.assertIn("askingPrice", doc, "Hit deve ter askingPrice")

        print(f"\nIntegração OK: {result.found} resultados, "
              f"primeiro: {doc.get('city')} - R$ {doc.get('askingPrice')}")

    def test_real_parse(self):
        """Busca real + parse — verifica schema normalizado."""
        client = EmCasaClient(delay=1)
        result = client.search_page(
            "location_state:=SP && location_city:=São Paulo",
            page=1,
            per_page=5,
        )
        self.assertGreater(len(result.hits), 0)

        parsed = [parse_hit(h) for h in result.hits]
        first = parsed[0]
        self.assertIn("emcasa_", first["id"], "ID deve ter prefixo emcasa_")
        self.assertEqual(first["fonte"], "emcasa")
        self.assertIsNotNone(first["preco_venda"])

        print(f"\nParse OK: {len(parsed)} hits normalizados, "
              f"exemplo: {first['titulo']} - R$ {first['preco_venda']}")

    def test_real_small_town(self):
        """Busca em cidade pequena (poucas páginas) — ideal para teste de paginação."""
        client = EmCasaClient(delay=1)
        result = client.search_page(
            "location_state:=SP && location_city:=Diadema",
            page=1,
            per_page=12,
        )
        print(f"\nDiadema: {result.found} resultados, "
              f"{result.nb_pages} páginas")
        self.assertGreaterEqual(result.found, 1)


if __name__ == "__main__":
    unittest.main()
