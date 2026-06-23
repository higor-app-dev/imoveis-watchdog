"""
Testes para o sistema de registro config-driven de portais.

Cobre:
  - Carregamento de config YAML
  - Dynamic module resolution (import por arquivo)
  - PortalInfo dataclass e helpers
  - from_listing() para QuintoAndar, Loft e Zap (mock)
  - from_payload() para todos os portais
  - build_search_url()
  - Cache de módulos
  - Error handling (portal inexistente, função faltando, config inválida)
  - Compatibilidade reversa: parsers existentes importáveis diretamente
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path.home() / ".hermes"))
sys.path.insert(0, str(Path.home() / "imoveis-watchdog"))

from imovel_schema import Imovel
from skills.portal_registry import (
    load_portals,
    get_portal,
    list_active_portals,
    resolve_parser,
    get_parser_function,
    call_parser,
    from_listing,
    from_payload,
    build_search_url,
    invalidate_cache,
    PortalInfo,
    DEFAULT_CONFIG_PATH,
    REPO_ROOT,
)

# ── Helpers ────────────────────────────────────────────────────────────────

TEST_DATA_DIR = Path(__file__).resolve().parent.parent / "tests"


def make_portal_yaml(extra: str = "") -> str:
    """Gera YAML de configuração com portais reais + extra opcional."""
    return f"""
portals:
  quinto_andar:
    name: "quintoandar"
    display_name: "QuintoAndar"
    parser_module: "skills.quinto_andar.quintoandar_parser"
    base_url: "https://www.quintoandar.com.br"
    enabled: true
    auth: {{}}
    functions:
      parse_listing: "from_quintoandar_listing"
      parse_payload: "from_quintoandar_payload"

  loft:
    name: "loft"
    display_name: "Loft"
    parser_module: "skills.loft.loft_parser"
    base_url: "https://www.loft.com.br"
    enabled: true
    auth: {{}}
    functions:
      parse_listing: "from_loft_listing"
      parse_payload: "from_loft_payload"
{extra}
"""


# ── Dados de exemplo ──────────────────────────────────────────────────────

QA_LISTING = {
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
    "forSale": True,
    "title": "Apartamento 3 quartos em Santana",
}

LOFT_LISTING = {
    "id": "ino0ntno",
    "title": "Cobertura Duplex 4 quartos — Jardim Guedala",
    "url": "https://loft.com.br/imovel/ino0ntno",
    "salePrice": 35950000,
    "area": 1200,
    "bedrooms": 4,
    "bathrooms": 8,
    "parkingSpots": 10,
    "type": "Cobertura",
    "address": {
        "street": "Rua Albertina de Oliveira Godinho",
        "neighborhood": "Jardim Guedala",
        "city": "São Paulo",
        "stateCode": "SP",
    },
}

ZAP_LISTING = {
    "codigo": "zap98765",
    "titulo": "Apartamento 2 quartos no Centro",
    "url": "https://www.zapimoveis.com.br/imovel/zap98765",
    "preco": 450000,
    "area": 65,
    "quartos": 2,
    "banheiros": 1,
    "vagas": 1,
    "tipo": "apartamento",
    "bairro": "Centro",
    "cidade": "São Paulo",
    "uf": "SP",
}

ZAP_CONFIG = """
  zap_mock:
    name: "zap"
    display_name: "Zap (mock)"
    parser_module: "skills.zap.zap_parser"
    base_url: "https://www.zapimoveis.com.br"
    enabled: true
    auth: {}
    functions:
      parse_listing: "from_zap_listing"
      parse_payload: "from_zap_payload"
      build_url: "build_zap_url"
