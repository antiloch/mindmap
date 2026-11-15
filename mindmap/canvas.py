"""Вид карты. Рисуется только видимая часть, поэтому размер карты не важен."""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from . import status as st
from .layout import Box, Layout, box_rows, compute
from .model import DoneStub, Node

BACKGROUND = "#14161b"
COLORS = {
    st.RED: "#ff5c57",
    st.YELLOW: "#f2d34b",     # уже идёт
    st.ORANGE: "#ff9f1c",
    st.GREEN: "#3fcf6e",
    st.GREY: "#5f6672",
    st.DARK_RED: "#7e3536",   # красный, наполовину смешанный с фоном
    st.PLAIN: "#d8dce3",
}
LINE_STYLE = Style(color="#5f6672")
SELECTED_BG = "#2a2f3a"
MARKED_BG = "#3d4470"
WHEEL_ROWS = 3
WHEEL_COLS = 6


def box_style(kind: str, selected: bool, marked: bool = False) -> Style:
    if marked:
        return Style(color=COLORS[kind], bold=selected, bgcolor=MARKED_BG)
    if selected:
        return Style(color=COLORS[kind], bold=True, bgcolor=SELECTED_BG)
    return Style(color=COLORS[kind])


class MapView(ScrollView, inherit_bindings=False):
    DEFAULT_CSS = f"""
    MapView {{
        background: {BACKGROUND};
        scrollbar-size: 0 0;
    }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan: Layout | None = None
        self.current: Box | None = None
        self._rows: dict[int, list[tuple[int, int, str, Style]]] = {}
        self._starts: dict[int, list[int]] = {}
        self._max_item = 1

    def show(self, root: Node, selected: Node, now: datetime, reveal: bool = True, marks=(),
             shown=frozenset(), stubs: dict | None = None) -> None:
        self.plan = compute(root, shown, stubs)
        self.current = self.plan.by_node.get(id(selected)) or self.plan.boxes[0]
        self._index(now, {id(n) for n in marks})
        self.virtual_size = Size(self.plan.width + 2, self.plan.height + 1)
        self.refresh()
        if reveal:
            self.reveal_current()

    def _index(self, now: datetime, marked: set[int]) -> None:
        rows: dict[int, list[tuple[int, int, str, Style]]] = {}
        widest = 1
        for box in self.plan.boxes:
            chosen = box is self.current
            kind = st.GREY if isinstance(box.node, DoneStub) else st.classify(box.node, now)
            style = box_style(kind, chosen, id(box.node) in marked)
            for i, text in enumerate(box_rows(box.lines, box.inner, box.label, chosen)):
                rows.setdefault(box.y + i, []).append((box.x, box.w, text, style))
            widest = max(widest, box.w)
        for y, items in self.plan.lines.items():
            row = rows.setdefault(y, [])
            for x, text in items:
                width = cell_len(text)
                row.append((x, width, text, LINE_STYLE))
                widest = max(widest, width)
        for row in rows.values():
            row.sort(key=lambda item: item[0])
        self._rows = rows
        self._starts = {y: [item[0] for item in row] for y, row in rows.items()}
        self._max_item = widest

    def reveal_current(self, center: bool = False) -> None:
        """Прокрутить так, чтобы выбранный пункт был виден целиком."""
        box = self.current
        if box is None or not self.size.width or not self.size.height:
            return
        w, h = self.size
        if center:
            nx = box.x + box.w // 2 - w // 2
            ny = box.y + box.h // 2 - h // 2
        else:
            x0, y0 = self.scroll_offset
            margin = 2
            nx = x0
            if box.x + box.w + margin > nx + w:
                nx = box.x + box.w + margin - w
            if box.x - margin < nx:      # левый край важнее: там начало текста
                nx = box.x - margin
            ny = y0
            if box.y + box.h + 1 > ny + h:
                ny = box.y + box.h + 1 - h
            if box.y - 1 < ny:
                ny = box.y - 1
        self.scroll_to(max(0, nx), max(0, ny), animate=False, force=True, immediate=True)

    def on_resize(self) -> None:
        self.reveal_current()

    # Колёсико приходит в программу, а не в историю терминала; прокручивает только вид.

    def _wheel(self, event, dx: int, dy: int) -> None:
        event.stop()
        event.prevent_default()
        x, y = self.scroll_offset
        self.scroll_to(x + dx, y + dy, animate=False, force=True, immediate=True)

    def on_mouse_scroll_down(self, event) -> None:
        if event.shift:
            self._wheel(event, WHEEL_COLS, 0)
        else:
            self._wheel(event, 0, WHEEL_ROWS)

    def on_mouse_scroll_up(self, event) -> None:
        if event.shift:
            self._wheel(event, -WHEEL_COLS, 0)
        else:
            self._wheel(event, 0, -WHEEL_ROWS)

    def on_mouse_scroll_right(self, event) -> None:
        self._wheel(event, WHEEL_COLS, 0)

    def on_mouse_scroll_left(self, event) -> None:
        self._wheel(event, -WHEEL_COLS, 0)

    def render_line(self, y: int) -> Strip:
        sx, sy = self.scroll_offset
        width = self.size.width
        base = self.rich_style
        row = self._rows.get(y + sy)
        if not row:
            return Strip.blank(width, base)
        # Находим первое окошко, которое может попасть в экран, не перебирая всю строку.
        first = max(0, bisect_right(self._starts[y + sy], sx - self._max_item) - 1)
        origin = None
        cursor = 0
        segments: list[Segment] = []
        for x, w, text, style in row[first:]:
            if x >= sx + width:
                break
            if x + w <= sx:
                continue
            if origin is None:
                origin = min(x, sx)
                cursor = origin
            if x > cursor:
                segments.append(Segment(" " * (x - cursor)))
            segments.append(Segment(text, style))
            cursor = x + w
        if origin is None:
            return Strip.blank(width, base)
        strip = Strip(segments, cursor - origin)
        return strip.crop(sx - origin, sx - origin + width).adjust_cell_length(width).apply_style(base)
