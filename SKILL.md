---
name: code-review
description: Generate an interactive visual code review for changes since a given ref.
---

Generate an interactive visual code review and write it to an HTML file.

## Step 0 — Choose review mode

Use the `AskUserQuestion` tool to present a dialog with the following question:

- Question: "What would you like to review?"
- Header: "Review mode"
- Options:
  1. Label: "Uncommitted changes" — Description: "Review working tree and staged changes (git diff + git diff --cached)"
  2. Label: "Commits since main" — Description: "Review all commits on this branch since main"
  3. Label: "Commits since ref" — Description: "Specify a base ref (branch, tag, or commit hash) to diff against HEAD"

If the user selects **"Uncommitted changes"**, proceed with Mode A.
If the user selects **"Commits since main"**, proceed with Mode B with base = `main`. Detect the default branch first: run `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'` — if it returns `master` or another name, use that instead of `main`.
If the user selects **"Commits since ref"**, ask a follow-up: "Enter the base ref (e.g. HEAD~5, v1.2.0, abc1234):" — then proceed with Mode B using that ref.
If the user selects **"Other"** and provides custom text, treat it as a base ref and proceed with Mode B.

## Step 1 — Gather changes

**Mode A — Uncommitted changes:**
1. Run `git diff --stat` and `git diff --cached --stat` to get modified files.
2. Run `git diff --shortstat` and `git diff --cached --shortstat` to get the summary line (files changed, insertions, deletions) for the stats bar.
3. Run `git diff` and `git diff --cached` to read the actual diffs.
4. For large diffs, read the changed files directly to understand context.
5. Record the scope label: `uncommitted changes`.

**Mode B — Committed changes:**
1. Run `git diff <base>...HEAD --stat -M` to get the list of changed files and their churn. The `-M` flag detects renames.
2. Run `git diff <base>...HEAD --shortstat` to get the summary line for the stats bar.
3. Run `git log <base>..HEAD --oneline --format="%h %s|%an|%ad" --date=short` to get the commit history with author and date.
4. For each commit, run `git show <hash> --stat` and read the diff to understand what changed and why.
5. Record the scope label: `<base>..HEAD (N commits)`.

### Skip list

Skip the following files — do not create sections for them. Instead, add them to the `skipped` array with a reason:

- Lock files: `Cargo.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Gemfile.lock`, `poetry.lock`, `composer.lock`
- Generated code: protobuf outputs (`*.pb.go`, `*.pb.rs`, `*_pb2.py`), GraphQL generated files, OpenAPI generated clients
- Vendored dependencies: anything under `vendor/`, `third_party/`, `node_modules/`
- Binary files: images, fonts, compiled assets

If a skipped file has significant manual changes mixed in (e.g. a manually edited lock file), include it as a regular section instead.

### Scale guidance

- **≤15 files**: Create one section per file. Full detail on all.
- **16–40 files**: Group trivially related files (e.g. a migration + its generated type) into single sections. Full detail on important changes, lighter on chores.
- **>40 files**: Group aggressively. Summarize mechanical changes (renames, import updates) in a single section. Focus detail on the top ~20 most important changes.

## Step 2 — Read the template

Read the template file at `~/.claude/templates/code-review-template.html`. This contains all CSS, HTML skeleton, and renderer JS. You will copy it verbatim and only fill in the JSON data slot.

If the file does not exist, report the error and stop.

## Step 3 — Produce the review JSON

Analyze the diffs from Step 1 and produce a JSON object matching the schema below. This is the only content you generate — the template handles all rendering.

### Tab classification

Classify each change into exactly one tab:

| Tab key | What belongs here |
|---|---|
| `features` | New functionality, new annotation types, new export formats, new UI capabilities |
| `fixes` | Corrections to broken behavior, crash fixes, data integrity fixes |
| `refactors` | Code restructuring that doesn't change behavior — renames, extractions, simplifications |
| `chores` | Dependencies, config, CI, migrations, docs, type cleanups, dead code removal |

Omit any tab key from `sections` that has zero entries.

### JSON schema

```json
{
  "title": "Code Review",
  "projectName": "<project name from directory or Cargo.toml/package.json>",
  "date": "YYYY-MM-DD",
  "scope": "<scope label from Step 1>",
  "stats": { "files": <int>, "added": <int>, "deleted": <int> },
  "commits": [
    {
      "hash": "<short hash, 7 chars>",
      "message": "<commit subject line>",
      "author": "<author name>",
      "date": "YYYY-MM-DD"
    }
  ],
  "skipped": [
    {
      "file": "<file path>",
      "reason": "<why it was skipped, e.g. 'Auto-generated lock file (+1843 lines)'>"
    }
  ],
  "sections": {
    "<tab key>": [
      {
        "file": "<display file path>",
        "status": "<new|modified|deleted|renamed>",
        "oldFile": "<original path — only when status is 'renamed', otherwise omit>",
        "desc": "<short description>",
        "added": <int>,
        "removed": <int>,
        "commits": ["<short hash>"],
        "related": ["<file path>"],
        "breaking": <bool>,
        "breakingDetail": "<what breaks — only when breaking is true, otherwise omit>",
        "context": "<2-3 sentences: what this file does, what the changed code does, background for a reviewer>",
        "note": "<optional 'Also in this diff' note — omit if not needed>",
        "before": <BeforeBlock or null>,
        "after": <AfterBlock or null>,
        "why": "<one paragraph: motivation, not description>"
      }
    ]
  }
}
```

