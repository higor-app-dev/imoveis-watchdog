# QuintoAndar — Extração de Imóveis

Skill para extrair listings de imóveis do QuintoAndar (quintoandar.com.br).

## Visão Geral

O QuintoAndar é um SPA Next.js. Os dados dos imóveis estão disponíveis:
- **Via SSR (Server-Side Rendered)**: dados no DOM + Next.js data route
- **API interna**: `apigw.prod.quintoandar.com.br/house-listing-search/`
- **Browser automation**: necessário para filtros específicos (bairro, preço)

## URLs que funcionam

| URL | Resultado |
|-----|-----------|
| `/comprar/imovel/sao-paulo-sp-brasil` | Imóveis à venda em SP |
| `/comprar/imovel/sao-paulo-sp-brasil/apartamento` | Apartamentos à venda |
| `/alugar/imovel/sao-paulo-sp-brasil` | Imóveis para alugar |

⚠️ Filtros de bairro/preço funcionam apenas via interação no browser (SPA client-side).

## Estrutura de Dados

Cada imóvel retorna:
```json
{
  "id": "892820623",
  "salePrice": 1000000,
  "rentPrice": 3700,
  "area": 105,
  "bedrooms": 3,
  "bathrooms": 2,
  "parkingSpots": 3,
  "type": "Apartamento",
  "address": {"address": "R. Mal. Hermes da Fonseca", "city": "São Paulo"},
  "neighbourhood": "Santana",
  "regionName": "Santana",
  "condoIptu": {},
  "forSale": true,
  "shortSaleDescription": "Apartamento para comprar em Santana...",
  "amenities": ["piscina", "academia", ...],
  "photos": [...]
}
```

## Métodos de Extração

### 1. Next.js Data Route (recomendado — rápido, estruturado)
```
GET /_next/data/{buildId}/pt-BR/comprar/imovel/sao-paulo-sp-brasil.json
```
Retorna JSON completo com `pageProps.initialState.houses` (array de imóveis) e `search.count`.

### 2. Browser Automation (para filtros específicos)
- Navegar até a URL base
- Interagir com o formulário de busca (cidade → bairro → valor)
- Clicar em "Buscar imóveis"
- Extrair dados do DOM ou da rota Next.js

### 3. DOM Extraction (fallback)
Os listings estão no DOM como links com atributos `aria-label` contendo preço, área, quartos, endereço.

## Quando Usar

- **Busca por cidade + tipo**: Next.js data route (rápido)
- **Filtros específicos (bairro, preço, quartos)**: Browser automation
- **Monitoramento contínuo**: Browser automation com cron job

## Fluxo Recomendado

1. Configurar alvos em `config/targets.yaml`
2. Usar Hermes browser tool para navegar + extrair
3. Parsear JSON da rota Next.js
4. Salvar em `data/results/` com timestamp
5. Comparar com resultado anterior (skill watchdog)
