#!/usr/bin/env python3
"""Gather git diff, stats, and commit history for code review.

Usage:
    python3 gather_diff.py uncommitted --meta meta.json --diff raw.diff
    python3 gather_diff.py branch --meta meta.json --diff raw.diff
    python3 gather_diff.py <base-ref> --meta meta.json --diff raw.diff

Modes:
    uncommitted  — working tree + staged changes (git diff + git diff --cached)
    branch       — auto-detect default branch, diff against HEAD
    <base-ref>   — diff <base-ref>...HEAD

Outputs:
    --meta: JSON with scope, stats, commits, skipped files, changed file list
    --diff: raw unified diff (skipped files excluded) for piping into parse_diff.py

Exit code 0 on success, 1 on error.
"""

from __future__ import annotations

import sys
import subprocess
import json
import argparse
import os
from typing import Any, TypedDict


class CommitInfo(TypedDict):
    """Single commit entry from git log."""

    hash: str
    message: str
    author: str
    date: str


class SkippedFile(TypedDict):
    """File excluded from the review diff with the reason for exclusion."""

    file: str
    reason: str


class FileContents(TypedDict):
    """Before and after source lines for a changed file."""

    file: str
    before_lines: list[str]
    after_lines: list[str]


# Lock files that bloat diffs without review value
SKIP_FILENAMES: set[str] = {
    'Cargo.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'Gemfile.lock', 'poetry.lock', 'composer.lock', 'go.sum',
    'flake.lock', 'Pipfile.lock',
}

# Vendored / third-party directories
SKIP_DIRS: set[str] = {'vendor/', 'third_party/', 'node_modules/', '.git/'}

# Machine-generated file extensions
SKIP_EXTENSIONS: set[str] = {
    '.pb.go', '.pb.rs', '_pb2.py', '.pb.h', '.pb.cc',
    '.generated.ts', '.generated.js',
    '.min.js', '.min.css',
}


