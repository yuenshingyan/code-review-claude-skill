---
name: code-review
description: >-
  Generate an interactive visual code review and write it to an HTML
  file. Multi-step: choose review mode, gather full diffs, read
  changed files for context, analyze and produce structured JSON,
  inject into HTML template via a single script.
when_to_use: >-
  TRIGGER when the user asks to "review my code", "code review",
  "review changes", "review my diff", "review commits",
  "visual code review", or similar. For GitHub PR reviews,
  use /review instead.
disable-model-invocation: true
effort: max
allowed-tools:
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git status *)
  - Bash(git show *)
  - Bash(git symbolic-ref *)
  - Bash(python3 *)
  - Read
  - Write
  - AskUserQuestion
disallowed-tools:
  - Agent
---

Generate an interactive visual code review and write it to an HTML file.

## Step 0 — Choose review mode

Use `AskUserQuestion` with header "Review mode", question "What would you like to review?", options:

1. **Uncommitted changes** — Review working tree and staged changes (git diff + git diff --cached)
2. **Commits since main** — All commits on this branch since main
3. **Commits since ref** — Specify a base ref to diff against HEAD

- Option 1 → pass `uncommitted` to gather_diff.py.
- Option 2 → pass `branch` to gather_diff.py (it auto-detects the default branch).
- Option 3 → ask follow-up for the ref, then pass that ref string to gather_diff.py.
- Custom text → treat as base ref, pass directly to gather_diff.py.

## Step 1 — Gather changes

Run `gather_diff.py` with the mode chosen in Step 0:

```bash
python3 ~/.claude/skills/code-review/scripts/gather_diff.py <mode> \
  --meta scratchpad/meta.json \
  --diff scratchpad/raw.diff
```

Where `<mode>` is `uncommitted`, `branch`, or a base ref string (e.g. `main`, `v1.2.0`).

The script handles all git commands, skip-list filtering (lock files, vendored deps, generated code, binary files), stat extraction, and commit history automatically. It outputs:
- `scratchpad/meta.json` — scope, stats, commits, skipped files, changed file list
- `scratchpad/raw.diff` — filtered unified diff
- `scratchpad/file-contents.json` — full before/after line content for each changed file

### Scale guidance

- **≤15 files**: One section per file, full detail.
- **16–40 files**: Group trivially related files. Full detail on important changes, lighter on chores.
- **>40 files**: Group aggressively. Summarize mechanical changes in one section. Focus on top ~20.

## Step 2 — Parse the diff

```bash
cat scratchpad/raw.diff | python3 ~/.claude/skills/code-review/scripts/parse_diff.py > scratchpad/hunks.json
```

## Step 3 — Produce the review JSON

Read `scratchpad/meta.json` and `scratchpad/hunks.json`. Analyze the diffs and produce JSON matching the schema below. Write to `scratchpad/review.json`.

Use the values from `meta.json` directly for the top-level `scope`, `stats`, `commits`, and `skipped` fields — do not recompute them.

For each section, look up the corresponding entry in `hunks.json` by `file` path and record the `old_start` value(s) of the matching hunk(s) in the section's `lines` array. For new files (no before side), use `new_start` instead. This is how the build script locates the right code blocks.

### Tab classification

Choose tab keys that describe the logical groupings in this specific changeset. The keys you write in `sections` become the tab names in the UI — `"bug-fixes"` renders as "Bug Fixes", `"auth-refactor"` as "Auth Refactor". Use kebab-case for multi-word keys; use only `[a-z0-9-_]` characters.

Common starting points (not the only options):

| Key | Use when |
|---|---|
| `features` | New capabilities, UI, APIs, data formats |
| `bug-fixes` | Crash fixes, data integrity, behavioral corrections |
| `refactors` | Restructuring without behavior change |
| `chores` | Deps, config, CI, docs, type-only cleanup, dead code removal |
| `security` | Auth, input validation, permission changes |
| `performance` | Caching, query optimization, algorithmic improvements |
| `migrations` | Schema changes, data migrations, breaking format changes |

Aim for 2–5 tabs. Omit any tab key with zero entries.

### WHY / HOW / WHEN / WHERE annotations

Each section MUST include structured annotations explaining the change. These render as a labeled block in the template.

**WHY** — State the problem, requirement, bug, or goal that motivated this change. Name the root cause, not the symptom. Reference ticket IDs, error messages, or user-reported issues when available. Write for someone who has never seen the original bug. Explain why the old behavior was wrong or insufficient — not just what changed. Aim for 3–5 sentences for any non-trivial change.

