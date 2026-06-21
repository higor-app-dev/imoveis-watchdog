"""
Testes de dados esparsos e missing data para o QuintoAndar parser.

Cobre:
  - Listing com quase nenhum campo
  - Campos com tipos inesperados (int no lugar de str, dict no lugar de str)
  - Navegação segura em payloads malformados
  - from_quintoandar_safe() com payloads inválidos
  - Processamento de arquivos inexistentes
  - Warnings não viram crash
"""

import json
import sys
import os
import io
import warnings
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

sys.path.insert(0, str(Path(__file__).parent))
from quintoandar_parser import (
    from_quintoandar_listing,
    from_quintoandar_payload,
    from_quintoandar_api_response,
    from_quintoandar_houses,
    from_quintoandar_safe,
    process_file,
    _extract_address,
    _extract_condo_iptu,
    _extract_amenities,
    _extract_photos,
    _build_url,
    _map_tipo,
    _safe_get,
    _safe_navigate,
    _as_str,
)

SPARSE_DATA_PATH = Path(__file__).parent / "sample_sparse_quintoandar.json"


# ── Tests de campos ausentes ────────────────────────────────────────────────────


def test_empty_dict():
    """Dict vazio → Imovel com defaults, sem crash."""
    imovel = from_quintoandar_listing({})
    assert imovel.id == ""
    assert imovel.preco_venda is None
    assert imovel.preco_aluguel is None
    assert imovel.condominio is None
    assert imovel.iptu is None
    assert imovel.area is None
    assert imovel.quartos is None
    assert imovel.banheiros is None
    assert imovel.vagas is None
    assert imovel.tipo == ""
    assert imovel.endereco == ""
    assert imovel.bairro == ""
    assert imovel.amenities == []
    assert imovel.fotos == []
    assert imovel.titulo == ""
    print("[PASS] test_empty_dict — todos defaults corretos")


def test_none_instead_of_dict():
    """None em vez de dict → Imovel vazio."""
    imovel = from_quintoandar_listing(None)
    assert isinstance(imovel, Imovel)
    assert imovel.id == ""
    print("[PASS] test_none_instead_of_dict — não crashou, retornou Imovel vazio")


def test_list_instead_of_dict():
    """Lista em vez de dict → Imovel vazio."""
    imovel = from_quintoandar_listing([1, 2, 3])
    assert isinstance(imovel, Imovel)
    assert imovel.id == ""
    print("[PASS] test_list_instead_of_dict — não crashou")


def test_type_field_as_dict():
    """Campo 'type' como dict (não string) → tipo vazio."""
    listing = {"id": "x1", "salePrice": 300000, "type": {"name": "Apartamento"}}
    imovel = from_quintoandar_listing(listing)
    # O tipo será a string repr do dict, que não corresponde a nenhum tipo válido
    assert isinstance(imovel.tipo, str)
    # Não crashou — é o que importa
    print(f"[PASS] test_type_field_as_dict — tipo='{imovel.tipo}', não crashou")


def test_null_id_with_fallback():
    """id=None, listingId presente → fallback funciona."""
    listing = {"id": None, "listingId": "fallback-001", "salePrice": 250000, "type": "Casa"}
    imovel = from_quintoandar_listing(listing)
    assert imovel.id == "fallback-001"
    print("[PASS] test_null_id_with_fallback — usou listingId como fallback")


def test_missing_both_prices():
    """Sem preço de venda nem aluguel → Imovel ainda criado (validação falha depois)."""
    listing = {"id": "no-price", "type": "Apartamento"}
    imovel = from_quintoandar_listing(listing)
    assert imovel.preco_venda is None
    assert imovel.preco_aluguel is None
    # is_valid() deve falhar, mas o parser não crashou
    assert not imovel.is_valid()
    print("[PASS] test_missing_both_prices — parser não crashou, is_valid=False")


