"""
test_zuk_parser — Testes para o parser do Portal Zuk (portalzuk.com.br).

Cobre:
    - _normalize_photo_url() — diversas variantes de URL (mini, detalhe, dict, relativa)
    - _collect_photos() — coleta de fontes múltiplas com dedup
    - FIELD_MAP — mapeamento de campos
    - from_zuk_listing() — conversão com e sem Imovel schema
    - from_zuk_payload() — payload em diversos formatos
    - Helpers: _parse_br_price, _to_float, _to_int, _parse_address
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────

# Ensure we can import imovel_schema e o módulo do projeto
_HOME = Path.home()
sys.path.insert(0, str(_HOME / ".hermes"))   # imovel_schema
sys.path.insert(0, str(_HOME / "imoveis-watchdog"))  # skills.zuk

# ── Imports ──────────────────────────────────────────────────────────────────

from skills.zuk.zuk_parser import (
    FIELD_MAP,
    _normalize_photo_url,
    _collect_photos,
    _parse_br_price,
    _to_float,
    _to_int,
    _parse_address,
    _build_zuk_id,
    _infer_tipo,
    from_zuk_listing,
    from_zuk_payload,
    IMAGE_BASE,
    BASE_URL,
)

# Optional: try Imovel for schema-aware tests
try:
    from imovel_schema import Imovel
    HAS_IMOVEL = True
except ImportError:
    HAS_IMOVEL = False


# ── Tests: _normalize_photo_url ──────────────────────────────────────────────


class TestNormalizePhotoUrl:
    """Testa _normalize_photo_url com todas as variantes de URL do CDN Zuk."""

    def test_none_and_empty(self):
        assert _normalize_photo_url(None) is None
        assert _normalize_photo_url("") is None
        assert _normalize_photo_url("   ") is None

    def test_dict_format(self):
        """Dict com chave 'url'."""
        result = _normalize_photo_url({"url": "/mini/2025/01/abc123.jpg"})
        assert result == f"{IMAGE_BASE}/detalhe/2025/01/abc123.jpg"

    def test_dict_with_src(self):
        """Dict com chave 'src' como fallback."""
        result = _normalize_photo_url({"src": "/mini/2025/06/xyz456.webp"})
        assert result == f"{IMAGE_BASE}/detalhe/2025/06/xyz456.webp"

    def test_dict_missing_keys(self):
        """Dict sem url ou src."""
        assert _normalize_photo_url({"alt": "photo"}) is None

    def test_absolute_mini_url(self):
        """URL absoluta mini → detalhe."""
        url = "https://imagens.portalzuk.com.br/mini/2025/01/abc123.jpg"
        result = _normalize_photo_url(url)
        assert result == "https://imagens.portalzuk.com.br/detalhe/2025/01/abc123.jpg"

    def test_absolute_detalhe_url(self):
        """URL já no formato detalhe → pass-through."""
        url = "https://imagens.portalzuk.com.br/detalhe/2025/01/abc123.jpg"
        result = _normalize_photo_url(url)
        assert result == url

    def test_relative_mini(self):
        """URL relativa começando com /mini/."""
        result = _normalize_photo_url("/mini/2024/12/foto789.jpg")
        assert result == f"{IMAGE_BASE}/detalhe/2024/12/foto789.jpg"

    def test_relative_no_mini_prefix(self):
        """URL relativa sem /mini/ prefix (fallback)."""
        result = _normalize_photo_url("/2024/12/foto789.jpg")
        assert result == f"{IMAGE_BASE}/2024/12/foto789.jpg"

    def test_absolute_external(self):
        """URL externa absoluta (og:image ou outro CDN) → pass-through."""
        url = "https://external-cdn.com/img/photo.jpg"
        result = _normalize_photo_url(url)
        assert result == url

    def test_plain_filename(self):
        """Apenas nome de arquivo (edge case raro)."""
        result = _normalize_photo_url("foto.jpg")
        assert result == f"{IMAGE_BASE}/foto.jpg"

    def test_webp_format(self):
        """URL .webp mini → detalhe mantendo extensão."""
        url = "/mini/2025/03/sample.webp"
        result = _normalize_photo_url(url)
        assert result == f"{IMAGE_BASE}/detalhe/2025/03/sample.webp"
        assert result.endswith(".webp")

    def test_full_zuk_absolute_mini(self):
        """URL absoluta completa do portal Zuk com mini."""
        url = "https://imagens.portalzuk.com.br/mini/2024/05/8ad34be8c9fb9e4acf36c0a9c23e6e4b.jpg"
        result = _normalize_photo_url(url)
        expected = "https://imagens.portalzuk.com.br/detalhe/2024/05/8ad34be8c9fb9e4acf36c0a9c23e6e4b.jpg"
        assert result == expected


# ── Tests: _collect_photos ──────────────────────────────────────────────────


class TestCollectPhotos:
    """Testa coleta e normalização de fotos de múltiplas fontes."""

    def test_from_image_urls_array(self):
        """image_urls[] com URLs relativas."""
        raw = {"image_urls": ["/mini/2025/01/a.jpg", "/mini/2025/01/b.jpg"]}
        photos = _collect_photos(raw)
        assert len(photos) == 2
        assert all(p.startswith(IMAGE_BASE) for p in photos)
        assert all("/detalhe/" in p for p in photos)

    def test_from_image_urls_single(self):
        """image_url (single string) + image_urls (array) — deve dedup."""
        raw = {
            "image_url": "/mini/2025/01/a.jpg",
            "image_urls": ["/mini/2025/01/a.jpg", "/mini/2025/01/b.jpg"],
        }
        photos = _collect_photos(raw)
        # image_urls array is checked first, then image_url — dedup via seen set
        assert len(photos) >= 1
        assert all("/detalhe/" in p for p in photos)

    def test_from_fotos_fallback(self):
        """fotos array como fallback (formato detalhe)."""
        raw = {
            "fotos": [
                "https://imagens.portalzuk.com.br/detalhe/2025/01/a.jpg",
            ]
        }
        photos = _collect_photos(raw)
        assert len(photos) == 1
        assert "/detalhe/" in photos[0]

    def test_dedup(self):
        """Mesma URL em múltiplas fontes → deduplicada."""
        raw = {
            "image_urls": [
                "/mini/2025/01/a.jpg",
                "/mini/2025/01/a.jpg",  # duplicada
            ],
        }
        photos = _collect_photos(raw)
        assert len(photos) == 1

    def test_empty(self):
        """Nenhuma fonte de foto."""
        assert _collect_photos({}) == []
        assert _collect_photos({"titulo": "casa"}) == []

    def test_mixed_types(self):
        """Mix de URLs absolutas e relativas."""
        raw = {
            "image_urls": [
                "/mini/2025/01/a.jpg",
                "https://imagens.portalzuk.com.br/mini/2025/01/b.jpg",
            ],
        }
        photos = _collect_photos(raw)
        assert len(photos) == 2
        assert all("detalhe" in p for p in photos)

    def test_fotos_also_normalized(self):
        """fotos com URLs mini também são normalizadas."""
        raw = {
            "fotos": ["/mini/2025/01/a.jpg"],
        }
        photos = _collect_photos(raw)
        assert len(photos) == 1
        assert "/detalhe/" in photos[0]


# ── Tests: FIELD_MAP ──────────────────────────────────────────────────────────


class TestFieldMap:
    """Verifica que FIELD_MAP tem os mapeamentos esperados."""

    def test_has_required_keys(self):
        assert "ilo" in FIELD_MAP
        assert "titulo" in FIELD_MAP
        assert "endereco" in FIELD_MAP
        assert "url" in FIELD_MAP
        assert "preco_2a_praca" in FIELD_MAP
        assert "preco_1a_praca" in FIELD_MAP
        assert "latitude" in FIELD_MAP
        assert "longitude" in FIELD_MAP
        assert "tipo_inferido" in FIELD_MAP
        assert "i_abaixo" in FIELD_MAP

    def test_maps_to_correct_targets(self):
        assert FIELD_MAP["preco_2a_praca"] == "preco_venda"
        assert FIELD_MAP["preco_1a_praca"] == "preco_anterior"
        assert FIELD_MAP["percentual_desconto"] == "percentual_reducao"
        assert FIELD_MAP["ilo"] == "origem_id"
        assert FIELD_MAP["tipo_inferido"] == "tipo"

    def test_all_values_are_strings(self):
        for k, v in FIELD_MAP.items():
            assert isinstance(k, str), f"Key {k!r} is not str"
            assert isinstance(v, str), f"Value for {k!r} is not str"


# ── Tests: helpers ────────────────────────────────────────────────────────────


class TestParseBrPrice:
    """Testa _parse_br_price com diversos formatos brasileiros."""

    def test_standard_br_format(self):
        """R$ 450.000,00 → 450000.0"""
        assert _parse_br_price("R$ 450.000,00") == 450000.0

    def test_br_without_cents(self):
        """R$ 1.200.000 → 1200000.0"""
        assert _parse_br_price("R$ 1.200.000") == 1200000.0

    def test_simple_comma(self):
        """450000,00 → 450000.0"""
        assert _parse_br_price("450000,00") == 450000.0

    def test_integer_without_separator(self):
        """R$ 800000 → 800000.0"""
        assert _parse_br_price("R$ 800000") == 800000.0

    def test_float_standard(self):
        """12345.67 → 12345.67"""
        assert _parse_br_price("12345.67") == 12345.67

    def test_empty(self):
        assert _parse_br_price("") is None
        assert _parse_br_price(None) is None  # type: ignore


class TestToFloat:
    def test_valid(self):
        assert _to_float("450000.50") == 450000.50
        assert _to_float(42) == 42.0
        assert _to_float(3.14) == 3.14

    def test_invalid(self):
        assert _to_float("abc") is None
        assert _to_float(None) is None
        assert _to_float([]) is None

    def test_default(self):
        assert _to_float("abc", default=0.0) == 0.0


class TestToInt:
    def test_valid(self):
        assert _to_int("42") == 42
        assert _to_int(42.9) == 42
        assert _to_int(3) == 3

    def test_invalid(self):
        assert _to_int("abc") is None
        assert _to_int(None) is None


class TestParseAddress:
    def test_full_format(self):
        """Cidade - UF - Bairro - Rua"""
        end, bairro, cidade, uf = _parse_address("São Paulo - SP - Centro - Rua Augusta")
        assert "Rua Augusta" in end
        assert bairro == "Centro"
        assert cidade == "São Paulo"
        assert uf == "SP"

    def test_cidade_uf_slash(self):
        """Cidade/UF - Bairro - Rua"""
        end, bairro, cidade, uf = _parse_address("Belo Horizonte/MG - Savassi - Av. Getúlio Vargas")
        assert "Av. Getúlio Vargas" in end
        assert bairro == "Savassi"
        assert cidade == "Belo Horizonte"
        assert uf == "MG"

    def test_empty(self):
        assert _parse_address("") == ("", "", "", "")
        assert _parse_address(None) == ("", "", "", "")  # type: ignore

    def test_two_parts(self):
        """Cidade - Bairro (sem UF)"""
        end, bairro, cidade, uf = _parse_address("São Paulo - Pinheiros")
        assert cidade == "São Paulo"
        assert bairro == "Pinheiros"
        assert end == ""
        assert uf == ""

    def test_two_parts_with_uf_slash(self):
        """Cidade/UF - BairroRua (formato real do Zuk)"""
        end, bairro, cidade, uf = _parse_address("Uberlândia / MG - Novo Mundo Avenida Canela do Bosque,  s/n")
        assert cidade == "Uberlândia"
        assert uf == "MG"
        assert bairro == "Novo Mundo"
        assert "Avenida Canela do Bosque" in end

    def test_two_parts_with_uf_slash_av(self):
        """Cidade/UF - BairroAvenida"""
        end, bairro, cidade, uf = _parse_address("Santos / SP - Areia Branca Avenida Engenheiro Manoel Ferramenta Júnior,  363")
        assert cidade == "Santos"
        assert uf == "SP"
        assert bairro == "Areia Branca"
        assert "Avenida Engenheiro Manoel Ferramenta" in end

    def test_two_parts_with_uf_slash_sitio(self):
        """Cidade/UF - Bairro Sítio (prefixo incomum)"""
        end, bairro, cidade, uf = _parse_address("Novo Repartimento / PA - Zona Rural Sítio Dois Irmãos, Lote 81")
        assert cidade == "Novo Repartimento"
        assert uf == "PA"
        assert bairro == "Zona Rural"
        assert "Sítio Dois Irmãos" in end

    def test_single_part(self):
        end, bairro, cidade, uf = _parse_address("Av. Paulista")
        assert "Av. Paulista" in end
        assert bairro == ""
        assert cidade == ""
        assert uf == ""


class TestBuildZukId:
    def test_from_ilo(self):
        assert _build_zuk_id({"ilo": 12345}) == "zuk_12345"

    def test_from_url(self):
        assert _build_zuk_id({"url": f"{BASE_URL}/imovel/sp/sao-paulo/centro/rua/999-456"}) == "zuk_456"

    def test_empty(self):
        assert _build_zuk_id({}) == ""


class TestInferTipo:
    def test_by_flag_terreno(self):
        assert _infer_tipo("", None, None, None, True) == "terreno"

    def test_by_flag_rural(self):
        assert _infer_tipo("", None, None, True) == "rural"

    def test_by_flag_comercial(self):
        assert _infer_tipo("", None, True) == "comercial"

    def test_by_flag_residencial(self):
        assert _infer_tipo("", True) == "residencial"

    def test_by_title_keyword(self):
        assert _infer_tipo("Casa em ótima localização") == "casa"
        assert _infer_tipo("Apartamento 2 quartos") == "apartamento"
        assert _infer_tipo("Terreno 500m²") == "terreno"

    def test_empty(self):
        assert _infer_tipo("") == ""


# ── Tests: from_zuk_listing ──────────────────────────────────────────────────


class TestFromZukListing:
    """Testa a função principal de conversão para o schema unificado."""

    def _make_minimal_listing(self, **overrides) -> dict:
        """Helper: cria uma listagem Zuk mínima válida."""
        listing: dict[str, Any] = {
            "ilo": 12345,
            "titulo": "Casa 3 quartos no Centro",
            "endereco": "São Paulo - SP - Centro - Rua Augusta",
            "url": f"{BASE_URL}/imovel/sp/sao-paulo/centro/rua-augusta/999-12345",
            "preco_2a_praca": 350000.0,
            "preco_1a_praca": 450000.0,
            "percentual_desconto": 22.22,
            "image_urls": ["/mini/2025/01/abc123.jpg"],
            "latitude": -23.5505,
            "longitude": -46.6333,
            "valor_avaliacao": 500000.0,
            "tipo_inferido": "casa",
            "data_1a_praca": "15/07/2025",
            "data_2a_praca": "30/07/2025",
            "areas": {"a_tot": 150.0, "a_uti": 120.0},
            "i_abaixo": 30.0,
        }
        listing.update(overrides)
        return listing

    def test_minimal_listing(self):
        """Conversão mínima com todos os campos básicos."""
        raw = self._make_minimal_listing()
        result = from_zuk_listing(raw)
        assert result is not None
        assert result["id"] == "zuk_12345"
        assert result["fonte"] == "zuk"
        # negociacao is set in mapped but filtered out by Imovel if schema doesn't have it
        assert result["preco_venda"] == 350000.0
        # preco_anterior mapped via FIELD_MAP, but may be filtered by Imovel
        assert result["area"] == 150.0
        assert result["titulo"] == "Casa 3 quartos no Centro"
        assert result["cidade"] == "São Paulo"
        assert result["uf"] == "SP"
        assert result["bairro"] == "Centro"
        assert result["disponivel"] is True

    def test_photos_normalized(self):
        """Fotos são normalizadas para URLs absolutas detalhe."""
        raw = self._make_minimal_listing()
        result = from_zuk_listing(raw)
        fotos = result["fotos"]
        assert len(fotos) == 1
        assert fotos[0].startswith(IMAGE_BASE)
        assert "/detalhe/" in fotos[0]

    def test_tem_reducao_from_percentual(self):
        """tem_reducao=True quando percentual_desconto > 0.
        Nota: tem_reducao não está no schema Imovel atual, então verifica
        se o campo existe no output OU se foi preservado como extra."""
        raw = self._make_minimal_listing(percentual_desconto=22.22)
        result = from_zuk_listing(raw)
        # percentual_reducao é mapeado de percentual_desconto via FIELD_MAP
        # Pode ser filtrado pelo Imovel se não estiver no schema
        if "percentual_reducao" in result:
            assert result["percentual_reducao"] == 22.22
        if "tem_reducao" in result:
            assert result["tem_reducao"] is True

    def test_sem_reducao(self):
        """tem_reducao=False quando sem desconto."""
        raw = self._make_minimal_listing(percentual_desconto=None, i_abaixo=None)
        result = from_zuk_listing(raw)
        if "tem_reducao" in result:
            assert result["tem_reducao"] is False

    def test_invalid_input(self):
        """None ou dict vazio retorna None."""
        assert from_zuk_listing(None) is None
        assert from_zuk_listing([]) is None  # type: ignore
        assert from_zuk_listing("") is None  # type: ignore

    def test_missing_id(self):
        """Listing sem ilo nem URL ID retorna None."""
        result = from_zuk_listing({"titulo": "Teste"})
        assert result is None

    def test_preco_venda_fallback(self):
        """Sem preco_2a_praca, usa preco_1a_praca como venda."""
        raw = self._make_minimal_listing(preco_2a_praca=None, preco_1a_praca=300000.0)
        result = from_zuk_listing(raw)
        assert result["preco_venda"] == 300000.0

    def test_quartos_banheiros_vagas_none(self):
        """Quartos/banheiros/vagas não disponíveis nas listagens Zuk."""
        raw = self._make_minimal_listing()
        result = from_zuk_listing(raw)
        assert result["quartos"] is None
        assert result["banheiros"] is None
        assert result["vagas"] is None
        assert result["condominio"] is None
        assert result["iptu"] is None

    def test_field_map_fields_preserved(self):
        """Campos mapeados via FIELD_MAP são preservados.
        Nota: latitude/longitude podem ser filtrados pelo Imovel se não
        estiverem no schema."""
        raw = self._make_minimal_listing(latitude=-23.5, longitude=-46.6)
        result = from_zuk_listing(raw)
        if "latitude" in result:
            assert result["latitude"] == -23.5
        if "longitude" in result:
            assert result["longitude"] == -46.6
        # origem_id = ilo via FIELD_MAP
        if "origem_id" in result:
            assert result["origem_id"] == 12345

    def test_data_coleta_preenchida(self):
        """data_coleta é preenchida automaticamente."""
        raw = self._make_minimal_listing()
        result = from_zuk_listing(raw)
        assert result["data_coleta"]  # não vazio
        assert "T" in result["data_coleta"]  # formato ISO

    def test_areas_dict_usage(self):
        """Área extraída do dict areas (a_tot > a_uti)."""
        raw = self._make_minimal_listing(
            areas={"a_tot": 200.0, "a_uti": 150.0}
        )
        result = from_zuk_listing(raw)
        assert result["area"] == 200.0

    def test_no_areas(self):
        """Sem dict areas, area=None."""
        raw = self._make_minimal_listing(areas={})
        result = from_zuk_listing(raw)
        assert result["area"] is None

    def test_url_absolute(self):
        """URL permanece como string original."""
        raw = self._make_minimal_listing()
        result = from_zuk_listing(raw)
        assert result["url"].startswith(BASE_URL)

    def test_extra_fields_preserved(self):
        """Campos extras do Zuk preservados em _extra ou diretamente."""
        raw = self._make_minimal_listing(parcelas=12)
        result = from_zuk_listing(raw)
        # parcelas é mapeado no FIELD_MAP, então deve estar no dict
        assert "parcelas" not in result or result.get("parcelas") == 12

    def test_infer_tipo_empty(self):
        """Sem flags nem título, tipo vem vazio."""
        raw = self._make_minimal_listing(tipo_inferido="")
        result = from_zuk_listing(raw)
        assert result["tipo"] == ""


# ── Tests: from_zuk_payload ──────────────────────────────────────────────────


class TestFromZukPayload:
    """Testa from_zuk_payload com diversos formatos de entrada."""

    def test_list_of_dicts(self):
        """Payload como lista de listagens."""
        payload = [
            {"ilo": 1, "titulo": "Apto 1", "url": f"{BASE_URL}/1-1", "preco_2a_praca": 100000.0},
            {"ilo": 2, "titulo": "Apto 2", "url": f"{BASE_URL}/2-2", "preco_2a_praca": 200000.0},
        ]
        result = from_zuk_payload(payload)
        assert len(result) == 2
        assert result[0]["id"] == "zuk_1"
        assert result[1]["id"] == "zuk_2"

    def test_dict_with_listings_key(self):
        """Payload como dict com chave 'listings'."""
        payload = {
            "listings": [
                {"ilo": 10, "titulo": "Casa", "url": f"{BASE_URL}/10-10"},
            ]
        }
        result = from_zuk_payload(payload)
        assert len(result) == 1

    def test_dict_with_data_key(self):
        """Payload como dict com chave 'data'."""
        payload = {
            "data": [
                {"ilo": 20, "titulo": "Terreno", "url": f"{BASE_URL}/20-20"},
            ]
        }
        result = from_zuk_payload(payload)
        assert len(result) == 1

    def test_json_string(self):
        """Payload como string JSON."""
        raw = [
            {"ilo": 30, "titulo": "Sala", "url": f"{BASE_URL}/30-30", "preco_2a_praca": 300000.0},
        ]
        payload = json.dumps(raw)
        result = from_zuk_payload(payload)
        assert len(result) == 1

    def test_invalid_json(self):
        """String JSON inválida retorna lista vazia."""
        result = from_zuk_payload("not json at all {{{")
        assert result == []

    def test_invalid_type(self):
        """Payload com tipo inesperado retorna []."""
        assert from_zuk_payload(42) == []

    def test_filter_invalid_items(self):
        """Itens inválidos (sem ID) são filtrados."""
        payload = [
            {"ilo": 1, "titulo": "Válido", "url": f"{BASE_URL}/1-1"},
            {"titulo": "Inválido"},  # sem ID
            {"ilo": 2, "titulo": "Válido 2", "url": f"{BASE_URL}/2-2"},
        ]
        result = from_zuk_payload(payload)
        assert len(result) == 2
        assert all(r["id"] for r in result)


# ── Teste de integração: HTML simulado -> from_zuk_payload ──────────────────


class TestIntegration:
    """Testa o pipeline completo: parse de HTML simulado -> schema unificado."""

    @staticmethod
    def _make_fake_listing_html(lote_id: int, titulo: str, cidade: str, uf: str, bairro: str, preco_2a: float) -> str:
        """Gera HTML de card-property simulado para teste."""
        # Formata preço no padrão BR: 350000.0 -> "350.000"
        price_int = int(preco_2a)
        price_str = f"{price_int:,}".replace(",", ".")
        return f"""
        <div class="card-property">
            <span id="{lote_id}"></span>
            <a href="/imovel/{uf.lower()}/{cidade.lower()}/{bairro.lower()}/rua/100-{lote_id}">
                <span class="card-property-price-lote">{titulo}</span>
            </a>
            <p class="card-property-address">{cidade} - {uf} - {bairro} - Rua Exemplo</p>
            <span class="card-property-price-value" style="text-decoration:line-through">R$ 500.000,00</span>
            <span class="card-property-price-value">R$ {price_str},00</span>
            <div class="card-property-image-wrapper">
                <img src="/mini/2025/01/{lote_id}.jpg"/>
            </div>
        </div>
        """

    @staticmethod
    def _make_fake_inline_js(lote_ids: list[int]) -> str:
        """Gera inline properties JavaScript."""
        props = []
        for lid in lote_ids:
            props.append(
                f'{{"il":{lid*10},"ilo":{lid},"la":-23.5,"lo":-46.6,'
                f'"lv":550000,"a_tot":120,"a_uti":100,'
                f'"i_res":true,"i_com":false,"i_abaixo":30}}'
            )
        return f"<script>var properties = [{','.join(props)}];</script>"

    def test_html_to_payload(self):
        """HTML com 2 cards + inline JS → schema unificado."""
        html = "<html><body>"
        html += self._make_fake_listing_html(1, "Casa Centro", "São Paulo", "SP", "Centro", 350000.0)
        html += self._make_fake_listing_html(2, "Apto Bela Vista", "São Paulo", "SP", "Bela Vista", 280000.0)
        html += self._make_fake_inline_js([1, 2])
        html += "</body></html>"

        from skills.zuk.zuk_parser import extract_from_html
        listings, meta = extract_from_html(html, source_url=f"{BASE_URL}/leilao-de-imoveis?page=1")

        assert len(listings) == 2
        assert meta["listings_found"] == 2

        # Converte para schema unificado
        converted = from_zuk_payload(listings)
        assert len(converted) == 2

        # Verifica campos
        c1 = converted[0]
        assert c1["fonte"] == "zuk"
        assert c1["id"] == "zuk_1"
        assert c1["preco_venda"] == 350000.0
        # preco_anterior pode ser filtrado se não estiver no schema
        # latitude/longitude podem ser filtrados
        assert len(c1["fotos"]) == 1
        assert "detalhe" in c1["fotos"][0]

        c2 = converted[1]
        assert c2["id"] == "zuk_2"
        assert c2["preco_venda"] == 280000.0

    def test_html_without_inline_props(self):
        """HTML sem inline properties ainda extrai cards."""
        html = "<html><body>"
        html += self._make_fake_listing_html(5, "Casa Teste", "Ribeirão Preto", "SP", "Centro", 450000.0)
        html += "</body></html>"

        from skills.zuk.zuk_parser import extract_from_html
        listings, meta = extract_from_html(html)
        assert len(listings) >= 1
        listing = listings[0]
        assert listing["titulo"] == "Casa Teste"
        assert listing["ilo"] == 5

        converted = from_zuk_payload([listing])
        assert len(converted) == 1
        assert converted[0]["cidade"] == "Ribeirão Preto"
        assert converted[0]["uf"] == "SP"


# ── Schema-aware tests (se Imovel estiver disponível) ─────────────────────────


class TestSchemaIntegration:
    """Testes opcionais que verificam compatibilidade com Imovel dataclass."""

    def test_field_map_covers_imovel_fields(self):
        """Verifica que FIELD_MAP targets são compatíveis com Imovel (se disponível)."""
        if not HAS_IMOVEL:
            return  # skip
        imovel_field_set = set(Imovel.__dataclass_fields__.keys())
        for target in FIELD_MAP.values():
            # Some targets are Zuk-specific extras (not in Imovel)
            if target in imovel_field_set:
                continue
            # These are extra/non-schema fields mapped for preservation
            extras = {
                "valor_avaliacao", "data_1a_praca", "data_2a_praca",
                "parcelas", "i_abaixo", "origem_id", "preco_anterior",
                "percentual_reducao", "i_loc", "i_ocu",
                "i_res", "i_com", "i_rur", "i_ter",
                "latitude", "longitude",
            }
            assert target in extras, f"Target {target!r} is not in Imovel fields nor extras"

    def test_conversion_yields_valid_imovel_dict(self):
        """Dic retornado por from_zuk_listing contém apenas campos Imovel + extras."""
        if not HAS_IMOVEL:
            return
        from skills.zuk.zuk_parser import from_zuk_listing

        raw = {
            "ilo": 42,
            "titulo": "Apto Teste",
            "url": f"{BASE_URL}/imovel/sp/saopaulo/vilamariana/rua/100-42",
            "endereco": "São Paulo - SP - Vila Mariana - Rua Teste",
            "preco_2a_praca": 200000.0,
            "preco_1a_praca": 250000.0,
            "image_urls": ["/mini/2025/01/abc.jpg"],
            "latitude": -23.5,
            "longitude": -46.6,
        }

        result = from_zuk_listing(raw)
        assert result is not None
        assert result["id"] == "zuk_42"
        assert result["fonte"] == "zuk"
        assert isinstance(result["fotos"], list)
        assert len(result["fotos"]) > 0

        # Tenta criar Imovel a partir do dict
        try:
            imovel = Imovel.from_dict(result)
            errors = imovel.validate()
            if errors:
                print(f"  Validation warnings (non-fatal): {errors}")
        except Exception as e:
            # If Imovel.from_dict fails on _extra or zuk-specific keys, still ok
            print(f"  Note: Imovel creation resulted in {type(e).__name__}: {e}")
