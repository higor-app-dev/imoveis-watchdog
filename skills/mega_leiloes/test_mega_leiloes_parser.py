#!/usr/bin/env python3
"""Testes para o parser Mega Leilões (mega_leiloes_parser.py).

Testa as funções principais:
    - from_mega_listing()    — conversão de hit Algolia para Imovel
    - from_mega_payload()    — conversão de resposta da API
    - _query_algolia()       — requisição HTTP ao Algolia (mockada)
    - _build_image_url()     — construção de URL de imagem
    - _get_medium_res_image() — conversão thumbnail → média resolução
    - _parse_br_price()      — parsing de preço brasileiro
    - _parse_timestamp()     — conversão de timestamp Unix
    - _extract_md5_hash()    — extração de hash de URL
    - fetch_active_listings() — paginação completa (mockada)
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone
from pathlib import Path

# Adiciona schema ao path
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".hermes"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from skills.mega_leiloes.mega_leiloes_parser import (
    from_mega_listing,
    from_mega_payload,
    fetch_active_listings,
    _query_algolia,
    _build_image_url,
    _get_medium_res_image,
    _parse_br_price,
    _parse_timestamp,
    _extract_md5_hash,
    FIELD_MAP,
    SUBCATEGORY_TIPO_MAP,
    REAL_ESTATE_SUBCATEGORIES,
    ACTIVE_STATUS_VALUES,
    HITS_PER_PAGE,
    ALGOLIA_URL,
    ALGOLIA_HEADERS,
)

from imovel_schema import Imovel


# ═══════════════════════════════════════════════════════════════════════════════
# Dados de exemplo — Hits do Algolia
# ═══════════════════════════════════════════════════════════════════════════════

# SP — Apartamento em São Paulo (leilão aberto)
SP_APTO_HIT = {
    "objectID": "sp_apto_001",
    "headline": "Apartamento 2 dormitórios no Ipiranga",
    "batch": "Lote 001",
    "batch_id": 12345,
    "batch_status": 1,  # open
    "auction": "Leilão de Imóveis SP #42",
    "auction_id": 789,
    "auction_headline": "1º Leilão de Imóveis - Tribunal de Justiça SP",
    "category": "Imóveis",
    "subcategory": "Apartamentos",
    "address": "Rua do Manifesto, 1200",
    "sublocality": "Ipiranga",
    "city": "São Paulo",
    "state": "SP",
    "first_instance_value": "R$ 450.000,00",
    "second_instance_value": "R$ 337.500,00",
    "third_instance_value": None,
    "currency": "R$",
    "first_instance_date_start": 1750000000,
    "first_instance_date_end": 1750086400,
    "second_instance_date_end": 1750172800,
    "type": "Judicial",
    "process_number": "1001234-56.2026.8.26.0100",
    "forum": "Foro Central - SP",
    "author": "Banco do Brasil S/A",
    "respondent": "João da Silva",
    "constituent": None,
    "image_path": "https://cdn1.megaleiloes.com.br/batches/12345/abc123def45678901234567890123456_320x240.jpg",
    "url": "/imovel/sp/sao-paulo/ipiranga/lote-001",
    "rating": 4,
}

# RJ — Casa no Leblon (leilão upcoming)
RJ_CASA_HIT = {
    "objectID": "rj_casa_001",
    "headline": "Casa 3 suítes no Leblon com piscina",
    "batch": "Lote 042",
    "batch_id": 67890,
    "batch_status": 0,  # upcoming
    "auction": "Leilão de Imóveis RJ #15",
    "auction_id": 456,
    "auction_headline": "Leilão Extrajudicial - Caixa Econômica",
    "category": "Imóveis",
    "subcategory": "Casas",
    "address": "Rua Rainha Elizabeth, 500",
    "sublocality": "Leblon",
    "city": "Rio de Janeiro",
    "state": "RJ",
    "first_instance_value": "R$ 1.200.000,00",
    "second_instance_value": "R$ 900.000,00",
    "third_instance_value": None,
    "currency": "R$",
    "first_instance_date_start": 1755000000,
    "first_instance_date_end": 1755086400,
    "second_instance_date_end": 1755172800,
    "type": "Extrajudicial",
    "process_number": "2005678-90.2026.8.19.0001",
    "forum": "Foro Regional do Leblon",
    "author": "Caixa Econômica Federal",
    "respondent": "Maria Oliveira",
    "constituent": None,
    "image_path": "https://cdn1.megaleiloes.com.br/batches/67890/def45678901234567890123456789012_320x240.jpg",
    "url": "/imovel/rj/rio-de-janeiro/leblon/lote-042",
    "rating": 5,
}

# MG — Terreno em BH (suspenso)
MG_TERRENO_HIT = {
    "objectID": "mg_terreno_001",
    "headline": "Terreno 500m² no Buritis",
    "batch": "Lote 007",
    "batch_id": 33333,
    "batch_status": 3,  # suspended
    "auction": "Leilão BH #08",
    "auction_id": 222,
    "auction_headline": "Leilão de Terrenos - Prefeitura BH",
    "category": "Imóveis",
    "subcategory": "Terrenos e Lotes",
    "address": "Rua das Oliveiras, s/n",
    "sublocality": "Buritis",
    "city": "Belo Horizonte",
    "state": "MG",
    "first_instance_value": "R$ 280.000,00",
    "second_instance_value": "R$ 210.000,00",
    "third_instance_value": None,
    "currency": "R$",
    "first_instance_date_start": 1745000000,
    "first_instance_date_end": 1745086400,
    "second_instance_date_end": 1745172800,
    "type": "Judicial",
    "process_number": "3009012-34.2026.8.13.0001",
    "forum": "Foro de Belo Horizonte",
    "author": "Município de BH",
    "respondent": "Pedro Santos",
    "constituent": None,
    "image_path": None,
    "url": "/imovel/mg/belo-horizonte/buritis/lote-007",
    "rating": 3,
}

# Hit mínimo (apenas campos obrigatórios)
MIN_HIT = {
    "objectID": "min_001",
    "batch_id": 99999,
    "headline": "Imóvel mínimo",
    "subcategory": "Apartamentos",
    "city": "São Paulo",
    "state": "SP",
}

# Hit vazio
EMPTY_HIT = {}

# Hit sem subcategory
NO_SUBCAT_HIT = {
    "objectID": "no_sub_001",
    "batch_id": 11111,
    "batch_status": 1,
    "headline": "Lote sem subcategoria",
    "city": "Curitiba",
    "state": "PR",
}

# Hit com valor numérico sem formatação
NUMERIC_PRICE_HIT = {
    "objectID": "num_price_001",
    "batch_id": 22222,
    "batch_status": 1,
    "headline": "Imóvel com preço numérico",
    "subcategory": "Apartamentos",
    "city": "São Paulo",
    "state": "SP",
    "first_instance_value": "350000",
}

# Resposta completa da API simulada
API_RESPONSE = {
    "nbHits": 52200,
    "nbPages": 53,
    "hitsPerPage": 1000,
    "page": 0,
    "hits": [
        SP_APTO_HIT,
        RJ_CASA_HIT,
        MG_TERRENO_HIT,
    ],
    "params": "query=&hitsPerPage=1000&page=0&attributesToRetrieve=*",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Testes
# ═══════════════════════════════════════════════════════════════════════════════

class TestFromMegaListing(unittest.TestCase):
    """Testes da função from_mega_listing()."""

    def test_sp_apartamento_open(self):
        """SP — Apartamento no Ipiranga (batch_status=1)."""
        imovel = from_mega_listing(SP_APTO_HIT)
        self.assertEqual(imovel["id"], "megaleiloes_sp_apto_001")
        self.assertEqual(imovel["fonte"], "megaleiloes")
        self.assertEqual(imovel["titulo"], "Apartamento 2 dormitórios no Ipiranga")
        self.assertAlmostEqual(imovel["preco_venda"], 450000.00)
        self.assertEqual(imovel["endereco"], "Rua do Manifesto, 1200")
        self.assertEqual(imovel["bairro"], "Ipiranga")
        self.assertEqual(imovel["cidade"], "São Paulo")
        self.assertEqual(imovel["uf"], "SP")
        self.assertEqual(imovel["tipo"], "apartamento")
        self.assertEqual(imovel["status"], "ativo")
        self.assertEqual(imovel["disponivel"], True)
        self.assertEqual(imovel["batch_status"], 1)
        self.assertEqual(imovel["batch_id"], 12345)
        self.assertEqual(len(imovel["fotos"]), 1)
        self.assertIn("_670x380.jpg", imovel["fotos"][0])
        self.assertIn("megaleiloes.com.br", imovel["url"])

    def test_rj_casa_upcoming(self):
        """RJ — Casa no Leblon (batch_status=0)."""
        imovel = from_mega_listing(RJ_CASA_HIT)
        self.assertEqual(imovel["id"], "megaleiloes_rj_casa_001")
        self.assertEqual(imovel["fonte"], "megaleiloes")
        self.assertEqual(imovel["tipo"], "casa")
        self.assertAlmostEqual(imovel["preco_venda"], 1200000.00)
        self.assertAlmostEqual(imovel["second_instance_value"], 900000.00)
        self.assertEqual(imovel["status"], "upcoming")
        self.assertEqual(imovel["disponivel"], True)
        self.assertEqual(imovel["tipo_leilao"], "Extrajudicial")
        self.assertEqual(imovel["uf"], "RJ")

    def test_mg_terreno_suspended(self):
        """MG — Terreno suspenso (batch_status=3)."""
        imovel = from_mega_listing(MG_TERRENO_HIT)
        self.assertEqual(imovel["id"], "megaleiloes_mg_terreno_001")
        self.assertEqual(imovel["tipo"], "terreno")
        self.assertEqual(imovel["status"], "suspenso")
        self.assertEqual(imovel["disponivel"], False)
        self.assertEqual(imovel["fotos"], [])
        self.assertIsNone(imovel["image_path_original"])

    def test_min_hit(self):
        """Hit mínimo deve gerar ID e não crashar."""
        imovel = from_mega_listing(MIN_HIT)
        self.assertEqual(imovel["id"], "megaleiloes_min_001")
        self.assertEqual(imovel["fonte"], "megaleiloes")
        self.assertEqual(imovel["tipo"], "apartamento")
        self.assertEqual(imovel["preco_venda"], None)

    def test_empty_hit(self):
        """Hit vazio deve retornar None."""
        result = from_mega_listing(EMPTY_HIT)
        self.assertIsNone(result)

    def test_no_subcategory(self):
        """Hit sem subcategory → tipo 'outro'."""
        imovel = from_mega_listing(NO_SUBCAT_HIT)
        self.assertEqual(imovel["tipo"], "outro")
        self.assertEqual(imovel["cidade"], "Curitiba")
        self.assertEqual(imovel["uf"], "PR")

    def test_numeric_price(self):
        """Preço em formato numérico direto."""
        imovel = from_mega_listing(NUMERIC_PRICE_HIT)
        self.assertAlmostEqual(imovel["preco_venda"], 350000.0)

    def test_nao_dict(self):
        """Se não for dict, retorna None sem crash."""
        result = from_mega_listing("invalido")
        self.assertIsNone(result)

    def test_none_hit(self):
        """None → None."""
        result = from_mega_listing(None)
        self.assertIsNone(result)

    def test_image_url_construction(self):
        """Imagem deve ser convertida para alta resolução."""
        imovel = from_mega_listing(SP_APTO_HIT)
        fotos = imovel["fotos"]
        self.assertEqual(len(fotos), 1)
        self.assertIn("_670x380.jpg", fotos[0])
        self.assertNotIn("_320x240.jpg", fotos[0])

    def test_url_normalization(self):
        """URL relativa deve ser convertida para absoluta."""
        imovel = from_mega_listing(SP_APTO_HIT)
        self.assertTrue(imovel["url"].startswith("http"))
        self.assertIn("megaleiloes.com.br", imovel["url"])

    def test_auction_metadata_preserved(self):
        """Metadados do leilão preservados."""
        imovel = from_mega_listing(SP_APTO_HIT)
        self.assertEqual(imovel["process_number"], "1001234-56.2026.8.26.0100")
        self.assertEqual(imovel["forum"], "Foro Central - SP")
        self.assertEqual(imovel["author"], "Banco do Brasil S/A")
        self.assertEqual(imovel["respondent"], "João da Silva")
        self.assertEqual(imovel["rating"], 4)

    def test_timestamps_parsed(self):
        """Timestamps Unix convertidos para ISO."""
        imovel = from_mega_listing(SP_APTO_HIT)
        self.assertIsNotNone(imovel["data_leilao_inicio"])
        self.assertIsNotNone(imovel["data_leilao_fim"])
        self.assertIsNotNone(imovel["data_segunda_praca"])
        self.assertIn("T", imovel["data_leilao_inicio"])
        self.assertIn("T", imovel["data_leilao_fim"])
        self.assertIn("T", imovel["data_segunda_praca"])

    def test_imovel_schema_compatible(self):
        """Resultado deve ser compatível com Imovel.from_dict()."""
        imovel_dict = from_mega_listing(SP_APTO_HIT)
        # Deve ser possível criar um Imovel a partir do dict
        imovel = Imovel.from_dict(imovel_dict)
        self.assertIsInstance(imovel, Imovel)
        self.assertEqual(imovel.id, "megaleiloes_sp_apto_001")
        self.assertEqual(imovel.fonte, "megaleiloes")

    def test_uf_uppercase(self):
        """UF deve estar em maiúsculas."""
        hit = dict(RJ_CASA_HIT)
        hit["state"] = "rj"
        imovel = from_mega_listing(hit)
        self.assertEqual(imovel["uf"], "RJ")


class TestFromMegaPayload(unittest.TestCase):
    """Testes da função from_mega_payload()."""

    def test_api_response_dict(self):
        """Resposta da API com campo 'hits'."""
        imoveis = from_mega_payload(API_RESPONSE)
        self.assertEqual(len(imoveis), 3)
        self.assertEqual(imoveis[0]["id"], "megaleiloes_sp_apto_001")
        self.assertEqual(imoveis[1]["id"], "megaleiloes_rj_casa_001")
        self.assertEqual(imoveis[2]["id"], "megaleiloes_mg_terreno_001")

    def test_list_direct(self):
        """Lista direta de hits."""
        imoveis = from_mega_payload([SP_APTO_HIT, RJ_CASA_HIT])
        self.assertEqual(len(imoveis), 2)

    def test_single_hit_dict(self):
        """Dict de hit único (com objectID)."""
        imoveis = from_mega_payload(SP_APTO_HIT)
        self.assertEqual(len(imoveis), 1)
        self.assertEqual(imoveis[0]["id"], "megaleiloes_sp_apto_001")

    def test_json_string(self):
        """String JSON."""
        imoveis = from_mega_payload(json.dumps(API_RESPONSE))
        self.assertEqual(len(imoveis), 3)

    def test_empty_list(self):
        """Lista vazia → lista vazia."""
        self.assertEqual(from_mega_payload([]), [])

    def test_invalid_type(self):
        """Tipo inválido → []."""
        self.assertEqual(from_mega_payload("não é json"), [])

    def test_none(self):
        """None → []."""
        self.assertEqual(from_mega_payload(None), [])

    def test_int(self):
        """Int → []."""
        self.assertEqual(from_mega_payload(42), [])


class TestParseBrPrice(unittest.TestCase):
    """Testes de parsing de preço brasileiro."""

    def test_full_format(self):
        """R$ 450.000,00 → 450000.0"""
        self.assertAlmostEqual(_parse_br_price("R$ 450.000,00"), 450000.00)

    def test_millions(self):
        """R$ 1.200.000,00 → 1200000.0"""
        self.assertAlmostEqual(_parse_br_price("R$ 1.200.000,00"), 1200000.00)

    def test_no_thousands_sep(self):
        """R$ 5000,00 → 5000.0"""
        self.assertAlmostEqual(_parse_br_price("R$ 5000,00"), 5000.00)

    def test_numeric_only(self):
        """350000 → 350000.0"""
        self.assertAlmostEqual(_parse_br_price("350000"), 350000.00)

    def test_none(self):
        """None → None"""
        self.assertIsNone(_parse_br_price(None))

    def test_empty_string(self):
        """"" → None"""
        self.assertIsNone(_parse_br_price(""))

    def test_zero(self):
        """'0' → None"""
        self.assertIsNone(_parse_br_price("0"))

    def test_zero_br(self):
        """'0,00' → None"""
        self.assertIsNone(_parse_br_price("0,00"))


class TestBuildImageUrl(unittest.TestCase):
    """Testes de construção de URL de imagem."""

    def test_high_res_default(self):
        """URL de alta resolução com tamanho padrão (670)."""
        url = _build_image_url(12345, "abc123def45678901234567890123456")
        self.assertEqual(
            url,
            "https://cdn1.megaleiloes.com.br/batches/12345/abc123def45678901234567890123456_670x380.jpg"
        )

    def test_thumbnail_size(self):
        """URL de thumbnail (size=320)."""
        url = _build_image_url(12345, "abc123def45678901234567890123456", size=320)
        self.assertEqual(
            url,
            "https://cdn1.megaleiloes.com.br/batches/12345/abc123def45678901234567890123456_320x240.jpg"
        )

    def test_string_batch_id(self):
        """batch_id como string também funciona."""
        url = _build_image_url("12345", "hash123")
        self.assertIn("/batches/12345/", url)
        self.assertIn("hash123", url)

    def test_full_size(self):
        """URL full resolution (1024×768) com size=1024."""
        url = _build_image_url(12345, "abc123def45678901234567890123456", size=1024)
        self.assertEqual(
            url,
            "https://cdn1.megaleiloes.com.br/batches/12345/abc123def45678901234567890123456_1024x768.jpg"
        )


class TestGetMediumResImage(unittest.TestCase):
    """Testes de conversão thumbnail → média resolução (670×380)."""

    def test_replace_size(self):
        """_320x240 → _670x380."""
        thumb = "https://cdn1.megaleiloes.com.br/batches/12345/abc123_320x240.jpg"
        high = _get_medium_res_image(thumb)
        self.assertEqual(
            high,
            "https://cdn1.megaleiloes.com.br/batches/12345/abc123_670x380.jpg"
        )

    def test_none(self):
        """None → None."""
        self.assertIsNone(_get_medium_res_image(None))

    def test_empty(self):
        """"" → None."""
        self.assertIsNone(_get_medium_res_image(""))

    def test_already_medium_res(self):
        """URL já em resolução média."""
        url = "https://cdn1.megaleiloes.com.br/batches/12345/abc123_670x380.jpg"
        result = _get_medium_res_image(url)
        # Deve retornar a mesma URL (já é média res)
        self.assertEqual(result, url)


class TestExtractMd5Hash(unittest.TestCase):
    """Testes de extração de md5 hash de URL de imagem."""

    def test_valid_url(self):
        """Extrai hash de URL de thumbnail."""
        url = "https://cdn1.megaleiloes.com.br/batches/12345/abc123def45678901234567890123456_320x240.jpg"
        md5 = _extract_md5_hash(url)
        self.assertEqual(md5, "abc123def45678901234567890123456")

    def test_high_res_url(self):
        """Extrai hash de URL de alta resolução."""
        url = "https://cdn1.megaleiloes.com.br/batches/12345/abc123def45678901234567890123456_670x380.jpg"
        md5 = _extract_md5_hash(url)
        self.assertEqual(md5, "abc123def45678901234567890123456")

    def test_invalid_url(self):
        """URL sem hash → None."""
        self.assertIsNone(_extract_md5_hash("https://example.com/image.jpg"))

    def test_none(self):
        """None → None."""
        self.assertIsNone(_extract_md5_hash(None))

    def test_empty(self):
        """"" → None."""
        self.assertIsNone(_extract_md5_hash(""))


class TestFieldMap(unittest.TestCase):
    """Testes do FIELD_MAP."""

    def test_required_keys_mapped(self):
        """Campos essenciais mapeados."""
        self.assertIn("objectID", FIELD_MAP)
        self.assertIn("headline", FIELD_MAP)
        self.assertIn("batch_id", FIELD_MAP)
        self.assertIn("batch_status", FIELD_MAP)
        self.assertIn("address", FIELD_MAP)
        self.assertIn("city", FIELD_MAP)
        self.assertIn("state", FIELD_MAP)
        self.assertIn("first_instance_value", FIELD_MAP)
        self.assertIn("url", FIELD_MAP)
        self.assertIn("image_path", FIELD_MAP)

    def test_subcategory_tipo_map(self):
        """Mapeamento de subcategorias para tipos Imovel."""
        self.assertEqual(SUBCATEGORY_TIPO_MAP["Apartamentos"], "apartamento")
        self.assertEqual(SUBCATEGORY_TIPO_MAP["Casas"], "casa")
        self.assertEqual(SUBCATEGORY_TIPO_MAP["Terrenos e Lotes"], "terreno")
        self.assertEqual(SUBCATEGORY_TIPO_MAP["Imóveis Comerciais"], "comercial")

    def test_real_estate_subcategories(self):
        """Lista de subcategorias de imóveis definida."""
        self.assertIn("Apartamentos", REAL_ESTATE_SUBCATEGORIES)
        self.assertIn("Casas", REAL_ESTATE_SUBCATEGORIES)
        self.assertIn("Terrenos e Lotes", REAL_ESTATE_SUBCATEGORIES)
        self.assertGreaterEqual(len(REAL_ESTATE_SUBCATEGORIES), 8)


class TestActiveStatusValues(unittest.TestCase):
    """Testes dos valores de status ativos."""

    def test_upcoming_and_open(self):
        """Status ativos: upcoming (0) e open (1)."""
        self.assertIn(0, ACTIVE_STATUS_VALUES)
        self.assertIn(1, ACTIVE_STATUS_VALUES)
        self.assertNotIn(3, ACTIVE_STATUS_VALUES)


class TestParseTimestamp(unittest.TestCase):
    """Testes de conversão de timestamp Unix para ISO 8601."""

    def test_valid_timestamp(self):
        """1750000000 → ISO string."""
        iso = _parse_timestamp(1750000000)
        self.assertIsNotNone(iso)
        self.assertIn("T", iso)

    def test_none(self):
        """None → None."""
        self.assertIsNone(_parse_timestamp(None))

    def test_zero(self):
        """0 → data base."""
        iso = _parse_timestamp(0)
        self.assertIsNotNone(iso)
        self.assertIn("1970", iso)


class TestQueryAlgolia(unittest.TestCase):
    """Testes da função _query_algolia com mock."""

    @patch("skills.mega_leiloes.mega_leiloes_parser.requests.post")
    def test_query_defaults(self, mock_post):
        """Chamada com parâmetros padrão."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"hits": [], "nbHits": 0, "nbPages": 0}
        mock_post.return_value = mock_response

        result = _query_algolia()

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], ALGOLIA_URL)
        self.assertEqual(
            kwargs["headers"]["X-Algolia-API-Key"],
            ALGOLIA_HEADERS["X-Algolia-API-Key"],
        )
        self.assertEqual(
            kwargs["headers"]["X-Algolia-Application-Id"],
            ALGOLIA_HEADERS["X-Algolia-Application-Id"],
        )

        called_payload = kwargs["json"]
        self.assertIn("params", called_payload)
        self.assertIn("hitsPerPage=1000", called_payload["params"])
        self.assertIn("page=0", called_payload["params"])

    @patch("skills.mega_leiloes.mega_leiloes_parser.requests.post")
    def test_query_with_subcategories(self, mock_post):
        """Chamada sem filtros de subcategorias (agora feito client-side)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"hits": [], "nbHits": 0}
        mock_post.return_value = mock_response

        _query_algolia()

        args, kwargs = mock_post.call_args
        called_payload = kwargs["json"]
        params = called_payload["params"]
        # No facetFilters should be in the params
        self.assertNotIn("facetFilters", params)

    @patch("skills.mega_leiloes.mega_leiloes_parser.requests.post")
    def test_query_with_filters(self, mock_post):
        """Chamada sem filtros de status (agora feito client-side)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"hits": [], "nbHits": 0}
        mock_post.return_value = mock_response

        _query_algolia()

        args, kwargs = mock_post.call_args
        called_payload = kwargs["json"]
        # No filters should be in the params
        self.assertNotIn("filters=", called_payload["params"])

    @patch("skills.mega_leiloes.mega_leiloes_parser.requests.post")
    def test_query_custom_page(self, mock_post):
        """Chamada com página customizada."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"hits": [], "nbHits": 0}
        mock_post.return_value = mock_response

        _query_algolia(page=3, hits_per_page=50)

        args, kwargs = mock_post.call_args
        called_payload = kwargs["json"]
        self.assertIn("page=3", called_payload["params"])
        self.assertIn("hitsPerPage=50", called_payload["params"])

    @patch("skills.mega_leiloes.mega_leiloes_parser.requests.post")
    def test_query_http_error(self, mock_post):
        """Erro HTTP deve propagar."""
        from requests.exceptions import HTTPError

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("403 Forbidden")
        mock_post.return_value = mock_response

        with self.assertRaises(HTTPError):
            _query_algolia()


class TestFetchActiveListings(unittest.TestCase):
    """Testes de fetch_active_listings com mock."""

    @patch("skills.mega_leiloes.mega_leiloes_parser._query_algolia")
    def test_fetch_single_page(self, mock_query):
        """Uma página com todos os resultados."""
        # Build mock hits — only Imóveis + active status should pass filter
        hit1 = dict(SP_APTO_HIT)  # Imóveis, batch_status=1 -> passes
        hit2 = dict(RJ_CASA_HIT)  # Imóveis, batch_status=0 -> passes
        hit3 = dict(MG_TERRENO_HIT)  # Imóveis, batch_status=3 -> filtered out
        hit4 = dict(SP_APTO_HIT, objectID="veic_001", category="Veículos")  # filtered out

        mock_query.return_value = {
            "nbHits": 122095,
            "nbPages": 1,
            "page": 0,
            "hits": [hit1, hit2, hit3, hit4],
        }

        imoveis = fetch_active_listings(max_pages=5)

        # Only 2 pass the client-side filter (Imóveis + batch_status in {0,1})
        self.assertEqual(len(imoveis), 2)
        # Verifica que chamou sem filtros no servidor
        mock_query.assert_called_once_with(
            page=0,
            hits_per_page=1000,
            timeout=30,
        )

    @patch("skills.mega_leiloes.mega_leiloes_parser._query_algolia")
    def test_fetch_multiple_pages(self, mock_query):
        """Múltiplas páginas de resultados."""
        # Retorna 2 real estate hits na página 0, 1 na página 1
        def make_hit(oid, batch_status=0, category="Imóveis"):
            return {"objectID": oid, "batch_id": 1000, "batch_status": batch_status, "category": category, "subcategory": "Apartamentos", "city": "SP", "state": "SP"}

        page0_hits = [make_hit(f"hit_{i:04d}") for i in range(2)]
        page1_hits = [make_hit(f"hit_{i:04d}") for i in range(2, 3)]

        mock_query.side_effect = [
            {"nbHits": 1500, "nbPages": 2, "page": 0, "hits": page0_hits},
            {"nbHits": 1500, "nbPages": 2, "page": 1, "hits": page1_hits},
        ]

        imoveis = fetch_active_listings(max_pages=5)

        self.assertEqual(len(imoveis), 3)
        self.assertEqual(mock_query.call_count, 2)

    @patch("skills.mega_leiloes.mega_leiloes_parser._query_algolia")
    def test_fetch_deduplicates(self, mock_query):
        """Deduplicação por objectID + filtro client-side."""
        hit_a = dict(SP_APTO_HIT)
        hit_b = dict(SP_APTO_HIT)  # mesmo objectID
        hit_c = dict(SP_APTO_HIT, objectID="veic_001", category="Veículos")  # não-Imóveis

        mock_query.return_value = {
            "nbHits": 3,
            "nbPages": 1,
            "page": 0,
            "hits": [hit_a, hit_b, hit_c],
        }

        imoveis = fetch_active_listings(max_pages=5)
        # Deve deduplicar → apenas 1 (hit_c é Veículos, filtrado)
        self.assertEqual(len(imoveis), 1)

    @patch("skills.mega_leiloes.mega_leiloes_parser._query_algolia")
    def test_fetch_empty(self, mock_query):
        """Nenhum resultado."""
        mock_query.return_value = {
            "nbHits": 0,
            "nbPages": 0,
            "page": 0,
            "hits": [],
        }

        imoveis = fetch_active_listings(max_pages=5)
        self.assertEqual(imoveis, [])

    @patch("skills.mega_leiloes.mega_leiloes_parser._query_algolia")
    def test_fetch_first_page_fails(self, mock_query):
        """Erro na primeira página → RuntimeError."""
        from requests.exceptions import ConnectionError

        mock_query.side_effect = ConnectionError("Network error")

        with self.assertRaises(RuntimeError):
            fetch_active_listings(max_pages=5)


class TestAllSubcategoriesMapped(unittest.TestCase):
    """Todas as subcategorias de imóveis devem ter tipo mapeado."""

    def test_all_subcategories_have_tipo(self):
        """Cada subcategoria definida em REAL_ESTATE_SUBCATEGORIES deve ter
        mapeamento em SUBCATEGORY_TIPO_MAP."""
        for sub in REAL_ESTATE_SUBCATEGORIES:
            self.assertIn(
                sub, SUBCATEGORY_TIPO_MAP,
                f"Subcategoria '{sub}' não tem mapeamento de tipo"
            )


class TestDescriptionConstruction(unittest.TestCase):
    """Testes de construção da descrição."""

    def test_sp_apto_description(self):
        """Descrição deve conter metadados do leilão."""
        imovel = from_mega_listing(SP_APTO_HIT)
        desc = imovel.get("descricao", "")
        self.assertIn("Judicial", desc)
        self.assertIn("1001234-56.2026.8.26.0100", desc)
        self.assertIn("Foro Central", desc)
        self.assertIn("R$ 450.000,00", desc)

    def test_min_hit_description(self):
        """Hit mínimo deve ter descrição vazia."""
        imovel = from_mega_listing(MIN_HIT)
        self.assertEqual(imovel["descricao"], "")


class TestAmenitiesTags(unittest.TestCase):
    """Testes de geração de amenities/tags."""

    def test_subcategory_as_tag(self):
        """Subcategoria deve virar tag."""
        imovel = from_mega_listing(SP_APTO_HIT)
        self.assertIn("apartamentos", imovel["amenities"])

    def test_tipo_leilao_as_tag(self):
        """Tipo de leilão deve virar tag."""
        imovel = from_mega_listing(SP_APTO_HIT)
        self.assertIn("judicial", imovel["amenities"])

    def test_extrajudicial_tag(self):
        """Caso extrajudicial."""
        imovel = from_mega_listing(RJ_CASA_HIT)
        self.assertIn("extrajudicial", imovel["amenities"])
        self.assertIn("casas", imovel["amenities"])


if __name__ == "__main__":
    unittest.main()
