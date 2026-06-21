# AVA-EFAPE + Moodle Interactive Video

Platform-specific quirks and patterns for the Brazilian AVA-EFAPE education platform (Moodle-based).

## Platform info

- **URL**: `https://avaefape.educacao.sp.gov.br/`
- **Login**: CPF (username) + password
- **CMS**: Moodle with `mod_interactivevideo` plugin
- **Video player**: YouTube embed via iframe (`id="player"`), custom HTML overlay

## Login flow

```python
await page.fill("#username", CPF)
await page.fill("#password", SENHA)
await page.click("#loginbtn")
await page.wait_for_load_state("networkidle")
# Verify: await page.wait_for_selector('text=Olá, Ródiney', timeout=10000)
```

## Video page structure

The page has two progress indicators:

### 1. Plugin sidebar metadata (ground truth)
```
17m 35s          # duration
1 / 8            # chapters completed / total
0 / 0            # activities completed / total
```
The chapter list (right sidebar) shows:
- "Iniciar" at 00:00
- "Para começar: Alinhando desafios" at 00:08
- "Foco na aula: Modelando o raciocínio" at 03:49 (with "atividade 1")
- "Foco na aula: Compartilhando estratégias e insights" at 13:14 (with "atividade 2", "Plano de aula: Sala de edição")

Completion = chapters show 8/8.

### 2. YouTube iframe (client tracking)
- Iframe src: `https://www.youtube.com/embed/<VIDEO_ID>?autoplay=0&hl=pt_br&start=0&end=<DURATION>&controls=0`
- `controls=0` means plugin manages playback — never use native YT controls
- YouTube at 98% does NOT equal server-side completion

## Play button priority

1. Plugin's "Reproduzir vídeo" button (initial screen overlay)
2. Plugin's Play/Pause button via aria-label
3. YouTube iframe postMessage (fallback)

## Modal handling specifics

The AVA-EFAPE mod_interactivevideo plugin fires modals at specific timestamps:

| Modal type | Button to click |
|------------|-----------------|
| Informational ("Objetivos de aprendizagem") | "Concluído" |
| Section headers ("Para começar...") | "Concluído" |
| Activity prompts ("atividade 1") | "Concluído" |
| "Plano de aula: Sala de edição" | Open file (just accessing is sufficient) |
| Survey/Pesquisa | "Concluído" |

**Key rule**: Always click the named button. Never press Escape. Escape bypasses the server-side completion flag for that modal.

## Script structure

The automation script (`~/.hermes/scripts/assistir_video_ava.py`) follows this flow:

1. Login → navigate to video URL
2. Setup auto-resume (YouTube postMessage listener for pause events)
3. Click "Reproduzir vídeo" 
4. Loop:
   a. Check for activity modals (with 8s cooldown between checks)
   b. Check plugin progress (chapters/activities counters in sidebar)
   c. Check YouTube progress via postMessage
   d. If stalled >30s, re-send play command
   e. Every ~45s, send keepalive play command
5. When YouTube >= 98% OR plugin shows 8/8 chapters:
   a. Wait up to 30s for plugin to confirm
   b. Save to database
   c. Return

## Database schema (Turso Cloud)

```sql
CREATE TABLE videos_ava (
    id INTEGER PRIMARY KEY,
    video_id TEXT,
    titulo TEXT,
    disciplina TEXT,
    ano_escolar TEXT,
    aula TEXT,
    duracao_segundos INTEGER,
    url TEXT,
    progresso_percentual REAL,
    atividades_total INTEGER,
    atividades_completadas INTEGER,
    modais_tratados INTEGER,
    perguntas TEXT,          -- JSON array
    perguntas_markdown TEXT,  -- Markdown formatted
    data_inicio DATETIME,
    data_conclusao DATETIME,
    status TEXT,
    created_at DATETIME
);
```

## Known video IDs (Semana 8 de junho - Ciências)

| Title | ID |
|-------|----|
| Transformações químicas e físicas (6º ano) | 66937 |
| Doenças crônicas não transmissíveis (8º ano) | 66899 |
| Seleção natural e cladogramas (9º ano) | 66903 |

## Turso connection

```python
db_url = "https://videos-ava-db-higor-app-dev.aws-us-east-1.turso.io"
# Token stored at /tmp/turso_videos_token.txt
# Auth: Bearer token in Authorization header
# Pipeline API: POST {db_url}/v2/pipeline with JSON body
```
