"""
Testes de validação para o módulo validacao.py e schema Imovel.

Cobre:
  - Validação de cada regra individualmente (preço, área, ID, tipo, fonte, URL, timestamps)
  - Múltiplos erros simultâneos
  - Validação em lote (validar_lote)
  - Relatório resumido e JSON
  - Casos de borda (None, lista vazia, dict mínimo)
"""

from __future__ import annotations

import json
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

sys.path.insert(0, str(Path(__file__).parent))
from validacao import (
    validar_imovel,
    validar_lote,
    relatorio_resumido,
    relatorio_json,
    ResultadoValidacao,
    RelatorioValidacao,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────


def imovel_valido(**kwargs) -> Imovel:
    """Retorna Imovel válido com valores padrão, sobrescritos por kwargs."""
    base = {
        "id": "test_001",
        "fonte": "quintoandar",
        "preco_venda": 450000.0,
        "area": 65.0,
        "quartos": 2,
        "banheiros": 1,
        "vagas": 1,
        "tipo": "apartamento",
        "uf": "SP",
        "url": "https://www.quintoandar.com.br/comprar/imovel/123",
    }
    base.update(kwargs)
    return Imovel(**base)


# ═══════════════════════════════════════════════════════════════════════════════
# Testes individuais — cada regra
# ═══════════════════════════════════════════════════════════════════════════════


def test_valido():
    """Imóvel completo e válido → 0 erros."""
    imv = imovel_valido()
    erros = imv.validate()
    assert len(erros) == 0, f"Esperado 0 erros, recebeu {erros}"
    assert imv.is_valid()
    print("[PASS] test_valido — 0 erros")


def test_preco_venda_zero():
    """preco_venda = 0 → erro."""
    imv = imovel_valido(preco_venda=0.0)
    erros = imv.validate()
    assert any("preco_venda" in e and "positivo" in e for e in erros), \
        f"Deveria rejeitar preco_venda=0: {erros}"
    print(f"[PASS] test_preco_venda_zero — erros: {erros}")


def test_preco_venda_negativo():
    """preco_venda negativo → erro."""
    imv = imovel_valido(preco_venda=-100.0)
    erros = imv.validate()
    assert any("preco_venda" in e and "positivo" in e for e in erros), \
        f"Deveria rejeitar preco_venda negativo: {erros}"
    print(f"[PASS] test_preco_venda_negativo — erros: {erros}")


def test_preco_aluguel_zero():
    """preco_aluguel = 0 → erro."""
    imv = imovel_valido(preco_venda=None, preco_aluguel=0.0)
    erros = imv.validate()
    assert any("preco_aluguel" in e and "positivo" in e for e in erros), \
        f"Deveria rejeitar preco_aluguel=0: {erros}"
    print(f"[PASS] test_preco_aluguel_zero — erros: {erros}")


def test_area_zero():
    """area = 0 → erro."""
    imv = imovel_valido(area=0.0)
    erros = imv.validate()
    assert any("area" in e and "positiva" in e for e in erros), \
        f"Deveria rejeitar area=0: {erros}"
    print(f"[PASS] test_area_zero — erros: {erros}")


def test_area_negativa():
    """area negativa → erro."""
    imv = imovel_valido(area=-10.0)
    erros = imv.validate()
    assert any("area" in e and "positiva" in e for e in erros), \
        f"Deveria rejeitar area negativa: {erros}"
    print(f"[PASS] test_area_negativa — erros: {erros}")


def test_sem_preco():
    """Nenhum preço informado → erro."""
    imv = imovel_valido(preco_venda=None, preco_aluguel=None)
    erros = imv.validate()
    assert any("preco" in e for e in erros), \
        f"Deveria exigir ao menos um preço: {erros}"
    print(f"[PASS] test_sem_preco — erros: {erros}")


def test_sem_id():
    """id vazio → erro."""
    imv = imovel_valido(id="")
    erros = imv.validate()
    assert any("id" in e for e in erros), \
        f"Deveria exigir id: {erros}"
    print(f"[PASS] test_sem_id — erros: {erros}")


def test_tipo_invalido():
    """tipo fora de TIPOS_VALIDOS → erro."""
    imv = imovel_valido(tipo="mansao")
    erros = imv.validate()
    assert any("tipo" in e and "inválido" in e for e in erros), \
        f"Deveria rejeitar tipo inválido: {erros}"
    print(f"[PASS] test_tipo_invalido — erros: {erros}")


def test_fonte_vazia():
    """fonte vazia → erro."""
    imv = imovel_valido(fonte="")
    erros = imv.validate()
    assert any("fonte" in e for e in erros), \
        f"Deveria exigir fonte: {erros}"
    print(f"[PASS] test_fonte_vazia — erros: {erros}")


def test_url_malformada():
    """url que não começa com http → erro."""
    imv = imovel_valido(url="ftp://exemplo.com")
    erros = imv.validate()
    assert any("url" in e and "http" in e for e in erros), \
        f"Deveria rejeitar URL sem http: {erros}"
    print(f"[PASS] test_url_malformada — erros: {erros}")


def test_url_vazia_ok():
    """url vazia → SEM erro (campo informacional)."""
    imv = imovel_valido(url="")
    erros = imv.validate()
    assert not any("url" in e for e in erros), \
        f"url vazia não deveria gerar erro: {erros}"
    print(f"[PASS] test_url_vazia_ok — 0 erros de URL")


def test_uf_tres_letras():
    """UF com 3 caracteres → erro."""
    imv = imovel_valido(uf="SPO")
    erros = imv.validate()
    assert any("uf" in e for e in erros), \
        f"Deveria rejeitar UF com 3 chars: {erros}"
    print(f"[PASS] test_uf_tres_letras — erros: {erros}")


def test_quartos_negativo():
    """quartos negativo → erro."""
    imv = imovel_valido(quartos=-1)
    erros = imv.validate()
    assert any("quartos" in e for e in erros), \
        f"Deveria rejeitar quartos negativo: {erros}"
    print(f"[PASS] test_quartos_negativo — erros: {erros}")


def test_quartos_zero_ok():
    """quartos = 0 → OK (studio/kitnet sem quarto)."""
    imv = imovel_valido(quartos=0)
    erros = imv.validate()
    assert not any("quartos" in e for e in erros), \
        f"quartos=0 não deveria gerar erro: {erros}"
    print(f"[PASS] test_quartos_zero_ok — 0 erros")


def test_banheiros_negativo():
    """banheiros negativo → erro."""
    imv = imovel_valido(banheiros=-1)
    erros = imv.validate()
    assert any("banheiros" in e for e in erros), \
        f"Deveria rejeitar banheiros negativo: {erros}"
    print(f"[PASS] test_banheiros_negativo — erros: {erros}")


def test_vagas_negativas():
    """vagas negativo → erro."""
    imv = imovel_valido(vagas=-1)
    erros = imv.validate()
    assert any("vagas" in e for e in erros), \
        f"Deveria rejeitar vagas negativa: {erros}"
    print(f"[PASS] test_vagas_negativas — erros: {erros}")


# ═══════════════════════════════════════════════════════════════════════════════
# Múltiplos erros
# ═══════════════════════════════════════════════════════════════════════════════


def test_multiplos_erros():
    """Imóvel com vários campos inválidos → todos os erros reportados."""
    imv = imovel_valido(
        id="",
        preco_venda=-500.0,
        area=0.0,
        fonte="",
        tipo="zigurate",
        uf="SPO",
    )
    erros = imv.validate()
    assert len(erros) >= 5, f"Esperava >=5 erros, recebeu {len(erros)}: {erros}"
    erros_str = " ".join(erros).lower()
    assert "id" in erros_str
    assert "preco_venda" in erros_str
    assert "area" in erros_str
    assert "fonte" in erros_str
    assert "tipo" in erros_str
    print(f"[PASS] test_multiplos_erros — {len(erros)} erros reportados")


# ═══════════════════════════════════════════════════════════════════════════════
# Validação em lote (validar_lote)
# ═══════════════════════════════════════════════════════════════════════════════


def test_lote_vazio():
    """Lista vazia → relatório com 0 itens."""
    rel = validar_lote([])
    assert rel.total == 0
    assert rel.validos == 0
    assert rel.invalidos == 0
    assert rel.resultados == []
    print(f"[PASS] test_lote_vazio — total={rel.total}")


def test_lote_misto():
    """Lote com válidos e inválidos → contagens corretas."""
    imoveis = [
        imovel_valido(id="v1"),                    # válido
        imovel_valido(id="v2"),                    # válido
        imovel_valido(id="i1", preco_venda=0.0),  # inválido
        imovel_valido(id="i2", area=0.0),          # inválido
    ]
    rel = validar_lote(imoveis)
    assert rel.total == 4
    assert rel.validos == 2
    assert rel.invalidos == 2
    print(f"[PASS] test_lote_misto — {rel.validos} válidos, {rel.invalidos} inválidos de {rel.total}")


def test_resultado_validacao_individual():
    """validar_imovel retorna ResultadoValidacao correto."""
    imv = imovel_valido(preco_venda=-1.0)
    res = validar_imovel(imv, indice=5)
    assert isinstance(res, ResultadoValidacao)
    assert res.indice == 5
    assert not res.valido
    assert len(res.erros) >= 1
    assert "preco_venda" in res.erros[0]
    assert res.imovel["id"] == "test_001"
    print(f"[PASS] test_resultado_validacao_individual — índice={res.indice}, {len(res.erros)} erro(s)")


# ═══════════════════════════════════════════════════════════════════════════════
# Relatórios
# ═══════════════════════════════════════════════════════════════════════════════


def test_relatorio_resumido_valido():
    """Relatório resumido com lote 100% válido."""
    imoveis = [imovel_valido(id=f"v{i}") for i in range(3)]
    rel = validar_lote(imoveis)
    texto = relatorio_resumido(rel)
    assert "3 imóveis" in texto
    assert "3 válidos" in texto
    assert "0 inválidos" in texto
    print(f"[PASS] test_relatorio_resumido_valido")


def test_relatorio_resumido_invalido():
    """Relatório resumido com inválidos → mostra detalhes."""
    imoveis = [
        imovel_valido(id="ok"),
        imovel_valido(id="bad1", preco_venda=0.0),
        imovel_valido(id="bad2", area=-1.0),
    ]
    rel = validar_lote(imoveis)
    texto = relatorio_resumido(rel)
    assert "3 imóveis" in texto
    assert "1 válidos" in texto
    assert "2 inválidos" in texto
    assert "bad1" in texto
    assert "bad2" in texto
    print(f"[PASS] test_relatorio_resumido_invalido")


def test_relatorio_json():
    """relatorio_json retorna dict serializável."""
    imoveis = [
        imovel_valido(id="ok"),
        imovel_valido(id="bad", preco_venda=-1.0),
    ]
    rel = validar_lote(imoveis)
    j = relatorio_json(rel)
    assert isinstance(j, dict)
    assert j["total"] == 2
    assert j["validos"] == 1
    assert j["invalidos"] == 1
    assert len(j["resultados"]) == 2
    assert j["resultados"][0]["valido"] is True
    assert j["resultados"][1]["valido"] is False
    # JSON-safe
    import json as _json
    _json.dumps(j)  # não deve lançar exceção
    print(f"[PASS] test_relatorio_json — {j['total']} itens, JSON-safe")


def test_relatorio_vazio():
    """Relatório com 0 imóveis."""
    rel = validar_lote([])
    texto = relatorio_resumido(rel)
    assert "Nenhum imóvel" in texto
    print(f"[PASS] test_relatorio_vazio — '{texto}'")


# ═══════════════════════════════════════════════════════════════════════════════
# Casos de borda
# ═══════════════════════════════════════════════════════════════════════════════


def test_timestamp_invalido():
    """data_coleta com formato inválido → erro."""
    imv = imovel_valido(data_coleta="21/06/2026")
    erros = imv.validate()
    assert any("data_coleta" in e and "ISO 8601" in e for e in erros), \
        f"Deveria rejeitar timestamp BR: {erros}"
    print(f"[PASS] test_timestamp_invalido — erros: {erros}")


def test_timestamp_iso_ok():
    """data_coleta ISO 8601 → OK."""
    imv = imovel_valido(data_coleta="2026-06-21T10:30:00Z")
    erros = imv.validate()
    assert not any("data_coleta" in e for e in erros), \
        f"Timestamp ISO não deveria gerar erro: {erros}"
    print(f"[PASS] test_timestamp_iso_ok — 0 erros")


def test_condominio_zero():
    """condominio = 0 → erro (deve ser positivo se informado)."""
    imv = imovel_valido(condominio=0.0)
    erros = imv.validate()
    assert any("condominio" in e and "positivo" in e for e in erros), \
        f"Deveria rejeitar condominio=0: {erros}"
    print(f"[PASS] test_condominio_zero — erros: {erros}")


def test_condominio_none_ok():
    """condominio None → OK (não informado)."""
    imv = imovel_valido(condominio=None)
    erros = imv.validate()
    assert not any("condominio" in e for e in erros), \
        f"condominio=None não deveria gerar erro: {erros}"
    print(f"[PASS] test_condominio_none_ok — 0 erros")


def test_iptu_negativo():
    """IPTU negativo → erro."""
    imv = imovel_valido(iptu=-50.0)
    erros = imv.validate()
    assert any("iptu" in e and "positivo" in e for e in erros), \
        f"Deveria rejeitar iptu negativo: {erros}"
    print(f"[PASS] test_iptu_negativo — erros: {erros}")


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [
        test_valido,
        test_preco_venda_zero,
        test_preco_venda_negativo,
        test_preco_aluguel_zero,
        test_area_zero,
        test_area_negativa,
        test_sem_preco,
        test_sem_id,
        test_tipo_invalido,
        test_fonte_vazia,
        test_url_malformada,
        test_url_vazia_ok,
        test_uf_tres_letras,
        test_quartos_negativo,
        test_quartos_zero_ok,
        test_banheiros_negativo,
        test_vagas_negativas,
        test_multiplos_erros,
        test_lote_vazio,
        test_lote_misto,
        test_resultado_validacao_individual,
        test_relatorio_resumido_valido,
        test_relatorio_resumido_invalido,
        test_relatorio_json,
        test_relatorio_vazio,
        test_timestamp_invalido,
        test_timestamp_iso_ok,
        test_condominio_zero,
        test_condominio_none_ok,
        test_iptu_negativo,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"[FAIL] {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Validação: {passed} passaram, {failed} falharam")
    sys.exit(0 if failed == 0 else 1)
