"""Канбан-доска. Колонки вычисляются из даты и статуса, источник правды — сама карта."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

from . import status as st
from .canvas import BACKGROUND, COLORS, LINE_STYLE, SELECTED_BG, box_style
from .layout import _cut, box_lines, box_rows, frame_label
from .model import Node, finished

NO_PRIORITY = 5  # пункты без приоритета — после самого низкого
NEST_STEP = 4    # рамка и поля родителя вокруг вложенной карточки
MIN_INNER = 14   # уже не вкладываем: строка статуса перестанет помещаться
# Завершённых и проваленных на доске нет: смотреть на них незачем, итог разбирают по gk.
COLUMN_TITLES = ["Запланировано", "На этой неделе"]
COLS = len(COLUMN_TITLES)
SECTIONS = [
    [(None, st.B_PLANNED)],
    [("Сегодня", st.B_TODAY), ("Просрочено", st.B_OVERDUE), ("Эта неделя", st.B_WEEK), ("Идёт", st.B_RUNNING)],
]
SECTION_STYLE = {
    st.B_TODAY: Style(color=COLORS[st.ORANGE], bold=True),
    st.B_OVERDUE: Style(color=COLORS[st.RED], bold=True),
    st.B_WEEK: Style(color=COLORS[st.ORANGE]),
    st.B_RUNNING: Style(color=COLORS[st.ORANGE]),
}
DIM = Style(color=COLORS[st.GREY])
HEAD = Style(color=COLORS[st.PLAIN])
HEAD_ACTIVE = Style(color=COLORS[st.PLAIN], bold=True, underline=True)


def collect(sheets: list[Node], now: datetime) -> dict[str, list[Node]]:
    """Незакрытые пункты с датой по разделам доски. Без даты и закрытые сюда не попадают."""
    out: dict[str, list[Node]] = {}
    for root in sheets:
        for node in root.walk():
            if finished(node):
                continue
            place = st.bucket(node, now)
            if place is not None:
                out.setdefault(place, []).append(node)
    for place, nodes in out.items():
        nodes.sort(key=lambda n: (n.priority or NO_PRIORITY, n.period.first(), n.period.last()))
    return out


def full_span(node: Node) -> tuple:
    return node.period.first(), node.period.last()


def nest(nodes: list[Node], span=full_span) -> tuple[list[Node], dict[int, list[Node]]]:
    """Какие карточки лежат внутри других: пункт входит в ближайшего родителя из этого
    же набора, если весь его срок внутри срока родителя. span — что считать сроком
    (на графике — только дни в окне). Порядок сохраняется."""
    here = {id(n) for n in nodes}
    tops: list[Node] = []
    kids: dict[int, list[Node]] = {}
    for node in nodes:
        first, last = span(node)
        host = next((a for a in node.ancestors() if id(a) in here
                     and span(a)[0] <= first and last <= span(a)[1]), None)
        if host is None:
            tops.append(node)
        else:
            kids.setdefault(id(host), []).append(node)
    return tops, kids


def crumb(node: Node, with_tab: bool, inside: Node | None = None) -> str:
    """Откуда карточка: «Вкладка › ветка». Без вкладки — только ветка.
    Внутри другой карточки — только путь от неё."""
    ancestors = node.ancestors()
    if inside is not None:
        return " › ".join(a.title for a in reversed(ancestors[:ancestors.index(inside)]))
    names = [a.title for a in reversed(ancestors)]
    if names and not with_tab:
        names = names[1:]
    return " › ".join(names)


def cut_left(text: str, width: int) -> str:
    """Оставить конец строки: ближайшая ветка важнее дальней."""
    if cell_len(text) <= width:
        return text
    tail = text
    while cell_len(tail) > width - 1:
        tail = tail[1:]
    return "…" + tail


@dataclass
class _Line:
    segments: list[Segment]


class KanbanView(Widget, inherit_bindings=False):
    DEFAULT_CSS = f"""
    KanbanView {{
        background: {BACKGROUND};
    }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.col = 1
        self.index = [0] * COLS
        self.cards: list[list[Node]] = [[] for _ in range(COLS)]
        self.scroll = [0] * COLS
        self.sheets: list[Node] = []
        self.with_tab = False
        self.now = datetime.now()
        self._parts: dict[str, list[Node]] = {}
        self._tops: dict[str, list[Node]] = {}
        self._kids: dict[int, list[Node]] = {}
        self._lines: list[list[_Line]] = [[] for _ in range(COLS)]
        self._ranges: list[list[tuple[int, int]]] = [[] for _ in range(COLS)]
        self._col_w = 0

    # ---------- данные и выбор ----------

    def current(self) -> Node | None:
        cards = self.cards[self.col]
        if not cards:
            return None
        return cards[min(self.index[self.col], len(cards) - 1)]

    def load(self, sheets: list[Node], now: datetime, with_tab: bool, follow: Node | None = None) -> None:
        """Пересобрать доску. follow — карточка, за которой должен перейти выбор."""
        self.sheets, self.now, self.with_tab = sheets, now, with_tab
        parts = collect(sheets, now)
        self._parts = parts
        self._tops, self._kids = {}, {}
        for place, nodes in parts.items():
            self._tops[place], kids = nest(nodes)
            self._kids.update(kids)
        # Порядок выбора совпадает с порядком на экране: родитель, затем вложенные.
        self.cards = [[n for _, place in SECTIONS[c] for n in self._in_order(self._tops.get(place, []))]
                      for c in range(COLS)]
        if follow is not None:
            for c in range(COLS):
                for i, n in enumerate(self.cards[c]):
                    if n is follow:
                        self.col, self.index[c] = c, i
        for c in range(COLS):
            self.index[c] = max(0, min(self.index[c], len(self.cards[c]) - 1))
        self._draw()

    def _in_order(self, tops: list[Node]) -> list[Node]:
        out: list[Node] = []
        stack = list(reversed(tops))
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(reversed(self._kids.get(id(node), [])))
        return out

    def move_col(self, delta: int) -> None:
        self.col = max(0, min(COLS - 1, self.col + delta))
        self._draw()

    def move_card(self, delta: int) -> None:
        cards = self.cards[self.col]
        if cards:
            self.index[self.col] = max(0, min(len(cards) - 1, self.index[self.col] + delta))
            self._draw()

    def jump(self, last: bool) -> None:
        self.index[self.col] = max(0, len(self.cards[self.col]) - 1) if last else 0
        self._draw()

    # ---------- рисование ----------

    def on_resize(self) -> None:
        self._draw()

    def _wheel(self, event, delta: int) -> None:
        event.stop()
        event.prevent_default()
        self.move_card(delta)
        self.app.update_bars()

    def on_mouse_scroll_down(self, event) -> None:
        self._wheel(event, 1)

    def on_mouse_scroll_up(self, event) -> None:
        self._wheel(event, -1)

    def _style(self, node: Node, selected: bool, lit: bool) -> Style:
        """lit — карточка лежит внутри выбранной: подсветка общая, а выбрана только внешняя."""
        style = box_style(st.classify(node, self.now), selected)
        return style + Style(bgcolor=SELECTED_BG) if lit else style

    def _card(self, node: Node, inner: int, selected: bool, inside: Node | None, lit: bool) -> list[_Line]:
        lines = box_lines(node, inner)
        where = cut_left(crumb(node, self.with_tab, inside), inner)
        if where:
            lines.append(where)
        style = self._style(node, selected, lit)
        rows = box_rows(lines, inner, frame_label(node, with_counter=False), selected)
        out = []
        for i, row in enumerate(rows):
            if where and i == len(rows) - 2:
                # Строка «откуда» приглушена внутри рамки того же цвета.
                out.append(_Line([Segment(row[:2], style), Segment(row[2:-2], DIM + Style(bgcolor=style.bgcolor)), Segment(row[-2:], style)]))
            else:
                out.append(_Line([Segment(row, style)]))
        return out

    def _stack(self, nodes: list[Node], inner: int, c: int, top: int,
               ranges: list[tuple[int, int]], inside: Node | None = None, lit: bool = False) -> list[_Line]:
        """Карточки друг под другом, вложенные — внутри родителя. Рекурсия неглубокая:
        её ограничивает ширина колонки. Где места нет, вложенные идут сразу под родителем."""
        out: list[_Line] = []
        for node in nodes:
            pos = len(ranges)
            ranges.append((0, 0))
            selected = c == self.col and pos == self.index[c]
            card = self._card(node, inner, selected, inside, lit)
            start = top + len(out)
            out.extend(card[:-1])
            kids = self._kids.get(id(node), [])
            fits = inner - NEST_STEP >= MIN_INNER
            if kids and fits:
                style = self._style(node, selected, lit)
                side = "║" if selected else "│"
                left, right = Segment(f"{side} ", style), Segment(f" {side}", style)
                inner_cards = self._stack(kids, inner - NEST_STEP, c, top + len(out), ranges, node, lit or selected)
                out.extend(_Line([left, *line.segments, right]) for line in inner_cards)
            out.append(card[-1])
            ranges[pos] = (start, top + len(out))
            if kids and not fits:
                out.extend(self._stack(kids, inner, c, top + len(out), ranges, inside, lit or selected))
        return out

    def _draw(self) -> None:
        width = self.size.width
        if not width:
            return
        self._col_w = max(12, (width - (COLS - 1)) // COLS)
        inner = max(6, self._col_w - 4)
        for c in range(COLS):
            lines: list[_Line] = []
            ranges: list[tuple[int, int]] = []
            for title, place in SECTIONS[c]:
                nodes = self._parts.get(place, [])
                if not nodes:
                    continue
                if title:
                    label = f"─ {title} ({len(nodes)}) "
                    label += "─" * max(0, self._col_w - cell_len(label))
                    lines.append(_Line([Segment(label, SECTION_STYLE[place])]))
                lines.extend(self._stack(self._tops[place], inner, c, len(lines), ranges))
            self._lines[c], self._ranges[c] = lines, ranges
        self._reveal()
        self.refresh()

    def _reveal(self) -> None:
        body = max(1, self.size.height - 2)
        for c in range(COLS):
            if not self._ranges[c]:
                self.scroll[c] = 0
                continue
            top, bottom = self._ranges[c][self.index[c]]
            # Заголовок раздела — над карточкой, его показываем вместе с первой.
            if self.index[c] == 0:
                top = 0
            if bottom > self.scroll[c] + body:
                self.scroll[c] = bottom - body
            if top < self.scroll[c]:
                self.scroll[c] = top

    def _head(self, c: int) -> list[Segment]:
        text = f" {COLUMN_TITLES[c]} ({len(self.cards[c])})"
        text, _ = _cut(text, self._col_w)
        return [Segment(text, HEAD_ACTIVE if c == self.col else HEAD)]

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        base = self.rich_style
        if not self._col_w:
            return Strip.blank(width, base)
        segments: list[Segment] = []
        for c in range(COLS):
            if y == 0:
                cell = self._head(c)
            elif y == 1:
                cell = [Segment("─" * self._col_w, LINE_STYLE)]
            else:
                idx = y - 2 + self.scroll[c]
                cell = self._lines[c][idx].segments if idx < len(self._lines[c]) else []
            used = sum(seg.cell_length for seg in cell)
            segments.extend(cell)
            if used < self._col_w:
                segments.append(Segment(" " * (self._col_w - used)))
            if c < COLS - 1:
                segments.append(Segment("│", LINE_STYLE))
        return Strip(segments).adjust_cell_length(width).apply_style(base)
