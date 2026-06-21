"""Template for Playwright-based browser automation in Hermes background processes.

This is a scaffold. Adapt the login, URL, and interaction logic for your target site.

Key patterns to preserve:
- asyncio + playwright async API
- print(flush=True) + log file for Hermes process monitoring
- headless=True with autoplay-policy flag
- Modal detection with overlay check (position:fixed/absolute + z-index)
- Dual progress sources (plugin-native + YouTube API where applicable)
"""

import asyncio
import json
import sys
from playwright.async_api import async_playwright

# ==== CONFIG ====
LOG_FILE = "/home/higor/.hermes/scripts/automation_log.txt"

def log(msg):
    line = f"[{msg}]"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
        f.flush()

async def login(page, login_url, username, password):
    """Template: adapt selectors to your target site."""
    await page.goto(login_url, wait_until="networkidle")
    await page.fill("#username", username)
    await page.fill("#password", password)
    await page.click("#loginbtn")
    await page.wait_for_load_state("networkidle")
    # Validate login succeeded
    await page.wait_for_selector("text=Bem-vindo", timeout=10000)
    log("✅ Login OK")

async def check_for_modal(page):
    """Detect and handle overlays/dialogs. Returns dict or None."""
    info = await page.evaluate("""() => {
        const candidates = document.querySelectorAll(
            '[role="dialog"], [aria-modal="true"], [class*="modal"], ' +
            '[class*="overlay"], [class*="popup"]'
        );
        for (const m of candidates) {
            if (m.offsetParent === null && m.offsetWidth === 0) continue;
            // Only overlays, not page content
            const pos = window.getComputedStyle(m).position;
            const zIdx = parseInt(window.getComputedStyle(m).zIndex) || 0;
            if (pos !== 'fixed' && pos !== 'absolute' && zIdx < 100) continue;
            return { id: m.id, text: m.textContent.trim().substring(0, 200) };
        }
        return null;
    }""")
    if info:
        log(f"📋 Modal detectado: {info.get('text','')[:80]}")
        # Try clicking buttons - adapt priority order
        for btn_text in ["Concluído", "Concluir", "OK", "Fechar", "Continuar"]:
            clicked = await page.evaluate(f"""txt => {{
                const btn = document.querySelector('button, input[type="submit"]');
                if (btn && btn.textContent.trim().toLowerCase().includes(txt.toLowerCase())) {{
                    btn.click(); return true;
                }}
                return false;
            }}""", btn_text)
            if clicked:
                log(f"   ✅ Clicou: {btn_text}")
                await asyncio.sleep(1)
                return True
        # Fallback: ESC
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
        return True
    return False

async def main():
    # ==== LAUNCH BROWSER ====
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--autoplay-policy=no-user-gesture-required',
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            locale='pt-BR'
        )
        page = await context.new_page()

        # ==== YOUR LOGIC HERE ====
        # await login(page, "https://example.com/login", "user", "pass")
        # await page.goto("https://example.com/target")

        # Main loop template
        while True:
            await asyncio.sleep(3)
            
            # Handle any modals
            await check_for_modal(page)
            
            # Check progress / do work
            # ...
            
            # Exit condition
            # if done: break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
