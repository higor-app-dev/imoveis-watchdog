#!/usr/bin/env python3
"""
Testes para o módulo opportunity_detector.

Cobre:
  - EmCasa com priceChangePercent (origem 'EmCasa')
  - Fallback para previousPrice
  - Fallback diff com estado anterior
  - Imóveis novos / removidos
  - Primeira execução (previous=None)
  - Sem mudanças
  - Múltiplas fontes
"""

import json
import os
import sys
import unittest

# Adiciona schema ao path
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".hermes"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from imovel_schema import Imovel

# O módulo sob teste
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from skills.emcasa.emcasa_parser import from_emcasa_hit
from skills.watchdog.opportunity_detector import (
    detect,
    detect_from_dicts,
    group_by_fonte,
    build_notification_text,
    Opportunity,
    OPORTUNIDADE_NOVO,
    OPORTUNIDADE_REMOVIDO,
    OPORTUNIDADE_QUEDA_PRECO,
    OPORTUNIDADE_AUMENTO_PRECO,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Dados de exemplo (replicados do test_emcasa_parser.py)
# ═══════════════════════════════════════════════════════════════════════════════

# SP — Apartamento na Vila Mariana (com priceChangePercent)
SP_APTO_RAW = {
    "document": {
        "id": "sp_apto_001",
        "askingPrice": 850000.0,
        "previousPrice": 900000.0,
        "priceChangePercent": -5.56,
        "condoFee": 1200.0,
        "propertyTax": 2500.0,
        "bedrooms": 3,
        "bathrooms": 2,
        "parkingSpots": 2,
        "propertyType": "apartment",
        "totalArea": 86.0,
        "usableArea": 72.0,
        "city": "São Paulo",
        "state": "SP",
        "neighborhood": "Vila Mariana",
        "street": "Rua Vergueiro, 2000",
        "unitDescription": "Apto 3q Vila Mariana com vaga",
        "buildingAmenities": ["piscina", "academia", "portaria24h"],
        "propertyFeatures": ["sacada", "armário embutido"],
        "imageUrls": [
            "https://cdn.fndn.ai/images/sp/test1/detail",
            "https://cdn.fndn.ai/images/sp/test2/detail",
        ],
        "floor": "12",
        "buildingName": "Edifício Vila Rica",
        "slug": "vila-mariana/rua-vergueiro/sp_apto_001",
        "coordinates": [-23.5800, -46.6400],
        "createdAt": "2026-05-15T10:00:00Z",
    }
}

# SP — Cobertura nos Jardins (com priceChangePercent)
SP_COBERTURA_RAW = {
    "document": {
        "id": "sp_coh_002",
        "askingPrice": 2500000.0,
        "previousPrice": 2700000.0,
        "priceChangePercent": -7.41,
        "condoFee": 3500.0,
        "propertyTax": 8000.0,
        "bedrooms": 4,
        "bathrooms": 3,
        "parkingSpots": 3,
        "propertyType": "penthouse",
        "totalArea": 200.0,
        "city": "São Paulo",
        "state": "SP",
        "neighborhood": "Jardins",
        "unitDescription": "Cobertura duplex nos Jardins",
        "buildingAmenities": ["piscina", "academia", "salao_festas", "sauna"],
        "propertyFeatures": ["sacada_gourmet", "lareira"],
        "imageUrls": ["https://cdn.fndn.ai/images/sp/cobertura/detail"],
        "slug": "jardins/alameda-lorena/sp_coh_002",
    }
}

# SP — Studio na Consolação (SEM priceChangePercent)
SP_STUDIO_RAW = {
    "document": {
        "id": "sp_stu_003",
        "askingPrice": 320000.0,
        "condoFee": 450.0,
        "propertyTax": 600.0,
        "bedrooms": 1,
        "bathrooms": 1,
        "parkingSpots": 0,
        "propertyType": "studio",
        "totalArea": 35.0,
        "city": "São Paulo",
        "state": "SP",
        "neighborhood": "Consolação",
        "buildingAmenities": ["portaria24h", "elevador"],
    }
}

# RJ — Casa no Leblon (com priceChangePercent -11.11%)
RJ_CASA_RAW = {
    "document": {
        "id": "rj_casa_001",
        "askingPrice": 1200000.0,
        "previousPrice": 1350000.0,
        "priceChangePercent": -11.11,
        "condoFee": 0,
        "propertyTax": 4800.0,
        "bedrooms": 4,
        "bathrooms": 3,
        "parkingSpots": 3,
        "propertyType": "house",
        "totalArea": 280.0,
        "city": "Rio de Janeiro",
        "state": "RJ",
        "neighborhood": "Leblon",
        "unitDescription": "Casa 4q no Leblon com piscina",
        "buildingAmenities": ["piscina", "jardim"],
        "propertyFeatures": ["churrasqueira", "edicula"],
        "imageUrls": [
            "https://cdn.fndn.ai/images/rj/casa1/detail",
            "https://cdn.fndn.ai/images/rj/casa2/detail",
            "https://cdn.fndn.ai/images/rj/casa3/detail",
        ],
        "slug": "leblon/rua-rainha-elizabeth/rj_casa_001",
    }
}

# RJ — Apt em Copacabana (SEM priceChangePercent)
# Usando preço de aluguel como exemplo de fallback
RJ_APTO_RAW = {
    "document": {
        "id": "rj_apto_002",
        "askingPrice": 750000.0,
        "condoFee": 1500.0,
        "propertyTax": 3200.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parkingSpots": 1,
        "propertyType": "apartment",
        "totalArea": 65.0,
        "city": "Rio de Janeiro",
        "state": "RJ",
        "neighborhood": "Copacabana",
        "unitDescription": "Apto 2q em Copacabana",
        "buildingAmenities": ["piscina", "portaria24h"],
        "slug": "copacabana/av-atlantica/rj_apto_002",
    }
}


def _make_imovel(raw: dict) -> Imovel:
    """Converte raw dict EmCasa para Imovel (com _extra preservado)."""
    return from_emcasa_hit(raw)


def _make_imovel_simples(
    id_: str,
    preco: float,
    fonte: str = "olx",
    bairro: str = "Centro",
    cidade: str = "São Paulo",
    quartos: int = 2,
    area: float = 60.0,
    extra: dict | None = None,
) -> Imovel:
    """Cria Imovel sem _extra (simulando OLX/Zap)."""
    im = Imovel(
        id=id_,
        titulo=f"Imóvel {id_}",
        url=f"https://exemplo.com/{id_}",
        fonte=fonte,
        bairro=bairro,
        cidade=cidade,
        uf="SP",
        preco_venda=preco,
        area=area,
        quartos=quartos,
        tipo="apartamento",
    )
    if extra:
        im._extra = extra
    return im


# ═══════════════════════════════════════════════════════════════════════════════
# Testes
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpportunityDetector(unittest.TestCase):
    """Testes core do detector de oportunidades."""

    # ── priceChangePercent (EmCasa) ───────────────────────────────────────

    def test_emcasa_price_change_detected(self):
        """EmCasa com priceChangePercent negativo → queda_preco com origem 'EmCasa'."""
        current = [_make_imovel(SP_APTO_RAW)]
        # Anterior com mesmo ID mas preço diferente (priceChangePercent deve prevalecer)
        previous = [_make_imovel(SP_APTO_RAW)]
        # Ajusta o preço do anterior para simular estado histórico
        prev_im = previous[0]
        prev_im.preco_venda = 900000.0  # mesmo valor do previousPrice

        opps = detect(current, previous)

        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        self.assertEqual(len(quedas), 1, "Deveria detectar 1 queda de preço")
        queda = quedas[0]
        self.assertEqual(queda.origem, "EmCasa")
        self.assertAlmostEqual(queda.change_pct, -5.56, places=2)
        self.assertEqual(queda.old_price, 900000.0)
        self.assertEqual(queda.new_price, 850000.0)
        self.assertEqual(queda.imovel.id, "emcasa_sp_apto_001")
        self.assertEqual(
            queda.detalhes.get("origem_calc"), "priceChangePercent"
        )

    def test_emcasa_price_change_multiple(self):
        """Múltiplos imóveis EmCasa com priceChangePercent."""
        current = [_make_imovel(SP_APTO_RAW), _make_imovel(SP_COBERTURA_RAW)]
        previous = current  # Não importa, priceChangePercent prevalece

        opps = detect(current, previous)

        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        self.assertEqual(len(quedas), 2)

        # Verifica que ambos vieram com origem EmCasa
        for q in quedas:
            self.assertEqual(q.origem, "EmCasa")
            self.assertEqual(q.detalhes.get("origem_calc"), "priceChangePercent")

        # O maior percentual de queda deve vir primeiro (ordenado)
        # -11.11 (casa) < -7.41 (cobertura) < -5.56 (apto)
        # Mas só temos apto (-5.56) e cobertura (-7.41)
        self.assertAlmostEqual(quedas[0].change_pct, -7.41, places=2,
                               msg="Maior queda deve vir primeiro")

    def test_emcasa_no_price_change(self):
        """EmCasa sem priceChangePercent → não detecta queda via portal."""
        im = _make_imovel(SP_STUDIO_RAW)
        # Studio não tem priceChangePercent nem previousPrice
        current = [im]
        # Estado anterior com mesmo preço
        prev = [Imovel.from_dict(im.to_dict())]
        prev[0]._extra = getattr(im, "_extra", {})

        opps = detect(current, prev)
        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        self.assertEqual(len(quedas), 0,
                         "Studio sem priceChangePercent e sem diff → sem queda")

    def test_emcasa_no_change_same_price(self):
        """EmCasa com priceChangePercent mas sem diff real → ainda detecta."""
        # Simula um imóvel onde o portal diz que houve mudança (-5.56%)
        # mesmo que no estado anterior o preço já refletisse a mudança
        im_cur = _make_imovel(SP_APTO_RAW)  # 850k, -5.56%
        im_prev = _make_imovel(SP_APTO_RAW)
        im_prev.preco_venda = 850000.0  # mesmo preço

        opps = detect([im_cur], [im_prev])
        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        # Ainda detecta porque priceChangePercent está presente e < 0
        self.assertEqual(len(quedas), 1,
                         "priceChangePercent presente → detecta mesmo sem diff de estado")
        self.assertEqual(quedas[0].origem, "EmCasa")

    # ── Fallback: previousPrice ───────────────────────────────────────────

    def test_fallback_previous_price(self):
        """Sem priceChangePercent mas com previousPrice → calcula do previousPrice."""
        # Cria imóvel com previousPrice no _extra mas sem priceChangePercent
        im = _make_imovel_simples(
            "test_001", preco=800000.0, bairro="Pinheiros",
            extra={"previousPrice": 950000.0},
        )

        opps = detect([im], [im])  # previousPrice está no imovel atual
        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        self.assertEqual(len(quedas), 1)
        q = quedas[0]
        self.assertEqual(q.origem, "Olx")  # fonte 'olx' capitalizada
        self.assertAlmostEqual(q.change_pct, -15.79, places=1)
        self.assertEqual(q.old_price, 950000.0)
        self.assertEqual(q.new_price, 800000.0)
        self.assertEqual(q.detalhes.get("origem_calc"), "previousPrice")

    # ── Fallback: diff com estado anterior ────────────────────────────────

    def test_fallback_diff_state(self):
        """Sem priceChangePercent nem previousPrice → fallback para diff de estado."""
        cur = _make_imovel_simples("olx_001", preco=450000.0, fonte="olx")
        prev = _make_imovel_simples("olx_001", preco=500000.0, fonte="olx")

        opps = detect([cur], [prev])
        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        self.assertEqual(len(quedas), 1)
        q = quedas[0]
        self.assertEqual(q.origem, "Watchdog")
        self.assertAlmostEqual(q.change_pct, -10.0, places=1)
        self.assertEqual(q.old_price, 500000.0)
        self.assertEqual(q.new_price, 450000.0)
        self.assertEqual(q.detalhes.get("origem_calc"), "diff_state")

    def test_fallback_diff_state_increase(self):
        """Aumento de preço via fallback de estado."""
        cur = _make_imovel_simples("olx_002", preco=600000.0, fonte="olx")
        prev = _make_imovel_simples("olx_002", preco=550000.0, fonte="olx")

        opps = detect([cur], [prev])
        aumentos = [o for o in opps if o.tipo == OPORTUNIDADE_AUMENTO_PRECO]
        self.assertEqual(len(aumentos), 1)
        a = aumentos[0]
        self.assertAlmostEqual(a.change_pct, 9.09, places=1)
        self.assertEqual(a.old_price, 550000.0)
        self.assertEqual(a.new_price, 600000.0)

    # ── Imóveis novos / removidos ─────────────────────────────────────────

    def test_new_listing(self):
        """Imóvel que não existia no estado anterior → novo."""
        cur = [_make_imovel(SP_APTO_RAW)]
        opps = detect(cur, [])
        novos = [o for o in opps if o.tipo == OPORTUNIDADE_NOVO]
        self.assertEqual(len(novos), 1)
        self.assertEqual(novos[0].imovel.id, "emcasa_sp_apto_001")
        self.assertEqual(novos[0].origem, "Emcasa")

    def test_new_listing_multiple(self):
        """Vários imóveis novos."""
        cur = [_make_imovel(SP_APTO_RAW), _make_imovel(RJ_CASA_RAW)]
        opps = detect(cur, None)  # first run
        novos = [o for o in opps if o.tipo == OPORTUNIDADE_NOVO]
        self.assertEqual(len(novos), 2)

    def test_removed_listing(self):
        """Imóvel que existia e não está mais → removido."""
        prev = [_make_imovel(SP_APTO_RAW)]
        opps = detect([], prev)
        removidos = [o for o in opps if o.tipo == OPORTUNIDADE_REMOVIDO]
        self.assertEqual(len(removidos), 1)
        self.assertEqual(removidos[0].imovel.id, "emcasa_sp_apto_001")

    def test_first_run_all_new(self):
        """Primeira execução (previous=None) → todos são novos."""
        cur = [
            _make_imovel(SP_APTO_RAW),
            _make_imovel(SP_COBERTURA_RAW),
            _make_imovel(SP_STUDIO_RAW),
        ]
        opps = detect(cur, None)
        novos = [o for o in opps if o.tipo == OPORTUNIDADE_NOVO]
        self.assertEqual(len(novos), 3)

    # ── Sem mudanças ──────────────────────────────────────────────────────

    def test_no_changes(self):
        """Mesma lista → zero oportunidades."""
        im = _make_imovel_simples("stable_001", preco=500000.0)
        opps = detect([im], [im])
        self.assertEqual(len(opps), 0, "Sem mudanças → sem oportunidades")

    def test_no_changes_multiple(self):
        """Vários imóveis sem mudanças."""
        current = [
            _make_imovel_simples("a", 100000.0),
            _make_imovel_simples("b", 200000.0),
        ]
        previous = [
            _make_imovel_simples("a", 100000.0),
            _make_imovel_simples("b", 200000.0),
        ]
        opps = detect(current, previous)
        self.assertEqual(len(opps), 0)

    # ── Cenários mistos ───────────────────────────────────────────────────

    def test_mixed_sources(self):
        """EmCasa + OLX na mesma execução."""
        apto_emcasa = _make_imovel(SP_APTO_RAW)

        # OLX que caiu de preço (sem priceChangePercent)
        olx_cur = _make_imovel_simples("olx_100", preco=350000.0, fonte="olx")
        olx_prev = _make_imovel_simples("olx_100", preco=400000.0, fonte="olx")

        # OLX novo
        olx_new = _make_imovel_simples("olx_101", preco=500000.0, fonte="olx")

        current = [apto_emcasa, olx_cur, olx_new]
        previous = [_make_imovel(SP_APTO_RAW), olx_prev]

        # Ajusta preço do anterior para que o EmCasa seja detectado
        previous[0].preco_venda = 900000.0

        opps = detect(current, previous)

        # Deve ter: 1 queda EmCasa, 1 queda OLX, 1 novo OLX
        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        novos = [o for o in opps if o.tipo == OPORTUNIDADE_NOVO]

        self.assertEqual(len(quedas), 2)
        self.assertEqual(len(novos), 1)

        # Queda EmCasa
        emcasa_quedas = [q for q in quedas if q.origem == "EmCasa"]
        self.assertEqual(len(emcasa_quedas), 1)
        self.assertAlmostEqual(emcasa_quedas[0].change_pct, -5.56, places=2)

        # Queda OLX (fallback)
        olx_quedas = [q for q in quedas if q.origem == "Watchdog"]
        self.assertEqual(len(olx_quedas), 1)
        self.assertAlmostEqual(olx_quedas[0].change_pct, -12.5, places=1)

    def test_new_and_removed(self):
        """Mistura de novos e removidos."""
        a_cur = _make_imovel_simples("a", 100000.0)
        b_cur = _make_imovel_simples("b", 200000.0)  # novo
        a_prev = _make_imovel_simples("a", 100000.0)
        c_prev = _make_imovel_simples("c", 300000.0)  # removido

        opps = detect([a_cur, b_cur], [a_prev, c_prev])

        novos = [o for o in opps if o.tipo == OPORTUNIDADE_NOVO]
        removidos = [o for o in opps if o.tipo == OPORTUNIDADE_REMOVIDO]
        self.assertEqual(len(novos), 1)
        self.assertEqual(len(removidos), 1)
        self.assertEqual(novos[0].imovel.id, "b")
        self.assertEqual(removidos[0].imovel.id, "c")

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_empty_current(self):
        """Lista atual vazia → só removidos."""
        prev = [
            _make_imovel_simples("x", 100000.0),
            _make_imovel_simples("y", 200000.0),
        ]
        opps = detect([], prev)
        self.assertEqual(len(opps), 2)
        for o in opps:
            self.assertEqual(o.tipo, OPORTUNIDADE_REMOVIDO)

    def test_empty_both(self):
        """Ambas listas vazias → sem oportunidades."""
        opps = detect([], [])
        self.assertEqual(len(opps), 0)

    def test_previous_none(self):
        """previous=None → todos novos."""
        cur = [_make_imovel_simples("a", 100000.0)]
        opps = detect(cur, None)
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].tipo, OPORTUNIDADE_NOVO)

    def test_zero_change_percent(self):
        """priceChangePercent = 0 → não gera oportunidade de queda/aumento."""
        im = _make_imovel_simples(
            "zero_001", preco=500000.0,
            extra={"priceChangePercent": 0.0, "previousPrice": 500000.0},
        )
        opps = detect([im], [im])
        changes = [
            o for o in opps
            if o.tipo in (OPORTUNIDADE_QUEDA_PRECO, OPORTUNIDADE_AUMENTO_PRECO)
        ]
        self.assertEqual(len(changes), 0,
                         "priceChangePercent=0 não deve gerar mudança")

    def test_detect_from_dicts(self):
        """detect_from_dicts reconstrói Imovel + _extra de dicts."""
        im = _make_imovel(SP_APTO_RAW)
        cur_dict = im.to_dict()
        cur_dict["_extra"] = getattr(im, "_extra", {})

        prev_dict = im.to_dict()
        prev_dict["preco_venda"] = 900000.0
        prev_dict["_extra"] = getattr(im, "_extra", {})

        opps = detect_from_dicts([cur_dict], [prev_dict])
        quedas = [o for o in opps if o.tipo == OPORTUNIDADE_QUEDA_PRECO]
        self.assertEqual(len(quedas), 1)
        self.assertEqual(quedas[0].origem, "EmCasa")


