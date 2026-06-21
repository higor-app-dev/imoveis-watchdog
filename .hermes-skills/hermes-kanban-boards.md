---
name: hermes-kanban-boards
description: "Create and manage kanban boards in Hermes Agent — board.json structure, SQLite schema, and the filesystem-level workflow for adding new boards."
version: 1.6.0
author: agent
---

# Hermes Kanban Boards

Kanban boards in Hermes Agent are filesystem-level constructs — each board is a directory under `~/.hermes/kanban/boards/<slug>/` with a `board.json` config file and an SQLite database (`kanban.db`).

Existing boards are auto-discovered by scanning the directory; there is no registry or config entry to update.

## Creating a New Board

### Inspect board.json

```bash
cat ~/.hermes/kanban/boards/<slug>/board.json
```

## Active Board Selection (Before Creating Tasks)

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

Once the board exists and the active board is set correctly, create tasks via the CLI:

```bash
hermes kanban create "Task title" --body "Description" --assignee default --tenant <slug>
```

Tasks are written into `kanban.db` of the **active board** automatically — no manual SQL needed.

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

When tasks should wait for user review before the dispatcher picks them up, use `--triage` on creation:

```bash
hermes kanban create "Task title" --body "Description" --triage --priority 1 --assignee default
```

This sets the task's initial status to `triage` (backlog) instead of `ready`. The dispatcher ignores triage tasks entirely — they stay parked until promoted.

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

### 2. Write board.json

```json
{
  "slug": "my-project",
  "name": "My Project",
  "description": "A short description of the project",
  "icon": "🔤",
  "color": "",
  "default_workdir": "/home/user/my-project",
  "created_at": 1782144000,
  "archived": false
}
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Unique identifier (lowercase, hyphens). Used by the kanban CLI and hermes-dash routing. |
| `name` | string | Human-readable board name |
| `description` | string | Short project description |
| `icon` | string | Emoji icon (optional, hermes-dash displays it) |
| `color` | string | Color tag (optional, unused by default) |
| `default_workdir` | string | Working directory for tasks on this board — worker agents use this path. **Do not write this into kanban.db** (the hermes-dash user corrected this explicitly: workspace de board usa default_workdir do board.json, não escreve no kanban.db). |
| `created_at` | int | Unix timestamp. Use `$(date +%s)` for current time. |
| `archived` | bool | If true, the board is hidden from dashboards and CLI listings. |

### 3. Create kanban.db

The database requires 5 tables. Create it with any language that has SQLite bindings (Python, Go, Node.js via better-sqlite3).

**Python (sqlite3 — stdlib):**

```python
import sqlite3, os, json

board_dir = os.path.expanduser("~/.hermes/kanban/boards/<slug>")
db_path = os.path.join(board_dir, "kanban.db")
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.executescript("""
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    assignee TEXT,
    status TEXT NOT NULL DEFAULT 'triage',
    priority INTEGER DEFAULT 0,
    tenant TEXT,
    created_by TEXT,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'local',
    workspace_path TEXT,
    skills TEXT,
    result TEXT,
    session_id TEXT
);
CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_id INTEGER,
    kind TEXT NOT NULL,
    payload TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    profile TEXT,
    step_key TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    claim_lock TEXT,
    started_at INTEGER,
    completed_at INTEGER,
    workspace_kind TEXT,
    workspace_path TEXT,
    model_override TEXT
);
CREATE TABLE IF NOT EXISTS task_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    skill TEXT NOT NULL
);
""")

conn.commit()
conn.close()
```

**Node.js (better-sqlite3, same DDL — for hermes-dash API routes):**

The same DDL is used in `src/lib/kanban-db.ts`. See `references/kanban-board-schema.md` for column-by-column annotations.

### 4. Verify

```bash
# Check the files exist
ls -la ~/.hermes/kanban/boards/<slug>/
# Expected: board.json, kanban.db

