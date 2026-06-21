---
name: hermes-server-lock
description: "Atomic port-based lock system for concurrent agents — prevents conflicts on dev servers, builds, and deploys across parallel Hermes sessions."
version: 1.0.0
author: Hermes Agent
tags: [dev-server, build, lock, port, queue, concurrent, multi-agent]
---

# hermes-server Lock System

Prevents multiple agents from starting servers or builds on the same port simultaneously. Uses atomic `mkdir` (no race conditions on Linux/WSL).

## How It Works

Before starting ANY dev server, build process, or deploy that binds to a port:

1. **Lock the port** — `hermes-server lock <PORT> "<purpose>"`
   - Returns `OK` immediately if free
   - Returns `BUSY` with agent info if someone else holds it

2. **Do your work** — start the server / run the build

3. **Unlock when done** — `hermes-server unlock <PORT>`

## Key Principle

**Lock first, then start.** Never start a server or build without acquiring the lock. The lock is your safety check that no other agent is using that port.

## Recommended: `hermes-server-exec` (lock + exec + auto-unlock)

The easiest way: instead of running commands directly, wrap them:

```bash
# Dev server — lock :3000, run command, unlock on exit
hermes-server-exec 3000 next dev -p 3000

# Build
hermes-server-exec 3000 next build

# Production server
hermes-server-exec 8421 next start -p 8421
```

The wrapper automatically locks the port before executing and **unlocks on exit** (success, failure, Ctrl+C, or signal). No manual unlock needed.

## Direct Commands

| Command | What it does |
|---------|-------------|
| `hermes-server lock <PORT> [purpose]` | Acquire lock. Fails if held. |
| `hermes-server wait <PORT> [timeout_s] [purpose]` | Wait up to N seconds for lock. |
| `hermes-server unlock <PORT>` | Release lock. |
| `hermes-server status [PORT]` | Show all locks (or one port). |
| `hermes-server unlock-stale [max_age_min]` | Remove locks older than N minutes (default: 10). |

Locks live in `~/.hermes/locks/port-<N>.lock/` and contain an `.info` file with agent ID, timestamp, purpose, and hostname.

## Examples

### Dev server (long-running — lock held until stopped)
```bash
# Before starting dev server:
hermes-server lock 3000 "next dev hermes-dash"
# start server...
next dev -p 3000 &
# When done / server crashes:
hermes-server unlock 3000
```

### Build (short-lived — lock during build)
```bash
hermes-server lock 3000 "next build hermes-dash"
next build && next start -p 3000
hermes-server unlock 3000
```

### Wait for port (up to 2 minutes)
```bash
hermes-server wait 3000 120 "next dev" && next dev -p 3000
```

### Check what's locked
```bash
hermes-server status
```

## Stale Lock Cleanup

If an agent crashes mid-operation, the lock persists. Clean up manually:
```bash
hermes-server unlock-stale    # removes locks older than 10 min
hermes-server unlock-stale 5  # removes locks older than 5 min
```

## Project Versioning

When a project depends on `hermes-server-lock`, **commit the scripts into the project repo** so they're versioned and available to all agents working on that project:

```bash
mkdir -p scripts/hermes-server-lock/
cp ~/.local/bin/hermes-server      scripts/hermes-server-lock/
cp ~/.local/bin/hermes-server-exec scripts/hermes-server-lock/
cp ~/.hermes/skills/devops/hermes-server-lock/SKILL.md  scripts/hermes-server-lock/
git add scripts/hermes-server-lock/
git commit -m "chore: versiona hermes-server-lock no repo"
```

From the project root, other agents can use them directly via `./scripts/hermes-server-lock/hermes-server lock 3000`.

## Stale Build Cache

If a `next build` or similar build was interrupted and you get errors like `ENOENT: no such file or directory, open '.next/static/.../_buildManifest.js.tmp'`, the `.next/` cache is corrupted. Clean it before retrying:

```bash
rm -rf .next && npm run build
```

Add this as the first troubleshooting step whenever a build fails with ENOENT inside `.next/`.

## Pitfalls / Anti-patterns

- **Don't start a server without locking first** — you'll race with other agents
- **Don't forget to unlock** — on failure, use `hermes-server unlock-stale` or an explicit unlock
- **Don't lock unrelated ports** — only lock the port you're actually using
- **Lock per port, not per project** — the system is port-based, not project-based
- **`hermes-server-exec` com `background=true` pode liberar o lock mas deixar a porta ocupada** — quando um servidor `next start` ou `next dev` é iniciado via `hermes-server-exec` em background e depois terminado (exit 137 = SIGKILL), o wrapper vê a saída do shell e executa o auto-unlock. Mas o processo filho `next-server` pode continuar vivo segurando a porta. **Sempre verifique** `ss -tlnp | grep <PORT>` após qualquer servidor em background, mesmo que o lock tenha sido liberado.
- **Don't retry a failed build without cleaning `.next/` first** — a partially-written cache from an interrupted build causes cryptic ENOENT errors on retry
- **`fuser -k` (SIGTERM) may not free the port** — if a process has a child that inherited the socket (e.g., `sh -c next start` where the shell dies but the next server keeps the port), `fuser -k 8421/tcp` reports success but the port stays occupied. Always verify with `ss -tlnp | grep 8421` after kill, and use `fuser -k -9 8421/tcp` (SIGKILL) if still held.
