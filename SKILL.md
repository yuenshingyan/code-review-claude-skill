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

### Tab classification

| Tab | Content |
|---|---|
| `features` | New functionality, capabilities, UI, formats |
| `fixes` | Bug fixes, crash fixes, data integrity |
| `refactors` | Restructuring without behavior change |
| `chores` | Deps, config, CI, docs, type cleanup, dead code |

Omit any tab key with zero entries.

### WHY / HOW / WHEN / WHERE annotations

Each section MUST include structured annotations explaining the change. These render as a labeled block in the template.

**WHY** — State the problem, requirement, bug, or goal that motivated this change. Name the root cause, not the symptom. Reference ticket IDs, error messages, or user-reported issues when available. Write for someone who has never seen the original bug.

**HOW** — Explain what the new code does to address the WHY. Describe the approach and key technical decisions — not a line-by-line narration of syntax. If you chose this approach over a more obvious alternative, note the tradeoff in one sentence so future developers don't revert to the broken approach.

**WHEN** — Describe the runtime conditions, user actions, data states, or system configurations under which this code path activates. This helps maintainers know when to test it, when to suspect it during debugging, and which users or environments are affected.

**WHERE** — Name the files, modules, components, APIs, hooks, or downstream systems that depend on, call, or are affected by this change. This maps the blast radius so reviewers and future maintainers know what else to check or update.

