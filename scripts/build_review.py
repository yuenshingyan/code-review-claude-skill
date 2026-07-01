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

from __future__ import annotations

import sys
import os
import json
from typing import Any


def embed_diff_metadata(
    review: dict[str, Any],
    parsed: list[dict[str, Any]],
) -> None:
    """Enrich each review section with absolute file path and start line.

    Builds an index of hunks keyed by ``(file_path, old_start)`` for O(1)
    lookup, then walks every section in the review and writes ``absPath``
    (absolute filesystem path) and ``startLine`` (the hunk line number
    used by the "Jump to line" button in the HTML viewer).

    Parameters
    ----------
    review : dict[str, Any]
        Parsed review JSON.  Must contain a ``sections`` key mapping tab
        names to lists of section dicts.  Modified **in place**.
    parsed : list[dict[str, Any]]
        Parsed diff entries (output of ``parse_diff``), each with ``file``
        and ``hunks`` keys.  See ``FileEntry`` / ``Hunk`` in
        ``parse_diff.py`` for the canonical structure.

    Notes
    -----
    Mutates *review* in place; does not return a value.  ``absPath`` is
    constructed from the current working directory via ``os.getcwd()``.
    """
    # Build hunk index keyed by (file_path, old_start) for O(1) lookup
    hunk_index: dict[str, dict[int, dict[str, Any]]] = {}
    for entry in parsed:
        file_path: str = entry['file']
        hunk_index[file_path] = {h['old_start']: h for h in entry['hunks']}

    repo_root = os.getcwd()

    for tab, entries in review['sections'].items():
        for section in entries:
            file_path = section['file']
            section['absPath'] = os.path.join(repo_root, file_path)

            line_numbers: list[int] = section.get('lines', [])
            file_hunks: dict[int, dict[str, Any]] = hunk_index.get(file_path, {})
            status: str = section.get('status', 'modified')

            if status == 'new':
                # New files have no old_start; locate hunk by new_start instead
                all_hunks = list(file_hunks.values())
                if all_hunks:
                    section['startLine'] = all_hunks[0].get('new_start', 1)
            elif line_numbers:
                anchor_ln = min(line_numbers)
                hunk = file_hunks.get(anchor_ln)
                if hunk:
                    section['startLine'] = hunk['old_start']
                    # If this hunk only deletes (no additions), also include the
                    # next hunk so the After panel can show the replacement code.
                    has_additions = any(line['type'] == 'added' for line in hunk.get('after', []))
                    if not has_additions and hunk.get('before'):
                        sorted_starts = sorted(file_hunks)
                        idx = sorted_starts.index(anchor_ln)
                        if idx + 1 < len(sorted_starts):
                            next_start = sorted_starts[idx + 1]
                            if next_start not in line_numbers:
                                section['lines'] = list(line_numbers) + [next_start]
            elif file_hunks:
                # No lines specified — default to the first hunk
                first_hunk = next(iter(file_hunks.values()))
                section['startLine'] = first_hunk['old_start']


def validate(review: dict[str, Any]) -> int:
    """Validate that every review section has an ``absPath`` set.

    Iterates over all sections and prints a diagnostic for each one
    missing an absolute path.  Intended to be called after
    ``embed_diff_metadata`` and before ``inject``.

    Parameters
    ----------
    review : dict[str, Any]
        Review JSON with sections already processed by
        ``embed_diff_metadata``.

    Returns
    -------
    int
        Number of sections missing an ``absPath``.  Zero means all
        sections are valid and ready for injection.
    """
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


def check_hunk_coverage(review: dict[str, Any], parsed: list[dict[str, Any]]) -> int:
    """Warn about hunks that no section's ``lines`` array claims.

    Cross-checks every hunk in *parsed* (``hunks.json``) against the union
    of ``lines`` across all sections for that file. A hunk claimed by
    neither a section's ``old_start`` nor ``new_start`` entries most often
    means a section's ``why``/``how``/``when`` narrates behavior spanning
    multiple hunks but only listed one of them (see the ``lines`` field
    rule in ``SKILL.md``) — the un-listed hunk renders as plain,
    unhighlighted context in the diff panel even though the prose
    describes it.

    Parameters
    ----------
    review : dict[str, Any]
        Review JSON with sections already processed by
        ``embed_diff_metadata``.
    parsed : list[dict[str, Any]]
        Parsed diff entries (output of ``parse_diff``).

    Returns
    -------
    int
        Number of orphaned hunks found. Non-fatal — this is a heuristic
        (a file may legitimately have hunks with no sections at all, e.g.
        if every hunk in it was deliberately left un-annotated), so
        callers should warn rather than block the build.
    """
    claimed_by_file: dict[str, set[int]] = {}
    for entries in review['sections'].values():
        for section in entries:
            claimed = claimed_by_file.setdefault(section['file'], set())
            claimed.update(section.get('lines', []))

    orphaned = 0
    for entry in parsed:
        file_path = entry['file']
        claimed = claimed_by_file.get(file_path)
        if not claimed:
            continue  # file has no sections at all — out of scope for this check
        for hunk in entry.get('hunks', []):
            if hunk['old_start'] in claimed or hunk['new_start'] in claimed:
                continue
            print(f"  ORPHANED HUNK: {file_path} hunk at old_start={hunk['old_start']} is not "
                  f"referenced by any section's `lines` — if a section's why/how/when narrates "
                  f"this hunk's behavior, add {hunk['old_start']} to its `lines` array.")
            orphaned += 1
    if orphaned:
        print(f"\n{orphaned} hunk(s) not covered by any section's `lines` (see warnings above).")
    return orphaned


