# AVA-EFAPE Automation

Platform: `https://avaefape.educacao.sp.gov.br` — Moodle with `mod_interactivevideo` plugin.

## Login

```
CPF: 34048787870
Senha: Rm62103970@
```

Use Playwright to fill `#username`, `#password`, click `#loginbtn`, wait for `text=Olá, Ródiney`.

## Interactive Video Plugin Internals

### Key Globals
- `window.IVANNO` — array of all 13 annotations (chapters, interactions, analytics, etc.)
- `window.IVPLAYER` — player instance with `type: "yt"`, `videoId`, `start`, `end`, `totaltime`
- `require.s.contexts._.defined['mod_interactivevideo/displaycontent']` — content display module

### Annotation Types
| Type | Has Modal | Button to Click |
|------|-----------|-----------------|
| `richtext` | `#message.modal-dialog.active` | "Marcar como concluído" / "Concluído" |
| `poll` | `#message.modal-dialog.active` | "Marcar como concluído" / "Enviar" |
| `courseactivity` | `#message.modal-dialog.active` | "Marcar como concluído" |
| `form` | `#message.modal-dialog.active` | "Marcar como concluído" |
| `chapter` | No modal | N/A (navigation only) |
| `analytics` | No modal | N/A |

### Showing an Interaction Programmatically
```javascript
const annotation = IVANNO.find(a => a.id == '39247');
const ctx = require.s.contexts._;
const dc = ctx.defined['mod_interactivevideo/displaycontent'];
await dc.defaultDisplayContent(annotation, IVPLAYER);
// Modal appears as #message.modal-dialog.active
```

### The Completion Persistence Problem (UNSOLVED)
Clicking "Marcar como concluído" via `element.click()` or `dispatchEvent(MouseEvent)` **closes the modal but does NOT persist** to the server. The annotation remains `completed: false` in `IVANNO` and the course sidebar still shows "Pendente".

**Attempted fixes (all failed):**
- `dispatchEvent(new MouseEvent('click', {bubbles:true}))` — no effect
- `dispatchEvent` with mousedown + mouseup + click sequence — no effect
- Direct AJAX to `/mod/interactivevideo/ajax.php?action=togglecompletion` — no effect
- AJAX with POST body `annotationid=X&sesskey=Y&id=Z` — no effect

The plugin's JavaScript handler (likely jQuery delegation on `.mark-done` class) requires a real user interaction (`e.isTrusted === true`) or a specific event path not replicable via Playwright's `click()`.

## Script

Location: `~/.hermes/scripts/assistir_video_ava.py`

Current approach (v6):
1. Login + navigate to video
2. Wait for `IVANNO` to be defined
3. Loop through pending annotations, call `defaultDisplayContent`, click button
4. Close browser (avoids EPIPE crash)
5. `time.sleep` for progress wait (timer-based, no browser)

**Known limitation:** Completion does not persist to server. The script processes all 7 interactions successfully but the course remains "Pendente".

## Video Data (Semana 8 de junho - Ciências)

Video ID: 66937
Duration: 1054.75s (~17:35)
Interactions: 8 total, 7 pendentes (1 já concluída: "Objetivos de aprendizagem")

| Timestamp | ID | Type | Name |
|-----------|-----|------|------|
| 11s | 39238 | richtext | Objetivos de aprendizagem ✅ |
| 220s | 39247 | courseactivity | Diagnóstico da turma |
| 786s | 39241 | poll | Foco na aula: atividade 1 |
| 788s | 39240 | richtext | Reflexão |
| 1046s | 39243 | poll | Foco na aula: atividade 2 |
| 1048s | 39244 | richtext | Reflexão |
| 1050s | 39246 | courseactivity | Plano de aula: Sala de edição |
| 1053.75s | 39245 | form | Pesquisa de satisfação |
