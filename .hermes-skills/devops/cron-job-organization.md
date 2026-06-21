---
name: cron-job-organization
description: Organize Hermes cron jobs — unify related ones into a single Python script with mode flags; keep separate jobs when cadences differ. Covers the merge-or-split decision, script architecture, state files, and migration workflow.
domain: devops
triggers:
  - "unify similar cron jobs"
  - "merge cron jobs"
  - "consolidate cron jobs"
  - "too many cron jobs doing related things"
  - "overlapping cron jobs"
  - "cron job organization"
  - "cron job invocation failed"
  - "cron script not found"
  - "data-collection script failed"
  - "pre-run script error"
version: "1.1"
---

# Cron Job Organization (Hermes)

When you have multiple Hermes cron jobs doing related things, the recommended architecture is:

**Unified Python script + mode flags → separate jobs for different cadences.**

## Decision matrix

| Scenario | What to do |
|----------|-----------|
| Same domain, same cadence, both no_agent | **Single job, single script** (e.g. kanban-watchdog-unified.py) |
| Same domain, same cadence, one needs LLM | **Single job, agent-driven** — script does data collection, agent processes |
| Same domain, **different cadences** | **Unified script, separate jobs** — each passes `--mode` to select its function |
| Different domains | Keep separate (no merge needed) |

## Unified script pattern

```python
# ~/.hermes/scripts/<domain>-unified.py

# Modes (CLI args):
#   --check-a   → function A (e.g. watchdog, no_agent mode)
#   --check-b   → function B (e.g. data collection for LLM)

def check_a(): ...
def check_b(): ...

if __name__ == "__main__":
    if "--check-a" in sys.argv[1:]: check_a()
    elif "--check-b" in sys.argv[1:]: check_b()
```

## State files

Each function tracks its own state separately:

```python
STATE_DIR = Path.home() / ".hermes" / "scripts"
STATE_A = STATE_DIR / ".state-a.json"    # or .state-a (plain text)
STATE_B = STATE_DIR / ".state-b.json"    # or .state-b (plain text)
```

Prefix with `.` to keep state files hidden from `ls`. Use JSON for structured state, plain text for simple values (timestamps, hashes).

## Migration workflow

1. `cronjob(action='list')` — find the two (or more) jobs to merge
2. `read_file(~/.hermes/scripts/<script>)` — understand each script
3. Create unified script with `--mode` flags
4. `cronjob(action='remove', job_id=...)` — delete old jobs
5. Create a wrapper script in `~/.hermes/scripts/` (see Pitfalls → "Script invocation fails") and then `cronjob(action='create', script='<wrapper>.sh', ...)` — create replacement(s)

## Pitfalls

### Scheduler behavior

- **`cronjob(action='run')` reschedules, it does NOT execute immediately.** Calling `run` on a job updates its `next_run_at` timestamp but the scheduler only processes jobs on its own tick cycle (typically at coarse intervals — every 30-60s or at the turn of a minute). The job will fire at the new `next_run_at` time, not right away. Do not use `run` as a "run now" button — it's a "reschedule so the next tick picks it up" button.
- **One-shot jobs with very short schedules (`1m`, `30s`) may not fire during an active conversation.** If you need to see immediate output from a cron job, the scheduler is the wrong tool. Use `delegate_task` (with `terminal` toolset) or run the underlying script directly in a terminal instead. If you must use the scheduler, use `every 1m` with `repeat=1` (recurring, one-repeat) rather than the one-shot `1m` syntax — recurring schedules have more reliable tick alignment.
- **The scheduler processes all due jobs at once per tick.** A job scheduled for `20:01:15` and another for `20:01:49` both fire at the same scheduler pass (the first tick after 20:01). Don't assume sub-minute ordering between jobs.

### Script invocation

- **Don't merge no_agent + LLM into a single job** unless you're okay with the LLM firing at the no_agent cadence. LLM calls = token cost even on no-change runs. Keep different-cadence jobs separate.
- **no_agent jobs must exit code 0 with empty stdout** to stay silent when nothing changes. `sys.exit(0)` with no `print()` calls = silent delivery.
- **Test each mode independently** before creating the cron job: `python3 ~/.hermes/scripts/<script>.py --mode-x`
- **State files persist between runs** — after deleting an old job, its state file still exists and the new script picks up where it left off. That's usually correct, but if you want a fresh start, delete the state file too.
- **Old scripts** (bash, older versions) aren't auto-deleted. After migrating, confirm the user wants them removed.
- **Script invocation fails with 'Script not found' despite existing on disk** → the cron job's `script` field was set to a concatenated string like `"script.py --flag"`. The Hermes cron system treats the `script` field as a single file path — there is no separate `args` field in `jobs.json`. The scheduler looks for a file literally named `script.py --flag` (with spaces). To pass arguments, create a wrapper shell script in `~/.hermes/scripts/`:
  ```bash
  # ~/.hermes/scripts/my-wrapper.sh
  #!/bin/bash
  python3 ~/.hermes/scripts/real-script.py --flag
  ```
  Then set `"script": "my-wrapper.sh"` in the cron job. This is the established pattern — see `gitagent-check-git.sh` and `gitagent-check-hermes-sync.sh` for working examples.
- **`cronjob(action='create')` stores the `script` field literally** — if you pass `script='script.py --flag'`, it goes into `jobs.json` as-is with no splitting or wrapper creation. The same "Script not found" error occurs on the scheduler side. Always provide a bare script path and use a wrapper for arguments.
- **Pre-run data-collection script failure doesn't mean the session is blocked** → if the cron job's data-collection step (e.g. `--check-knowledge`) fails to run, manually execute it: `python3 ~/.hermes/scripts/<script>.py --mode <flag>`. The script on disk likely works fine — only the cron invocation was wrong. Use the manual output to proceed with the LLM sync rather than aborting.
- **Always verify the script independently** before assuming the cron definition is the problem. Run it directly in terminal: `cd /home/higor && python3 ~/.hermes/scripts/<script>.py --<mode>`. If it works in terminal but not in cron, the definition needs fixing, not the script.

## References

- `references/gitagent-unified-architecture.md` — GitAgent unified script design and two-job architecture (watchdog 15min + knowledge sync 6h)
- `references/kanban-unified-architecture.md` — Kanban watchdog unified script design
- `references/cron-invocation-troubleshooting.md` — Full troubleshooting guide for "Script not found" errors, wrapper script pattern, `jobs.json` structure reference, and LLM session fallback procedure
- `references/cron-scheduler-behavior.md` — How the Hermes cron scheduler actually works (ticks, `run` action semantics, schedule types, testing strategies, and tool-missing fallbacks)