def check_file_contents_coverage(
    parsed: list[dict[str, Any]],
    file_contents: list[dict[str, Any]],
) -> int:
    """Verify every file with hunks has a matching file-contents entry.

    Cross-checks each file in *parsed* (``hunks.json``, whose paths come
    straight from the diff's ``diff --git a/... b/...`` header and are never
    truncated) against the ``file`` keys in *file_contents*
    (``file-contents.json``). A mismatch — from a truncated path, an encoding
    difference, or any other divergence between the two extraction paths —
    means the template's ``fileContentsByFile[s.file]`` lookup misses and the
    before/after diff panel renders blank for that file, so this is treated
    as a blocking error rather than a soft warning.

    Parameters
    ----------
    parsed : list[dict[str, Any]]
        Parsed diff entries (output of ``parse_diff``).
    file_contents : list[dict[str, Any]]
        Before/after file-contents entries (``file-contents.json``).

    Returns
    -------
    int
        Number of files in *parsed* with no matching ``file_contents`` entry.
    """
    contents_files = {fc['file'] for fc in file_contents}
    missing = 0
    for entry in parsed:
        file_path = entry['file']
        if file_path not in contents_files:
            print(f"  MISSING FILE CONTENTS: {file_path} has hunks but no matching entry in "
                  f"file-contents.json — the diff panel for this file will render blank.")
            missing += 1
    if missing:
        print(f"\n{missing} file(s) missing from file-contents.json.")
    return missing


DEFAULT_PLACEHOLDER: str = '{"title":"","projectName":"","date":"","scope":"","stats":{"files":0,"added":0,"deleted":0},"commits":[],"sections":{}}'
HUNKS_PLACEHOLDER: str = '<script id="hunks-data" type="application/json">[]</script>'
FILE_CONTENTS_PLACEHOLDER: str = '<script id="file-contents-data" type="application/json">[]</script>'


def _escape_for_script_tag(json_str: str) -> str:
    """Escape `</` so embedded source containing a literal `</script>` (e.g.
    this very file's own placeholder constants, or any reviewed HTML/JS) can't
    prematurely close the surrounding inline `<script>` tag. `\\/` parses back
    to `/` in JSON, so this is a no-op for the data itself.
    """
    return json_str.replace('</', '<\\/')


def inject(
    review: dict[str, Any],
    parsed: list[dict[str, Any]],
    file_contents: list[dict[str, Any]],
    template_path: str,
    output_path: str,
) -> bool:
    """Inject review data, hunks, and file contents into the HTML template.

    Reads the template HTML, replaces placeholder ``<script>`` tags with
    serialised JSON data, and writes the final self-contained review page.

    Parameters
    ----------
    review : dict[str, Any]
        Fully enriched review JSON (with ``absPath`` / ``startLine``).
    parsed : list[dict[str, Any]]
        Parsed diff hunks to embed in the ``hunks-data`` script tag.
    file_contents : list[dict[str, Any]]
        Before/after file line arrays for the inline source viewer.
    template_path : str
        Path to the HTML template file containing placeholder script tags.
    output_path : str
        Path where the final HTML review page will be written.

    Returns
    -------
    bool
        ``True`` if injection succeeded, ``False`` if the placeholder was
        not found in the template (indicating a template mismatch).
    """
    with open(template_path, encoding='utf-8') as f:
        template = f.read()

    json_str = _escape_for_script_tag(json.dumps(review, ensure_ascii=False))
    # Placeholder must exactly match the template's initial script tag content
    placeholder = f'<script id="review-data" type="application/json">{DEFAULT_PLACEHOLDER}</script>'
    replacement = f'<script id="review-data" type="application/json">{json_str}</script>'

    result = template.replace(placeholder, replacement)
    # Safety check — if the review JSON is absent, the placeholder didn't match
    if json_str not in result:
        print("ERROR: template injection failed — placeholder not found")
        return False

    hunks_str = _escape_for_script_tag(json.dumps(parsed, ensure_ascii=False))
    result = result.replace(HUNKS_PLACEHOLDER, f'<script id="hunks-data" type="application/json">{hunks_str}</script>')

    file_contents_str = _escape_for_script_tag(json.dumps(file_contents, ensure_ascii=False))
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

    with open(hunks_path, encoding="utf-8") as f:
        parsed = json.load(f)
    with open(file_contents_path, encoding="utf-8") as f:
        file_contents = json.load(f)
    with open(review_path, encoding="utf-8") as f:
        review = json.load(f)

    embed_diff_metadata(review, parsed)

    if validate(review):
        print("\nFix missing paths before injecting.")
        sys.exit(1)

    if check_file_contents_coverage(parsed, file_contents):
        print("\nFix missing file-contents entries before injecting.")
        sys.exit(1)

    check_hunk_coverage(review, parsed)

    if not inject(review, parsed, file_contents, template_path, output_path):
        sys.exit(1)

    with open(review_path, 'w', encoding="utf-8") as f:
        json.dump(review, f, indent=2, ensure_ascii=False)
