"""
Testes para o Biasi Leilões parser (biasileiloes.com.br).

Cobre:
  - _normalize_photo_url() com IDs numéricos, URLs absolutas, dicts
  - _derive_partition() com vários tamanhos de ID
  - _collect_photos() de múltiplas fontes
  - _parse_area_text() com formatos brasileiros
  - _parse_bedrooms_text() com vários patterns
  - _extract_vagas_text() com diferentes formatos
  - _parse_money_br() com formatos de moeda brasileiros
  - _parse_date_br() com datas brasileiras
  - _infer_tipo() a partir de descrição/título
  - from_biasi_listing() com listing completo
  - from_biasi_listing() com listing mínimo
  - from_biasi_listing() invalid input
  - from_biasi_payload() com vários formatos
  - Schema validation (Imovel compatibility)
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

sys.path.insert(0, str(Path(__file__).parent))
from biasi_leiloes_parser import (
    from_biasi_listing,
    from_biasi_payload,
    _normalize_photo_url,
    _collect_photos,
    _generate_all_resolutions,
    _parse_area_text,
    _parse_bedrooms_text,
    _extract_vagas_text,
    _parse_money_br,
    _parse_date_br,
    _derive_partition,
    _infer_tipo,
    CDN_BASE,
    PHOTO_SIZES,
    FONTE,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Sample data
# ═══════════════════════════════════════════════════════════════════════════════

# Full listing based on real Biasi Leilões detail page structure
LISTING_FULL = {
    "id": "1564035",
    "titulo": "Apartamento 3 Quartos com 2 Vagas — Mooca, SP",
    "url": "https://www.biasileiloes.com.br/sale/detail?id=1564035",
    "descricao": (
        "Apartamento com 03 dormitórios sendo 1 suíte, 73,7600 m² de área "
        "privativa, sala para 2 ambientes, cozinha, área de serviço, dependência "
        "de empregada, 2 vagas de garagem. Prédio com portaria 24h, piscina, "
        "academia e salão de festas."
        "\n\nOBS: Imóvel Ocupado."
    ),
    "endereco": "Rua Visconde de Itaboraí, 456",
    "bairro": "Mooca",
    "cidade": "São Paulo",
    "uf": "SP",
    "cep": "03108-020",
    "lote": "1564035",
    "nome_leilao": "1º Leilão Unificado de Imóveis",
    "data_primeiro_leilao": "15/07/2026 14:30",
    "data_segundo_leilao": "12/08/2026 14:30",
    "status": "Liberado para Lance",
    "lance_inicial": 450000.0,
    "lance_inicial_2": 315000.0,
    "ocupacao": "Ocupado",
    "tipo_imovel": "Apartamento",
    "quartos": 3,
    "vagas": 2,
    "area_text": "73,7600 m²",
    "cadastro_municipal": "123.456.789-0",
    "matricula": "CRI 45.678",
    "edital_url": "https://www.biasileiloes.com.br/edital/1564035.pdf",
    "whatsapp": "https://wa.me/5511999999999",
    "og_image": "https://cdn-biasi.blueintra.com/images/lot/15/64/1000/1564035.jpg",
}

# Full listing with primary fields at top level
LISTING_WITH_BID_STRINGS = {
    "id": "2298731",
    "titulo": "Casa 2 Quartos em Interlagos",
    "descricao": "Casa com 2 dormitórios, 1 suíte, 150m² de área total, quintal, churrasqueira.",
    "endereco": "Av. Atlântica, 1500",
    "bairro": "Interlagos",
    "cidade": "São Paulo",
    "uf": "SP",
    "lote": "2298731",
    "nome_leilao": "Leilão Santander Imóveis",
    "data_primeiro_leilao": "21/06/2026",
    "status": "Liberado para Lance",
    "lance_inicial": "R$ 550.000,00",
    "lance_inicial_2": "R$ 385.000,00",
    "ocupacao": "Desocupado",
    "tipo_imovel": "Casa",
    "cadastro_municipal": "987.654.321-0",
    "edital_url": "https://www.biasileiloes.com.br/edital/2298731.pdf",
    "whatsapp": "(11) 99999-9999",
    "og_image": "https://cdn-biasi.blueintra.com/images/lot/22/98/1000/2298731.jpg",
}

# Minimal listing
LISTING_MINIMAL = {
    "id": "998877",
    "titulo": "Imóvel em Leilão",
    "lance_inicial": 250000.0,
    "cidade": "São Paulo",
    "uf": "SP",
}

# Auction listing page format (from /leilao/{id}/{slug})
AUCTION_LISTING_FORMAT = {
    "leilao": {
        "id": 4283,
        "nome": "Leilão de Imóveis Itaú",
        "data_inicio": "01/07/2026 10:00",
    },
    "lotes": [
        {
            "id": "LOT001",
            "titulo": "Apartamento 2 Quartos — Centro",
            "lance_inicial": 180000.0,
            "cidade": "São Paulo",
            "uf": "SP",
            "fotos": ["998877"],
        },
        {
            "id": "LOT002",
            "titulo": "Casa 3 Quartos — Jardins",
            "lance_inicial": 650000.0,
            "cidade": "São Paulo",
            "uf": "SP",
        },
    ],
}

# AJAX partial format (from /Sale/LotListSearch)
AJAX_PARTIAL_FORMAT = {
    "listings": [
        {"id": "1001", "titulo": "Apto 2q Pinheiros", "lance_inicial": 350000.0, "cidade": "São Paulo", "uf": "SP"},
        {"id": "1002", "titulo": "Apto 1q Vila Mariana", "lance_inicial": 280000.0, "cidade": "São Paulo", "uf": "SP"},
    ]
}

# Photo test data
PHOTO_TEST = {
    "id": "test-photos",
    "titulo": "Test Photos",
    "lance_inicial": 100000.0,
    "cidade": "São Paulo",
    "uf": "SP",
    "og_image": "https://cdn-biasi.blueintra.com/images/lot/15/64/1000/1564035.jpg",
    "fotos": ["1564035", "1564036", "1564037"],
    "foto_principal": "1564035",
}

# Vehicle listing
LISTING_VEHICLE = {
    "id": "VEH001",
    "titulo": "VW Gol 1.6 2018",
    "lance_inicial": 35000.0,
    "cidade": "São Paulo",
    "uf": "SP",
    "placa": "ABC-1234",
    "ano_fabricacao": 2018,
    "km": "45000",
    "tipo_imovel": "Veículo",
}

# Empty/invalid
LISTING_EMPTY = {}
LISTING_NONE = None
INVALID_PAYLOADS = ["not json", 42, True]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _derive_partition
# ═══════════════════════════════════════════════════════════════════════════════


class TestDerivePartition:
    def test_standard_id(self):
        """1564035 → partition 15/64"""
        xx, yy = _derive_partition("1564035")
        assert xx == "15"
        assert yy == "64"
        print("  [OK] 1564035 → 15/64")

    def test_short_id(self):
        """998 → partition 09/98 (zero-padded)"""
        xx, yy = _derive_partition("998")
        assert xx == "09"
        assert yy == "98"
        print("  [OK] 998 → 09/98")

    def test_single_digit(self):
        """5 → partition 00/05"""
        xx, yy = _derive_partition("5")
        assert xx == "00"
        assert yy == "05"
        print("  [OK] 5 → 00/05")

    def test_long_id(self):
        """12345678 → partition 12/34"""
        xx, yy = _derive_partition("12345678")
        assert xx == "12"
        assert yy == "34"
        print("  [OK] 12345678 → 12/34")

    def test_numeric_input(self):
        """int input works too"""
        xx, yy = _derive_partition(1564035)
        assert xx == "15"
        assert yy == "64"
        print("  [OK] int 1564035 → 15/64")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _normalize_photo_url
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizePhotoURL:
    def test_absolute_url_passthrough(self):
        """Already absolute URL passes through."""
        url = _normalize_photo_url("https://cdn-biasi.blueintra.com/images/lot/15/64/1000/1564035.jpg")
        assert url == "https://cdn-biasi.blueintra.com/images/lot/15/64/1000/1564035.jpg"
        print("  [OK] absolute URL passes through")

    def test_numeric_image_id(self):
        """Numeric image ID builds CDN URL."""
        url = _normalize_photo_url("1564035")
        assert url == f"{CDN_BASE}/15/64/1000/1564035.jpg"
        print(f"  [OK] numeric ID → {url}")

    def test_int_image_id(self):
        """Integer image ID builds CDN URL."""
        url = _normalize_photo_url(1564035)
        assert url == f"{CDN_BASE}/15/64/1000/1564035.jpg"
        print(f"  [OK] int ID → {url}")

    def test_dict_with_url(self):
        """Dict with url key extracts and normalizes."""
        url = _normalize_photo_url({"url": "1564035"})
        assert url == f"{CDN_BASE}/15/64/1000/1564035.jpg"
        print("  [OK] dict with url → CDN")

    def test_dict_with_id(self):
        """Dict with id key extracts and normalizes."""
        url = _normalize_photo_url({"id": "998877"})
        assert url == f"{CDN_BASE}/99/88/1000/998877.jpg"
        print("  [OK] dict with id → CDN")

    def test_custom_size(self):
        """Custom size (500px) builds correct URL."""
        url = _normalize_photo_url("1564035", size=500)
        assert url == f"{CDN_BASE}/15/64/500/1564035.jpg"
        print("  [OK] custom size 500px")

    def test_none_empty(self):
        """None and empty return None."""
        assert _normalize_photo_url(None) is None
        assert _normalize_photo_url("") is None
        assert _normalize_photo_url({}) is None
        print("  [OK] None/empty handled")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _collect_photos
# ═══════════════════════════════════════════════════════════════════════════════


class TestCollectPhotos:
    def test_og_image_only(self):
        """Only og_image → returns it."""
        raw = {"og_image": "https://cdn-biasi.blueintra.com/images/lot/15/64/1000/1564035.jpg"}
        fotos = _collect_photos(raw)
        assert len(fotos) == 1
        assert "1564035.jpg" in fotos[0]
        print("  [OK] og_image only")

    def test_og_image_with_fotos(self):
        """og_image prioritized, fotos appended deduplicated."""
        raw = {
            "og_image": "https://cdn-biasi.blueintra.com/images/lot/15/64/1000/1564035.jpg",
            "fotos": ["1564035", "1564036", "1564037"],
        }
        fotos = _collect_photos(raw)
        assert len(fotos) == 3, f"Expected 3, got {len(fotos)}"
        assert "1564035.jpg" in fotos[0]  # OG first
        assert "1564036.jpg" in fotos[1]
        assert "1564037.jpg" in fotos[2]
        print("  [OK] og_image + fotos, deduped")

    def test_foto_principal(self):
        """foto_principal included."""
        raw = {
            "foto_principal": "112233",
            "fotos": ["112233", "445566"],
        }
        fotos = _collect_photos(raw)
        assert len(fotos) == 2, f"Expected 2, got {len(fotos)}"
        assert "112233" in fotos[0]  # foto_principal or from fotos, not OG
        print("  [OK] foto_principal included")

    def test_images_field(self):
        """Legacy images field processed."""
        raw = {
            "images": ["998877", "998878"],
        }
        fotos = _collect_photos(raw)
        assert len(fotos) == 2
        print("  [OK] legacy 'images' field")

    def test_no_photos(self):
        """No photo sources → empty list."""
        fotos = _collect_photos({"id": "x"})
        assert fotos == []
        print("  [OK] no photos → []")

    def test_from_listing_full(self):
        """Full listing with og_image returns photos."""
        fotos = _collect_photos(LISTING_FULL)
        assert len(fotos) >= 1
        assert all(f.startswith("https://") for f in fotos)
        print(f"  [OK] {len(fotos)} photos from full listing")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _parse_area_text
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseAreaText:
    def test_brazilian_comma(self):
        """73,7600 m² → 73.76"""
        area = _parse_area_text("73,7600 m²")
        assert area is not None
        assert abs(area - 73.76) < 0.01, f"Got {area}"
        print(f"  [OK] 73,7600 m² → {area}")

    def test_no_decimals(self):
        """120 m² → 120.0"""
        area = _parse_area_text("120 m²")
        assert area == 120.0
        print(f"  [OK] 120 m² → {area}")

    def test_with_thousands_separator(self):
        """1.500,00 m² → 1500.0"""
        area = _parse_area_text("1.500,00 m²")
        assert area is not None
        assert abs(area - 1500.0) < 0.01, f"Got {area}"
        print(f"  [OK] 1.500,00 m² → {area}")

    def test_inline_no_space(self):
        """150m² → 150.0"""
        area = _parse_area_text("área total de 150m²")
        assert area == 150.0
        print(f"  [OK] 150m² → {area}")

    def test_m2_lowercase(self):
        """73,7600 m2 → 73.76"""
        area = _parse_area_text("73,7600 m2")
        assert area is not None
        assert abs(area - 73.76) < 0.01
        print(f"  [OK] 73,7600 m2 → {area}")

    def test_none_text(self):
        """None → None"""
        assert _parse_area_text(None) is None
        print("  [OK] None → None")

    def test_no_match(self):
        """No area pattern in text → None"""
        assert _parse_area_text("Sem informação de área") is None
        print("  [OK] no match → None")

    def test_from_description(self):
        """Extract from full description text."""
        area = _parse_area_text(LISTING_FULL["descricao"])
        assert area is not None
        assert abs(area - 73.76) < 0.01
        print(f"  [OK] from description → {area}")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _parse_bedrooms_text
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseBedroomsText:
    def test_standard_format(self):
        """03 dormitórios → 3"""
        rooms = _parse_bedrooms_text("Apartamento com 03 dormitórios")
        assert rooms == 3
        print("  [OK] 03 dormitórios → 3")

    def test_no_padding(self):
        """3 dormitorios → 3"""
        rooms = _parse_bedrooms_text("3 dormitorios")
        assert rooms == 3
        print("  [OK] 3 dormitorios → 3")

    def test_quartos_format(self):
        """2 quartos → 2"""
        rooms = _parse_bedrooms_text("Apartamento com 2 quartos")
        assert rooms == 2
        print("  [OK] 2 quartos → 2")

    def test_suite_plus_dormitorios(self):
        """1 suíte + 2 dormitórios → 3 (both patterns captured)"""
        rooms = _parse_bedrooms_text("1 suíte + 2 dormitórios")
        # This captures "2 dormitórios" → 2
        assert rooms == 2
        print("  [OK] 1 suíte + 2 dormitórios → 2 (separate terms)")

    def test_no_match(self):
        """No bedroom info → None"""
        assert _parse_bedrooms_text("Sem quartos") is None
        print("  [OK] no match → None")

    def test_none(self):
        """None → None"""
        assert _parse_bedrooms_text(None) is None
        print("  [OK] None → None")

    def test_from_full_listing(self):
        """From LISTING_FULL description → 3"""
        rooms = _parse_bedrooms_text(LISTING_FULL["descricao"])
        assert rooms == 3
        print("  [OK] from full listing → 3")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _extract_vagas_text
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractVagasText:
    def test_standard(self):
        """2 vagas de garagem → 2"""
        vagas = _extract_vagas_text("2 vagas de garagem")
        assert vagas == 2
        print("  [OK] 2 vagas → 2")

    def test_simple(self):
        """1 vaga → 1"""
        vagas = _extract_vagas_text("1 vaga")
        assert vagas == 1
        print("  [OK] 1 vaga → 1")

    def test_no_match(self):
        """No parking info → None"""
        assert _extract_vagas_text("Sem vagas") is None
        print("  [OK] no match → None")

    def test_none(self):
        """None → None"""
        assert _extract_vagas_text(None) is None
        print("  [OK] None → None")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _parse_money_br
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseMoneyBR:
    def test_brazilian_format(self):
        """R$ 450.000,00 → 450000.0"""
        val = _parse_money_br("R$ 450.000,00")
        assert val == 450000.0
        print("  [OK] R$ 450.000,00 → 450000.0")

    def test_no_decimal(self):
        """R$ 550000 → 550000.0"""
        val = _parse_money_br("R$ 550000")
        assert val == 550000.0
        print("  [OK] R$ 550000 → 550000.0")

    def test_no_prefix(self):
        """450.000,00 → 450000.0"""
        val = _parse_money_br("450.000,00")
        assert val == 450000.0
        print("  [OK] 450.000,00 → 450000.0")

    def test_float_input(self):
        """450000.0 → 450000.0"""
        val = _parse_money_br(450000.0)
        assert val == 450000.0
        print("  [OK] float → 450000.0")

    def test_int_input(self):
        """450000 → 450000.0"""
        val = _parse_money_br(450000)
        assert val == 450000.0
        print("  [OK] int → 450000.0")

    def test_large_value(self):
        """R$ 1.200.000,00 → 1200000.0"""
        val = _parse_money_br("R$ 1.200.000,00")
        assert val == 1200000.0
        print("  [OK] R$ 1.200.000,00 → 1200000.0")

    def test_none(self):
        """None → None"""
        assert _parse_money_br(None) is None
        print("  [OK] None → None")

    def test_empty(self):
        """'' → None"""
        assert _parse_money_br("") is None
        print("  [OK] '' → None")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _parse_date_br
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseDateBR:
    def test_with_time(self):
        """15/07/2026 14:30 → ISO string"""
        dt = _parse_date_br("15/07/2026 14:30")
        assert dt is not None
        assert "2026-07-15" in dt
        assert "14:30" in dt
        print(f"  [OK] 15/07/2026 14:30 → {dt}")

    def test_date_only(self):
        """21/06/2026 → ISO date"""
        dt = _parse_date_br("21/06/2026")
        assert dt is not None
        assert "2026-06-21" in dt
        print(f"  [OK] 21/06/2026 → {dt}")

    def test_with_as(self):
        """21/06/2026 às 10:00 → ISO string"""
        dt = _parse_date_br("21/06/2026 às 10:00")
        assert dt is not None
        assert "2026-06-21" in dt
        assert "10:00" in dt
        print(f"  [OK] 21/06/2026 às 10:00 → {dt}")

    def test_none(self):
        """None → None"""
        assert _parse_date_br(None) is None
        print("  [OK] None → None")

    def test_invalid(self):
        """Invalid → None"""
        assert _parse_date_br("not a date") is None
        print("  [OK] invalid → None")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _infer_tipo
# ═══════════════════════════════════════════════════════════════════════════════


class TestInferTipo:
    def test_apartamento(self):
        t = _infer_tipo("Apartamento moderno com vista")
        assert t == "apartamento"
        print("  [OK] apartamento")

    def test_casa(self):
        t = _infer_tipo("Casa com piscina e jardim")
        assert t == "casa"
        print("  [OK] casa")

    def test_fallback_default(self):
        t = _infer_tipo("Propriedade única")
        assert t == "apartamento"
        print("  [OK] fallback to apartamento")

    def test_from_title(self):
        t = _infer_tipo("", "Cobertura Duplex de Luxo")
        assert t == "cobertura"
        print("  [OK] from title")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: from_biasi_listing
# ═══════════════════════════════════════════════════════════════════════════════


def test_listing_full():
    """Full listing → all fields mapped correctly."""
    imovel = from_biasi_listing(LISTING_FULL)
    assert imovel is not None
    assert imovel["id"] == "1564035"
    assert imovel["fonte"] == FONTE
    assert imovel["titulo"] == LISTING_FULL["titulo"]
    assert imovel["preco_venda"] == 450000.0
    assert imovel["preco_segundo_leilao"] == 315000.0
    assert imovel["bairro"] == "Mooca"
    assert imovel["cidade"] == "São Paulo"
    assert imovel["uf"] == "SP"
    assert imovel["endereco"] == "Rua Visconde de Itaboraí, 456"
    assert imovel["status"] == "Liberado para Lance"
    assert imovel["disponivel"] is True
    assert imovel["ocupacao"] == "Ocupado"
    assert imovel["tipo"] == "apartamento"
    # Area parsed from description
    assert imovel["area"] is not None
    assert abs(imovel["area"] - 73.76) < 0.01, f"Area = {imovel['area']}"
    # Bedrooms parsed from description
    assert imovel["quartos"] == 3
    # Parking from description
    assert imovel["vagas"] == 2
    # Auction-specific fields
    assert imovel["nome_leilao"] == "1º Leilão Unificado de Imóveis"
    assert imovel["numero_lote"] == "1564035"
    assert "2026-07-15" in imovel["data_primeiro_leilao"]
    assert "2026-08-12" in imovel["data_segundo_leilao"]
    # Legal fields
    assert imovel["cadastro_municipal"] == "123.456.789-0"
    assert imovel["matricula"] == "CRI 45.678"
    assert imovel["edital_url"] == "https://www.biasileiloes.com.br/edital/1564035.pdf"
    assert imovel["whatsapp"] == "https://wa.me/5511999999999"
    # Photos
    assert len(imovel["fotos"]) >= 1
    assert all(f.startswith("https://") for f in imovel["fotos"])
    print("[PASS] test_listing_full")


def test_listing_with_string_bids():
    """Listing with string-formatted bid values."""
    imovel = from_biasi_listing(LISTING_WITH_BID_STRINGS)
    assert imovel is not None
    assert imovel["preco_venda"] == 550000.0
    assert imovel["preco_segundo_leilao"] == 385000.0
    assert imovel["tipo"] == "casa"
    assert imovel["bairro"] == "Interlagos"
    assert imovel["ocupacao"] == "Desocupado"
    # Area from description
    assert imovel["area"] == 150.0
    # Bedrooms from description
    assert imovel["quartos"] == 2
    print("[PASS] test_listing_with_string_bids")


def test_listing_minimal():
    """Minimal listing → no crashes, sensible defaults."""
    imovel = from_biasi_listing(LISTING_MINIMAL)
    assert imovel is not None
    assert imovel["id"] == "998877"
    assert imovel["fonte"] == FONTE
    assert imovel["preco_venda"] == 250000.0
    assert imovel["cidade"] == "São Paulo"
    assert imovel["uf"] == "SP"
    # Defaults
    assert imovel["bairro"] == ""
    assert imovel["tipo"] == "apartamento"  # default
    assert imovel["status"] == ""  # no status provided
    assert imovel["disponivel"] is True
    assert imovel["area"] is None
    assert imovel["quartos"] is None
    assert imovel["fotos"] == []
    assert len(imovel["data_coleta"]) > 0
    print("[PASS] test_listing_minimal")


def test_listing_invalid():
    """Invalid inputs → None."""
    assert from_biasi_listing(None) is None
    assert from_biasi_listing([]) is None
    assert from_biasi_listing("string") is None
    assert from_biasi_listing(123) is None
    print("[PASS] test_listing_invalid")


def test_listing_empty():
    """Empty dict → returns mapped dict with defaults, no crash."""
    imovel = from_biasi_listing({})
    assert imovel is not None
    assert imovel["id"] == ""
    assert imovel["fonte"] == FONTE
    assert imovel["preco_venda"] is None
    assert imovel["disponivel"] is True
    print("[PASS] test_listing_empty")


def test_listing_photo_construction():
    """Photos constructed from image IDs in fotos array."""
    imovel = from_biasi_listing(PHOTO_TEST)
    assert imovel is not None
    fotos = imovel["fotos"]
    assert len(fotos) >= 1
    # All should be CDN URLs or absolute
    for f in fotos:
        assert "cdn-biasi" in f or f.startswith("http")
    print(f"[PASS] test_listing_photo_construction: {len(fotos)} photos")


def test_listing_vehicle():
    """Vehicle listing → extra fields preserved."""
    imovel = from_biasi_listing(LISTING_VEHICLE)
    assert imovel is not None
    assert imovel["preco_venda"] == 35000.0
    assert imovel["placa"] == "ABC-1234"
    assert imovel["ano_fabricacao"] == 2018
    assert imovel["km"] == "45000"
    # tipo inferred from tipo_imovel and lowercased
    assert imovel["tipo"] == "veículo", f"Expected 'veículo', got '{imovel['tipo']}'"
    print("[PASS] test_listing_vehicle")


def test_listing_imovel_compatibility():
    """Output dict is compatible with Imovel.from_dict()."""
    imovel_dict = from_biasi_listing(LISTING_FULL)
    assert imovel_dict is not None
    try:
        imovel = Imovel.from_dict(imovel_dict)
        assert imovel.id == "1564035"
        assert imovel.fonte == FONTE
        assert imovel.preco_venda == 450000.0
        assert imovel.bairro == "Mooca"
        errors = imovel.validate()
        # With preco_venda set (450000.0), validation should have no errors
        # related to missing prices. preco_aluguel=None is fine because
        # preco_venda exists.
        price_errors = [e for e in errors if "preco" in e.lower()]
        assert len(price_errors) == 0, f"Unexpected price errors: {price_errors}"
        print(f"[PASS] test_listing_imovel_compatibility: id={imovel.id}, errors={errors}")
    except Exception as e:
        print(f"[FAIL] test_listing_imovel_compatibility: {e}")
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: from_biasi_payload
# ═══════════════════════════════════════════════════════════════════════════════


def test_payload_ajax_format():
    """AJAX partial format (dict with 'listings')."""
    imoveis = from_biasi_payload(AJAX_PARTIAL_FORMAT)
    assert len(imoveis) == 2
    assert imoveis[0]["id"] == "1001"
    assert imoveis[1]["id"] == "1002"
    print(f"[PASS] test_payload_ajax_format: {len(imoveis)} listings")


def test_payload_auction_format():
    """Auction listing format (dict with 'lotes')."""
    imoveis = from_biasi_payload(AUCTION_LISTING_FORMAT)
    assert len(imoveis) == 2
    assert imoveis[0]["id"] == "LOT001"
    assert imoveis[1]["id"] == "LOT002"
    print(f"[PASS] test_payload_auction_format: {len(imoveis)} listings")


def test_payload_direct_list():
    """Direct list of listings."""
    imoveis = from_biasi_payload([
        LISTING_FULL,
        LISTING_MINIMAL,
    ])
    assert len(imoveis) == 2
    assert imoveis[0]["id"] == "1564035"
    assert imoveis[1]["id"] == "998877"
    print(f"[PASS] test_payload_direct_list: {len(imoveis)} listings")


def test_payload_json_string():
    """JSON string payload."""
    data = json.dumps(AJAX_PARTIAL_FORMAT)
    imoveis = from_biasi_payload(data)
    assert len(imoveis) == 2
    print(f"[PASS] test_payload_json_string: {len(imoveis)} listings")


def test_payload_empty_list():
    """Empty list → []."""
    imoveis = from_biasi_payload([])
    assert imoveis == []
    print("[PASS] test_payload_empty_list")


def test_payload_invalid():
    """Invalid payloads → []."""
    for payload in INVALID_PAYLOADS:
        imoveis = from_biasi_payload(payload)
        assert imoveis == [], f"Expected [] for {type(payload).__name__}, got {len(imoveis)}"
    print("[PASS] test_payload_invalid")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Photo CDN debug
# ═══════════════════════════════════════════════════════════════════════════════


class TestPhotoCDN:
    def test_cdn_url_format_250(self):
        """CDN 250px URL format."""
        url = _normalize_photo_url("1564035", size=250)
        assert url == f"{CDN_BASE}/15/64/250/1564035.jpg"
        print("  [OK] CDN 250px URL")

    def test_cdn_url_format_500(self):
        """CDN 500px URL format."""
        url = _normalize_photo_url("1564035", size=500)
        assert url == f"{CDN_BASE}/15/64/500/1564035.jpg"
        print("  [OK] CDN 500px URL")

    def test_cdn_url_format_1000(self):
        """CDN 1000px URL format."""
        url = _normalize_photo_url("1564035", size=1000)
        assert url == f"{CDN_BASE}/15/64/1000/1564035.jpg"
        print("  [OK] CDN 1000px URL")

    def test_size_constants_exist(self):
        """PHOTO_SIZES dict has expected keys."""
        assert "thumb" in PHOTO_SIZES
        assert "medium" in PHOTO_SIZES
        assert "large" in PHOTO_SIZES
        assert PHOTO_SIZES["large"] == 1000
        print("  [OK] PHOTO_SIZES defined")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _generate_all_resolutions
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateAllResolutions:
    def test_from_numeric_id(self):
        """Generate all resolutions from a numeric image ID."""
        result = _generate_all_resolutions("1564035")
        assert result is not None
        assert result["original"] == f"{CDN_BASE}/15/64/1000/1564035.jpg"
        assert result["large"] == f"{CDN_BASE}/15/64/1000/1564035.jpg"
        assert result["medium"] == f"{CDN_BASE}/15/64/500/1564035.jpg"
        assert result["thumb"] == f"{CDN_BASE}/15/64/250/1564035.jpg"
        print("  [OK] from numeric ID")

    def test_from_absolute_url(self):
        """Generate all resolutions from an absolute CDN URL."""
        result = _generate_all_resolutions(
            "https://cdn-biasi.blueintra.com/images/lot/15/62/1000/1562647.jpg"
        )
        assert result is not None
        assert result["original"] == f"{CDN_BASE}/15/62/1000/1562647.jpg"
        assert result["large"] == f"{CDN_BASE}/15/62/1000/1562647.jpg"
        assert result["medium"] == f"{CDN_BASE}/15/62/500/1562647.jpg"
        assert result["thumb"] == f"{CDN_BASE}/15/62/250/1562647.jpg"
        print("  [OK] from absolute URL")

    def test_small_id_zero_padded(self):
        """Small IDs get zero-padded for partition derivation."""
        result = _generate_all_resolutions("12")
        assert result is not None
        assert result["original"] == f"{CDN_BASE}/00/12/1000/12.jpg"
        print("  [OK] small ID zero-padded")

    def test_none_empty(self):
        """None and empty return None."""
        assert _generate_all_resolutions(None) is None
        assert _generate_all_resolutions("") is None
        print("  [OK] None/empty handled")

    def test_non_image_url(self):
        """Non-CDN URL returns as original only."""
        result = _generate_all_resolutions("https://example.com/image.png")
        assert result is not None
        assert result["original"] == "https://example.com/image.png"
        print("  [OK] non-CDN URL passthrough")

    def test_invalid_string(self):
        """Random non-numeric, non-URL string returns None."""
        assert _generate_all_resolutions("foobar") is None
        print("  [OK] invalid string returns None")

    def test_added_to_listing_output(self):
        """image_urls field is populated in from_biasi_listing output."""
        raw = {
            "id": "test-photo-urls",
            "titulo": "Test image_urls",
            "lance_inicial": 100000.0,
            "cidade": "São Paulo",
            "uf": "SP",
            "fotos": ["1564035", "1564036"],
        }
        result = from_biasi_listing(raw)
        assert "image_urls" in result
        assert len(result["image_urls"]) == 2
        first = result["image_urls"][0]
        assert "original" in first
        assert "large" in first
        assert "medium" in first
        assert "thumb" in first
        print("  [OK] image_urls in listing output")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    all_tests = [
        # from_biasi_listing
        test_listing_full,
        test_listing_with_string_bids,
        test_listing_minimal,
        test_listing_invalid,
        test_listing_empty,
        test_listing_photo_construction,
        test_listing_vehicle,
        test_listing_imovel_compatibility,
        # from_biasi_payload
        test_payload_ajax_format,
        test_payload_auction_format,
        test_payload_direct_list,
        test_payload_json_string,
        test_payload_empty_list,
        test_payload_invalid,
        # Class-based test groups
        TestDerivePartition().test_standard_id,
        TestDerivePartition().test_short_id,
        TestDerivePartition().test_single_digit,
        TestDerivePartition().test_long_id,
        TestDerivePartition().test_numeric_input,
        TestNormalizePhotoURL().test_absolute_url_passthrough,
        TestNormalizePhotoURL().test_numeric_image_id,
        TestNormalizePhotoURL().test_int_image_id,
        TestNormalizePhotoURL().test_dict_with_url,
        TestNormalizePhotoURL().test_dict_with_id,
        TestNormalizePhotoURL().test_custom_size,
        TestNormalizePhotoURL().test_none_empty,
        TestCollectPhotos().test_og_image_only,
        TestCollectPhotos().test_og_image_with_fotos,
        TestCollectPhotos().test_foto_principal,
        TestCollectPhotos().test_images_field,
        TestCollectPhotos().test_no_photos,
        TestCollectPhotos().test_from_listing_full,
        TestParseAreaText().test_brazilian_comma,
        TestParseAreaText().test_no_decimals,
        TestParseAreaText().test_with_thousands_separator,
        TestParseAreaText().test_inline_no_space,
        TestParseAreaText().test_m2_lowercase,
        TestParseAreaText().test_none_text,
        TestParseAreaText().test_no_match,
        TestParseAreaText().test_from_description,
        TestParseBedroomsText().test_standard_format,
        TestParseBedroomsText().test_no_padding,
        TestParseBedroomsText().test_quartos_format,
        TestParseBedroomsText().test_suite_plus_dormitorios,
        TestParseBedroomsText().test_no_match,
        TestParseBedroomsText().test_none,
        TestParseBedroomsText().test_from_full_listing,
        TestExtractVagasText().test_standard,
        TestExtractVagasText().test_simple,
        TestExtractVagasText().test_no_match,
        TestExtractVagasText().test_none,
        TestParseMoneyBR().test_brazilian_format,
        TestParseMoneyBR().test_no_decimal,
        TestParseMoneyBR().test_no_prefix,
        TestParseMoneyBR().test_float_input,
        TestParseMoneyBR().test_int_input,
        TestParseMoneyBR().test_large_value,
        TestParseMoneyBR().test_none,
        TestParseMoneyBR().test_empty,
        TestParseDateBR().test_with_time,
        TestParseDateBR().test_date_only,
        TestParseDateBR().test_with_as,
        TestParseDateBR().test_none,
        TestParseDateBR().test_invalid,
        TestInferTipo().test_apartamento,
        TestInferTipo().test_casa,
        TestInferTipo().test_fallback_default,
        TestInferTipo().test_from_title,
        TestPhotoCDN().test_cdn_url_format_250,
        TestPhotoCDN().test_cdn_url_format_500,
        TestPhotoCDN().test_cdn_url_format_1000,
        TestPhotoCDN().test_size_constants_exist,
        TestGenerateAllResolutions().test_from_numeric_id,
        TestGenerateAllResolutions().test_from_absolute_url,
        TestGenerateAllResolutions().test_small_id_zero_padded,
        TestGenerateAllResolutions().test_none_empty,
        TestGenerateAllResolutions().test_non_image_url,
        TestGenerateAllResolutions().test_invalid_string,
        TestGenerateAllResolutions().test_added_to_listing_output,
    ]

    passed = 0
    failed = 0
    for test in all_tests:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"[FAIL] {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Resultado: {len(all_tests)} testes executados")
    print(f"Passaram:  {passed}")
    print(f"Falharam:  {failed}")
    sys.exit(0 if failed == 0 else 1)
