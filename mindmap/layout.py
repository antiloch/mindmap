"""Раскладка дерева вправо на сетку символов: главная тема слева, ветки только вправо.

Чистая геометрия, без интерфейса. Обход без рекурсии, поэтому глубина не ограничена.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rich.cells import cell_len

from . import criteria, links, notes
from .model import DONE, FAILED, PRIORITY_BARS, TODO, DoneStub, Node, finished

INNER = 24        # ширина текста в окошке: вместе с рамкой и полями — 28
GAP = 4           # столбцов между родителем и ребёнком
VGAP = 1          # строк между соседними ветками
TITLE_LINES = 3

STATUS_TEXT = {TODO: "☐ не завершено", DONE: "☑ завершено", FAILED: "✗ провалено"}

# Символ линии по сторонам, куда она идёт: (влево, вправо, вверх, вниз)
_LINE = {
    (1, 1, 0, 0): "─", (0, 1, 0, 0): "─", (1, 0, 0, 0): "─",
    (0, 0, 1, 1): "│", (0, 0, 1, 0): "│", (0, 0, 0, 1): "│",
    (0, 1, 0, 1): "╭", (0, 1, 1, 0): "╰", (1, 0, 0, 1): "╮", (1, 0, 1, 0): "╯",
    (0, 1, 1, 1): "├", (1, 0, 1, 1): "┤", (1, 1, 0, 1): "┬", (1, 1, 1, 0): "┴",
    (1, 1, 1, 1): "┼",
}


def _cut(text: str, width: int) -> tuple[str, str]:
    """Отрезать слева столько символов, сколько влезает в width клеток."""
    used = 0
    for i, ch in enumerate(text):
        w = cell_len(ch)
        if used + w > width:
            return text[:i], text[i:]
        used += w
    return text, ""


def wrap(text: str, width: int, max_lines: int | None = None) -> list[str]:
    """Перенос по словам; слишком длинное слово режется, лишнее заменяется на «…»."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        candidate = f"{cur} {word}" if cur else word
        if cell_len(candidate) <= width:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
        while cell_len(word) > width:
            head, word = _cut(word, width)
            lines.append(head)
        cur = word
    if cur or not lines:
        lines.append(cur)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last, _ = _cut(lines[-1], width - 1)
        lines[-1] = last.rstrip() + "…"
    return lines


def box_lines(node: Node, inner: int = INNER) -> list[str]:
    """Текст окошка: приоритет и название, статус, срок, ссылки (только то, что задано)."""
    title = node.title or "(без названия)"
    if node.priority is not None:
        title = f"{PRIORITY_BARS[node.priority]} {title}"
    lines = wrap(title, inner, TITLE_LINES)
    if node.status is not None:
        lines.append(STATUS_TEXT[node.status])
    if node.period is not None:
        lines.extend(wrap(node.period.show(), inner))
    link = links.box_line(node)
    if link:
        lines.extend(wrap(link, inner, 1))
    return lines


def counter(node: Node) -> str:
    """«1/3» на рамке родителя: сколько детей со статусом завершено."""
    marked = [c for c in node.children if c.status is not None]
    if not marked:
        return ""
    return f"{sum(c.status == DONE for c in marked)}/{len(marked)}"


def frame_label(node: Node, with_counter: bool = True) -> str:
    """Надпись на верхней рамке: «✎» — есть заметка, «◎» — критерии или разбор, счётчик детей."""
    parts = [notes.MARK] if notes.has(node) else []
    if criteria.has(node):
        parts.append(criteria.ICON)
    if with_counter and (c := counter(node)):
        parts.append(c)
    return " ".join(parts)


def box_rows(lines: list[str], inner: int, label: str = "", selected: bool = False) -> list[str]:
    """Окошко построчно: рамка и текст. Выбранный пункт — двойной рамкой."""
    tl, tr, bl, br, h, v = "╔╗╚╝═║" if selected else "╭╮╰╯─│"
    if label:
        top = tl + h * (inner + 2 - len(label) - 3) + f" {label} " + h + tr
    else:
        top = tl + h * (inner + 2) + tr
    rows = [top]
    for line in lines:
        rows.append(f"{v} {line}{' ' * (inner - cell_len(line))} {v}")
    rows.append(bl + h * (inner + 2) + br)
    return rows


@dataclass(slots=True, eq=False)
class Box:
    node: Node
    depth: int
    lines: list[str]
    inner: int
    label: str
    hidden: int = 0      # сколько пунктов спрятано в свёрнутой ветке
    x: int = 0
    y: int = 0
    # служебное для раскладки: высота поддерева и смещения детей внутри него
    band: int = 0
    kids: list["Box"] = field(default_factory=list)
    kid_offsets: list[int] = field(default_factory=list)

    @property
    def w(self) -> int:
        return self.inner + 4

    @property
    def h(self) -> int:
        return len(self.lines) + 2

    @property
    def anchor(self) -> int:
        """Строка, в которой к окошку подходят линии: первая строка текста."""
        return self.y + 1