class TestOpportunityDataClass(unittest.TestCase):
    """Testes do dataclass Opportunity."""

    def test_resumo_queda(self):
        """Resumo de queda de preço."""
        im = _make_imovel_simples("test", 850000.0, bairro="Vila Mariana")
        opp = Opportunity(
            tipo=OPORTUNIDADE_QUEDA_PRECO,
            imovel=im,
            origem="EmCasa",
            change_pct=-5.56,
            old_price=900000.0,
            new_price=850000.0,
        )
        resumo = opp.resumo()
        self.assertIn("📉", resumo)
        self.assertIn("-5.6%", resumo)
        self.assertIn("EmCasa", resumo)

    def test_resumo_novo(self):
        """Resumo de imóvel novo."""
        im = _make_imovel_simples("novo", 300000.0, bairro="Centro")
        opp = Opportunity(tipo=OPORTUNIDADE_NOVO, imovel=im, origem="Emcasa")
        resumo = opp.resumo()
        self.assertIn("🆕", resumo)

    def test_resumo_removido(self):
        """Resumo de imóvel removido."""
        im = _make_imovel_simples("removido", 500000.0, bairro="Pinheiros")
        opp = Opportunity(tipo=OPORTUNIDADE_REMOVIDO, imovel=im, origem="Watchdog")
        resumo = opp.resumo()
        self.assertIn("❌", resumo)

    def test_tipo_invalido(self):
        """Tipo inválido deve lançar AssertionError."""
        with self.assertRaises(AssertionError):
            Opportunity(tipo="invalido")