**BeforeBlock / AfterBlock:**
```json
{
  "code": [
    { "line": <int or "">, "text": "<source line>", "type": "<context|added|removed>" }
  ],
  "identifiers": [
    { "name": "<identifier>", "desc": "<what it is>" }
  ],
  "explanation": "<one paragraph>"
}
```

### Field rules

- **No `id` fields needed.** The template derives section IDs automatically from file paths (replacing `/` and `.` with `-`).
- **No `summary` array needed.** The template builds the summary table automatically from `sections`.
- **`status`**: Required on each section. One of `"new"` (file created), `"modified"` (file changed), `"deleted"` (file removed), `"renamed"` (file moved/renamed). Detect renames from `git diff -M` output.
- **`oldFile`**: Only include when `status` is `"renamed"`. The original file path before the rename.
- **`added`** / **`removed`**: Lines added/removed for this file. Shown in the summary churn column and section header.
- **`commits`** (top-level): Array of all commits in the review range (Mode B only). Ordered newest-first. Each entry has `hash`, `message`, `author`, `date`. Omit for Mode A.
- **`commits`** (per-section): Array of short commit hashes that touched this file. Derived from `git log` output. Omit for Mode A.
- **`skipped`**: Array of files that were excluded from review. Each entry has `file` and `reason`. Omit if nothing was skipped.
- **`related`**: Array of related file paths (strings, not objects) — files that import, call, or are tightly coupled with this one. The template resolves them to section links automatically. Detect relationships from: import statements, function calls across files, files changed in the same commit for the same purpose, migration + schema pairs, test + implementation pairs. Omit if no relationships detected.
- **`before`**: Set to `null` for purely additive sections (new file, new function, new match arm). The renderer will use full-width layout for the `after` block.
- **`after`**: Set to `null` for deletion-only sections (file removed). The renderer will use full-width layout for the `before` block, showing all removed code.
- **`breakingDetail`**: Only include when `breaking` is `true`. Explain specifically what breaks: which callers, consumers, or behavior changes.
- **`note`**: Optional. Use for "Also in this diff" notes when a section covers multiple changes in the same file.
- **`codeLine.line`**: Use the actual source line number from diff hunk headers. Use `""` (empty string) for separator/comment lines in multi-file grouped sections.
- **`codeLine.type`**: `"context"` for unchanged lines, `"added"` for new/changed lines, `"removed"` for deleted lines.
- **Rich text**: The fields `context`, `breakingDetail`, `note`, `explanation`, and `why` may contain inline `<code>`, `<strong>`, and `<em>` HTML tags. No other HTML.

### Content quality rules

- Show enough surrounding context in each code snippet for the reader to orient themselves (the function signature, the match arm, etc.) — not just the changed line.
- The key identifiers list should cover types, functions, fields, and variables a reader unfamiliar with the codebase would need defined. Skip trivial ones (`i`, `db`, `Ok`).
- Keep explanations concise — one paragraph per block.
- The `why` field is mandatory for every section. Derive the motivation from commit messages, PR context, code comments, or by reasoning about the bug/feature. Never leave it as a restatement of the "what" — it must answer *why was this change necessary?*
- Add `breaking: true` only when the change genuinely breaks callers or existing behavior: renamed function, changed function signature, removed parameter, changed default value, removed feature, changed return type. Do not add it for new features, bug fixes, or internal refactors.
- For deleted files (`status: "deleted"`), set `after: null` and populate `before` with the key code that was removed, using `"removed"` type for all substantive lines.
- For renamed files (`status: "renamed"`), include `oldFile` with the original path. The template shows "Renamed from <oldFile>" inside the expanded section.
- For related changes, prioritize the strongest relationships: direct imports, caller→callee, test→implementation, migration→schema. Don't link every file to every other file — 1-3 related links per section is ideal.

### Example sections

**Modified file with related changes:**
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