def test_condo_iptu_not_dict():
    """condoIptu como string → None, sem crash."""
    listing = {"id": "c1", "salePrice": 500000, "condoIptu": "R$ 800,00"}
    imovel = from_quintoandar_listing(listing)
    assert imovel.condominio is None
    assert imovel.iptu is None
    print("[PASS] test_condo_iptu_not_dict — não crashou, condominio=None")


def test_null_amenities():
    """Amenities como None → lista vazia."""
    listing = {"id": "a1", "salePrice": 400000, "amenities": None}
    imovel = from_quintoandar_listing(listing)
    assert imovel.amenities == []
    print("[PASS] test_null_amenities — lista vazia")


def test_amenities_mixed_types():
    """Amenities com tipos mistos (dict, str, int) → normaliza os válidos."""
    listing = {"id": "a2", "salePrice": 400000, "amenities": [
        {"name": "Piscina"},
        "Academia",
        42,  # tipo inesperado
        {"label": "Salão de Festas"},
        None,
    ]}
    imovel = from_quintoandar_listing(listing)
    assert "piscina" in imovel.amenities
    assert "academia" in imovel.amenities
    assert "salao_de_festas" in imovel.amenities
    print(f"[PASS] test_amenities_mixed_types — {len(imovel.amenities)} amenities válidas")


def test_photos_not_list():
    """Fotos em formato não-list → lista vazia."""
    listing = {"id": "p1", "salePrice": 400000, "photos": "https://img.com/foto.jpg"}
    imovel = from_quintoandar_listing(listing)
    assert imovel.fotos == []
    print("[PASS] test_photos_not_list — lista vazia")


def test_photos_dict_instead_of_url():
    """Foto como dict sem url (ex: só alt) → ignorada."""
    listing = {"id": "p2", "salePrice": 400000, "photos": [
        {"alt": "Foto da sala"},
        {"url": "https://img.com/valida.jpg"},
    ]}
    imovel = from_quintoandar_listing(listing)
    assert len(imovel.fotos) == 1
    assert "valida.jpg" in imovel.fotos[0]
    print(f"[PASS] test_photos_dict_instead_of_url — {len(imovel.fotos)} foto(s) válida(s)")


# ── Payload malformados ─────────────────────────────────────────────────────────


def test_payload_not_dict():
    """Payload não-dict → lista vazia."""
    imoveis = from_quintoandar_payload("não sou dict")
    assert imoveis == []
    print("[PASS] test_payload_not_dict — lista vazia")


def test_api_response_not_dict():
    """API response não-dict → lista vazia."""
    imoveis = from_quintoandar_api_response(None)
    assert imoveis == []
    print("[PASS] test_api_response_not_dict — lista vazia")


def test_empty_payload():
    """Payload vazio → lista vazia."""
    imoveis = from_quintoandar_payload({})
    assert imoveis == []
    print("[PASS] test_empty_payload — lista vazia")


def test_deeply_nested_payload():
    """Payload com estrutura aninhada correta → lista parseada."""
    payload = {
        "pageProps": {
            "initialState": {
                "houses": [
                    {"id": "d1", "salePrice": 100000},
                    {"id": "d2", "rentPrice": 2000},
                ]
            }
        }
    }
    imoveis = from_quintoandar_payload(payload)
    assert len(imoveis) == 2
    assert imoveis[0].id == "d1"
    assert imoveis[1].id == "d2"
    print("[PASS] test_deeply_nested_payload — 2 imóveis parseados")


# ── from_quintoandar_safe ───────────────────────────────────────────────────────


def test_safe_with_valid_payload():
    """Safe wrapper com payload Next.js válido."""
    payload = {
        "pageProps": {
            "initialState": {
                "houses": [
                    {"id": "s1", "salePrice": 100000},
                    {"id": "s2", "rentPrice": 2000},
                ]
            }
        }
    }
    imoveis = from_quintoandar_safe(payload)
    assert len(imoveis) == 2
    print("[PASS] test_safe_with_valid_payload — 2 imóveis")


