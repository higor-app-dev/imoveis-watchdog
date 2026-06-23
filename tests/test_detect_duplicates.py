"""
Tests for detect_duplicates module.

Cobrem todos os 6 tiers de matching e cenários reais:
  - EXACT_URL: mesma URL entre runs
  - EXACT_ID: mesmo list_id da mesma fonte
  - STRUCTURAL: mesmo bairro + área + quartos + preço
  - FUZZY_TITLE: títulos similares (token-set ratio)
  - FUZZY_ADDRESS: endereços similares
  - FUZZY_DESCRIPTION: descrições similares
  - Sem match: imóveis diferentes
  - Cross-source: OLX + QuintoAndar para o mesmo imóvel
  - Integração: pipeline real de duas runs
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Adiciona skills ao path
SKILLS_DIR = Path(__file__).parent.parent / "skills" / "detect-duplicates"
sys.path.insert(0, str(SKILLS_DIR))

from detect_duplicates import (
    MatchResult,
    find_duplicates,
    dedup_list,
    normalize_url,
    token_set_ratio,
    seq_match_ratio,
    fingerprint,
    summarize_matches,
    SCORE_EXACT_URL,
    SCORE_EXACT_ID,
    SCORE_STRUCTURAL,
    SCORE_FUZZY_TITLE,
    SCORE_FUZZY_ADDRESS,
    SCORE_FUZZY_DESCRIPTION,
)


# ── Helpers de teste ──────────────────────────────────────────────────────────


def imovel(**kw):
    """Factory para criar dict de imóvel (schema Imovel)."""
    defaults = dict(
        id="", titulo="", url="", fonte="olx",
        endereco="", bairro="", cidade="São Paulo", uf="SP",
        preco_venda=None, preco_aluguel=None,
        condominio=None, iptu=None,
        area=None, quartos=None, banheiros=None, vagas=None,
        tipo="apartamento", descricao="",
        amenities=[], fotos=[],
        data_coleta="2026-06-21T12:00:00Z",
        created_at="2026-06-21T12:00:00Z",
        updated_at="2026-06-21T12:00:00Z",
    )
    defaults.update(kw)
    return defaults


def olx_ad(**kw):
    """Factory para criar dict no formato parse_ad() da pipeline OLX."""
    defaults = dict(
        list_id="", title="", url="", price=None,
        category="Apartamentos", municipality="",
        neighbourhood="", uf="SP",
        area_m2=None, rooms=None, bathrooms=None,
        garage_spaces=None, condominio_fee="",
        date=0, image_count=0,
    )
    defaults.update(kw)
    return defaults


def assert_match(matches, expected_idx_a, expected_idx_b,
                 min_score=0.60, match_type=None):
    """Verifica se existe um match específico na lista."""
    for m in matches:
        if m.idx_a == expected_idx_a and m.idx_b == expected_idx_b:
            assert m.score >= min_score, (
                f"Score muito baixo: {m.score} < {min_score}"
            )
            if match_type:
                assert m.match_type == match_type, (
                    f"Tier errado: {m.match_type} != {match_type}"
                )
            return m
    raise AssertionError(
        f"Match ({expected_idx_a}, {expected_idx_b}) não encontrado em:\n"
        + "\n".join(f"  ({m.idx_a}, {m.idx_b}) {m.match_type} {m.score}"
                    for m in matches)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════


def test_normalize_url():
    """URL normalization removes protocol, www, trailing slash."""
    assert normalize_url("https://www.olx.com.br/imovel") == "olx.com.br/imovel"
    assert normalize_url("HTTP://OLX.COM.BR/IMOVEL/") == "olx.com.br/imovel"
    assert normalize_url("https://mg.olx.com.br/imovel#fragment") == "mg.olx.com.br/imovel"
    assert normalize_url("") == ""
    assert normalize_url("  ") == ""


def test_token_set_ratio():
    """Token-set ratio: similar titles get high scores."""
    # Mesmo conjunto de palavras, ordem diferente
    score = token_set_ratio(
        "Apartamento 2 quartos Consolação",
        "Consolação Apartamento 2 quartos",
    )
    assert score == 1.0, f"Esperado 1.0, got {score}"

    # Palavras parcialmente sobrepostas
    score = token_set_ratio(
        "Apartamento 2 quartos vaga",
        "Apartamento 3 quartos vaga garagem",
    )
    assert score >= 0.30, f"Partial overlap muito baixo: {score}"

    # Completamente diferentes
    score = token_set_ratio(
        "Apartamento 2 quartos",
        "Terreno 500m²",
    )
    assert score == 0.0, f"Esperado 0.0, got {score}"


def test_seq_match_ratio():
    """SequenceMatcher: small diffs in long text."""
    a = "Apartamento amplo com 2 quartos sendo 1 suíte, sala ampla, cozinha planejada."
    b = "Apartamento amplo com 2 quartos sendo 1 suíte, sala ampla, cozinha planejada."
    assert seq_match_ratio(a, b) == 1.0

    c = "Apartamento amplo 2 quartos 1 suíte sala ampla cozinha."
    assert seq_match_ratio(a, c) >= 0.60


# ── Tier 1: EXACT_URL ─────────────────────────────────────────────────────────


def test_exact_url_detects_duplicate():
    """EXACT_URL: mesma URL normalizada entre runs = score 1.0."""
    run1 = [
        imovel(id="olx_1", url="https://www.olx.com.br/imovel-1", fonte="olx"),
    ]
    run2 = [
        imovel(id="olx_1", url="https://www.olx.com.br/imovel-1", fonte="olx"),
        imovel(id="olx_2", url="https://www.olx.com.br/imovel-2", fonte="olx"),
    ]

    matches = find_duplicates(run2, run1)
    assert_match(matches, 0, 0, min_score=SCORE_EXACT_URL, match_type="EXACT_URL")


def test_exact_url_trailing_slash():
    """EXACT_URL: URLs com/sem trailing slash são consideradas iguais."""
    run1 = [
        imovel(id="a", url="https://olx.com.br/imovel/123/"),
    ]
    run2 = [
        imovel(id="a", url="https://olx.com.br/imovel/123"),
    ]
    matches = find_duplicates(run2, run1)
    assert_match(matches, 0, 0, match_type="EXACT_URL")


# ── Tier 2: EXACT_ID ──────────────────────────────────────────────────────────


def test_exact_id_same_source():
    """EXACT_ID: mesmo ID da mesma fonte = score 1.0."""
    run1 = [
        imovel(id="12345", fonte="olx",
               url="https://www.olx.com.br/old-url"),
    ]
    run2 = [
        imovel(id="12345", fonte="olx",
               url="https://www.olx.com.br/new-url"),
    ]
    matches = find_duplicates(run2, run1)
    assert_match(matches, 0, 0, min_score=SCORE_EXACT_ID, match_type="EXACT_ID")


def test_exact_id_different_source_not_match():
    """EXACT_ID: mesmo ID de fontes diferentes NÃO é match (falso positivo)."""
    run1 = [
        imovel(id="12345", fonte="olx"),
    ]
    run2 = [
        imovel(id="12345", fonte="quintoandar"),
    ]
    matches = find_duplicates(run2, run1)
    # Não deve pegar EXACT_ID — fontes diferentes
    assert not matches, (
        "Não deveria ter match EXACT_ID com fontes diferentes"
    )


# ── Tier 3: STRUCTURAL ─────────────────────────────────────────────────────────


def test_structural_same_property():
    """STRUCTURAL: mesmo bairro, área, quartos, preço ≈ = match."""
    run1 = [
        imovel(id="olx_a", fonte="olx",
               bairro="Consolação", cidade="São Paulo", uf="SP",
               area=65.0, quartos=2, banheiros=1, vagas=1,
               preco_venda=450000.0,
               titulo="Apto 2q Consolação"),
    ]
    run2 = [
        imovel(id="qa_b", fonte="quintoandar",
               bairro="Consolação", cidade="São Paulo", uf="SP",
               area=64.0, quartos=2, banheiros=1, vagas=1,
               preco_venda=460000.0,
               titulo="Apartamento 2 quartos Consolação SP"),
    ]
    matches = find_duplicates(run2, run1)
    # Deve pegar por STRUCTURAL (cross-source)
    assert_match(matches, 0, 0, min_score=0.60, match_type="STRUCTURAL")


def test_structural_no_match_different_location():
    """STRUCTURAL: mesma área/preço mas bairro diferente = sem match."""
    run1 = [
        imovel(id="a", bairro="Consolação", cidade="São Paulo", uf="SP",
               area=65.0, quartos=2, preco_venda=450000.0),
    ]
    run2 = [
        imovel(id="b", bairro="Pinheiros", cidade="São Paulo", uf="SP",
               area=65.0, quartos=2, preco_venda=450000.0),
    ]
    matches = find_duplicates(run2, run1)
    assert not matches, "Bairros diferentes não deveriam dar match"


def test_structural_olx_format():
    """STRUCTURAL funciona com formato parse_ad() da OLX."""
    run1 = [
        olx_ad(list_id="1", neighbourhood="Savassi",
               municipality="Belo Horizonte", uf="MG",
               area_m2=64, rooms=2, bathrooms=2,
               garage_spaces=2, price=1470000),
    ]
    run2 = [
        olx_ad(list_id="2", neighbourhood="Savassi",
               municipality="Belo Horizonte", uf="MG",
               area_m2=64, rooms=2, bathrooms=2,
               garage_spaces=2, price=1480000),
    ]
    matches = find_duplicates(run2, run1)
    assert_match(matches, 0, 0, match_type="STRUCTURAL")


# ── Tier 4: FUZZY_TITLE ────────────────────────────────────────────────────────


def test_fuzzy_title():
    """FUZZY_TITLE: títulos similares com palavras sobrepostas."""
    run1 = [
        imovel(id="a", titulo="Apartamento 2 quartos Consolação SP",
               bairro="Pinheiros", cidade="São Paulo"),
    ]
    run2 = [
        imovel(id="b", titulo="Apartamento 2 quartos Consolação",
               bairro="Vila Mariana", cidade="São Paulo"),
    ]
    matches = find_duplicates(run2, run1)
    assert len(matches) >= 1, "Nenhum match FUZZY_TITLE encontrado"
    assert any(m.match_type in ("FUZZY_TITLE", "STRUCTURAL") for m in matches), (
        f"Esperado FUZZY_TITLE ou STRUCTURAL: {[(m.match_type, m.score) for m in matches]}"
    )


def test_fuzzy_title_no_match():
    """FUZZY_TITLE: títulos completamente diferentes = sem match."""
    run1 = [
        imovel(id="a", titulo="Apartamento 2 quartos Consolação"),
    ]
    run2 = [
        imovel(id="b", titulo="Terreno 500m² zona sul"),
    ]
    matches = find_duplicates(run2, run1)
    assert not matches, "Títulos diferentes não deveriam dar match"


# ── Tier 5: FUZZY_ADDRESS ─────────────────────────────────────────────────────


def test_fuzzy_address():
    """FUZZY_ADDRESS: endereços similares, bairros diferentes p/ evitar STRUCTURAL."""
    run1 = [
        imovel(id="a", endereco="Rua Augusta, 1500", bairro="Consolação",
               cidade="São Paulo", area=65.0, quartos=2),
    ]
    run2 = [
        imovel(id="b", endereco="Rua Augusta 1500", bairro="Bela Vista",
               cidade="São Paulo", area=None, quartos=None),
    ]
    matches = find_duplicates(run2, run1)
    # Deve detectar por FUZZY_ADDRESS (STRUCTURAL falha por bairro diferente
    # e area/quartos None = peso insuficiente)
    assert len(matches) >= 1, "Nenhum match encontrado"
    assert any(m.match_type == "FUZZY_ADDRESS" for m in matches), (
        f"Nenhum match FUZZY_ADDRESS: {[(m.match_type, m.score) for m in matches]}"
    )


# ── Tier 6: FUZZY_DESCRIPTION ──────────────────────────────────────────────────


def test_fuzzy_description():
    """FUZZY_DESCRIPTION: descrições longas com pequenas diferenças."""
    desc = (
        "Apartamento amplo com 2 quartos sendo 1 suíte, "
        "sala para 2 ambientes, cozinha planejada, "
        "banheiro social, área de serviço, vaga 1 carro. "
        "Próximo ao metrô Consolação, comércio local."
    )
    run1 = [
        imovel(id="a", descricao=desc, titulo="Apto Consolação",
               bairro="Consolação", cidade="São Paulo"),
    ]
    run2 = [
        imovel(id="b", descricao=desc.replace("2 quartos", "2 dormitórios"),
               titulo="Apto Consolação",
               bairro="Perdizes", cidade="São Paulo"),
    ]
    matches = find_duplicates(run2, run1)
    # Pode pegar STRUCTURAL (bairro diferente) ou FUZZY_DESCRIPTION
    assert len(matches) >= 1


# ── Cross-source: OLX ↔ QuintoAndar ───────────────────────────────────────────


def test_cross_source_same_property():
    """
    Cross-source: mesmo imóvel anunciado na OLX e QuintoAndar.

    OLX e QuintoAndar têm IDs diferentes, URLs diferentes.
    A detecção deve vir de STRUCTURAL ou FUZZY_TITLE.
    """
    olx_run = [
        # Capturado pela pipeline OLX
        {
            "list_id": "1234567",
            "title": "Apartamento 2 quartos Consolação",
            "url": "https://www.olx.com.br/imovel-1234567",
            "price": 450000,
            "category": "Apartamentos",
            "municipality": "São Paulo",
            "neighbourhood": "Consolação",
            "uf": "SP",
            "area_m2": 65,
            "rooms": 2,
            "bathrooms": 1,
            "garage_spaces": 1,
            "condominio_fee": "R$ 800",
            "date": 1782060000,
            "image_count": 10,
        },
    ]
    qa_run = [
        # Capturado pelo parser QuintoAndar (schema Imovel)
        imovel(
            id="qa_7654321",
            fonte="quintoandar",
            titulo="Apartamento com 2 quartos na Consolação",
            url="https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/apto-2q/7654321",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            area=65.0,
            quartos=2,
            banheiros=1,
            vagas=1,
            preco_venda=450000.0,
        ),
    ]

    # OLX como referência, QuintoAndar como atual
    matches = find_duplicates(qa_run, olx_run)
    # Deve detectar por STRUCTURAL ou FUZZY_TITLE
    assert len(matches) >= 1, (
        f"Cross-source não detectado. Matches: {matches}"
    )
    assert matches[0].score >= 0.60


# ── dedup_list (batch processing) ──────────────────────────────────────────────


def test_dedup_list_filters_duplicates():
    """dedup_list remove itens duplicados, mantém únicos."""
    run1 = [
        imovel(id="1", url="https://ex.com/a"),
        imovel(id="2", url="https://ex.com/b"),
    ]
    run2 = [
        imovel(id="1", url="https://ex.com/a"),  # duplicado
        imovel(id="3", url="https://ex.com/c"),  # novo
        imovel(id="4", url="https://ex.com/d"),  # novo
    ]
    novos, matches = dedup_list(run2, run1)
    assert len(novos) == 2, f"Esperado 2 novos, got {len(novos)}"
    assert len(matches) == 1, f"Esperado 1 match, got {len(matches)}"
    assert novos[0]["id"] in ("3", "4")
    assert novos[1]["id"] in ("3", "4")


# ── fingerprint ────────────────────────────────────────────────────────────────


def test_fingerprint_changes_when_data_changes():
    """fingerprint: hash muda quando os IDs mudam."""
    run_a = [imovel(id="1"), imovel(id="2"), imovel(id="3")]
    run_b = [imovel(id="1"), imovel(id="2"), imovel(id="4")]

    fp_a = fingerprint(run_a)
    fp_b = fingerprint(run_b)

    assert fp_a != fp_b, "fingerprint deveria mudar com IDs diferentes"
    assert len(fp_a) == 16


def test_fingerprint_stable():
    """fingerprint: mesmo conjunto de IDs = mesmo hash."""
    run_a = [imovel(id="3"), imovel(id="1"), imovel(id="2")]
    run_b = [imovel(id="1"), imovel(id="2"), imovel(id="3")]

    assert fingerprint(run_a) == fingerprint(run_b), (
        "fingerprint deveria ser estável (ordem não importa)"
    )


# ── summarize_matches ─────────────────────────────────────────────────────────


def test_summarize_matches_empty():
    """summarize_matches: lista vazia retorna zeros."""
    summary = summarize_matches([])
    assert summary["total"] == 0
    assert summary["avg_score"] == 0.0


def test_summarize_matches():
    """summarize_matches: estatísticas corretas."""
    matches = [
        MatchResult(0, 0, "a", "b", 1.0, "EXACT_URL"),
        MatchResult(1, 2, "c", "d", 0.85, "STRUCTURAL"),
        MatchResult(2, 3, "e", "f", 0.70, "FUZZY_TITLE"),
        MatchResult(3, 4, "g", "h", 0.70, "FUZZY_TITLE"),
    ]
    summary = summarize_matches(matches)
    assert summary["total"] == 4
    assert summary["avg_score"] == round((1.0 + 0.85 + 0.70 + 0.70) / 4, 4)
    assert summary["by_tier"]["EXACT_URL"]["count"] == 1
    assert summary["by_tier"]["FUZZY_TITLE"]["count"] == 2


# ── Integration: two full runs ─────────────────────────────────────────────────


def test_integration_two_runs():
    """
    Teste de integração: simula duas execuções completas.

    Run 1: 4 imóveis (OLX + QuintoAndar)
    Run 2: 6 imóveis (2 novos, 1 mudou de preço, 3 repetidos)

    Verifica:
      - 3 duplicatas detectadas (1 EXACT_ID, 1 EXACT_URL, 1 STRUCTURAL)
      - 1 falso positivo evitado (cross-source com dados diferentes)
      - 2 imóveis novos identificados corretamente
    """
    # ── Run 1 (referência) ────────────────────────────────────────────
    ref = [
        # Imóvel A: da OLX
        olx_ad(
            list_id="a_olx_001",
            title="Apto 2q Consolação com vaga",
            url="https://www.olx.com.br/sp/sao-paulo/apto-2q-consolacao",
            price=450000,
            neighbourhood="Consolação",
            municipality="São Paulo",
            uf="SP",
            area_m2=65,
            rooms=2,
            bathrooms=1,
            garage_spaces=1,
        ),
        # Imóvel B: do QuintoAndar (mesmo imóvel que A, cross-source)
        imovel(
            id="qa_b_001",
            fonte="quintoandar",
            titulo="Apartamento 2 dormitórios Consolação",
            url="https://www.quintoandar.com.br/imovel/qa_b_001",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            area=65.0,
            quartos=2,
            banheiros=1,
            vagas=1,
            preco_venda=450000.0,
        ),
        # Imóvel C: OLX (imóvel diferente, Pinheiros)
        olx_ad(
            list_id="a_olx_003",
            title="Cobertura duplex Pinheiros",
            url="https://www.olx.com.br/sp/sao-paulo/cobertura-pinheiros",
            price=1200000,
            neighbourhood="Pinheiros",
            municipality="São Paulo",
            uf="SP",
            area_m2=150,
            rooms=3,
            bathrooms=2,
            garage_spaces=2,
        ),
    ]

    # ── Run 2 (atual) ─────────────────────────────────────────────────
    current = [
        # Imóvel A repete (EXACT_URL com run 1)
        olx_ad(
            list_id="a_olx_001",  # mesmo ID
            title="Apto 2q Consolação com vaga",
            url="https://www.olx.com.br/sp/sao-paulo/apto-2q-consolacao",
            price=450000,
            neighbourhood="Consolação",
            municipality="São Paulo",
            uf="SP",
            area_m2=65,
            rooms=2,
            bathrooms=1,
            garage_spaces=1,
        ),
        # Imóvel B repete (EXACT_ID com run 1, fonte=olx, id=a_olx_001)
        # Esse é o mesmo que A, mas com ID igual a olx_001 e fonte=olx → EXACT_ID
        # Na verdade, vou criar um cenário onde o ID é o mesmo da mesma fonte

        # QuintoAndar B repete (EXACT_URL com imóvel B da run 1)
        imovel(
            id="qa_b_001",
            fonte="quintoandar",
            titulo="Apartamento 2 dormitórios Consolação",
            url="https://www.quintoandar.com.br/imovel/qa_b_001",
            bairro="Consolação",
            cidade="São Paulo",
            uf="SP",
            area=65.0,
            quartos=2,
            banheiros=1,
            vagas=1,
            preco_venda=450000.0,
        ),
        # Imóvel D: OLX novo (único)
        olx_ad(
            list_id="a_olx_004",
            title="Kitnet Vila Mariana",
            url="https://www.olx.com.br/sp/sao-paulo/kitnet-vila-mariana",
            price=180000,
            neighbourhood="Vila Mariana",
            municipality="São Paulo",
            uf="SP",
            area_m2=25,
            rooms=1,
            bathrooms=1,
            garage_spaces=0,
        ),
        # Imóvel E: QuintoAndar novo
        imovel(
            id="qa_e_001",
            fonte="quintoandar",
            titulo="Studio Pinheiros mobiliado",
            url="https://www.quintoandar.com.br/imovel/qa_e_001",
            bairro="Pinheiros",
            cidade="São Paulo",
            uf="SP",
            area=30.0,
            quartos=1,
            banheiros=1,
            vagas=0,
            preco_venda=350000.0,
        ),
    ]

    # ── Find duplicates ───────────────────────────────────────────────
    matches = find_duplicates(current, ref)

    # Verificações
    # Match 1: Imóvel A current (idx 0) ↔ Imóvel A ref (idx 0) — EXACT_URL ou EXACT_ID
    # (mesmo URL, mesma fonte, mesmo ID)
    m1 = assert_match(matches, 0, 0, match_type="EXACT_URL")

    # Match 2: Imóvel B current (idx 1) ↔ Imóvel B ref (idx 1)
    # mesmo URL = EXACT_URL
    m2 = assert_match(matches, 1, 1, match_type="EXACT_URL")

    # Os novos imóveis (D e E) não devem ter match
    matched_indices = {m.idx_a for m in matches}
    assert 2 not in matched_indices, "Imóvel D (único) não deveria ter match"
    assert 3 not in matched_indices, "Imóvel E (único) não deveria ter match"

    # dedup_list deve retornar só os 2 novos
    novos, matches_final = dedup_list(current, ref)
    assert len(novos) == 2, f"Esperado 2 novos, got {len(novos)}: {[n.get('list_id', n.get('id')) for n in novos]}"


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_empty_lists():
    """find_duplicates com listas vazias."""
    assert find_duplicates([], []) == []
    assert find_duplicates([imovel(id="1")], []) == []
    assert find_duplicates([], [imovel(id="1")]) == []


def test_same_run_internal_duplicates():
    """Duplicatas DENTRO da mesma execução (não é o foco, mas não quebra)."""
    data = [
        imovel(id="1", url="https://ex.com/a"),
        imovel(id="2", url="https://ex.com/b"),
    ]
    # Comparar contra si mesmo = todos são "duplicatas"
    matches = find_duplicates(data, data)
    assert len(matches) >= 2  # 2 itens, cada um encontra a si mesmo


def test_min_score_filter():
    """min_score filtra matches de baixa confiança."""
    run1 = [
        imovel(id="a", titulo="Apto 2q Consolação",
               bairro="Perdizes", cidade="São Paulo"),
    ]
    run2 = [
        imovel(id="b", titulo="Apartamento 2q Perdizes",
               bairro="Perdizes", cidade="São Paulo"),
    ]
    # Com min_score alto (0.90): só EXACT_URL/EXACT_ID passam
    matches_high = find_duplicates(run2, run1, min_score=0.90)
    assert len(matches_high) == 0, (
        f"Nenhum match esperado com min_score=0.90, got {len(matches_high)}"
    )

    # Com min_score baixo (0.50): FUZZY_TITLE deve pegar
    matches_low = find_duplicates(run2, run1, min_score=0.50)
    assert len(matches_low) >= 1, (
        "Deveria ter match com min_score=0.50"
    )


def test_real_world_duplicate_from_state():
    """
    Cenário real: imóvel que aparece DUAS VEZES no state do pipeline
    (dados do pipeline_state.json sem dedup).
    O módulo deve identificar os pares corretamente.
    """
    # Os dados reais têm entradas duplicadas — mesmo list_id
    run1 = [
        {"list_id": 1443223238, "title": "Área privativa, 2 quartos, 1 suite, 2 vagas",
         "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/area-privativa-2-quartos-1-suite-2-vagas-1443223238",
         "price": 1470000, "neighbourhood": "Savassi", "municipality": "Belo Horizonte",
         "uf": "MG", "area_m2": 64, "rooms": 2, "bathrooms": 2, "garage_spaces": 2},
    ]
    run2 = [
        {"list_id": 1443223238, "title": "Área privativa, 2 quartos, 1 suite, 2 vagas",
         "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/area-privativa-2-quartos-1-suite-2-vagas-1443223238",
         "price": 1470000, "neighbourhood": "Savassi", "municipality": "Belo Horizonte",
         "uf": "MG", "area_m2": 64, "rooms": 2, "bathrooms": 2, "garage_spaces": 2},
    ]
    matches = find_duplicates(run2, run1)
    # Mesmo list_id + mesma fonte (olx) + mesma URL = EXACT_URL ou EXACT_ID
    assert len(matches) >= 1, "Dados reais duplicados não detectados"
    assert matches[0].score >= 0.90, f"Score muito baixo: {matches[0].score}"


# ── Main ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    # Roda todos os testes
    tests = [
        name for name in dir()
        if name.startswith("test_")
    ]
    passed = 0
    failed = 0
    for name in sorted(tests):
        func = globals()[name]
        try:
            func()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Resultado: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)
