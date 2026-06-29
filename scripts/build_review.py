#!/usr/bin/env python3
"""Build code-review.html from parsed hunks and editorial review JSON.

Usage:
    python3 build_review.py <hunks.json> <review.json> <template.html> <output.html>

Steps:
1. Match review sections to parsed diff hunks by line number
2. Validate (hunk gaps, missing blocks)
3. Inject the final JSON into the HTML template
4. Write output HTML

Hunk matching strategy:
- Each section specifies a "lines" array of old_start line numbers
- The build script looks up each line number in the file's hunk list
- Multiple line numbers produce merged code blocks with separators
- No keyword scoring or claimed-set tracking needed

Exit code 0 on success, 1 if hunk gap violations or injection failure.
"""

import sys
import os
import json
import re


def read_source_lines(file_path):
    """Read a source file and return a list of lines (0-indexed)."""
    for candidate in [file_path, os.path.join('.', file_path)]:
        if os.path.isfile(candidate):
            with open(candidate, encoding='utf-8', errors='replace') as f:
                return f.readlines()
    return None


# Cache to avoid re-reading the same file multiple times
_source_cache = {}


def get_source_lines(file_path):
    if file_path not in _source_cache:
        _source_cache[file_path] = read_source_lines(file_path)
    return _source_cache[file_path]


FUNC_SIG_PATTERNS = [
    re.compile(r'^\s*(pub(\s*\(.*?\))?\s+)?(async\s+)?fn\s+\w'),      # Rust fn
    re.compile(r'^\s*(async\s+)?def\s+\w'),                             # Python def
    re.compile(r'^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w'),  # JS/TS
    re.compile(r'^\s*(public|private|protected|internal)\b.*\w\s*\('),  # Java/C#/Swift
]


def find_enclosing_signature(source_lines, first_line_1idx, max_lookback=200):
    """Walk backward from first_line_1idx (1-indexed) to the nearest function
    signature. For Rust, extends backward to include attached #[...] attributes.
    Returns 1-indexed line number of the signature start, or None."""
    stop = max(0, first_line_1idx - max_lookback - 2)
    for i in range(first_line_1idx - 2, stop, -1):
        if 0 <= i < len(source_lines):
            for pat in FUNC_SIG_PATTERNS:
                if pat.match(source_lines[i]):
                    sig_start = i
                    for j in range(i - 1, max(0, i - 10) - 1, -1):
                        if 0 <= j < len(source_lines) and source_lines[j].lstrip().startswith('#['):
                            sig_start = j
                        else:
                            break
                    return sig_start + 1  # 1-indexed
    return None


def _signature_preamble(source, sig_start, first_line):
    """Return context line objects from sig_start up to (not including) first_line.
    If preamble > 12 lines, include just the signature through '{' + '...' separator."""
    preamble_count = first_line - sig_start
    if preamble_count <= 12:
        return [
            {'line': ln, 'text': source[ln - 1].rstrip('\n'), 'type': 'context'}
            for ln in range(sig_start, first_line)
            if 0 <= ln - 1 < len(source)
        ]
    sig_end = sig_start
    for ln in range(sig_start, min(sig_start + 20, first_line)):
        if 0 <= ln - 1 < len(source) and '{' in source[ln - 1]:
            sig_end = ln
            break
    lines = [
        {'line': ln, 'text': source[ln - 1].rstrip('\n'), 'type': 'context'}
        for ln in range(sig_start, sig_end + 1)
        if 0 <= ln - 1 < len(source)
    ]
    if sig_end + 1 < first_line:
        lines.append({'line': '', 'text': '...', 'type': 'separator'})
    return lines


