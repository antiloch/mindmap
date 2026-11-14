"""Ссылки пункта. В файле это строки-заметки, поэтому файл остаётся обычным Markdown:

      Ссылка: https://thecode.media/launchctl/
      Ссылка: ~/Desktop/отчёт.pdf
      Ссылка на пункт: Регулярный менеджмент
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .model import Node

WEB = "web"       # сайт или почта
FILE = "file"     # файл или папка на этом компьютере
ITEM = "item"     # другой пункт карты
OTHER = "other"   # адрес, который программа не открывает

_ADDRESS = "Ссылка: "
_ITEM = "Ссылка на пункт: "
_WEB_RE = re.compile(r"(?:https?://|mailto:)\S", re.I)
_PATH_RE = re.compile(r"(?:/|~/|\./|\.\./|file://)")
# Такие файлы при открытии запускают код, поэтому сначала спрашиваем.
_RUNNABLE = {".app", ".command", ".sh", ".tool", ".terminal", ".workflow", ".pkg", ".mpkg"}
_MATCHES_SHOWN = 3


@dataclass(frozen=True)
class Link:
    kind: str
    target: str

    def note(self) -> str:
        return (_ITEM if self.kind == ITEM else _ADDRESS) + self.target


def _classify(address: str) -> Link:
    if _WEB_RE.match(address):
        return Link(WEB, address)
    if _PATH_RE.match(address):
        return Link(FILE, address)
    return Link(OTHER, address)


def _from_note(line: str) -> Link | None:
    s = line.strip()
    if s.startswith(_ITEM) and s[len(_ITEM):].strip():
        return Link(ITEM, s[len(_ITEM):].strip())
    if s.startswith(_ADDRESS) and s[len(_ADDRESS):].strip():
        return _classify(s[len(_ADDRESS):].strip())
    return None


def read(node: Node) -> list[Link]:
    return [link for line in node.notes if (link := _from_note(line)) is not None]


def add(node: Node, link: Link) -> bool:
    """Дописать ссылку. False — такая уже есть."""
    if link in read(node):
        return False
    node.notes.append(link.note())
    return True


def remove(node: Node, link: Link) -> None:
    for i, line in enumerate(node.notes):
        if _from_note(line) == link:
            del node.notes[i]
            return


def label(link: Link) -> str:
    """Короткое имя для окошка."""
    if link.kind == WEB:
        if link.target.lower().startswith("mailto:"):
            return link.target[len("mailto:"):]
        host = urlsplit(link.target).netloc
        return host[4:] if host.startswith("www.") else host
    if link.kind == FILE:
        return Path(link.target.rstrip("/")).name or link.target
    return link.target


def box_line(node: Node) -> str | None:
    """Строка в окошке пункта."""
    links = read(node)
    if not links:
        return None
    if len(links) > 1:
        return f"↗ ссылок: {len(links)}"
    return ("→ " if links[0].kind == ITEM else "↗ ") + label(links[0])


def file_path(link: Link, base: Path) -> Path:
    """Путь на диске. Относительный считается от папки карты."""
    target = link.target
    if target.lower().startswith("file://"):
        target = unquote(urlsplit(target).path)
    path = Path(target).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def is_runnable(path: Path) -> bool:
    """Открытие такого файла запустит код, а не покажет его."""
    if path.suffix.lower() in _RUNNABLE:
        return True
    return path.is_file() and os.access(path, os.X_OK)


def items_named(sheets: list[Node], title: str, exclude: Node | None = None) -> list[Node]:
    """Пункты с точно таким названием. Сам пункт не считается: в карте пункт и вкладка
    с одним названием ссылаются друг на друга."""
    return [n for root in sheets for n in root.walk() if n.title == title and n is not exclude]


def rename_target(sheets: list[Node], old: str, new: str) -> None:
    """Пункт переименован: ссылки на него должны вести туда же."""
    before = Link(ITEM, old)
    after = Link(ITEM, new).note()
    for root in sheets:
        for node in root.walk():
            for i, line in enumerate(node.notes):
                if _from_note(line) == before:
                    node.notes[i] = after


def _clean_address(text: str) -> str:
    """Terminal при перетаскивании файла экранирует путь и дописывает пробел."""
    s = text.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return re.sub(r"\\(.)", r"\1", s) if "\\" in s else s


def parse_input(text: str, sheets: list[Node], node: Node | None = None) -> Link | None:
    """Строка из окна ссылки → Link; пустая → None. Непонятное — ValueError с текстом для показа."""
    raw = text.strip()
    if not raw:
        return None
    address = _clean_address(raw)
    if _WEB_RE.match(address):
        return Link(WEB, address)
    if address.lower().startswith("www."):
        return Link(WEB, "https://" + address)
    if _PATH_RE.match(address):
        return Link(FILE, address)

    titles: dict[str, None] = {}
    wanted = raw.casefold()
    exact: dict[str, None] = {}
    for root in sheets:
        for n in root.walk():
            if n is node or not n.title:
                continue
            folded = n.title.casefold()
            if folded == wanted:
                exact[n.title] = None
            elif wanted in folded:
                titles[n.title] = None
    found = list(exact or titles)
    if not found:
        raise ValueError(f"Нет такого пункта: «{raw}»")
    if len(found) > 1:
        shown = ", ".join(found[:_MATCHES_SHOWN])
        raise ValueError(f"Подходит пунктов: {len(found)} ({shown}…), уточните")
    return Link(ITEM, found[0])
