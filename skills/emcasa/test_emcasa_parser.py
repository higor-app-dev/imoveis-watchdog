#!/usr/bin/env python3
"""Testes para o parser EmCasa (emcasa_parser.py)."""

import json
import os
import sys
import unittest

# Adiciona schema ao path
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".hermes"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from skills.emcasa.emcasa_parser import (
    from_emcasa_hit,
    from_emcasa_hits,
    from_emcasa_api_response,
    from_emcasa_safe,
    parse_hit,
    TIPO_MAP,
    _normalize_amenity,
    _map_tipo,
)

from imovel_schema import Imovel


# ═══════════════════════════════════════════════════════════════════════════════
# Dados de exemplo
# ═══════════════════════════════════════════════════════════════════════════════

# SP — Apartamento na Vila Mariana
SP_APTO = {
    "document": {
        "id": "sp_apto_001",
        "askingPrice": 850000.0,
        "previousPrice": 900000.0,
        "priceChangePercent": -5.56,
        "condoFee": 1200.0,
        "propertyTax": 2500.0,
        "bedrooms": 3,
        "bathrooms": 2,
        "parkingSpots": 2,
        "propertyType": "apartment",
        "totalArea": 86.0,
        "usableArea": 72.0,
        "city": "São Paulo",
        "state": "SP",
        "neighborhood": "Vila Mariana",
        "street": "Rua Vergueiro, 2000",
        "unitDescription": "Apto 3q Vila Mariana com vaga",
        "buildingAmenities": ["piscina", "academia", "portaria24h"],
        "propertyFeatures": ["sacada", "armário embutido"],
        "imageUrls": [
            "https://cdn.fndn.ai/images/sp/test1/detail",
            "https://cdn.fndn.ai/images/sp/test2/detail",
        ],
        "floor": "12",
        "buildingName": "Edifício Vila Rica",
        "slug": "vila-mariana/rua-vergueiro/sp_apto_001",
        "coordinates": [-23.5800, -46.6400],
        "createdAt": "2026-05-15T10:00:00Z",
    }
}

# SP — Cobertura nos Jardins
SP_COBERTURA = {
    "document": {
        "id": "sp_coh_002",
        "askingPrice": 2500000.0,
        "previousPrice": 2700000.0,
        "priceChangePercent": -7.41,
        "condoFee": 3500.0,
        "propertyTax": 8000.0,
        "bedrooms": 4,
        "bathrooms": 3,
        "parkingSpots": 3,
        "propertyType": "penthouse",
        "totalArea": 200.0,
        "city": "São Paulo",
        "state": "SP",
        "neighborhood": "Jardins",
        "unitDescription": "Cobertura duplex nos Jardins",
        "buildingAmenities": ["piscina", "academia", "salao_festas", "sauna"],
        "propertyFeatures": ["sacada_gourmet", "lareira"],
        "imageUrls": ["https://cdn.fndn.ai/images/sp/cobertura/detail"],
        "slug": "jardins/alameda-lorena/sp_coh_002",
    }
}

# SP — Studio na Consolação
SP_STUDIO = {
    "document": {
        "id": "sp_stu_003",
        "askingPrice": 320000.0,
        "condoFee": 450.0,
        "propertyTax": 600.0,
        "bedrooms": 1,
        "bathrooms": 1,
        "parkingSpots": 0,
        "propertyType": "studio",
        "totalArea": 35.0,
        "city": "São Paulo",
        "state": "SP",
        "neighborhood": "Consolação",
        "buildingAmenities": ["portaria24h", "elevador"],
    }
}

# RJ — Casa no Leblon (sem condomínio)
RJ_CASA = {
    "document": {
        "id": "rj_casa_001",
        "askingPrice": 1200000.0,
        "previousPrice": 1350000.0,
        "priceChangePercent": -11.11,
        "condoFee": 0,
        "propertyTax": 4800.0,
        "bedrooms": 4,
        "bathrooms": 3,
        "parkingSpots": 3,
        "propertyType": "house",
        "totalArea": 280.0,
        "city": "Rio de Janeiro",
        "state": "RJ",
        "neighborhood": "Leblon",
        "unitDescription": "Casa 4q no Leblon com piscina",
        "buildingAmenities": ["piscina", "jardim"],
        "propertyFeatures": ["churrasqueira", "edicula"],
        "imageUrls": [
            "https://cdn.fndn.ai/images/rj/casa1/detail",
            "https://cdn.fndn.ai/images/rj/casa2/detail",
            "https://cdn.fndn.ai/images/rj/casa3/detail",
        ],
        "slug": "leblon/rua-rainha-elizabeth/rj_casa_001",
    }
}