# Check tables were created
sqlite3 ~/.hermes/kanban/boards/<slug>/kanban.db ".tables"
# Expected: tasks, task_comments, task_events, task_runs, task_skills
```

## Managing Boards

### Inspect board.json

```bash
cat ~/.hermes/kanban/boards/<slug>/board.json
```

## Active Board Selection (Before Creating Tasks)

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

Once the board exists and the active board is set correctly, create tasks via the CLI:

```bash
hermes kanban create "Task title" --body "Description" --assignee default --tenant <slug>
```

Tasks are written into `kanban.db` of the **active board** automatically — no manual SQL needed.

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

When tasks should wait for user review before the dispatcher picks them up, use `--triage` on creation:

```bash
hermes kanban create "Task title" --body "Description" --triage --priority 1 --assignee default
```

This sets the task's initial status to `triage` (backlog) instead of `ready`. The dispatcher ignores triage tasks entirely — they stay parked until promoted.

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

Edit `board.json` and set `"archived": true`.

### Inspect board.json

```bash
cat ~/.hermes/kanban/boards/<slug>/board.json
```

## Active Board Selection (Before Creating Tasks)

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

Once the board exists and the active board is set correctly, create tasks via the CLI:

```bash
hermes kanban create "Task title" --body "Description" --assignee default --tenant <slug>
```

Tasks are written into `kanban.db` of the **active board** automatically — no manual SQL needed.

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

When tasks should wait for user review before the dispatcher picks them up, use `--triage` on creation:

```bash
hermes kanban create "Task title" --body "Description" --triage --priority 1 --assignee default
```

This sets the task's initial status to `triage` (backlog) instead of `ready`. The dispatcher ignores triage tasks entirely — they stay parked until promoted.

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

### Inspect board.json

```bash
cat ~/.hermes/kanban/boards/<slug>/board.json
```

## Active Board Selection (Before Creating Tasks)

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

Once the board exists and the active board is set correctly, create tasks via the CLI:

```bash
hermes kanban create "Task title" --body "Description" --assignee default --tenant <slug>
```

Tasks are written into `kanban.db` of the **active board** automatically — no manual SQL needed.

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

When tasks should wait for user review before the dispatcher picks them up, use `--triage` on creation:

```bash
hermes kanban create "Task title" --body "Description" --triage --priority 1 --assignee default
```

This sets the task's initial status to `triage` (backlog) instead of `ready`. The dispatcher ignores triage tasks entirely — they stay parked until promoted.

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

### Inspect board.json

```bash
cat ~/.hermes/kanban/boards/<slug>/board.json
```

## Active Board Selection (Before Creating Tasks)

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

Once the board exists and the active board is set correctly, create tasks via the CLI:

```bash
hermes kanban create "Task title" --body "Description" --assignee default --tenant <slug>
```

Tasks are written into `kanban.db` of the **active board** automatically — no manual SQL needed.

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

When tasks should wait for user review before the dispatcher picks them up, use `--triage` on creation:

```bash
hermes kanban create "Task title" --body "Description" --triage --priority 1 --assignee default
```

This sets the task's initial status to `triage` (backlog) instead of `ready`. The dispatcher ignores triage tasks entirely — they stay parked until promoted.

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

### Inspect board.json

```bash
cat ~/.hermes/kanban/boards/<slug>/board.json
```

## Active Board Selection (Before Creating Tasks)

The `hermes kanban create` CLI has **no `--board` flag**. Tasks go to whatever board slug is in `~/.hermes/kanban/current`, or `default` if that file doesn't exist. The `--tenant` flag sets a **namespace/metadata field** on the task, NOT the target board.

**Always check and set the active board before creating tasks:**

```bash
# 1. Check what board is currently active
cat ~/.hermes/kanban/current

# 2. If it's not the board you want, switch it
echo "my-project-slug" > ~/.hermes/kanban/current

# 3. Create tasks — they go to the active board
hermes kanban create "Task title" --body "Description" --assignee default

