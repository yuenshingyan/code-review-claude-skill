#!/usr/bin/env python3
"""Extract scope-aware code blocks from hunks and source files.

Usage:
    python3 extract_scopes.py <hunks.json> <scopes.json>

For each file in hunks.json, reads the actual source (before via git,
after via filesystem), finds which fn/struct/enum/impl/trait contains
each changed line, and outputs full-scope code blocks.

Output: JSON array mirroring hunks.json structure, but each hunk is
replaced by scope-aware blocks that include the complete enclosing
scope (function, struct, enum, impl, trait) for every changed line.
"""

import sys
import json
import os
import re
import subprocess

# ---------- scope parsing ----------

SCOPE_RE = re.compile(
    r'^\s*'
    r'(?:(?:pub\s*(?:\(.*?\)\s*)?)?'
    r'(?:async\s+)?'
    r'(?:unsafe\s+)?'
    r'(?:const\s+)?)'
    r'(fn|struct|enum|impl|trait|mod|macro_rules\s*!)\s'
)


def _strip_comments_and_strings(text):
    """Remove comments and string literals, preserving line structure.
    Returns a list of cleaned lines (same count as input)."""
    result = []
    in_block_comment = False
    for line in text:
        cleaned = []
        i = 0
        chars = line
        while i < len(chars):
            if in_block_comment:
                if chars[i:i+2] == '*/':
                    in_block_comment = False
                    i += 2
                else:
                    i += 1
                continue
            if chars[i:i+2] == '//':
                break
            if chars[i:i+2] == '/*':
                in_block_comment = True
                i += 2
                continue
            if chars[i] == '"':
                # Check for raw string r#"..."# or br#"..."#
                raw_prefix = ''
                j = i - 1
                while j >= 0 and chars[j] == '#':
                    raw_prefix += '#'
                    j -= 1
                if j >= 0 and chars[j] in ('r', 'b'):
                    # raw string - skip to closing "###
                    closing = '"' + raw_prefix
                    i += 1  # skip opening "
                    while i < len(chars):
                        if chars[i:i+len(closing)] == closing:
                            i += len(closing)
                            break
                        i += 1
                    continue
                # Regular string
                i += 1
                while i < len(chars):
                    if chars[i] == '\\':
                        i += 2
                        continue
                    if chars[i] == '"':
                        i += 1
                        break
                    i += 1
                continue
            if chars[i] == '\'':
                # Character literal - skip 'x' or '\x'
                if i + 2 < len(chars) and chars[i+2] == '\'':
                    i += 3
                    continue
                if i + 3 < len(chars) and chars[i+1] == '\\' and chars[i+3] == '\'':
                    i += 4
                    continue
                # Lifetime or label, not a char literal - keep it
                cleaned.append(chars[i])
                i += 1
                continue
            cleaned.append(chars[i])
            i += 1
        result.append(''.join(cleaned))
    return result


def parse_scopes(lines):
    """Parse Rust source lines and return a list of scopes.
    Each scope: {kind, name, start, end} where start/end are 1-indexed."""
    cleaned = _strip_comments_and_strings(lines)
    scopes = []
    _parse_scopes_recursive(lines, cleaned, 0, len(lines), 0, scopes)
    return scopes


def _parse_scopes_recursive(raw_lines, cleaned_lines, start_idx, end_idx, depth, scopes):
    """Find scopes in the range [start_idx, end_idx) of cleaned_lines."""
    i = start_idx
    while i < end_idx:
        line = cleaned_lines[i]
        m = SCOPE_RE.match(line)
        if m:
            kind_raw = m.group(1).strip().rstrip('!')
            # Find the scope's attribute block (preceding #[...] lines)
            attr_start = i
            for j in range(i - 1, max(start_idx - 1, i - 20) - 1, -1):
                stripped = raw_lines[j].strip()
                if stripped.startswith('#[') or stripped.startswith('#!['):
                    attr_start = j
                elif stripped == '' or stripped.startswith('///') or stripped.startswith('//!'):
                    attr_start = j
                else:
                    break

            # Find the opening brace
            brace_line = _find_opening_brace(cleaned_lines, i, end_idx)
            if brace_line is None:
                # No brace (e.g., `mod foo;` or forward declaration)
                i += 1
                continue

            # Count braces to find the closing brace
            close_line = _find_closing_brace(cleaned_lines, brace_line, end_idx)
            if close_line is None:
                i += 1
                continue

            name = _extract_name(raw_lines[i], kind_raw)
            scope = {
                'kind': kind_raw,
                'name': name,
                'start': attr_start + 1,  # 1-indexed
                'end': close_line + 1,     # 1-indexed, inclusive
            }
            scopes.append(scope)

            # Recurse into the scope body for nested scopes (methods in impl, etc.)
            body_start = brace_line + 1
            body_end = close_line
            if body_start < body_end:
                _parse_scopes_recursive(raw_lines, cleaned_lines, body_start, body_end, depth + 1, scopes)

            i = close_line + 1
        else:
            i += 1