def prepend_function_context(code, file_path):
    """Prepend the enclosing function signature before each code segment.
    Segments are runs of non-separator lines split by '...' markers. When
    consecutive segments share the same enclosing function, the signature is
    only prepended before the first such segment."""
    if not code or not file_path:
        return code
    source = get_source_lines(file_path)
    if not source:
        return code

    segments = []
    current = []
    for item in code:
        if item.get('type') == 'separator':
            segments.append(('code', current))
            segments.append(('sep', [item]))
            current = []
        else:
            current.append(item)
    segments.append(('code', current))

    result = []
    last_sig_start = None
    for kind, items in segments:
        if kind == 'sep' or not items:
            result.extend(items)
            continue
        first_line = next((it['line'] for it in items if isinstance(it.get('line'), int)), None)
        if first_line and first_line > 1:
            sig_start = find_enclosing_signature(source, first_line)
            if sig_start and sig_start < first_line and sig_start != last_sig_start:
                result.extend(_signature_preamble(source, sig_start, first_line))
                last_sig_start = sig_start
        result.extend(items)
    return result


def merge_hunk_sides(hunks, side, file_path=None):
    """Merge code arrays from multiple hunks into one, separated by '...' markers.
    Gap lines are never filled: they are always unchanged context, and
    prepend_function_context handles orientation by showing function signatures."""
    if not hunks:
        return []
    merged = []
    for hunk in hunks:
        code = hunk.get(side, [])
        if not code:
            continue
        if merged:
            merged.append({'line': '', 'text': '...', 'type': 'separator'})
        merged.extend(code)
    return merged


def preserve_field(section, block_name, field):
    block = section.get(block_name)
    if isinstance(block, dict):
        return block.get(field, [] if field == 'identifiers' else '')
    return [] if field == 'identifiers' else ''


def build_hunk_index(hunks):
    """Build a dict from old_start line number to hunk for O(1) lookup."""
    index = {}
    for hunk in hunks:
        index[hunk['old_start']] = hunk
    return index


def rebuild(review, parsed):
    file_hunks = {}
    for entry in parsed:
        file_hunks[entry['file']] = build_hunk_index(entry['hunks'])

    for tab, entries in review['sections'].items():
        for section in entries:
            file_path = section['file']
            hunk_index = file_hunks.get(file_path, {})
            if not hunk_index:
                continue

            status = section.get('status', 'modified')
            line_numbers = section.get('lines', [])
            if not line_numbers:
                continue

            matched_hunks = []
            for ln in line_numbers:
                hunk = hunk_index.get(ln)
                if hunk:
                    matched_hunks.append(hunk)

            if not matched_hunks:
                continue

            if status == 'new':
                section['before'] = None
                section['after'] = {
                    'code': prepend_function_context(merge_hunk_sides(matched_hunks, 'after', file_path), file_path),
                    'function_context': matched_hunks[0].get('function_context', ''),
                    'identifiers': preserve_field(section, 'after', 'identifiers'),
                    'explanation': preserve_field(section, 'after', 'explanation'),
                }
            elif status == 'deleted':
                section['before'] = {
                    'code': prepend_function_context(merge_hunk_sides(matched_hunks, 'before', file_path), file_path),
                    'function_context': matched_hunks[0].get('function_context', ''),
                    'identifiers': preserve_field(section, 'before', 'identifiers'),
                    'explanation': preserve_field(section, 'before', 'explanation'),
                }
                section['after'] = None
            else:
                section['before'] = {
                    'code': prepend_function_context(merge_hunk_sides(matched_hunks, 'before', file_path), file_path),
                    'function_context': matched_hunks[0].get('function_context', ''),
                    'identifiers': preserve_field(section, 'before', 'identifiers'),
                    'explanation': preserve_field(section, 'before', 'explanation'),
                }
                section['after'] = {
                    'code': prepend_function_context(merge_hunk_sides(matched_hunks, 'after', file_path), file_path),
                    'function_context': matched_hunks[0].get('function_context', ''),
                    'identifiers': preserve_field(section, 'after', 'identifiers'),
                    'explanation': preserve_field(section, 'after', 'explanation'),
                }