# 4. (Optional) Restore the original board when done
echo "original-slug" > ~/.hermes/kanban/current
```

**Important:** This is a single-target system — there's one active board at a time. If you switch boards to create tasks, restore the previous board afterward so other operations (dashboard, dispatcher) don't break.

## Creating Tasks on a Board

Once the board exists and the active board is set correctly, create tasks via the CLI:

```bash
hermes kanban create "Task title" --body "Description" --assignee default --tenant <slug>
```

Tasks are written into `kanban.db` of the **active board** automatically — no manual SQL needed.

### CLI Limitations When Creating Tasks

- **No `--board` flag** — the CLI does not accept a board parameter. Active board must be set via `~/.hermes/kanban/current` first.
- **No `edit`/`update` for title/body** — `hermes kanban edit` only accepts `--result`/`--summary` for completed tasks. You cannot update a task's title or body via CLI; use SQLite directly (`UPDATE tasks SET title=?, body=? WHERE id=?`) if you need to correct a task after creation.
- **Available subcommands:** `init`, `boards`, `create`, `swarm`, `list`, `ls`, `show`, `assign`, `reclaim`, `reassign`, `diagnostics`, `diag`, `link`, `unlink`, `claim`, `comment`, `complete`, `edit`, `block`, `schedule`, `unblock`, `promote`, `archive`, `tail`, `dispatch`, `daemon`, `watch`, `stats`, `notify-subscribe`, `notify-list`, `notify-unsubscribe`, `log`, `runs`, `heartbeat`, `assignees`, `context`, `specify`, `decompose`, `gc`.
- **To edit task metadata after creation**, use Python/sqlite3 directly against the board's `kanban.db`.

## User-Approval Gating (Triage Workflow)

When tasks should wait for user review before the dispatcher picks them up, use `--triage` on creation:

```bash
hermes kanban create "Task title" --body "Description" --triage --priority 1 --assignee default
```

This sets the task's initial status to `triage` (backlog) instead of `ready`. The dispatcher ignores triage tasks entirely — they stay parked until promoted.

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

**To approve a task** (promote from triage to ready):

```bash
# Via CLI
hermes kanban specify <task-id>   # promote from triage to ready
hermes kanban promote <task-id>   # alternative command

