#!/usr/bin/env python3
"""Parse unified diff into structured hunks for code review JSON.

Usage:
    git diff | python3 parse_diff.py
    git diff | python3 parse_diff.py > hunks.json

Output: JSON array of file entries, each with hunks containing
changed line numbers keyed by old_start/new_start.
"""

import sys
import json
import re

HUNK_HEADER = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

def parse_diff(lines):
    files = []
    current_file = None
    current_hunk = None
    old_line = 0
    new_line = 0

    for raw in lines:
        line = raw.rstrip('\n')

        # New file diff
        if line.startswith('diff --git '):
            if current_file and current_hunk:
                current_file['hunks'].append(current_hunk)
            if current_file:
                files.append(current_file)
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

        if line.startswith('rename to '):
            current_file['file'] = line[len('rename to '):]

        # Skip other header lines
        if line.startswith('--- ') or line.startswith('+++ '):
            continue
        if line.startswith('index ') or line.startswith('new file') or line.startswith('deleted file'):
            continue
        if line.startswith('similarity') or line.startswith('rename from ') or line.startswith('old mode') or line.startswith('new mode'):
            continue

        # Hunk header
        m = HUNK_HEADER.match(line)
        if m:
            if current_hunk:
                current_file['hunks'].append(current_hunk)
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

        # Diff content lines
        if line.startswith('-'):
            current_hunk['before'].append({
                'line': old_line,
                'type': 'removed',
            })
            old_line += 1
        elif line.startswith('+'):
            current_hunk['after'].append({
                'line': new_line,
                'type': 'added',
            })
            new_line += 1
        elif line.startswith(' ') or line == '':
            old_line += 1
            new_line += 1
        # Binary/no-newline markers
        elif line.startswith('\\'):
            continue

    # Flush last file/hunk
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
