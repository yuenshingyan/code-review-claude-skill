#!/usr/bin/env python3
"""Parse unified diff into structured hunks for code review JSON.

Usage:
    git diff | python3 parse_diff.py
    git diff | python3 parse_diff.py > hunks.json

Output: JSON array of file entries, each with hunks containing
before/after code arrays matching the review template schema.
"""

import sys
import json
import re

HUNK_HEADER = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$')

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
                'old_file': None,
                'status': 'modified',
                'added': 0,
                'removed': 0,
                'hunks': [],
            }
            current_hunk = None
            continue

        if not current_file:
            continue

        # Detect renames
        if line.startswith('rename from '):
            current_file['old_file'] = line[len('rename from '):]
            current_file['status'] = 'renamed'
        elif line.startswith('rename to '):
            current_file['file'] = line[len('rename to '):]

        # Detect new/deleted
        if line.startswith('--- /dev/null'):
            current_file['status'] = 'new'
        elif line.startswith('+++ /dev/null'):
            current_file['status'] = 'deleted'

        # Skip other header lines
        if line.startswith('--- ') or line.startswith('+++ '):
            continue
        if line.startswith('index ') or line.startswith('new file') or line.startswith('deleted file'):
            continue
        if line.startswith('similarity') or line.startswith('rename ') or line.startswith('old mode') or line.startswith('new mode'):
            continue

        # Hunk header
        m = HUNK_HEADER.match(line)
        if m:
            if current_hunk:
                current_file['hunks'].append(current_hunk)
            old_line = int(m.group(1))
            new_line = int(m.group(3))
            function_context = m.group(5).strip() if m.group(5) else ''
            current_hunk = {
                'old_start': old_line,
                'new_start': new_line,
                'function_context': function_context,
                'before': [],  # context + removed lines with old line numbers
                'after': [],   # context + added lines with new line numbers
            }
            continue

        if not current_hunk:
            continue

        # Diff content lines
        if line.startswith('-'):
            text = line[1:]
            current_hunk['before'].append({
                'line': old_line,
                'text': text,
                'type': 'removed',
            })
            old_line += 1
            current_file['removed'] += 1
        elif line.startswith('+'):
            text = line[1:]
            current_hunk['after'].append({
                'line': new_line,
                'text': text,
                'type': 'added',
            })
            new_line += 1
            current_file['added'] += 1
        elif line.startswith(' ') or line == '':
            text = line[1:] if line.startswith(' ') else ''
            current_hunk['before'].append({
                'line': old_line,
                'text': text,
                'type': 'context',
            })
            current_hunk['after'].append({
                'line': new_line,
                'text': text,
                'type': 'context',
            })
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