def _find_opening_brace(cleaned_lines, start, end):
    """Find the line containing the opening '{' for a scope starting at start."""
    for i in range(start, min(start + 30, end)):
        if '{' in cleaned_lines[i]:
            return i
    return None


def _find_closing_brace(cleaned_lines, brace_line, end):
    """From the line with the opening '{', count braces to find the matching '}'."""
    depth = 0
    for i in range(brace_line, end):
        for ch in cleaned_lines[i]:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
    return None


def _extract_name(raw_line, kind):
    """Extract the identifier name from a scope-opening line."""
    line = raw_line.strip()
    if kind == 'impl':
        # impl Foo { or impl Trait for Foo {
        m = re.search(r'\bimpl\s+(?:<[^>]*>\s*)?(\w+)', line)
        return m.group(1) if m else 'impl'
    if kind == 'macro_rules':
        m = re.search(r'macro_rules!\s*(\w+)', line)
        return m.group(1) if m else 'macro'
    # fn, struct, enum, trait, mod
    m = re.search(r'\b' + re.escape(kind) + r'\s+(\w+)', line)
    return m.group(1) if m else kind


# ---------- scope mapping ----------

def find_enclosing_scope(scopes, line_num):
    """Find the innermost scope containing line_num (1-indexed).
    Returns the scope dict, or None if outside all scopes."""
    best = None
    for s in scopes:
        if s['start'] <= line_num <= s['end']:
            if best is None or (s['end'] - s['start']) < (best['end'] - best['start']):
                best = s
    return best


def changed_lines_from_hunk_side(side_data):
    """Extract 1-indexed line numbers of changed (added/removed) lines."""
    return [item['line'] for item in side_data if item['type'] in ('added', 'removed')]


# ---------- source reading ----------

