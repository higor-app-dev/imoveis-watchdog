"""
Tests for output_schema — unified JSON schema transformation and output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure skills dir is on path
_HERE = Path(__file__).resolve().parent.parent
_SKILLS = _HERE / "skills"
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import pytest

from skills.filter_imoveis import filter_imoveis
from skills.output_schema import (
    _infer_negociacao,
    _infer_preco,
    _get_photos,
    _get_amenities,
    normalize_to_schema,
    save_listings,
    save_listings_batch,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_items():
    return [
        {
            "id": "loft_001",
            "titulo": "Apto 2q na Consolação",
            "url": "https://loft.com.br/imovel/loft_001",
            "fonte": "loft",
            "preco_venda": 450000.0,
            "preco_aluguel": None,
            "preco_anterior": 500000.0,
            "condominio": 800.0,
            "iptu": 200.0,
            "endereco": "Rua da Consolação, 500",
            "bairro": "Consolação",
            "cidade": "São Paulo",
            "uf": "SP",
            "area": 55.0,
            "quartos": 2,
            "banheiros": 1,
            "vagas": 1,
            "tipo": "apartamento",
            "descricao": "Apt bem localizado",
            "fotos": ["https://foto1.jpg", "https://foto2.jpg"],
            "agencia": "Loft",
        },
        {
            "id": "emcasa_002",
            "titulo": "Casa 3q Jardins",
            "url": "https://emcasa.com/imovel/emcasa_002",
            "fonte": "emcasa",
            "preco_venda": 1200000.0,
            "preco_aluguel": 5000.0,
            "endereco": "Rua Oscar Freire, 200",
            "bairro": "Jardins",
            "cidade": "São Paulo",
            "uf": "SP",
            "area": 120.0,
            "quartos": 3,
            "banheiros": 2,
            "vagas": 2,
            "tipo": "casa",
            "amenities": ["piscina", "jardim"],
        },
        {
            "id": "olx_003",
            "fonte": "olx",
            "preco_aluguel": 3500.0,
            "bairro": "Pinheiros",
        },
    ]


# ── Tests: _infer_negociacao ─────────────────────────────────────────────────


class TestInferNegociacao:
    def test_venda_only(self):
        assert _infer_negociacao({"preco_venda": 100000}) == "venda"

    def test_aluguel_only(self):
        assert _infer_negociacao({"preco_aluguel": 2000}) == "aluguel"

    def test_both_prices(self):
        # vendas take precedence when both present
        result = _infer_negociacao({"preco_venda": 100000, "preco_aluguel": 2000})
        assert result == "venda"

    def test_no_prices(self):
        assert _infer_negociacao({}) is None

    def test_price_alias(self):
        assert _infer_negociacao({"price": 100000}) == "venda"
        assert _infer_negociacao({"rentalPrice": 2000}) == "aluguel"


# ── Tests: _get_photos ─────────────────────────────────────────────────────


class TestGetPhotos:
    def test_fotos_field(self):
        assert _get_photos({"fotos": ["a.jpg"]}) == ["a.jpg"]

    def test_imagens_field(self):
        assert _get_photos({"imagens": ["b.jpg"]}) == ["b.jpg"]

    def test_photos_field(self):
        assert _get_photos({"photos": ["c.jpg"]}) == ["c.jpg"]

    def test_empty(self):
        assert _get_photos({}) == []

    def test_none(self):
        assert _get_photos({"fotos": None}) == []


# ── Tests: normalize_to_schema ────────────────────────────────────────────


class TestNormalizeToSchema:
    def test_basic_normalization(self, sample_items):
        result = normalize_to_schema(sample_items)
        assert len(result) == 3

    def test_codigo_from_id(self, sample_items):
        result = normalize_to_schema(sample_items)
        assert result[0]["codigo"] == "loft_001"
        assert result[1]["codigo"] == "emcasa_002"
        assert result[2]["codigo"] == "olx_003"

    def test_negociacao_inferred(self, sample_items):
        result = normalize_to_schema(sample_items)
        assert result[0]["negociacao"] == "venda"
        assert result[1]["negociacao"] == "venda"  # both prices → venda
        assert result[2]["negociacao"] == "aluguel"

    def test_preco_derived(self, sample_items):
        result = normalize_to_schema(sample_items)
        assert result[0]["preco"] == 450000.0
        assert result[1]["preco"] == 1200000.0
        assert result[2]["preco"] == 3500.0

    def test_non_dict_items_skipped(self):
        result = normalize_to_schema([None, "string", 42, {}])
        assert len(result) == 1  # only the empty dict gets through

    def test_empty_list(self):
        assert normalize_to_schema([]) == []

    def test_tem_reducao_computed(self, sample_items):
        result = normalize_to_schema(sample_items)
        # Item 0 has preco_anterior=500000 > preco_venda=450000
        assert result[0]["tem_reducao"] is True
        assert result[0]["percentual_reducao"] == pytest.approx(10.0)
        # Item 1 has no preco_anterior
        assert result[1]["tem_reducao"] is False

    def test_todos_os_campos_presentes(self, sample_items):
        result = normalize_to_schema(sample_items)
        expected_fields = {
            "codigo", "titulo", "url", "fonte", "negociacao",
            "tipo", "uso", "preco", "preco_venda", "preco_aluguel",
            "preco_anterior", "condominio", "iptu",
            "endereco", "bairro", "cidade", "uf", "cep",
            "latitude", "longitude",
            "area", "quartos", "suites", "banheiros", "vagas", "andar",
            "descricao", "comodidades", "fotos",
            "agencia", "origem_id",
            "disponivel", "tem_reducao", "percentual_reducao",
            "data_coleta", "data_publicacao", "data_atualizacao_preco",
        }
        assert set(result[0].keys()) == expected_fields

    def test_amenities_aliases(self, sample_items):
        result = normalize_to_schema(sample_items)
        # Item 1 has "amenities" field
        assert result[1]["comodidades"] == ["piscina", "jardim"]

    def test_photo_aliases(self):
        items = [{"id": "x", "imagens": ["img1.jpg", "img2.jpg"]}]
        result = normalize_to_schema(items)
        assert result[0]["fotos"] == ["img1.jpg", "img2.jpg"]


# ── Tests: save_listings ──────────────────────────────────────────────────


class TestSaveListings:
    def test_save_basic(self, sample_items, tmp_path):
        output = tmp_path / "output.json"
        result = save_listings(sample_items, output)
        assert result.exists()
        data = json.loads(output.read_bytes())
        assert data["versao"] == 1
        assert data["total"] == 3
        assert len(data["imoveis"]) == 3

    def test_save_with_filter(self, sample_items, tmp_path):
        output = tmp_path / "filtered.json"
        result = save_listings(
            sample_items, output,
            filter_fn=filter_imoveis,
            tipo="apartamento",
        )
        data = json.loads(output.read_bytes())
        assert data["total"] == 1
        assert data["imoveis"][0]["codigo"] == "loft_001"

    def test_save_with_multi_filter(self, sample_items, tmp_path):
        output = tmp_path / "multi.json"
        result = save_listings(
            sample_items, output,
            filter_fn=filter_imoveis,
            bairro="Jardins",
        )
        data = json.loads(output.read_bytes())
        assert data["total"] == 1
        assert data["imoveis"][0]["codigo"] == "emcasa_002"

    def test_save_empty_list(self, tmp_path):
        output = tmp_path / "empty.json"
        result = save_listings([], output)
        data = json.loads(output.read_bytes())
        assert data["total"] == 0
        assert data["imoveis"] == []

    def test_save_creates_dir(self, sample_items, tmp_path):
        output = tmp_path / "subdir" / "nested" / "output.json"
        result = save_listings(sample_items, output)
        assert result.exists()

    def test_invalid_filter_raises(self, sample_items, tmp_path):
        def bad_filter(items, **_kw):
            raise ValueError("filter failed")
        with pytest.raises(ValueError, match="filter failed"):
            save_listings(sample_items, tmp_path / "bad.json", filter_fn=bad_filter)


# ── Tests: save_listings_batch ────────────────────────────────────────────


class TestSaveListingsBatch:
    def test_batch_basic(self, sample_items, tmp_path):
        batches = {"loft": sample_items[:1], "emcasa": sample_items[1:2]}
        output = save_listings_batch(batches, output_dir=str(tmp_path))
        assert output.exists()
        data = json.loads(output.read_bytes())
        assert data["total"] == 2
        assert data["fontes"] == {"loft": 1, "emcasa": 1}

    def test_batch_with_filter(self, sample_items, tmp_path):
        batches = {"loft": sample_items[:1], "emcasa": sample_items[1:2]}
        output = save_listings_batch(
            batches,
            output_dir=str(tmp_path),
            filter_fn=filter_imoveis,
            tipo="casa",
        )
        data = json.loads(output.read_bytes())
        assert data["total"] == 1
        assert data["filtro"]["aplicado"] == "filter_imoveis"

    def test_batch_empty(self, tmp_path):
        output = save_listings_batch({}, output_dir=str(tmp_path))
        data = json.loads(output.read_bytes())
        assert data["total"] == 0


# ── Integration tests ─────────────────────────────────────────────────────


class TestIntegration:
    def test_loft_then_filter(self, sample_items, tmp_path):
        """Simulate: scrape Loft → normalize → filter → save"""
        raw = sample_items[:1]  # Loft data
        filtered = save_listings(
            raw,
            tmp_path / "loft_filtrado.json",
            filter_fn=filter_imoveis,
            tipo="apartamento",
            bairro="Consolação",
        )
        data = json.loads(filtered.read_bytes())
        assert data["total"] == 1
        assert data["imoveis"][0]["bairro"] == "Consolação"

    def test_multi_source_pipeline(self, sample_items, tmp_path):
        """Simulate: multiple scrapers → batch save → filter"""
        batches = {
            "loft": sample_items[:1],
            "emcasa": sample_items[1:2],
        }
        output = save_listings_batch(
            batches,
            output_dir=str(tmp_path),
            filter_fn=filter_imoveis,
            negociacao="venda",
        )
        data = json.loads(output.read_bytes())
        # Only loft (preco_venda only) passes; emcasa has both prices → ambiguous
        assert data["total"] == 1
        assert data["imoveis"][0]["fonte"] == "loft"
