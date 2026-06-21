# Playwright E2E Test Selector Patterns

Writing robust selectors that resist strict-mode violations and flaky assertions.

## The Enemy: Broad Regex Selectors

```ts
// ❌ BAD — matches multiple elements → strict mode violation
await expect(page.getByText(/Profiles|Providers|Models|Secrets/)).toBeVisible();
await expect(page.getByText(/deepseek|openai/i)).toBeVisible();
await expect(page.getByRole("link", { name: "Sessões" })).toBeVisible();
await expect(page.getByText(/web_search|image_gen/i)).toBeVisible();
await expect(page.getByText(/Checkpoints/)).toBeVisible();
```

These fail because:
- `getByText(/Profiles|Providers|.../)` matches sidebar links AND page content
- `getByRole("link", { name: "Sessões" })` matches the sidebar link AND "Ver todas as sessões →"
- `getByText(/web_search|image_gen/)` uses internal IDs, but the page shows display names ("Web Search", "Image Generation")

## Fix Patterns

### 1. `.first()` — disambiguate when first match suffices

```ts
// ✅ GOOD — takes the first matching element
await expect(page.getByText(/Profiles|Providers|Models|Secrets/).first()).toBeVisible();
await expect(page.getByText(/deepseek|openai/i).first()).toBeVisible();
await expect(page.getByText(/hermes-dash|shadcn/).first()).toBeVisible();
```

Use when: the regex matches N elements but you just need to confirm the content exists on the page.

### 2. `exact: true` — match only exact accessible names

```ts
// ✅ GOOD — only matches the sidebar link, not "Ver todas as sessões →"
await expect(page.getByRole("link", { name: "Sessões", exact: true })).toBeVisible();
```

Use when: a partial name match catches the right role but wrong element. `exact: true` limits to elements whose accessible name equals the string exactly.

### 3. `getByRole('heading')` — target headings explicitly

```ts
// ✅ GOOD — unambiguous, targets the heading element
await expect(page.getByRole("heading", { name: "Checkpoints" })).toBeVisible();
// ❌ BAD — matches sidebar link AND heading
await expect(page.getByText(/Checkpoints/)).toBeVisible();
```

Use when: the assertion is about a page title / heading. Always prefer `getByRole('heading')` over `getByText(/regex/)` for headings.

### 4. Use display text, not internal IDs

```ts
// ❌ BAD — "web_search" is an internal ID, not what the user sees
await expect(page.getByText(/web_search|image_gen/i)).toBeVisible();
// ✅ GOOD — "Web Search" is what's actually rendered
await expect(page.getByText("Web Search")).toBeVisible();
```

Use when: verifying that content appears on screen. Match the rendered text, not internal identifiers.

### 5. `getByText("exact string")` — avoid regex when exact works

```ts
// ✅ GOOD — exact string, no ambiguity
await expect(page.getByText("Web Search")).toBeVisible();
// ❌ BAD — broad regex that could match too much
await expect(page.getByText(/Web/i)).toBeVisible();
```

## Dev Server + Playwright Coordination

### Port conflicts

When the dev server is already running and Playwright tries to start a new one:

```ts
// playwright.config.ts
webServer: {
  command: "npm run dev",
  port: 8421,
  reuseExistingServer: true,  // ✅ Skips start if port is already open
}
```

Set `reuseExistingServer: true` during development, revert to `false` for CI.

### Freeing a stuck port

```bash
fuser -k 8421/tcp          # kills whatever is on the port
```

### Dev server crashes mid-test

Next.js dev + Turbopack can crash with hydration errors or CSS corruption. Signs:
- Tests 1-2 pass, then everything fails with 404
- WebServer error in output with hydration mismatch stack trace
- `curl -I http://localhost:8421/page` returns 200 but Playwright gets 404 on the same page (race condition)

Mitigation:
- Run `npx next dev --no-turbopack` (if flag is supported) or just `npx next dev`
- Pre-build with `npx next build && npx next start` for CI/reliable runs
- Use `reuseExistingServer: true` and start the dev server manually first to isolate issues

## When All Pages Return 404 Mid-Run

If tests 1-2 pass and all subsequent tests fail with 404 on internal pages:
1. The dev server probably crashed (check `process(action='poll')` or `process(action='log')`)
2. Kill the old process: `fuser -k 8421/tcp`
3. Restart: `cd project && npm run dev &`
4. Verify pages are back: `curl -s -o /dev/null -w '%{http_code}' http://localhost:8421/sessions`
5. Re-run tests
