import io
import os
from pathlib import Path
import tempfile
import contextlib
import unittest
import sys

# Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eloc_metrix as em


class TestElocMetrix(unittest.TestCase):
    def test_load_excluded_extensions(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ex.txt"
            p.write_text("""
            # comment
            md
            .log

            # mixed case
            JPG
            """.strip(), encoding="utf-8")

            exts = em.load_excluded_extensions(p)
            self.assertEqual(exts, {".md", ".log", ".jpg"})

    def test_count_python_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "sample.py"
            content = (
                "# a comment line\n"
                "\n"
                "x = 1\n"
                "x = 2  # inline comment\n"
                "\n"
                "# another comment"
            )
            f.write_text(content, encoding="utf-8")

            eloc, loc = em.count_loc_eloc_for_file(f)
            # LOC: all lines
            self.assertEqual(loc, 6)
            # eLOC: two lines with code
            self.assertEqual(eloc, 2)

    def test_count_c_like_block_comments(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "code.js"
            content = (
                "/* header block\n"
                "still comment */\n"
                "\n"
                "// line comment\n"
                "const a = 1; // trailing ok\n"
                "/* block start */ const b = 2; /* midline block end */\n"
                "const c = 3; /* trailing block start\n"
                "multi line\n"
                "end */ const d = 4;"
            )
            f.write_text(content, encoding="utf-8")

            eloc, loc = em.count_loc_eloc_for_file(f)
            # Count lines: 9 logical lines in the text above
            self.assertEqual(loc, 9)
            # eLOC: code lines are: a, b, c, d => 4
            self.assertEqual(eloc, 4)

    def test_count_html_block_comments(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "page.html"
            f.write_text("<!-- header comment -->\n<div>hi</div>", encoding="utf-8")
            eloc, loc = em.count_loc_eloc_for_file(f)
            self.assertEqual(loc, 2)
            self.assertEqual(eloc, 1)

    def test_unknown_extension_counts_non_empty(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "data.foo"
            f.write_text("a\n\n# not a comment here", encoding="utf-8")
            eloc, loc = em.count_loc_eloc_for_file(f)
            # 3 lines total
            self.assertEqual(loc, 3)
            # Non-empty lines = 2 ("a" and "# not a comment here")
            self.assertEqual(eloc, 2)

    def test_walk_and_count_with_excludes_and_skips(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Create directories
            (root / "src").mkdir()
            (root / "node_modules").mkdir()
            (root / ".git").mkdir()

            # Files to be counted
            py = root / "src" / "m.py"
            py.write_text("x = 1\n# c\n\n", encoding="utf-8")  # loc=3, eloc=1

            js = root / "src" / "a.js"
            js.write_text("// c\nconst a=1;\n", encoding="utf-8")  # loc=2, eloc=1

            # Excluded by extension
            md = root / "src" / "README.md"
            md.write_text("# title\n\ntext\n", encoding="utf-8")

            # Skipped directories (should not be scanned)
            (root / "node_modules" / "pkg.js").write_text("const x=1;\n", encoding="utf-8")
            (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

            # Exclude set
            excluded = {".md"}

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                files, eloc, loc, results = em.walk_and_count(root, excluded)

            # Only m.py and a.js should be counted
            self.assertEqual(files, 2)
            self.assertEqual(eloc, 2)  # 1 from py + 1 from js
            self.assertEqual(loc, 5)   # 3 from py + 2 from js
            # results contains exactly the two files
            paths = {p.name for (p, _, _) in results}
            self.assertEqual(paths, {"m.py", "a.js"})

    def test_latest_top10_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()

            f1 = root / "src" / "older.py"
            f1.write_text("x=1\n", encoding="utf-8")
            f2 = root / "src" / "newer.py"
            f2.write_text("x=2\n", encoding="utf-8")
            f3 = root / "src" / "middle.py"
            f3.write_text("x=3\n", encoding="utf-8")

            # Set mtimes explicitly
            import time
            now = time.time()
            os.utime(f1, (now - 300, now - 300))  # oldest
            os.utime(f3, (now - 200, now - 200))
            os.utime(f2, (now - 100, now - 100))  # newest

            # Run the CLI main with no exclude file
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = em.main([str(root)])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            # Ensure header present and the first listed file is the newest
            self.assertIn("Latest Top 10", out)
            # Find the line after the header
            lines = out.splitlines()
            try:
                idx = lines.index("Latest Top 10")
            except ValueError:
                idx = -1
            self.assertGreaterEqual(idx, 0)
            # The first entry line should contain newer.py
            if idx >= 0 and idx + 1 < len(lines):
                first_entry = lines[idx + 1]
                self.assertIn("newer.py", first_entry)

    def test_language_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            # Create files: JS should have more eLOC than Python; Unknown should be last
            # JavaScript total eLOC: 3 (two files: 2 + 1)
            (root / "src" / "b1.js").write_text("const a=1;\nconst b=2;\n", encoding="utf-8")
            (root / "src" / "b2.js").write_text("const c=3;\n", encoding="utf-8")
            # Python total eLOC: 2 (two files: 1 + 1)
            (root / "src" / "a1.py").write_text("x=1\n", encoding="utf-8")
            (root / "src" / "a2.py").write_text("y=2\n", encoding="utf-8")
            # Unknown with larger eLOC but should be printed last in summary
            (root / "src" / "u.unknown").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = em.main([str(root)])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("Languages Summary", out)
            # Expect Python and JavaScript entries with files>=1
            self.assertRegex(out, r"- Python: .*files=2\b")
            self.assertRegex(out, r"- JavaScript: .*files=2\b")
            # Unknown should be last in the summary order
            lines = out.splitlines()
            idx_langs = lines.index("Languages Summary")
            # capture the next few lines until a blank or next header
            block = []
            for line in lines[idx_langs + 1:]:
                if not line.strip():
                    break
                if line.startswith("Top 10 in"):
                    break
                if line.startswith("-"):
                    block.append(line)
                else:
                    break
            joined = "\n".join(block)
            # Ensure Unknown appears in block and is the last bullet line
            unknown_lines = [i for i, l in enumerate(block) if l.startswith("- Unknown:")]
            self.assertTrue(unknown_lines, "Unknown summary line missing")
            self.assertEqual(unknown_lines[-1], len(block) - 1)

            # Verify Top 20 sections for the top non-Unknown languages exist
            self.assertIn("Top 20 in JavaScript", out)
            self.assertIn("Top 20 in Python", out)


if __name__ == "__main__":
    unittest.main()