def validate(review):
    total = sum(len(e) for e in review['sections'].values())
    violations = 0
    no_before = 0
    no_after = 0
    no_lines = 0
    context_only = 0
    for tab, entries in review['sections'].items():
        for section in entries:
            if not section.get('lines'):
                no_lines += 1
                print(f"  NO LINES: {section['file']}: {section['desc']}")
            if section.get('status') == 'modified':
                if section.get('before') is None:
                    no_before += 1
                    print(f"  NO BEFORE: {section['file']}: {section['desc']}")
                if section.get('after') is None:
                    no_after += 1
                    print(f"  NO AFTER: {section['file']}: {section['desc']}")
            for block_name in ('before', 'after'):
                block = section.get(block_name)
                if not isinstance(block, dict):
                    continue
                code = block.get('code', [])
                changed = [c for c in code if c['type'] in ('added', 'removed')]
                if not changed:
                    context_only += 1
                    print(f"  CONTEXT-ONLY: {section['file']} {block_name}: {section['desc']}")
                prev = None
                for item in code:
                    if item.get('type') == 'separator':
                        prev = None
                        continue
                    ln = item.get('line')
                    if isinstance(ln, int):
                        if prev is not None and ln - prev > 5:
                            violations += 1
                            print(f"  GAP: {section['file']} ({block_name}): {prev} -> {ln}")
                        prev = ln
    print(f"\n{total} sections rebuilt")
    print(f"Gap violations: {violations}")
    print(f"Missing lines field: {no_lines}")
    print(f"Modified missing before: {no_before}")
    print(f"Modified missing after: {no_after}")
    print(f"Context-only blocks: {context_only}")
    return violations


DEFAULT_PLACEHOLDER = '{"title":"","projectName":"","date":"","scope":"","stats":{"files":0,"added":0,"deleted":0},"commits":[],"sections":{}}'


def _load_vendor_hljs():
    """Return (js_content, css_content) from vendor/ next to this script, or ('', '')."""
    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vendor_dir = os.path.join(skill_root, 'vendor')

    js_path = os.path.join(vendor_dir, 'highlight.min.js')
    if not os.path.isfile(js_path):
        return '', ''

    with open(js_path, encoding='utf-8') as f:
        js_content = f.read()

    css_content = ''
    try:
        css_files = sorted(
            f for f in os.listdir(vendor_dir) if f.endswith('.css')
        )
        if css_files:
            with open(os.path.join(vendor_dir, css_files[0]), encoding='utf-8') as f:
                css_content = f.read()
    except OSError:
        pass

    return js_content, css_content


def inject(review, template_path, output_path):
    with open(template_path, encoding='utf-8') as f:
        template = f.read()

    hljs_js, hljs_css = _load_vendor_hljs()
    if hljs_js:
        print("highlight.js found — syntax highlighting enabled")
        template = template.replace('/* HLJS_CSS_PLACEHOLDER */', hljs_css, 1)
        template = template.replace('/* HLJS_JS_PLACEHOLDER */', hljs_js, 1)
    else:
        print("no highlight.js in vendor/ — skipping syntax highlighting")
        template = template.replace('/* HLJS_CSS_PLACEHOLDER */', '', 1)
        template = template.replace('/* HLJS_JS_PLACEHOLDER */', '', 1)

    json_str = json.dumps(review, ensure_ascii=False)
    placeholder = f'<script id="review-data" type="application/json">{DEFAULT_PLACEHOLDER}</script>'
    replacement = f'<script id="review-data" type="application/json">{json_str}</script>'

    result = template.replace(placeholder, replacement)
    if json_str not in result:
        print("ERROR: template injection failed — placeholder not found")
        return False

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)

    print(f"Written: {output_path} ({len(result)} bytes)")
    return True


if __name__ == '__main__':
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <hunks.json> <review.json> <template.html> <output.html>")
        sys.exit(2)

    hunks_path = sys.argv[1]
    review_path = sys.argv[2]
    template_path = sys.argv[3]
    output_path = sys.argv[4]

    with open(hunks_path) as f:
        parsed = json.load(f)
    with open(review_path) as f:
        review = json.load(f)

    rebuild(review, parsed)
    violations = validate(review)

    if violations:
        print("\nFix violations before injecting.")
        sys.exit(1)

    if not inject(review, template_path, output_path):
        sys.exit(1)

    with open(review_path, 'w') as f:
        json.dump(review, f, indent=2, ensure_ascii=False)