# RJ — Apartamento em Copacabana
RJ_APTO = {
    "document": {
        "id": "rj_apto_002",
        "askingPrice": 750000.0,
        "condoFee": 1500.0,
        "propertyTax": 3200.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parkingSpots": 1,
        "propertyType": "apartment",
        "totalArea": 65.0,
        "city": "Rio de Janeiro",
        "state": "RJ",
        "neighborhood": "Copacabana",
        "unitDescription": "Apto 2q Copacabana",
        "buildingAmenities": ["piscina", "portaria24h", "salao_festas"],
        "imageUrls": ["https://cdn.fndn.ai/images/rj/apto/detail"],
        "slug": "copacabana/av-atlantica/rj_apto_002",
    }
}

# Hit direto (sem wrapper "document")
RAW_HIT = {
    "id": "raw_hit_001",
    "askingPrice": 550000.0,
    "bedrooms": 2,
    "propertyType": "apartment",
    "city": "São Paulo",
    "state": "SP",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Testes
# ═══════════════════════════════════════════════════════════════════════════════

class TestFromEmCasaHit(unittest.TestCase):
    """Testes da função principal from_emcasa_hit()."""

    def test_sp_apartamento(self):
        """SP — Apartamento na Vila Mariana: campos core."""
        imovel = from_emcasa_hit(SP_APTO)
        self.assertEqual(imovel.id, "emcasa_sp_apto_001")
        self.assertEqual(imovel.fonte, "emcasa")
        self.assertEqual(imovel.titulo, "Apto 3q Vila Mariana com vaga")
        self.assertEqual(imovel.preco_venda, 850000.0)
        self.assertEqual(imovel.condominio, 1200.0)
        self.assertEqual(imovel.iptu, 2500.0)
        self.assertEqual(imovel.area, 86.0)
        self.assertEqual(imovel.quartos, 3)
        self.assertEqual(imovel.banheiros, 2)
        self.assertEqual(imovel.vagas, 2)
        self.assertEqual(imovel.tipo, "apartamento")
        self.assertEqual(imovel.cidade, "São Paulo")
        self.assertEqual(imovel.uf, "SP")
        self.assertEqual(imovel.bairro, "Vila Mariana")
        self.assertEqual(imovel.endereco, "Rua Vergueiro, 2000")
        self.assertIn("piscina", imovel.amenities)
        self.assertIn("academia", imovel.amenities)
        self.assertEqual(len(imovel.fotos), 2)
        self.assertIn("emcasa.com", imovel.url)
        self.assertTrue(imovel.is_valid())

    def test_sp_cobertura(self):
        """SP — Cobertura nos Jardins: tipo mapeado."""
        imovel = from_emcasa_hit(SP_COBERTURA)
        self.assertEqual(imovel.tipo, "cobertura")
        self.assertEqual(imovel.preco_venda, 2500000.0)
        self.assertEqual(imovel.condominio, 3500.0)
        self.assertEqual(imovel.area, 200.0)
        self.assertEqual(imovel.quartos, 4)
        self.assertTrue(imovel.is_valid())

    def test_sp_studio(self):
        """SP — Studio na Consolação: tipo studio, vaga 0."""
        imovel = from_emcasa_hit(SP_STUDIO)
        self.assertEqual(imovel.tipo, "studio")
        self.assertEqual(imovel.preco_venda, 320000.0)
        self.assertEqual(imovel.vagas, 0)  # 0 é válido (não tem vaga)
        self.assertEqual(imovel.banheiros, 1)
        self.assertIsNotNone(imovel.preco_venda)

    def test_rj_casa(self):
        """RJ — Casa no Leblon: sem condomínio (0 → None)."""
        imovel = from_emcasa_hit(RJ_CASA)
        self.assertEqual(imovel.tipo, "casa")
        self.assertEqual(imovel.preco_venda, 1200000.0)
        self.assertIsNone(imovel.condominio)  # 0 → None
        self.assertEqual(imovel.iptu, 4800.0)
        self.assertEqual(imovel.area, 280.0)
        self.assertEqual(imovel.quartos, 4)
        self.assertEqual(imovel.cidade, "Rio de Janeiro")
        self.assertEqual(imovel.uf, "RJ")
        self.assertEqual(imovel.bairro, "Leblon")
        self.assertEqual(len(imovel.fotos), 3)
        self.assertTrue(imovel.is_valid())

    def test_rj_apartamento(self):
        """RJ — Apartamento em Copacabana: validade completa."""
        imovel = from_emcasa_hit(RJ_APTO)
        self.assertEqual(imovel.tipo, "apartamento")
        self.assertEqual(imovel.preco_venda, 750000.0)
        self.assertEqual(imovel.condominio, 1500.0)
        self.assertEqual(imovel.bairro, "Copacabana")
        self.assertEqual(imovel.cidade, "Rio de Janeiro")
        self.assertEqual(imovel.uf, "RJ")
        self.assertTrue(imovel.is_valid())

    def test_raw_hit_sem_wrapper(self):
        """Hit direto (sem wrapper 'document') deve ser aceito."""
        imovel = from_emcasa_hit(RAW_HIT)
        self.assertEqual(imovel.id, "emcasa_raw_hit_001")
        self.assertEqual(imovel.preco_venda, 550000.0)
        self.assertEqual(imovel.tipo, "apartamento")
        self.assertEqual(imovel.cidade, "São Paulo")

    def test_hit_minimo(self):
        """Hit mínimo: deve gerar ID e não crashar."""
        imovel = from_emcasa_hit({"document": {"id": "min"}})
        self.assertEqual(imovel.id, "emcasa_min")
        self.assertIsNone(imovel.preco_venda)
        self.assertEqual(imovel.amenities, [])
        self.assertEqual(imovel.fotos, [])

    def test_hit_vazio(self):
        """Hit vazio: deve retornar Imovel vazio."""
        imovel = from_emcasa_hit({})
        self.assertEqual(imovel.id, "")
        self.assertFalse(imovel.is_valid())  # sem id

    def test_nao_dict(self):
        """Se não for dict, retorna Imovel vazio sem crash."""
        imovel = from_emcasa_hit("invalido")
        self.assertIsInstance(imovel, Imovel)
        self.assertEqual(imovel.id, "")

    def test_none_values(self):
        """Campos ausentes → None (não crasha)."""
        hit = {"document": {"id": "nulo"}}
        imovel = from_emcasa_hit(hit)
        self.assertIsNone(imovel.preco_venda)
        self.assertIsNone(imovel.condominio)
        self.assertIsNone(imovel.iptu)
        self.assertIsNone(imovel.area)


class TestExtraFields(unittest.TestCase):
    """Campos EmCasa-specific preservados em _extra."""

    def test_previous_price_preserved(self):
        """previousPrice preservado no _extra."""
        imovel = from_emcasa_hit(SP_APTO)
        extra = getattr(imovel, "_extra", {})
        self.assertEqual(extra.get("previousPrice"), 900000.0)
        self.assertEqual(extra.get("priceChangePercent"), -5.56)

    def test_price_change_rj(self):
        """priceChangePercent preservado para RJ."""
        imovel = from_emcasa_hit(RJ_CASA)
        extra = getattr(imovel, "_extra", {})
        self.assertEqual(extra.get("previousPrice"), 1350000.0)
        self.assertEqual(extra.get("priceChangePercent"), -11.11)

    def test_building_name_and_floor(self):
        """buildingName e floor preservados."""
        imovel = from_emcasa_hit(SP_APTO)
        extra = getattr(imovel, "_extra", {})
        self.assertEqual(extra.get("buildingName"), "Edifício Vila Rica")
        self.assertEqual(extra.get("floor"), "12")

    def test_coordinates(self):
        """Coordenadas preservadas."""
        imovel = from_emcasa_hit(SP_APTO)
        extra = getattr(imovel, "_extra", {})
        self.assertEqual(extra.get("coordinates"), [-23.5800, -46.6400])

    def test_coordinates_dict_shape(self):
        """Coordenadas no formato dict também funcionam."""
        hit = {
            "document": {
                "id": "coord_test",
                "coordinates": {"lat": -23.5, "lng": -46.6},
            }
        }
        imovel = from_emcasa_hit(hit)
        extra = getattr(imovel, "_extra", {})
        self.assertEqual(extra.get("coordinates"), [-23.5, -46.6])

    def test_building_amenities_preserved(self):
        """buildingAmenities original preservado em _extra."""
        imovel = from_emcasa_hit(SP_COBERTURA)
        extra = getattr(imovel, "_extra", {})
        self.assertIn("piscina", extra.get("buildingAmenities", []))

    def test_property_features_preserved(self):
        """propertyFeatures original preservado em _extra."""
        imovel = from_emcasa_hit(SP_APTO)
        extra = getattr(imovel, "_extra", {})
        self.assertIn("sacada", extra.get("propertyFeatures", []))
        self.assertIn("armário embutido", extra.get("propertyFeatures", []))

    def test_sem_extra_fields(self):
        """Sem campos extra → _extra com defaults."""
        imovel = from_emcasa_hit({"document": {"id": "plain"}})
        extra = getattr(imovel, "_extra", {})
        self.assertIsNone(extra.get("previousPrice"))
        self.assertIsNone(extra.get("priceChangePercent"))
        self.assertEqual(extra.get("buildingAmenities"), [])
        self.assertEqual(extra.get("propertyFeatures"), [])


class TestParseHitBackwardCompat(unittest.TestCase):
    """parse_hit() mantida para compatibilidade com emcasa_api.py."""

    def test_parse_hit_returns_dict(self):
        """parse_hit deve retornar dict (não Imovel)."""
        result = parse_hit(SP_APTO)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("id"), "emcasa_sp_apto_001")
        self.assertEqual(result.get("preco_venda"), 850000.0)
        self.assertEqual(result.get("fonte"), "emcasa")

    def test_parse_hit_has_raw(self):
        """parse_hit deve ter _raw com campos extra."""
        result = parse_hit(SP_APTO)
        self.assertIn("_raw", result)
        self.assertEqual(result["_raw"].get("previousPrice"), 900000.0)
        self.assertEqual(result["_raw"].get("priceChangePercent"), -5.56)

    def test_parse_hit_minimal(self):
        """parse_hit com hit mínimo."""
        result = parse_hit({"document": {"id": "abc"}})
        self.assertEqual(result.get("id"), "emcasa_abc")


