"""Дерево карты. Обход везде без рекурсии: глубина вложенности не ограничена."""
from __future__ import annotations

from typing import Iterator

from .dates import Period

TODO = "todo"
DONE = "done"
FAILED = "failed"   # завершено неудачно
PRIORITY_BARS = {1: "▰▰▰▰", 2: "▰▰▰", 3: "▰▰", 4: "▰"}  # 1 — самый важный


class Node:
    __slots__ = ("title", "status", "period", "collapsed", "priority", "notes", "children", "parent")

    def __init__(self, title: str = "", status: str | None = None, period: Period | None = None,
                 collapsed: bool = False, priority: int | None = None) -> None:
        self.title = title
        self.status = status  # None — статуса нет, TODO, DONE, FAILED
        self.period = period
        self.collapsed = collapsed
        self.priority = priority  # None — приоритета нет, 1…4
        self.notes: list[str] = []
        self.children: list[Node] = []
        self.parent: Node | None = None

    def __repr__(self) -> str:
        return f"Node({self.title!r})"

    def add(self, child: "Node", index: int | None = None) -> "Node":
        child.parent = self
        if index is None:
            self.children.append(child)
        else:
            self.children.insert(index, child)
        return child

    def detach(self) -> None:
        if self.parent is not None:
            self.parent.children.remove(self)
            self.parent = None

    @property
    def index(self) -> int:
        return self.parent.children.index(self) if self.parent else 0

    def walk(self) -> Iterator["Node"]:
        """Прямой обход поддерева, начиная с самого пункта."""
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def ancestors(self) -> list["Node"]:
        """Родители от ближайшего к главной теме."""
        out, n = [], self.parent
        while n is not None:
            out.append(n)
            n = n.parent
        return out

    def root(self) -> "Node":
        n = self
        while n.parent is not None:
            n = n.parent
        return n

    def path(self) -> tuple[int, ...]:
        out, n = [], self
        while n.parent is not None:
            out.append(n.parent.children.index(n))
            n = n.parent
        return tuple(reversed(out))

    def follow(self, path: tuple[int, ...]) -> "Node":
        """Пункт по пути индексов; если ветка короче — самый близкий из существующих."""
        n = self
        for i in path:
            if not n.children:
                break
            n = n.children[min(i, len(n.children) - 1)]
        return n

    def clone(self) -> "Node":
        def one(src: Node) -> Node:
            c = Node(src.title, src.status, src.period, src.collapsed, src.priority)
            c.notes = list(src.notes)
            return c

        top = one(self)
        stack = [(self, top)]
        while stack:
            src, dst = stack.pop()
            for ch in src.children:
                d = dst.add(one(ch))
                stack.append((ch, d))
        return top


class Document:
    """Файл целиком: вкладки (корни) и текст перед первой вкладкой."""

    def __init__(self, sheets: list[Node] | None = None, preamble: list[str] | None = None) -> None:
        self.sheets = sheets if sheets is not None else []
        self.preamble = preamble or []


class DoneStub(Node):
    """Окошко «…» первым ребёнком: за ним спрятаны завершённые дети пункта host.
    В дерево не входит: host.children его не содержит, в файл оно не пишется."""
    __slots__ = ("host", "count")

    def __init__(self, host: Node) -> None:
        super().__init__()
        self.host = host
        self.parent = host
        self.count = 0      # сколько спрятано: завершённых и проваленных вместе

    def __repr__(self) -> str:
        return f"DoneStub({self.host.title!r})"

    @property
    def index(self) -> int:
        return 0

    def path(self) -> tuple[int, ...]:
        return self.host.path()


def finished(node: Node) -> bool:
    """Задача закрыта: завершена или провалена."""
    return node.status in (DONE, FAILED)


def done_hidden(node: Node, shown) -> bool:
    """Спрятан ли пункт за «…»: он сам или его предок завершён, а у родителя завершённые не показаны.
    shown — множество id родителей, у которых завершённые показаны."""
    n = node
    while n.parent is not None:
        if finished(n) and id(n.parent) not in shown:
            return True
        n = n.parent
    return False
