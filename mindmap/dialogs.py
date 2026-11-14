"""Окна: название, сроки, подтверждение, справка, командная строка."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea

from . import criteria, links
from .dates import parse_input
from .keys import normalize
from .model import Node

_DIALOG_CSS = """
.dialog {
    width: 64;
    max-width: 100%;
    height: auto;
    padding: 0 1;
    border: round #ff9f1c;
    background: #1b1e25;
}
.dialog Input { border: none; height: 1; padding: 0; background: #2a2f3a; margin: 1 0; }
.dialog .title { color: #d8dce3; text-style: bold; }
.dialog .note { color: #8b93a1; }
"""


class TextDialog(ModalScreen[str | None]):
    """Ввод строки. Enter — принять, Esc — отмена."""

    CSS = "TextDialog { align: center middle; }" + _DIALOG_CSS
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, value: str = "") -> None:
        super().__init__()
        self.title_text, self.value = title, value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(self.title_text), classes="title")
            yield Input(value=self.value, select_on_focus=False)
            yield Static("Enter — сохранить, Esc — отмена", classes="note")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(" ".join(event.value.split()))

    def action_cancel(self) -> None:
        self.dismiss(None)


class NoteDialog(ModalScreen[str]):
    """Заметка пункта в несколько строк. Enter — новая строка, Esc — сохранить и закрыть:
    Esc не зависит от раскладки, а лишнее отменяет u."""

    CSS = ("NoteDialog { align: center middle; }" + _DIALOG_CSS
           + ".dialog TextArea { height: 12; border: none; padding: 0; margin: 1 0; background: #2a2f3a; }")
    AUTO_FOCUS = "TextArea"
    BINDINGS = [Binding("escape", "save", show=False, priority=True)]

    def __init__(self, title: str, value: str = "") -> None:
        super().__init__()
        self.title_text, self.value = title, value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(f"Заметка: {self.title_text}"), classes="title")
            yield TextArea(self.value, soft_wrap=True, show_line_numbers=False,
                           highlight_cursor_line=False)
            yield Static("Enter — новая строка · Esc — сохранить (u отменит)", classes="note")

    def on_mount(self) -> None:
        area = self.query_one(TextArea)
        area.move_cursor(area.document.end)

    def action_save(self) -> None:
        self.dismiss(self.query_one(TextArea).text)


class DateDialog(ModalScreen[tuple | None]):
    """Сроки: разбор на лету. Результат — (Period | None,); None — отмена."""

    CSS = "DateDialog { align: center middle; }" + _DIALOG_CSS
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", show=False)]
    HINT = "2026 · 2026-2027 · 11.2026 · 05.11 · 05-07.11\n05.11 15:20-16:00 · завтра · пт"

    def __init__(self, title: str, value: str, now: datetime) -> None:
        super().__init__()
        self.title_text, self.value, self.now = title, value, now

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(f"Сроки: {self.title_text}", no_wrap=True, overflow="ellipsis"), classes="title")
            yield Input(value=self.value, select_on_focus=True)
            yield Static("", id="preview")
            yield Static(self.HINT, classes="note")
            yield Static("Enter — сохранить, пусто — снять срок, Esc — отмена", classes="note")

    def on_mount(self) -> None:
        self._preview(self.value)

    def _preview(self, text: str) -> None:
        widget = self.query_one("#preview", Static)
        try:
            period = parse_input(text, self.now)
        except ValueError as err:
            widget.update(Text(str(err), style="#ff5c57"))
            return
        widget.update(Text(f"→ {period.show()}" if period else "→ без срока", style="#3fcf6e"))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._preview(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            self.dismiss((parse_input(event.value, self.now),))
        except ValueError:
            pass  # ошибка уже показана под полем, окно остаётся открытым

    def action_cancel(self) -> None:
        self.dismiss(None)


class LinkDialog(ModalScreen[links.Link | None]):
    """Новая ссылка: разбор на лету. Результат — Link; None — отмена."""

    CSS = "LinkDialog { align: center middle; }" + _DIALOG_CSS
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", show=False)]
    HINT = "адрес сайта · путь к файлу (файл можно перетащить сюда)\nили часть названия пункта карты"

    def __init__(self, title: str, sheets: list[Node], node: Node, base: Path) -> None:
        super().__init__()
        self.title_text, self.sheets, self.node, self.base = title, sheets, node, base

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(f"Ссылка: {self.title_text}", no_wrap=True, overflow="ellipsis"), classes="title")
            yield Input(select_on_focus=False)
            yield Static("", id="preview")
            yield Static(self.HINT, classes="note")
            yield Static("Enter — сохранить, Esc — отмена", classes="note")

    def _describe(self, link: links.Link) -> Text:
        if link.kind == links.WEB:
            return Text(f"→ сайт: {links.label(link)}", style="#3fcf6e")
        if link.kind == links.ITEM:
            return Text(f"→ пункт: {link.target}", style="#3fcf6e")
        if links.file_path(link, self.base).exists():
            return Text(f"→ файл: {links.label(link)}", style="#3fcf6e")
        return Text(f"→ файла сейчас нет: {links.label(link)}", style="#ff9f1c")

    def on_input_changed(self, event: Input.Changed) -> None:
        widget = self.query_one("#preview", Static)
        try:
            link = links.parse_input(event.value, self.sheets, self.node)
        except ValueError as err:
            widget.update(Text(str(err), style="#ff5c57"))
            return
        widget.update(self._describe(link) if link else "")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            self.dismiss(links.parse_input(event.value, self.sheets, self.node))
        except ValueError:
            pass  # ошибка уже показана под полем, окно остаётся открытым

    def action_cancel(self) -> None:
        self.dismiss(None)


class LinkListDialog(ModalScreen[tuple | None]):
    """Ссылки пункта. Результат — ("open" | "remove", номер); None — закрыто."""

    CSS = "LinkListDialog { align: center middle; }" + _DIALOG_CSS

    def __init__(self, title: str, items: list[links.Link]) -> None:
        super().__init__()
        self.title_text, self.items, self.pos = title, items, 0

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(f"Ссылки: {self.title_text}", no_wrap=True, overflow="ellipsis"), classes="title")
            yield Static("", id="list")
            yield Static("цифра или Enter — открыть · d — удалить · Esc — закрыть", classes="note")

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        text = Text(no_wrap=True, overflow="ellipsis")
        for i, link in enumerate(self.items):
            mark = "→" if link.kind == links.ITEM else "↗"
            line = f"{i + 1} {mark} {link.target}"
            text.append(line + ("\n" if i < len(self.items) - 1 else ""), style="reverse" if i == self.pos else "")
        self.query_one("#list", Static).update(text)

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        key = normalize(event.key, event.character)
        if key == "escape":
            self.dismiss(None)
        elif key in ("j", "down"):
            self.pos = min(self.pos + 1, len(self.items) - 1)
            self._draw()
        elif key in ("k", "up"):
            self.pos = max(self.pos - 1, 0)
            self._draw()
        elif key == "enter":
            self.dismiss(("open", self.pos))
        elif key == "d":
            self.dismiss(("remove", self.pos))
        elif key.isdecimal() and 1 <= int(key) <= len(self.items):
            self.dismiss(("open", int(key) - 1))


class CriterionForm(ModalScreen[tuple | None]):
    """Критерий и факт. Enter — сохранить, Tab — к другому полю, Esc — отмена."""

    CSS = "CriterionForm { align: center middle; }" + _DIALOG_CSS
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, item: criteria.Criterion | None) -> None:
        super().__init__()
        self.item = item or criteria.Criterion("")

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("Критерий успеха", classes="title")
            yield Input(value=self.item.text, placeholder="по чему судить, что задача удалась", id="text")
            yield Static("Факт (необязательно)", classes="title")
            yield Input(value=self.item.fact, placeholder="что получилось на деле", id="fact")
            yield Static("Enter — сохранить · Tab — другое поле · Esc — отмена", classes="note")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = " ".join(self.query_one("#text", Input).value.split())
        fact = " ".join(self.query_one("#fact", Input).value.split())
        self.dismiss((text, fact) if text else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# Подсказка к причине по виду итога — вопросы из конспекта Фридмана о разборе результата.
CAUSE_HINTS = {
    "закономерный успех": "за счёт чего получилось и повторится ли",
    "чудо": "что спасло в последний момент",
    "форсаж": "какие ресурсы ушли сверх плана",
    "провал": "причина внутри, а не снаружи; можно ли было повлиять",
}


class KindDialog(ModalScreen[str | None]):
    """Вид итога цифрой. Результат — вид; "" — убрать разбор; None — отмена."""

    CSS = "KindDialog { align: center middle; }" + _DIALOG_CSS

    def __init__(self, current: str) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        text = Text()
        for i, kind in enumerate(criteria.KINDS, 1):
            text.append(f"{i} {kind}" + ("\n" if i < len(criteria.KINDS) else ""),
                        style="reverse" if kind == self.current else "")
        with Vertical(classes="dialog"):
            yield Static("Разбор итога: каков результат?", classes="title")
            yield Static(text)
            hint = "цифра — выбрать · Enter — оставить · d — убрать разбор · Esc" if self.current else "цифра — выбрать · Esc — отмена"
            yield Static(hint, classes="note")

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        key = normalize(event.key, event.character)
        if key == "escape":
            self.dismiss(None)
        elif key == "enter" and self.current:
            self.dismiss(self.current)
        elif key == "d" and self.current:
            self.dismiss("")
        elif key.isdecimal() and 1 <= int(key) <= len(criteria.KINDS):
            self.dismiss(criteria.KINDS[int(key) - 1])


class ReviewForm(ModalScreen[tuple | None]):
    """Причина и что меняем. Enter — сохранить, Tab — к другому полю, Esc — отмена."""

    CSS = "ReviewForm { align: center middle; }" + _DIALOG_CSS
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, review: criteria.Review) -> None:
        super().__init__()
        self.review = review

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(f"Разбор: {self.review.kind}"), classes="title")
            yield Static("Причина", classes="note")
            yield Input(value=self.review.cause, placeholder=CAUSE_HINTS.get(self.review.kind, ""), id="cause")
            yield Static("Что меняем", classes="note")
            yield Input(value=self.review.change, placeholder="что меняем в системе управления", id="change")
            yield Static("Enter — сохранить · Tab — другое поле · Esc — отмена", classes="note")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss((" ".join(self.query_one("#cause", Input).value.split()),
                      " ".join(self.query_one("#change", Input).value.split())))

    def action_cancel(self) -> None:
        self.dismiss(None)


class CriteriaDialog(ModalScreen[tuple]):
    """Критерии успеха и разбор итога. Правится копия; Esc возвращает (критерии, разбор),
    и всё сделанное в окне ложится одним шагом отмены."""

    CSS = "CriteriaDialog { align: center middle; }" + _DIALOG_CSS

    def __init__(self, title: str, items: list[criteria.Criterion], review: criteria.Review,
                 failed: bool = False) -> None:
        super().__init__()
        self.title_text, self.items, self.review, self.failed = title, list(items), review, failed
        self.pos = 0

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(f"Критерии: {self.title_text}", no_wrap=True, overflow="ellipsis"), classes="title")
            yield Static("", id="list")
            yield Static("", id="review")
            yield Static("a добавить · Enter изменить · Space оценка · d удалить\n"
                         "J K порядок · r разбор · Esc сохранить и закрыть", classes="note")

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        text = Text(no_wrap=True, overflow="ellipsis")
        if not self.items:
            text.append("Критериев пока нет: a — добавить", style="#8b93a1")
        for i, item in enumerate(self.items):
            line = f"{i + 1} {item.show()}"
            text.append(line + ("\n" if i < len(self.items) - 1 else ""), style="reverse" if i == self.pos else "")
        self.query_one("#list", Static).update(text)
        review = Text(no_wrap=True, overflow="ellipsis")
        if self.review.kind:
            review.append(f"\nРазбор: {self.review.kind}")
            if self.review.cause:
                review.append(f"\nПричина: {self.review.cause}")
            if self.review.change:
                review.append(f"\nМеняем: {self.review.change}")
        else:
            review.append("\nРазбора нет: r — разобрать итог", style="#8b93a1")
        self.query_one("#review", Static).update(review)

    def _form(self, at: int | None) -> None:
        def back(result: tuple | None) -> None:
            if result is None:
                return
            text, fact = result
            if at is None:
                self.pos = len(self.items) and self.pos + 1
                self.items.insert(self.pos, criteria.Criterion(text, criteria.UNRATED, fact))
            else:
                self.items[at] = criteria.Criterion(text, self.items[at].mark, fact)
            self._draw()
        self.app.push_screen(CriterionForm(None if at is None else self.items[at]), back)

    def _review(self) -> None:
        def chosen(kind: str | None) -> None:
            if kind is None:
                return
            if not kind:
                self.review = criteria.Review()
                self._draw()
                return
            draft = criteria.Review(kind, self.review.cause, self.review.change)
            def written(result: tuple | None) -> None:
                if result is not None:
                    self.review = criteria.Review(kind, *result)
                    self._draw()
            self.app.push_screen(ReviewForm(draft), written)
        current = self.review.kind or ("провал" if self.failed else "")
        self.app.push_screen(KindDialog(current), chosen)

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        key = normalize(event.key, event.character)
        n = len(self.items)
        if key == "escape":
            self.dismiss((self.items, self.review))
        elif key in ("j", "down") and n:
            self.pos = min(self.pos + 1, n - 1)
        elif key in ("k", "up") and n:
            self.pos = max(self.pos - 1, 0)
        elif key == "a":
            self._form(None)
        elif key == "enter" and n:
            self._form(self.pos)
        elif key == "space" and n:
            item = self.items[self.pos]
            self.items[self.pos] = criteria.Criterion(item.text, criteria.NEXT_MARK[item.mark], item.fact)
        elif key == "d" and n:
            del self.items[self.pos]
            self.pos = max(0, min(self.pos, len(self.items) - 1))
        elif key in ("J", "K") and n:
            j = self.pos + (1 if key == "J" else -1)
            if 0 <= j < n:
                self.items[self.pos], self.items[j] = self.items[j], self.items[self.pos]
                self.pos = j
        elif key == "r":
            self._review()
        self._draw()


class ConfirmDialog(ModalScreen[bool]):
    """Только Enter и Esc: они не зависят от раскладки, случайная буква ничего не удалит."""

    CSS = "ConfirmDialog { align: center middle; }" + _DIALOG_CSS

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(self.text), classes="title")
            yield Static("Enter — да, Esc — нет", classes="note")

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        if event.key == "enter":
            self.dismiss(True)
        elif event.key == "escape":
            self.dismiss(False)


class CommandLine(ModalScreen[str | None]):
    """Командная строка внизу экрана, как в vim."""

    CSS = """
    CommandLine { align: left bottom; background: transparent; }
    CommandLine Horizontal, #cmd { height: 1; width: 100%; }
    #cmd { border: none; padding: 0; background: #1b1e25; }
    """
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def compose(self) -> ComposeResult:
        yield Input(id="cmd", placeholder=":tabnew имя  :tabclose  :w  :q", select_on_focus=False)

    def on_mount(self) -> None:
        self.query_one(Input).value = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


HELP = """\
ВКЛАДКИ (во всех видах)
  Shift+→ или gt   следующая вкладка
  Shift+← или gT   предыдущая вкладка
  :tabnew имя   новая вкладка
  :tabclose     закрыть вкладку

ВЫДЕЛЕНИЕ (на карте)
  c             включить; стрелками добавлять пункты, шаг назад снимает
  Space S       статус всем: как у пункта под курсором / убрать
  t             срок всем (пустой ввод снимает)
  1 2 3 4       приоритет всем
  za zc zo      свернуть или развернуть
  gl            одна и та же ссылка всем
  dd            вырезать с ветками (с подтверждением) и выйти
  y             копировать с ветками и выйти
  u             отмена и выход
  Esc           выйти; p вставляет скопированное дочерним к выбранному

ПРИОРИТЕТЫ, ССЫЛКИ И ЗАМЕТКИ (во всех видах)
  1 2 3 4       приоритет ▰▰▰▰ ▰▰▰ ▰▰ ▰; та же цифра снимает
  n             заметка: Enter — новая строка, Esc — сохранить
                у пункта с заметкой на рамке ✎
  Enter  gx     открыть ссылку (на канбане и графике только gx)
  gl            добавить ссылку: сайт, файл или часть названия пункта
  gL            список ссылок: открыть, d — удалить

КАРТА
  h l  ← →      к родителю / к ребёнку
  j k  ↓ ↑      вниз / вверх
  gg  G         первый / последний пункт в столбце
  0             главная тема
  zz            выбранный пункт в центр экрана
  o  O          новый соседний пункт ниже / выше
  a             новый дочерний пункт
  i             переименовать
  Space         статус: нет → не завершено → завершено → провалено → …
  S             убрать статус
  t             сроки (пустой ввод снимает срок)
  dd            вырезать ветку
  yy  p         копировать ветку / вставить дочерней к выбранному пункту
                скопированное можно вставить и в другую программу
  J K           порядок среди соседей
  H L           на уровень выше / ниже
  za zc zo      свернуть или развернуть ветку
  zM zR         свернуть / развернуть всё
  u  Ctrl+R     отмена / повтор
  v             карта → канбан → сетевой график → карта

КРИТЕРИИ УСПЕХА И РАЗБОР (во всех видах)
  gk            окно критериев; у пункта с ними на рамке ◎
  a  Enter  d   добавить / изменить (критерий и факт) / удалить
  Space         оценка: ○ не оценён → ✓ достигнут → ✗ не достигнут
  J K           порядок критериев
  r             разбор: 1 закономерный успех, 2 «чудо», 3 форсаж,
                4 провал; затем причина и что меняем
  Esc           сохранить и закрыть; всё сделанное в окне — один шаг u

ЗАВЕРШЁННЫЕ (на карте)
  завершённые и проваленные спрятаны за окошком «… завершено: 2✓ 1✗»
  za zo  на «…» показать завершённые; za zc — спрятать снова
  показанное помнится до выхода из программы, файл не меняется

КАНБАН (только незакрытые пункты с датой)
  подзадача со сроком внутри срока родителя — карточка в карточке
  h l  ← →      колонки
  j k  ↓ ↑      карточки
  gg  G         первая / последняя карточка
  H L           влево / вправо; L из недели — завершить
  Space S t i   как на карте; закрытая карточка уходит с доски
                (u — вернуть), при неоценённых критериях сразу окно gk
  a             текущая вкладка / все вкладки
  Enter         открыть пункт на карте
  v             дальше, к сетевому графику

СЕТЕВОЙ ГРАФИК (только пункты со сроком)
  задача — полоса на свои дни, подзадача — в рамке родителя
  ‹ ›           срок идёт дальше края окна
  -  +          период: неделя (7 дней с сегодня), месяц, квартал, год
                месяц и квартал — столбцы-недели, год — месяцы;
                однодневные там скрыты — их число над столбцом,
                ◆ — однодневная с приоритетом ▰▰▰▰ или ▰▰▰
  h l  ← →      окно на столбец назад / вперёд (день, неделя, месяц)
  0             к сегодня: неделя с сегодня, остальное — текущий период
  j k  ↓ ↑      задачи; gg G — первая / последняя
  Space S t i   как на карте
  a             текущая вкладка / все вкладки
  Enter         открыть пункт на карте
  v             назад к карте

КОМАНДЫ
  :w            сохранить (сохранение и так автоматическое)
  :q  ZZ        выход

ЦВЕТА
  красный       не завершено, срок прошёл (пункт без статуса тоже)
  оранжевый     период задевает текущую неделю
  зелёный       начинается на следующей неделе, не длиннее 7 дней
  серый         завершено
  тёмно-красный провалено

Колёсико мыши прокручивает карту, Shift+колёсико — вбок.
Выделить текст на экране мышью — с зажатым Option.

Клавиши работают и в русской раскладке.\
"""


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen { align: center middle; }
    #help { width: 78; max-width: 100%; height: 90%; border: round #ff9f1c; background: #1b1e25; padding: 0 1; color: #d8dce3; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help"):
            yield Static(Text(HELP))

    def on_mount(self) -> None:
        scroller = self.query_one("#help", VerticalScroll)
        scroller.border_subtitle = "j k ↓ ↑ — прокрутка · Esc — закрыть"
        scroller.focus()

    def on_key(self, event) -> None:
        key = normalize(event.key, event.character)
        scroller = self.query_one("#help", VerticalScroll)
        if key in ("escape", "q", "?"):
            self.dismiss(None)
        elif key == "j":
            scroller.scroll_down(animate=False)
        elif key == "k":
            scroller.scroll_up(animate=False)
        else:
            return
        event.stop()
        event.prevent_default()
