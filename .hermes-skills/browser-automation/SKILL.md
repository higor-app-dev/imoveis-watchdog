---
name: browser-automation
description: Browser automation with Playwright — login flows, modal interaction, JavaScript API discovery, and platform-specific patterns.
triggers:
  - "automatizar login"
  - "automatizar navegação"
  - "Playwright script"
  - "interactive video"
  - "Moodle plugin"
  - "AVA-EFAPE"
  - "click programático"
  - "headless crash"
---

# Browser Automation

Patterns, pitfalls, and workflows for automating browser interactions with Playwright.

## Core Workflow

1. Launch browser headless (add `--autoplay-policy=no-user-gesture-required` for video)
2. Login → navigate → interact
3. Close browser promptly after interaction phase (EPIPE crash risk on long-lived sessions)

## Key Pitfalls

### 1. Headless Chromium EPIPE Crash
Headless Chromium crashes with `Error: write EPIPE` after ~7 minutes of continuous operation, especially with video playback. **Close the browser after the interaction phase and use `time.sleep` for progress waits.**

### 2. Programmatic Clicks vs Real Events
`element.click()` and `dispatchEvent(new MouseEvent('click', ...))` may NOT trigger JavaScript handlers that check `e.isTrusted` or use event delegation. For Moodle interactive video plugin, this is the #1 cause of "button clicked but nothing happened."

### 3. Moodle Interactive Video Plugin API
The plugin exposes `window.IVANNO` (annotations array) and `window.IVPLAYER` (player instance). Use `require.s.contexts._.defined['mod_interactivevideo/displaycontent'].defaultDisplayContent(annotation, IVPLAYER)` to show interaction modals programmatically.

See `references/ava-efape.md` for platform-specific patterns.

### 4. YouTube PostMessage Polling Kills Playback
Calling `iframe.contentWindow.postMessage(getCurrentTime)` in a tight loop interferes with YouTube playback. For progress tracking, inject a single `setInterval` that updates a global variable once every 1.5–3 seconds, and read that variable from Python.

## Cloudflare / Bot-Detection Bypass

When the Hermes browser tool (Browserbase) gets blocked by Cloudflare or bot-detection, fall back to **local Playwright** (already installed in the Hermes venv). The local browser has a different fingerprint and often passes where the cloud browser doesn't.

### Fallback Strategy

```
Web_extract → Browserbase (Hermes browser tool) → Local Playwright → curl (headers)
```

Try each method in order. Local Playwright is the best fallback for Cloudflare-heavy sites (OLX).

