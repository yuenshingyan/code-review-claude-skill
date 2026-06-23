# Changelog

## 1.0.0 — 2026-06-23

Initial public release.

- Interactive visual code review generation via Claude Code
- Three review modes: uncommitted changes, commits since main, commits since custom ref
- Tabbed UI: Summary, Features, Bug Fixes, Refactors, Chores, Commits, Skipped
- Side-by-side before/after diffs with syntax highlighting
- Per-section review status (approve/reject/concern) persisted in localStorage
- Review checklist, reviewer notes, and export to markdown
- Keyboard navigation and command palette
- Scale guidance for small, medium, and large diffs
- Automatic skip list for lock files, generated code, and vendored dependencies