class TestAmenities(unittest.TestCase):
    """Normalização e merge de amenities."""

    def test_merge_building_and_property(self):
        """buildingAmenities + propertyFeatures são merged."""
        imovel = from_emcasa_hit(SP_APTO)
        # piscina, academia, portaria24h + sacada, armarioembutido
        self.assertIn("piscina", imovel.amenities)
        self.assertIn("academia", imovel.amenities)
        self.assertIn("portaria24h", imovel.amenities)
        self.assertIn("sacada", imovel.amenities)
        self.assertIn("armario_embutido", imovel.amenities)

    def test_amenity_normalization(self):
        """Acentos removidos, espaços → underscore."""
        name = _normalize_amenity("Armário Embutido")
        self.assertEqual(name, "armario_embutido")

    def test_amenity_lowercase(self):
        """Case normalizado para lowercase."""
        name = _normalize_amenity("SACADA GOURMET")
        self.assertEqual(name, "sacada_gourmet")

    def test_amenity_empty(self):
        """String vazia → vazia."""
        self.assertEqual(_normalize_amenity(""), "")

    def test_no_duplicates(self):
        """Mesma amenity não aparece duplicada."""
        hit = {
            "document": {
                "id": "dup_test",
                "buildingAmenities": ["piscina", "piscina", "academia"],
                "propertyFeatures": ["piscina"],
            }
        }
        imovel = from_emcasa_hit(hit)
        self.assertEqual(imovel.amenities.count("piscina"), 1)


