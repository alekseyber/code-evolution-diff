#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты code-evolution-diff на синтетических данных.

Фикстуры создаются во временном каталоге с заранее известным ответом:
compare() должен дать ровно те классы, которые заложены в тест.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compare  # noqa: E402

KEEP = """<?php
class Keep {
    public function a() { return 1; }
}
"""

# тот же файл, но переименован и лежит в другой папке — должен пойматься по хешу
MOVED = KEEP

# изменённая версия: одна строка другая из многих — должен быть modified
MOD_BASE = """<?php
class Cart {
    public function add($id) { return $id + 1; }
    public function remove($id) { return $id - 1; }
    public function total() { return 0; }
    public function clear() { return true; }
    public function count() { return 0; }
}
"""

MOD_TARGET = MOD_BASE.replace("public function total() { return 0; }", "public function total() { return 100; }")

# совершенно другой файл — должен быть new
NEW_FILE = """<?php
namespace App\Widgets;
final class Slider {
    public function render(array $items): string {
        $out = '';
        foreach ($items as $item) { $out .= "<div>{$item}</div>"; }
        return $out;
    }
}
"""


def write(root: str, rel: str, content: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


class NormalizeTest(unittest.TestCase):
    def test_comments_and_whitespace_removed(self):
        a = "<?php\n// комментарий\n$a = 1;   /* блок */\n\n$b = 2;\n"
        b = "<?php $a = 1; $b = 2;"
        self.assertEqual(compare.normalize(a), compare.normalize(b))

    def test_line_count_ignores_blank_lines(self):
        with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False, encoding="utf-8") as fh:
            fh.write("<?php\n\n$a = 1;\n\n$b = 2;\n")
            path = fh.name
        try:
            self.assertEqual(compare.count_lines(path), 3)
        finally:
            os.unlink(path)


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "base")
        self.target = os.path.join(self.tmp.name, "target")

        # базовая версия
        write(self.base, "app/keep.php", KEEP)
        write(self.base, "app/cart.php", MOD_BASE)
        write(self.base, "lib/moved.php", MOVED)

        # целевая версия
        write(self.target, "app/keep.php", KEEP)              # identical по пути
        write(self.target, "app/cart.php", MOD_TARGET)         # modified
        write(self.target, "app/moved.php", MOVED)             # identical по хешу (перенос)
        write(self.target, "app/slider.php", NEW_FILE)         # new

        self.base_files = compare.collect(self.base, ".php")
        self.target_files = compare.collect(self.target, ".php")
        self.verdicts = compare.compare(self.base_files, self.target_files, 0.30)

    def tearDown(self):
        self.tmp.cleanup()

    def by_rel(self):
        return {v.rel: v for v in self.verdicts}

    def test_classes(self):
        v = self.by_rel()
        self.assertEqual(v["app/keep.php"].cls, "identical")
        self.assertEqual(v["app/moved.php"].cls, "identical")   # переименование ловится хешем
        self.assertEqual(v["app/cart.php"].cls, "modified")
        self.assertEqual(v["app/slider.php"].cls, "new")

    def test_modified_keeps_ancestor(self):
        v = self.by_rel()
        self.assertEqual(v["app/cart.php"].source, "app/cart.php")
        self.assertGreater(v["app/cart.php"].ratio, 0.8)
        self.assertEqual(v["app/moved.php"].source, "lib/moved.php")

    def test_threshold_changes_classification(self):
        strict = compare.compare(self.base_files, self.target_files, 0.999)
        classes = {v.rel: v.cls for v in strict}
        self.assertEqual(classes["app/cart.php"], "new")   # при пороге 0,999 переработка = новое

    def test_aggregate_totals(self):
        groups = compare.aggregate(self.verdicts, self.base_files, self.target_files, None)
        total = compare.totals(groups)
        self.assertEqual(total.target_files, 4)
        self.assertEqual(total.counts["identical"], 2)
        self.assertEqual(total.counts["modified"], 1)
        self.assertEqual(total.counts["new"], 1)
        self.assertEqual(total.lines["new"], self.by_rel()["app/slider.php"].lines)

    def test_markdown_report_has_row_per_layer(self):
        groups = compare.aggregate(self.verdicts, self.base_files, self.target_files, None)
        report = compare.render_markdown(groups, 0.30)
        self.assertIn("| app |", report)
        self.assertIn("**ИТОГО**", report)


class CliTest(unittest.TestCase):
    def test_cli_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "b")
            target = os.path.join(tmp, "t")
            write(base, "app/keep.php", KEEP)
            write(base, "app/cart.php", MOD_BASE)
            write(target, "app/keep.php", KEEP)
            write(target, "app/cart.php", MOD_TARGET)
            write(target, "app/slider.php", NEW_FILE)

            script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "compare.py")
            out = subprocess.run(
                [sys.executable, script, "--baseline", base, "--target", target],
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn("ИТОГО", out)
            self.assertIn("новое", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