**New file:**
```json
{
  "file": "src/auth/claims.rs",
  "status": "new",
  "desc": "New RefreshClaim type and validation",
  "added": 38,
  "removed": 0,
  "commits": ["a1b2c3d"],
  "related": ["src/auth/middleware.rs"],
  "breaking": false,
  "context": "New file defining JWT claim types for the token refresh flow.",
  "before": null,
  "after": {
    "code": [
      { "line": 1, "text": "pub struct RefreshClaim {", "type": "added" },
      { "line": 2, "text": "    pub sub: String,", "type": "added" },
      { "line": 3, "text": "    pub refresh_count: u32,", "type": "added" },
      { "line": 4, "text": "}", "type": "added" }
    ],
    "identifiers": [
      { "name": "RefreshClaim", "desc": "JWT claim tracking refresh state" },
      { "name": "refresh_count", "desc": "Prevents infinite refresh chains" }
    ],
    "explanation": "New type that enforces a ceiling on consecutive refreshes."
  },
  "why": "Without a bounded refresh count, a compromised token could be refreshed indefinitely."
}
```

**Deleted file:**
```json
{
  "file": "src/legacy_auth.rs",
  "status": "deleted",
  "desc": "Remove deprecated basic-auth module",
  "added": 0,
  "removed": 87,
  "commits": ["f4e5d6c"],
  "related": ["src/auth/middleware.rs"],
  "breaking": true,
  "breakingDetail": "Any service calling <code>legacy_auth::check_password()</code> will fail to compile.",
  "context": "This module provided HTTP Basic Auth, superseded by JWT auth in v2.0.",
  "before": {
    "code": [
      { "line": 3, "text": "pub fn check_password(user: &str, pass: &str) -> bool {", "type": "removed" },
      { "line": 4, "text": "    let stored = get_stored_hash(user);", "type": "removed" },
      { "line": 5, "text": "    verify(pass, &stored).unwrap_or(false)", "type": "removed" },
      { "line": 6, "text": "}", "type": "removed" }
    ],
    "identifiers": [
      { "name": "check_password", "desc": "Legacy password verification against hardcoded bcrypt hashes" }
    ],
    "explanation": "The entire module is removed."
  },
  "after": null,
  "why": "Dead auth code creates confusion about which auth path is canonical and increases security audit surface."
}
```

**Renamed file:**
```json
{
  "file": "src/validation/user.rs",
  "status": "renamed",
  "oldFile": "src/handlers/user_validation.rs",
  "desc": "Move user validation to shared module",
  "added": 4,
  "removed": 2,
  "commits": ["b7c8d9e"],
  "related": ["src/handlers/users.rs"],
  "breaking": false,
  "context": "Relocated from handlers to a dedicated validation module.",
  "before": {
    "code": [
      { "line": 1, "text": "use crate::handlers::types::CreateUser;", "type": "removed" }
    ],
    "identifiers": [],
    "explanation": "Import path referenced the old module location."
  },
  "after": {
    "code": [
      { "line": 1, "text": "use crate::types::CreateUser;", "type": "added" }
    ],
    "identifiers": [],
    "explanation": "Updated to the new crate-level types module."
  },
  "why": "Validation logic buried in handlers was hard to discover and reuse."
}
```

## Step 4 — Assemble and write the output file

1. Read the template from Step 2.
2. In the template, find `<script id="review-data" type="application/json">{}</script>` and replace the `{}` with the JSON from Step 3.
3. Write the result to `code-review.html` in the project root.

## Step 5 — Report

Tell the user the path and a one-line summary of how many changes were documented.

## Template features reference

The template provides these interactive features automatically — no extra data needed:

- **Tabbed navigation**: Summary, Features, Bug Fixes, Refactors, Chores, Commits (timeline), Skipped files
- **Summary table**: File, status badge, tab, description, churn (+N / -N)
- **Section headers**: Status badge, breadcrumb file path, description, LOCs, BREAKING badge, commit pills, copy-as-context button, review status group
- **Side-by-side diffs**: Before/after with syntax-colored added/removed lines; full-width for new/deleted files
- **Related changes**: Clickable pills linking between related sections
- **Review status**: Per-section approve (✓) / reject (✗) / concern (⚠) toggles, persisted in localStorage
- **Review checklist**: Per-section toggleable pills (Tests, Error handling, Docs, Security), persisted in localStorage
- **Reviewer notes**: Per-section text area, persisted in localStorage
- **Note indicator**: Pencil icon on collapsed sections that have a note
- **Commit timeline**: Vertical timeline with dots, commit info, and file pills linking to sections
- **Command palette**: `⌘K` / `Ctrl+K` or `/` opens fuzzy search across all sections and tabs
- **Keyboard shortcuts**: `j`/`k` navigate, `e` expand, `x` cycle status, `n` next unreviewed
- **Deep linking**: URL hash reflects current tab and section (`#features/src-auth-middleware-rs`)
- **Export**: Copies all sections with statuses/notes as structured markdown — includes full code context for use in PR comments or coding agent prompts
- **Copy section**: Per-section button copies that section as structured markdown context
- **Scroll breadcrumb**: Sticky bar showing current tab and section while scrolling
- **Print stylesheet**: Light backgrounds, all panels expanded, controls hidden
