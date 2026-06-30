#!/usr/bin/env python3
"""Parse unified diff into structured hunks for code review JSON.

Usage:
    git diff | python3 parse_diff.py
    git diff | python3 parse_diff.py > hunks.json

Output: JSON array of file entries, each with hunks containing
changed line numbers keyed by old_start/new_start.
"""

from __future__ import annotations

import sys
import json
import re
from typing import TypedDict


class DiffLine(TypedDict):
    """Single changed line within a hunk."""

    line: int
    type: str


class Hunk(TypedDict):
    """Contiguous block of changes within a file diff."""

    old_start: int
    new_start: int
    before: list[DiffLine]
    after: list[DiffLine]


class FileEntry(TypedDict):
    """Parsed diff for a single file, containing one or more hunks."""

    file: str
    hunks: list[Hunk]


HUNK_HEADER: re.Pattern[str] = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def parse_diff(lines: list[str]) -> list[FileEntry]:
    """Parse unified diff text into structured file entries with hunks.

    Processes a unified diff (as produced by ``git diff``) line by line
    using a state machine.  Each ``diff --git`` header starts a new file
    entry, and each ``@@`` hunk header starts a new hunk within that entry.

    Parameters
    ----------
    lines : list[str]
        Raw lines of a unified diff, typically from ``sys.stdin.readlines()``
        or ``str.splitlines()``.  Trailing newlines are stripped internally.

    Returns
    -------
    list[FileEntry]
        One entry per changed file.  Each entry contains the file path and
        a list of hunks with before/after line metadata.

    Notes
    -----
    Handles file renames (``rename to``), new files, deleted files, and
    binary/no-newline markers.  Binary diff markers (lines starting with
    ``\\``) are silently skipped.
    """
    files: list[FileEntry] = []
    current_file: FileEntry | None = None
    current_hunk: Hunk | None = None
    old_line: int = 0
    new_line: int = 0

    for raw in lines:
        line = raw.rstrip('\n')

        # Flush accumulated file/hunk when a new file header appears
        if line.startswith('diff --git '):
            if current_file and current_hunk:
                current_file['hunks'].append(current_hunk)
            if current_file:
                files.append(current_file)
            # Extract path from the "b/" side of the diff header
            parts = line.split(' b/', 1)
            path = parts[1] if len(parts) > 1 else ''
            current_file = {
                'file': path,
                'hunks': [],
            }
            current_hunk = None
            continue

        if not current_file:
            continue

        # Rename directive overrides the path from the diff header
        if line.startswith('rename to '):
            current_file['file'] = line[len('rename to '):]

        # Skip diff metadata lines that don't contain hunk content
        if line.startswith('--- ') or line.startswith('+++ '):
            continue
        if line.startswith('index ') or line.startswith('new file') or line.startswith('deleted file'):
            continue
        if line.startswith('similarity') or line.startswith('rename from ') or line.startswith('old mode') or line.startswith('new mode'):
            continue

        # Hunk header — regex captures old_start, old_count, new_start, new_count
        m = HUNK_HEADER.match(line)
        if m:
            if current_hunk:
                current_file['hunks'].append(current_hunk)
            # Initialize line counters from the hunk range header
            old_line = int(m.group(1))
            new_line = int(m.group(3))
            current_hunk = {
                'old_start': old_line,
                'new_start': new_line,
                'before': [],
                'after': [],
            }
            continue

        if not current_hunk:
            continue

        # Classify diff content lines and advance the appropriate counter
        if line.startswith('-'):
            # Removed line — only advances old (before) counter
            current_hunk['before'].append({
                'line': old_line,
                'type': 'removed',
            })
            old_line += 1
        elif line.startswith('+'):
            # Added line — only advances new (after) counter
            current_hunk['after'].append({
                'line': new_line,
                'type': 'added',
            })
            new_line += 1
        elif line.startswith(' ') or line == '':
            # Context line — advances both counters
            old_line += 1
            new_line += 1
        elif line.startswith('\\'):
            # Binary/no-newline marker — skip
            continue

    # Flush the last accumulated file and hunk
    if current_file:
        if current_hunk:
            current_file['hunks'].append(current_hunk)
        files.append(current_file)

    return files


if __name__ == '__main__':
    lines = sys.stdin.readlines()
    files = parse_diff(lines)
    json.dump(files, sys.stdout, indent=2, ensure_ascii=False)
    print()  # trailing newline
