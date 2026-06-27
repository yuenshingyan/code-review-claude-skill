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

- Option 1 → Mode A.
- Option 2 → Mode B. Detect default branch first: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'` — use result if it differs from `main`.
- Option 3 → ask follow-up for the ref, then Mode B.
- Custom text → treat as base ref, Mode B.

## Step 1 — Gather changes

**Mode A (uncommitted):**
1. `git diff --stat` + `git diff --cached --stat` → modified files.
2. `git diff --shortstat` + `git diff --cached --shortstat` → stats bar numbers.
3. `git diff` + `git diff --cached` → actual diffs.
4. Read changed files directly for large diffs needing context.
5. Scope label: `uncommitted changes`.

**Mode B (committed):**
1. `git diff <base>...HEAD --stat -M` → changed files + churn (`-M` detects renames).
2. `git diff <base>...HEAD --shortstat` → stats bar numbers.
3. `git log <base>..HEAD --oneline --format="%h %s|%an|%ad" --date=short` → commit history.
4. For each commit, `git show <hash> --stat` and read the diff.
5. Scope label: `<base>..HEAD (N commits)`.

### Skip list

Add to the `skipped` array (don't create sections): lock files (`Cargo.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Gemfile.lock`, `poetry.lock`, `composer.lock`), generated code (protobuf, GraphQL, OpenAPI), vendored deps (`vendor/`, `third_party/`, `node_modules/`), binary files. Exception: include if significant manual changes are mixed in.

### Scale guidance

- **≤15 files**: One section per file, full detail.
- **16–40 files**: Group trivially related files. Full detail on important changes, lighter on chores.
- **>40 files**: Group aggressively. Summarize mechanical changes in one section. Focus on top ~20.

## Step 2 — Verify the template exists

Run: `test -f ~/.claude/skills/code-review/templates/code-review-template.html && echo OK || echo MISSING`

If MISSING, report the error and stop. Do not read the file — Step 4's script handles injection directly.

## Step 3 — Produce the review JSON

Analyze the diffs and produce JSON matching the schema below. Write to `scratchpad/review.json`.

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

Keep each field to 1–3 sentences. If you need more, the change should be broken smaller. For trivially obvious changes (typo fixes, formatting, renames with self-evident names), a short `why` alone is sufficient — omit `how`/`when`/`where`.

### JSON schema

```json
{
  "title": "Code Review",
  "projectName": "<from directory or manifest>",
  "date": "YYYY-MM-DD",
  "scope": "<scope label from Step 1>",
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
        "commits": ["<short hash — omit array for Mode A>"],
        "related": ["<file path>"],
        "breaking": false,
        "breakingDetail": "<what breaks — only when breaking=true, else omit>",
        "context": "<2-3 sentences: what this file does, what changed, reviewer background>",
        "note": "<optional 'Also in this diff' note — omit if not needed>",
        "before": "<BeforeAfterBlock or null (null for new files)>",
        "after": "<BeforeAfterBlock or null (null for deleted files)>",
        "why": "<1-3 sentences: root cause or motivation>",
        "how": "<1-3 sentences: approach and key technical decisions>",
        "when": "<1-3 sentences: runtime conditions that activate this path>",
        "where": "<1-3 sentences: files/systems affected — blast radius>"
      }
    ]
  }
}
```

**BeforeAfterBlock:**
```json
{
  "code": [
    { "line": "<int or empty string>", "text": "<source line>", "type": "<context|added|removed>" }
  ],
  "identifiers": [
    { "name": "<identifier>", "desc": "<what it is>" }
  ],
  "explanation": "<one paragraph>"
}
```

### Field rules

- **No `id` or `summary` needed.** The template derives both automatically.
- **`commits` (top-level):** Newest-first. Omit entirely for Mode A.
- **`commits` (per-section):** Short hashes of commits touching this file. Omit for Mode A.
- **`related`:** Array of file path strings. Detect from: imports, caller→callee, same-commit co-changes, migration+schema pairs, test+implementation pairs. 1–3 links per section max. The template automatically groups related sections into a collapsible visual container — no extra markup needed.
- **`code.line`:** Actual source line number from diff hunk headers. Use `""` for separator/comment lines in grouped sections.
- **`breaking`:** Only for genuine caller-breaking changes: renamed function, changed signature, removed parameter/feature, changed return type/default. Not for new features, bug fixes, or internal refactors.
- **`why`:** Mandatory. Derive motivation from commit messages, PR context, code comments, or reasoning. Never restate the "what."
- **`how`:** Mandatory for non-trivial changes. Describe approach and tradeoffs, not syntax.
- **`when`:** Mandatory for non-trivial changes. Name runtime conditions, user actions, data states.
- **`where`:** Mandatory for non-trivial changes. Map the blast radius — downstream files, APIs, consumers.
- **Rich text:** `breakingDetail`, `note`, `why`, `how`, `when`, `where` may contain `<code>`, `<strong>`, `<em>`. No other HTML.

### Content quality rules

- Include enough surrounding context (function signature, match arm) for orientation — not just changed lines.
- **Never drop lines from the middle of a code block.** Every line between the first and last line of a snippet must be present — no silent omissions. If a diff hunk shows 12 lines, the code array must have all 12. Especially watch for multi-branch constructs (`if/else`, `match`, `try/catch`): include every branch in full, not just the first arm.
- **Synthetic comment lines** (`"line": "", "type": "context"`) serve exactly two purposes — no others:
  1. **Orient the reader** by naming the enclosing scope before/after changed lines (e.g. `// inside send_report()`).
  2. **Abbreviate large modified blocks** when the change adds or removes many repetitive lines. Show a representative sample of the actual changed lines and summarize the rest (e.g. `// … 4 more similar query arms`).
  Never use synthetic comments to bridge the gap between separate hunks, to replace unchanged code between changes, or to substitute for changed lines that should be shown in full. Use `//` comments regardless of language — these are reviewer annotations, not real source. Example:
  ```json
  { "line": "", "text": "// inside calculate_invoice()", "type": "context" },
  { "line": 84, "text": "    let total = total + shipping_fee;", "type": "added" },
  { "line": 85, "text": "    let total = total + handling_fee;", "type": "added" },
  { "line": "", "text": "// … 4 more similar fee additions", "type": "context" }
  ```
- **One logical change per snippet.** When a file's diff contains multiple separate hunks (non-adjacent `@@` sections), do NOT concatenate them into a single code block. Each hunk is a distinct change — show each one in its own snippet. Split the file into multiple section entries (same `file` path, different `desc`/`before`/`after`/`why` for each change). This prevents unrelated changes from appearing as one continuous block and lets each change have its own explanation.
- Key identifiers should cover types, functions, fields a newcomer needs defined. Skip trivial ones (`i`, `db`, `Ok`). Include `kind` (function, variable, interface, type, class, const, enum) and `type` (type signature) when available — these help reviewers understand what each identifier is at a glance.
- `why` is mandatory. Derive motivation from commit messages, PR context, code comments, or reasoning. Never restate the "what."
- For deleted files: `after: null`, populate `before` with key removed code using `"removed"` type.
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
    "code": [
      { "line": 31, "text": "pub fn new(secret: &str) -> Self {", "type": "context" },
      { "line": 32, "text": "    Self { secret: secret.to_owned() }", "type": "removed" },
      { "line": 33, "text": "}", "type": "context" }
    ],
    "identifiers": [
      { "name": "AuthMiddleware", "desc": "Tower middleware for JWT validation" }
    ],
    "explanation": "The constructor only took a secret string."
  },
  "after": {
    "code": [
      { "line": 31, "text": "pub fn new(secret: &str, refresh: RefreshConfig) -> Self {", "type": "added" },
      { "line": 32, "text": "    Self { secret: secret.to_owned(), refresh }", "type": "added" },
      { "line": 33, "text": "}", "type": "context" }
    ],
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
      "code": [
        { "line": "", "text": "// inside send_report()", "type": "context" },
        { "line": 42, "text": "    let parsed_ids: Vec<i32> = recipient_ids.iter().filter_map(|s| s.parse::<i32>().ok()).collect();", "type": "added" },
        { "line": 43, "text": "    let recipient_users = Users::Entity::find()", "type": "added" },
        { "line": 44, "text": "        .filter(Users::Column::Id.is_in(parsed_ids))", "type": "added" },
        { "line": 45, "text": "        .all(db).await.map_err(|e| e.to_string())?;", "type": "added" }
      ],
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
      "code": [
        { "line": "", "text": "// inside gather_report_data()", "type": "context" },
        { "line": 95, "text": "    let new_count = query_new(db).await?;", "type": "removed" },
        { "line": 96, "text": "    let resolved_count = query_resolved(db).await?;", "type": "removed" }
      ],
      "identifiers": [],
      "explanation": "Queries ran sequentially — each awaited before the next."
    },
    "after": {
      "code": [
        { "line": "", "text": "// inside gather_report_data()", "type": "context" },
        { "line": 95, "text": "    let (new_count, resolved_count) = tokio::try_join!(", "type": "added" },
        { "line": 96, "text": "        query_new(db),", "type": "added" },
        { "line": 97, "text": "        query_resolved(db),", "type": "added" },
        { "line": 98, "text": "    )?;", "type": "added" }
      ],
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

For `status: "new"` → set `before: null`, all code lines use type `"added"`.
For `status: "deleted"` → set `after: null`, all code lines use type `"removed"`.
For `status: "renamed"` → add `"oldFile": "<original path>"`.

## Step 4 — Validate, inject, and write

Run as a **single** script:

```python
python3 - <<'EOF'
import json, os

with open('scratchpad/review.json', encoding='utf-8') as f:
    data = json.load(f)

tpl = os.path.expanduser('~/.claude/skills/code-review/templates/code-review-template.html')
with open(tpl, encoding='utf-8') as f:
    template = f.read()

json_str = json.dumps(data, ensure_ascii=False)
result = template.replace(
    '<script id="review-data" type="application/json">{}</script>',
    f'<script id="review-data" type="application/json">{json_str}</script>')

assert json_str in result, "injection failed"

with open('code-review.html', 'w', encoding='utf-8') as f:
    f.write(result)

print(f"Done: {len(result)} bytes, sections: {({k: len(v) for k, v in data.get('sections', {}).items()})}")
EOF
```

## Step 5 — Report

Tell the user the output path and a one-line summary of how many changes were documented.