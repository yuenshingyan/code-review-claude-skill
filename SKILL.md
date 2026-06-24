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
        "why": "<one paragraph: motivation, not description>"
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
- **`related`:** Array of file path strings. Detect from: imports, caller→callee, same-commit co-changes, migration+schema pairs, test+implementation pairs. 1–3 links per section max. The template resolves them to clickable links.
- **`code.line`:** Actual source line number from diff hunk headers. Use `""` for separator/comment lines in grouped sections.
- **`breaking`:** Only for genuine caller-breaking changes: renamed function, changed signature, removed parameter/feature, changed return type/default. Not for new features, bug fixes, or internal refactors.
- **Rich text:** `context`, `breakingDetail`, `note`, `explanation`, `why` may contain `<code>`, `<strong>`, `<em>`. No other HTML.

### Content quality rules

- Include enough surrounding context (function signature, match arm) for orientation — not just changed lines.
- Key identifiers should cover types, functions, fields a newcomer needs defined. Skip trivial ones (`i`, `db`, `Ok`).
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
  "why": "Users were getting logged out mid-session when their token expired during long form submissions."
}
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