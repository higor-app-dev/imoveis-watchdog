# Watchdog — Comparação e Notificação

Skill core para comparar resultados de extração entre execuções e notificar oportunidades.

## Fluxo

1. **Extrair** dados do portal (via skill específica)
2. **Parsear** para schema unificado
3. **Comparar** com resultado anterior (`data/results/ultimo_<portal>.json`)
4. **Detectar** mudanças:
   - 🆕 Imóveis novos
   - ❌ Imóveis removidos (venderam/alugaram)
   - 📉 Redução de preço (💰 oportunidade!)
   - 📈 Aumento de preço
5. **Notificar** via Telegram

## Schema Unificado

```json
{
  "id": "string (id do portal)",
  "portal": "quintoandar | loft",
  "url": "string",
  "tipo": "compra | aluguel",
  "preco": number,
  "preco_condominio": number,
  "preco_iptu": number,
  "area_m2": number,
  "quartos": number,
  "banheiros": number,
  "vagas": number,
  "tipo_imovel": "Apartamento | Casa | Kitnet",
  "endereco": "string",
  "bairro": "string",
  "cidade": "string",
  "descricao": "string",
  "amenities": ["string"],
  "fotos": ["string (urls)"],
  "data_coleta": "ISO datetime",
  "disponivel": true
}
```

## Detecção de Oportunidades

### Redução de Preço
Comparar `preco_atual < preco_anterior * 0.95` (5%+ de redução).

### Imóvel Novo
ID não existia na execução anterior.

### Imóvel Barato na Região
Preço abaixo da média do bairro em mais de 1 desvio padrão.

## Formato de Notificação

```
🏠 *QuintoAndar — 3 novidades*
🆕 Novo: Apt 2qt R$350k na Vila Mariana
📉 Redução: Apt 3qt R$420k → R$380k (-9.5%) em Santana
❌ Removido: Kitnet R$250k no Centro

🔗 Ver no QuintoAndar
```

## Arquivos de Estado

- `data/results/ultimo_quintoandar.json` — última extração
- `data/results/ultimo_loft.json` — última extração
- `data/results/historico/` — histórico completo
