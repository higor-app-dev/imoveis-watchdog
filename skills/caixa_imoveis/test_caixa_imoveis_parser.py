#!/usr/bin/env python3
"""Testes para o parser Caixa Imóveis (caixa_imoveis_parser.py).

Testa as funções principais:
    - from_caixa_listing()     — conversão de listagem individual para Imovel
    - from_caixa_payload()     — conversão de payload (lista/dict/string)
    - _normalize_photo_url()   — normalização de URL de foto
    - build_photo_url()        — construção de URL de foto a partir do número
    - build_photo_urls()       — construção de múltiplas URLs
    - _extract_property_number_digits() — extração de dígitos
    - _parse_br_price()        — parsing de preço brasileiro
    - _collect_photos()        — coleta de fotos de múltiplas fontes
    - fetch_via_apify()        — integração com Apify (mockada)
    - FIELD_MAP                — validação do mapeamento
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call
from pathlib import Path

# Add schema to path
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".hermes"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from skills.caixa_imoveis.caixa_imoveis_parser import (
    from_caixa_listing,
    from_caixa_payload,
    fetch_via_apify,
    _normalize_photo_url,
    build_photo_url,
    build_photo_urls,
    _collect_photos,
    _parse_br_price,
    _extract_property_number_digits,
    _derivar_tipo_venda,
    FIELD_MAP,
    FONTE,
    BASE_URL,
    PHOTO_URL_PREFIX,
    SEARCH_BASE,
)

try:
    from imovel_schema import Imovel
    HAS_IMOVEL_SCHEMA = True
except ImportError:
    HAS_IMOVEL_SCHEMA = False


# ═══════════════════════════════════════════════════════════════════════════════
# Dados de exemplo — Listagens da Caixa
# ═══════════════════════════════════════════════════════════════════════════════

# SP — Apartamento em São Paulo (dados completos estilo Apify/detail page)
SP_APTO = {
    "propertyNumber": "155550814458-7",
    "state": "SP",
    "city": "SAO PAULO",
    "district": "VILA PRUDENTE",
    "address": "RUA DAS LOBELIAS, N. 380 Apto. 44 BL B",
    "zipCode": "03155-000",
    "propertyType": "Apartamento",
    "rooms": 2,
    "garage": 1,
    "privateArea": 55.0,
    "totalArea": 65.0,
    "landArea": None,
    "evaluationValue": "R$ 350.000,00",
    "minimumSaleValue": "R$ 310.000,00",
    "discount": 11.43,
    "modality": "Venda Online",
    "firstAuctionDate": "2026-07-15 10:00:00",
    "secondAuctionDate": "2026-08-15 10:00:00",
    "paymentMethods": ["Financiamento Caixa", "FGTS"],
    "expenseRules": ["Comprador responsável por IPTU e condomínio"],
    "occupancy": "Desocupado",
    "acceptsFGTS": True,
    "description": "Apartamento 2 quartos, 1 vaga, sala, cozinha, banheiro social. "
                   "Próximo ao metrô Vila Prudente.",
    "edital": "EDITAL-2026-042",
    "url": "/sistema/detalhe-imovel.asp?hdnimovel=155550814458-7",
    "image": "/fotos/F1555508144587.jpg",
}

# RJ — Casa no Rio (dados parciais estilo CSV)
RJ_CASA_CSV = {
    "N° do imóvel": "272400124451-3",
    "UF": "RJ",
    "Cidade": "RIO DE JANEIRO",
    "Bairro": "COPACABANA",
    "Endereço": "AV ATLANTICA, N. 2000 Apto. 1001",
    "Preço": "R$ 1.200.000,00",
    "Valor de avaliação": "R$ 1.500.000,00",
    "Desconto": "20.00",
    "Descrição": "Cobertura 3 suítes com vista para o mar, 2 vagas.",
    "Modalidade de venda": "Venda Online",
    "Link de acesso": "/sistema/detalhe-imovel.asp?hdnimovel=272400124451-3",
}

# MG — Terreno em Belo Horizonte (dados mínimos)
MG_TERRENO = {
    "propertyNumber": "312700334567-1",
    "state": "MG",
    "city": "BELO HORIZONTE",
    "district": "BURITIS",
    "propertyType": "Terreno",
    "privateArea": None,
    "landArea": 500.0,
    "minimumSaleValue": "280000.00",
    "evaluationValue": "350000.00",
}

# Dict vazio / inválido
EMPTY_DICT = {}
NONE_INPUT = None
NOT_A_DICT = ["not", "a", "dict"]


# ═══════════════════════════════════════════════════════════════════════════════
# Testes
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildPhotoUrl(unittest.TestCase):
    """Testes para build_photo_url e build_photo_urls."""

    def test_build_photo_url_with_hyphen(self):
        """Número com hífen: 155550814458-7 -> F1555508144587.jpg"""
        url = build_photo_url("155550814458-7")
        expected = f"{PHOTO_URL_PREFIX}/F1555508144587.jpg"
        self.assertEqual(url, expected)

    def test_build_photo_url_without_hyphen(self):
        """Número sem hífen: 1555508144587 -> F1555508144587.jpg"""
        url = build_photo_url("1555508144587")
        expected = f"{PHOTO_URL_PREFIX}/F1555508144587.jpg"
        self.assertEqual(url, expected)

    def test_build_photo_url_numeric(self):
        """Número como int: 1555508144587 -> F1555508144587.jpg"""
        url = build_photo_url(1555508144587)
        expected = f"{PHOTO_URL_PREFIX}/F1555508144587.jpg"
        self.assertEqual(url, expected)

    def test_build_photo_url_none(self):
        """None retorna None."""
        url = build_photo_url(None)
        self.assertIsNone(url)

    def test_build_photo_url_empty(self):
        """String vazia retorna None."""
        url = build_photo_url("")
        self.assertIsNone(url)

    def test_build_photo_urls_multiple(self):
        """Múltiplos números retornam URLs deduplicadas."""
        urls = build_photo_urls("155550814458-7", "272400124451-3", "155550814458-7")
        self.assertEqual(len(urls), 2)
        self.assertIn(f"{PHOTO_URL_PREFIX}/F1555508144587.jpg", urls)
        self.assertIn(f"{PHOTO_URL_PREFIX}/F2724001244513.jpg", urls)

    def test_build_photo_urls_with_invalid(self):
        """Números inválidos são ignorados."""
        urls = build_photo_urls("155550814458-7", None, "")
        self.assertEqual(len(urls), 1)
        self.assertIn(f"{PHOTO_URL_PREFIX}/F1555508144587.jpg", urls)

    def test_build_photo_urls_empty(self):
        """Nenhum argumento -> lista vazia."""
        urls = build_photo_urls()
        self.assertEqual(urls, [])


class TestExtractPropertyNumberDigits(unittest.TestCase):
    """Testes para _extract_property_number_digits."""

    def test_with_hyphen(self):
        """155550814458-7 -> 1555508144587"""
        self.assertEqual(_extract_property_number_digits("155550814458-7"), "1555508144587")

    def test_digits_only(self):
        """1555508144587 -> 1555508144587"""
        self.assertEqual(_extract_property_number_digits("1555508144587"), "1555508144587")

    def test_numeric(self):
        """1555508144587 como int -> 1555508144587"""
        self.assertEqual(_extract_property_number_digits(1555508144587), "1555508144587")

    def test_none(self):
        """None -> None"""
        self.assertIsNone(_extract_property_number_digits(None))

    def test_empty_string(self):
        """'' -> None"""
        self.assertIsNone(_extract_property_number_digits(""))


class TestNormalizePhotoUrl(unittest.TestCase):
    """Testes para _normalize_photo_url."""

    def test_absolute_url_passthrough(self):
        """URL absoluta HTTP deve passar direto."""
        url = _normalize_photo_url("https://externo.com/foto.jpg")
        self.assertEqual(url, "https://externo.com/foto.jpg")

    def test_relative_with_slash(self):
        """URL relativa começando com / deve prefixar com BASE_URL."""
        url = _normalize_photo_url("/fotos/F123.jpg")
        self.assertEqual(url, f"{BASE_URL}/fotos/F123.jpg")

    def test_filename_only(self):
        """Apenas nome do arquivo deve prefixar com PHOTO_URL_PREFIX."""
        url = _normalize_photo_url("F123.jpg")
        self.assertEqual(url, f"{PHOTO_URL_PREFIX}/F123.jpg")

    def test_dict_with_url_key(self):
        """Dict com chave 'url' deve extrair e normalizar."""
        url = _normalize_photo_url({"url": "/fotos/F456.jpg"})
        self.assertEqual(url, f"{BASE_URL}/fotos/F456.jpg")

    def test_dict_with_src_key(self):
        """Dict com chave 'src' deve extrair."""
        url = _normalize_photo_url({"src": "F789.jpg"})
        self.assertEqual(url, f"{PHOTO_URL_PREFIX}/F789.jpg")

    def test_dict_without_url(self):
        """Dict sem url/src deve cair no fallback property_number."""
        url = _normalize_photo_url({"alt": "foto"}, property_number="155550814458-7")
        expected = f"{PHOTO_URL_PREFIX}/F1555508144587.jpg"
        self.assertEqual(url, expected)

    def test_none_with_property_number(self):
        """None com property_number deve construir URL."""
        url = _normalize_photo_url(None, property_number="155550814458-7")
        expected = f"{PHOTO_URL_PREFIX}/F1555508144587.jpg"
        self.assertEqual(url, expected)

    def test_none_without_property_number(self):
        """None sem property_number retorna None."""
        self.assertIsNone(_normalize_photo_url(None))

    def test_empty_string(self):
        """String vazia retorna None."""
        self.assertIsNone(_normalize_photo_url(""))


class TestCollectPhotos(unittest.TestCase):
    """Testes para _collect_photos."""

    def test_from_fotos_array(self):
        """Array fotos[] com URLs absolutas."""
        raw = {
            "fotos": [
                "https://venda-imoveis.caixa.gov.br/fotos/F123.jpg",
                "https://venda-imoveis.caixa.gov.br/fotos/F456.jpg",
            ]
        }
        fotos = _collect_photos(raw)
        self.assertEqual(len(fotos), 2)

    def test_from_imagens_fallback(self):
        """Array imagens[] como fallback."""
        raw = {
            "imagens": [
                "/fotos/F789.jpg",
                "/fotos/F012.jpg",
            ]
        }
        fotos = _collect_photos(raw)
        self.assertEqual(len(fotos), 2)
        self.assertTrue(all(f.startswith(BASE_URL) for f in fotos))

    def test_from_single_image_field(self):
        """Campo image único como cover."""
        raw = {
            "image": "/fotos/F123.jpg",
            "propertyNumber": "155550814458-7",
        }
        fotos = _collect_photos(raw)
        self.assertEqual(len(fotos), 1)
        self.assertEqual(fotos[0], f"{BASE_URL}/fotos/F123.jpg")

    def test_from_property_number_fallback(self):
        """Qunado não há fotos, constrói a partir do propertyNumber."""
        raw = {"propertyNumber": "155550814458-7"}
        fotos = _collect_photos(raw)
        self.assertEqual(len(fotos), 1)
        self.assertIn("F1555508144587.jpg", fotos[0])

    def test_deduplication(self):
        """URLs duplicadas devem ser removidas."""
        raw = {
            "image": "/fotos/F123.jpg",
            "fotos": ["/fotos/F123.jpg", "/fotos/F456.jpg"],
        }
        fotos = _collect_photos(raw)
        self.assertEqual(len(fotos), 2)
        # image should be first (cover)
        self.assertTrue(fotos[0].endswith("/fotos/F123.jpg"))

    def test_no_photos(self):
        """Dict sem nenhuma fonte de foto retorna lista vazia."""
        fotos = _collect_photos({"city": "SP"})
        self.assertEqual(fotos, [])


class TestParseBrPrice(unittest.TestCase):
    """Testes para _parse_br_price."""

    def test_br_format_full(self):
        """R$ 1.234.567,89 -> 1234567.89"""
        self.assertEqual(_parse_br_price("R$ 1.234.567,89"), 1234567.89)

    def test_br_format_thousands(self):
        """R$ 450.000,00 -> 450000.00"""
        self.assertEqual(_parse_br_price("R$ 450.000,00"), 450000.0)

    def test_br_format_no_currency(self):
        """450.000,00 -> 450000.0"""
        self.assertEqual(_parse_br_price("450.000,00"), 450000.0)

    def test_float_input(self):
        """450000.0 (float) -> 450000.0"""
        self.assertEqual(_parse_br_price(450000.0), 450000.0)

    def test_int_input(self):
        """450000 (int) -> 450000.0"""
        self.assertEqual(_parse_br_price(450000), 450000.0)

    def test_zero_returns_none(self):
        """'0' -> None"""
        self.assertIsNone(_parse_br_price("0"))

    def test_none_returns_none(self):
        """None -> None"""
        self.assertIsNone(_parse_br_price(None))

    def test_empty_returns_none(self):
        """'' -> None"""
        self.assertIsNone(_parse_br_price(""))


class TestFromCaixaListing(unittest.TestCase):
    """Testes para from_caixa_listing."""

    def test_sp_apto_full(self):
        """SP apartamento com dados completos deve mapear todos os campos."""
        result = from_caixa_listing(SP_APTO)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], f"{FONTE}_155550814458-7")
        self.assertEqual(result["fonte"], FONTE)
        self.assertEqual(result["cidade"], "SAO PAULO")
        self.assertEqual(result["uf"], "SP")
        self.assertEqual(result["bairro"], "VILA PRUDENTE")
        self.assertEqual(result["endereco"], "RUA DAS LOBELIAS, N. 380 Apto. 44 BL B")
        self.assertEqual(result["tipo"], "Apartamento")
        self.assertEqual(result["quartos"], 2)
        self.assertEqual(result["vagas"], 1)
        self.assertEqual(result["area"], 55.0)
        self.assertEqual(result["preco_venda"], 310000.0)
        self.assertEqual(result["caixa_valor_avaliacao"], 350000.0)
        self.assertEqual(result["caixa_desconto_percentual"], 11.43)
        self.assertEqual(result["caixa_modalidade"], "Venda Online")
        self.assertEqual(result["caixa_tipo_venda"], "venda_direta")
        self.assertIn("VILA PRUDENTE", result["titulo"])
        self.assertEqual(len(result.get("fotos", [])), 1)
        self.assertIn("F1555508144587.jpg", result["fotos"][0])

    def test_rj_casa_csv(self):
        """RJ casa no formato CSV deve mapear campos alternativos."""
        result = from_caixa_listing(RJ_CASA_CSV)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], f"{FONTE}_272400124451-3")
        self.assertEqual(result["cidade"], "RIO DE JANEIRO")
        self.assertEqual(result["uf"], "RJ")
        self.assertEqual(result["bairro"], "COPACABANA")
        self.assertEqual(result["endereco"], "AV ATLANTICA, N. 2000 Apto. 1001")
        self.assertEqual(result["preco_venda"], 1200000.0)
        self.assertEqual(result["caixa_valor_avaliacao"], 1500000.0)
        self.assertEqual(result["caixa_modalidade"], "Venda Online")

    def test_mg_terreno_minimal(self):
        """MG terreno com dados mínimos deve funcionar."""
        result = from_caixa_listing(MG_TERRENO)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], f"{FONTE}_312700334567-1")
        self.assertEqual(result["cidade"], "BELO HORIZONTE")
        self.assertEqual(result["uf"], "MG")
        self.assertEqual(result["bairro"], "BURITIS")
        self.assertEqual(result["tipo"], "Terreno")
        self.assertEqual(result["preco_venda"], 280000.0)

    def test_empty_dict(self):
        """Dict vazio deve retornar dict com defaults."""
        result = from_caixa_listing(EMPTY_DICT)
        self.assertIsNotNone(result)
        self.assertEqual(result["fonte"], FONTE)
        self.assertEqual(result["id"], "")
        self.assertEqual(result.get("preco_venda"), None)

    def test_none_input(self):
        """None deve retornar None."""
        self.assertIsNone(from_caixa_listing(NONE_INPUT))

    def test_not_a_dict(self):
        """Input que não é dict deve retornar None."""
        self.assertIsNone(from_caixa_listing(NOT_A_DICT))

    @unittest.skipUnless(HAS_IMOVEL_SCHEMA, "Imovel schema not available")
    def test_imovel_schema_available(self):
        """Se Imovel schema está disponível, resultado deve conter campos do schema."""
        result = from_caixa_listing(SP_APTO)
        self.assertIsNotNone(result)
        # Campos do Imovel schema que devem existir
        self.assertIn("id", result)
        self.assertIn("titulo", result)
        self.assertIn("fonte", result)
        self.assertIn("preco_venda", result)
        self.assertIn("area", result)
        self.assertIn("quartos", result)
        self.assertIn("cidade", result)
        self.assertIn("uf", result)
        self.assertIn("fotos", result)
        self.assertIn("descricao", result)

    def test_title_from_location(self):
        """Quando não há título explícito, deve construir a partir de localização."""
        result = from_caixa_listing({
            "propertyNumber": "123",
            "city": "SAO PAULO",
            "propertyType": "Apartamento",
        })
        self.assertIsNotNone(result)
        # Título deve conter o tipo e cidade
        self.assertIn("Apartamento", result["titulo"])
        self.assertIn("SAO PAULO", result["titulo"])

    def test_url_normalization(self):
        """URL relativa deve ser normalizada para URL absoluta."""
        result = from_caixa_listing(SP_APTO)
        self.assertIsNotNone(result)
        self.assertTrue(result["url"].startswith("https://"))
        self.assertIn("detalhe-imovel.asp", result["url"])

    def test_price_as_string(self):
        """Preço como string brasileira deve ser parseado."""
        result = from_caixa_listing({
            "propertyNumber": "999",
            "minimumSaleValue": "R$ 500.000,00",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["preco_venda"], 500000.0)

    def test_price_as_plain_number(self):
        """Preço como string numérica simples deve ser convertido."""
        result = from_caixa_listing({
            "propertyNumber": "888",
            "minimumSaleValue": "310000.00",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["preco_venda"], 310000.0)

    def test_no_photos_fallback(self):
        """Sem fotos, deve usar propertyNumber para construir (se disponível)."""
        result = from_caixa_listing({
            "propertyNumber": "155550814458-7",
            "city": "SAO PAULO",
        })
        self.assertIsNotNone(result)
        fotos = result.get("fotos", [])
        self.assertGreaterEqual(len(fotos), 1)
        self.assertIn("F1555508144587.jpg", fotos[0])


class TestFromCaixaPayload(unittest.TestCase):
    """Testes para from_caixa_payload."""

    def test_from_list_of_dicts(self):
        """Lista de dicts deve retornar lista de imóveis."""
        payload = [SP_APTO, RJ_CASA_CSV]
        result = from_caixa_payload(payload)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["cidade"], "SAO PAULO")
        self.assertEqual(result[1]["cidade"], "RIO DE JANEIRO")

    def test_from_dict_with_results_key(self):
        """Dict com chave 'results' deve extrair a lista."""
        payload = {"results": [SP_APTO, RJ_CASA_CSV]}
        result = from_caixa_payload(payload)
        self.assertEqual(len(result), 2)

    def test_from_dict_with_listings_key(self):
        """Dict com chave 'listings' deve extrair a lista."""
        payload = {"listings": [SP_APTO]}
        result = from_caixa_payload(payload)
        self.assertEqual(len(result), 1)

    def test_from_dict_with_hits_key(self):
        """Dict com chave 'hits' (Algolia-style) deve extrair a lista."""
        payload = {"hits": [SP_APTO]}
        result = from_caixa_payload(payload)
        self.assertEqual(len(result), 1)

    def test_from_json_string(self):
        """String JSON deve ser parseada."""
        payload = json.dumps([SP_APTO])
        result = from_caixa_payload(payload)
        self.assertEqual(len(result), 1)

    def test_invalid_json_string(self):
        """String JSON inválida retorna lista vazia."""
        result = from_caixa_payload("not json at all {{{")
        self.assertEqual(result, [])

    def test_empty_list(self):
        """Lista vazia retorna lista vazia."""
        result = from_caixa_payload([])
        self.assertEqual(result, [])

    def test_none(self):
        """None retorna lista vazia."""
        result = from_caixa_payload(None)
        self.assertEqual(result, [])

    def test_int(self):
        """Inteiro retorna lista vazia."""
        result = from_caixa_payload(42)
        self.assertEqual(result, [])

    def test_invalid_items_skipped(self):
        """Items inválidos na lista são ignorados."""
        payload = [SP_APTO, None, "string", 42, RJ_CASA_CSV]
        result = from_caixa_payload(payload)
        self.assertEqual(len(result), 2)


class TestFieldMap(unittest.TestCase):
    """Testes para FIELD_MAP."""

    def test_field_map_maps_to_imovel_fields(self):
        """FIELD_MAP deve mapear para campos reconhecidos do Imovel schema."""
        imovel_fields = {
            "id", "titulo", "url", "fonte", "endereco", "bairro", "cidade", "uf",
            "cep", "preco_venda", "preco_aluguel", "condominio", "iptu",
            "area", "quartos", "banheiros", "vagas", "tipo", "descricao",
            "fotos", "data_coleta", "data_publicacao",
        }

        caixa_specific_fields = {
            "origem_id",
            "caixa_area_total", "caixa_area_terreno",
            "caixa_valor_avaliacao", "caixa_desconto_percentual",
            "caixa_modalidade", "caixa_primeira_data_leilao",
            "caixa_segunda_data_leilao", "caixa_formas_pagamento",
            "caixa_regras_despesas", "caixa_ocupacao", "caixa_aceita_fgts",
            "caixa_matricula", "caixa_comarca", "caixa_cartorio",
            "caixa_registro_imovel", "caixa_edital", "caixa_leiloeiro",
            "caixa_numero_item", "foto_principal",
        }

        all_valid = imovel_fields | caixa_specific_fields

        for _, dst_key in FIELD_MAP.items():
            self.assertIn(
                dst_key, all_valid,
                f"Campo '{dst_key}' não está em imovel_fields nem caixa_specific_fields",
            )

    def test_field_map_has_essential_mappings(self):
        """FIELD_MAP deve conter os campos essenciais."""
        mapped_dst = set(FIELD_MAP.values())
        essential = {"origem_id", "uf", "cidade", "bairro", "endereco",
                      "preco_venda", "descricao", "url", "tipo"}
        for field in essential:
            self.assertIn(field, mapped_dst, f"Campo essencial '{field}' não mapeado")


class TestDerivarTipoVenda(unittest.TestCase):
    """Testes para _derivar_tipo_venda."""

    def test_venda_online(self):
        """Venda Online -> venda_direta"""
        self.assertEqual(_derivar_tipo_venda("Venda Online"), "venda_direta")

    def test_venda_direta_online(self):
        """Venda Direta Online -> venda_direta"""
        self.assertEqual(_derivar_tipo_venda("Venda Direta Online"), "venda_direta")

    def test_venda_direta_far(self):
        """Venda Direta FAR -> venda_direta"""
        self.assertEqual(_derivar_tipo_venda("Venda Direta FAR"), "venda_direta")

    def test_primeiro_leilao(self):
        """1º Leilão SFI -> leilao"""
        self.assertEqual(_derivar_tipo_venda("1º Leilão SFI"), "leilao")

    def test_segundo_leilao(self):
        """2º Leilão SFI -> leilao"""
        self.assertEqual(_derivar_tipo_venda("2º Leilão SFI"), "leilao")

    def test_concorrencia_publica(self):
        """Concorrência Pública -> leilao"""
        self.assertEqual(_derivar_tipo_venda("Concorrência Pública"), "leilao")

    def test_edital_unico(self):
        """Leilão SFI - Edital Único -> leilao"""
        self.assertEqual(_derivar_tipo_venda("Leilão SFI - Edital Único"), "leilao")

    def test_licitacao_aberta(self):
        """Licitação Aberta -> leilao"""
        self.assertEqual(_derivar_tipo_venda("Licitação Aberta"), "leilao")

    def test_codigo_33(self):
        """Código 33 (Venda Online) -> venda_direta"""
        self.assertEqual(_derivar_tipo_venda("33"), "venda_direta")

    def test_codigo_34(self):
        """Código 34 (Venda Direta Online) -> venda_direta"""
        self.assertEqual(_derivar_tipo_venda("34"), "venda_direta")

    def test_codigo_9(self):
        """Código 9 (Venda Direta FAR) -> venda_direta"""
        self.assertEqual(_derivar_tipo_venda("9"), "venda_direta")

    def test_codigo_4(self):
        """Código 4 (1º Leilão SFI) -> leilao"""
        self.assertEqual(_derivar_tipo_venda("4"), "leilao")

    def test_codigo_5(self):
        """Código 5 (2º Leilão SFI) -> leilao"""
        self.assertEqual(_derivar_tipo_venda("5"), "leilao")

    def test_codigo_14(self):
        """Código 14 -> leilao"""
        self.assertEqual(_derivar_tipo_venda("14"), "leilao")

    def test_codigo_21(self):
        """Código 21 -> leilao"""
        self.assertEqual(_derivar_tipo_venda("21"), "leilao")

    def test_none(self):
        """None -> None"""
        self.assertIsNone(_derivar_tipo_venda(None))

    def test_empty(self):
        """String vazia -> None"""
        self.assertIsNone(_derivar_tipo_venda(""))

    def test_unknown(self):
        """Modalidade desconhecida -> None"""
        self.assertIsNone(_derivar_tipo_venda("Modalidade Invalida"))


class TestFetchViaApify(unittest.TestCase):
    """Testes para fetch_via_apify (com mock)."""

    def _patch_apify_client(self):
        """Set up mocks for apify_client module and ApifyClient class.

        Returns the mock ApifyClient class and the mock module, so the
        caller can configure return values.
        """
        mock_client_class = MagicMock(name='ApifyClient')
        mock_module = MagicMock(name='apify_client')
        mock_module.ApifyClient = mock_client_class

        patcher = patch.dict('sys.modules', {'apify_client': mock_module})
        patcher.start()
        self.addCleanup(patcher.stop)

        return mock_client_class

    def test_fetch_via_apify_success(self):
        """Apify fetch bem-sucedido deve retornar lista de imóveis parseados."""
        mock_client_class = self._patch_apify_client()
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        mock_actor = MagicMock()
        mock_instance.actor.return_value = mock_actor

        mock_run = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds_123",
        }
        mock_actor.call.return_value = mock_run

        mock_dataset = MagicMock()
        mock_instance.dataset.return_value = mock_dataset

        mock_dataset.list_items.return_value.items = [SP_APTO, RJ_CASA_CSV]

        # Execute
        result = fetch_via_apify(
            apify_token="test_token_123",
            actor_id="pizani/caixa-imoveis-leiloes-api",
            run_input={"estado": "SP"},
        )

        # Assert
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["cidade"], "SAO PAULO")
        self.assertEqual(result[1]["cidade"], "RIO DE JANEIRO")
        mock_actor.call.assert_called_once_with(
            run_input={"estado": "SP"}
        )

    def test_fetch_via_apify_default_input(self):
        """Apify fetch com input padrão deve usar estado SP."""
        mock_client_class = self._patch_apify_client()
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        mock_actor = MagicMock()
        mock_instance.actor.return_value = mock_actor
        mock_actor.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds_456",
        }

        mock_dataset = MagicMock()
        mock_instance.dataset.return_value = mock_dataset
        mock_dataset.list_items.return_value.items = []

        fetch_via_apify(apify_token="test_token")

        mock_actor.call.assert_called_once_with(
            run_input={"estado": "SP", "cidade": "SAO PAULO"}
        )

    def test_fetch_via_apify_failed_run(self):
        """Apify run com status FAILED deve lançar RuntimeError."""
        mock_client_class = self._patch_apify_client()
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        mock_actor = MagicMock()
        mock_instance.actor.return_value = mock_actor
        mock_actor.call.return_value = {
            "status": "FAILED",
            "statusMessage": "Rate limited",
        }

        with self.assertRaises(RuntimeError) as ctx:
            fetch_via_apify(apify_token="test")
        self.assertIn("Rate limited", str(ctx.exception))

    def test_fetch_via_apify_no_client(self):
        """Sem apify-client instalado, deve lançar ImportError."""
        # Ensure apify_client is NOT in sys.modules
        with patch.dict(sys.modules, {"apify_client": None}, clear=True):
            with self.assertRaises(ImportError) as ctx:
                fetch_via_apify(apify_token="test")
            self.assertIn("apify-client", str(ctx.exception))

    def test_fetch_via_apify_no_dataset_id(self):
        """Apify run sem dataset ID deve lançar RuntimeError."""
        mock_client_class = self._patch_apify_client()
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        mock_actor = MagicMock()
        mock_instance.actor.return_value = mock_actor
        mock_actor.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": None,
        }

        with self.assertRaises(RuntimeError) as ctx:
            fetch_via_apify(apify_token="test")
        self.assertIn("no dataset", str(ctx.exception).lower())


class TestDocumentationAndConstants(unittest.TestCase):
    """Testes para documentação e constantes."""

    def test_base_url_is_correct(self):
        """BASE_URL deve ser o domínio correto."""
        self.assertEqual(BASE_URL, "https://venda-imoveis.caixa.gov.br")

    def test_fonte_is_caixa(self):
        """FONTE deve ser 'caixa'."""
        self.assertEqual(FONTE, "caixa")

    def test_search_base_constructed_correctly(self):
        """SEARCH_BASE deve ser BASE_URL + /sistema."""
        self.assertEqual(SEARCH_BASE, f"{BASE_URL}/sistema")

    def test_module_has_docstring(self):
        """Módulo deve ter docstring detalhada."""
        import skills.caixa_imoveis.caixa_imoveis_parser as parser_mod
        doc = parser_mod.__doc__
        self.assertIsNotNone(doc)
        self.assertIn("Radware", doc)
        self.assertIn("hCaptcha", doc)
        self.assertIn("Apify", doc)
        self.assertIn("venda-imoveis.caixa.gov.br", doc)


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
