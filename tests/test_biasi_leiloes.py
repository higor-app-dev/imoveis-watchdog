"""
test_biasi_leiloes.py — Testes pytest para o Biasi Leilões extractor.

Cobre:
  - _parse_listing_page() com HTML real do AJAX endpoint
  - _parse_listing_page() com páginas sem cards, HTML vazio, malformed
  - _parse_address() com vários formatos de endereço brasileiro
  - _infer_tipo_from_title() com todos os tipos e fallback
  - _infer_partner() com logos de parceiros
  - _extract_city_uf() de título e endereço
  - _parse_price() com formatos de moeda brasileiros
  - extract_listings() com mock de requests (pipeline completo)
  - Constants (BASE_URL, PARTNER_SLUGS, ITEMS_PER_PAGE)
"""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure project root is in path ────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from skills.biasi_leiloes.extractor import (
    _parse_listing_page,
    _parse_address,
    _infer_tipo_from_title,
    _infer_partner,
    _extract_city_uf,
    _parse_price,
    extract_listings,
    PARTNER_SLUGS,
    ITEMS_PER_PAGE,
    BASE_URL,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures — sample HTML payloads
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def html_with_cards() -> str:
    """HTML de listagem com 2 cards completos."""
    return """<div class="container">
    <div class="row" id="leilao-lista-lote" index="0" total="225" limit="48">
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=57352" target="_self" class="leilao-lote" data-id="57352" url="">
                <div class="card item-bid">
                    <div class="card-img-top photo-lot">
                        <div class="card-img-cover" style="background-image: url(https://cdn-biasi.blueintra.com/images/lot/15/62/250/1562647.jpg)"></div>
                    </div>
                    <div class="card-label">
                        <span><span>Lote 001</span></span>
                    </div>
                    <div class="card-body text-descricao">
                        <div class="d-flex container-title">
                            <i class="fa-solid fa-house"></i>
                            <h5 class="card-title">Apartamento Teste - São Paulo/SP</h5>
                        </div>
                        <div class="card-lot">
                            <div class="price-leiloes">
                                <span class="bid-value-text">1º Leilão:</span>
                                <span class="price-line-2-pracas">R$ 450.000,00</span><br>
                                <span class="bid-value-text">2º Leilão:</span>
                                <span class="price-line-2-pracas">R$ 315.000,00</span>
                            </div>
                        </div>
                        <div class="mt-3 mb-3">
                            <i class="fa-solid fa-gavel"></i>
                            <span>5 Lances</span>
                        </div>
                        <div style="text-align: center;">
                            <div class="label-md status-green">
                                <span>Liberado para Lance</span>
                            </div>
                        </div>
                    </div>
                </div>
            </a>
        </div>
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=57353" target="_self" class="leilao-lote" data-id="57353" url="">
                <div class="card item-bid">
                    <div class="card-img-cover" style="background-image: url(https://cdn-biasi.blueintra.com/images/lot/15/63/250/1563636.jpg)"></div>
                    <div class="card-body text-descricao">
                        <div class="d-flex container-title">
                            <h5 class="card-title">Casa Teste - Campinas/SP</h5>
                        </div>
                        <div class="card-lot">
                            <div class="price-leiloes">
                                <span class="price-line-2-pracas">R$ 550.000,00</span>
                            </div>
                        </div>
                        <div style="text-align: center;">
                            <div class="label-md status-orange">
                                <span>Não Iniciado</span>
                            </div>
                        </div>
                    </div>
                </div>
            </a>
        </div>
    </div>
</div>"""


@pytest.fixture
def html_no_cards() -> str:
    """HTML de listagem vazia (sem lotes encontrados)."""
    return """<div class="container">
    <div class="row" id="leilao-lista-lote" index="0" total="0" limit="48">
        <div class="text-center mb-3 mt-3">
            <div class="azul-Biasi not-found">:(</div>
            <div class="not-found-text">Nenhum lote encontrado</div>
        </div>
    </div>
</div>"""


@pytest.fixture
def html_with_comitente() -> str:
    """HTML com logo do comitente (parceiro Santander)."""
    return """<div class="container">
    <div class="row" id="leilao-lista-lote" index="0" total="5" limit="48">
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=12345" class="leilao-lote" data-id="12345">
                <div class="card item-bid">
                    <img class="image-comitente" src="/images/logo-santander.png">
                    <div class="card-body text-descricao">
                        <h5 class="card-title">Apto Santander - SP/SP</h5>
                    </div>
                </div>
            </a>
        </div>
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=12346" class="leilao-lote" data-id="12346">
                <div class="card item-bid">
                    <img class="image-comitente" src="/images/logo-itau.png">
                    <div class="card-body text-descricao">
                        <h5 class="card-title">Apto Itaú - RJ/RJ</h5>
                    </div>
                </div>
            </a>
        </div>
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=12347" class="leilao-lote" data-id="12347">
                <div class="card item-bid">
                    <img class="image-comitente" src="/images/logo-rodobens.png">
                    <div class="card-body text-descricao">
                        <h5 class="card-title">Apto Rodobens - BH/MG</h5>
                    </div>
                </div>
            </a>
        </div>
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=12348" class="leilao-lote" data-id="12348">
                <div class="card item-bid">
                    <div class="card-body text-descricao">
                        <h5 class="card-title">Sem comitente - DF/DF</h5>
                    </div>
                </div>
            </a>
        </div>
    </div>
</div>"""


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _parse_listing_page
# ═══════════════════════════════════════════════════════════════════════════


class TestParseListingPage:
    """Testes para _parse_listing_page() — parser de cards HTML."""

    def test_with_cards(self, html_with_cards: str):
        """Parse HTML com 2 cards completos — verifica todos os campos."""
        listings = _parse_listing_page(html_with_cards)
        assert len(listings) == 2

        # --- Card 1: completo (id, título, preços, status, lote, foto, lances) ---
        l1 = listings[0]
        assert l1["id"] == "57352"
        assert l1["titulo"] == "Apartamento Teste - São Paulo/SP"
        assert l1["url"] == "https://www.biasileiloes.com.br/sale/detail?id=57352"
        assert l1["lote"] == "Lote 001"
        assert l1["valor_primeira_praca"] == "R$ 450.000,00"
        assert l1["valor_segunda_praca"] == "R$ 315.000,00"
        assert l1["status"] == "Liberado para Lance"
        assert l1["num_lances"] == 5
        assert "cdn-biasi" in l1["foto_principal"]

        # --- Card 2: sem 2º preço, sem lances, sem lote ---
        l2 = listings[1]
        assert l2["id"] == "57353"
        assert l2["titulo"] == "Casa Teste - Campinas/SP"
        assert l2["valor_primeira_praca"] == "R$ 550.000,00"
        assert "valor_segunda_praca" not in l2 or not l2.get("valor_segunda_praca")
        assert l2["status"] == "Não Iniciado"
        assert "num_lances" not in l2
        assert "lote" not in l2

    def test_no_cards(self, html_no_cards: str):
        """Página sem cards → lista vazia."""
        assert _parse_listing_page(html_no_cards) == []

    @pytest.mark.parametrize(
        "html", ["", "   ", "<html></html>", "<div>nada aqui</div>"]
    )
    def test_empty_or_invalid_html(self, html: str):
        """HTML vazio, whitespace, ou sem estrutura → lista vazia."""
        assert _parse_listing_page(html) == []


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _parse_address
# ═══════════════════════════════════════════════════════════════════════════


class TestParseAddress:
    """Testes para _parse_address() — parser de endereço brasileiro."""

    @pytest.mark.parametrize(
        "addr_str, expected",
        [
            (
                "Rua Clóvis Lordano, 140, Núcleo Santa Isabel, Hortolândia/SP",
                {"endereco": "Rua Clóvis Lordano, 140", "bairro": "Núcleo Santa Isabel", "cidade": "Hortolândia", "uf": "SP"},
            ),
            (
                "Av. Paulista, 1000, Bela Vista, São Paulo/SP",
                {"endereco": "Av. Paulista, 1000", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP"},
            ),
            (
                "Rua XV de Novembro, 500, Curitiba/PR",
                {"endereco": "Rua XV de Novembro, 500", "cidade": "Curitiba", "uf": "PR"},
            ),
            (
                "Rua do Catete, 200, Catete, Rio de Janeiro/RJ",
                {"endereco": "Rua do Catete, 200", "bairro": "Catete", "cidade": "Rio de Janeiro", "uf": "RJ"},
            ),
            (
                "Rua da Praia, 100, Centro, Porto Alegre/RS",
                {"endereco": "Rua da Praia, 100", "bairro": "Centro", "cidade": "Porto Alegre", "uf": "RS"},
            ),
            (
                "Rua sem bairro, 999, São Paulo/SP",
                {"endereco": "Rua sem bairro, 999", "cidade": "São Paulo", "uf": "SP"},
            ),
        ],
    )
    def test_valid_addresses(self, addr_str: str, expected: dict):
        """Vários formatos de endereço brasileiro são parsados corretamente."""
        result = _parse_address(addr_str)
        for key, value in expected.items():
            assert result.get(key) == value, (
                f"Mismatch for '{key}': expected {value!r}, got {result.get(key)!r}"
            )

    @pytest.mark.parametrize("addr", ["", None])
    def test_empty_or_none(self, addr):
        """String vazia ou None → dict vazio."""
        assert _parse_address(addr) == {}

    def test_address_number_in_street(self):
        """Número de rua no final da string deve ser anexado ao endereço."""
        result = _parse_address("Rua Augusta, 1500, Consolação, São Paulo/SP")
        assert result["endereco"] == "Rua Augusta, 1500"
        assert result["bairro"] == "Consolação"
        assert result["cidade"] == "São Paulo"
        assert result["uf"] == "SP"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _infer_tipo_from_title
# ═══════════════════════════════════════════════════════════════════════════


class TestInferTipoFromTitle:
    """Testes para _infer_tipo_from_title() — inferência de tipo do imóvel."""

    @pytest.mark.parametrize(
        "title, expected",
        [
            ("Apartamento 2 Quartos Mobiliado", "apartamento"),
            ("Casa em Condomínio Fechado", "casa"),
            ("Terreno Residencial 300m²", "terreno"),
            ("Sala Comercial Centro", "comercial"),
            ("Cobertura Duplex VIP", "cobertura"),
            ("Kitnet Mobiliada", "kitnet"),
            ("Studio 30m²", "studio"),
            ("Flat Novo", "flat"),
            ("Loft Reformado", "loft"),
            ("Sobrado 3 Quartos", "sobrado"),
            ("Galpão Industrial 500m²", "comercial"),
            ("Prédio Comercial Centro", "comercial"),
            ("Loja 50m²", "comercial"),
        ],
    )
    def test_known_types(self, title: str, expected: str):
        """Tipos conhecidos retornam o valor normalizado."""
        assert _infer_tipo_from_title(title) == expected

    def test_unknown_type(self):
        """Título sem tipo conhecido → None."""
        assert _infer_tipo_from_title("Propriedade única em São Paulo") is None

    def test_case_insensitive(self):
        """Busca é case-insensitive."""
        assert _infer_tipo_from_title("APARTAMENTO LUXO") == "apartamento"
        assert _infer_tipo_from_title("CASA NA PRAIA") == "casa"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _infer_partner
# ═══════════════════════════════════════════════════════════════════════════


class TestInferPartner:
    """Testes para _infer_partner() — inferência do parceiro pelo logo."""

    @pytest.mark.parametrize(
        "logo_url, expected",
        [
            ("/images/logo-santander.png", "Leilão Santander"),
            ("/images/santander-banner.jpg", "Leilão Santander"),
            ("/images/logo-itau.png", "Leilão Itaú"),
            ("/images/itau_imoveis.svg", "Leilão Itaú"),
            ("/images/logo-rodobens.png", "Leilão Rodobens"),
            ("/images/outro-banco.png", ""),
        ],
    )
    def test_partner_inference(self, logo_url: str, expected: str):
        """Logo do parceiro mapeia para nome do leilão."""
        result = _infer_partner({"comitente_logo": logo_url})
        assert result == expected

    def test_no_logo(self):
        """Sem logo → string vazia."""
        assert _infer_partner({}) == ""
        assert _infer_partner({"comitente_logo": ""}) == ""


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _extract_city_uf
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractCityUF:
    """Testes para _extract_city_uf() — extração cidade/UF."""

    def test_from_title_with_dash(self):
        """Cidade/UF extraída do título após travessão."""
        result = _extract_city_uf("Apartamento - São Paulo/SP")
        assert result is not None
        assert result["cidade"] == "São Paulo"
        assert result["uf"] == "SP"

    def test_from_title_with_en_dash(self):
        """Cidade/UF extraída com en-dash."""
        result = _extract_city_uf("Cobertura – Rio de Janeiro/RJ")
        assert result is not None
        assert result["cidade"] == "Rio de Janeiro"
        assert result["uf"] == "RJ"

    def test_address_priority(self):
        """Endereço tem prioridade sobre título."""
        result = _extract_city_uf(
            "Imóvel em Leilão", address="Rua X, Campinas/SP"
        )
        assert result is not None
        assert result["cidade"] == "Campinas"
        assert result["uf"] == "SP"

    def test_no_match(self):
        """Sem informação de cidade/UF."""
        assert _extract_city_uf("Generic Property") is None

    def test_title_with_uf_only(self):
        """Título termina com /UF mas sem cidade explícita."""
        result = _extract_city_uf("Lote Residencial/SP")
        assert result is not None
        assert result["uf"] == "SP"

    def test_empty_title_and_address(self):
        """Título vazio e sem address."""
        assert _extract_city_uf("") is None
        assert _extract_city_uf("", "") is None


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _parse_price
# ═══════════════════════════════════════════════════════════════════════════


class TestParsePrice:
    """Testes para _parse_price() — parser de preço brasileiro."""

    @pytest.mark.parametrize(
        "price_str, expected",
        [
            ("R$ 450.000,00", 450000.00),
            ("R$ 315.000,00", 315000.00),
            ("R$ 1.234.567,89", 1234567.89),
            ("R$ 99,90", 99.90),
            ("R$ 1000,00", 1000.00),
            ("R$ 1000", 1000.00),
            ("450000", 450000.00),
            ("1.500,50", 1500.50),
        ],
    )
    def test_valid_prices(self, price_str: str, expected: float):
        """Preços em formato brasileiro são convertidos para float."""
        result = _parse_price(price_str)
        assert result is not None
        assert abs(result - expected) < 0.01

    @pytest.mark.parametrize("price_str", ["", None, 45000, "N/A", "Grátis"])
    def test_invalid_prices(self, price_str):
        """Entradas inválidas retornam None."""
        assert _parse_price(price_str) is None


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _parse_listing_page with comitente/partner
# ═══════════════════════════════════════════════════════════════════════════


class TestParseListingPageWithPartner:
    """Testes de parsing de cards com logos de parceiros."""

    def test_comitente_partner_inference(self, html_with_comitente: str):
        """Logo do comitente é parsado e parceiro inferido."""
        listings = _parse_listing_page(html_with_comitente)
        assert len(listings) == 4

        names = [l.get("nome_leilao", "") for l in listings]
        assert names[0] == "Leilão Santander"
        assert names[1] == "Leilão Itaú"
        assert names[2] == "Leilão Rodobens"
        assert names[3] == ""  # sem comitente

    def test_comitente_logo_url_saved(self, html_with_comitente: str):
        """URL do logo é preservada no campo comitente_logo."""
        listings = _parse_listing_page(html_with_comitente)
        assert "comitente_logo" in listings[0]
        assert "santander" in listings[0]["comitente_logo"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Tests: extract_listings (com mock)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractListings:
    """Testes para extract_listings() com requests mockado."""

    def test_single_page(self, html_with_cards: str):
        """Extração de 1 página retorna os cards apropriados."""
        mock_resp = MagicMock()
        mock_resp.text = html_with_cards
        mock_resp.raise_for_status = MagicMock()

        with patch("skills.biasi_leiloes.extractor.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.return_value = mock_resp

            listings = extract_listings(source="santander", pages=1)

        assert len(listings) == 2
        assert listings[0]["id"] == "57352"
        assert listings[1]["id"] == "57353"
        # Verifica que a URL AJAX foi chamada
        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert AJAX_SEARCH_URL in call_args[0][0] or "/Sale/LotListSearch" in call_args[0][0]

    def test_empty_page(self, html_no_cards: str):
        """Página sem resultados → lista vazia (pagination stop)."""
        mock_resp = MagicMock()
        mock_resp.text = html_no_cards
        mock_resp.raise_for_status = MagicMock()

        with patch("skills.biasi_leiloes.extractor.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.return_value = mock_resp

            listings = extract_listings(source="santander", pages=3)

        # Deve parar na primeira página (sem cards) e retornar vazio
        assert listings == []

    def test_pagination_stops_on_empty(self):
        """Paginação deve parar quando uma página vem sem cards."""
        # Page 1: 1 card, Page 2: 1 card, Page 3: empty
        html_page1 = """<div class="row" id="leilao-lista-lote">
            <a href="/sale/detail?id=1" class="leilao-lote" data-id="1">
                <div class="card-body"><h5 class="card-title">Apto 1</h5></div>
            </a>
        </div>"""
        html_page2 = """<div class="row" id="leilao-lista-lote">
            <a href="/sale/detail?id=2" class="leilao-lote" data-id="2">
                <div class="card-body"><h5 class="card-title">Apto 2</h5></div>
            </a>
        </div>"""
        html_empty = """<div class="container">
            <div class="row" id="leilao-lista-lote" index="0" total="0" limit="48">
                <div class="text-center"><div class="not-found-text">Nenhum lote encontrado</div></div>
            </div>
        </div>"""

        mock_resp_1 = MagicMock(text=html_page1, raise_for_status=MagicMock())
        mock_resp_2 = MagicMock(text=html_page2, raise_for_status=MagicMock())
        mock_resp_3 = MagicMock(text=html_empty, raise_for_status=MagicMock())

        with patch("skills.biasi_leiloes.extractor.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.side_effect = [mock_resp_1, mock_resp_2, mock_resp_3]

            listings = extract_listings(source="santander", pages=3)

        assert len(listings) == 2
        assert listings[0]["id"] == "1"
        assert listings[1]["id"] == "2"

    def test_partner_slugs_mapping(self):
        """PARTNER_SLUGS mapeia corretamente os parceiros."""
        assert PARTNER_SLUGS["santander"] == "santander"
        assert PARTNER_SLUGS["itau"] == "itau"
        assert PARTNER_SLUGS["rodobens"] == "rodobenssa"
        assert PARTNER_SLUGS["todos"] == ""

    def test_http_failure_propagates(self):
        """Falha HTTP em session.get() propaga exceção (sem try/except interno)."""
        with patch("skills.biasi_leiloes.extractor.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.side_effect = Exception("Connection error")

            with pytest.raises(Exception, match="Connection error"):
                extract_listings(source="santander", pages=1)


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Constants and module-level
# ═══════════════════════════════════════════════════════════════════════════


class TestConstants:
    """Verifica constantes do módulo."""

    def test_base_url(self):
        assert BASE_URL == "https://www.biasileiloes.com.br"

    def test_items_per_page(self):
        assert ITEMS_PER_PAGE == 48

    def test_partner_slugs_has_keys(self):
        assert set(PARTNER_SLUGS.keys()) == {"santander", "itau", "rodobens", "todos"}


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Detail page parsing (via _parse_listing_page + URL convention)
# ═══════════════════════════════════════════════════════════════════════════


class TestUrlConstruction:
    """Testes de construção de URL nos cards."""

    def test_url_absolute(self, html_with_cards: str):
        """URL relativa é convertida para absoluta."""
        listings = _parse_listing_page(html_with_cards)
        assert all(l["url"].startswith("https://www.biasileiloes.com.br") for l in listings)

    def test_url_contains_id(self, html_with_cards: str):
        """URL contém o ID do imóvel."""
        listings = _parse_listing_page(html_with_cards)
        assert "/sale/detail?id=57352" in listings[0]["url"]
        assert "/sale/detail?id=57353" in listings[1]["url"]


# ── Reuse for pagination test ─────────────────────────────────────

AJAX_SEARCH_URL = "/Sale/LotListSearch"
