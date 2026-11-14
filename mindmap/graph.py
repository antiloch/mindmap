"""Сетевой график: дни, недели или месяцы столбцами; задача растянута на свои дни,
дети — внутри родителей.

Задача — полоса в одну строку, как в диаграмме Ганта, родитель с вложенными — рамка на свои дни.
На месяце, квартале и годе однодневные задачи не рисуются (кроме вех с приоритетом 1–2),
их число стоит над столбцом — так видна загрузка недели или месяца.

Каждая задача занимает свою полосу строк: ничего не накладывается, порядок читается сверху вниз.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, time, timedelta

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

from . import status as st
from .board import DIM, HEAD, HEAD_ACTIVE, NO_PRIORITY, nest
from .canvas import BACKGROUND, LINE_STYLE, SELECTED_BG, box_style
from .layout import _cut, frame_label
from .model import DONE, FAILED, PRIORITY_BARS, TODO, Node

DAYS = 7
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
GUIDE = "┊"       # граница столбцов там, где нет окошек
MARK = {TODO: "☐ ", DONE: "☑ ", FAILED: "✗ "}

# Масштабы: «-» отдаляет, «+» приближает.
SCALES = ["week", "month", "quarter", "year"]
SCALE_NAMES = {"week": "неделя", "month": "месяц", "quarter": "квартал", "year": "год"}
SHIFT_WEEKS = {"month": 5, "quarter": 13}   # длина сдвинутого окна, недель
MILESTONE_PRIORITY = 2   # однодневная задача с приоритетом 1–2 на крупном масштабе — веха
MILESTONE = "◆"
FRAME_MIN = 24    # уже рамки вложенные полосы идут под родителем: внутри не видно названий
NAME_MIN = 12     # столько клеток названию нужно хотя бы, чтобы стоять рядом с полосой

Item = tuple[int, str, Style]   # (столбец, текст, стиль); позже нарисованное лежит сверху


def add_months(day: date, months: int) -> date:
    """Первое число месяца через months месяцев."""
    m = day.month - 1 + months
    return date(day.year + m // 12, m % 12 + 1, 1)


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def bounds(scale: str, anchor: date) -> tuple[date, date]:
    """Окно масштаба вокруг anchor: неделя — 7 дней с него, остальное — календарный период.
    Конец не входит в окно."""
    if scale == "week":
        return anchor, anchor + timedelta(days=DAYS)
    if scale == "month":
        first = anchor.replace(day=1)
        return first, add_months(first, 1)
    if scale == "quarter":
        first = date(anchor.year, (anchor.month - 1) // 3 * 3 + 1, 1)
        return first, add_months(first, 3)
    first = date(anchor.year, 1, 1)
    return first, date(anchor.year + 1, 1, 1)


def shifted(scale: str, start: date, step: int) -> tuple[date, date]:
    """Окно, сдвинутое на один столбец: день, неделю или месяц. Длина окна постоянна,
    сдвинутое окно месяца и квартала начинается с понедельника — крайние недели полные."""
    if scale == "week":
        new = start + timedelta(days=step)
        return new, new + timedelta(days=DAYS)
    if scale == "year":
        new = add_months(start, step)
        return new, add_months(new, 12)
    new = monday(start) + timedelta(days=7) if step > 0 else monday(start - timedelta(days=1))
    return new, new + timedelta(weeks=SHIFT_WEEKS[scale])


def columns(scale: str, start: date, end: date) -> list[date]:
    """Начала столбцов окна: дни, понедельники или первые числа (первый столбец — start)."""
    out = [start]
    day = start + timedelta(days=1)
    while day < end:
        if (scale == "week" or (scale in SHIFT_WEEKS and day.weekday() == 0)
                or (scale == "year" and day.day == 1)):
            out.append(day)
        day += timedelta(days=1)
    return out


def window(start: date, end: date | None = None) -> tuple[datetime, datetime]:
    lo = datetime.combine(start, time())
    return lo, datetime.combine(end, time()) if end else lo + timedelta(days=DAYS)


def collect(sheets: list[Node], start: date, end: date | None = None) -> list[Node]:
    """Пункты, чей срок задевает окно; порядок как на канбане."""
    lo, hi = window(start, end)
    out = [n for root in sheets for n in root.walk()
           if n.period is not None and n.period.first() < hi and n.period.last() >= lo]
    out.sort(key=lambda n: (n.priority or NO_PRIORITY, n.period.first(), n.period.last()))
    return out


def milestone(node: Node) -> bool:
    return node.period.days == 1 and node.priority is not None and node.priority <= MILESTONE_PRIORITY


def split_short(nodes: list[Node]) -> tuple[list[Node], list[date]]:
    """Крупный масштаб: однодневные задачи, кроме вех, не рисуются — остаются их дни."""
    kept, hidden = [], []
    for n in nodes:
        if n.period.days == 1 and not milestone(n):
            hidden.append(n.period.first().date())
        else:
            kept.append(n)
    return kept, hidden


def days_of(node: Node, start: date, total: int = DAYS) -> tuple[int, int]:
    """Дни задачи от начала окна: первый и последний, обрезанные краями окна."""
    a = (node.period.first().date() - start).days
    b = (node.period.last().date() - start).days
    return max(0, a), min(total - 1, b)


def bar_text(node: Node, start: date | None = None) -> str:
    """Подпись полосы: статус, приоритет, время начала (на неделе, если оно в окне),
    название и значки заметки и критериев."""
    text = MARK.get(node.status, "")
    if node.priority is not None:
        text += PRIORITY_BARS[node.priority] + " "
    p = node.period.start
    if start is not None and p.precision == 3 and p.first().date() >= start:
        text += f"{p.hour:02d}:{p.minute or 0:02d} "
    text += node.title or "(без названия)"
    label = frame_label(node, with_counter=False)
    return f"{text} {label}" if label else text


def fit(text: str, width: int) -> str:
    """Обрезать до width клеток, отрезанное заменить на «…»."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    return _cut(text, width - 1)[0] + "…"