@dataclass(slots=True)
class Layout:
    boxes: list[Box]
    by_node: dict[int, Box]
    by_depth: list[list[Box]]
    lines: dict[int, list[tuple[int, str]]]  # строка → [(столбец, символ или текст)]
    width: int
    height: int


def _make_box(node: Node, depth: int) -> Box:
    lines = box_lines(node)
    label = frame_label(node)
    hidden = 0
    if node.collapsed and node.children:
        hidden = sum(1 for _ in node.walk()) - 1
    return Box(node, depth, lines, INNER, label, hidden)


def stub_title(done: int, failed: int, shown: bool) -> str:
    """«… завершено: 2✓ 1✗»: удачно и неудачно закрытые отдельно."""
    parts = [f"{done}✓"] if done else []
    if failed:
        parts.append(f"{failed}✗")
    return f"… завершено: {' '.join(parts)}" + (", показаны" if shown else "")


def visible_children(node: Node, shown, stubs: dict[int, DoneStub]) -> list[Node]:
    """Дети на карте: при завершённых первым идёт окошко «…», сами завершённые —
    только если у пункта они показаны (shown — id таких пунктов)."""
    if node.collapsed or isinstance(node, DoneStub):
        return []
    kids = node.children
    done = sum(1 for c in kids if c.status == DONE)
    failed = sum(1 for c in kids if c.status == FAILED)
    if not done + failed:
        return list(kids)
    stub = stubs.get(id(node))
    if stub is None or stub.host is not node:
        stub = stubs[id(node)] = DoneStub(node)
    open_ = id(node) in shown
    stub.count = done + failed
    stub.title = stub_title(done, failed, open_)
    return [stub] + (list(kids) if open_ else [c for c in kids if not finished(c)])


def compute(root: Node, shown=frozenset(), stubs: dict[int, DoneStub] | None = None) -> Layout:
    """shown — id пунктов, у которых завершённые показаны; stubs — окошки «…» по id
    родителя, чтобы выбранное окошко оставалось тем же объектом между перерисовками."""
    stubs = {} if stubs is None else stubs
    # 1. Видимые пункты в прямом порядке.
    top = _make_box(root, 0)
    order = [top]
    stack = [top]
    while stack:
        box = stack.pop()
        box.kids = [_make_box(ch, box.depth + 1) for ch in visible_children(box.node, shown, stubs)]
        order.extend(box.kids)
        stack.extend(box.kids)

    # 2. Снизу вверх: высота полосы поддерева. Первый ребёнок начинается вровень
    #    с родителем, остальные — ниже. Родители всегда раньше детей в order,
    #    поэтому обратный проход безопасен.
    for box in reversed(order):
        cursor = 0
        for kid in box.kids:
            box.kid_offsets.append(cursor)
            cursor += kid.band + VGAP
        box.band = max(box.h, cursor - VGAP)

    # 3. Сверху вниз: координаты.
    lines: dict[int, list[tuple[int, str]]] = {}
    by_depth: list[list[Box]] = []
    width = height = 0
    for box in order:
        for kid, off in zip(box.kids, box.kid_offsets):
            kid.x = box.x + box.w + GAP
            kid.y = box.y + off

    for box in order:
        while len(by_depth) <= box.depth:
            by_depth.append([])
        by_depth[box.depth].append(box)
        right = box.x + box.w
        if box.hidden:
            badge = f" +{box.hidden}"
            lines.setdefault(box.anchor, []).append((right, badge))
            right += len(badge)
        width = max(width, right)
        height = max(height, box.y + box.h)
        if box.kids:
            _connect(box, lines)
    for row in by_depth:
        row.sort(key=lambda b: b.y)

    return Layout(order, {id(b.node): b for b in order}, by_depth, lines, width, height)


def _connect(box: Box, lines: dict[int, list[tuple[int, str]]]) -> None:
    """Линии от родителя к детям: короткий отрезок, ствол и отводы."""
    start = box.x + box.w
    trunk = start + 1
    py = box.anchor
    ys = [k.anchor for k in box.kids]
    low, high = min(ys + [py]), max(ys + [py])

    def put(y: int, x: int, ch: str) -> None:
        lines.setdefault(y, []).append((x, ch))

    put(py, start, "─")
    kid_rows = set(ys)
    for y in range(low, high + 1):
        flags = (
            int(y == py),
            int(y in kid_rows),
            int(y > low),
            int(y < high),
        )
        put(y, trunk, _LINE[flags])
    for y in ys:
        for x in range(trunk + 1, box.x + box.w + GAP):
            put(y, x, "─")
