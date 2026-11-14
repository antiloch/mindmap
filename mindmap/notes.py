"""Заметка пункта: строки под ним без маркера, кроме служебных (ссылки, критерии, разбор).

Строка заметки, которую файл прочёл бы иначе (пункт списка, вкладка, начало блока кода,
служебная строка), пишется с «\\» впереди и при показе возвращается как была.
"""
from __future__ import annotations

from . import criteria, links
from .mdformat import _MARKER_RE
from .model import Node

MARK = "✎"   # на рамке окошка: у пункта есть заметка


def _service(line: str) -> bool:
    """Строка ссылки, критерия или разбора: у них свои окна, заметка их не показывает."""
    return links._from_note(line) is not None or criteria.is_line(line)


def _special(body: str) -> bool:
    return bool(body.startswith(("#", "```")) or _MARKER_RE.match(body) or _service(body))


def _split(line: str) -> tuple[str, str]:
    body = line.lstrip(" ")
    return line[: len(line) - len(body)], body


def text(node: Node) -> str:
    """Заметка для окна правки: без ссылок и без экранирования."""
    out = []
    for line in node.notes:
        if _service(line):
            continue
        pad, body = _split(line)
        if body.startswith("\\") and _special(body[1:]):
            body = body[1:]
        out.append(pad + body)
    return "\n".join(out).strip("\n")


def has(node: Node) -> bool:
    return any(line.strip() and not _service(line) for line in node.notes)


def lines_for(node: Node, value: str) -> list[str]:
    """Строки заметок пункта после правки: новый текст, затем прежние служебные строки."""
    lines = [line.rstrip() for line in value.expandtabs(4).splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    out = []
    for line in lines:
        pad, body = _split(line)
        out.append(pad + ("\\" + body if body and _special(body) else body))
    return out + [line for line in node.notes if _service(line)]
