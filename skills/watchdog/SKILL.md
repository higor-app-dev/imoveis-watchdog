# Watchdog — Comparação e Notificação

Skill core para comparar resultados de extração entre execuções e notificar oportunidades.

## Fluxo

1. **Extrair** dados do portal (via skill específica)
2. **Parsear** para schema unificado (Imovel dataclass)
3. **Comparar** com resultado anterior usando `opportunity_detector.detect()`
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
  "portal": "emcasa | quintoandar | loft | olx",
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

## Detecção de Oportunidades (`opportunity_detector.py`)

Módulo universal que detecta oportunidades usando 3 estratégias em cascata:

### 1. priceChangePercent (Portal)
Quando o portal já calcula a variação (ex.: EmCasa), usa o valor direto.
- Origem: `'EmCasa'`
- Não recalcula — confia no dado do servidor
- Mesmo que o estado anterior tenha o mesmo preço, a detecção acontece
  porque o portal reportou a mudança

### 2. previousPrice (_extra)
Quando o portal fornece o preço anterior (sem o percentual).
- Calcula: `(preco_atual - previousPrice) / previousPrice * 100`
- Origem: `'EmCasa'` (ou nome da fonte)

### 3. Diff de Estado (Watchdog)
Quando não há dados do portal, compara com estado anterior salvo.
- Origem: `'Watchdog'`
- Fallback para portais que não expõem histórico de preço

### Estrutura de Opportunity

```python
@dataclass
class Opportunity:
    tipo: str       # novo | removido | queda_preco | aumento_preco
    imovel: Imovel
    origem: str     # 'EmCasa' | 'Watchdog' | 'Olx' etc.
    change_pct: Optional[float]
    old_price: Optional[float]
    new_price: Optional[float]
    detalhes: dict
```

### Uso

```python
from skills.watchdog.opportunity_detector import detect, build_notification_text

opps = detect(imoveis_atuais, imoveis_anteriores)
for opp in opps:
    print(opp.resumo())       # "📉 R$ 900.000 → R$ 850.000 (-5.6%) — Apto 3q (EmCasa)"

text = build_notification_text(opps)
send_telegram(text)
```

## Arquivos de Estado

- `data/results/ultimo_<portal>.json` — última extração
- `data/results/historico/` — histórico completo
