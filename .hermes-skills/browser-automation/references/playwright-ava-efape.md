# AVA-EFAPE Specifics

Plataforma: AVA-EFAPE (Moodle adaptado pela EFAPE - SP)
URL: https://avaefape.educacao.sp.gov.br
Tipo de conteúdo: `mod_interactivevideo` (Interactive Video Plugin)

## Login
- URL: `/login/index.php`
- Campos: username=CPF (apenas números), password=senha
- Botão: "Acessar" (`#loginbtn`)
- Validação: aguardar texto "Olá, Ródiney"
- Sessão expira após ~15 min de inatividade. Script precisa refazer login.

## Página do Vídeo
URL: `/mod/interactivevideo/view.php?id={ID}`

### Estrutura do Player
- Iframe YouTube com `id="player"`, `controls=0`
- Youtube URL: `https://www.youtube.com/embed/{VIDEO_ID}?autoplay=0&hl=pt_br&start=0&end={DURATION}&controls=0`
- Plugin sobrepõe controles customizados
- Botão "Reproduzir vídeo" na tela inicial (só aparece na primeira carga)
- Barra de progresso do YouTube: 0-100%

### Metadados do Plugin (sidebar)
- **Capítulos:** `X / 8` (X concluídos de 8 totais)
- **Atividades:** `Y / Z` (Y completas de Z)
- **Duração:** `Xm Ys`

### Modais Conhecidos
1. **"Tarefas: Concluir: 100% das interações"** — modal que aparece ao iniciar o vídeo. Tem lista de links (materiais) e um botão. O botão de fechar/concluir precisa ser clicado explicitamente; ESC não registra como completo.
2. **Modais de atividade no player** — aparecem em timestamps específicos. Geralmente têm botão "Concluído" ou "Fechar".
3. **"Plano de aula: Sala de edição"** — atividade final que abre um arquivo externo. Necessário apenas abrir.

### Condições de Conclusão
- **98% mínimo** do vídeo assistido
- **100% das interações** completadas
- Progresso é salvo via AJAX pelo plugin Moodle (não pelo YouTube)
- O relatório "Planejamentos Concluídos 2026" no menu mostra o status consolidado

## Cursos da Semana 8 de Junho
Disciplinas com vídeos pendentes:

| Curso | ID Curso | Vídeos |
|-------|----------|--------|
| Ciências (6º-9º ano) | — | 3 vídeos (aula 17, 21-22, 23-24) |
| Tecnologia e Inovação: Programação | — | 2 vídeos |
| Biologia (Ensino Médio) | — | 2 vídeos |
| CONVIVA | — | 1 vídeo |
| Educação Antirracista | — | 1 vídeo |
| Educação Especial Regentes | — | 1 vídeo |

## Script de Automação
Criado em: `~/.hermes/scripts/assistir_video_ava.py` (versão completa com modal detection)
          `~/.hermes/scripts/assistir_video_simples.py` (versão simplificada, apenas progresso YouTube)
Banco: Turso Cloud (`videos-ava-db-higor-app-dev.aws-us-east-1.turso.io`)
Token: `/tmp/turso_videos_token.txt`

### Abordagens testadas

| Abordagem | Progresso | Modais | Registrou? |
|-----------|-----------|--------|------------|
| Headless, modal detection agressivo | 98.0% | 97 | ❌ Não |
| Headed, sem auto-resume | 99.9% | 0 | ❌ Não |
| Headed, com auto-resume + simplificado | 98.2% | 0 | ❌ Não (precisa verificar) |

**Conclusão**: Atingir 98% de playback não é suficiente — o plugin Moodle só
registra com 98% + 100% das interações. Auto-resume pode estar impedindo
as interações de renderizarem.

### Execução em modo headed (WSLg)
Confirmado funcionando: `headless=False` com `DISPLAY=:0` (WSLg) abre o Chromium
visivelmente. Necessário para o plugin Moodle registrar progresso AJAX.

**Env vars obrigatórias para headed no WSL:**
```bash
export DISPLAY=:0
export XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir
export WAYLAND_DISPLAY=wayland-0
export PULSE_SERVER=/mnt/wslg/PulseServer
```

### Auto-Resume (Ingrediente Crítico)
O setup_auto_resume (event listener no window message + postMessage play) é
**obrigatório** para o YouTube tocar continuamente. Sem ele, o vídeo pausa após
~30s e nunca mais volta. Implementar com:
```python
# Dentro do evaluate:
window.addEventListener('message', function(e) {
    const data = JSON.parse(e.data);
    if (data.event === 'onStateChange' && data.info === 2) {
        setTimeout(() => { /* postMessage playVideo */ }, 500);
    }
});
// + visibilitychange handler + setTimeout kickstart de 2s
```

**ATENÇÃO**: Auto-resume pode IMPEDIR modais de aparecerem — o YouTube pausa
para mostrar a interação, mas o auto-resume dá play imediatamente (500ms),
antes do modal renderizar. Se isso acontecer, aumentar o delay para 3-5s ou
desligar auto-resume temporariamente nos trechos de interação.

### Resultado de execuções registradas no Turso

| ID | Vídeo | Progresso | Modais | Data |
|----|-------|-----------|--------|------|
| 1  | 66937 Transformações químicas e físicas | 98.0% | 97 | 14/06 22:15 |
| 2  | 66937 (headless, 2ª tentativa) | 99.9% | 0 | 15/06 00:38 |
| 3  | 66937 (headed via WSLg) | 99.4% | 0 | 15/06 01:08 |
| 4  | 66937 (headed, auto-resume + simplificado) | 98.2% | 0 | 15/06 22:xx |

**Nota**: Cada execução cria um NOVO registro. O script não faz upsert.
Execuções headed tendem a capturar 0 modais — provável race condition no polling.

### Consulta manual ao Turso
```bash
python3 -c "
import json, urllib.request
token = open('/tmp/turso_videos_token.txt').read().strip()
db_url = 'https://videos-ava-db-higor-app-dev.aws-us-east-1.turso.io'
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
sql = 'SELECT id, video_id, titulo, progresso_percentual, modais_tratados FROM videos_ava ORDER BY id DESC LIMIT 5'
body = json.dumps({'requests': [{'type': 'execute', 'stmt': {'sql': sql}}]}).encode()
req = urllib.request.Request(f'{db_url}/v2/pipeline', data=body, headers=headers, method='POST')
with urllib.request.urlopen(req) as resp:
    print(json.dumps(json.loads(resp.read()), indent=2))
"
```

### IDs dos Vídeos de Ciências (Semana 8)
- `66937` — Transformações químicas e físicas (6º ano, aula 17)
- `66899` — Doenças crônicas não transmissíveis (8º ano, aulas 21-22)
- `66903` — Seleção natural e cladogramas (9º ano, aulas 23-24)
