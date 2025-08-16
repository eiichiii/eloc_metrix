# Changelog (session summary)

All notable changes in this session are recorded here.

## Unreleased

- Add CLI tool `eloc_metrix.py` to recursively measure eLOC/LOC with hierarchical output.
- Add `exclude_extensions.txt` pre-populated with common non-code extensions.
- Add `README.md` with usage, heuristics, and examples.
- Add unit tests `tests/test_eloc_metrix.py` covering counting rules, excludes, directory skips, latest list, and language summary.
- Add CI via GitHub Actions `.github/workflows/ci.yml` running `unittest` on Python 3.9–3.12.
- Fix test discovery reliability by adding `tests/__init__.py`.
- Add packaging files: `pyproject.toml` (with console script `eloc-metrix`) and `requirements.txt` (no runtime deps).
- Enhance output: Top by eLOC (configurable), Latest by mtime, Languages summary.
- Sort Languages summary by eLOC desc with `Unknown` always last.
- Add per-language rankings for the top non-Unknown languages; initially Top 10 for top two languages, later extended to Top 20 for top five.
- Add CLI flags:
  - `--top-eloc N` to control count in “Top by eLOC” (default 30)
  - `--latest M` to control count in “Latest” (default 10)
  - `--top-lang L` to control how many languages to expand (default 5)
  - `--top-files-per-lang K` to control files per language (default 20)

