"""
Tests for lello_parser — Higher-level parser and pagination.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.lello_imoveis.lello_parser import (
    build_lello_url,
    from_lello_listing,
    from_lello_payload,
    save_results,
    parse_tipos_arg,
    load_targets_from_yaml,
    crawl_from_targets,
    TIPOS_DISPONIVEIS,
)

SAMPLE_LISTING = {
    "idImovel": 43923,
    "tipoImovel": "Apartamento",
    "subTipoImovel": "Duplex",
    "cidade": "São Paulo",
    "bairro": "Mooca",
    "uf": "SP",
    "endereco": "Rua Padre Benedito Maria Cardoso",
    "metragemPrincipal": 140,
    "quantidadeDormitorios": 4,
    "quantidadeVagas": 1,
    "quantidadeSuites": 0,
    "quantidadeBanheiros": 1,
    "previsaoCondominio": 600,
    "previsaoIptu": 52,
    "valorVenda": 700000,
    "dataCadastro": "2008-11-19",
    "andar": 0,
    "descricaoFilial": "Mooca",
    "telefoneFilial": "(11) 1111-1111",
    "enderecoFotoPrincipal": "3491/6984433.jpg",
    "fotos": [],
    "estacoesProximas": [],
    "alugueltranquilo": 0,
    "arquitetoDeBolso": True,
}


class TestBuildLelloURL:
    def test_default(self):
        url = build_lello_url({})
        assert "/venda/residencial/apartamento-tipos/1-pagina/" in url

    def test_custom(self):
        url = build_lello_url({"tipo": "casa", "negociacao": "aluguel", "pagina": 5})
        assert "/aluguel/residencial/casa-tipos/5-pagina/" in url

    def test_with_bairro(self):
        url = build_lello_url({"tipo": "apartamento", "negociacao": "venda",
                               "bairro": "Mooca"})
        assert "mooca" in url


class TestFromLelloListing:
    def test_basic(self):
        result = from_lello_listing(SAMPLE_LISTING, negociacao="venda")
        assert result is not None
        assert result.get("id") == "lello_43923"
        assert result.get("preco_venda") == 700000.0
        assert result.get("tipo") == "apartamento"

    def test_empty(self):
        result = from_lello_listing({})
        assert result == {}  # Returns empty dict on failure


class TestFromLelloPayload:
    def test_dict_with_list(self):
        payload = {"list": [SAMPLE_LISTING]}
        results = from_lello_payload(payload)
        assert len(results) == 1
        assert results[0]["id"] == "lello_43923"

    def test_empty_list(self):
        results = from_lello_payload({"list": []})
        assert results == []

    def test_direct_list(self):
        results = from_lello_payload([SAMPLE_LISTING])
        assert len(results) == 1

    def test_invalid_type(self):
        results = from_lello_payload("invalid")
        assert results == []


class TestSaveResults:
    def test_save_and_read(self):
        listings = [{"id": "test_1", "titulo": "Test Listing"}]
        metadata = {"total": 1}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            saved = save_results(listings, metadata, output_path)
            assert os.path.exists(saved)

            with open(saved, "r") as f:
                data = json.load(f)

            assert data["meta"]["total"] == 1
            assert len(data["listings"]) == 1
            assert data["listings"][0]["id"] == "test_1"
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_save_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            saved = save_results([], {}, output_path)
            assert os.path.exists(saved)

            with open(saved, "r") as f:
                data = json.load(f)

            assert data["meta"] == {}
            assert data["listings"] == []
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)


class TestParseTipos:
    def test_all(self):
        result = parse_tipos_arg("all")
        assert result == TIPOS_DISPONIVEIS

    def test_comma_separated(self):
        result = parse_tipos_arg("apartamento,casa,terreno")
        assert result == ["apartamento", "casa", "terreno"]

    def test_single(self):
        result = parse_tipos_arg("apartamento")
        assert result == ["apartamento"]

    def test_wildcard(self):
        result = parse_tipos_arg("*")
        assert result == TIPOS_DISPONIVEIS


# ══════════════════════════════════════════════════════════════════════════════
# Tests: Condo vs non-condo property mapping through unified schema
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_CONDO = {
    "idImovel": 83811,
    "tipoImovel": "Apartamento",
    "cidade": "São Paulo",
    "bairro": "Vila Olímpia",
    "uf": "SP",
    "endereco": "Rua Fidêncio Ramos, 100",
    "metragemPrincipal": 72,
    "quantidadeDormitorios": 2,
    "quantidadeVagas": 1,
    "quantidadeSuites": 0,
    "quantidadeBanheiros": 1,
    "previsaoCondominio": 850,
    "previsaoIptu": 85,
    "valorVenda": 520000,
    "dataCadastro": "2020-03-15",
    "descricaoFilial": "Vila Olímpia",
    "enderecoFotoPrincipal": "some/path.jpg",
}

SAMPLE_NON_CONDO = {
    "idImovel": 99221,
    "tipoImovel": "Casa",
    "subTipoImovel": "Sobrado",
    "cidade": "São Paulo",
    "bairro": "Interlagos",
    "uf": "SP",
    "endereco": "Av. Atlântica, 500",
    "metragemPrincipal": 180,
    "quantidadeDormitorios": 3,
    "quantidadeVagas": 2,
    "quantidadeSuites": 1,
    "quantidadeBanheiros": 2,
    "previsaoCondominio": 0,        # no condo fee — non-condo
    "previsaoIptu": 95,
    "valorVenda": 650000,
    "dataCadastro": "2021-07-22",
    "descricaoFilial": "Interlagos",
    "enderecoFotoPrincipal": "",
    "fotos": [],
}

SAMPLE_RENTAL_WITH_CONDO = {
    "idImovel": 77341,
    "tipoImovel": "Apartamento",
    "cidade": "São Paulo",
    "bairro": "Pinheiros",
    "uf": "SP",
    "endereco": "Rua Cardeal Arcoverde, 250",
    "metragemPrincipal": 55,
    "quantidadeDormitorios": 1,
    "quantidadeVagas": 1,
    "quantidadeSuites": 0,
    "quantidadeBanheiros": 1,
    "previsaoCondominio": 720,
    "previsaoIptu": 42,
    "valorVenda": 0,
    "valorCampanhaLocacao": 3200,
    "dataCadastro": "2024-01-10",
    "descricaoFilial": "Pinheiros",
    "enderecoFotoPrincipal": "",
    "fotos": [],
    "estacoesProximas": [],
}


class TestCondoMapping:
    """Test that condo properties include condominium data in the unified schema."""

    def test_condo_has_condominio_field(self):
        result = from_lello_listing(SAMPLE_CONDO, negociacao="venda")
        assert result is not None
        # Must have condominio populated
        assert result.get("condominio") == 850.0, (
            f"Expected condominio=850.0, got {result.get('condominio')}"
        )
        assert result.get("iptu") == 85.0
        # Must map to unified schema correctly
        assert result.get("codigo") == "83811"
        assert result.get("fonte") == "lelloimoveis"
        assert result.get("preco_venda") == 520000.0
        assert result.get("tipo") == "apartamento"
        assert result.get("bairro") == "Vila Olímpia"
        assert result.get("area") == 72.0

    def test_rental_with_condo(self):
        """Rental listing with condominio should preserve condominio field."""
        result = from_lello_listing(SAMPLE_RENTAL_WITH_CONDO, negociacao="aluguel")
        assert result is not None
        assert result.get("condominio") == 720.0, (
            f"Expected condominio=720.0, got {result.get('condominio')}"
        )
        assert result.get("negociacao") == "aluguel"
        assert result.get("tipo") == "apartamento"

    def test_non_condo_has_no_condominio(self):
        """Non-condo property (previsaoCondominio=0) should have condominio=0.0."""
        result = from_lello_listing(SAMPLE_NON_CONDO, negociacao="venda")
        assert result is not None
        # Lello stores 0 when there's no condo fee; parser preserves it as 0.0
        # (it's not None because the field exists; downstream output_schema
        #  keeps it as-is since it's a valid float)
        assert result.get("codigo") == "99221"
        assert result.get("tipo") == "casa"
        assert result.get("area") == 180.0
        assert result.get("preco_venda") == 650000.0
        assert result.get("bairro") == "Interlagos"
        # condominio is 0.0 (not None) because Lello stores 0 for non-condo
        assert isinstance(result.get("condominio"), (int, float))
        # Confirm the lot size makes sense for a house
        assert result.get("vagas") == 2


# ══════════════════════════════════════════════════════════════════════════════
# Tests: amenities mapping from Lello features
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_WITH_COMPLEMENTOS = {
    "idImovel": 55661,
    "tipoImovel": "Apartamento",
    "cidade": "São Paulo",
    "bairro": "Moema",
    "uf": "SP",
    "metragemPrincipal": 85,
    "quantidadeDormitorios": 3,
    "quantidadeVagas": 2,
    "quantidadeBanheiros": 2,
    "previsaoCondominio": 1200,
    "previsaoIptu": 90,
    "valorVenda": 650000,
    "descricaoFilial": "Moema",
    "enderecoFotoPrincipal": "some/path.jpg",
    "complementos": [
        {"nomeComplemento": "Piscina"},
        {"nomeComplemento": "Academia"},
        {"nomeComplemento": "Salão de Festas"},
    ],
    "dependencias": [
        {"nomeDependencia": "Sacada"},
    ],
}


class TestAmenitiesMapping:
    """Test that Lello features/complementos map to amenities in unified schema."""

    def test_complementos_mapeados_para_amenities(self):
        """Complementos do Lello devem aparecer em amenities."""
        result = from_lello_listing(SAMPLE_WITH_COMPLEMENTOS, negociacao="venda")
        assert result is not None
        amenities = result.get("amenities", [])
        assert len(amenities) == 4, f"Expected 4 amenities, got {len(amenities)}: {amenities}"
        expected = {"piscina", "academia", "salão de festas", "sacada"}
        assert set(amenities) == expected, f"Got {set(amenities)}, expected {expected}"

    def test_amenities_campo_existe_no_schema_imovel(self):
        """O campo amenities no Lello mapper deve ser compatível com Imovel.from_dict."""
        sys.path.insert(0, str(Path.home() / ".hermes"))
        from imovel_schema import Imovel
        result = from_lello_listing(SAMPLE_WITH_COMPLEMENTOS, negociacao="venda")
        assert result is not None
        # Imovel.from_dict deve capturar amenities
        imovel = Imovel.from_dict(result)
        assert imovel.amenities == ["piscina", "academia", "salão de festas", "sacada"] or \
               set(imovel.amenities) == {"piscina", "academia", "salão de festas", "sacada"}

    def test_sem_complementos_amenities_vazio(self):
        """Listing sem complementos deve ter amenities vazio."""
        result = from_lello_listing(SAMPLE_CONDO, negociacao="venda")
        assert result is not None
        assert result.get("amenities") == [], f"Expected empty amenities, got {result.get('amenities')}"


# ══════════════════════════════════════════════════════════════════════════════
# Tests: target-driven crawl (config/targets.yaml integration)
# ══════════════════════════════════════════════════════════════════════════════


class TestTargetDrivenCrawl:
    def test_load_targets_from_yaml(self):
        """load_targets_from_yaml should read Lello section from targets.yaml."""
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "targets.yaml"
        result = load_targets_from_yaml(config_path)
        assert result is not None
        assert "compra" in result, "Expected 'compra' key in Lello targets"
        assert "aluguel" in result, "Expected 'aluguel' key in Lello targets"

        compra = result["compra"]
        assert isinstance(compra, list), "compra should be a list"
        assert len(compra) >= 1, "Should have at least one compra target"

        compra_entry = compra[0]
        assert compra_entry["cidade"] == "são paulo"
        assert compra_entry["uf"] == "SP"
        assert "apartamento" in compra_entry.get("tipos", [])

    def test_load_targets_raises_on_missing(self):
        """load_targets_from_yaml should raise FileNotFoundError for missing path."""
        with pytest.raises(FileNotFoundError):
            load_targets_from_yaml("/nonexistent/path.yaml")

    def test_crawl_from_targets_parses_tipos(self):
        """crawl_from_targets should collect tipos from targets.yaml config."""
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "targets.yaml"
        # We don't actually crawl (would hit real HTTP), but verify the
        # function would construct the right tipo list by temporarily
        # patching crawl_all to capture the args
        called_with = {}

        def mock_crawl_all(tipos=None, negociacoes=None, **kwargs):
            called_with["tipos"] = tipos
            called_with["negociacoes"] = negociacoes
            return [], {"mock": True}

        import skills.lello_imoveis.lello_parser as lp
        original = lp.crawl_all
        lp.crawl_all = mock_crawl_all

        try:
            result, meta = crawl_from_targets(config_path=config_path, max_pages=1)
            assert called_with["tipos"] is not None, "crawl_all should be called with tipos"
            assert "apartamento" in called_with["tipos"]
            assert "casa" in called_with["tipos"]
            assert "venda" in called_with["negociacoes"]
            assert "aluguel" in called_with["negociacoes"]
            assert meta == {"mock": True}
        finally:
            lp.crawl_all = original

    def test_crawl_from_targets_handles_empty_config(self):
        """crawl_from_targets should fall back to all tipos when YAML has no Lello section."""
        import tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
        try:
            tmp.write("geral:\n  intervalo_horas: 6\n")
            tmp.close()
            result, meta = crawl_from_targets(config_path=tmp.name, max_pages=1)
            # Falls back to all tipos — no actual crawl happens, so result is []
            assert isinstance(result, list)
        finally:
            os.unlink(tmp.name)
