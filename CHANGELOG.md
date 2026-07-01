# Changelog

## Unreleased

- Clarify SKILL.md guidance: a section spanning multiple hunks must list every hunk's `old_start` in `lines`, or the un-listed hunk renders unhighlighted in the diff panel
- `build_review.py` now warns (non-fatal) about hunks not claimed by any section's `lines`, catching the case where a section's narrative covers a hunk it forgot to list
- Remove the WHERE annotation from review sections; blast-radius info is already covered by the `related` field
- Add background-color styling to inline `<code>` references (file names, function/variable names) in WHY/HOW/WHEN annotations, breaking-change details, and notes
- Add click-to-trace: click an identifier in a diff panel to highlight matching occurrences within that section's Before/After panels; click again or press Escape to clear
- Restore Key Identifiers list per section (dropped by mistake in a since-reverted diff-editor-buttons change), now rendered above the diff panels and included in markdown export

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
