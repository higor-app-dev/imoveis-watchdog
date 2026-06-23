"""
zap_parser — Mock parser de terceiro portal para testes.

Este módulo é usado exclusivamente para validar o mecanismo de
descoberta dinâmica de portais. Simula um parser de portal novo
com interface compatível com o sistema de registro.

Uso:
    from zap_parser import from_zap_listing, from_zap_payload
    from imovel_schema import Imovel

    listing = from_zap_listing(raw_data)
    listings = from_zap_payload(payload)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# O schema unificado vive em ~/.hermes/imovel_schema.py
sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel


def from_zap_listing(data: dict) -> Imovel:
    """Converte um dicionário de listagem do Zap para Imovel.

    Aceita campos típicos:
        - codigo (str): ID do anúncio
        - titulo (str): Título
        - url (str): URL do anúncio
        - preco (float): Preço de venda
        - area (float): Área em m²
        - quartos (int): Número de quartos
        - banheiros (int): Número de banheiros
        - vagas (int): Vagas de garagem
        - tipo (str): Tipo de imóvel
        - bairro (str): Bairro
        - cidade (str): Cidade
        - uf (str): Sigla do estado
        - descricao (str): Descrição
    """
    return Imovel(
        id=str(data.get("codigo", data.get("id", ""))),
        titulo=data.get("titulo", data.get("title", "")),
        url=data.get("url", ""),
        fonte="zap",
        bairro=data.get("bairro", data.get("neighborhood", "")),
        cidade=data.get("cidade", data.get("city", "")),
        uf=data.get("uf", data.get("stateCode", "")),
        endereco=data.get("endereco", data.get("address", "")),
        preco_venda=data.get("preco", data.get("salePrice")),
        area=data.get("area"),
        quartos=data.get("quartos", data.get("bedrooms")),
        banheiros=data.get("banheiros", data.get("bathrooms")),
        vagas=data.get("vagas", data.get("parkingSpots")),
        tipo=data.get("tipo", data.get("type", "apartamento")),
        descricao=data.get("descricao", data.get("description", "")),
    )


def from_zap_payload(payload: dict) -> list[Imovel]:
    """Converte payload de busca do Zap para lista de Imovel.

    Aceita:
        - payload["results"]: list[dict]  (resultados diretos)
        - payload["listings"]: list[dict] (nome alternativo)
        - payload["data"]["listings"]: list[dict] (aninhado)
    """
    raw = (
        payload.get("results")
        or payload.get("listings")
        or (payload.get("data") or {}).get("listings")
        or []
    )
    return [from_zap_listing(item) for item in raw]


def build_zap_url(params: dict) -> str:
    """Constrói URL de busca no Zap (formato simulado)."""
    cidade = params.get("cidade", params.get("city", "sao-paulo"))
    bairro = params.get("bairro", params.get("neighborhood", ""))
    preco_max = params.get("preco_max", params.get("price_max", ""))

    url = f"https://www.zapimoveis.com.br/venda/imoveis/{cidade}/"
    if bairro:
        url += f"{bairro}/"
    if preco_max:
        url += f"?precoMaximo={preco_max}"
    return url
