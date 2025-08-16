#!/usr/bin/env python3
"""
eLOC/LOC counter for a directory tree.

- LOC: total lines in a file (including blanks and comments)
- eLOC: effective lines of code, counting non-empty, non-comment lines

The program walks a directory, prints a hierarchical listing with per-file
eLOC/LOC, and shows totals at the end. File extensions to exclude can be
provided via a plain text file (one extension per line, comments with '#').
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from datetime import datetime


def load_excluded_extensions(file_path: Path) -> Set[str]:
    """Load excluded file extensions from a text file.

    - Ignores blank lines.
    - Lines starting with '#' are treated as comments.
    - Extensions may start with '.' or not; stored lowercase with leading '.'.
    """
    exts: Set[str] = set()
    if not file_path:
        return exts
    try:
        with file_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if not line.startswith('.'):
                    line = '.' + line
                exts.add(line.lower())
    except FileNotFoundError:
        # Silently ignore; caller may create a default one.
        pass
    return exts


def comment_syntax_for_extension(ext: str) -> Tuple[Set[str], List[Tuple[str, str]]]:
    """Return (line_comment_prefixes, block_comment_pairs) for a file extension.

    This is a heuristic for common languages; unknown extensions return empty sets.
    """
    ext = ext.lower()

    # Common C-like languages
    c_like = {
        '.c', '.h', '.cpp', '.cxx', '.cc', '.hpp', '.hh', '.hxx',
        '.java', '.js', '.ts', '.tsx', '.jsx', '.cs', '.go', '.swift', '.kt', '.kts', '.scala', '.rs', '.dart', '.css'
    }
    if ext in c_like:
        return {"//"}, [("/*", "*/")]

    # Python, Shell, Ruby, Make, YAML/TOML, Dockerfile, etc.
    hash_line = {'.py', '.sh', '.bash', '.zsh', '.rb', '.rake', '.ps1', '.psm1', '.psd1',
                 '.toml', '.ini', '.cfg', '.conf', '.yml', '.yaml', '.env', '.mak', '.mk'}
    if ext in hash_line:
        return {"#"}, []

    # PHP supports //, #, and /* */
    if ext in {'.php', '.phtml'}:
        return {"//", "#"}, [("/*", "*/")]

    # SQL supports -- line and /* */ block
    if ext in {'.sql'}:
        return {"--"}, [("/*", "*/")]

    # HTML/XML style
    if ext in {'.html', '.htm', '.xml', '.xhtml'}:
        return set(), [("<!--", "-->")]

    # Lua uses -- and --[[ ... ]]
    if ext in {'.lua'}:
        return {"--"}, [("--[[", "]]--")]

    # Ruby already handled with '#', but ERB has HTML style too; we keep simple.

    # For unknown extensions, no comment syntax
    return set(), []


def count_loc_eloc_for_file(path: Path) -> Tuple[int, int]:
    """Return (eLOC, LOC) for a given file path.

    Heuristics:
    - LOC: line count (splitlines) including blanks and comments.
    - eLOC: counts lines that contain any non-whitespace character after removing
      block comments for the line, and where the first non-whitespace token is not a
      line-comment prefix.
    - Inline line comments after code do not affect counting (still counted as code).
    - Block comments spanning multiple lines are ignored entirely.
    - Does not attempt to parse string literals; comment markers inside strings may
      produce rare false negatives/positives.
    """
    ext = path.suffix.lower()
    line_prefixes, block_pairs = comment_syntax_for_extension(ext)

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
    except (UnicodeDecodeError, OSError):
        return 0, 0

    loc = len(lines)
    eloc = 0

    in_block = False
    current_end: Optional[str] = None

    for raw in lines:
        s = raw

        # Remove block comments from the line, maintaining state across lines
        i = 0
        out_chunks: List[str] = []
        while i < len(s):
            if in_block:
                assert current_end is not None
                end_idx = s.find(current_end, i)
                if end_idx == -1:
                    # Entire rest of the line is inside a block comment
                    i = len(s)
                    break
                else:
                    # Skip comment portion and continue scanning
                    i = end_idx + len(current_end)
                    in_block = False
                    current_end = None
                    continue
            else:
                # Not in a block; find next block start among all pairs
                next_starts: List[Tuple[int, Tuple[str, str]]] = []
                for start, end in block_pairs:
                    idx = s.find(start, i)
                    if idx != -1:
                        next_starts.append((idx, (start, end)))
                if not next_starts:
                    out_chunks.append(s[i:])
                    break
                # Choose earliest start
                next_starts.sort(key=lambda t: t[0])
                idx, (start_tok, end_tok) = next_starts[0]
                # Add code before the block comment
                out_chunks.append(s[i:idx])
                # Enter block comment
                in_block = True
                current_end = end_tok
                i = idx + len(start_tok)
                # If the block closes later on the same line, continue loop will handle it

        # After processing block comments, check if there is effective code on the line
        processed = "".join(out_chunks)
        stripped = processed.strip()
        if not stripped:
            continue  # blank or only comments
        # If the first non-space token starts with a line-comment prefix, it's a comment line
        if line_prefixes:
            lstripped = processed.lstrip()
            for lp in sorted(line_prefixes, key=len, reverse=True):
                if lstripped.startswith(lp):
                    # Entire line (after whitespace) is a comment
                    break
            else:
                # No line comment at start; count as effective code
                eloc += 1
        else:
            # No concept of line comment; any non-empty line after block stripping counts
            eloc += 1

    return eloc, loc


def walk_and_count(root: Path, excluded_exts: Set[str]) -> Tuple[int, int, int, List[Tuple[Path, int, int]]]:
    """Walk directory `root`, print a hierarchical tree with per-file counts.

    Returns a tuple (files_counted, total_eloc, total_loc).
    """
    total_eloc = 0
    total_loc = 0
    total_files = 0
    results: List[Tuple[Path, int, int]] = []  # (path, eloc, loc)

    # Common directories to skip regardless of extension
    skip_dirs = {'.git', '.hg', '.svn', '.idea', '.vscode', '__pycache__',
                 'node_modules', 'dist', 'build', 'out', '.tox', '.mypy_cache', '.pytest_cache', '.venv', 'venv'}

    root = root.resolve()

    def depth_of(path: Path) -> int:
        try:
            rel = path.relative_to(root)
            if str(rel) == '.':
                return 0
            return len(rel.parts)
        except Exception:
            return 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # Prune directories
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        dpath = Path(dirpath)
        depth = depth_of(dpath)
        indent = "  " * depth
        # Print the directory header
        label = dpath.name if dpath != root else dpath.name
        print(f"{indent}{label}/")

        # Sort files for stable output
        for fname in sorted(filenames):
            fpath = dpath / fname
            ext = fpath.suffix.lower()
            if ext in excluded_exts:
                continue

            eloc, loc = count_loc_eloc_for_file(fpath)
            # Skip files with zero lines (or unreadable) to reduce noise
            if loc == 0:
                continue

            total_eloc += eloc
            total_loc += loc
            total_files += 1
            results.append((fpath, eloc, loc))

            print(f"{indent}  {fname}  eLOC: {eloc}  LOC: {loc}")

    return total_files, total_eloc, total_loc, results


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Measure eLOC and LOC per file under a directory.")
    p.add_argument("path", nargs="?", default=".", help="Target directory (default: current directory)")
    p.add_argument(
        "--exclude-file",
        default="exclude_extensions.txt",
        help="Path to a text file listing file extensions to exclude (default: exclude_extensions.txt)",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.path)
    if not root.exists() or not root.is_dir():
        print(f"Error: '{root}' is not a directory")
        return 2

    exclude_file = Path(args.exclude_file) if args.exclude_file else None
    excluded_exts = load_excluded_extensions(exclude_file) if exclude_file else set()

    if exclude_file and not exclude_file.exists():
        # Friendly hint if the default file isn't present
        print(f"Note: exclude file '{exclude_file}' not found; counting all extensions.")

    files, eloc, loc, results = walk_and_count(root, excluded_exts)

    print()
    print("Summary")
    print(f"- Files counted: {files}")
    print(f"- Total eLOC:   {eloc}")
    print(f"- Total LOC:    {loc}")

    # Top 30 files by eLOC
    if results:
        print()
        print("Top 30 by eLOC")
        # Sort by eLOC desc, then LOC desc, then path for stability
        top = sorted(results, key=lambda t: (-t[1], -t[2], str(t[0]).lower()))[:30]
        for idx, (fpath, feloc, floc) in enumerate(top, 1):
            try:
                rel = fpath.resolve().relative_to(root.resolve())
                rel_str = str(rel)
            except Exception:
                rel_str = str(fpath)
            print(f"{idx:2d}. {rel_str}  eLOC: {feloc}  LOC: {floc}")

        # Latest Top 10 by modification time
        print()
        print("Latest Top 10")
        with_times: List[Tuple[Path, int, int, float]] = []
        for fpath, feloc, floc in results:
            try:
                mtime = fpath.stat().st_mtime
            except OSError:
                mtime = 0.0
            with_times.append((fpath, feloc, floc, mtime))
        latest = sorted(with_times, key=lambda t: (-t[3], str(t[0]).lower()))[:10]
        for idx, (fpath, feloc, floc, mtime) in enumerate(latest, 1):
            try:
                rel = fpath.resolve().relative_to(root.resolve())
                rel_str = str(rel)
            except Exception:
                rel_str = str(fpath)
            ts = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S') if mtime else 'N/A'
            print(f"{idx:2d}. {rel_str}  eLOC: {feloc}  LOC: {floc}  Updated: {ts}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