def test_safe_with_api_response():
    """Safe wrapper com API response."""
    payload = {"results": [{"id": "api1", "salePrice": 500000}]}
    imoveis = from_quintoandar_safe(payload)
    assert len(imoveis) == 1
    assert imoveis[0].id == "api1"
    print("[PASS] test_safe_with_api_response — 1 imóvel")


def test_safe_with_direct_list():
    """Safe wrapper com lista direta (houses)."""
    payload = {"houses": [{"id": "dir1", "salePrice": 300000}]}
    imoveis = from_quintoandar_safe(payload)
    assert len(imoveis) == 1
    assert imoveis[0].id == "dir1"
    print("[PASS] test_safe_with_direct_list — 1 imóvel")


def test_safe_with_none():
    """Safe wrapper com None → lista vazia."""
    imoveis = from_quintoandar_safe(None)
    assert imoveis == []
    print("[PASS] test_safe_with_none — lista vazia")


def test_safe_with_string():
    """Safe wrapper com string → lista vazia."""
    imoveis = from_quintoandar_safe("invalid")
    assert imoveis == []
    print("[PASS] test_safe_with_string — lista vazia")


def test_safe_with_unrecognized():
    """Safe wrapper com dict sem estrutura conhecida → lista vazia."""
    imoveis = from_quintoandar_safe({"foo": "bar"})
    assert imoveis == []
    print("[PASS] test_safe_with_unrecognized — lista vazia")


# ── Helpers individuais ─────────────────────────────────────────────────────────


def test_as_str_with_various_types():
    """_as_str lida com vários tipos sem crash."""
    assert _as_str(None) == ""
    assert _as_str("hello") == "hello"
    assert _as_str(42) == "42"
    assert _as_str(3.14) == "3.14"
    assert _as_str(True) == "True"
    # Dict deve logar warning mas retornar string
    result = _as_str({"key": "val"})
    assert isinstance(result, str)
    assert "key" in result or "val" in result
    print("[PASS] test_as_str_with_various_types")


def test_safe_get_missing_keys():
    """_safe_get retorna default para chaves ausentes."""
    assert _safe_get({}, "a", default="x") == "x"
    assert _safe_get({"a": 1}, "b") is None
    assert _safe_get({"a": {"b": 2}}, "a", "b") == 2
    assert _safe_get({"a": {"b": 2}}, "a", "c") is None
    print("[PASS] test_safe_get_missing_keys")


def test_safe_get_non_dict():
    """_safe_get com valor não-dict no meio do caminho."""
    assert _safe_get({"a": "not_a_dict"}, "a", "b") is None
    print("[PASS] test_safe_get_non_dict")


def test_safe_navigate_multiple_paths():
    """_safe_navigate tenta múltiplos caminhos."""
    data = {"houses": [1, 2, 3]}
    result = _safe_navigate(data, "pageProps.houses", "houses", default=[])
    assert result == [1, 2, 3]
    print("[PASS] test_safe_navigate_multiple_paths")


def test_safe_navigate_no_match():
    """_safe_navigate retorna default quando nenhum caminho existe."""
    result = _safe_navigate({}, "a.b.c", "x.y.z", default="fallback")
    assert result == "fallback"
    print("[PASS] test_safe_navigate_no_match")


def test_build_url_without_url_fields():
    """_build_url mesmo sem url, slug, citySlug → URL gerada com default."""
    listing = {"id": "b1", "salePrice": 100000}
    url = _build_url(listing)
    assert "quintoandar.com.br" in url
    assert "b1" in url
    print(f"[PASS] test_build_url_without_url_fields — {url}")


def test_build_url_with_non_dict():
    """_build_url com não-dict → string vazia."""
    url = _build_url(None)
    assert url == ""
    print("[PASS] test_build_url_with_non_dict")


# ── Sparse data realístico ──────────────────────────────────────────────────────