**HOW** — Explain what the new code does to address the WHY. Describe the approach and key technical decisions — not a line-by-line narration of syntax. If you chose this approach over a more obvious alternative, note the tradeoff and explain why the alternative was rejected, so future developers don't revert to the broken approach. Describe the data flow, control flow, or state change in enough detail that a reader can follow the logic without opening the file. Aim for 3–5 sentences.

**WHEN** — Describe the runtime conditions, user actions, data states, or system configurations under which this code path activates. This helps maintainers know when to test it, when to suspect it during debugging, and which users or environments are affected. Include edge cases, error states, or concurrency scenarios where relevant. Name specific triggers (e.g. "on every authenticated HTTP request", "when the queue is empty", "only on first render"). Aim for 2–4 sentences.

**WHERE** — Name the files, modules, components, APIs, hooks, or downstream systems that depend on, call, or are affected by this change. This maps the blast radius so reviewers and future maintainers know what else to check or update. Include both direct callers and indirect consumers — tests, configuration, documentation, and external contracts that may need to change. Aim for 2–4 sentences.

Write as much as needed to make each field genuinely useful to someone reading this code cold in six months. Clarity trumps brevity. For trivially obvious changes (typo fixes, formatting, renames with self-evident names), a short `why` alone is sufficient — omit `how`/`when`/`where`. When a section covers a diff that mixes multiple unrelated concerns, open `why` with a one-sentence summary and break each concern into a numbered item with its own before/after/why narrative. Never write a single sentence where three would give the full picture.

### JSON schema

```json
{
  "title": "Code Review",
  "projectName": "<from directory or manifest>",
  "date": "YYYY-MM-DD",
  "scope": "<from meta.json>",
  "stats": { "files": 0, "added": 0, "deleted": 0 },
  "commits": [
    {
      "hash": "<7-char short hash>",
      "message": "<subject line>",
      "author": "<name>",
      "date": "YYYY-MM-DD"
    }
  ],
  "skipped": [
    { "file": "<path>", "reason": "<why skipped>" }
  ],
  "sections": {
    "<tab key>": [
      {
        "file": "<display path>",
        "status": "<new|modified|deleted|renamed>",
        "oldFile": "<original path — only when status=renamed, else omit>",
        "desc": "<short description>",
        "added": 0,
        "removed": 0,
        "lines": ["<old_start line numbers from hunks.json that belong to this section>"],
        "commits": ["<short hash — omit array for uncommitted mode>"],
        "related": ["<file path>"],
        "breaking": false,
        "breakingDetail": "<what breaks — only when breaking=true, else omit>",
        "context": "<2-3 sentences: what this file does, what changed, reviewer background>",
        "note": "<optional 'Also in this diff' note — omit if not needed>",
        "why": "<root cause or motivation — as much prose as needed>",
        "how": "<approach and key technical decisions — as much prose as needed>",
        "when": "<runtime conditions that activate this path — as much prose as needed>",
        "where": "<files/systems affected — blast radius — as much prose as needed>"
      }
    ]
  }
}
```

### Field rules

- **No `id` or `summary` needed.** The template derives both automatically.
- **`lines`:** Array of `old_start` integers from `hunks.json` — one per hunk that belongs to this section. Read `hunks.json`, find the hunks for this file by matching `file` path, and list their `old_start` values. For new files (no "before" side) use the hunk's `new_start` instead. `build_review.py` uses the first value to resolve the starting line for the "Jump to line" button.
- **`commits` (top-level):** Newest-first. From `meta.json`. Empty array for uncommitted mode.
- **`commits` (per-section):** Short hashes of commits touching this file. Omit for uncommitted mode.
- **`related`:** Array of file path strings. Detect from: imports, caller→callee, same-commit co-changes, migration+schema pairs, test+implementation pairs. 1–3 links per section max. The template automatically groups related sections into a collapsible visual container — no extra markup needed.
- **`breaking`:** Only for genuine caller-breaking changes: renamed function, changed signature, removed parameter/feature, changed return type/default. Not for new features, bug fixes, or internal refactors.
- **`why`:** Mandatory. Derive motivation from commit messages, PR context, code comments, or reasoning. Never restate the "what."
- **`how`:** Mandatory for non-trivial changes. Describe approach and tradeoffs, not syntax.
- **`when`:** Mandatory for non-trivial changes. Name runtime conditions, user actions, data states.
- **`where`:** Mandatory for non-trivial changes. Map the blast radius — downstream files, APIs, consumers.
- **Rich text:** `breakingDetail`, `note`, `why`, `how`, `when`, `where` may contain `<code>`, `<strong>`, `<em>`, and `<br>`. No other HTML.
- **Numbered lists:** When a field contains a numbered list (e.g. "1. … 2. … 3. …"), place a `<br>` before each item number so each item renders on its own line. Example: `"First sentence of context.<br>1. Point one.<br>2. Point two.<br>3. Point three."`

