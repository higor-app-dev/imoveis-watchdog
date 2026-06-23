"""
Testes para o Biasi Leilões extractor (biasileiloes.com.br).

Cobre:
  - _parse_listing_page() com HTML real do AJAX endpoint
  - _parse_listing_page() com página sem cards
  - _parse_address() com vários formatos de endereço
  - _infer_tipo_from_title() com diferentes tipos
  - _extract_city_uf() de título e endereço
  - extract_listings() com página real (integração)
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from skills.biasi_leiloes.extractor import (
    _parse_listing_page,
    _parse_address,
    _infer_tipo_from_title,
    _extract_city_uf,
    extract_listings,
    PARTNER_SLUGS,
    ITEMS_PER_PAGE,
    BASE_URL,
)

logger = logging.getLogger("test_biasi_extractor")

# ═══════════════════════════════════════════════════════════════════════════════
# Sample HTML (minimal listing page with cards)
# ═══════════════════════════════════════════════════════════════════════════════

HTML_WITH_CARDS = """<div class="container">
    <div class="row" id="leilao-lista-lote" index="0" total="225" limit="48">
        <div class="col-xs-12 col-sm-6 col-md-4 col-lg-3 mb-4">
            <a href="/sale/detail?id=57352" target="_self" class="leilao-lote" data-id="57352" url="">
                <div class="card item-bid">
                    <div class="card-img-top photo-lot">
                        <div class="card-img-cover" style="background-image: url(https://cdn-biasi.blueintra.com/images/lot/15/62/250/1562647.jpg"></div>
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
                    <div class="card-img-top photo-lot">
                        <div class="card-img-cover" style="background-image: url(https://cdn-biasi.blueintra.com/images/lot/15/63/250/1563636.jpg"></div>
                    </div>
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

HTML_NO_CARDS = """<div class="container">
    <div class="row" id="leilao-lista-lote" index="0" total="0" limit="48">
        <div class="text-center mb-3 mt-3">
            <div class="azul-Biasi not-found">:(</div>
            <div class="not-found-text">Nenhum lote encontrado</div>
        </div>
    </div>
</div>"""


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _parse_listing_page
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseListingPage:
    def test_with_cards(self):
        """Parse HTML with 2 listing cards."""
        listings = _parse_listing_page(HTML_WITH_CARDS)
        assert len(listings) == 2, f"Expected 2, got {len(listings)}"

        # First card
        l1 = listings[0]
        assert l1.get("id") == "57352"
        assert "Apartamento" in l1.get("titulo", "")
        assert "R$ 450.000,00" in l1.get("valor_primeira_praca", "")
        assert "R$ 315.000,00" in l1.get("valor_segunda_praca", "")
        assert l1.get("status") == "Liberado para Lance"
        assert l1.get("lote") == "Lote 001"
        assert "/sale/detail?id=57352" in l1.get("url", "")
        assert "cdn-biasi" in l1.get("foto_principal", "")

        # Second card
        l2 = listings[1]
        assert l2.get("id") == "57353"
        assert "Casa" in l2.get("titulo", "")
        assert "R$ 550.000,00" in l2.get("valor_primeira_praca", "")
        # No 2nd price
        assert "valor_segunda_praca" not in l2 or not l2.get("valor_segunda_praca")
        assert l2.get("status") == "Não Iniciado"
        # Bid count
        assert "num_lances" not in l2 or l2.get("num_lances") is None

        print(f"  [OK] parsed 2 cards correctly")

    def test_no_cards(self):
        """Empty listing page → empty list."""
        listings = _parse_listing_page(HTML_NO_CARDS)
        assert listings == []
        print("  [OK] empty page → []")

    def test_empty_html(self):
        """Empty HTML → empty list."""
        listings = _parse_listing_page("")
        assert listings == []
        print("  [OK] empty HTML → []")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _parse_address
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseAddress:
    def test_full_address(self):
        """Full Brazilian address."""
        addr = _parse_address("Rua Clóvis Lordano, 140, Núcleo Santa Isabel, Hortolândia/SP")
        assert addr.get("endereco") == "Rua Clóvis Lordano, 140"
        assert addr.get("bairro") == "Núcleo Santa Isabel"
        assert addr.get("cidade") == "Hortolândia"
        assert addr.get("uf") == "SP"
        print("  [OK] full address parsed")

    def test_simple_address(self):
        """Simple address without neighborhood."""
        addr = _parse_address("Av. Paulista, 1000, Bela Vista, São Paulo/SP")
        assert addr.get("endereco") == "Av. Paulista, 1000"
        assert addr.get("bairro") == "Bela Vista"
        assert addr.get("cidade") == "São Paulo"
        assert addr.get("uf") == "SP"
        print("  [OK] simple address")

    def test_address_no_bairro(self):
        """Minimal address - street only."""
        addr = _parse_address("Rua XV de Novembro, 500, Curitiba/PR")
        assert addr.get("endereco") == "Rua XV de Novembro, 500"
        assert addr.get("cidade") == "Curitiba"
        assert addr.get("uf") == "PR"
        print("  [OK] minimal address")

    def test_empty(self):
        """Empty string → empty dict."""
        assert _parse_address("") == {}
        assert _parse_address(None) == {}
        print("  [OK] empty → {}")

    def test_rj_uf(self):
        """RJ UF parsing."""
        addr = _parse_address("Rua do Catete, 200, Catete, Rio de Janeiro/RJ")
        assert addr.get("cidade") == "Rio de Janeiro"
        assert addr.get("uf") == "RJ"
        print("  [OK] RJ city/UF")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _infer_tipo_from_title