"""


# ══════════════════════════════════════════════════════════════════════════
# TESTES
# ══════════════════════════════════════════════════════════════════════════


class TestLoadConfig:
    """Carregamento e parsing do YAML de portais."""

    def setup_method(self):
        invalidate_cache()

    def test_load_default_path(self):
        """Carrega config do path padrão (config/portals.yaml)."""
        portals = load_portals()
        assert "quinto_andar" in portals
        assert "loft" in portals
        assert len(portals) >= 2

    def test_load_custom_path(self):
        """Carrega config de um arquivo temporário."""
        content = make_portal_yaml()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            portals = load_portals(tmp_path)
            assert "quinto_andar" in portals
            assert "loft" in portals
        finally:
            os.unlink(tmp_path)

    def test_load_missing_file(self):
        """FileNotFoundError se o YAML não existir."""
        import pytest
        with pytest.raises(FileNotFoundError):
            load_portals("/tmp/nonexistent_portals.yaml")

    def test_load_invalid_yaml(self):
        """ValueError se faltar chave 'portals'."""
        import pytest
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("not_portals:\n  foo: bar\n")
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="portals"):
                load_portals(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_portal_info_defaults(self):
        """PortalInfo preenche defaults corretamente."""
        p = PortalInfo(
            slug="teste",
            name="teste",
            display_name="Teste",
            parser_module="mod.x",
            base_url="https://teste.com",
        )
        assert p.enabled is True
        assert p.auth == {}
        assert p.functions == {}
        assert p.can_parse_listing is False
        assert p.can_parse_payload is False
        assert p.has_build_url is False


class TestPortalLookup:
    """Lookup de portais por slug."""

    def setup_method(self):
        invalidate_cache()
        load_portals()

    def test_get_portal_exists(self):
        """get_portal retorna PortalInfo para slug válido."""
        p = get_portal("quinto_andar")
        assert p.slug == "quinto_andar"
        assert p.name == "quintoandar"
        assert p.display_name == "QuintoAndar"
        assert p.base_url == "https://www.quintoandar.com.br"
        assert p.enabled is True
        assert p.can_parse_listing is True
        assert p.can_parse_payload is True

    def test_get_portal_not_found(self):
        """KeyError para slug inexistente."""
        import pytest
        with pytest.raises(KeyError, match="nonexistent"):
            get_portal("nonexistent")

    def test_list_active_portals(self):
        """list_active_portals retorna apenas portais enabled=True."""
        active = list_active_portals()
        slugs = [p.slug for p in active]
        assert "quinto_andar" in slugs
        assert "loft" in slugs


class TestDynamicResolver:
    """Import dinâmico de módulos parser."""

    def setup_method(self):
        invalidate_cache()
        load_portals()

    def test_resolve_quinto_andar(self):
        """Resolve quinto_andar por caminho de arquivo (diretório com hífen)."""
        mod = resolve_parser("quinto_andar")
        assert mod.__name__ == "quintoandar_parser"
        assert hasattr(mod, "from_quintoandar_listing")
        assert hasattr(mod, "from_quintoandar_payload")

    def test_resolve_loft(self):
        """Resolve loft por import padrão."""
        mod = resolve_parser("loft")
        assert hasattr(mod, "from_loft_listing")
        assert hasattr(mod, "from_loft_payload")

    def test_resolve_cache(self):
        """Módulo importado é cacheado."""
        mod1 = resolve_parser("quinto_andar")
        mod2 = resolve_parser("quinto_andar")
        assert mod1 is mod2

    def test_resolve_with_zap(self):
        """Resolve o mock Zap quando configurado com ele."""
        # Carrega config que inclui Zap
        content = make_portal_yaml(ZAP_CONFIG)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            invalidate_cache()
            load_portals(tmp_path)
            mod = resolve_parser("zap_mock")
            assert hasattr(mod, "from_zap_listing")
            assert hasattr(mod, "from_zap_payload")
            assert hasattr(mod, "build_zap_url")
        finally:
            os.unlink(tmp_path)

    def test_get_parser_function(self):
        """get_parser_function retorna a função correta do módulo."""
        fn = get_parser_function("quinto_andar", "parse_listing")
        assert fn.__name__ == "from_quintoandar_listing"

        fn2 = get_parser_function("loft", "parse_payload")
        assert fn2.__name__ == "from_loft_payload"

    def test_get_parser_function_missing_key(self):
        """KeyError para chave de função não configurada."""
        import pytest
        with pytest.raises(KeyError, match="nonexistent_func"):
            get_parser_function("quinto_andar", "nonexistent_func")


class TestFromListing:
    """Conversão de listagem individual para Imovel via registry."""

    def setup_method(self):
        invalidate_cache()
        load_portals()

    def test_quinto_andar_listing(self):
        """from_listing quinto_andar produz Imovel válido."""
        imovel = from_listing("quinto_andar", QA_LISTING)
        assert isinstance(imovel, Imovel)
        assert imovel.id == "892820623"
        assert imovel.fonte == "quintoandar"
        assert imovel.preco_venda == 1000000
        assert imovel.bairro == "Santana"
        assert imovel.cidade == "São Paulo"
        assert imovel.uf == "SP"
        assert imovel.area == 105
        assert imovel.quartos == 3
        assert imovel.is_valid()

    def test_loft_listing(self):
        """from_listing loft produz Imovel válido."""
        imovel = from_listing("loft", LOFT_LISTING)
        assert isinstance(imovel, Imovel)
        assert imovel.id == "ino0ntno"
        assert imovel.fonte == "loft"
        assert imovel.preco_venda == 35950000
        assert imovel.area == 1200
        assert imovel.bairro == "Jardim Guedala"
        assert imovel.is_valid()

    def test_zap_listing(self):
        """from_listing zap_mock produz Imovel válido."""
        content = make_portal_yaml(ZAP_CONFIG)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            invalidate_cache()
            load_portals(tmp_path)
            imovel = from_listing("zap_mock", ZAP_LISTING)
            assert isinstance(imovel, Imovel)
            assert imovel.id == "zap98765"
            assert imovel.fonte == "zap"
            assert imovel.preco_venda == 450000
            assert imovel.bairro == "Centro"
            assert imovel.cidade == "São Paulo"
            assert imovel.uf == "SP"
            assert imovel.area == 65
            assert imovel.quartos == 2
            assert imovel.is_valid()
        finally:
            os.unlink(tmp_path)


class TestFromPayload:
    """Conversão de payload de busca para lista de Imovel."""

    def setup_method(self):
        invalidate_cache()
        load_portals()

    def test_quinto_andar_payload(self):
        """from_payload quinto_andar com Next.js data route."""
        payload = {"pageProps": {"initialState": {"houses": [QA_LISTING]}}}
        imoveis = from_payload("quinto_andar", payload)
        assert len(imoveis) == 1
        assert imoveis[0].id == "892820623"

    def test_loft_payload(self):
        """from_payload loft com array de listings."""
        payload = {"listings": [LOFT_LISTING]}
        imoveis = from_payload("loft", payload)
        assert len(imoveis) == 1
        assert imoveis[0].id == "ino0ntno"

    def test_zap_payload(self):
        """from_payload zap_mock com results."""
        content = make_portal_yaml(ZAP_CONFIG)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            invalidate_cache()
            load_portals(tmp_path)

            # results direto
            imoveis = from_payload("zap_mock", {"results": [ZAP_LISTING]})
            assert len(imoveis) == 1
            assert imoveis[0].id == "zap98765"

            # listings alternativo
            imoveis2 = from_payload("zap_mock", {"listings": [ZAP_LISTING]})
            assert len(imoveis2) == 1

            # payload vazio
            imoveis3 = from_payload("zap_mock", {})
            assert imoveis3 == []
        finally:
            os.unlink(tmp_path)

    def test_quinto_andar_empty_payload(self):
        """Payload vazio do QuintoAndar retorna lista vazia."""
        imoveis = from_payload("quinto_andar", {})
        assert imoveis == []


class TestBuildSearchURL:
    """Construção de URLs de busca via registry."""

    def setup_method(self):
        invalidate_cache()

    def test_zap_build_url(self):
        """build_search_url com zap_mock que tem build_url configurada."""
        content = make_portal_yaml(ZAP_CONFIG)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            invalidate_cache()
            load_portals(tmp_path)
            url = build_search_url("zap_mock", cidade="sao-paulo", bairro="centro")
            assert "zapimoveis" in url
            assert "centro" in url
        finally:
            os.unlink(tmp_path)

    def test_build_url_not_configured(self):
        """KeyError se o portal não tiver build_url configurada."""
        import pytest
        invalidate_cache()
        load_portals()
        with pytest.raises(KeyError, match="build_url"):
            build_search_url("quinto_andar")


class TestErrorHandling:
    """Tratamento de erros no registry."""

    def setup_method(self):
        invalidate_cache()
        load_portals()

    def test_invalid_slug_from_listing(self):
        """KeyError para slug inválido em from_listing."""
        import pytest
        with pytest.raises(KeyError, match="nonexistent"):
            from_listing("nonexistent", {})

    def test_disabled_portal_in_active(self):
        """Portal desabilitado não aparece em list_active_portals."""
        content = make_portal_yaml(
            """
  disabled_test:
    name: "disabled"
    display_name: "Disabled"
    parser_module: "skills.zap.zap_parser"
    base_url: "https://test.com"
    enabled: false
    functions:
      parse_listing: "from_zap_listing"
