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


def language_for_extension(ext: str) -> str:
    """Map a file extension to a human-readable language name.

    Unknown extensions map to 'Unknown'.
    """
    ext = ext.lower()
    mapping = {
        # Python and shells
        '.py': 'Python', '.pyw': 'Python',
        '.sh': 'Shell', '.bash': 'Shell', '.zsh': 'Shell',
        '.ps1': 'PowerShell', '.psm1': 'PowerShell', '.psd1': 'PowerShell',

        # C-family
        '.c': 'C', '.h': 'C Header',
        '.cpp': 'C++', '.cc': 'C++', '.cxx': 'C++',
        '.hpp': 'C++ Header', '.hh': 'C++ Header', '.hxx': 'C++ Header',
        '.cs': 'C#',

        # Web / JS
        '.js': 'JavaScript', '.mjs': 'JavaScript',
        '.ts': 'TypeScript', '.tsx': 'TypeScript (TSX)',
        '.jsx': 'JavaScript (JSX)',
        '.css': 'CSS', '.scss': 'SCSS', '.sass': 'Sass', '.less': 'Less',
        '.html': 'HTML', '.htm': 'HTML', '.xml': 'XML',

        # Others
        '.java': 'Java', '.go': 'Go', '.rs': 'Rust', '.swift': 'Swift',
        '.kt': 'Kotlin', '.kts': 'Kotlin Script', '.scala': 'Scala', '.rb': 'Ruby',
        '.php': 'PHP', '.lua': 'Lua', '.dart': 'Dart', '.sql': 'SQL',

        # Config / data-like (still counted)
        '.yml': 'YAML', '.yaml': 'YAML', '.toml': 'TOML', '.ini': 'INI',
        '.cfg': 'Config', '.conf': 'Config', '.env': 'Config',
        '.mak': 'Makefile', '.mk': 'Makefile',
    }
    return mapping.get(ext, 'Unknown')


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
    lang_totals: Dict[str, List[int]] = {}  # lang -> [files, eloc_sum, loc_sum]
    lang_files: Dict[str, List[Tuple[Path, int, int]]] = {}

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

            # Accumulate language totals
            lang = language_for_extension(ext)
            agg = lang_totals.setdefault(lang, [0, 0, 0])
            agg[0] += 1
            agg[1] += eloc
            agg[2] += loc
            lang_files.setdefault(lang, []).append((fpath, eloc, loc))

    # Attach language totals on the function for later printing (simple approach)
    walk_and_count.lang_totals = lang_totals  # type: ignore[attr-defined]
    walk_and_count.lang_files = lang_files    # type: ignore[attr-defined]
    return total_files, total_eloc, total_loc, results


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Measure eLOC and LOC per file under a directory.")
    p.add_argument("path", nargs="?", default=".", help="Target directory (default: current directory)")
    p.add_argument(
        "--exclude-file",
        default="exclude_extensions.txt",
        help="Path to a text file listing file extensions to exclude (default: exclude_extensions.txt)",
    )
    p.add_argument(
        "--top-eloc",
        type=int,
        default=30,
        help="How many files to show in the Top by eLOC section (default: 30)",
    )
    p.add_argument(
        "--latest",
        type=int,
        default=10,
        help="How many files to show in the Latest section (default: 10)",
    )
    p.add_argument(
        "--top-lang",
        type=int,
        default=5,
        help="How many non-Unknown languages to expand with per-file rankings (default: 5)",
    )
    p.add_argument(
        "--top-files-per-lang",
        type=int,
        default=20,
        help="How many files to show per language in per-language rankings (default: 20)",
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

    # Top files by eLOC
    if results:
        print()
        print(f"Top {args.top_eloc} by eLOC")
        # Sort by eLOC desc, then LOC desc, then path for stability
        top = sorted(results, key=lambda t: (-t[1], -t[2], str(t[0]).lower()))[: args.top_eloc]
        for idx, (fpath, feloc, floc) in enumerate(top, 1):
            try:
                rel = fpath.resolve().relative_to(root.resolve())
                rel_str = str(rel)
            except Exception:
                rel_str = str(fpath)
            print(f"{idx:2d}. {rel_str}  eLOC: {feloc}  LOC: {floc}")

        # Latest by modification time
        print()
        print(f"Latest Top {args.latest}")
        with_times: List[Tuple[Path, int, int, float]] = []
        for fpath, feloc, floc in results:
            try:
                mtime = fpath.stat().st_mtime
            except OSError:
                mtime = 0.0
            with_times.append((fpath, feloc, floc, mtime))
        latest = sorted(with_times, key=lambda t: (-t[3], str(t[0]).lower()))[: args.latest]
        for idx, (fpath, feloc, floc, mtime) in enumerate(latest, 1):
            try:
                rel = fpath.resolve().relative_to(root.resolve())
                rel_str = str(rel)
            except Exception:
                rel_str = str(fpath)
            ts = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S') if mtime else 'N/A'
            print(f"{idx:2d}. {rel_str}  eLOC: {feloc}  LOC: {floc}  Updated: {ts}")

        # Language summary
        lang_totals = getattr(walk_and_count, 'lang_totals', {})  # type: ignore[attr-defined]
        if lang_totals:
            print()
            print("Languages Summary")
            # Sort by: Unknown last, then eLOC desc, LOC desc, name asc
            ordered = sorted(
                ((lang, vals[0], vals[1], vals[2]) for lang, vals in lang_totals.items()),
                key=lambda t: (1 if t[0] == 'Unknown' else 0, -t[2], -t[3], t[0].lower()),
            )
            for lang, fcount, lel, llc in ordered:
                print(f"- {lang}: files={fcount}  eLOC={lel}  LOC={llc}")

            # Per-language Top N for the top M non-Unknown languages by eLOC
            non_unknown = [t for t in ordered if t[0] != 'Unknown']
            top_langs = [t[0] for t in non_unknown[: args.top_lang]]
            if top_langs:
                lang_files = getattr(walk_and_count, 'lang_files', {})  # type: ignore[attr-defined]
                for lang in top_langs:
                    print()
                    print(f"Top {args.top_files_per_lang} in {lang}")
                    files_in_lang = lang_files.get(lang, [])
                    top_lang = sorted(files_in_lang, key=lambda t: (-t[1], -t[2], str(t[0]).lower()))[: args.top_files_per_lang]
                    for idx, (fpath, feloc, floc) in enumerate(top_lang, 1):
                        try:
                            rel = fpath.resolve().relative_to(root.resolve())
                            rel_str = str(rel)
                        except Exception:
                            rel_str = str(fpath)
                        print(f"{idx:2d}. {rel_str}  eLOC: {feloc}  LOC: {floc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
