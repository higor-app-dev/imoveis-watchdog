#!/usr/bin/env python3
"""Testes para extract_page — extração de Algolia JSON do HTML do EmCasa."""

import json
import os
import sys
import unittest

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from skills.emcasa.extract_page import (
    extract_page,
    extract_page_results,
    _fetch_html,
    _extract_algolia_json,
    VALID_CITIES,
)


class TestExtractPage(unittest.TestCase):
    """Testes da função principal."""

    def test_sp_page_0_returns_dict(self):
        """extract_page('sp', 0) deve retornar um dict."""
        data = extract_page("sp", 0)
        self.assertIsInstance(data, dict)

    def test_sp_page_0_has_hits(self):
        """extract_page('sp', 0) deve conter 'properties.results[0].hits'."""
        data = extract_page("sp", 0)
        results = data.get("properties", {}).get("results", [{}])
        self.assertGreater(len(results), 0)
        hits = results[0].get("hits", [])
        self.assertEqual(len(hits), 12)  # 12 hits per page

    def test_sp_page_0_has_nbHits(self):
        """Dados devem ter nbHits > 0 (total de imóveis)."""
        data = extract_page("sp", 0)
        r = data["properties"]["results"][0]
        self.assertGreater(r["nbHits"], 0)

    def test_sp_page_0_hit_structure(self):
        """Cada hit deve ter campos essenciais do Algolia."""
        data = extract_page("sp", 0)
        hits = data["properties"]["results"][0]["hits"]
        h = hits[0]
        # Campos esperados
        self.assertIn("objectID", h)
        self.assertIn("title", h)
        self.assertIn("price", h)
        self.assertIn("location_city", h)
        self.assertIn("property_type", h)

    def test_rj_page_0(self):
        """extract_page('rj', 0) também deve funcionar."""
        data = extract_page("rj", 0)
        self.assertIsInstance(data, dict)
        r = data["properties"]["results"][0]
        self.assertGreater(len(r["hits"]), 0)
        self.assertGreater(r["nbHits"], 0)

    def test_invalid_city(self):
        """Cidade inválida deve retornar None."""
        result = extract_page("xyz", 0)
        self.assertIsNone(result)

    def test_empty_case(self):
        """Código vazio deve retornar None."""
        result = extract_page("", 0)
        self.assertIsNone(result)

    def test_case_insensitive(self):
        """Código com maiúsculas deve funcionar (SP, RJ)."""
        data = extract_page("SP", 0)
        self.assertIsInstance(data, dict)
        hits = data["properties"]["results"][0]["hits"]
        self.assertGreater(len(hits), 0)

    def test_facets_present(self):
        """Resposta deve conter facets."""
        data = extract_page("sp", 0)
        r = data["properties"]["results"][0]
        facets = r.get("facets", {})
        self.assertIn("location_city", facets)
        self.assertIn("property_type", facets)
        self.assertIn("location_neighborhood", facets)


class TestExtractPageResults(unittest.TestCase):
    """Testes do helper extract_page_results."""

    def test_returns_hits_list(self):
        """extract_page_results deve retornar lista de hits."""
        hits = extract_page_results("sp", 0)
        self.assertIsInstance(hits, list)
        self.assertEqual(len(hits), 12)

    def test_hits_have_city(self):
        """Hits devem ter location_city='São Paulo' para sp."""
        hits = extract_page_results("sp", 0)
        for h in hits:
            self.assertEqual(h["location_city"], "São Paulo")

    def test_rj_hits_have_city(self):
        """Hits do RJ devem ter location_city='Rio de Janeiro'."""
        hits = extract_page_results("rj", 0)
        for h in hits:
            self.assertEqual(h["location_city"], "Rio de Janeiro")


class TestInternalHelpers(unittest.TestCase):
    """Testes das funções internas _fetch_html e _extract_algolia_json.

    Usa HTML salvo localmente para não depender de rede.
    """

    @classmethod
    def setUpClass(cls):
        """Carrega HTML de teste (se disponível)."""
        test_html_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "emcasa_sp_page0.html"
        )
        if os.path.exists(test_html_path):
            with open(test_html_path, "r", encoding="utf-8") as f:
                cls.test_html = f.read()
        else:
            cls.test_html = None

    def test_extract_algolia_json_from_saved_html(self):
        """_extract_algolia_json deve funcionar com HTML real salvo."""
        if not self.test_html:
            self.skipTest("Arquivo HTML de teste não encontrado")
        json_str = _extract_algolia_json(self.test_html)
        self.assertIsNotNone(json_str)
        data = json.loads(json_str)
        self.assertIn("properties", data)
        r = data["properties"]["results"][0]
        self.assertIn("hits", r)

    def test_extract_algolia_json_no_marker(self):
        """HTML sem o marcador deve retornar None."""
        result = _extract_algolia_json("<html><body>no data</body></html>")
        self.assertIsNone(result)

    def test_extract_algolia_json_empty(self):
        """HTML vazio deve retornar None."""
        result = _extract_algolia_json("")
        self.assertIsNone(result)

    def test_extract_algolia_json_partial(self):
        """HTML com marcador mas sem JSON válido deve retornar None."""
        html = '<script>window[Symbol.for("InstantSearchInitialResults")] = BAD_JSON</script>'
        result = _extract_algolia_json(html)
        # Vai falhar porque não encontra { após o marcador, ou o json.loads falha
        self.assertIsNone(result)


class TestValidCities(unittest.TestCase):
    """Testes do mapa de cidades válidas."""

    def test_has_sp(self):
        self.assertIn("sp", VALID_CITIES)

    def test_has_rj(self):
        self.assertIn("rj", VALID_CITIES)

    def test_sp_maps_to_sao_paulo(self):
        self.assertEqual(VALID_CITIES["sp"], "São Paulo")

    def test_rj_maps_to_rio(self):
        self.assertEqual(VALID_CITIES["rj"], "Rio de Janeiro")


if __name__ == "__main__":
    unittest.main()