"""
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            invalidate_cache()
            load_portals(tmp_path)
            active = list_active_portals()
            slugs = [p.slug for p in active]
            assert "disabled_test" not in slugs
        finally:
            os.unlink(tmp_path)


class TestReverseCompatibility:
    """Parsers existentes continuam funcionando como imports diretos."""

    def test_quintoandar_direct_import(self):
        """quintoandar_parser importável diretamente."""
        sys.path.insert(0, str(REPO_ROOT / "skills" / "quinto-andar"))
        from quintoandar_parser import (
            from_quintoandar_listing,
            from_quintoandar_payload,
        )
        imovel = from_quintoandar_listing(QA_LISTING)
        assert isinstance(imovel, Imovel)
        assert imovel.id == "892820623"
        assert imovel.fonte == "quintoandar"

    def test_loft_direct_import(self):
        """loft_parser importável diretamente."""
        sys.path.insert(0, str(REPO_ROOT / "skills" / "loft"))
        from loft_parser import from_loft_listing, from_loft_payload
        imovel = from_loft_listing(LOFT_LISTING)
        assert isinstance(imovel, Imovel)
        assert imovel.id == "ino0ntno"
        assert imovel.fonte == "loft"

    def test_zap_direct_import(self):
        """zap_parser importável diretamente."""
        sys.path.insert(0, str(REPO_ROOT / "skills" / "zap"))
        from zap_parser import from_zap_listing
        imovel = from_zap_listing(ZAP_LISTING)
        assert isinstance(imovel, Imovel)
        assert imovel.id == "zap98765"
        assert imovel.fonte == "zap"
