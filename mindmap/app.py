"""Приложение: вкладки, клавиши, правка карты, отмена, сохранение."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from rich.cells import cell_len
from rich.text import Text
from textual.app import App, ComposeResult
from textual.screen import ModalScreen, Screen
from textual.widgets import Static

from . import criteria, links, notes, system
from . import status as st
from .board import KanbanView, cut_left
from .canvas import BACKGROUND, COLORS, MapView
from .dialogs import (CommandLine, ConfirmDialog, CriteriaDialog, DateDialog, HelpScreen, LinkDialog,
                      LinkListDialog, NoteDialog, TextDialog)
from .graph import SCALE_NAMES, GraphView
from .keys import BOARD_KEYS, GRAPH_KEYS, MAP_KEYS, SELECT_KEYS, Chord, normalize, to_latin
from .layout import Box, visible_children
from .mdformat import dump, item_lines, parse, split_priority
from .model import DONE, FAILED, TODO, Document, DoneStub, Node, done_hidden, finished

UNDO_LIMIT = 100
HINTS = {
    "map": "  ? справка  v канбан",
    "board": "  ? справка  v график",
    "graph": "  ? справка  -+ период",
}
VIEWS = ["map", "board", "graph"]
# Space по кругу: нет статуса → не завершено → завершено → провалено → не завершено
NEXT_STATUS = {None: TODO, TODO: DONE, DONE: FAILED, FAILED: TODO}  # v переключает по кругу
# На окошке «…» нечего править: только движение, свёртывание, виды и выход.
STUB_ACTIONS = {
    "go_left", "go_right", "go_down", "go_up", "go_first", "go_last", "go_root", "center",
    "fold_toggle", "fold_close", "fold_open", "fold_all", "unfold_all", "undo", "redo",
    "tab_next", "tab_prev", "toggle_view", "help", "command", "save_quit",
    "mark_left", "mark_right", "mark_down", "mark_up", "mark_copy", "mark_cut",
}
STUB_MESSAGE = "Здесь спрятаны завершённые: za — показать"


def pbcopy(text: str) -> None:
    """Положить текст в системный буфер обмена (macOS — pbcopy, Linux — wl-copy/xclip/xsel)."""
    system.copy_text(text)


def open_url(target: str) -> None:
    """Открыть адрес или файл в программе по умолчанию (macOS — open, Linux — xdg-open)."""
    system.open_target(target)


class MainScreen(Screen):
    CSS = f"""
    MainScreen {{ background: {BACKGROUND}; }}
    #tabs, #info, #hints {{ height: 1; background: #1b1e25; color: #d8dce3; }}
    #map, #board, #graph {{ height: 1fr; }}
    """

    def compose(self) -> ComposeResult:
        yield Static(id="tabs")
        yield MapView(id="map")
        yield KanbanView(id="board")
        yield GraphView(id="graph")
        yield Static(id="info")
        yield Static(id="hints")

    def on_mount(self) -> None:
        self.app.first_paint()

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        self.app.handle_key(event)


class MindmapApp(App):
    TITLE = "mindmap"
    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = ""
    ALLOW_SELECT = False

    def __init__(self, path: Path, now: Callable[[], datetime] = datetime.now) -> None:
        super().__init__()
        self.path = path
        self.now_fn = now
        self.mode = "map"
        self.tab = 0
        self.selected: dict[int, Node] = {}
        self.chord = Chord()
        self.register: list[Node] = []
        self.marks: list[Node] | None = None  # None — режим выделения выключен
        self.undo_stack: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.board_all = False
        # Родители, у которых завершённые показаны (только на сеанс), и их окошки «…».
        self.shown_done: dict[int, Node] = {}
        self.stubs: dict[int, DoneStub] = {}
        self.message = ""
        self.save_failed = False
        self.doc = self._read()
        self.text = dump(self.doc)
        self.stamp = self._stat()

    # ---------- файл ----------

    def _default_title(self) -> str:
        return self.path.stem or "Карта"

    def _read(self) -> Document:
        if not self.path.exists():
            return parse("", self._default_title())
        return parse(self.path.read_text(encoding="utf-8"), self._default_title())

    def _stat(self) -> tuple[int, int] | None:
        try:
            s = self.path.stat()
        except OSError:
            return None
        return s.st_mtime_ns, s.st_size

    def _save(self) -> None:
        """Запись атомарно: файл либо старый целиком, либо новый целиком."""
        self.text = dump(self.doc)
        try:
            disk = self._stat()
            if disk is not None and disk != self.stamp:
                # Файл поменяли извне, пока было открыто окно: чужую версию не теряем.
                backup = self.path.with_name(f"{self.path.name}.conflict-{datetime.now():%Y%m%d-%H%M%S}")
                shutil.copy2(self.path, backup)
                self.message = f"Файл менялся извне, его версия сохранена: {backup.name}"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".{self.path.name}.tmp")
            tmp.write_text(self.text, encoding="utf-8")
            os.replace(tmp, self.path)
            self.stamp = self._stat()
            self.save_failed = False
        except OSError as err:
            self.save_failed = True
            self.message = f"Не удалось сохранить: {err}"

    def _check_external(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        stamp = self._stat()
        if stamp is None or stamp == self.stamp:
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        self.stamp = stamp
        if text == self.text:
            return
        self._push_undo()
        snapshot = (text, self.tab, self.sel.path())
        self._restore(snapshot, save=False)
        self.message = "Файл изменился извне, карта перечитана (u — вернуть)"
        self.update_bars()

    # ---------- жизненный цикл ----------

    def on_mount(self) -> None:
        self.push_screen(MainScreen())
        self.set_interval(60, self._tick)
        self.set_interval(2, self._check_external)

    def first_paint(self) -> None:
        self.query_board().display = False
        self.query_graph().display = False
        self.refresh_view()

    def _tick(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.refresh_view(reveal=False)

    def query_map(self) -> MapView:
        return self.screen_stack[1].query_one("#map", MapView)

    def query_board(self) -> KanbanView:
        return self.screen_stack[1].query_one("#board", KanbanView)

    def query_graph(self) -> GraphView:
        return self.screen_stack[1].query_one("#graph", GraphView)

    @property
    def now(self) -> datetime:
        return self.now_fn()

    @property
    def root(self) -> Node:
        return self.doc.sheets[self.tab]

    @property
    def sel(self) -> Node:
        return self.selected.get(id(self.root)) or self.root

    def select(self, node: Node) -> None:
        self.selected[id(node.root())] = node

    def _stub(self, host: Node) -> DoneStub:
        stub = self.stubs.get(id(host))
        if stub is None or stub.host is not host:
            stub = self.stubs[id(host)] = DoneStub(host)
        return stub

    def _hidden(self, node: Node) -> bool:
        """Пункт не виден на карте: в свёрнутой ветке или за «…»."""
        return any(a.collapsed for a in node.ancestors()) or done_hidden(node, self.shown_done)

    def _fix_selection(self) -> None:
        """Выбранный пункт не должен прятаться в свёрнутой ветке или за «…»:
        выбор встаёт на самое верхнее, что его прячет."""
        node = self.sel
        if isinstance(node, DoneStub):
            host = node.host
            if host.root() is not self.root or not any(finished(c) for c in host.children):
                node = host
        start = node.host if isinstance(node, DoneStub) else node
        visible = node
        chain = [start] + start.ancestors()
        for n in chain:
            if n.collapsed and (n is not start or isinstance(node, DoneStub)):
                visible = n
            if finished(n) and n.parent is not None and id(n.parent) not in self.shown_done:
                visible = self._stub(n.parent)
        if visible is not self.sel:
            self.select(visible)

    # ---------- отрисовка ----------

    def refresh_view(self, reveal: bool = True, follow: Node | None = None) -> None:
        if self.mode == "map":
            self._fix_selection()
            if self.marks:
                # Невидимое не должно меняться следующей командой.
                self.marks = [m for m in self.marks if not self._hidden(m)] or None
            self.query_map().show(self.root, self.sel, self.now, reveal, self.marks or (),
                                  self.shown_done, self.stubs)
        else:
            sheets = self.doc.sheets if self.board_all else [self.root]
            view = self.query_board() if self.mode == "board" else self.query_graph()
            view.load(sheets, self.now, self.board_all, follow)
        self.update_bars()

    def update_bars(self) -> None:
        screen = self.screen_stack[1]
        width = max(10, self.size.width)
        screen.query_one("#tabs", Static).update(self._tabs_text(width))
        info = Text(no_wrap=True, overflow="ellipsis")
        if self.message:
            info.append(" " + self.message, style="#ff9f1c")
        elif self.marks is not None:
            info.append(f" Выделено: {len(self.marks)} · Space S t 1-4 za gl dd y · Esc", style="#ff9f1c")
        else:
            node = self.current_node()
            if node is not None:
                names = [a.title for a in reversed(node.ancestors())] + [node.title]
                info.append(" " + cut_left(" › ".join(names), width - 2))
        screen.query_one("#info", Static).update(info)
        hints = Text(no_wrap=True, overflow="ellipsis")
        for label, kind in (("просрочено", st.RED), ("эта неделя", st.ORANGE), ("след.", st.GREEN),
                            ("завершено", st.GREY), ("провалено", st.DARK_RED)):
            hints.append(" ■ ", style=COLORS[kind])
            hints.append(label, style=COLORS[kind])
        hints.append(HINTS[self.mode], style="#8b93a1")
        screen.query_one("#hints", Static).update(hints)

    def _tabs_text(self, width: int) -> Text:
        mode = {"map": "карта", "board": "канбан", "graph": "график"}[self.mode]
        if self.mode == "graph":
            mode += " · " + SCALE_NAMES[self.query_graph().scale]
        if self.mode != "map" and self.board_all:
            mode += " · все вкладки"
        right = f" {mode} "
        names = [" " + (s.title or "(без названия)") + " " for s in self.doc.sheets]
        room = width - cell_len(right) - 1
        start = 0
        # Если вкладки не влезают — убираем слева, пока активная не окажется на экране.
        while start < self.tab and sum(cell_len(n) + 1 for n in names[start: self.tab + 1]) > room:
            start += 1
        text = Text(no_wrap=True, overflow="ellipsis")
        used = 0
        if start:
            text.append("‹")
            used += 1
        for i in range(start, len(names)):
            if used + cell_len(names[i]) > room and i != self.tab:
                break
            text.append(names[i], style="bold reverse" if i == self.tab else "#8b93a1")
            text.append(" ")
            used += cell_len(names[i]) + 1
        text.append(" " * max(0, width - used - cell_len(right)))
        text.append(right, style="#8b93a1")
        return text

    # ---------- клавиши ----------

    def handle_key(self, event) -> None:
        if self.screen_stack[-1] is not self.screen_stack[1]:
            return
        key = normalize(event.key, event.character)
        if self.marks is not None:
            table = SELECT_KEYS
        else:
            table = {"map": MAP_KEYS, "board": BOARD_KEYS, "graph": GRAPH_KEYS}[self.mode]
        action = self.chord.feed(key, table)
        self.message = ""
        if key == "escape" and self.marks is not None:
            self.marks = None
            self.refresh_view(reveal=False)
        if action and self.mode == "map" and isinstance(self.sel, DoneStub) and action not in STUB_ACTIONS:
            self.message = STUB_MESSAGE
        elif action:
            getattr(self, "do_" + action)()
        self.update_bars()

    def current_node(self) -> Node | None:
        if self.mode == "map":
            return self.sel
        return (self.query_board() if self.mode == "board" else self.query_graph()).current()

    def _targets(self) -> list[Node]:
        """На что действует команда: всё выделенное либо текущий пункт."""
        if self.marks is not None:
            return list(self.marks)
        node = self.current_node()
        return [node] if node is not None else []

    # ---------- правка с отменой ----------

    def _push_undo(self) -> None:
        self.undo_stack.append((self.text, self.tab, self.sel.path()))
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def _changed(self, follow: Node | None = None) -> None:
        self._save()
        self.refresh_view(follow=follow)

    def _restore(self, snapshot: tuple, save: bool = True) -> None:
        text, tab, path = snapshot
        self.marks = None  # старые пункты больше не существуют
        # Показанные завершённые переносим по месту пункта: сами пункты будут новыми.
        sheets = {id(r): i for i, r in enumerate(self.doc.sheets)}
        shown = [(sheets[id(n.root())], n.path()) for n in self.shown_done.values() if id(n.root()) in sheets]
        self.doc = parse(text, self._default_title())
        self.shown_done, self.stubs = {}, {}
        for i, where in shown:
            if i < len(self.doc.sheets):
                node = self.doc.sheets[i].follow(where)
                if node.path() == where:
                    self.shown_done[id(node)] = node
        self.tab = min(tab, len(self.doc.sheets) - 1)
        self.selected = {}
        self.select(self.root.follow(path))
        if save:
            self._save()
        else:
            self.text = dump(self.doc)
        self.refresh_view()

    def do_undo(self) -> None:
        if not self.undo_stack:
            self.message = "Отменять нечего"
            return
        self.redo_stack.append((self.text, self.tab, self.sel.path()))
        self._restore(self.undo_stack.pop())

    def do_redo(self) -> None:
        if not self.redo_stack:
            self.message = "Повторять нечего"
            return
        self.undo_stack.append((self.text, self.tab, self.sel.path()))
        self._restore(self.redo_stack.pop())

    # ---------- перемещение по карте ----------

    def _box(self) -> Box:
        return self.query_map().current

    def _go(self, node: Node) -> None:
        self.select(node)
        self.refresh_view()

    def do_go_left(self) -> None:
        if self.sel.parent is not None:
            self._go(self.sel.parent)

    def do_go_right(self) -> None:
        node = self.sel
        if not node.children:
            return
        if node.collapsed:
            node.collapsed = False
            self._save()
        self._go(visible_children(node, self.shown_done, self.stubs)[0])

    def _vertical(self, step: int) -> None:
        tree = self.query_map().plan
        box = self._box()
        column = tree.by_depth[box.depth]
        i = column.index(box) + step
        if 0 <= i < len(column):
            self._go(column[i].node)
            return
        # В своём столбце дальше никого: берём ближайшее окошко в этом направлении.
        if step > 0:
            options = [b for b in tree.boxes if b.y > box.y]
            near = lambda b: (abs(b.x - box.x), b.y)
        else:
            options = [b for b in tree.boxes if b.y < box.y]
            near = lambda b: (abs(b.x - box.x), -b.y)
        if options:
            self._go(min(options, key=near).node)

    def do_go_down(self) -> None:
        self._vertical(1)

    def do_go_up(self) -> None:
        self._vertical(-1)

    def do_go_first(self) -> None:
        self._go(self.query_map().plan.by_depth[self._box().depth][0].node)

    def do_go_last(self) -> None:
        self._go(self.query_map().plan.by_depth[self._box().depth][-1].node)

    def do_go_root(self) -> None:
        self._go(self.root)

    def do_center(self) -> None:
        self.query_map().reveal_current(center=True)

    # ---------- новые пункты и названия ----------

    def _ask_title(self, title: str, value: str, done: Callable[[str], None]) -> None:
        def back(text: str | None) -> None:
            if text:
                done(text)
        self.push_screen(TextDialog(title, value), back)

    def _insert(self, parent: Node, index: int | None) -> None:
        def done(text: str) -> None:
            self._push_undo()
            priority, title = split_priority(text)
            node = parent.add(Node(title, priority=priority), index)
            parent.collapsed = False
            self.select(node)
            self._changed()
        self._ask_title("Новый пункт", "", done)

    def do_new_below(self) -> None:
        node = self.sel
        if node.parent is None:
            self._insert(node, None)
        else:
            self._insert(node.parent, node.index + 1)

    def do_new_above(self) -> None:
        node = self.sel
        if node.parent is None:
            self._insert(node, 0)
        else:
            self._insert(node.parent, node.index)

    def do_new_child(self) -> None:
        self._insert(self.sel, None)

    def do_rename(self) -> None:
        node = self.current_node()
        if node is None:
            return
        def done(text: str) -> None:
            priority, title = split_priority(text)
            title = title or node.title
            priority = node.priority if priority is None else priority
            if title == node.title and priority == node.priority:
                return
            self._push_undo()
            old = node.title
            node.title, node.priority = title, priority
            # Ссылки ведут по названию; если такое название есть ещё где-то, цель неоднозначна.
            if title != old and not links.items_named(self.doc.sheets, old):
                links.rename_target(self.doc.sheets, old, title)
            self._changed()
        self._ask_title("Название", node.title, done)

    # ---------- статус, сроки, приоритет ----------

    def _set_status(self, value: str | None) -> None:
        changed = [n for n in self._targets() if n.status != value]
        if changed:
            self._push_undo()
            for node in changed:
                node.status = value
            self._changed()

    def do_toggle_status(self) -> None:
        # На выделении итог один для всех: следующий статус пункта под курсором.
        cursor = self.current_node()
        if cursor is not None:
            value = NEXT_STATUS[cursor.status]
            targets = self._targets()
            self._set_status(value)
            if value in (DONE, FAILED):
                self._after_close(cursor, targets)

    def _after_close(self, cursor: Node, targets: list[Node]) -> None:
        """Закрытую задачу оценивают по её критериям (Фридман: результат всегда разбираем)."""
        if self.mode == "board":
            # С доски закрытая карточка уходит: gk попал бы в соседнюю, поэтому окно сразу.
            if criteria.unrated(cursor):
                self._open_criteria(cursor)
            else:
                self.message = f"Завершено: {cursor.title} · u — вернуть"
            return
        if any(criteria.unrated(n) for n in targets):
            self.message = "Оцените критерии и разбор: gk"
            if self.mode == "map" and self.marks is None and cursor.parent is not None:
                # Иначе задача ушла бы за «…» и gk было бы не на чем нажать.
                self.shown_done[id(cursor.parent)] = cursor.parent
                self.select(cursor)
                self.refresh_view()

    def do_clear_status(self) -> None:
        self._set_status(None)

    def _targets_title(self, nodes: list[Node]) -> str:
        return nodes[0].title if len(nodes) == 1 else f"выделено пунктов: {len(nodes)}"

    def _ask_date(self, nodes: list[Node], value: str, follow: bool = False) -> None:
        def back(result: tuple | None) -> None:
            if result is None:
                return
            changed = [n for n in nodes if n.period != result[0]]
            if changed:
                self._push_undo()
                for node in changed:
                    node.period = result[0]
                self._changed(follow=nodes[0] if follow else None)
        self.push_screen(DateDialog(self._targets_title(nodes), value, self.now), back)

    def do_edit_date(self) -> None:
        nodes = self._targets()
        if nodes:
            periods = {n.period for n in nodes}
            common = periods.pop() if len(periods) == 1 else None
            self._ask_date(nodes, common.show() if common else "")

    def _set_priority(self, level: int) -> None:
        cursor = self.current_node()
        if cursor is None:
            return
        value = None if cursor.priority == level else level
        changed = [n for n in self._targets() if n.priority != value]
        if changed:
            self._push_undo()
            for node in changed:
                node.priority = value
            self._changed(follow=cursor)

    def do_priority_1(self) -> None:
        self._set_priority(1)

    def do_priority_2(self) -> None:
        self._set_priority(2)

    def do_priority_3(self) -> None:
        self._set_priority(3)

    def do_priority_4(self) -> None:
        self._set_priority(4)

    # ---------- заметки ----------

    def do_edit_note(self) -> None:
        node = self.current_node()
        if node is None:
            return
        def back(text: str | None) -> None:
            if text is None:
                return
            lines = notes.lines_for(node, text)
            if lines != node.notes:
                self._push_undo()
                node.notes = lines
                self._changed(follow=node)
                self.update_bars()
        self.push_screen(NoteDialog(node.title, notes.text(node)), back)

    # ---------- критерии успеха ----------

    def do_criteria(self) -> None:
        node = self.current_node()
        if node is not None:
            self._open_criteria(node)

    def _open_criteria(self, node: Node) -> None:
        before = (criteria.read(node), criteria.review(node))
        def back(result: tuple) -> None:
            items, review = result
            if (items, review) == before:
                return
            self._push_undo()
            node.notes = criteria.lines_for(node, items, review)
            self._changed(follow=node)
            self.update_bars()
        self.push_screen(CriteriaDialog(node.title, before[0], before[1], node.status == FAILED), back)

    # ---------- ссылки ----------

    def do_open_link(self) -> None:
        node = self.current_node()
        if node is None:
            return
        found = links.read(node)
        if not found:
            self.message = "У пункта нет ссылок (gl — добавить)"
        elif len(found) == 1:
            self._follow(found[0], node)
        else:
            self._show_links(node)

    def do_list_links(self) -> None:
        node = self.current_node()
        if node is None:
            return
        if links.read(node):
            self._show_links(node)
        else:
            self.message = "У пункта нет ссылок (gl — добавить)"

    def _show_links(self, node: Node) -> None:
        found = links.read(node)
        def back(result: tuple | None) -> None:
            if result is None:
                return
            action, i = result
            if action == "open":
                self._follow(found[i], node)
            else:
                self._push_undo()
                links.remove(node, found[i])
                self._changed(follow=node)
                if links.read(node):
                    self._show_links(node)
            self.update_bars()
        self.push_screen(LinkListDialog(node.title, found), back)

    def do_add_link(self) -> None:
        nodes = self._targets()
        cursor = self.current_node()
        if not nodes or cursor is None:
            return
        def back(link: links.Link | None) -> None:
            if link is None:
                return
            # Пункт без другого такого же названия ссылался бы сам на себя.
            fit = [n for n in nodes if link.kind != links.ITEM or links.items_named(self.doc.sheets, link.target, n)]
            fresh = [n for n in fit if link not in links.read(n)]
            if not fresh:
                self.message = "Такая ссылка уже есть"
                self.update_bars()
                return
            self._push_undo()
            for node in fresh:
                links.add(node, link)
            self._changed(follow=cursor)
        self.push_screen(LinkDialog(self._targets_title(nodes), self.doc.sheets, cursor, self.path.parent), back)

    def _follow(self, link: links.Link, node: Node) -> None:
        if link.kind == links.ITEM:
            self._follow_item(link, node)
        elif link.kind == links.WEB:
            self._launch(link.target, links.label(link))
        elif link.kind == links.FILE:
            self._open_file(link)
        else:
            self.message = f"Такой адрес программа не открывает: {link.target}"

    def _follow_item(self, link: links.Link, node: Node) -> None:
        found = links.items_named(self.doc.sheets, link.target, node)
        if not found:
            self.message = f"Пункт не найден: {link.target}"
            return
        self._reveal(found[0])
        if self.mode != "map":
            self._set_mode("map")
        else:
            self.refresh_view()
        if len(found) > 1:
            self.message = f"Пунктов с таким названием: {len(found)}, открыт первый"

    def _open_file(self, link: links.Link) -> None:
        path = links.file_path(link, self.path.parent)
        if not path.exists():
            self.message = f"Файла нет: {path}"
            return
        if not links.is_runnable(path):
            self._launch(str(path), path.name)
            return
        def back(yes: bool) -> None:
            if yes:
                self._launch(str(path), path.name)
                self.update_bars()
        self.push_screen(ConfirmDialog(f"«{path.name}» — программа или скрипт. Запустить?"), back)

    def _launch(self, target: str, name: str) -> None:
        try:
            open_url(target)
            self.message = f"Открыто: {name}"
        except (OSError, subprocess.SubprocessError):
            self.message = f"Не удалось открыть: {name}"

    # ---------- структура ----------

    def _remove(self, node: Node) -> None:
        self._push_undo()
        parent = node.parent
        i = node.index
        node.detach()
        siblings = parent.children
        self.select(siblings[min(i, len(siblings) - 1)] if siblings else parent)
        self._changed()

    def do_cut(self) -> None:
        node = self.sel
        if node.parent is None:
            self.message = "Главную тему вырезать нельзя; закрыть вкладку — :tabclose"
            return
        def go(yes: bool = True) -> None:
            if yes:
                self.register = [node.clone()]
                self._remove(node)
        if node.children:
            count = sum(1 for _ in node.walk()) - 1
            self.push_screen(ConfirmDialog(f"Вырезать «{node.title}» вместе с вложенными пунктами ({count})?"), go)
        else:
            go()

    def _tops(self, nodes: list[Node]) -> list[Node]:
        """Верхние из пунктов в порядке карты: пункт внутри другого едет с его веткой."""
        chosen = {id(n) for n in nodes}
        tops = {id(n) for n in nodes if not any(id(a) in chosen for a in n.ancestors())}
        return [n for n in nodes[0].root().walk() if id(n) in tops]

    def _copy(self, nodes: list[Node]) -> None:
        """Копировать пункты с ветками: в буфер для p и текстом в системный буфер."""
        ordered = self._tops(nodes)
        self.register = [n.clone() for n in ordered]
        text = "\n".join(item_lines(ordered)) + "\n"
        done = f"Скопировано: {len(ordered)} (p — вставить, {system.PASTE_KEY} — в другую программу)"
        try:
            pbcopy(text)
            self.message = done
        except FileNotFoundError:
            # Linux без wl-copy/xclip/xsel: буфер через сам терминал (OSC 52), если он это умеет.
            self.copy_to_clipboard(text)
            self.message = done
        except (OSError, subprocess.SubprocessError):
            self.message = f"Скопировано: {len(ordered)} для p; в системный буфер записать не удалось"

    def do_copy(self) -> None:
        self._copy([self.sel])

    def do_paste(self) -> None:
        if not self.register:
            self.message = "Буфер пуст: сначала yy, c или dd"
            return
        self._push_undo()
        target = self.sel
        pasted = [target.add(n.clone()) for n in self.register]
        target.collapsed = False
        self.select(pasted[0])
        self._changed()

    # ---------- выделение ----------

    def do_mark_start(self) -> None:
        self.marks = [self.sel]
        self.refresh_view()

    def _mark_step(self, move: Callable[[], None]) -> None:
        before = self.sel
        move()
        after = self.sel
        if after is before or isinstance(after, DoneStub):
            return
        marks = self.marks
        if len(marks) >= 2 and marks[-2] is after:
            marks.pop()                 # шаг назад снимает последнюю отметку
        elif not any(m is after for m in marks):
            marks.append(after)
        self.refresh_view()

    def do_mark_left(self) -> None:
        self._mark_step(self.do_go_left)

    def do_mark_right(self) -> None:
        self._mark_step(self.do_go_right)

    def do_mark_down(self) -> None:
        self._mark_step(self.do_go_down)

    def do_mark_up(self) -> None:
        self._mark_step(self.do_go_up)

    def do_mark_copy(self) -> None:
        marks, self.marks = self.marks, None
        self._copy(marks)
        self.refresh_view(reveal=False)

    def do_mark_cut(self) -> None:
        tops = [n for n in self.marks if n.parent is not None]
        if not tops:
            self.message = "Главную тему вырезать нельзя; закрыть вкладку — :tabclose"
            return
        tops = self._tops(tops)
        total = sum(1 for top in tops for _ in top.walk())
        def go(yes: bool) -> None:
            if not yes:
                return
            self._push_undo()
            self.register = [n.clone() for n in tops]
            parent, at = tops[0].parent, tops[0].index
            for node in tops:
                node.detach()
            siblings = parent.children
            self.select(siblings[min(at, len(siblings) - 1)] if siblings else parent)
            self.marks = None
            self._changed()
        self.push_screen(ConfirmDialog(f"Вырезать выделенное вместе с вложенными? Всего пунктов: {total}."), go)

    def _seen(self, node: Node) -> list[Node]:
        """Соседи пункта, видимые на карте: спрятанные за «…» не в счёт."""
        return [c for c in node.parent.children if not done_hidden(c, self.shown_done)]

    def _swap(self, step: int) -> None:
        node = self.sel
        if node.parent is None:
            return
        seen = self._seen(node)
        j = seen.index(node) + step
        if 0 <= j < len(seen):
            self._push_undo()
            siblings = node.parent.children
            a, b = siblings.index(node), siblings.index(seen[j])
            siblings[a], siblings[b] = siblings[b], siblings[a]
            self._changed()

    def do_move_down(self) -> None:
        self._swap(1)

    def do_move_up(self) -> None:
        self._swap(-1)

    def do_promote(self) -> None:
        node = self.sel
        parent = node.parent
        if parent is None or parent.parent is None:
            return
        self._push_undo()
        grand = parent.parent
        at = parent.index + 1
        node.detach()
        grand.add(node, at)
        self._changed()

    def do_demote(self) -> None:
        node = self.sel
        if node.parent is None:
            return
        seen = self._seen(node)
        i = seen.index(node)
        if i == 0:
            return
        self._push_undo()
        target = seen[i - 1]
        node.detach()
        target.add(node)
        target.collapsed = False
        self._changed()

    # ---------- свёртывание ----------

    def _fold(self, value: bool | None) -> None:
        if isinstance(self.sel, DoneStub):
            self._show_done(self.sel.host, None if value is None else not value)
            return
        nodes = [n for n in self._targets() if n.children]
        if not nodes:
            return
        if value is None:
            value = not (self.sel if self.sel.children else nodes[0]).collapsed
        for node in nodes:
            node.collapsed = value
        self._changed()

    def _show_done(self, host: Node, show: bool | None) -> None:
        """Показать или спрятать завершённых детей host. Только на сеанс: файл не меняется."""
        if show is None:
            show = id(host) not in self.shown_done
        if show:
            self.shown_done[id(host)] = host
        else:
            self.shown_done.pop(id(host), None)
        self.refresh_view()

    def do_fold_toggle(self) -> None:
        self._fold(None)

    def do_fold_close(self) -> None:
        self._fold(True)

    def do_fold_open(self) -> None:
        self._fold(False)

    def do_fold_all(self) -> None:
        for node in self.root.walk():
            if node.parent is not None and node.children:
                node.collapsed = True
        self._changed()

    def do_unfold_all(self) -> None:
        for node in self.root.walk():
            node.collapsed = False
        self._changed()

    # ---------- вкладки и виды ----------

    def _tab_step(self, step: int) -> None:
        self.tab = (self.tab + step) % len(self.doc.sheets)
        self.refresh_view()

    def do_tab_next(self) -> None:
        self._tab_step(1)

    def do_tab_prev(self) -> None:
        self._tab_step(-1)

    def _set_mode(self, mode: str) -> None:
        """Сменить вид. Выбор переходит за тем же пунктом, если он есть в новом виде."""
        follow = self.current_node()
        views = {"map": self.query_map(), "board": self.query_board(), "graph": self.query_graph()}
        self.mode = mode
        for name, view in views.items():
            view.display = name == mode
        if mode == "map":
            self.call_after_refresh(self.refresh_view)
            self.refresh_view()
        else:
            self.call_after_refresh(self.refresh_view, True, follow)
            self.refresh_view(follow=follow)

    def do_toggle_view(self) -> None:
        self._set_mode(VIEWS[(VIEWS.index(self.mode) + 1) % len(VIEWS)])

    def do_help(self) -> None:
        self.push_screen(HelpScreen())

    # ---------- канбан ----------

    def do_col_left(self) -> None:
        self.query_board().move_col(-1)

    def do_col_right(self) -> None:
        self.query_board().move_col(1)

    def do_card_down(self) -> None:
        self.query_board().move_card(1)

    def do_card_up(self) -> None:
        self.query_board().move_card(-1)

    def do_card_first(self) -> None:
        self.query_board().jump(False)

    def do_card_last(self) -> None:
        self.query_board().jump(True)

    def do_board_scope(self) -> None:
        self.board_all = not self.board_all
        self.refresh_view(follow=self.query_board().current())

    def _reveal(self, node: Node) -> None:
        """Сделать пункт выбранным: его вкладка, свёрнутые родители развёрнуты,
        завершённые предки показаны."""
        folded = [a for a in node.ancestors() if a.collapsed]
        for a in folded:
            a.collapsed = False
        for n in [node] + node.ancestors():
            if finished(n) and n.parent is not None:
                self.shown_done[id(n.parent)] = n.parent
        root = node.root()
        self.tab = next(i for i, s in enumerate(self.doc.sheets) if s is root)
        self.select(node)
        if folded:
            self._save()

    def do_open_on_map(self) -> None:
        node = self.current_node()
        if node is None:
            return
        self._reveal(node)
        self._set_mode("map")

    def do_card_to_right(self) -> None:
        board = self.query_board()
        node = board.current()
        if node is None:
            return
        if board.col == 0:
            sunday = st.week_bounds(self.now)[1] - timedelta(days=1)
            self._ask_date([node], sunday.strftime("%d.%m.%Y"), follow=True)
        elif board.col == 1:
            self._push_undo()
            node.status = DONE
            self._changed(follow=node)
            self._after_close(node, [node])

    def do_card_to_left(self) -> None:
        board = self.query_board()
        node = board.current()
        if node is None:
            return
        if board.col == 1:
            monday = st.week_bounds(self.now)[1]
            self._ask_date([node], monday.strftime("%d.%m.%Y"), follow=True)

    # ---------- сетевой график ----------

    def do_days_back(self) -> None:
        self.query_graph().shift(-1)

    def do_days_forward(self) -> None:
        self.query_graph().shift(1)

    def do_days_today(self) -> None:
        self.query_graph().shift(None)

    def do_zoom_out(self) -> None:
        self.query_graph().zoom(1)

    def do_zoom_in(self) -> None:
        self.query_graph().zoom(-1)

    def do_task_down(self) -> None:
        self.query_graph().move_card(1)

    def do_task_up(self) -> None:
        self.query_graph().move_card(-1)

    def do_task_first(self) -> None:
        self.query_graph().jump(False)

    def do_task_last(self) -> None:
        self.query_graph().jump(True)

    # ---------- командная строка ----------

    def do_command(self) -> None:
        def back(text: str | None) -> None:
            if text:
                self._run_command(text)
                self.update_bars()
        self.push_screen(CommandLine(), back)

    def _run_command(self, text: str) -> None:
        word, _, arg = text.strip().lstrip(":").partition(" ")
        cmd = to_latin(word)
        arg = " ".join(arg.split())
        if cmd == "q!":
            self.exit()
        elif cmd == "q":
            self.do_quit_checked()
        elif cmd == "w":
            self._save()
            if not self.save_failed:
                self.message = f"Сохранено: {self.path.name}"
        elif cmd in ("wq", "x"):
            self.do_save_quit()
        elif cmd == "tabnew":
            self._push_undo()
            root = Node(arg or "Новая вкладка")
            self.doc.sheets.insert(self.tab + 1, root)
            self.tab += 1
            self._changed()
        elif cmd == "tabclose":
            self._close_tab()
        else:
            self.message = f"Нет такой команды: {word}"

    def _close_tab(self) -> None:
        if len(self.doc.sheets) == 1:
            self.message = "Это последняя вкладка, её закрыть нельзя"
            return
        def go(yes: bool = True) -> None:
            if yes:
                self._push_undo()
                del self.doc.sheets[self.tab]
                self.tab = min(self.tab, len(self.doc.sheets) - 1)
                self._changed()
        root = self.root
        if root.children:
            self.push_screen(ConfirmDialog(f"Закрыть вкладку «{root.title}» и удалить её пункты?"), go)
        else:
            go()

    def do_quit_checked(self) -> None:
        if self.save_failed:
            self.message = "Последнее сохранение не удалось. Выйти без сохранения — :q!"
            return
        self.exit()

    def do_save_quit(self) -> None:
        self._save()
        self.do_quit_checked()
