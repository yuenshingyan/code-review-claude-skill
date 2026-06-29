#!/usr/bin/env python3
"""Build code-review.html from parsed hunks and editorial review JSON.

Usage:
    python3 build_review.py <hunks.json> <review.json> <template.html> <output.html>

Steps:
1. Embed diff metadata (absPath, startLine) into each review section
2. Validate (missing paths)
3. Inject the final JSON into the HTML template
4. Write output HTML
"""

import sys
import os
import json


def embed_diff_metadata(review, parsed):
    """Write absPath and startLine into each section.

    absPath: absolute path to the file (after-side for new/modified, before-side for deleted).
    startLine: the hunk's old_start (or new_start for new files) where the change begins —
               used by the 'Jump to line' button in the HTML.
    """
    hunk_index = {}
    for entry in parsed:
        file_path = entry['file']
        hunk_index[file_path] = {h['old_start']: h for h in entry['hunks']}

    repo_root = os.getcwd()

    for tab, entries in review['sections'].items():
        for section in entries:
            file_path = section['file']
            section['absPath'] = os.path.join(repo_root, file_path)

            line_numbers = section.get('lines', [])
            file_hunks = hunk_index.get(file_path, {})
            status = section.get('status', 'modified')

            if status == 'new':
                # new files have no old_start; find hunk by new_start
                all_hunks = list(file_hunks.values())
                if all_hunks:
                    section['startLine'] = all_hunks[0].get('new_start', 1)
            elif line_numbers:
                first_ln = line_numbers[0]
                hunk = file_hunks.get(first_ln)
                if hunk:
                    section['startLine'] = hunk['old_start']
            elif file_hunks:
                # no lines specified — use first hunk
                first_hunk = next(iter(file_hunks.values()))
                section['startLine'] = first_hunk['old_start']


def validate(review):
    total = sum(len(e) for e in review['sections'].values())
    missing = 0
    for tab, entries in review['sections'].items():
        for section in entries:
            if not section.get('absPath'):
                missing += 1
                print(f"  NO ABS PATH: {section['file']}: {section['desc']}")
    print(f"\n{total} sections processed")
    if missing:
        print(f"Missing absPath: {missing}")
    return missing


DEFAULT_PLACEHOLDER = '{"title":"","projectName":"","date":"","scope":"","stats":{"files":0,"added":0,"deleted":0},"commits":[],"sections":{}}'
HUNKS_PLACEHOLDER = '<script id="hunks-data" type="application/json">[]</script>'
FILE_CONTENTS_PLACEHOLDER = '<script id="file-contents-data" type="application/json">[]</script>'


def inject(review, parsed, file_contents, template_path, output_path):
    with open(template_path, encoding='utf-8') as f:
        template = f.read()

    json_str = json.dumps(review, ensure_ascii=False)
    placeholder = f'<script id="review-data" type="application/json">{DEFAULT_PLACEHOLDER}</script>'
    replacement = f'<script id="review-data" type="application/json">{json_str}</script>'

    result = template.replace(placeholder, replacement)
    if json_str not in result:
        print("ERROR: template injection failed — placeholder not found")
        return False

    hunks_str = json.dumps(parsed, ensure_ascii=False)
    result = result.replace(HUNKS_PLACEHOLDER, f'<script id="hunks-data" type="application/json">{hunks_str}</script>')

    file_contents_str = json.dumps(file_contents, ensure_ascii=False)
    result = result.replace(FILE_CONTENTS_PLACEHOLDER, f'<script id="file-contents-data" type="application/json">{file_contents_str}</script>')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)

    print(f"Written: {output_path} ({len(result)} bytes)")
    return True


if __name__ == '__main__':
    if len(sys.argv) != 6:
        print(f"Usage: {sys.argv[0]} <hunks.json> <file-contents.json> <review.json> <template.html> <output.html>")
        sys.exit(2)

    hunks_path = sys.argv[1]
    file_contents_path = sys.argv[2]
    review_path = sys.argv[3]
    template_path = sys.argv[4]
    output_path = sys.argv[5]

    with open(hunks_path) as f:
        parsed = json.load(f)
    with open(file_contents_path) as f:
        file_contents = json.load(f)
    with open(review_path) as f:
        review = json.load(f)

    embed_diff_metadata(review, parsed)

    if validate(review):
        print("\nFix missing paths before injecting.")
        sys.exit(1)

    if not inject(review, parsed, file_contents, template_path, output_path):
        sys.exit(1)

    with open(review_path, 'w') as f:
        json.dump(review, f, indent=2, ensure_ascii=False)