# Via direct SQLite (fastest)
python3 -c "
import sqlite3
db = sqlite3.connect('~/.hermes/kanban/boards/<slug>/kanban.db')
db.execute(\"UPDATE tasks SET status='ready' WHERE id=?\", ('<task-id>',))
db.commit()
"
```

**Alternative: `--initial-status blocked`** also prevents dispatch, but the card sits in the Blocked column visually. `--triage` is cleaner for "pending approval" because triage is semantically a backlog state, not a problem state.

**When to use which:**

| Scenario | Flag |
|----------|------|
| Task needs user review/approval before work starts | `--triage` |
| Task has a real blocker (missing credentials, dependency not ready) | `--initial-status blocked` |
| Task is ready to go, no gate needed | (omit both flags) |

**Pitfall:** If you forget both `--triage` and `--initial-status blocked`, the task goes to `ready` status and the dispatcher may pick it up immediately — potentially running code against incomplete requirements. Always gate new tasks unless you explicitly want auto-dispatch.

## Integration with hermes-dash

The hermes-dash web UI discovers boards by scanning `~/.hermes/kanban/boards/`. No config entry is needed. The UI uses:

- `board.json` → board list, icons, workdir
- `kanban.db` → task list, comments, events (via API routes that open the DB)

See `hermes-dash-brainstorming` skill for the hermes-dash kanban UI architecture.

## Querying Board State Without Direct DB Access

When `terminal` or `execute_code` are unavailable (e.g. cron jobs, restricted profiles), you can reconstruct board state from past session history using `session_search` or check the filesystem for task artifacts. This works because task creation, status changes, and worker completions produce distinctive text in session transcripts and leave filesystem traces.

### Strategy — Fast Bail-Out First

When checking if a specific task ID exists, **start with the log files, not session_search**. This avoids costly session_search calls when the answer might be "doesn't exist".

1. **Log file check (fastest)**: `search_files(target="files", pattern="*<task_id_partial>*")` on the board's `logs/` directory. If a dedicated log file like `t_73e24e8e.log` exists, the task was created. If it doesn't, the task almost certainly was never started. This works without terminal, costs minimal tokens, and is deterministic (unlike FTS5).

2. **Workspace check (confirmatory)**: `search_files(target="files", pattern="*", path="~/.hermes/kanban/boards/<slug>/workspaces/<task_id>")` — if the workspace directory exists, the task was claimed and had at least one run.

3. **Grep inside all logs**: `search_files(target="content", pattern="t_<id>", path="~/.hermes/kanban/boards/<slug>/logs/")` — catches tasks mentioned in other tasks' logs (e.g. a parent task spawning it). Much broader than a dedicated log file check.

4. **Combined session discovery**: Search for the board slug + task-related keywords in one query. `session_search` runs FTS5 across all past session transcripts, so terms like task IDs, status names, and board slugs act as retrieval fingerprints.

   ```
   session_search(query="hermes-dash kanban tasks created", limit=3)
   ```

5. **Multi-pass drill-down**: Start broad (status counts, task titles), then scroll into specific sessions for detail:

   ```
   # Get task lists printed by workers
   session_search(query="hermes-dash P1 P2 P3 P4 code review", limit=3)
   
   # Scroll into a matching session near the task list
   session_search(session_id="...", around_message_id=<match_id>, window=15)
   ```

6. **Cross-session aggregation**: A board's state is often scattered across sessions (creation in one, status updates in another, completion in a third). Use multiple `session_search` calls with different angles and `sort="newest"` to reconstruct a timeline.

7. **Session bookends**: `session_search` returns `bookend_start` (first 3 messages — the goal/kickoff) and `bookend_end` (last 3 messages — the resolution/decisions) for every matching session. These alone often tell you what was done without scrolling.

8. **Browse if unsure**: `session_search()` with no args returns recent sessions chronologically. Scan titles and previews to find sessions that mention the board, then drill in.

### Not-Found Protocol

If none of the eight layers above produce a hit for a specific task ID, report to the user:

- What was searched (logs/, workspaces/, session history, cross-reference listings)
- That nothing was found in any layer
- Three common explanations:
  - The task was discussed but never created as a kanban card (most common)
  - The ID belongs to a different board or a different Hermes profile
  - The board was reset/re-created and tasks from the previous board were lost

Then offer to create the task if appropriate, or ask the user where they saw the ID so you can narrow the search.

### Watchdog Artifact Fallback

If all eight session-search layers above produce zero results but you still need to confirm a task exists, the kanban watchdog cron job maintains filesystem artifacts that capture board state independently of conversation history:

1. Read `~/.hermes/scripts/kanban-watchdog-state.json` (JSON snapshot of all tasks with status + title)
2. List cron outputs from the "Kanban Watchdog" job via `cronjob(list)` then read its `*.md` outputs

See `references/kanban-watchdog-fallback.md` for the full protocol.

**Pitfall: watchdog state file can be stale.** `~/.hermes/scripts/kanban-watchdog-state.json` is only updated when the watchdog cron job runs (typically every 10-15 min). Tasks created, completed, or archived between ticks are invisible in the snapshot. Use log files or session_search for current state — treat the watchdog file as a coarse "was the task ever created?" check, not a live status view.

### Limitations

- Session text is not a live query of `kanban.db` — tasks completed silently (no session transcript) or status changes that happened through the web UI (hermes-dash) may not appear in session history.
- FTS5 hit density matters: boards with many session transcripts are easy to reconstruct; boards with few are sparse.
- Always cross-reference facts found via `session_search` against `board.json` and any available API endpoints before reporting to the user.

See `references/board-query-via-session-search.md` for concrete query patterns used in production.

## Looking Up a Task by ID

When a user asks about a specific task ID (e.g. `t_73e24e8e`, `t_3ba62d3f`), the task may or may not exist in the board. Searching only the database is insufficient — tasks can be referenced before creation, discussed in sessions but never committed, or the board may have been reset. Use a multi-pronged approach:

### Layer 1 — Terminal / execute_code (fastest)

Run a SQLite query against the board's kanban.db. Use `sqlite3` on the CLI or `execute_code` with `import sqlite3`. Query the tasks table by id, and optionally join with task_comments, task_events, and task_runs for full metadata (status, body, assignee, comments, events).

### Layer 2 — Log files

The board's `logs/` directory contains `.log` files named after task IDs (`t_<id>.log`). Use `search_files(target="files", pattern="*73e24*")` to check for a log by partial ID, or `search_files(target="content", pattern="t_73e24e8e")` to grep inside all log files for any mention of the exact ID, even if no dedicated log file exists.

**Fast technique: read the end of the log file.** Workers write a structured completion summary block in the last 20-40 lines of every `.log` file when they finish — whether via `kanban_complete` or `kanban_block` (review-required). This summary includes:
- What was delivered (files created/modified, line counts)
- Whether the task completed or was blocked for review
- Any review-required notes for the user
- Special characters rendering info (markdown in the summary)
- Session resume command (`hermes --resume <id>`)

To read the tail: first check the file's total_lines via `read_file(path, limit=5)`, then `read_file(path, offset=total_lines-40, limit=50)`. This costs ~2 tool calls instead of reading the entire log (typically 50-500 lines). Useful when you need to know "was this task completed and what was its output?" without reconstructing the full session.

Pitfall: logs are plain text with ANSI/emoji rendering characters embedded (from terminal output). The structured summary at the end is clean markdown text written by the worker, not raw terminal output — it's always readable.

### Layer 3 — Workspace files

The board's `workspaces/` directory has subdirectories per task. Use `search_files` to check if `workspaces/t_<id>/` exists and list its contents.

### Layer 4 — Session history (always available, no terminal needed)

Search all past sessions for the exact task ID using `session_search`. Task IDs (t_hex format) are highly distinctive tokens that FTS5 indexes reliably — even tasks that were discussed in conversation but never formally created in kanban.db will appear here.

```
session_search(query="t_73e24e8e", limit=5, sort="newest")
```

### Layer 5 — Cross-reference all-task listings

Task lists printed by workers during handoffs often contain every task on the board. Search for recent task-table output and scroll in to see the full inventory:

```
session_search(query="kanban task hermes-dash a fazer pronto em andamento", limit=3, sort="newest")
```

This shows ALL tasks at a point in time, revealing whether the target ever existed on that board.

### Layer 6 — Kanban Watchdog Artifacts (last resort, no terminal needed)

When execute_code and terminal are both blocked AND session_search returns nothing, the task likely exists only in the kanban DB (created via CLI or dashboard, not during a conversation). Check filesystem artifacts:

1. **Full grep**: `search_files(target="content", pattern="t_<short-id>", path="~/.hermes/")` — fastest catch-all
2. **Watchdog state file**: `read_file("~/.hermes/scripts/kanban-watchdog-state.json")` — JSON snapshot with status + title for every task
3. **Watchdog cron output**: Identify the "Kanban Watchdog" job via `cronjob(list)`, then read its newest output file at `~/.hermes/cron/output/<job_id>/<timestamp>.md`

If the task ID appears in the watchdog state file but nowhere else, it exists in the kanban DB but has zero conversation history — it was created externally. See `references/kanban-watchdog-fallback.md` for the full protocol.

### Reporting Not-Found Results

When none of the six layers produce a hit, report:

1. What was searched (kanban.db, logs/, workspaces/, session history, cross-reference task listings)
2. That nothing was found in any layer
3. Three common explanations:
   - The task was discussed but never created as a kanban card (most common)
   - The ID belongs to a different board or a different Hermes profile
   - The board was reset/re-created and tasks from the previous board were lost

Then offer to create the task if appropriate, or ask the user where they saw the ID so you can narrow the search.

## Pitfalls

- **Board slug must be unique** — the directory under `~/.hermes/kanban/boards/` is the only identifier. Two boards with the same slug silently overwrite each other.
- **No `hermes kanban create-board` CLI** — board creation is filesystem-only. The `hermes kanban` CLI only manages tasks within existing boards.
- **default_workdir is in board.json only** — do NOT replicate it into kanban.db. The hermes-dash user corrected this explicitly. Always read it from board.json when setting workspace paths.
- **kanban.db is initially empty** — no seed data. The dispatcher, CLI, and API routes handle table creation, but pre-creating the DB with the correct schema avoids stale-lock issues during first write.
- **`.init.lock` file** — the hermes-dash may create a `kanban.db.init.lock` file (0 bytes) during discovery. It is harmless and can be ignored or deleted.
- **`read_file` dedup on previously-read paths** — If you read `board.json` or `kanban.db` earlier in a conversation, subsequent calls to `read_file` on the same path return `{"status": "unchanged", "dedup": true}` with no file content. This is by design (tool deduplication). Workarounds:
  - **Prevention**: if you know you'll need board.json content later, read it early (as the first file in the conversation) — dedup only fires after a prior read in the same turn or a recent one.
  - **`search_files`** with `target="files"` on the board directory confirms the file still exists without hitting the dedup cache — but returns only the filename, not the content.
  - **`curl` via `terminal`** (e.g. `cat path`) — works when the `terminal` tool is available; `terminal` may not be in all tool sets.
  - **`session_search()`** — look for the board slug in the `bookend_start` or `bookend_end` of the previous session; the assistant often echoes board.json fields and task lists there.
  - **Accept the cached value** — if you read it earlier in the same conversation, the content was already returned. Do not keep retrying `read_file` on the same path; it will trigger a tool-loop warning.
- **DO NOT try `web_extract(file://...)` to bypass dedup** — the `file://` scheme is blocked and returns `"Blocked: URL targets a private or internal network address"`.
- **Check `current` before creating tasks** — `hermes kanban create` has no `--board` flag. Without checking `~/.hermes/kanban/current` first, tasks silently land on whatever board is active (which may be another project). Always check, set, and restore the current board around task creation.
- **Tenant is NOT a board selector** — `--tenant <slug>` sets a metadata namespace on the task, nothing more. It does NOT target a specific board's database. Confusing tenant with board slug is the most common mistake when creating tasks for a new board.
- **No CLI for editing task title/body** — once created, you cannot change a task's title or body via `hermes kanban`. Use Python/sqlite3 directly against the board's `kanban.db` if corrections are needed. The `edit` subcommand only accepts `--result`/`--summary` for already-completed tasks.
- **`workspace_kind: "local"` is rejected by the dispatcher** — The `tasks` table DDL defaults `workspace_kind` to `'local'`, but the Hermes Agent dispatcher only recognizes `'scratch'`. Tasks created via the hermes-dash API (`src/app/api/kanban-v2/tasks/route.ts`) correctly set `workspace_kind: "scratch"`, but tasks created via the `hermes kanban create` CLI or the auto-decomposer inherit the DB default `"local"`. This causes `spawn_failed` with `workspace: unknown workspace_kind: local`. After creating CLI/decomposed tasks, check and patch `workspace_kind` to `'scratch'` in kanban.db. See `references/dispatcher-workspace-kind.md` for the recovery SQL.
- **Decomposed parent tasks stay `blocked` after children finish** — When the auto-decomposer splits a task into children, the parent remains in `blocked` status even after all child tasks complete. Before investigating a blocked task as real pending work, check whether it was decomposed: query its events (`kind='decomposed'`) and verify the status of its child tasks. If all children are `done`, the parent can be marked `done` or `archived`.

## References

- `references/kanban-board-schema.md` — annotated schema for each kanban.db table with column types, defaults, and usage patterns.
- `references/board-query-via-session-search.md` — concrete session_search query patterns for reconstructing board state from session history.
- `references/kanban-watchdog-fallback.md` — full protocol for recovering task state via watchdog artifacts when both terminal/execute_code and session_search are blocked or empty.
- `references/kanban-batch-operations.md` — batch task operations via API (unblock, archive) and CLI (complete), including available actions and curl patterns.
- `references/dispatcher-workspace-kind.md` — root cause and fix for `workspace: unknown workspace_kind: local` dispatcher failures, with recovery SQL.

