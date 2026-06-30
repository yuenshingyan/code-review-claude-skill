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

import sys
import subprocess
import json
import argparse
import os

SKIP_FILENAMES = {
    'Cargo.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'Gemfile.lock', 'poetry.lock', 'composer.lock', 'go.sum',
    'flake.lock', 'Pipfile.lock',
}

SKIP_DIRS = {'vendor/', 'third_party/', 'node_modules/', '.git/'}

SKIP_EXTENSIONS = {
    '.pb.go', '.pb.rs', '_pb2.py', '.pb.h', '.pb.cc',
    '.generated.ts', '.generated.js',
    '.min.js', '.min.css',
}


def run(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def should_skip(filepath):
    basename = os.path.basename(filepath)
    if basename in SKIP_FILENAMES:
        return "lock file"
    for d in SKIP_DIRS:
        if filepath.startswith(d) or f'/{d}' in filepath:
            return f"vendored ({d.rstrip('/')})"
    for ext in SKIP_EXTENSIONS:
        if filepath.endswith(ext):
            return "generated code"
    return None


def detect_default_branch():
    result = subprocess.run(
        ['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip().replace('refs/remotes/origin/', '')
    for candidate in ['main', 'master']:
        check = subprocess.run(
            ['git', 'rev-parse', '--verify', candidate],
            capture_output=True, text=True
        )
        if check.returncode == 0:
            return candidate
    return 'main'


def parse_shortstat(text):
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


def parse_stat_files(text):
    """Extract file paths from git diff --stat output."""
    files = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith(' '):
            continue
        # Last line is the summary "N files changed, ..."
        if 'changed' in line and ('insertion' in line or 'deletion' in line):
            continue
        # Format: "path/to/file | N ++--" or "path/to/file (new)" etc.
        # Also handles renames: "old => new"
        parts = line.split('|')
        if len(parts) >= 2:
            path = parts[0].strip()
            # Handle renames: "src/{old => new}/file.rs"
            if '=>' in path:
                # Extract the new path
                path = path.replace('{', '').replace('}', '')
                parts2 = path.split('=>')
                if len(parts2) == 2:
                    path = parts2[1].strip()
            files.append(path)
    return files


def parse_log(text):
    commits = []
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


def build_excludes(skipped_files):
    """Build git pathspec excludes for skipped files."""
    excludes = []
    for filepath in skipped_files:
        excludes.append(f':!{filepath}')
    return excludes


def get_file_contents(kept_files, before_ref, read_disk=False):
    contents = []
    for filepath in kept_files:
        before_result = subprocess.run(
            ['git', 'show', f'{before_ref}:{filepath}'],
            capture_output=True, text=True, errors='replace'
        )
        before_lines = before_result.stdout.splitlines() if before_result.returncode == 0 else []

        if read_disk:
            try:
                with open(filepath, encoding='utf-8', errors='replace') as f:
                    after_lines = f.read().splitlines()
            except FileNotFoundError:
                after_lines = []
        else:
            after_result = subprocess.run(
                ['git', 'show', f'HEAD:{filepath}'],
                capture_output=True, text=True, errors='replace'
            )
            after_lines = after_result.stdout.splitlines() if after_result.returncode == 0 else []

        contents.append({'file': filepath, 'before_lines': before_lines, 'after_lines': after_lines})
    return contents


def gather_uncommitted(meta_path, diff_path, file_contents_path):
    # Get file list from both staged and unstaged
    stat_unstaged = run(['git', 'diff', '--stat'])
    stat_staged = run(['git', 'diff', '--cached', '--stat'])

    all_files = set(parse_stat_files(stat_unstaged) + parse_stat_files(stat_staged))

    # Classify skipped
    skipped = []
    kept = []
    for f in sorted(all_files):
        reason = should_skip(f)
        if reason:
            skipped.append({'file': f, 'reason': reason})
        else:
            kept.append(f)

    excludes = build_excludes([s['file'] for s in skipped])

    # Get stats (after filtering)
    shortstat_args = ['git', 'diff', '--shortstat'] + (['--'] + excludes if excludes else [])
    shortstat_cached_args = ['git', 'diff', '--cached', '--shortstat'] + (['--'] + excludes if excludes else [])
    ss1 = run(shortstat_args)
    ss2 = run(shortstat_cached_args)
    f1, a1, d1 = parse_shortstat(ss1) if ss1.strip() else (0, 0, 0)
    f2, a2, d2 = parse_shortstat(ss2) if ss2.strip() else (0, 0, 0)

    # Get filtered diffs
    diff_args_base = ['--'] + excludes if excludes else []
    diff1 = run(['git', 'diff'] + diff_args_base)
    diff2 = run(['git', 'diff', '--cached'] + diff_args_base)
    combined_diff = diff1 + diff2

    # Check for binary files in the diff
    for line in combined_diff.splitlines():
        if line.startswith('Binary files'):
            # Extract filename
            parts = line.split(' and ')
            if len(parts) >= 2:
                bfile = parts[1].replace(' differ', '').strip()
                if bfile.startswith('b/'):
                    bfile = bfile[2:]
                if bfile not in [s['file'] for s in skipped]:
                    skipped.append({'file': bfile, 'reason': 'binary file'})

    meta = {
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
    with open(file_contents_path, 'w') as f:
        json.dump(contents, f, ensure_ascii=False)

    print(f"{len(kept)} files, +{meta['stats']['added']}/-{meta['stats']['deleted']}, {len(skipped)} skipped")


def gather_committed(base, meta_path, diff_path, file_contents_path):
    # Verify base ref exists
    check = subprocess.run(['git', 'rev-parse', '--verify', base], capture_output=True, text=True)
    if check.returncode != 0:
        print(f"ERROR: ref '{base}' not found", file=sys.stderr)
        sys.exit(1)

    # Get file list
    stat = run(['git', 'diff', f'{base}...HEAD', '--stat', '-M'])
    all_files = parse_stat_files(stat)

    skipped = []
    kept = []
    for f in sorted(set(all_files)):
        reason = should_skip(f)
        if reason:
            skipped.append({'file': f, 'reason': reason})
        else:
            kept.append(f)

    excludes = build_excludes([s['file'] for s in skipped])

    # Stats
    shortstat_args = ['git', 'diff', f'{base}...HEAD', '--shortstat'] + (['--'] + excludes if excludes else [])
    ss = run(shortstat_args)
    files, added, deleted = parse_shortstat(ss) if ss.strip() else (0, 0, 0)

    # Commits
    log_out = run(['git', 'log', f'{base}..HEAD', '--oneline',
                   '--format=%h %s|%an|%ad', '--date=short'])
    commits = parse_log(log_out)

    # Filtered diff
    diff_args = ['git', 'diff', f'{base}...HEAD', '-M'] + (['--'] + excludes if excludes else [])
    diff = run(diff_args)

    # Check binary
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
    meta = {
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
    with open(file_contents_path, 'w') as f:
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