class TestTipoMapping(unittest.TestCase):
    """Mapeamento de tipos EN → BR."""

    def test_all_types_mapped(self):
        """Todos os tipos do TIPO_MAP são mapeados corretamente."""
        for en, br in TIPO_MAP.items():
            hit = {"document": {"id": f"tipo_{en}", "propertyType": en}}
            imovel = from_emcasa_hit(hit)
            self.assertEqual(
                imovel.tipo, br,
                f"Tipo {en} → {br}, obteve {imovel.tipo}"
            )

    def test_unknown_type_preserved(self):
        """Tipo desconhecido é preservado como está."""
        hit = {"document": {"id": "unknown", "propertyType": "chalet"}}
        imovel = from_emcasa_hit(hit)
        self.assertEqual(imovel.tipo, "chalet")

    def test_map_tipo_empty(self):
        """_map_tipo com string vazia → vazia."""
        self.assertEqual(_map_tipo(""), "")

    def test_map_tipo_none(self):
        """Hit sem propertyType → tipo vazio."""
        imovel = from_emcasa_hit({"document": {"id": "no_type"}})
        self.assertEqual(imovel.tipo, "")

    def test_map_tipo_partial_match(self):
        """_map_tipo com match parcial de keyword."""
        self.assertEqual(_map_tipo("apartamento"), "apartamento")