### Local Playwright Stealth Config

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR"
        )
        # Remove headless detection vectors
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en'] });
        """)
        page = await context.new_page()
        # ... navigate and interact
```

### 5. Browserbase + Turbopack (Next.js) — JS não executa

O Hermes browser tool (Browserbase) **não executa corretamente JavaScript bundlado com Turbopack** (Next.js 15+ com build padrão). A página HTML estática carrega, os chunks `.js` são baixados (200 OK, Content-Type correto), mas o runtime do Turbopack nunca inicializa — `React`, `ReactDOM`, e `globalThis.TURBOPACK._` ficam indefinidos.

**Sintoma:** A página fica travada em "Carregando..." — o estado inicial `useState({loading: true})` nunca atualiza porque o `useEffect` de fetch nunca roda.

**Causa:** O `globalThis.TURBOPACK.push(...)` registra módulos, mas o bootstrap assíncrono que executa os callbacks nunca dispara no ambiente Browserbase.

**Solução:** Para verificar Next.js dashboards, **use Playwright local** (`require('playwright').chromium.launch({ headless: true })` em vez do Hermes browser tool.

```node
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:8421/sessions', { waitUntil: 'networkidle' });
  const count = await page.locator('a[href*=\"/sessions/\"]').count();
  console.log(count + ' session links');
  await browser.close();
})();
```

### 6. SPA Handling (Next.js / React)

OLX, QuintoAndar and similar SPAs load listings via JavaScript — the initial HTML is empty:

- Use `wait_until="domcontentloaded"` (NOT `networkidle` — SPAs keep loading resources indefinitely)
- Search results may need **UI interaction** (clicking categories, filling search) instead of direct filtered URLs
- OLX redirects `sp.olx.com.br` to `www.olx.com.br` — start from homepage and navigate
- `networkidle` times out on SPAs — use `domcontentloaded` + `await page.wait_for_timeout(3000)` instead
- When Playwright can't extract listings (0 matches in DOM), screenshot the page to verify

### Portal-Specific Notes for Brazilian Real Estate

| Portal | Access Method | Notes |
|--------|--------------|-------|
| **Loft** | Browser tool ✅ | Works directly, no Cloudflare |
| **Viva Real** | web_extract ✅ | Works for general page data; filtered URLs return 404 |
| **QuintoAndar** | Browser tool ✅ | City + type URLs work directly. Next.js data route returns structured JSON (`/_next/data/<buildId>/...json`). SPA ignores bairro/price URL params — use browser interaction for those filters. ~14 listings per SSR page. See `references/portal-fallback-chain.md` for full API/structure. |
| **OLX** | Local Playwright (partial) | SPA — needs UI navigation, listings not in initial DOM |
| **ZAP Imóveis** | ❌ Cloudflare | Blocks both Browserbase and local Playwright |
| **SP Imóvel** | ❌ 403 | Blocks all access |
| **Mercado Livre** | ❌ Error | Returns Hubo un error page |

## Absorbed: Playwright Deep Patterns

The following Playwright-specific detailed patterns were absorbed from sibling skills into this umbrella.

### Modal Detection (Critical — from `playwright-automation`)

The #1 failure mode in automated browser scripts is **false positive modal detection** — treating normal page content as a dialog.

**Correct Filter: Overlay Check**
```python
const pos = window.getComputedStyle(m).position;
const zIdx = parseInt(window.getComputedStyle(m).zIndex) || 0;
const isOverlay = pos === 'fixed' || pos === 'absolute' ||
                  zIdx > 100 || m.hasAttribute('aria-modal');
if (!isOverlay) continue;
```

Elements in normal document flow (`position: static/relative`, z-index < 100) are **not modals** — skip them.

**Known False Positives to Filter:**

| Element | Filter |
|---------|--------|
| "Clique para entender como navegar..." help section | `'clique para entender' in texto` |
| Notification panels | `'notificaç' in texto and buttons ≤ 3` |
| Moodle "Tarefas: Concluir: 100% das interações" | `'tarefas:' in texto and '100%' in texto` |
| Course sections with "Iniciar"/"Não iniciado" | `'não iniciado' in texto or ('iniciar' in texto and not isOverlay)` |

**CSS Selector Trap:** `[class*="activity"]` matches too broadly in Moodle. Always pair with the overlay check.

**Button Priority:** "Concluído"/"Concluir" (exact) → "OK"/"Continuar"/"Fechar" → any visible button → ESC. **Never use substring match** "concluí" (catches "Planejamentos Concluídos" nav link).

### YouTube Iframe Control

For embedded YouTube videos (controls=0, custom player overlay):

```python
# Play via postMessage
iframe.contentWindow.postMessage(
    '{"event":"command","func":"playVideo","args":""}', '*'
)
```

**Auto-Resume (Critical for YouTube):** Without auto-resume, the video stalls within 30-60s. Set up BEFORE the main monitoring loop:

```python
await page.evaluate("""() => {
    window.addEventListener('message', function(e) {
        try {
            const data = typeof e.data === 'string' ? JSON.parse(e.data) : e.data;
            if (data.event === 'onStateChange' && data.info === 2) {
                setTimeout(() => {
                    const yt = document.getElementById('player');
                    if (yt && yt.contentWindow)
                        yt.contentWindow.postMessage(
                            '{"event":"command","func":"playVideo","args":""}', '*');
                }, 500);
            }
        } catch(ex) {}
    });
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            const yt = document.getElementById('player');
            if (yt && yt.contentWindow)
                yt.contentWindow.postMessage(
                    '{"event":"command","func":"playVideo","args":""}', '*');
        }
    });
}""")
```

### Dual Progress Monitoring (from `playwright-web-automation`)

Many interactive video systems have **two separate progress trackers** — always check BOTH:

| Tracker | Mechanism | What it tracks |
|---------|-----------|----------------|
| **Client (YouTube API)** | `postMessage` to iframe | Video playback time / percentage |
| **Server (Moodle plugin)** | Plugin's UI counters | Chapters completed / activities done |

The YouTube reaching 98% does NOT mean the server saved the progress. The plugin must independently confirm.

### Script Structure for Background Execution

```python
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-gpu',
                  '--autoplay-policy=no-user-gesture-required']
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800}, locale='pt-BR'
        )
        page = await context.new_page()
        # ... work ...
        await browser.close()
asyncio.run(main())
```

**Logging:** Use `print(..., flush=True)` AND write to a log file so the background process output is visible both via Hermes process tool and on disk.

### Additional Pitfalls

- `button:text-is("texto")` is CASE-SENSITIVE and requires exact match. Use `has-text` for partial.
- f-strings with backslashes cause SyntaxError in Python. Store escaped value in a variable first.
- YT API state=2 is paused; state=1 is playing; state=-1/0 is unstarted.
- Multiple script runs leave orphaned Chrome processes. Track PID or kill before restart.
- Auto-resume can prevent modal detection. Add 3-5s delay before re-playing when progress is stalled to give modals time to appear.
- `headless=False` in WSL requires WSLg or X server. Confirmed working on this WSL2 setup.

## Additional Reference Files

- `references/browser-ava-efape.md` — AVA-EFAPE platform specifics (IVANNO API, interaction types, script)
- `references/playwright-pitfalls.md` — Common Playwright failures and workarounds
- `references/portal-fallback-chain.md` — Brazilian real estate portal access patterns, Cloudflare bypass results, and fallback chains for each portal
- `references/e2e-test-selectors.md` — Writing robust Playwright test assertions (strict mode, exact text, getByRole)
- `references/test-video-concat.md` — Concatenating Playwright test result videos with ffmpeg
- `references/playwright-ava-efape.md` — AVA-EFAPE patterns from playwright-automation skill
- `references/ava-efape-moodle-iv.md` — AVA-EFAPE Moodle Interactive Video specifics
- `templates/playwright-automation-scaffold.py` — Reusable Python scaffolding for Playwright automation scripts
