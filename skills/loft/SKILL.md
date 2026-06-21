# Loft — Extração de Imóveis

Skill para extrair listings de imóveis da Loft (loft.com.br).

## Visão Geral

A Loft é um portal Next.js (Pages Router) protegido por CloudFront (AWS). 
O Hermes Browser Tool (Browserbase) é bloqueado (HTTP 403).
O conteúdo é carregado via JS client-side (MUI components).

## URLs conhecidas

| URL | Resultado |
|-----|-----------|
| `/venda/apartamentos/sp/sao-paulo` | Apartamentos à venda em SP |
| `/venda/apartamentos/sp/sao-paulo/com-1-quarto` | + 1 quarto |
| `/venda/apartamentos/sp/sao-paulo/com-preco-500mil` | + até 500 mil |

## Parâmetros de URL
- `?bairros=bela-vista_sao-paulo_sp~consolacao_sao-paulo_sp` — bairros
- `&vagas=1` — vagas de garagem
- `&com-preco-500mil` — preço na URL path

## Métodos de Extração

### 1. curl com User-Agent (funciona — SSG)
```bash
curl -s -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  "https://www.loft.com.br/venda/apartamentos/sp/sao-paulo" | ...
```
⚠️ Dados de listings são carregados via JS — SSG retorna apenas HTML vazio + CSS.

### 2. Local Playwright (stealth mode) — recomendado
Usar `playwright` local com stealth config:
- `headless=True` com `--disable-blink-features=AutomationControlled`
- User-Agent realista
- `locale="pt-BR"`
- `add_init_script` para remover `navigator.webdriver`

### 3. Fallback: Google search
```python
site:loft.com.br/venda/apartamentos/sp/sao-paulo "preco" "quartos"
```

## Estrutura de Dados (esperada)

A extrair via DOM/Playwright:
- Preço de venda
- Área (m²)
- Quartos
- Vagas
- Endereço/bairro
- Fotos
- Condomínio
- Descrição

## Dependências
- `playwright` (pip install)
- `playwright install chromium`
- Ou usar Hermes browser tool (se disponível)
