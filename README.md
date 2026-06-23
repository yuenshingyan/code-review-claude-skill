# code-review

A Claude Code skill that generates interactive visual code reviews as self-contained HTML files. It analyzes your git diffs, classifies changes by type, and produces a review UI with side-by-side diffs, keyboard navigation, review status tracking, and markdown export.

## Features

- **Three review modes**: uncommitted changes, commits since main, or any custom ref
- **Tabbed navigation**: Summary, Features, Bug Fixes, Refactors, Chores, Commits timeline, Skipped files
- **Side-by-side diffs**: Before/after with syntax-colored added/removed lines; full-width for new/deleted files
- **Review status**: Per-section approve/reject/concern toggles, persisted in localStorage
- **Review checklist**: Toggleable pills (Tests, Error handling, Docs, Security) per section
- **Reviewer notes**: Per-section text area, persisted in localStorage
- **Keyboard shortcuts**: `j`/`k` navigate, `e` expand, `x` cycle status, `n` next unreviewed
- **Command palette**: `/` or `Cmd+K` for fuzzy search across all sections
- **Export**: Copy all reviewed sections with statuses and notes as structured markdown
- **Deep linking**: URL hash reflects current tab and section
- **Related changes**: Clickable pills linking between related files
- **Scale guidance**: Adapts detail level for small (≤15 files), medium (16-40), and large (>40) diffs

## Install

Clone this repo directly into your Claude Code skills directory:

```bash
git clone https://github.com/yuenshingyan/code-review-claude-skill ~/.claude/skills/code-review
```

That's it. Claude Code auto-discovers skills in `~/.claude/skills/`.

### Update

```bash
cd ~/.claude/skills/code-review && git pull
```

### Uninstall

```bash
rm -rf ~/.claude/skills/code-review
```

## Usage

In any git project, use one of:

- `/code-review` — invokes the skill directly
- "review my changes" — natural language trigger
- "code review since main" — natural language with a specific ref

Claude will ask which changes to review, analyze the diffs, and write a `code-review.html` file to the project root. Open it in any browser.

## Example

See [examples/code-review.html](examples/code-review.html) for a sample output you can open in your browser.

## License

MIT
