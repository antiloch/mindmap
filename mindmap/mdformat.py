"""Чтение и запись файла карты.

    # Вкладка (она же главная тема)

    - Пункт без статуса
      - [ ] Не завершено @2026-11-02..2026-11-06
      - [x] Завершено @2026 <!--collapsed-->

Файл можно править руками: чтение ничего не отвергает, а что не распознано,
остаётся текстом (заметкой пункта или частью названия).
"""
from __future__ import annotations

import re

from .dates import period_from_token
from .model import DONE, FAILED, PRIORITY_BARS, TODO, Document, Node

COLLAPSED = "<!--collapsed-->"
_PRIORITY_RE = re.compile(r"(▰{1,4}|[❶❷❸❹])(?:\s+|$)")  # кружочки — от прежних файлов, пишутся полосками
_PRIORITY_MARKS = {bars: level for level, bars in PRIORITY_BARS.items()} | {"❶": 1, "❷": 2, "❸": 3, "❹": 4}
_STATUS_RE = re.compile(r"\[( |x|X|-)\](?:\s+|$)")
_TOKEN_RE = re.compile(r"(?:^|\s+)@(\S+)$")
_ESC_TOKEN_RE = re.compile(r"(^|\s)\\@(\S+)$")
_BARE_TOKEN_RE = re.compile(r"(^|\s)@(\S+)$")
_ESC_STATUS_RE = re.compile(r"\\(\[(?: |x|X|-)\](?:\s|$))")
_LOOKS_STATUS_RE = re.compile(r"\[(?: |x|X|-)\](?:\s|$)")
_MARKER_RE = re.compile(r"(?:[-*+]|\d+[.)])(?:\s+|$)")
_HEADING_RE = re.compile(r"#\s+(.*)$")


def split_priority(text: str) -> tuple[int | None, str]:
    """Значок приоритета в начале строки: (уровень, остаток строки)."""
    if m := _PRIORITY_RE.match(text):
        return _PRIORITY_MARKS[m[1]], text[m.end():]
    return None, text


def _parse_head(content: str) -> Node:
    s = content.strip()
    node = Node()
    if s.endswith(COLLAPSED):
        node.collapsed = True
        s = s[: -len(COLLAPSED)].rstrip()
    if m := _STATUS_RE.match(s):
        node.status = {" ": TODO, "-": FAILED}.get(m[1], DONE)
        s = s[m.end():]
    node.priority, s = split_priority(s)
    if m := _TOKEN_RE.search(s):
        period = period_from_token(m[1])
        if period is not None:
            node.period = period
            s = s[: m.start()]
    if m := _ESC_TOKEN_RE.search(s):
        if period_from_token(m[2]) is not None:
            s = f"{s[: m.start()]}{m[1]}@{m[2]}"
    if m := _ESC_STATUS_RE.match(s):
        s = m[1] + s[m.end():]
    node.title = s.strip()
    return node


def _write_head(node: Node) -> str:
    title = node.title
    if _LOOKS_STATUS_RE.match(title):
        title = "\\" + title
    if (m := _BARE_TOKEN_RE.search(title)) and period_from_token(m[2]) is not None:
        title = f"{title[: m.start()]}{m[1]}\\@{m[2]}"
    parts = []
    if node.status is not None:
        parts.append({TODO: "[ ]", DONE: "[x]", FAILED: "[-]"}[node.status])
    if node.priority is not None:
        parts.append(PRIORITY_BARS[node.priority])
    if title:
        parts.append(title)
    if node.period is not None:
        parts.append("@" + node.period.token())
    if node.collapsed:
        parts.append(COLLAPSED)
    return " ".join(parts)


def parse(text: str, default_title: str = "Карта") -> Document:
    doc = Document()
    root: Node | None = None
    current: Node | None = None   # кому достаются строки-заметки
    base = 0                      # отступ заметок текущего пункта
    stack: list[tuple[int, Node]] = []
    blanks = 0
    fence = False

    def ensure_root() -> Node:
        nonlocal root
        if root is None:
            root = Node(default_title)
            doc.sheets.append(root)
        return root

    def add_note(line: str) -> None:
        nonlocal blanks
        target = current.notes if current is not None else doc.preamble
        if target:
            target.extend([""] * blanks)
        blanks = 0
        target.append(line)

    for raw in text.splitlines():
        body = raw.lstrip(" \t")
        prefix = raw[: len(raw) - len(body)]
        indent = len(prefix.expandtabs(4)) if "\t" in prefix else len(prefix)

        if body.startswith("```"):
            fence = not fence
            add_note(" " * max(0, indent - base) + body)
            continue
        if fence:
            add_note(" " * max(0, indent - base) + body)
            continue
        if not body:
            blanks += 1
            continue
        if not prefix and (m := _HEADING_RE.match(body)):
            root = _parse_head(m[1])
            doc.sheets.append(root)
            current, base, stack, blanks = root, 0, [], 0
            continue
        if m := _MARKER_RE.match(body):
            parent_root = ensure_root()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else parent_root
            node = parent.add(_parse_head(body[m.end():]))
            stack.append((indent, node))
            current, base, blanks = node, indent + 2, 0
            continue
        add_note(" " * max(0, indent - base) + body)

    if not doc.sheets:
        ensure_root()
    return doc


def item_lines(nodes: list[Node]) -> list[str]:
    """Пункты списком Markdown со всеми вложенными. Обход без рекурсии."""
    lines: list[str] = []
    stack = [(n, 0) for n in reversed(nodes)]
    while stack:
        node, depth = stack.pop()
        pad = "  " * depth
        lines.append(f"{pad}- {_write_head(node)}".rstrip())
        note_pad = pad + "  "
        lines.extend(note_pad + n if n else "" for n in node.notes)
        stack.extend((ch, depth + 1) for ch in reversed(node.children))
    return lines


def dump(doc: Document) -> str:
    lines: list[str] = []
    if doc.preamble:
        lines.extend(doc.preamble)
        lines.append("")
    for i, root in enumerate(doc.sheets):
        if i:
            lines.append("")
        lines.append(("# " + _write_head(root)).rstrip())
        if root.notes:
            lines.append("")
            lines.extend(root.notes)
        if root.children:
            lines.append("")
            lines.extend(item_lines(root.children))
    return "\n".join(lines) + "\n"
