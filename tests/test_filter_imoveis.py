"""
Tests for filter_imoveis — filtering by type, negotiation, and neighborhood.
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from skills.filter_imoveis import filter_imoveis, _get_negociacao


# ── Sample fixtures ─────────────────────────────────────────────────────────

APTO_VENDA_MOEMA = {
    "titulo": "Apto na Moema",
    "tipo": "apartamento",
    "bairro": "Moema",
    "preco_venda": 650000.0,
    "preco_aluguel": None,
    "area": 80,
    "quartos": 2,
}

APTO_VENDA_VILA_MARIANA = {
    "titulo": "Apto na Vila Mariana",
    "tipo": "apartamento",
    "bairro": "Vila Mariana",
    "preco_venda": 450000.0,
    "preco_aluguel": None,
    "area": 60,
    "quartos": 2,
}

CASA_VENDA_MOEMA = {
    "titulo": "Casa na Moema",
    "tipo": "casa",
    "bairro": "Moema",
    "preco_venda": 1200000.0,
    "preco_aluguel": None,
    "area": 200,
    "quartos": 4,
}

APTO_ALUGUEL_MOEMA = {
    "titulo": "Apto aluguel Moema",
    "tipo": "apartamento",
    "bairro": "Moema",
    "preco_venda": None,
    "preco_aluguel": 3500.0,
    "area": 70,
    "quartos": 2,
}

APTO_ALUGUEL_PINHEIROS = {
    "titulo": "Apto aluguel Pinheiros",
    "tipo": "apartamento",
    "bairro": "Pinheiros",
    "preco_venda": None,
    "preco_aluguel": 4200.0,
    "area": 85,
    "quartos": 3,
}

COBERTURA_VENDA_MOEMA = {
    "titulo": "Cobertura na Moema",
    "tipo": "cobertura",
    "bairro": "Moema",
    "preco_venda": 2500000.0,
    "preco_aluguel": None,
    "area": 300,
    "quartos": 5,
}

STUDIO_VENDA_CONSOLACAO = {
    "titulo": "Studio Consolação",
    "tipo": "studio",
    "bairro": "Consolação",
    "preco_venda": 350000.0,
    "preco_aluguel": None,
    "area": 35,
    "quartos": 1,
}

# Edge case: item without price fields (neither venda nor aluguel)
ITEM_SEM_PRECO = {
    "titulo": "Sem preço",
    "tipo": "apartamento",
    "bairro": "Centro",
    "preco_venda": None,
    "preco_aluguel": None,
    "area": 50,
    "quartos": 1,
}

SAMPLE_LISTINGS = [
    APTO_VENDA_MOEMA,
    APTO_VENDA_VILA_MARIANA,
    CASA_VENDA_MOEMA,
    APTO_ALUGUEL_MOEMA,
    APTO_ALUGUEL_PINHEIROS,
    COBERTURA_VENDA_MOEMA,
    STUDIO_VENDA_CONSOLACAO,
    ITEM_SEM_PRECO,
]


# ── Tests ──────────────────────────────────────────────────────────────────


class TestGetNegociacao(unittest.TestCase):
    """Test the _get_negociacao helper."""

    def test_venda(self):
        self.assertEqual(_get_negociacao(APTO_VENDA_MOEMA), "venda")

    def test_aluguel(self):
        self.assertEqual(_get_negociacao(APTO_ALUGUEL_MOEMA), "aluguel")

    def test_sem_preco(self):
        self.assertIsNone(_get_negociacao(ITEM_SEM_PRECO))


class TestFilterImoveis(unittest.TestCase):
    """Test the main filter_imoveis function."""

    def test_no_filters_returns_all(self):
        """With no filter params, returns all valid items."""
        result = filter_imoveis(SAMPLE_LISTINGS)
        self.assertEqual(len(result), 8)

    def test_filter_tipo_apartamento(self):
        """Filter by tipo=apartamento returns only apartments."""
        result = filter_imoveis(SAMPLE_LISTINGS, tipo="apartamento")
        self.assertEqual(len(result), 5)
        for item in result:
            self.assertEqual(item["tipo"], "apartamento")

    def test_filter_tipo_casa(self):
        """Filter by tipo=casa returns only houses."""
        result = filter_imoveis(SAMPLE_LISTINGS, tipo="casa")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tipo"], "casa")

    def test_filter_tipo_case_insensitive(self):
        """tipo filter is case-insensitive."""
        result = filter_imoveis(SAMPLE_LISTINGS, tipo="APARTAMENTO")
        self.assertEqual(len(result), 5)

    def test_filter_negociacao_venda(self):
        """Filter by negociacao=venda returns only sale items."""
        result = filter_imoveis(SAMPLE_LISTINGS, negociacao="venda")
        self.assertEqual(len(result), 5)
        for item in result:
            self.assertIsNotNone(item["preco_venda"])

    def test_filter_negociacao_aluguel(self):
        """Filter by negociacao=aluguel returns only rental items."""
        result = filter_imoveis(SAMPLE_LISTINGS, negociacao="aluguel")
        self.assertEqual(len(result), 2)
        for item in result:
            self.assertIsNotNone(item["preco_aluguel"])

    def test_filter_negociacao_case_insensitive(self):
        """negociacao filter is case-insensitive."""
        result = filter_imoveis(SAMPLE_LISTINGS, negociacao="VENDA")
        self.assertEqual(len(result), 5)

    def test_filter_bairro_moema(self):
        """Filter by bairro=Moema returns Moema items."""
        result = filter_imoveis(SAMPLE_LISTINGS, bairro="Moema")
        self.assertEqual(len(result), 4)
        for item in result:
            self.assertEqual(item["bairro"], "Moema")

    def test_filter_bairro_case_insensitive(self):
        """bairro filter is case-insensitive."""
        result = filter_imoveis(SAMPLE_LISTINGS, bairro="moema")
        self.assertEqual(len(result), 4)

    def test_filter_bairro_substring(self):
        """bairro filter matches substrings."""
        result = filter_imoveis(SAMPLE_LISTINGS, bairro="Vila")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["bairro"], "Vila Mariana")

    def test_combined_tipo_negociacao(self):
        """Apartments for sale only."""
        result = filter_imoveis(SAMPLE_LISTINGS, tipo="apartamento", negociacao="venda")
        self.assertEqual(len(result), 2)
        for item in result:
            self.assertEqual(item["tipo"], "apartamento")
            self.assertIsNotNone(item["preco_venda"])

    def test_combined_all_three(self):
        """Apartments for sale in Moema."""
        result = filter_imoveis(
            SAMPLE_LISTINGS,
            tipo="apartamento",
            negociacao="venda",
            bairro="Moema",
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["titulo"], "Apto na Moema")

    def test_no_matches_returns_empty(self):
        """When no items match, returns empty list."""
        result = filter_imoveis(SAMPLE_LISTINGS, tipo="casa", bairro="Pinheiros")
        self.assertEqual(result, [])

    def test_tipo_none_skips_filter(self):
        """tipo=None skips that filter."""
        result_no_tipo = filter_imoveis(SAMPLE_LISTINGS, tipo=None, negociacao="venda")
        result_with_tipo = filter_imoveis(SAMPLE_LISTINGS, negociacao="venda")
        self.assertEqual(result_no_tipo, result_with_tipo)

    def test_negociacao_none_skips_filter(self):
        """negociacao=None skips that filter."""
        result_no_neg = filter_imoveis(SAMPLE_LISTINGS, negociacao=None, bairro="Moema")
        result_with_neg = filter_imoveis(SAMPLE_LISTINGS, bairro="Moema")
        self.assertEqual(result_no_neg, result_with_neg)

    def test_bairro_none_skips_filter(self):
        """bairro=None skips that filter."""
        result_no_bairro = filter_imoveis(SAMPLE_LISTINGS, bairro=None, tipo="casa")
        result_with_bairro = filter_imoveis(SAMPLE_LISTINGS, tipo="casa")
        self.assertEqual(result_no_bairro, result_with_bairro)

    def test_empty_list_returns_empty(self):
        """Empty input returns empty list."""
        result = filter_imoveis([], tipo="apartamento")
        self.assertEqual(result, [])

    def test_non_dict_items_are_skipped(self):
        """Non-dict items in the list are silently skipped."""
        mixed = [APTO_VENDA_MOEMA, None, "string", 42, APTO_ALUGUEL_MOEMA]
        result = filter_imoveis(mixed)
        self.assertEqual(len(result), 2)

    def test_missing_tipo_field(self):
        """Items without 'tipo' field still work with None filter."""
        incomplete = [{"bairro": "Teste"}]
        result = filter_imoveis(incomplete, tipo="apartamento")
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
