"""Критерии успеха и разбор итога (по Фридману): строки под пунктом, как ссылки.

    Критерий: [x] написали ≥ 90 % детей → 94 %
    Критерий: [-] средний балл ≥ 15 → 13,4
    Критерий: [ ] разбор с учителями до 27.11
    Разбор: провал
    Причина: пробник поставили на неделю олимпиад
    Меняем: пробники только по графику ВСОКО

Отметка как у статуса задачи: [ ] не оценён, [x] достигнут, [-] не достигнут.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Node

CRITERION = "Критерий: "
REVIEW = "Разбор: "
CAUSE = "Причина: "
CHANGE = "Меняем: "
PREFIXES = (CRITERION, REVIEW, CAUSE, CHANGE)

UNRATED, MET, MISSED = " ", "x", "-"
NEXT_MARK = {UNRATED: MET, MET: MISSED, MISSED: UNRATED}
SHOW_MARK = {UNRATED: "○", MET: "✓", MISSED: "✗"}
KINDS = ["закономерный успех", "чудо", "форсаж", "провал"]   # цифры 1–4 в окне разбора
ICON = "◎"          # на рамке окошка: у пункта есть критерии или разбор
FACT = " → "        # между критерием и фактом

_MARK_RE = re.compile(r"\[( |x|X|-)\]\s*")


@dataclass(frozen=True)
class Criterion:
    text: str
    mark: str = UNRATED
    fact: str = ""

    def line(self) -> str:
        s = f"{CRITERION}[{self.mark}] {self.text}"
        return s + FACT + self.fact if self.fact else s

    def show(self) -> str:
        s = f"{SHOW_MARK[self.mark]} {self.text}"
        return s + FACT + self.fact if self.fact else s


@dataclass(frozen=True)
class Review:
    kind: str = ""
    cause: str = ""
    change: str = ""

    def lines(self) -> list[str]:
        return [prefix + value for prefix, value in
                ((REVIEW, self.kind), (CAUSE, self.cause), (CHANGE, self.change)) if value]


def is_line(line: str) -> bool:
    """Служебная строка критериев или разбора (заметка её не показывает)."""
    s = line.strip()
    return any(s.startswith(p) and s[len(p):].strip() for p in PREFIXES)


def _criterion(body: str) -> Criterion:
    mark = UNRATED
    if m := _MARK_RE.match(body):
        mark = m[1].lower()
        body = body[m.end():]
    text, sep, fact = body.rpartition(FACT)
    if not sep:
        text, fact = body, ""
    return Criterion(text.strip(), mark, fact.strip())


def read(node: Node) -> list[Criterion]:
    return [_criterion(line.strip()[len(CRITERION):]) for line in node.notes
            if is_line(line) and line.strip().startswith(CRITERION)]


def review(node: Node) -> Review:
    found = {}
    for line in node.notes:
        s = line.strip()
        for prefix in (REVIEW, CAUSE, CHANGE):
            if is_line(s) and s.startswith(prefix):
                found.setdefault(prefix, s[len(prefix):].strip())
    return Review(found.get(REVIEW, ""), found.get(CAUSE, ""), found.get(CHANGE, ""))


def has(node: Node) -> bool:
    return any(is_line(line) for line in node.notes)


def unrated(node: Node) -> bool:
    """Есть что оценить: критерий без отметки или нет вида разбора."""
    items = read(node)
    return bool(items) and (any(c.mark == UNRATED for c in items) or not review(node).kind)


def lines_for(node: Node, items: list[Criterion], result: Review) -> list[str]:
    """Заметки пункта после правки: прочие строки на месте, затем критерии и разбор."""
    rest = [line for line in node.notes if not is_line(line)]
    return rest + [c.line() for c in items if c.text] + result.lines()