class TestTitleAutoGeration(unittest.TestCase):
    """Geração automática de título quando não há unitDescription."""

    def test_title_from_tipo_bairro_quartos(self):
        """Título montado de tipo + bairro + quartos."""
        hit = {
            "document": {
                "id": "auto_title",
                "propertyType": "apartment",
                "bedrooms": 2,
                "neighborhood": "Pinheiros",
            }
        }
        imovel = from_emcasa_hit(hit)
        self.assertIn("2q", imovel.titulo)
        self.assertIn("Pinheiros", imovel.titulo)

    def test_title_fallback(self):
        """Sem nenhum campo, fallback para 'Imóvel EmCasa'."""
        imovel = from_emcasa_hit({"document": {"id": "min"}})
        self.assertEqual(imovel.titulo, "Imóvel EmCasa")


class TestFromEmCasaHits(unittest.TestCase):
    """Funções de lote."""

    def test_batch_sp_rj(self):
        """from_emcasa_hits com SP e RJ."""
        hits = [SP_APTO, RJ_CASA, SP_COBERTURA]
        imoveis = from_emcasa_hits(hits)
        self.assertEqual(len(imoveis), 3)
        self.assertEqual(imoveis[0].id, "emcasa_sp_apto_001")
        self.assertEqual(imoveis[1].id, "emcasa_rj_casa_001")
        self.assertEqual(imoveis[2].id, "emcasa_sp_coh_002")

    def test_batch_empty(self):
        """Lista vazia → lista vazia."""
        self.assertEqual(from_emcasa_hits([]), [])

    def test_batch_invalid_type(self):
        """Se não for list, retorna []"""
        self.assertEqual(from_emcasa_hits("invalido"), [])


class TestFromEmCasaAPIResponse(unittest.TestCase):
    """Conversão de respostas da API."""

    def test_from_api_response_hits(self):
        """Resposta da API com campo 'hits'."""
        response = {
            "found": 12800,
            "hits": [SP_APTO, SP_COBERTURA],
            "facet_counts": [],
        }
        imoveis = from_emcasa_api_response(response)
        self.assertEqual(len(imoveis), 2)

    def test_from_api_response_imoveis(self):
        """Payload já parseado com campo 'imoveis'."""
        payload = {"imoveis": [RJ_CASA]}
        imoveis = from_emcasa_api_response(payload)
        self.assertEqual(len(imoveis), 1)
        self.assertEqual(imoveis[0].id, "emcasa_rj_casa_001")

    def test_from_api_response_empty(self):
        """Sem hits no payload → []."""
        self.assertEqual(from_emcasa_api_response({"found": 0}), [])

    def test_from_api_response_invalid(self):
        """Payload inválido → []."""
        self.assertEqual(from_emcasa_api_response("invalido"), [])


class TestFromEmCasaSafe(unittest.TestCase):
    """Wrapper à prova de crash."""

    def test_safe_list(self):
        """Lista direta de hits."""
        imoveis = from_emcasa_safe([SP_APTO, RJ_CASA])
        self.assertEqual(len(imoveis), 2)

    def test_safe_dict_hits(self):
        """Dict com 'hits'."""
        imoveis = from_emcasa_safe({"hits": [SP_APTO]})
        self.assertEqual(len(imoveis), 1)

    def test_safe_single_hit(self):
        """Dict com 'document' → hit único."""
        imoveis = from_emcasa_safe(SP_APTO)
        self.assertEqual(len(imoveis), 1)

    def test_safe_single_raw_hit(self):
        """Dict com 'id' → hit único."""
        imoveis = from_emcasa_safe(RAW_HIT)
        self.assertEqual(len(imoveis), 1)

    def test_safe_none(self):
        """None → []."""
        self.assertEqual(from_emcasa_safe(None), [])

    def test_safe_string(self):
        """String → []."""
        self.assertEqual(from_emcasa_safe("invalido"), [])