class TestGroupByFonte(unittest.TestCase):
    """Testes de agrupamento por fonte."""

    def test_group_emcasa(self):
        """Agrupa oportunidades EmCasa."""
        im = _make_imovel(SP_APTO_RAW)
        opp = Opportunity(tipo=OPORTUNIDADE_QUEDA_PRECO, imovel=im, origem="EmCasa")
        grouped = group_by_fonte([opp])
        self.assertIn("emcasa", grouped)
        self.assertEqual(len(grouped["emcasa"]), 1)

    def test_group_multiple(self):
        """Agrupa múltiplas fontes."""
        im1 = _make_imovel(SP_APTO_RAW)
        im2 = _make_imovel_simples("olx_99", 300000.0, fonte="olx")

        opps = [
            Opportunity(tipo=OPORTUNIDADE_QUEDA_PRECO, imovel=im1, origem="EmCasa"),
            Opportunity(tipo=OPORTUNIDADE_NOVO, imovel=im2, origem="Watchdog"),
        ]
        grouped = group_by_fonte(opps)
        self.assertEqual(len(grouped), 2)
        self.assertIn("emcasa", grouped)
        self.assertIn("olx", grouped)


class TestBuildNotification(unittest.TestCase):
    """Testes de formatação de notificação."""

    def test_notification_with_opportunities(self):
        """Notificação com oportunidades."""
        im1 = _make_imovel(SP_APTO_RAW)
        opps = [
            Opportunity(
                tipo=OPORTUNIDADE_QUEDA_PRECO,
                imovel=im1,
                origem="EmCasa",
                change_pct=-5.56,
                old_price=900000.0,
                new_price=850000.0,
            ),
        ]
        text = build_notification_text(opps)
        self.assertIn("Watchdog", text)
        self.assertIn("Emcasa", text)
        self.assertIn("-5.6%", text)
        self.assertIn("1 oportunidade(s)", text)

    def test_notification_empty(self):
        """Notificação sem oportunidades."""
        text = build_notification_text([])
        self.assertIn("Sem oportunidades", text)

    def test_notification_no_imovel(self):
        """Notificação com Opportunity sem imovel."""
        opp = Opportunity(tipo=OPORTUNIDADE_NOVO, origem="Teste")
        text = build_notification_text([opp])
        self.assertIn("1 oportunidade(s)", text)


if __name__ == "__main__":
    unittest.main()
