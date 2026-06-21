# Playwright Pitfalls

## Headless Chromium EPIPE Crash

**Symptom:** After ~7 minutes of headless operation with video playback, Node.js crashes with:
```
Error: write EPIPE
    at afterWriteDispatched (node:internal/stream_base_commons:159:15)
```

**Root cause:** The pipe between Python and the Chromium process breaks when Chromium consumes too much memory or the video decoder stalls.

**Fix:** Close the browser after the interaction phase. Use plain `time.sleep()` for progress waits that don't need browser interaction.

```python
# BAD: keep browser open for 17-minute wait
await asyncio.sleep(1020)  # crashes

# GOOD: close browser, then wait
await page.context.browser.close()
time.sleep(1020)  # no crash
```

## asyncio.sleep vs time.sleep in async functions

In async Playwright functions, `time.sleep()` blocks the event loop. This prevents the browser pipe from being serviced, leading to timeouts or EPIPE.

- For short waits (<2s): `await asyncio.sleep(n)` — fine
- For long waits with browser closed: `time.sleep(n)` — fine
- For long waits with browser open: use `await page.wait_for_timeout(n)` or batch `await asyncio.sleep(5)` in a loop

## postMessage Polling Kills YouTube Playback

Calling `iframe.contentWindow.postMessage('getCurrentTime')` every 1-2 seconds interferes with YouTube's internal state management in headless mode.

**Fix:** Inject a single `setInterval` that pings every 3-5 seconds and stores the result in `window.__state`. Read from Python with `page.evaluate('window.__state')` which is synchronous.

## dispatchEvent Is Not click()

`element.dispatchEvent(new MouseEvent('click'))` does not trigger all the same paths as `element.click()`. For handlers that check `e.isTrusted`, neither works in automation. Moodle's interactive video plugin is one such case — the `.mark-done` button handler requires `isTrusted: true`.