Write as much as needed to make each field genuinely useful to someone reading this code cold in six months. Clarity trumps brevity. For trivially obvious changes (typo fixes, formatting, renames with self-evident names), a short `why` alone is sufficient — omit `how`/`when`/`where`. When a section covers a diff that mixes multiple unrelated concerns, open `why` with a one-sentence summary and break each concern into a numbered item with its own before/after/why narrative.

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
        "commits": ["<short hash — omit array for uncommitted mode>"],
        "related": ["<file path>"],
        "breaking": false,
        "breakingDetail": "<what breaks — only when breaking=true, else omit>",
        "context": "<2-3 sentences: what this file does, what changed, reviewer background>",
        "note": "<optional 'Also in this diff' note — omit if not needed>",
        "before": "<BeforeAfterBlock or null (null for new files)>",
        "after": "<BeforeAfterBlock or null (null for deleted files)>",
        "why": "<root cause or motivation — as much prose as needed>",
        "how": "<approach and key technical decisions — as much prose as needed>",
        "when": "<runtime conditions that activate this path — as much prose as needed>",
        "where": "<files/systems affected — blast radius — as much prose as needed>"
      }
    ]
  }
}
```

**BeforeAfterBlock:**
```json
{
  "code": [],
  "identifiers": [
    { "name": "<identifier>", "desc": "<what it is>" }
  ],
  "explanation": "<one paragraph>"
}
```

Always write `"code": []` — `build_review.py` populates code arrays from `hunks.json` by keyword-matching sections against diff hunks. Write real `identifiers` and `explanation`; the script preserves them.

### Field rules

- **No `id` or `summary` needed.** The template derives both automatically.
- **`commits` (top-level):** Newest-first. From `meta.json`. Empty array for uncommitted mode.
- **`commits` (per-section):** Short hashes of commits touching this file. Omit for uncommitted mode.
- **`related`:** Array of file path strings. Detect from: imports, caller→callee, same-commit co-changes, migration+schema pairs, test+implementation pairs. 1–3 links per section max. The template automatically groups related sections into a collapsible visual container — no extra markup needed.
- **`breaking`:** Only for genuine caller-breaking changes: renamed function, changed signature, removed parameter/feature, changed return type/default. Not for new features, bug fixes, or internal refactors.
- **`why`:** Mandatory. Derive motivation from commit messages, PR context, code comments, or reasoning. Never restate the "what."
- **`how`:** Mandatory for non-trivial changes. Describe approach and tradeoffs, not syntax.
- **`when`:** Mandatory for non-trivial changes. Name runtime conditions, user actions, data states.
- **`where`:** Mandatory for non-trivial changes. Map the blast radius — downstream files, APIs, consumers.
- **Rich text:** `breakingDetail`, `note`, `why`, `how`, `when`, `where` may contain `<code>`, `<strong>`, `<em>`. No other HTML.

### Content quality rules

- **One section per logical change.** When a file's diff contains multiple separate hunks (non-adjacent `@@` sections), emit one section per hunk — same `file` path, separate `desc`/`why`/`how`/`when`/`where`. The build script matches each section to a hunk by keyword scoring; grouping multiple hunks into one section prevents correct matching.
- Key identifiers should cover types, functions, fields a newcomer needs defined. Skip trivial ones (`i`, `db`, `Ok`). Include `kind` (function, variable, interface, type, class, const, enum) and `type` (type signature) when available — these help reviewers understand what each identifier is at a glance.
- `why` is mandatory. Derive motivation from commit messages, PR context, code comments, or reasoning. Never restate the "what."
- For deleted files: `after: null`.
- For renamed files: include `oldFile`. Template shows "Renamed from …" automatically.

### Example section (modified file)

```json
{
  "file": "src/auth/middleware.rs",
  "status": "modified",
  "desc": "Add JWT token refresh on expiry",
  "added": 42,
  "removed": 8,
  "commits": ["a1b2c3d"],
  "related": ["src/auth/claims.rs"],
  "breaking": true,
  "breakingDetail": "<code>AuthMiddleware::new()</code> now requires a <code>RefreshConfig</code> parameter.",
  "context": "This middleware intercepts every authenticated request and validates the JWT.",
  "before": {
    "code": [],
    "identifiers": [
      { "name": "AuthMiddleware", "desc": "Tower middleware for JWT validation" }
    ],
    "explanation": "The constructor only took a secret string."
  },
  "after": {
    "code": [],
    "identifiers": [
      { "name": "RefreshConfig", "desc": "Holds grace_period and max_refreshes" }
    ],
    "explanation": "Now accepts a <code>RefreshConfig</code> for transparent token refresh."
  },
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
    "before": null,
    "after": {
      "code": [],
      "identifiers": [{ "name": "parsed_ids", "desc": "Validated i32 user IDs parsed from string input" }],
      "explanation": "New block resolves recipient IDs to active user emails."
    },
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
    "before": {
      "code": [],
      "identifiers": [],
      "explanation": "Queries ran sequentially — each awaited before the next."
    },
    "after": {
      "code": [],
      "identifiers": [{ "name": "tokio::try_join!", "desc": "Runs futures concurrently, short-circuits on first error" }],
      "explanation": "Queries now run concurrently via <code>try_join!</code>."
    },
    "why": "Sequential queries added ~600ms latency to report generation.",
    "how": "Replaced sequential <code>.await</code> calls with <code>tokio::try_join!</code> to run both queries concurrently. Short-circuits on first error to preserve existing error behavior.",
    "when": "Every call to <code>gather_report_data()</code> — triggered by both scheduled and on-demand report generation.",
    "where": "<code>query_new()</code> and <code>query_resolved()</code> in this file, <code>src/report/scheduler.rs</code> (caller)."
  }
]
```

For `status: "new"` → set `before: null`.
For `status: "deleted"` → set `after: null`.
For `status: "renamed"` → add `"oldFile": "<original path>"`.

## Step 4 — Build the review

```bash
python3 ~/.claude/skills/code-review/scripts/build_review.py \
  scratchpad/hunks.json \
  scratchpad/review.json \
  ~/.claude/skills/code-review/templates/code-review-template.html \
  code-review.html
```

The script assigns hunks to sections, validates, and produces the HTML. If it exits 1, read the output to identify the issue:

- **Gap violation** (`GAP: file (before): 73 → 130`) — that section is matching a hunk that spans two changes. Split the section into two entries with distinct `desc`/`why` so the keyword scorer can route each to the right hunk.
- **NO BEFORE / NO AFTER** — no hunk in `hunks.json` matched this section. Check that the section's `desc`, `why`, `how` contain keywords from the actual diff lines. Adjust the wording or check that the file path matches exactly.
- **CONTEXT-ONLY** — the matched hunk had no added/removed lines on that side. Verify `status` is set correctly (`new`/`deleted`/`modified`).

Fix the violations in `scratchpad/review.json` and re-run until exit 0.

## Step 5 — Report

Tell the user the output path and a one-line summary of how many changes were documented.