class TestURLGeneration(unittest.TestCase):
    """Geração de URLs a partir do slug."""

    def test_url_with_slug(self):
        """URL montada com slug."""
        imovel = from_emcasa_hit(SP_APTO)
        expected = "https://www.emcasa.com/imovel/vila-mariana/rua-vergueiro/sp_apto_001"
        self.assertEqual(imovel.url, expected)

    def test_url_rj(self):
        """URL para RJ."""
        imovel = from_emcasa_hit(RJ_CASA)
        expected = "https://www.emcasa.com/imovel/leblon/rua-rainha-elizabeth/rj_casa_001"
        self.assertEqual(imovel.url, expected)

    def test_url_empty(self):
        """Sem slug → URL vazia."""
        imovel = from_emcasa_hit({"document": {"id": "no_slug"}})
        self.assertEqual(imovel.url, "https://www.emcasa.com/imovel/no_slug")


class TestValidation(unittest.TestCase):
    """Validação dos imóveis parseados."""

    def test_sp_apto_valido(self):
        """SP apto é válido."""
        self.assertTrue(from_emcasa_hit(SP_APTO).is_valid())

    def test_sp_cobertura_valido(self):
        """SP cobertura é válido."""
        self.assertTrue(from_emcasa_hit(SP_COBERTURA).is_valid())

    def test_rj_casa_valido(self):
        """RJ casa é válido (condominio=0 → None, sem erros)."""
        self.assertTrue(from_emcasa_hit(RJ_CASA).is_valid())

    def test_rj_apto_valido(self):
        """RJ apto é válido."""
        self.assertTrue(from_emcasa_hit(RJ_APTO).is_valid())

    def test_sem_preco(self):
        """Sem preço → inválido (precisa ao menos 1 preço)."""
        imovel = from_emcasa_hit({"document": {"id": "sem_preco"}})
        self.assertFalse(imovel.is_valid())
        errors = imovel.validate()
        self.assertTrue(any("preco" in e for e in errors))


class TestFotos(unittest.TestCase):
    """Extração de fotos."""

    def test_sp_apto_fotos(self):
        """SP apto tem 2 fotos."""
        imovel = from_emcasa_hit(SP_APTO)
        self.assertEqual(len(imovel.fotos), 2)

    def test_rj_casa_tres_fotos(self):
        """RJ casa tem 3 fotos."""
        imovel = from_emcasa_hit(RJ_CASA)
        self.assertEqual(len(imovel.fotos), 3)

    def test_sem_fotos(self):
        """Sem imageUrls → lista vazia."""
        imovel = from_emcasa_hit({"document": {"id": "no_pics"}})
        self.assertEqual(imovel.fotos, [])

    def test_fotos_sao_urls_http(self):
        """Fotos devem começar com http."""
        imovel = from_emcasa_hit(SP_APTO)
        for foto in imovel.fotos:
            self.assertTrue(foto.startswith("http"), f"Foto não-http: {foto}")


class TestDataPublicacao(unittest.TestCase):
    """data_publicacao deve ser extraída quando disponível."""

    def test_created_at_preserved(self):
        """createdAt vai para data_publicacao."""
        imovel = from_emcasa_hit(SP_APTO)
        self.assertEqual(imovel.data_publicacao, "2026-05-15T10:00:00Z")

    def test_sem_data_publicacao(self):
        """Sem createdAt → data_publicacao None."""
        imovel = from_emcasa_hit(RJ_CASA)
        self.assertIsNone(imovel.data_publicacao)


class TestColetaTimestamp(unittest.TestCase):
    """Timestamp de coleta."""

    def test_auto_timestamp(self):
        """Sem coleta_ts, preenche automaticamente."""
        imovel = from_emcasa_hit(SP_APTO)
        self.assertTrue(imovel.data_coleta.endswith("+00:00"))
        self.assertIn("T", imovel.data_coleta)

    def test_custom_timestamp(self):
        """coleta_ts customizado é preservado."""
        imovel = from_emcasa_hit(SP_APTO, coleta_ts="2026-06-21T12:00:00+00:00")
        self.assertEqual(imovel.data_coleta, "2026-06-21T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