### Content quality rules

- **One section per logical change.** When a file's diff contains multiple separate hunks (non-adjacent `@@` sections), emit one section per hunk — same `file` path, separate `desc`/`why`/`how`/`when`/`where`. If two hunks are conceptually connected, link them with the `related` field.
- `why` is mandatory. Derive motivation from commit messages, PR context, code comments, or reasoning. Never restate the "what."
- For deleted files: `after: null`.
- For renamed files: include `oldFile`. Template shows "Renamed from …" automatically.
- **Dashes:** Use regular hyphens/dashes (`-`) in all review text. Never use em dashes (`—`) or en dashes (`–`).

### Example section (modified file)

```json
{
  "file": "src/auth/middleware.rs",
  "status": "modified",
  "desc": "Add JWT token refresh on expiry",
  "added": 42,
  "removed": 8,
  "lines": [87],
  "commits": ["a1b2c3d"],
  "related": ["src/auth/claims.rs"],
  "breaking": true,
  "breakingDetail": "<code>AuthMiddleware::new()</code> now requires a <code>RefreshConfig</code> parameter.",
  "context": "This middleware intercepts every authenticated request and validates the JWT.",
  "why": "Users were getting logged out mid-session when their token expired during long form submissions.",
  "how": "Added a <code>RefreshConfig</code> parameter to <code>AuthMiddleware::new()</code> that enables transparent token refresh within a configurable grace period, avoiding forced re-authentication.",
  "when": "Activates on every authenticated HTTP request when the JWT is expired but within the grace period. Affects all users with active sessions during token rotation.",
  "where": "<code>src/auth/claims.rs</code> (RefreshConfig definition), <code>src/main.rs</code> (middleware construction), all integration tests that instantiate AuthMiddleware."
}
```

**Multiple hunks in one file → multiple sections.** When a diff has separate hunks in the same file (e.g. a new helper at line 20 and a refactored query at line 95), emit one section per logical change. The template handles duplicate file paths by appending a suffix to the DOM id. Example — two sections for the same file:

```json
[
  {
    "file": "src/report/service.rs",
    "status": "modified",
    "desc": "Resolve recipient emails from user IDs",
    "added": 6, "removed": 0,
    "lines": [20],
    "why": "Callers were passing raw IDs; the report needs email addresses.",
    "how": "Parses string IDs to i32, queries the Users table with <code>is_in</code> filter to batch-fetch matching user records.",
    "when": "Every time <code>send_report()</code> is called with recipient IDs — triggered by scheduled reports and manual sends.",
    "where": "<code>Users::Entity</code> (SeaORM model), <code>send_report()</code> callers in <code>src/report/scheduler.rs</code> and <code>src/api/reports.rs</code>."
  },
  {
    "file": "src/report/service.rs",
    "status": "modified",
    "desc": "Run report queries concurrently with try_join!",
    "added": 12, "removed": 18,
    "lines": [95],
    "why": "Sequential queries added ~600ms latency to report generation.",
    "how": "Replaced sequential <code>.await</code> calls with <code>tokio::try_join!</code> to run both queries concurrently. Short-circuits on first error to preserve existing error behavior.",
    "when": "Every call to <code>gather_report_data()</code> — triggered by both scheduled and on-demand report generation.",
    "where": "<code>query_new()</code> and <code>query_resolved()</code> in this file, <code>src/report/scheduler.rs</code> (caller)."
  }
]
```

For `status: "renamed"` → add `"oldFile": "<original path>"`.

## Step 4 — Build the review

```bash
python3 ~/.claude/skills/code-review/scripts/build_review.py \
  scratchpad/hunks.json \
  scratchpad/file-contents.json \
  scratchpad/review.json \
  ~/.claude/skills/code-review/templates/code-review-template.html \
  code-review.html
```

The script resolves each section's absolute file path and starting line number, then injects the review JSON into the HTML template. If it exits 1, read the output to identify the issue:

- **NO ABS PATH** — the section's `lines` array is missing or the `file` path doesn't match any entry in `hunks.json`. Open `scratchpad/hunks.json`, find the correct file entry, and update `lines` with the right `old_start` (or `new_start` for new files) integer.

Fix the violations in `scratchpad/review.json` and re-run until exit 0.

## Step 5 — Report

Tell the user the output path and a one-line summary of how many changes were documented.