def run(cmd: list[str], check: bool = True) -> str:
    """Execute a shell command and return its standard output.

    Parameters
    ----------
    cmd : list[str]
        Command and arguments to pass to ``subprocess.run``.
    check : bool, optional
        If ``True`` (default), print an error message to stderr and call
        ``sys.exit(1)`` when the command exits with a non-zero return code.

    Returns
    -------
    str
        The captured standard output of the command.

    Raises
    ------
    SystemExit
        If *check* is ``True`` and the command fails (non-zero exit code).
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def should_skip(filepath: str) -> str | None:
    """Determine whether a file should be excluded from the review diff.

    Checks the file against lock-file names, vendored directory prefixes,
    and generated-code suffixes.

    Parameters
    ----------
    filepath : str
        Relative path of the changed file (as reported by ``git diff``).

    Returns
    -------
    str or None
        A human-readable reason string (e.g. ``"lock file"``,
        ``"generated code"``) if the file should be skipped, or ``None``
        if it should be kept.
    """
    basename = os.path.basename(filepath)
    if basename in SKIP_FILENAMES:
        return "lock file"
    # Check if path traverses a vendored or third-party directory
    for d in SKIP_DIRS:
        if filepath.startswith(d) or f'/{d}' in filepath:
            return f"vendored ({d.rstrip('/')})"
    for ext in SKIP_EXTENSIONS:
        if filepath.endswith(ext):
            return "generated code"
    return None


def detect_default_branch() -> str:
    """Auto-detect the repository's default branch name.

    Tries ``git symbolic-ref refs/remotes/origin/HEAD`` first.  If that
    fails (e.g. shallow clone or missing remote), falls back to probing
    ``main`` then ``master``.  Returns ``"main"`` as a last resort.

    Returns
    -------
    str
        Name of the default branch (e.g. ``"main"`` or ``"master"``).
    """
    # Primary: resolve the symbolic HEAD ref on origin
    result = subprocess.run(
        ['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip().replace('refs/remotes/origin/', '')
    # Fallback: probe common branch names directly
    for candidate in ['main', 'master']:
        check = subprocess.run(
            ['git', 'rev-parse', '--verify', candidate],
            capture_output=True, text=True
        )
        if check.returncode == 0:
            return candidate
    return 'main'


def parse_shortstat(text: str) -> tuple[int, int, int]:
    """Parse ``git diff --shortstat`` output into numeric counts.

    Each comma-separated segment contains a keyword (``file``,
    ``insertion``, ``deletion``) that identifies the stat type.

    Parameters
    ----------
    text : str
        Raw shortstat output, e.g.
        ``" 3 files changed, 42 insertions(+), 7 deletions(-)"``.

    Returns
    -------
    tuple[int, int, int]
        ``(files_changed, lines_added, lines_deleted)``.
    """
    files = 0
    added = 0
    deleted = 0
    for part in text.strip().split(','):
        part = part.strip()
        if 'file' in part:
            files = int(part.split()[0])
        elif 'insertion' in part:
            added = int(part.split()[0])
        elif 'deletion' in part:
            deleted = int(part.split()[0])
    return files, added, deleted


def parse_stat_files(text: str) -> list[str]:
    """Extract file paths from ``git diff --stat`` output.

    Parses each line of the stat table to recover file paths, handling
    the rename syntax ``{old => new}`` by extracting only the new path.
    Skips the summary line (``N files changed, ...``).

    Parameters
    ----------
    text : str
        Full output of ``git diff --stat``.

    Returns
    -------
    list[str]
        Relative file paths, one per changed file.
    """
    files: list[str] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith(' '):
            continue
        # Skip the summary line at the bottom of --stat output
        if 'changed' in line and ('insertion' in line or 'deletion' in line):
            continue
        # Format: "path/to/file | N ++--"
        parts = line.split('|')
        if len(parts) >= 2:
            path = parts[0].strip()
            # Handle renames: "src/{old => new}/file.rs" — strip braces
            # and keep only the new-side path
            if '=>' in path:
                path = path.replace('{', '').replace('}', '')
                parts2 = path.split('=>')
                if len(parts2) == 2:
                    path = parts2[1].strip()
            files.append(path)
    return files


def parse_log(text: str) -> list[CommitInfo]:
    """Parse ``git log`` output into structured commit records.

    Expects the custom format ``%h %s|%an|%ad`` (pipe-delimited fields:
    hash+message, author, date).

    Parameters
    ----------
    text : str
        Raw output of ``git log --format='%h %s|%an|%ad'``.

    Returns
    -------
    list[CommitInfo]
        One dict per commit with keys ``hash``, ``message``, ``author``,
        ``date``.
    """
    commits: list[CommitInfo] = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split('|')
        if len(parts) >= 3:
            hash_msg = parts[0].strip()
            author = parts[1].strip()
            date = parts[2].strip()
            space_idx = hash_msg.find(' ')
            if space_idx > 0:
                commits.append({
                    'hash': hash_msg[:space_idx],
                    'message': hash_msg[space_idx + 1:],
                    'author': author,
                    'date': date,
                })
    return commits


def build_excludes(skipped_files: list[str]) -> list[str]:
    """Build git pathspec exclude patterns for skipped files.

    Parameters
    ----------
    skipped_files : list[str]
        File paths to exclude from the diff.

    Returns
    -------
    list[str]
        Pathspec strings prefixed with ``:!`` suitable for appending
        after ``--`` in a ``git diff`` command.
    """
    excludes: list[str] = []
    for filepath in skipped_files:
        excludes.append(f':!{filepath}')
    return excludes


def get_file_contents(
    kept_files: list[str],
    before_ref: str,
    read_disk: bool = False,
) -> list[FileContents]:
    """Retrieve before and after file contents for the changed files.

    For each file, the "before" content is read from git at *before_ref*.
    The "after" content is either read from ``HEAD`` (committed mode) or
    from the working-tree disk (uncommitted mode, when *read_disk* is
    ``True``).

    Parameters
    ----------
    kept_files : list[str]
        Relative paths of files to retrieve contents for.
    before_ref : str
        Git ref to read the "before" version from (e.g. ``"HEAD"`` or a
        branch name).
    read_disk : bool, optional
        If ``True``, read the "after" version from the filesystem instead
        of from ``HEAD``.  Used for uncommitted-changes mode.

    Returns
    -------
    list[FileContents]
        One entry per file with ``before_lines`` and ``after_lines`` as
        lists of strings (no trailing newlines).
    """
    contents: list[FileContents] = []
    for filepath in kept_files:
        # Retrieve the "before" snapshot from git's object store
        before_result = subprocess.run(
            ['git', 'show', f'{before_ref}:{filepath}'],
            capture_output=True, text=True, errors='replace'
        )
        before_lines = before_result.stdout.splitlines() if before_result.returncode == 0 else []

        if read_disk:
            # Uncommitted mode — read current working-tree state from disk
            try:
                with open(filepath, encoding='utf-8', errors='replace') as f:
                    after_lines = f.read().splitlines()
            except FileNotFoundError:
                after_lines = []
        else:
            # Committed mode — read the HEAD version from git
            after_result = subprocess.run(
                ['git', 'show', f'HEAD:{filepath}'],
                capture_output=True, text=True, errors='replace'
            )
            after_lines = after_result.stdout.splitlines() if after_result.returncode == 0 else []

        contents.append({'file': filepath, 'before_lines': before_lines, 'after_lines': after_lines})
    return contents


def gather_uncommitted(
    meta_path: str,
    diff_path: str,
    file_contents_path: str,
) -> None:
    """Gather staged and unstaged changes and write review artifacts.

    Collects the combined unstaged + staged diff, computes stats (after
    filtering out skipped files), detects binary files, and writes three
    output files: metadata JSON, raw diff, and file-contents JSON.

    Parameters
    ----------
    meta_path : str
        Output path for the metadata JSON (scope, stats, skipped files).
    diff_path : str
        Output path for the raw unified diff text.
    file_contents_path : str
        Output path for the before/after file-contents JSON.

    Raises
    ------
    SystemExit
        If any underlying ``git`` command fails.
    """
    # Collect file lists from both staged and unstaged changes
    stat_unstaged = run(['git', 'diff', '--stat'])
    stat_staged = run(['git', 'diff', '--cached', '--stat'])

    all_files = set(parse_stat_files(stat_unstaged) + parse_stat_files(stat_staged))

    skipped: list[SkippedFile] = []
    kept: list[str] = []
    for f in sorted(all_files):
        reason = should_skip(f)
        if reason:
            skipped.append({'file': f, 'reason': reason})
        else:
            kept.append(f)

    excludes = build_excludes([s['file'] for s in skipped])

    # Compute stats after filtering — run shortstat for both unstaged and staged
    shortstat_args = ['git', 'diff', '--shortstat'] + (['--'] + excludes if excludes else [])
    shortstat_cached_args = ['git', 'diff', '--cached', '--shortstat'] + (['--'] + excludes if excludes else [])
    ss1 = run(shortstat_args)
    ss2 = run(shortstat_cached_args)
    f1, a1, d1 = parse_shortstat(ss1) if ss1.strip() else (0, 0, 0)
    f2, a2, d2 = parse_shortstat(ss2) if ss2.strip() else (0, 0, 0)

    # Collect filtered diffs from both staged and unstaged
    diff_args_base = ['--'] + excludes if excludes else []
    diff1 = run(['git', 'diff'] + diff_args_base)
    diff2 = run(['git', 'diff', '--cached'] + diff_args_base)
    combined_diff = diff1 + diff2

    # Detect binary files by scanning for "Binary files" markers in the diff
    for line in combined_diff.splitlines():
        if line.startswith('Binary files'):
            parts = line.split(' and ')
            if len(parts) >= 2:
                bfile = parts[1].replace(' differ', '').strip()
                if bfile.startswith('b/'):
                    bfile = bfile[2:]
                if bfile not in [s['file'] for s in skipped]:
                    skipped.append({'file': bfile, 'reason': 'binary file'})

    meta: dict[str, Any] = {
        'scope': 'uncommitted changes',
        'stats': {
            'files': f1 + f2,
            'added': a1 + a2,
            'deleted': d1 + d2,
        },
        'commits': [],
        'skipped': skipped,
        'files': kept,
    }

    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    with open(diff_path, 'w') as f:
        f.write(combined_diff)

    contents = get_file_contents(kept, before_ref='HEAD', read_disk=True)
    with open(file_contents_path, 'w', encoding='utf-8') as f:
        json.dump(contents, f, ensure_ascii=False)

    print(f"{len(kept)} files, +{meta['stats']['added']}/-{meta['stats']['deleted']}, {len(skipped)} skipped")


def gather_committed(
    base: str,
    meta_path: str,
    diff_path: str,
    file_contents_path: str,
) -> None:
    """Gather committed changes from a base ref to HEAD and write artifacts.

    Verifies the base ref exists, collects the three-dot diff
    (``base...HEAD``), retrieves commit history, filters out skipped
    files and binary files, and writes metadata JSON, raw diff, and
    file-contents JSON.

    Parameters
    ----------
    base : str
        Git ref to diff against (e.g. ``"main"``, a commit hash, or a
        branch name).
    meta_path : str
        Output path for the metadata JSON.
    diff_path : str
        Output path for the raw unified diff.
    file_contents_path : str
        Output path for the before/after file-contents JSON.

    Raises
    ------
    SystemExit
        If *base* does not resolve to a valid ref, or if any ``git``
        command fails.
    """
    # Fail early if the base ref is invalid to give a clear error message
    check = subprocess.run(['git', 'rev-parse', '--verify', base], capture_output=True, text=True)
    if check.returncode != 0:
        print(f"ERROR: ref '{base}' not found", file=sys.stderr)
        sys.exit(1)

    # Use -M flag to enable rename detection in stat output
    stat = run(['git', 'diff', f'{base}...HEAD', '--stat', '-M'])
    all_files = parse_stat_files(stat)

    skipped: list[SkippedFile] = []
    kept: list[str] = []
    for f in sorted(set(all_files)):
        reason = should_skip(f)
        if reason:
            skipped.append({'file': f, 'reason': reason})
        else:
            kept.append(f)

    excludes = build_excludes([s['file'] for s in skipped])

    shortstat_args = ['git', 'diff', f'{base}...HEAD', '--shortstat'] + (['--'] + excludes if excludes else [])
    ss = run(shortstat_args)
    files, added, deleted = parse_shortstat(ss) if ss.strip() else (0, 0, 0)

    # Retrieve commit log using pipe-delimited custom format
    log_out = run(['git', 'log', f'{base}..HEAD', '--oneline',
                   '--format=%h %s|%an|%ad', '--date=short'])
    commits = parse_log(log_out)

    diff_args = ['git', 'diff', f'{base}...HEAD', '-M'] + (['--'] + excludes if excludes else [])
    diff = run(diff_args)

    # Detect binary files by scanning for "Binary files" markers
    for line in diff.splitlines():
        if line.startswith('Binary files'):
            parts = line.split(' and ')
            if len(parts) >= 2:
                bfile = parts[1].replace(' differ', '').strip()
                if bfile.startswith('b/'):
                    bfile = bfile[2:]
                if bfile not in [s['file'] for s in skipped]:
                    skipped.append({'file': bfile, 'reason': 'binary file'})

    n_commits = len(commits)
    meta: dict[str, Any] = {
        'scope': f'{base}..HEAD ({n_commits} commit{"s" if n_commits != 1 else ""})',
        'stats': {
            'files': files,
            'added': added,
            'deleted': deleted,
        },
        'commits': commits,
        'skipped': skipped,
        'files': kept,
    }

    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    with open(diff_path, 'w') as f:
        f.write(diff)

    contents = get_file_contents(kept, before_ref=base, read_disk=False)
    with open(file_contents_path, 'w', encoding='utf-8') as f:
        json.dump(contents, f, ensure_ascii=False)

    print(f"{len(kept)} files, +{added}/-{deleted}, {n_commits} commits, {len(skipped)} skipped")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gather git diff for code review')
    parser.add_argument('mode', help='uncommitted, branch, or a base ref')
    parser.add_argument('--meta', required=True, help='output path for metadata JSON')
    parser.add_argument('--diff', required=True, help='output path for raw diff')
    args = parser.parse_args()

    file_contents_path = os.path.join(os.path.dirname(args.meta), 'file-contents.json')

    if args.mode == 'uncommitted':
        gather_uncommitted(args.meta, args.diff, file_contents_path)
    elif args.mode == 'branch':
        base = detect_default_branch()
        print(f"Base branch: {base}")
        gather_committed(base, args.meta, args.diff, file_contents_path)
    else:
        gather_committed(args.mode, args.meta, args.diff, file_contents_path)