class GraphView(Widget, inherit_bindings=False):
    DEFAULT_CSS = f"""
    GraphView {{
        background: {BACKGROUND};
    }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.scale = "week"
        self.start: date | None = None   # первый день окна; None — период, где сегодня
        self.end: date | None = None     # день после окна
        self.index = 0
        self.scroll = 0
        self.cards: list[Node] = []
        self.sheets: list[Node] = []
        self.with_tab = False
        self.now = datetime.now()
        self._tops: list[Node] = []
        self._kids: dict[int, list[Node]] = {}
        self._rows: list[list[Item]] = []
        self._ranges: list[tuple[int, int]] = []
        self._order: list[Node] = []
        self._chosen: Node | None = None
        self._want: Node | None = None   # за какой задачей перейти при следующей отрисовке
        self._lost: Node | None = None   # выбранная до «-» задача, которую крупный масштаб скрыл
        self._cols: list[date] = []
        self._guides: set[int] = set()    # где рисовать границы столбцов
        self._hidden: list[int] = []      # однодневных задач в столбце (крупный масштаб)
        self._day_w = 0                   # ширина дня на неделе
        self._width = 0                   # ширина всех столбцов в клетках

    @property
    def long(self) -> bool:
        return self.scale != "week"

    @property
    def total(self) -> int:
        return (self.end - self.start).days

    # ---------- данные и выбор ----------

    def current(self) -> Node | None:
        if not self.cards:
            return None
        return self.cards[min(self.index, len(self.cards) - 1)]

    def load(self, sheets: list[Node], now: datetime, with_tab: bool, follow: Node | None = None) -> None:
        """Пересобрать график. follow — задача, за которой должен перейти выбор;
        без него выбор остаётся на той же задаче, если она ещё в окне."""
        self._want = follow or self._want or self.current()
        self.sheets, self.now, self.with_tab = sheets, now, with_tab
        if self.start is None:
            self.start, self.end = bounds(self.scale, now.date())
        start, total = self.start, self.total
        nodes = collect(sheets, start, self.end)
        self._cols = columns(self.scale, start, self.end)
        self._hidden = [0] * len(self._cols)
        if self.long:
            nodes, hidden = split_short(nodes)
            for day in hidden:
                self._hidden[max(0, bisect_right(self._cols, day) - 1)] += 1
        self._tops, self._kids = nest(nodes, lambda n: days_of(n, start, total))
        self._draw()

    def shift(self, step: int | None) -> None:
        """Сдвинуть окно на step столбцов; None — вернуть к периоду, где сегодня."""
        if step is None:
            self.start, self.end = bounds(self.scale, self.now.date())
        else:
            self.start, self.end = shifted(self.scale, self.start, step)
        self.load(self.sheets, self.now, self.with_tab, self.current())

    def zoom(self, delta: int) -> bool:
        """Сменить масштаб; окно — вокруг сегодня, если оно видно, иначе вокруг начала окна."""
        i = max(0, min(len(SCALES) - 1, SCALES.index(self.scale) + delta))
        if SCALES[i] == self.scale:
            return False
        today = self.now.date()
        anchor = today if self.start is None or self.start <= today < self.end else self.start
        self.scale = SCALES[i]
        self.start, self.end = bounds(self.scale, anchor)
        # Однодневная задача на месяце не видна: при возврате к неделе выбор снова на ней.
        follow = self._lost or self.current()
        self.load(self.sheets, self.now, self.with_tab, follow)
        self._lost = follow if follow is not None and follow not in self.cards else None
        return True

    def move_card(self, delta: int) -> None:
        self._lost = None
        if self.cards:
            self.index = max(0, min(len(self.cards) - 1, self.index + delta))
            self._want = None
            self._draw()

    def jump(self, last: bool) -> None:
        self._lost = None
        self.index = max(0, len(self.cards) - 1) if last else 0
        self._want = None
        self._draw()

    # ---------- рисование ----------

    def on_resize(self) -> None:
        self._want = self._want or self.current()
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

    def _x(self, day: int) -> int:
        """Столбец экрана, с которого начинается день day окна."""
        if not self.long:
            return day * self._day_w
        return day * self._width // self.total

    def _col_xs(self) -> list[int]:
        return [self._x((c - self.start).days) for c in self._cols]

    def _style(self, node: Node, selected: bool, lit: bool) -> Style:
        """lit — задача лежит внутри выбранной: подсветка общая, а выбрана только внешняя."""
        style = box_style(st.classify(node, self.now), selected)
        return style + Style(bgcolor=SELECTED_BG) if lit else style

    def _fill(self, x0: int, x1: int, bg: str | None) -> Item:
        """Пустое место от x0 до x1 включительно: границы столбцов пунктиром."""
        text = "".join(GUIDE if x in self._guides else " " for x in range(x0, x1 + 1))
        return x0, text, LINE_STYLE + Style(bgcolor=bg)

    def _span(self, node: Node, cx0: int, cx1: int) -> tuple[int, int]:
        a, b = days_of(node, self.start, self.total)
        x0, x1 = self._x(a), max(self._x(a), self._x(b + 1) - 1)
        return max(cx0, x0), max(max(cx0, x0), min(cx1, x1))

    def _beyond(self, node: Node) -> tuple[bool, bool]:
        """Срок начинается раньше окна / кончается позже него."""
        return node.period.first().date() < self.start, node.period.last().date() >= self.end

    def _enter(self, node: Node) -> int:
        pos = len(self._ranges)
        self._ranges.append((0, 0))
        self._order.append(node)
        return pos

    def _wrap_inside(self, begin: int, x0: int, x1: int, side: str, style: Style) -> None:
        """Строки вложенных начиная с begin — в боковые стенки родителя."""
        bg = style.bgcolor.name if style.bgcolor else None
        for row in self._rows[begin:]:
            row[0:0] = [(x0, side, style), self._fill(x0 + 1, x1 - 1, bg), (x1, side, style)]

    def _place(self, nodes: list[Node], cx0: int, cx1: int, lit: bool = False) -> None:
        """Задачи друг под другом в пределах столбцов cx0…cx1: каждая — полоса в одну строку,
        родитель с вложенными — рамка на свои дни. Рамка уже FRAME_MIN — вложенные под ней."""
        rows = self._rows
        for node in nodes:
            pos = self._enter(node)
            selected = node is self._chosen
            style = self._style(node, selected, lit)
            x0, x1 = self._span(node, cx0, cx1)
            kids = self._kids.get(id(node), [])
            first = len(rows)
            if kids and x1 - x0 + 1 >= FRAME_MIN:
                rows.append([(x0, self._frame_top(node, x0, x1, selected), style)])
                self._place(kids, x0 + 1, x1 - 1, lit or selected)
                self._wrap_inside(first + 1, x0, x1, "║" if selected else "│", style)
                bl, h, br = "╚═╝" if selected else "╰─╯"
                rows.append([(x0, bl + h * (x1 - x0 - 1) + br, style)])
                self._ranges[pos] = (first, len(rows))
            else:
                rows.append(self._bar(node, x0, x1, cx0, cx1, style, selected or lit))
                self._ranges[pos] = (first, len(rows))
                if kids:
                    self._place(kids, cx0, cx1, lit or selected)

    def _text(self, node: Node) -> str:
        return bar_text(node, None if self.long else self.start)

    def _frame_top(self, node: Node, x0: int, x1: int, selected: bool) -> str:
        tl, tr, h = "╔╗═" if selected else "╭╮─"
        inner = x1 - x0 - 1
        name = fit(f" {self._text(node)} ", inner)
        before, after = self._beyond(node)
        return ("‹" if before else tl) + name + h * (inner - cell_len(name)) + ("›" if after else tr)

    def _bar(self, node: Node, x0: int, x1: int, cx0: int, cx1: int, style: Style, lit: bool) -> list[Item]:
        """Строка полосы: подсветка строки, сама полоса и название на ней, справа или слева."""
        row: list[Item] = []
        if lit:
            row.append(self._fill(cx0, cx1, SELECTED_BG))
        text, w = self._text(node), x1 - x0 + 1
        tw = cell_len(text)
        if not self.long and node.period.days == 1:
            # Неделя: дело на день — надпись с начала своего дня, без полосы. Длинная идёт
            # вправо, у края обрезается: сдвинутая влево читалась бы как другой день.
            row.append((x0, " " + fit(text, cx1 - x0), style))   # пробел закрывает границу дня
            return row
        if self.long and node.period.days == 1:      # веха: ромб в свой день
            row.append((x0, MILESTONE, style))
            x1 = x0
        else:
            before, after = self._beyond(node)
            line = "━" * w if w < 2 else "╺" + "━" * (w - 2) + "╸"
            if before:
                line = "‹" + line[1:]
            if after:
                line = line[:-1] + "›"
            row.append((x0, line, style))
            if w >= tw + 4:                          # название на полосе
                row.append((x0 + 1, f" {text} ", style))
                return row
        right, left = cx1 - (x1 + 2) + 1, (x0 - 2) - cx0 + 1
        need = min(tw, NAME_MIN)
        if right >= need:                            # справа от полосы (пробел закрывает границу)
            row.append((x1 + 1, " " + fit(text, right), style))
        elif left >= need:                           # слева, у правого края
            name = fit(text, left) + " "
            row.append((x0 - cell_len(name), name, style))
        else:                                        # места нет — поверх полосы
            row.append((x0 + 1, fit(f" {text} ", cx1 - x0), style))
        return row

    def _draw(self) -> None:
        width = self.size.width
        if not width or self.start is None:
            return
        self._day_w = max(6, width // DAYS)
        self._width = DAYS * self._day_w if not self.long else width
        self._guides = set(self._col_xs()[1:])
        # Порядок выбора — порядок на экране, а он зависит от ширины: сначала раскладка
        # без выбора, затем выбранная задача и окончательная отрисовка.
        self._layout(None)
        order = self._order
        want = next((n for n in order if n is self._want), None)
        self._want = None
        if want is not None:
            self.index = order.index(want)
        self.index = max(0, min(self.index, len(order) - 1))
        self._layout(order[self.index] if order else None)
        self.cards = self._order
        self._reveal()
        self.refresh()

    def _layout(self, chosen: Node | None) -> None:
        self._rows, self._ranges, self._order, self._chosen = [], [], [], chosen
        if self._tops:
            self._place(self._tops, 0, self._width - 1)

    def _reveal(self) -> None:
        body = max(1, self.size.height - 2)
        if not self._ranges:
            self.scroll = 0
            return
        top, bottom = self._ranges[self.index]
        if bottom > self.scroll + body:
            self.scroll = bottom - body
        if top < self.scroll:
            self.scroll = top

    def _label(self, day: date, first: bool, room: int) -> str:
        if self.scale == "week":
            return f" {WEEKDAYS[day.weekday()]} {day:%d.%m}"
        if self.scale == "year":
            name = MONTHS[day.month - 1]
            full = f" {name} {day:%y}"        # год — у первого столбца и у января
            return full if (first or day.month == 1) and cell_len(full) <= room else f" {name}"
        return f" {day:%d.%m}"

    def _head(self) -> list[Item]:
        today = self.now.date()
        xs = self._col_xs() + [self._width]
        out: list[Item] = []
        for i, day in enumerate(self._cols):
            room = xs[i + 1] - xs[i]
            text = self._label(day, i == 0, room)
            if self.long and cell_len(text) > room:
                text = ""                         # неполная неделя у края: дату не резать
            text = _cut(text, room)[0]
            nxt = self._cols[i + 1] if i + 1 < len(self._cols) else self.end
            style = HEAD_ACTIVE if day <= today < nxt else DIM if nxt <= today else HEAD
            out.append((xs[i], text, style))
        return out

    def _rule(self, width: int) -> list[Item]:
        """Черта под заголовком; на крупном масштабе в ней число однодневных задач столбца."""
        out: list[Item] = [(0, "─" * width, LINE_STYLE)]
        xs = self._col_xs() + [self._width]
        for i, n in enumerate(self._hidden):
            text = f" {n} "
            room = xs[i + 1] - xs[i]
            if n and cell_len(text) <= room:
                out.append((xs[i] + (room - cell_len(text)) // 2, text, HEAD))
        return out

    def _paint(self, items: list[Item], width: int) -> list[Segment]:
        """Наложить окошки по порядку на пустую строку с границами столбцов."""
        cells: list[tuple[str, Style | None]] = [(" ", None)] * width
        for x in self._guides:
            if 0 <= x < width:
                cells[x] = (GUIDE, LINE_STYLE)
        for x, text, style in items:
            for ch in text:
                w = cell_len(ch)
                if x + w > width:
                    break
                if x >= 0:
                    cells[x] = (ch, style)
                    if w == 2:
                        cells[x + 1] = ("", style)
                x += w
        segments: list[Segment] = []
        run, run_style = "", None
        for ch, style in cells:
            if style != run_style and run:
                segments.append(Segment(run, run_style))
                run = ""
            run_style = style
            run += ch
        if run:
            segments.append(Segment(run, run_style))
        return segments

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        base = self.rich_style
        if not self._day_w or self.start is None:
            return Strip.blank(width, base)
        if y == 0:
            items = self._head()
        elif y == 1:
            items = self._rule(width)
        elif not self._rows:
            items = [(1, "Нет задач на эти дни · h l — листать, 0 — сегодня, - + — период", DIM)] if y == 2 else []
        else:
            idx = y - 2 + self.scroll
            items = self._rows[idx] if idx < len(self._rows) else []
        return Strip(self._paint(items, width)).adjust_cell_length(width).apply_style(base)
