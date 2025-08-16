# eLOC Metrix (CLI)

Command-line tool to recursively enumerate files under a directory and measure:

- LOC: total lines (including blanks and comments)
- eLOC: effective lines of code (non-empty, non-comment lines)

It prints a hierarchical tree of directories/files with per-file eLOC/LOC, a summary of totals, the Top 30 files by eLOC, and the Latest Top 10 by modification time.

## Usage

- Basic:
  
  ```bash
  python eloc_metrix.py /path/to/dir
  ```

- With a custom exclude list:
  
  ```bash
  python eloc_metrix.py /path/to/dir --exclude-file my_excludes.txt
  ```

If `--exclude-file` is not provided, the tool looks for `exclude_extensions.txt` in the current directory.

## Excluding files by extension

Edit `exclude_extensions.txt` to list file extensions to skip (one per line). Lines beginning with `#` are comments. Extensions can start with `.` or not; they are case-insensitive.

The provided `exclude_extensions.txt` is pre-populated with commonly excluded, non-source assets (images, archives, binaries, office docs, etc.), plus general text documents like `.md`.

## What counts as eLOC?

- eLOC counts lines with code after removing block comments on that line and ignoring lines where the first non-whitespace token is a line-comment.
- Inline end-of-line comments after code still count as code lines.
- Block comments spanning multiple lines are ignored entirely.
- Heuristics for common languages are supported:
  - C-like (`.c/.cpp/.h/.hpp/.java/.js/.ts/.go/.rs/.cs/.swift/.kt/.scala/.dart/.css`): `//`, `/* */`
  - Python/Shell/Ruby/YAML/TOML/etc.: `#`
  - PHP: `//`, `#`, `/* */`
  - SQL: `--`, `/* */`
  - HTML/XML: `<!-- -->`
  - Lua: `--`, `--[[ ]]--`

Unknown extensions have no comment syntax; eLOC counts non-empty lines.

Note: The parser is heuristic and does not fully parse string literals; in rare cases comment markers inside strings may affect counts.

## Example output

```
my-project/
  eloc_metrix.py  eLOC: 180  LOC: 260
  src/
    main.py  eLOC: 120  LOC: 170
    utils.js  eLOC: 90  LOC: 140

 Summary
 - Files counted: 3
 - Total eLOC:   390
 - Total LOC:    570
 
 Top 30 by eLOC
  1. src/main.py  eLOC: 120  LOC: 170
  2. src/utils.js  eLOC: 90  LOC: 140
  3. eloc_metrix.py  eLOC: 180  LOC: 260

 Latest Top 10
  1. src/utils.js  eLOC: 90  LOC: 140  Updated: 2025-01-01 12:34:56
  2. src/main.py   eLOC: 120 LOC: 170  Updated: 2025-01-01 12:00:00
```

## Tips

- Large non-code directories like `node_modules/`, build outputs, and caches are skipped automatically.
- To include or exclude more file types, edit `exclude_extensions.txt`.