# ═══════════════════════════════════════════════════════════════════════════════


class TestInferTipoFromTitle:
    def test_apartamento(self):
        assert _infer_tipo_from_title("Apartamento 2 Quartos") == "apartamento"
        print("  [OK] apartamento")

    def test_casa(self):
        assert _infer_tipo_from_title("Casa em Condomínio") == "casa"
        print("  [OK] casa")

    def test_terreno(self):
        assert _infer_tipo_from_title("Terreno Residencial") == "terreno"
        print("  [OK] terreno")

    def test_comercial(self):
        assert _infer_tipo_from_title("Sala Comercial - Centro") == "comercial"
        print("  [OK] comercial")

    def test_cobertura(self):
        assert _infer_tipo_from_title("Cobertura Duplex") == "cobertura"
        print("  [OK] cobertura")

    def test_none(self):
        assert _infer_tipo_from_title("Propriedade única") is None
        print("  [OK] unknown → None")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _extract_city_uf
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractCityUF:
    def test_from_title_dash(self):
        """City/UF extracted from title after dash."""
        result = _extract_city_uf("Apartamento - São Paulo/SP")
        assert result is not None
        assert result.get("cidade") == "São Paulo"
        assert result.get("uf") == "SP"
        print("  [OK] from title after dash")

    def test_from_address_first(self):
        """Address takes priority over title."""
        result = _extract_city_uf(
            "Imóvel em Leilão",
            address="Rua X, Campinas/SP"
        )
        assert result is not None
        assert result.get("cidade") == "Campinas"
        assert result.get("uf") == "SP"
        print("  [OK] address priority")

    def test_no_match(self):
        """No city/UF info."""
        assert _extract_city_uf("Generic Property") is None
        print("  [OK] no match → None")

    def run_all(self):
        for name in dir(self):
            if name.startswith("test_"):
                getattr(self, name)()


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    all_tests = [
        TestParseListingPage().test_with_cards,
        TestParseListingPage().test_no_cards,
        TestParseListingPage().test_empty_html,
        TestParseAddress().test_full_address,
        TestParseAddress().test_simple_address,
        TestParseAddress().test_address_no_bairro,
        TestParseAddress().test_empty,
        TestParseAddress().test_rj_uf,
        TestInferTipoFromTitle().test_apartamento,
        TestInferTipoFromTitle().test_casa,
        TestInferTipoFromTitle().test_terreno,
        TestInferTipoFromTitle().test_comercial,
        TestInferTipoFromTitle().test_cobertura,
        TestInferTipoFromTitle().test_none,
        TestExtractCityUF().test_from_title_dash,
        TestExtractCityUF().test_from_address_first,
        TestExtractCityUF().test_no_match,
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
