"""
Testes para o QuintoAndar parser.

Cobre:
  - Next.js data route payload completo
  - Listing individual com todos os campos
  - Listing com campos mínimos (edge case)
  - Listing com condoIptu vazio
  - Múltiplos listings
  - Validação do schema unificado
  - URL building
  - Tipo mapping
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

sys.path.insert(0, str(Path(__file__).parent))
from quintoandar_parser import (
    from_quintoandar_listing,
    from_quintoandar_payload,
    from_quintoandar_houses,
    from_quintoandar_api_response,
    _map_tipo,
    _extract_address,
    _extract_condo_iptu,
    _extract_amenities,
    _extract_photos,
)


# ── Dados de exemplo ────────────────────────────────────────────────────────────

LISTING_FULL = {
    "id": "892820623",
    "salePrice": 1000000,
    "rentPrice": 3700,
    "area": 105,
    "bedrooms": 3,
    "bathrooms": 2,
    "parkingSpots": 3,
    "type": "Apartamento",
    "address": {
        "address": "R. Mal. Hermes da Fonseca, 123",
        "city": "São Paulo",
        "stateCode": "SP",
        "neighborhood": "Santana",
    },
    "neighbourhood": "Santana",
    "regionName": "Santana",
    "condoIptu": {"condoFee": 800, "iptu": 150.50},
    "forSale": True,
    "shortSaleDescription": "Apartamento para comprar em Santana com 3 quartos, 2 banheiros, 105m² e 3 vagas de garagem",
    "description": "Ótimo apartamento na região de Santana, perto do metrô. Condomínio completo com piscina, academia e salão de festas. 3 quartos sendo 1 suíte. Cozinha planejada. Vaga para 3 carros.",
    "title": "Apartamento 3 quartos em Santana",
    "amenities": [
        "Piscina",
        "Academia",
        "Salão de Festas",
        "Portaria 24h",
    ],
    "photos": [
        {"url": "https://img.quintoandar.com.br/foto1.jpg"},
        {"url": "https://img.quintoandar.com.br/foto2.jpg"},
    ],
    "citySlug": "sao-paulo-sp-brasil",
    "publishDate": "2026-06-15T10:30:00Z",
}

LISTING_MINIMAL = {
    "id": "12345",
    "salePrice": 350000,
    "area": 45,
    "bedrooms": 2,
    "bathrooms": 1,
    "type": "Casa",
}

LISTING_RENT_ONLY = {
    "id": "67890",
    "rentPrice": 2500,
    "area": 50,
    "bedrooms": 1,
    "bathrooms": 1,
    "type": "Kitnet",
    "neighbourhood": "Centro",
    "citySlug": "sao-paulo-sp-brasil",
    "address": {"neighborhood": "Centro", "city": "São Paulo", "stateCode": "SP"},
    "condoIptu": {"condoFee": 200},
}

NEXTJS_PAYLOAD = {
    "pageProps": {
        "initialState": {
            "houses": [LISTING_FULL, LISTING_MINIMAL, LISTING_RENT_ONLY],
            "search": {"count": 3},
        }
    }
}

API_RESPONSE = {
    "results": [LISTING_FULL, LISTING_RENT_ONLY],
    "total": 2,
}


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_listing_full():
    """Listing completo → todos os campos mapeados corretamente."""
    imovel = from_quintoandar_listing(LISTING_FULL)
    assert imovel.id == "892820623"
    assert imovel.fonte == "quintoandar"
    assert imovel.preco_venda == 1000000.0
    assert imovel.preco_aluguel == 3700.0
    assert imovel.area == 105.0
    assert imovel.quartos == 3
    assert imovel.banheiros == 2
    assert imovel.vagas == 3
    assert imovel.tipo == "apartamento"
    assert imovel.condominio == 800.0
    assert imovel.iptu == 150.50
    assert imovel.bairro == "Santana"
    assert imovel.cidade == "São Paulo"
    assert imovel.uf == "SP"
    assert "Mal. Hermes" in imovel.endereco
    assert "Ótimo apartamento" in imovel.descricao
    assert len(imovel.amenities) == 4
    assert len(imovel.fotos) == 2
    assert imovel.data_publicacao == "2026-06-15T10:30:00Z"
    assert imovel.is_valid(), f"Erros de validação: {imovel.validate()}"
    print("[PASS] test_listing_full")


def test_listing_minimal():
    """Listing mínimo (venda apenas) → preenche defaults."""
    imovel = from_quintoandar_listing(LISTING_MINIMAL)
    assert imovel.id == "12345"
    assert imovel.preco_venda == 350000.0
    assert imovel.preco_aluguel is None
    assert imovel.area == 45.0
    assert imovel.quartos == 2
    assert imovel.banheiros == 1
    assert imovel.vagas is None
    assert imovel.tipo == "casa"
    assert imovel.condominio is None
    assert imovel.iptu is None
    assert imovel.endereco == ""
    assert imovel.bairro == ""
    assert imovel.amenities == []
    assert imovel.fotos == []
    assert imovel.data_publicacao is None
    assert imovel.is_valid(), f"Erros: {imovel.validate()}"
    print("[PASS] test_listing_minimal")


def test_listing_rent_only():
    """Apenas aluguel → preco_venda None."""
    imovel = from_quintoandar_listing(LISTING_RENT_ONLY)
    assert imovel.preco_venda is None
    assert imovel.preco_aluguel == 2500.0
    assert imovel.condominio == 200.0
    assert imovel.iptu is None
    assert imovel.tipo == "kitnet"
    assert imovel.bairro == "Centro"
    assert imovel.uf == "SP"
    assert imovel.is_valid(), f"Erros: {imovel.validate()}"
    print("[PASS] test_listing_rent_only")


def test_nextjs_payload():
    """Next.js data route payload → lista de Imovel."""
    imoveis = from_quintoandar_payload(NEXTJS_PAYLOAD)
    assert len(imoveis) == 3
    assert imoveis[0].id == "892820623"
    assert imoveis[1].id == "12345"
    assert imoveis[2].id == "67890"
    print(f"[PASS] test_nextjs_payload: {len(imoveis)} imóveis")


def test_houses_list():
    """Array de houses direto."""
    imoveis = from_quintoandar_houses([LISTING_FULL, LISTING_MINIMAL])
    assert len(imoveis) == 2
    print("[PASS] test_houses_list")


def test_api_response():
    """API response → lista."""
    imoveis = from_quintoandar_api_response(API_RESPONSE)
    assert len(imoveis) == 2
    print("[PASS] test_api_response")


def test_url_building():
    """URL é montada corretamente."""
    imovel = from_quintoandar_listing(LISTING_FULL)
    assert "quintoandar.com.br" in imovel.url
    assert "comprar" in imovel.url
    # Check that the URL ends with the listing id or similar
    assert len(imovel.url) > 30
    print(f"[PASS] test_url_building: {imovel.url}")

    # Rent only → /alugar/ prefix
    imovel2 = from_quintoandar_listing(LISTING_RENT_ONLY)
    assert "alugar" in imovel2.url
    print(f"[PASS] test_rent_url: {imovel2.url}")


def test_type_mapping():
    """Mapeamento de tipos funciona."""
    cases = [
        ("Apartamento", "apartamento"),
        ("Casa", "casa"),
        ("Casa em Condomínio", "casa_condominio"),
        ("Cobertura", "cobertura"),
        ("Studio", "studio"),
        ("Kitnet", "kitnet"),
        ("Sala Comercial", "comercial"),
        ("Terreno", "terreno"),
        ("Desconhecido", "desconhecido"),  # fallback lowercase
        ("", ""),
    ]
    for raw, expected in cases:
        result = _map_tipo(raw)
        assert result == expected, f"Tipo '{raw}' → '{result}', esperado '{expected}'"
    print("[PASS] test_type_mapping")


def test_validation():
    """Parser produz Imovel válidos ou com erros esperados."""
    # Sem preço → erro de validação
    no_price = {
        "id": "no-price",
        "type": "Apartamento",
        "bedrooms": 2,
    }
    imovel = from_quintoandar_listing(no_price)
    assert not imovel.is_valid()
    errors = imovel.validate()
    assert any("preco" in e for e in errors)
    print(f"[PASS] test_validation: sem preço → {len(errors)} erro(s): {errors}")


def test_empty_condo_iptu():
    """condoIptu vazio → condominio e iptu None."""
    listing = {**LISTING_FULL, "condoIptu": {}}
    imovel = from_quintoandar_listing(listing)
    assert imovel.condominio is None
    assert imovel.iptu is None
    print("[PASS] test_empty_condo_iptu")


def test_amenities_normalization():
    """Amenities são normalizadas para snake_case."""
    listing = {
        **LISTING_FULL,
        "amenities": [
            "Piscina",
            "Academia",
            "Salão de Festas",
            "Portaria 24h",
            "Área Gourmet",
            "Espaço Kids",
        ],
    }
    imovel = from_quintoandar_listing(listing)
    assert "piscina" in imovel.amenities
    assert "academia" in imovel.amenities
    assert "salao_de_festas" in imovel.amenities
    assert "area_gourmet" in imovel.amenities
    print(f"[PASS] test_amenities_normalization: {imovel.amenities}")


def test_photos_various_formats():
    """Fotos em diferentes formatos."""
    listing = {
        **LISTING_FULL,
        "photos": [
            {"url": "https://img.qa.com.br/a.jpg"},
            {"src": "https://img.qa.com.br/b.jpg"},
        ],
        "mainPhoto": {"url": "https://img.qa.com.br/main.jpg"},
    }
    imovel = from_quintoandar_listing(listing)
    assert len(imovel.fotos) >= 3
    assert imovel.fotos[0] == "https://img.qa.com.br/main.jpg"
    print(f"[PASS] test_photos_various_formats: {len(imovel.fotos)} fotos")


def test_city_slug_uf_extraction():
    """UF extraída do citySlug quando não tem stateCode."""
    listing = {
        "id": "999",
        "salePrice": 500000,
        "type": "Apartamento",
        "citySlug": "rio-de-janeiro-rj-brasil",
        "neighbourhood": "Copacabana",
    }
    imovel = from_quintoandar_listing(listing)
    assert imovel.uf == "RJ"
    assert imovel.cidade == "Rio De Janeiro"
    print(f"[PASS] test_city_slug_uf_extraction: UF={imovel.uf}, cidade={imovel.cidade}")


# ── Runner ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_listing_full,
        test_listing_minimal,
        test_listing_rent_only,
        test_nextjs_payload,
        test_houses_list,
        test_api_response,
        test_url_building,
        test_type_mapping,
        test_validation,
        test_empty_condo_iptu,
        test_amenities_normalization,
        test_photos_various_formats,
        test_city_slug_uf_extraction,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Resultado: {passed} passaram, {failed} falharam")
    sys.exit(0 if failed == 0 else 1)