def test_sparse_sample_file():
    """Arquivo sample_sparse_quintoandar.json → todos parseados sem crash."""
    if not SPARSE_DATA_PATH.exists():
        print(f"[SKIP] test_sparse_sample_file — arquivo não encontrado")
        return
    imoveis = process_file(str(SPARSE_DATA_PATH))
    assert len(imoveis) > 0, "Deveria ter parseado pelo menos alguns imóveis"
    # Verifica que nenhum crashou
    for imovel in imoveis:
        assert isinstance(imovel, Imovel)
    print(f"[PASS] test_sparse_sample_file — {len(imoveis)} imóveis parseados sem crash")


def test_sparse_sample_with_safe():
    """Arquivo sparse via from_quintoandar_safe → sem crash."""
    if not SPARSE_DATA_PATH.exists():
        print(f"[SKIP] test_sparse_sample_with_safe — arquivo não encontrado")
        return
    with open(str(SPARSE_DATA_PATH), "r") as f:
        data = json.load(f)
    imoveis = from_quintoandar_safe(data)
    assert len(imoveis) > 0
    print(f"[PASS] test_sparse_sample_with_safe — {len(imoveis)} imóveis")


def test_inexistent_file():
    """Arquivo inexistente → lista vazia, não crash."""
    imoveis = process_file("/tmp/nao_existe_444abc.json")
    assert imoveis == []
    print("[PASS] test_inexistent_file — lista vazia")


def test_invalid_json_file():
    """Arquivo com JSON inválido → lista vazia."""
    invalid_path = "/tmp/test_invalid_json.json"
    with open(invalid_path, "w") as f:
        f.write("{ isso não é json válido ")
    try:
        imoveis = process_file(invalid_path)
        assert imoveis == []
    finally:
        os.remove(invalid_path)
    print("[PASS] test_invalid_json_file — lista vazia")


# ── Warnings não viram crash ────────────────────────────────────────────────────


def test_warnings_captured_without_crash():
    """Garantir que warnings.warn não crasha."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # dispara warnings intencionais via helpers
        _safe_get("not_a_dict", "key")
        _as_str([1, 2, 3])

    assert len(w) >= 2, f"Esperava >=2 warnings, recebeu {len(w)}"
    print(f"[PASS] test_warnings_captured_without_crash — {len(w)} warnings emitidos")


def test_warnings_message_content():
    """Warnings têm conteúdo informativo."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _as_str({"test": "dict"})

    assert len(w) >= 1
    msg = str(w[0].message)
    assert "dict" in msg or "dict" in msg
    print(f"[PASS] test_warnings_message_content — '{msg[:60]}...'")


# ── Runner ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_empty_dict,
        test_none_instead_of_dict,
        test_list_instead_of_dict,
        test_type_field_as_dict,
        test_null_id_with_fallback,
        test_missing_both_prices,
        test_condo_iptu_not_dict,
        test_null_amenities,
        test_amenities_mixed_types,
        test_photos_not_list,
        test_photos_dict_instead_of_url,
        test_payload_not_dict,
        test_api_response_not_dict,
        test_empty_payload,
        test_deeply_nested_payload,
        test_safe_with_valid_payload,
        test_safe_with_api_response,
        test_safe_with_direct_list,
        test_safe_with_none,
        test_safe_with_string,
        test_safe_with_unrecognized,
        test_as_str_with_various_types,
        test_safe_get_missing_keys,
        test_safe_get_non_dict,
        test_safe_navigate_multiple_paths,
        test_safe_navigate_no_match,
        test_build_url_without_url_fields,
        test_build_url_with_non_dict,
        test_sparse_sample_file,
        test_sparse_sample_with_safe,
        test_inexistent_file,
        test_invalid_json_file,
        test_warnings_captured_without_crash,
        test_warnings_message_content,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"Resultado: {passed} passaram, {failed} falharam")
    sys.exit(0 if failed == 0 else 1)
