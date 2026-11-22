#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""code-evolution-diff — сравнение двух версий кодовой базы по содержимому.

Задача: понять, что стало с кодом между двумя состояниями проекта, когда
git-истории нет (архивы, zip-слепки, выгрузки с хостинга).

Для каждого файла целевой версии находится наиболее вероятный предок в
базовой версии и присваивается один из трёх классов:

  identical — нормализованное содержимое совпадает (с точностью до
              комментариев, пробелов и переносов строк);
  modified  — есть предок, коэффициент сходства не ниже порога;
  new       — предка выше порога не найдено.

Сопоставление идёт в три стадии: точный относительный путь, хеш содержимого
(ловит переименования и переносы между папками), нечёткое сходство
(difflib, коэффициент ≥ порога).

Пример:
    python compare.py --baseline course/ --target final/ --ext php
    python compare.py --baseline 2018/ --target 2021/ --layers app,vendor --format csv
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import io
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_THRESHOLD = 0.30
STRONG_THRESHOLD = 0.60  # совпадения такого уровня считаются переносом кода, а не случайностью

# --------------------------------------------------------------------------
# Нормализация
# --------------------------------------------------------------------------

_RE_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_RE_LINE_C = re.compile(r"(?m)^\s*(?://|#).*$")
_RE_TRAILING = re.compile(r"(?<![:\"'])\s//\s[^\n]*$")
_RE_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Убирает комментарии и схлопывает пробелы, чтобы сравнивать смысл, а не форматирование."""
    text = _RE_BLOCK.sub(" ", text)
    text = _RE_LINE_C.sub(" ", text)
    text = _RE_TRAILING.sub("", text)
    return _RE_SPACES.sub(" ", text).strip()


def count_lines(path: str) -> int:
    """Считает непустые строки файла (вес файла в отчёте)."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


# --------------------------------------------------------------------------
# Сбор файлов и сопоставление
# --------------------------------------------------------------------------


@dataclass
class FileInfo:
    rel: str
    path: str
    norm: str
    lines: int


@dataclass
class Verdict:
    rel: str
    cls: str                     # identical | modified | new
    ratio: float
    lines: int
    source: Optional[str] = None  # относительный путь предка
    group: str = ""               # слой (первый каталог или --layers)


@dataclass
class GroupResult:
    name: str
    baseline_files: int = 0
    baseline_lines: int = 0
    target_files: int = 0
    target_lines: int = 0
    counts: Dict[str, int] = field(default_factory=lambda: {"identical": 0, "modified": 0, "new": 0})
    lines: Dict[str, int] = field(default_factory=lambda: {"identical": 0, "modified": 0, "new": 0})
    verdicts: List[Verdict] = field(default_factory=list)


def collect(root: str, ext: str, layers: Optional[Iterable[str]] = None) -> Dict[str, FileInfo]:
    """Собирает файлы с расширением `ext`; при указании layers — только внутри них."""
    out: Dict[str, FileInfo] = {}
    roots: List[Tuple[str, str]] = []
    if layers:
        for layer in layers:
            full = os.path.join(root, layer)
            if os.path.isdir(full):
                roots.append((full, layer))
    else:
        roots.append((root, ""))

    for base, prefix in roots:
        for cur, dirs, files in os.walk(base):
            dirs.sort()
            for name in sorted(files):
                if not name.endswith(ext):
                    continue
                path = os.path.join(cur, name)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                out[rel] = FileInfo(rel=rel, path=path, norm=normalize(read_text(path)), lines=count_lines(path))
    return out


def group_of(rel: str, layers: Optional[Iterable[str]]) -> str:
    if layers:
        for layer in layers:
            if rel.startswith(layer.rstrip("/") + "/"):
                return layer
        return "(прочее)"
    return rel.split("/")[0] if "/" in rel else "(корень)"


