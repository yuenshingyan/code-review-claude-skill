#!/usr/bin/env python3
"""Build code-review.html from parsed hunks and editorial review JSON.

Usage:
    python3 build_review.py <hunks.json> <review.json> <template.html> <output.html>

Steps:
1. Assign parsed diff hunks to review sections as before/after code blocks
2. Validate (hunk gaps, missing blocks)
3. Inject the final JSON into the HTML template
4. Write output HTML

Hunk matching strategy:
- Extract keywords from section desc/identifiers/context/why/how
- For modified sections: prefer a paired hunk (both removed+added with
  keywords on both sides, >=2 changed lines each side)
- Fall back to independent before/after matching by keyword score
- Track claimed hunks per file to avoid double-assignment

Exit code 0 on success, 1 if hunk gap violations or injection failure.
"""

import sys
import json


def has_changes(hunk, side, change_type):
    return any(item['type'] == change_type for item in hunk.get(side, []))


def hunk_all_text(hunk, side):
    return ' '.join(item['text'] for item in hunk.get(side, []))


def hunk_changed_text(hunk, side, change_type):
    return ' '.join(item['text'] for item in hunk.get(side, []) if item['type'] == change_type)


def n_changed(hunk, side, change_type):
    return sum(1 for h in hunk.get(side, []) if h['type'] == change_type)


STOP_WORDS = {'this', 'that', 'with', 'from', 'into', 'each', 'when', 'then',
              'will', 'uses', 'used', 'adds', 'code', 'line', 'file', 'data',
              'also', 'same', 'were', 'been', 'have', 'more', 'only', 'page',
              'item', 'items', 'project', 'every', 'call', 'runs'}


def extract_keywords(section):
    words = set()
    for field in ('desc', 'context', 'why', 'how'):
        text = section.get(field, '') or ''
        for w in text.replace('/', ' ').replace('_', ' ').replace('<code>', ' ').replace('</code>', ' ').split():
            if len(w) > 3:
                words.add(w.lower().rstrip('.,;:'))
    for block_name in ('before', 'after'):
        block = section.get(block_name)
        if isinstance(block, dict):
            for ident in block.get('identifiers', []):
                name = ident.get('name', '')
                if name:
                    words.add(name.lower())
                    for p in name.split('_'):
                        if len(p) > 3:
                            words.add(p.lower())
    words -= STOP_WORDS
    return list(words)


def score_hunk(hunk, side, keywords):
    text = hunk_all_text(hunk, side).lower()
    return sum(1 for kw in keywords if kw in text)


def score_hunk_changed(hunk, side, change_type, keywords):
    text = hunk_changed_text(hunk, side, change_type).lower()
    return sum(1 for kw in keywords if kw in text)


def find_best_hunk(section, hunks, side, change_type, exclude=None):
    keywords = extract_keywords(section)
    candidates = []
    for i, hunk in enumerate(hunks):
        if exclude and i in exclude:
            continue
        if not has_changes(hunk, side, change_type):
            continue
        kw = score_hunk(hunk, side, keywords)
        n = n_changed(hunk, side, change_type)
        candidates.append((kw, n, i, hunk))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][3], candidates[0][2]


def find_paired_hunk(section, hunks, exclude=None):
    """Find a single hunk with both removed AND added lines, keywords on
    both sides, and at least 2 changed lines on each side."""
    keywords = extract_keywords(section)
    candidates = []
    for i, hunk in enumerate(hunks):
        if exclude and i in exclude:
            continue
        nr = n_changed(hunk, 'before', 'removed')
        na = n_changed(hunk, 'after', 'added')
        if nr < 2 or na < 2:
            continue
        kw_r = score_hunk_changed(hunk, 'before', 'removed', keywords)
        kw_a = score_hunk_changed(hunk, 'after', 'added', keywords)
        if kw_r == 0 or kw_a == 0:
            continue
        candidates.append((kw_r + kw_a, nr + na, i, hunk))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][3], candidates[0][2]


def preserve_field(section, block_name, field):
    block = section.get(block_name)
    if isinstance(block, dict):
        return block.get(field, [] if field == 'identifiers' else '')
    return [] if field == 'identifiers' else ''


def rebuild(review, parsed):
    file_hunks = {}
    for entry in parsed:
        file_hunks[entry['file']] = entry['hunks']

    file_claimed = {}

    for tab, entries in review['sections'].items():
        for section in entries:
            file_path = section['file']
            hunks = file_hunks.get(file_path, [])
            if not hunks:
                continue

            status = section.get('status', 'modified')
            claimed = file_claimed.setdefault(file_path, set())

            if status == 'new':
                best, idx = find_best_hunk(section, hunks, 'after', 'added', exclude=claimed)
                if best:
                    if idx is not None:
                        claimed.add(idx)
                    section['before'] = None
                    section['after'] = {
                        'code': best['after'],
                        'identifiers': preserve_field(section, 'after', 'identifiers'),
                        'explanation': preserve_field(section, 'after', 'explanation'),
                    }
            elif status == 'deleted':
                best, idx = find_best_hunk(section, hunks, 'before', 'removed', exclude=claimed)
                if best:
                    if idx is not None:
                        claimed.add(idx)
                    section['before'] = {
                        'code': best['before'],
                        'identifiers': preserve_field(section, 'before', 'identifiers'),
                        'explanation': preserve_field(section, 'before', 'explanation'),
                    }
                    section['after'] = None
            else:
                paired, pidx = find_paired_hunk(section, hunks, exclude=claimed)
                if paired:
                    if pidx is not None:
                        claimed.add(pidx)
                    before_hunk = paired
                    after_hunk = paired
                else:
                    before_hunk, bidx = find_best_hunk(section, hunks, 'before', 'removed', exclude=claimed)
                    after_hunk, aidx = find_best_hunk(section, hunks, 'after', 'added', exclude=claimed)
                    if bidx is not None:
                        claimed.add(bidx)
                    if aidx is not None:
                        claimed.add(aidx)

                if before_hunk:
                    section['before'] = {
                        'code': before_hunk['before'],
                        'identifiers': preserve_field(section, 'before', 'identifiers'),
                        'explanation': preserve_field(section, 'before', 'explanation'),
                    }
                if after_hunk:
                    section['after'] = {
                        'code': after_hunk['after'],
                        'identifiers': preserve_field(section, 'after', 'identifiers'),
                        'explanation': preserve_field(section, 'after', 'explanation'),
                    }


def validate(review):
    total = sum(len(e) for e in review['sections'].values())
    violations = 0
    no_before = 0
    no_after = 0
    context_only = 0
    for tab, entries in review['sections'].items():
        for section in entries:
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
                    ln = item.get('line')
                    if isinstance(ln, int):
                        if prev is not None and ln - prev > 5:
                            violations += 1
                            print(f"  GAP: {section['file']} ({block_name}): {prev} -> {ln}")
                        prev = ln
    print(f"\n{total} sections rebuilt")
    print(f"Gap violations: {violations}")
    print(f"Modified missing before: {no_before}")
    print(f"Modified missing after: {no_after}")
    print(f"Context-only blocks: {context_only}")
    return violations


DEFAULT_PLACEHOLDER = '{"title":"","projectName":"","date":"","scope":"","stats":{"files":0,"added":0,"deleted":0},"commits":[],"sections":{"features":[],"fixes":[],"refactors":[],"chores":[]}}'


def inject(review, template_path, output_path):
    with open(template_path, encoding='utf-8') as f:
        template = f.read()

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