def read_file_lines(path):
    """Read a file and return lines as list of strings (no trailing newline)."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return [l.rstrip('\n') for l in f.readlines()]
    except (OSError, IOError):
        return None


def read_git_file(path):
    """Read the HEAD version of a file via git show."""
    try:
        result = subprocess.run(
            ['git', 'show', f'HEAD:{path}'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
        if result.returncode == 0:
            return [l.rstrip('\n') for l in result.stdout.splitlines()]
    except (OSError, FileNotFoundError):
        pass
    return None


# ---------- scope block assembly ----------

def build_scope_blocks(source_lines, scopes, changed_line_nums, line_type_map):
    """Build code blocks from scopes that contain changed lines.

    Returns a list of scope block dicts:
    {
        scope_name, scope_kind, scope_start, scope_end,
        code: [{line, text, type}, ...]
    }

    line_type_map: dict mapping 1-indexed line number to 'added' or 'removed'.
    Lines not in the map are 'context'.
    """
    # Group changed lines by their enclosing scope
    scope_to_lines = {}
    orphan_lines = []
    for ln in changed_line_nums:
        scope = find_enclosing_scope(scopes, ln)
        if scope:
            key = (scope['start'], scope['end'])
            if key not in scope_to_lines:
                scope_to_lines[key] = scope
            # No need to store lines - we'll render the full scope
        else:
            orphan_lines.append(ln)

    blocks = []

    # Emit full scope blocks, sorted by start line
    for key in sorted(scope_to_lines.keys()):
        scope = scope_to_lines[key]
        code = []
        for ln in range(scope['start'], scope['end'] + 1):
            idx = ln - 1
            if 0 <= idx < len(source_lines):
                line_type = line_type_map.get(ln, 'context')
                code.append({
                    'line': ln,
                    'text': source_lines[idx],
                    'type': line_type,
                })
        blocks.append({
            'scope_name': scope['name'],
            'scope_kind': scope['kind'],
            'scope_start': scope['start'],
            'scope_end': scope['end'],
            'code': code,
        })

    # Emit orphan lines (outside any scope) with minimal context
    if orphan_lines:
        orphan_lines.sort()
        # Group consecutive orphan lines (within 5 lines of each other)
        groups = []
        current_group = [orphan_lines[0]]
        for ln in orphan_lines[1:]:
            if ln - current_group[-1] <= 5:
                current_group.append(ln)
            else:
                groups.append(current_group)
                current_group = [ln]
        groups.append(current_group)

        for group in groups:
            start = max(1, group[0] - 2)
            end = min(len(source_lines), group[-1] + 2)
            code = []
            for ln in range(start, end + 1):
                idx = ln - 1
                if 0 <= idx < len(source_lines):
                    line_type = line_type_map.get(ln, 'context')
                    code.append({
                        'line': ln,
                        'text': source_lines[idx],
                        'type': line_type,
                    })
            blocks.append({
                'scope_name': '(module level)',
                'scope_kind': 'module',
                'scope_start': start,
                'scope_end': end,
                'code': code,
            })

    blocks.sort(key=lambda b: b['scope_start'])
    return blocks


# ---------- main pipeline ----------

def extract_scopes(parsed_hunks):
    """Process parsed hunks and produce scope-aware output.

    For each file, reads both old (git HEAD) and new (working tree) source,
    parses scope boundaries, and maps changed lines to their enclosing scopes.

    Returns a list of file entries with scope-aware blocks.
    """
    results = []

    for entry in parsed_hunks:
        file_path = entry['file']
        status = entry['status']
        hunks = entry['hunks']

        # Collect changed line numbers and build type maps
        before_changed = []
        before_type_map = {}
        after_changed = []
        after_type_map = {}

        for hunk in hunks:
            for item in hunk.get('before', []):
                if item['type'] == 'removed':
                    before_changed.append(item['line'])
                    before_type_map[item['line']] = 'removed'
            for item in hunk.get('after', []):
                if item['type'] == 'added':
                    after_changed.append(item['line'])
                    after_type_map[item['line']] = 'added'

        result_entry = {
            'file': file_path,
            'status': status,
            'added': entry.get('added', 0),
            'removed': entry.get('removed', 0),
        }

        # Read source files and parse scopes
        if status == 'deleted':
            old_lines = read_git_file(file_path)
            if old_lines and before_changed:
                old_scopes = parse_scopes(old_lines)
                result_entry['before_blocks'] = build_scope_blocks(
                    old_lines, old_scopes, before_changed, before_type_map)
            else:
                result_entry['before_blocks'] = []
            result_entry['after_blocks'] = []
        elif status == 'new':
            new_lines = read_file_lines(file_path)
            if new_lines and after_changed:
                new_scopes = parse_scopes(new_lines)
                result_entry['after_blocks'] = build_scope_blocks(
                    new_lines, new_scopes, after_changed, after_type_map)
            else:
                result_entry['after_blocks'] = []
            result_entry['before_blocks'] = []
        else:
            # modified or renamed
            old_path = entry.get('old_file') or file_path
            old_lines = read_git_file(old_path)
            new_lines = read_file_lines(file_path)

            if old_lines and before_changed:
                old_scopes = parse_scopes(old_lines)
                result_entry['before_blocks'] = build_scope_blocks(
                    old_lines, old_scopes, before_changed, before_type_map)
            else:
                result_entry['before_blocks'] = []

            if new_lines and after_changed:
                new_scopes = parse_scopes(new_lines)
                result_entry['after_blocks'] = build_scope_blocks(
                    new_lines, new_scopes, after_changed, after_type_map)
            else:
                result_entry['after_blocks'] = []

        results.append(result_entry)

    return results


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <hunks.json> <scopes.json>")
        sys.exit(2)

    with open(sys.argv[1], encoding='utf-8') as f:
        parsed = json.load(f)

    results = extract_scopes(parsed)

    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    total_blocks = sum(
        len(e.get('before_blocks', [])) + len(e.get('after_blocks', []))
        for e in results
    )
    print(f"{len(results)} files processed, {total_blocks} scope blocks extracted")