def shingles(text: str, size: int = 4, step: int = 4) -> set:
    """Множество 4-грамм — дешёвый предфильтр кандидатов перед полным сравнением."""
    if len(text) < size:
        return {text}
    return {text[i:i + size] for i in range(0, len(text) - size + 1, step)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    # autojunk=False: иначе популярные символы выпадают из сравнения и сходство занижается
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < 0.25:  # быстрый отсев заведомо далёких файлов
        return sm.real_quick_ratio()
    return sm.ratio()


def compare(baseline: Dict[str, FileInfo], target: Dict[str, FileInfo], threshold: float) -> List[Verdict]:
    """Сопоставляет каждый файл целевой версии с базовой в три стадии."""
    by_hash: Dict[str, List[str]] = defaultdict(list)
    for rel, info in baseline.items():
        by_hash[hashlib.sha1(info.norm.encode("utf-8")).hexdigest()].append(rel)

    used: set = set()
    done: set = set()
    verdicts: List[Verdict] = []

    # 1) тот же путь и то же содержимое
    for rel, info in sorted(target.items()):
        base = baseline.get(rel)
        if base is not None and base.norm == info.norm:
            verdicts.append(Verdict(rel, "identical", 1.0, info.lines, rel))
            used.add(rel)
            done.add(rel)

    # 2) то же содержимое под другим именем (переименование, перенос)
    for rel, info in sorted(target.items()):
        if rel in done:
            continue
        digest = hashlib.sha1(info.norm.encode("utf-8")).hexdigest()
        candidates = sorted(c for c in by_hash.get(digest, []) if c not in used)
        if candidates:
            verdicts.append(Verdict(rel, "identical", 1.0, info.lines, candidates[0]))
            used.add(candidates[0])
            done.add(rel)

    # 3) нечёткое сходство
    # обратный индекс «шингл → файлы базы»: редкие шинглы дают кандидатов,
    # частые (общие для всего языка) отбрасываем — иначе перебор не окупается
    base_shingles = {rel: shingles(info.norm) for rel, info in baseline.items()}
    inverted: Dict[str, List[str]] = defaultdict(list)
    for rel, sh in base_shingles.items():
        for s in sh:
            inverted[s].append(rel)
    max_postings = 40

    for rel, info in sorted(target.items()):
        if rel in done:
            continue
        mine = shingles(info.norm)
        hits: Dict[str, int] = defaultdict(int)
        for s in mine:
            postings = inverted.get(s)
            if not postings or len(postings) > max_postings:
                continue
            for base_rel in postings:
                hits[base_rel] += 1
        scored = []
        for base_rel, shared in hits.items():
            if base_rel in used:
                continue
            base = baseline[base_rel]
            if len(base.norm) > 3 * max(len(info.norm), 1) or len(info.norm) > 3 * max(len(base.norm), 1):
                continue
            scored.append((shared / max(len(mine) + len(base_shingles[base_rel]) - shared, 1), base_rel))
        scored.sort(reverse=True)
        best_ratio, best_src = 0.0, None
        for _, base_rel in scored[:20]:
            ratio = similarity(info.norm, baseline[base_rel].norm)
            if ratio > best_ratio:
                best_ratio, best_src = ratio, base_rel
            if ratio > 0.995:
                break
        if best_ratio >= threshold and best_src is not None:
            verdicts.append(Verdict(rel, "modified", round(best_ratio, 4), info.lines, best_src))
            used.add(best_src)
        else:
            verdicts.append(Verdict(rel, "new", round(best_ratio, 4), info.lines, None))
        done.add(rel)

    return verdicts


def aggregate(verdicts: List[Verdict], baseline: Dict[str, FileInfo], target: Dict[str, FileInfo],
              layers: Optional[Iterable[str]]) -> Dict[str, GroupResult]:
    groups: Dict[str, GroupResult] = {}
    for rel, info in baseline.items():
        g = group_of(rel, layers)
        gr = groups.setdefault(g, GroupResult(g))
        gr.baseline_files += 1
        gr.baseline_lines += info.lines
    for rel, info in target.items():
        g = group_of(rel, layers)
        gr = groups.setdefault(g, GroupResult(g))
        gr.target_files += 1
        gr.target_lines += info.lines
    for v in verdicts:
        g = group_of(v.rel, layers)
        v.group = g
        gr = groups.setdefault(g, GroupResult(g))
        gr.counts[v.cls] += 1
        gr.lines[v.cls] += v.lines
        gr.verdicts.append(v)
    return groups


# --------------------------------------------------------------------------
# Вывод
# --------------------------------------------------------------------------


def totals(groups: Dict[str, GroupResult]) -> GroupResult:
    total = GroupResult("ИТОГО")
    for gr in groups.values():
        total.baseline_files += gr.baseline_files
        total.baseline_lines += gr.baseline_lines
        total.target_files += gr.target_files
        total.target_lines += gr.target_lines
        for cls in ("identical", "modified", "new"):
            total.counts[cls] += gr.counts[cls]
            total.lines[cls] += gr.lines[cls]
    return total


def pct(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "—"


def render_markdown(groups: Dict[str, GroupResult], threshold: float,
                    strong: float = STRONG_THRESHOLD) -> str:
    buf = io.StringIO()
    head = (f"| слой | база (файлы/строки) | цель (файлы/строки) | как есть | переработано | новое |\n"
            f"|---|---|---|---|---|---|\n")
    buf.write(head)
    for name in sorted(groups):
        gr = groups[name]
        buf.write(
            f"| {name} | {gr.baseline_files} / {gr.baseline_lines} | {gr.target_files} / {gr.target_lines} "
            f"| {gr.counts['identical']} / {gr.lines['identical']} "
            f"| {gr.counts['modified']} / {gr.lines['modified']} "
            f"| {gr.counts['new']} / {gr.lines['new']} |\n"
        )
    total = totals(groups)
    buf.write(
        f"| **ИТОГО** | {total.baseline_files} / {total.baseline_lines} | {total.target_files} / {total.target_lines} "
        f"| {total.counts['identical']} / {total.lines['identical']} "
        f"| {total.counts['modified']} / {total.lines['modified']} "
        f"| {total.counts['new']} / {total.lines['new']} |\n\n"
    )
    buf.write(f"Порог сходства: {threshold}. В строках: как есть {pct(total.lines['identical'], total.target_lines)}, "
              f"переработано {pct(total.lines['modified'], total.target_lines)}, "
              f"новое {pct(total.lines['new'], total.target_lines)}.\n")

    # Точечные переносы: агрегат по слоям их усредняет и прячет, а вопрос обычно
    # именно про них — «что из старого кода реально перешло».
    strong_hits = [(v.ratio, v.rel, v.source, v.lines)
                   for gr in groups.values() for v in gr.verdicts
                   if v.cls in ("modified", "identical") and v.ratio >= strong]
    if strong_hits:
        strong_hits.sort(reverse=True)
        buf.write(f"\nСильные совпадения (сходство ≥ {strong:.2f}) — вероятный перенос кода:\n\n")
        buf.write("| сходство | файл в цели | предок в базе | строк |\n|---|---|---|---|\n")
        for ratio, rel, src, lines in strong_hits[:20]:
            buf.write(f"| {ratio:.2f} | {rel} | {src or '—'} | {lines} |\n")
        if len(strong_hits) > 20:
            buf.write(f"\n… всего {len(strong_hits)} таких файлов.\n")
        buf.write("\n")
    return buf.getvalue()


def render_csv(groups: Dict[str, GroupResult]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["слой", "файл", "класс", "сходство", "строки", "предок"])
    for name in sorted(groups):
        for v in sorted(groups[name].verdicts, key=lambda x: (x.cls, x.rel)):
            writer.writerow([name, v.rel, v.cls, v.ratio, v.lines, v.source or ""])
    return buf.getvalue()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Сравнить две версии кодовой базы по содержимому.")
    parser.add_argument("--baseline", required=True, help="каталог базовой версии (предок)")
    parser.add_argument("--target", required=True, help="каталог целевой версии (потомок)")
    parser.add_argument("--ext", default=".php", help="расширение файлов, по умолчанию .php")
    parser.add_argument("--layers", default="", help="список слоёв через запятую; по умолчанию группировка по первому каталогу")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="порог сходства для класса modified")
    parser.add_argument("--strong", type=float, default=STRONG_THRESHOLD,
                        help="порог для блока «сильные совпадения» (по умолчанию 0.60)")
    parser.add_argument("--format", choices=["markdown", "csv"], default="markdown")
    parser.add_argument("--out", default="", help="файл для записи отчёта; по умолчанию stdout")
    args = parser.parse_args(argv)

    layers = [s.strip() for s in args.layers.split(",") if s.strip()] or None
    ext = args.ext if args.ext.startswith(".") else "." + args.ext

    if not os.path.isdir(args.baseline) or not os.path.isdir(args.target):
        parser.error("--baseline и --target должны быть существующими каталогами")

    baseline = collect(args.baseline, ext, layers)
    target = collect(args.target, ext, layers)
    if not baseline or not target:
        print("Не найдено файлов с расширением %s — проверьте пути и --layers" % ext, file=sys.stderr)
        return 2

    # --layers отсекает файлы С ОБЕИХ СТОРОН. Если у базовой версии другой набор
    # каталогов (например, «core/lib/objects» против «app»), фильтр по слоям цели
    # может оставить от базы один-два файла, и сравнение теряет смысл — оно
    # покажет «новое» почти для всего. Предупреждаем, а не молчим.
    if layers:
        base_by_layer = {g: 0 for g in layers}
        for rel in baseline:
            base_by_layer[group_of(rel, layers)] = base_by_layer.get(group_of(rel, layers), 0) + 1
        for layer, count in base_by_layer.items():
            if count == 0:
                print(
                    "Предупреждение: в базовой версии нет файлов в слое %r — "
                    "фильтр --layers применится к обеим сторонам, и это занизит совпадения. "
                    "Уберите --layers или назовите слои одинаково в обеих версиях." % layer,
                    file=sys.stderr,
                )

    verdicts = compare(baseline, target, args.threshold)
    groups = aggregate(verdicts, baseline, target, layers)
    report = (render_markdown(groups, args.threshold, args.strong)
              if args.format == "markdown" else render_csv(groups))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"Отчёт записан: {args.out}")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
