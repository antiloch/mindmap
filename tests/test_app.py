"""Сценарии с настоящими клавишами через Textual Pilot."""
from datetime import date, datetime

import pytest
from textual import events

from mindmap import links
from mindmap.app import MindmapApp
from mindmap.board import COLUMN_TITLES
from mindmap.canvas import BACKGROUND, SELECTED_BG
from mindmap.model import DoneStub
from mindmap.dialogs import HELP, ConfirmDialog, DateDialog, HelpScreen, LinkDialog, LinkListDialog, TextDialog

NOW = datetime(2026, 11, 5, 12, 0)
SIZE = (120, 40)


@pytest.fixture(autouse=True)
def clipboard(monkeypatch):
    """Настоящий буфер macOS тесты не трогают."""
    copied = []
    monkeypatch.setattr("mindmap.app.pbcopy", copied.append)
    return copied


@pytest.fixture(autouse=True)
def opened(monkeypatch):
    """Браузер и программы тесты не открывают."""
    targets = []
    monkeypatch.setattr("mindmap.app.open_url", targets.append)
    return targets


def make(tmp_path, text=None):
    path = tmp_path / "Карта.md"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return MindmapApp(path, now=lambda: NOW), path


async def typed(pilot, text):
    await pilot.press(*["space" if c == " " else c for c in text])


async def add(pilot, opener, title):
    await pilot.press(opener)
    await pilot.pause()
    await typed(pilot, title)
    await pilot.press("enter")
    await pilot.pause()


async def test_create_status_date_undo(tmp_path):
    app, path = make(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await add(pilot, "a", "Первый")
        await add(pilot, "o", "Второй")
        await add(pilot, "a", "Внук")
        assert path.read_text(encoding="utf-8") == "# Карта\n\n- Первый\n- Второй\n  - Внук\n"

        await pilot.press("space")
        assert "- [ ] Внук" in path.read_text(encoding="utf-8")
        await pilot.press("space")
        assert "- [x] Внук" in path.read_text(encoding="utf-8")
        assert isinstance(app.sel, DoneStub)       # завершённый ушёл за «…», курсор на нём
        await pilot.press("z", "a", "j")            # показать и перейти на пункт
        assert app.sel.title == "Внук"
        await pilot.press("S")
        assert "  - Внук\n" in path.read_text(encoding="utf-8")

        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, DateDialog)
        await typed(pilot, "05-07.11")
        await pilot.press("enter")
        await pilot.pause()
        assert "- Внук @2026-11-05..2026-11-07\n" in path.read_text(encoding="utf-8")

        # Ошибочная дата не закрывает окно; Esc ничего не меняет.
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("ctrl+u")
        await typed(pilot, "ерунда")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DateDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert "@2026-11-05..2026-11-07" in path.read_text(encoding="utf-8")

        # Пустой ввод снимает срок.
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("ctrl+u", "enter")
        await pilot.pause()
        assert "@" not in path.read_text(encoding="utf-8")

        await pilot.press("u")
        assert "@2026-11-05..2026-11-07" in path.read_text(encoding="utf-8")
        await pilot.press("ctrl+r")
        assert "@" not in path.read_text(encoding="utf-8")


async def test_russian_layout(tmp_path):
    app, path = make(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await add(pilot, "ф", "Первый")     # ф = a
        await add(pilot, "щ", "Второй")     # щ = o
        await pilot.press("л")              # л = k, вверх
        assert app.sel.title == "Первый"
        await pilot.press("о")              # о = j, вниз
        assert app.sel.title == "Второй"
        await pilot.press("р")              # р = h, к родителю
        assert app.sel.parent is None
        await pilot.press("д")              # д = l, к ребёнку
        assert app.sel.parent is app.root
        await pilot.press("в", "в")         # dd
        await pilot.pause()
        assert len(app.root.children) == 1
        await pilot.press("г")              # г = u
        assert len(app.root.children) == 2


async def test_arrows_move_like_hjkl(tmp_path):
    text = "# Т\n\n- a\n  - a1\n- b\n"
    app, _ = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("right")
        assert app.sel.title in ("a", "b")
        await pilot.press("up")
        assert app.sel.title == "a"
        await pilot.press("down")
        assert app.sel.title == "b"
        await pilot.press("up", "right")
        assert app.sel.title == "a1"
        await pilot.press("left", "left")
        assert app.sel is app.root


async def test_cut_confirm_paste_move_fold(tmp_path):
    text = "# Т\n\n- a\n  - a1\n  - a2\n- b\n- c\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.select(app.root.children[0])
        app.refresh_view()

        # Ветка с детьми: Esc отменяет вырезание, Enter подтверждает.
        await pilot.press("d", "d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.root.children) == 3
        await pilot.press("d", "d")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert [c.title for c in app.root.children] == ["b", "c"]
        assert app.sel.title == "b"

        await pilot.press("p")
        assert app.sel.title == "a" and app.sel.parent.title == "b"
        assert [c.title for c in app.sel.children] == ["a1", "a2"]

        # J/K порядок, H/L уровень.
        app.select(app.root.children[0])
        await pilot.press("J")
        assert [c.title for c in app.root.children] == ["c", "b"]
        await pilot.press("K")
        assert [c.title for c in app.root.children] == ["b", "c"]
        app.select(app.root.children[1])
        await pilot.press("L")
        assert [c.title for c in app.root.children] == ["b"]
        assert [c.title for c in app.root.children[0].children] == ["a", "c"]
        await pilot.press("H")
        assert [c.title for c in app.root.children] == ["b", "c"]

        # Свёртывание сохраняется в файле; выбранный пункт не прячется.
        app.select(app.root.children[0].children[0])
        app.refresh_view()
        await pilot.press("z", "M")
        assert app.sel.title == "b"
        assert "<!--collapsed-->" in path.read_text(encoding="utf-8")
        await pilot.press("z", "R")
        assert "<!--collapsed-->" not in path.read_text(encoding="utf-8")
        await pilot.press("z", "a")
        assert app.sel.collapsed
        # l на свёрнутой ветке разворачивает её и заходит внутрь.
        await pilot.press("l")
        assert not app.root.children[0].collapsed and app.sel.parent.title == "b"


async def test_tabs(tmp_path):
    app, path = make(tmp_path, "# Один\n\n- a\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("colon")
        await pilot.pause()
        await typed(pilot, "tabnew Два")
        await pilot.press("enter")
        await pilot.pause()
        assert path.read_text(encoding="utf-8") == "# Один\n\n- a\n\n# Два\n"
        assert app.tab == 1
        await pilot.press("g", "t")
        assert app.tab == 0
        await pilot.press("g", "T")
        assert app.tab == 1
        # Команда, набранная в русской раскладке, название не портит.
        await pilot.press("colon")
        await pilot.pause()
        await typed(pilot, "ефисдщыу")      # tabclose
        await pilot.press("enter")
        await pilot.pause()
        assert path.read_text(encoding="utf-8") == "# Один\n\n- a\n"
        # Последнюю вкладку закрыть нельзя.
        await pilot.press("colon")
        await pilot.pause()
        await typed(pilot, "tabclose")
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.doc.sheets) == 1


BOARD_FILE = """# Работа

- Ветка без даты
  - [ ] Сегодняшнее @2026-11-05
  - [ ] Просроченное @2026-11-03
  - Просроченное без статуса @2026-11-01
  - [ ] На неделе @2026-11-07
  - [ ] Годовая цель @2026
  - [ ] Следующая неделя @2026-11-10
  - [ ] Лист без даты
  - [x] Сделанное @2026-11-02
  - [x] Сделанное без даты

# Личное

- [ ] Личная задача @2026-11-06
"""


async def test_board_columns(tmp_path):
    app, path = make(tmp_path, BOARD_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        titles = lambda c: [n.title for n in board.cards[c]]
        assert titles(0) == ["Следующая неделя"]
        assert titles(1) == ["Сегодняшнее", "Просроченное без статуса", "Просроченное", "На неделе", "Годовая цель"]
        assert all(n.title != "Сделанное" for c in range(len(board.cards)) for n in board.cards[c])

        # Все вкладки.
        await pilot.press("a")
        assert "Личная задача" in titles(1)
        await pilot.press("a")
        assert "Личная задача" not in titles(1)

        # L из недели завершает: карточка уходит с доски, выбор — на соседней.
        board.index[1] = 0
        board.col = 1
        await pilot.press("L")
        assert "- [x] Сегодняшнее" in path.read_text(encoding="utf-8")
        assert "Сегодняшнее" not in titles(1)
        assert board.col == 1 and board.current().title == "Просроченное без статуса"
        assert app.message == "Завершено: Сегодняшнее · u — вернуть"
        # H из недели в «Завершено» не ведёт: колонки нет. u возвращает задачу.
        await pilot.press("u")
        assert "- [ ] Сегодняшнее" in path.read_text(encoding="utf-8")
        assert titles(1)[0] == "Сегодняшнее"

        # Из «Запланировано» в неделю: окно с подставленным воскресеньем.
        await pilot.press("h")
        assert board.col == 0
        await pilot.press("L")
        await pilot.pause()
        assert isinstance(app.screen, DateDialog)
        assert app.screen.value == "08.11.2026"
        await pilot.press("enter")
        await pilot.pause()
        assert "Следующая неделя @2026-11-08" in path.read_text(encoding="utf-8")
        assert board.col == 1 and board.current().title == "Следующая неделя"

        # Обратно в «Запланировано»: окно с понедельником следующей недели.
        await pilot.press("H")
        await pilot.pause()
        assert app.screen.value == "09.11.2026"
        await pilot.press("enter")
        await pilot.pause()
        assert board.col == 0 and "Следующая неделя @2026-11-09" in path.read_text(encoding="utf-8")

        # Стёртая дата уводит карточку с доски, на карте пункт остаётся.
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("ctrl+u", "enter")
        await pilot.pause()
        assert titles(0) == []
        assert "- [ ] Следующая неделя\n" in path.read_text(encoding="utf-8")

        # Space оставляет курсор в колонке.
        await pilot.press("l")
        assert board.col == 1
        first = board.current()
        await pilot.press("space")
        assert first.status == "done"
        assert board.col == 1 and board.current() is not first

        # Enter открывает пункт на карте.
        target = board.current()
        await pilot.press("enter")
        await pilot.pause()
        assert app.mode == "map" and app.sel is target


async def test_enter_jumps_to_other_tab(tmp_path):
    app, _ = make(tmp_path, BOARD_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v", "a")
        await pilot.pause()
        board = app.query_board()
        board.index[1] = [n.title for n in board.cards[1]].index("Личная задача")
        await pilot.press("enter")
        await pilot.pause()
        assert app.tab == 1 and app.sel.title == "Личная задача"


async def test_external_change_and_conflict(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- a\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        path.write_text("# Т\n\n- a\n- снаружи\n", encoding="utf-8")
        app._check_external()
        await pilot.pause()
        assert [c.title for c in app.root.children] == ["a", "снаружи"]
        await pilot.press("u")
        assert [c.title for c in app.root.children] == ["a"]

        # Файл поменяли, а проверка ещё не успела сработать: чужая версия не теряется.
        path.write_text("# Т\n\n- чужое\n", encoding="utf-8")
        await pilot.press("space")
        copies = list(tmp_path.glob("*.conflict-*"))
        assert len(copies) == 1 and "чужое" in copies[0].read_text(encoding="utf-8")


async def test_opening_does_not_rewrite_file(tmp_path):
    messy = "# Т\n\n* a\n    + b\n"
    app, path = make(tmp_path, messy)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("j", "k", "l", "h")
    assert path.read_text(encoding="utf-8") == messy


async def test_empty_title_cancels_new_item(tmp_path):
    app, path = make(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, TextDialog)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not app.root.children
        assert not path.exists()


async def test_deep_map_is_navigable(tmp_path):
    lines = ["# Т", ""]
    for i in range(300):
        lines.append("  " * i + f"- п{i}")
    app, _ = make(tmp_path, "\n".join(lines) + "\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        for _ in range(50):
            await pilot.press("l")
        await pilot.pause()
        assert app.sel.title == "п49"
        view = app.query_map()
        box = view.current
        sx, _sy = view.scroll_offset
        assert sx <= box.x and box.x + box.w <= sx + view.size.width
        text = "".join(seg.text for seg in view.render_line(box.y - _sy + 1)._segments)
        assert "п49" in text


async def test_help_shows_tabs_in_small_window(tmp_path):
    app, _ = make(tmp_path, "# Т\n")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        scroller = app.screen.query_one("#help")
        lines = HELP.splitlines()
        # Вкладки видны сразу, без прокрутки, даже в маленьком окне.
        assert next(i for i, l in enumerate(lines) if "gT" in l) < scroller.scrollable_content_region.height
        assert scroller.border_subtitle
        # Справка длиннее окна, и все клавиши прокрутки работают.
        for key in ("j", "о", "down"):
            before = scroller.scroll_y
            await pilot.press(key)
            await pilot.pause()
            assert scroller.scroll_y > before, key
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


SELECT_FILE = """# Т

- a
  - a1
    - a11
  - a2
- [ ] b @2026-11-06
  - b1
- c
"""


async def test_selection_marks_and_copies(tmp_path, clipboard):
    app, path = make(tmp_path, SELECT_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        assert app.sel.title == "a"
        await pilot.press("c", "c", "c")                  # зажатая буква ничего не сбрасывает
        assert [n.title for n in app.marks] == ["a"]
        await pilot.press("down", "down")
        assert [n.title for n in app.marks] == ["a", "b", "c"]
        await pilot.press("up")                           # шаг назад снимает отметку
        assert [n.title for n in app.marks] == ["a", "b"]
        # Новые пункты и переименование в режиме выделения не работают.
        await pilot.press("o", "a", "i", "x")
        await pilot.pause()
        assert app.marks is not None and app.sel.title == "b"
        assert path.read_text(encoding="utf-8") == SELECT_FILE
        await pilot.press("y")
        assert app.marks is None
        assert clipboard == ["- a\n  - a1\n    - a11\n  - a2\n- [ ] b @2026-11-06\n  - b1\n"]

        await pilot.press("down")
        assert app.sel.title == "c"
        await pilot.press("p")
        assert [n.title for n in app.root.children[2].children] == ["a", "b"]
        assert [n.title for n in app.root.children[2].children[0].children] == ["a1", "a2"]
        await pilot.press("u")                            # вставка отменяется одним шагом
        assert path.read_text(encoding="utf-8") == SELECT_FILE


async def test_selection_parent_and_child_not_duplicated(tmp_path, clipboard):
    app, _ = make(tmp_path, SELECT_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "с", "д")                  # русская раскладка: с = c, д = l
        assert [n.title for n in app.marks] == ["a", "a1"]
        await pilot.press("н")                            # н = y
        assert [n.title for n in app.register] == ["a"]
        assert clipboard[-1].count("- a1\n") == 1


async def test_selection_escape_and_order(tmp_path, clipboard):
    app, _ = make(tmp_path, SELECT_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "c", "escape")
        assert app.marks is None and not clipboard and not app.register
        # Выделение снизу вверх всё равно копирует в порядке карты.
        await pilot.press("G", "c", "up", "up", "y")
        assert [n.title for n in app.register] == ["a", "b", "c"]


async def test_yy_copies_to_macos_but_dd_does_not(tmp_path, clipboard):
    app, _ = make(tmp_path, "# Т\n\n- a\n- b\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "y", "y")
        assert clipboard == ["- a\n"]
        await pilot.press("d", "d")
        await pilot.pause()
        assert clipboard == ["- a\n"]
        assert [n.title for n in app.register] == ["a"]


async def test_pbcopy_failure_is_reported(tmp_path, monkeypatch):
    def broken(text):
        raise OSError("нет pbcopy")
    monkeypatch.setattr("mindmap.app.pbcopy", broken)
    app, _ = make(tmp_path, "# Т\n\n- a\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "y", "y")
        assert [n.title for n in app.register] == ["a"]
        assert "не удалось" in app.message


async def test_shift_arrows_switch_tabs(tmp_path):
    app, _ = make(tmp_path, BOARD_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("shift+right")
        assert app.tab == 1
        await pilot.press("shift+right")
        assert app.tab == 0                               # по кругу
        await pilot.press("shift+left")
        assert app.tab == 1
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("shift+left")
        assert app.tab == 0 and app.mode == "board"
        assert "Сегодняшнее" in [n.title for n in app.query_board().cards[1]]


def wheel(widget, kind, shift=False):
    return kind(widget, 5, 5, 0, 0, 0, shift, False, False)


async def test_mouse_wheel_scrolls_view_only(tmp_path):
    lines = ["# Т", ""] + [f"- п{i}" for i in range(60)]
    app, path = make(tmp_path, "\n".join(lines) + "\n")
    before = path.read_text(encoding="utf-8")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view = app.query_map()
        assert view.scroll_offset.y == 0
        view.post_message(wheel(view, events.MouseScrollDown))
        await pilot.pause()
        assert view.scroll_offset.y == 3
        view.post_message(wheel(view, events.MouseScrollUp))
        await pilot.pause()
        assert view.scroll_offset.y == 0
        selected = app.sel
        # Клавиша возвращает экран к выбранному пункту; выбор колёсико не менял.
        for _ in range(5):
            view.post_message(wheel(view, events.MouseScrollDown))
        await pilot.pause()
        assert app.sel is selected
        await pilot.press("l")
        box = view.current
        assert view.scroll_offset.y <= box.y < view.scroll_offset.y + view.size.height
    assert path.read_text(encoding="utf-8") == before


async def test_mouse_wheel_on_board_moves_card(tmp_path):
    app, _ = make(tmp_path, BOARD_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        first = board.current()
        board.post_message(wheel(board, events.MouseScrollDown))
        await pilot.pause()
        assert board.current() is not first
        board.post_message(wheel(board, events.MouseScrollUp))
        await pilot.pause()
        assert board.current() is first


GROUP_FILE = """# Т

- a
  - a1
- [ ] b @2026-11-06
- c
"""


async def mark_all(pilot):
    """Отметить a, b, c; курсор остаётся на c."""
    await pilot.press("l", "c", "down", "down")


async def test_group_status_follows_cursor_in_one_undo(tmp_path):
    app, path = make(tmp_path, GROUP_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await mark_all(pilot)
        await pilot.press("space")                  # c: нет статуса → не завершено, всем то же
        assert [n.status for n in app.root.children] == ["todo", "todo", "todo"]
        assert app.marks is not None                # выделение остаётся для следующей команды
        assert app.root.children[0].children[0].status is None  # дети не меняются
        await pilot.press("u")
        assert app.marks is None
        assert path.read_text(encoding="utf-8") == GROUP_FILE

        await pilot.press("0")                      # после отмены курсор остался на c
        await mark_all(pilot)
        await pilot.press("S")
        assert [n.status for n in app.root.children] == [None, None, None]
        await pilot.press("S")                      # менять нечего — нового шага отмены нет
        assert len(app.undo_stack) == 1


async def test_group_date(tmp_path):
    app, path = make(tmp_path, GROUP_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await mark_all(pilot)
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, DateDialog)
        assert app.screen.query_one("Input").value == ""   # сроки разные — поле пустое
        await typed(pilot, "20.11.2026")
        await pilot.press("enter")
        await pilot.pause()
        assert [n.period.token() for n in app.root.children] == ["2026-11-20"] * 3
        assert len(app.undo_stack) == 1
        await pilot.press("t")
        await pilot.pause()
        assert app.screen.query_one("Input").value == "20.11.2026"  # общий срок виден
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("u")
        assert path.read_text(encoding="utf-8") == GROUP_FILE


async def test_group_priority(tmp_path):
    app, path = make(tmp_path, GROUP_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await mark_all(pilot)
        await pilot.press("2")
        assert [n.priority for n in app.root.children] == [2, 2, 2]
        assert "- ▰▰▰ a\n" in path.read_text(encoding="utf-8")
        await pilot.press("2")                      # та же цифра снимает у всех
        assert [n.priority for n in app.root.children] == [None, None, None]
        await pilot.press("escape")
        assert app.marks is None


async def test_group_fold_drops_hidden_marks(tmp_path):
    app, path = make(tmp_path, GROUP_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "c", "l")            # a и его ребёнок a1
        assert [n.title for n in app.marks] == ["a", "a1"]
        await pilot.press("z", "c")
        assert app.root.children[0].collapsed
        assert [n.title for n in app.marks] == ["a"]
        assert app.sel.title == "a"
        await pilot.press("space")
        assert app.root.children[0].children[0].status is None
        await pilot.press("z", "o")
        assert not app.root.children[0].collapsed


async def test_group_cut(tmp_path):
    app, path = make(tmp_path, GROUP_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "c", "h")            # a и главная тема
        await pilot.press("d", "d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert app.marks is not None                # отказ не снимает выделение
        await pilot.press("d", "d")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.marks is None
        assert [n.title for n in app.root.children] == ["b", "c"]  # главная тема на месте
        assert [n.title for n in app.register] == ["a"]
        await pilot.press("u")
        assert path.read_text(encoding="utf-8") == GROUP_FILE


async def test_group_only_main_topic_cannot_be_cut(tmp_path):
    app, path = make(tmp_path, GROUP_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("c", "d", "d")
        await pilot.pause()
        assert "Главную тему" in app.message
        assert path.read_text(encoding="utf-8") == GROUP_FILE


async def test_group_link_without_duplicates(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- a\n  Ссылка: https://x.ru/\n- b\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "c", "down", "g", "l")
        await pilot.pause()
        assert isinstance(app.screen, LinkDialog)
        await typed(pilot, "https://x.ru/")
        await pilot.press("enter")
        await pilot.pause()
        text = path.read_text(encoding="utf-8")
        assert text == "# Т\n\n- a\n  Ссылка: https://x.ru/\n- b\n  Ссылка: https://x.ru/\n"
        assert len(app.undo_stack) == 1


async def test_priority_keys_and_board_order(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- ранний @2026-11-06\n- поздний @2026-11-07\n- ❶ важный @2026-11-08\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        assert [n.title for n in board.cards[1]] == ["важный", "ранний", "поздний"]
        assert path.read_text(encoding="utf-8").count("❶") == 1   # открытие файл не меняет
        await pilot.press("j", "4")                # «ранний» — низкий, но выше пунктов без приоритета
        assert board.current().title == "ранний"
        assert path.read_text(encoding="utf-8").count("❶") == 0   # первое сохранение — полоски
        assert "- ▰▰▰▰ важный @2026-11-08\n" in path.read_text(encoding="utf-8")
        assert "- ▰ ранний @2026-11-06\n" in path.read_text(encoding="utf-8")


async def test_priority_typed_in_title_dialog(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- a\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        app.screen.query_one("Input").value = "▰▰ новый"
        await pilot.press("enter")
        await pilot.pause()
        assert app.sel.priority == 3 and app.sel.title == "новый"
        await pilot.press("i")
        await pilot.pause()
        assert app.screen.query_one("Input").value == "новый"
        app.screen.query_one("Input").value = "▰ другое"
        await pilot.press("enter")
        await pilot.pause()
        assert app.sel.priority == 4 and app.sel.title == "другое"
        assert "- ▰ другое\n" in path.read_text(encoding="utf-8")


LINK_FILE = """# Работа

- сайт
  Ссылка: https://www.thecode.media/launchctl/
- мёртвая
  Ссылка: xmind:#380b
- два
  Ссылка: https://a.ru/
  Ссылка: https://b.ru/
- ведёт
  Ссылка на пункт: Цель
- без ссылок

# Цель

Ссылка на пункт: Цель

- внутри <!--collapsed-->
  - Глубоко
"""


async def goto(pilot, app, title):
    node = next(n for root in app.doc.sheets for n in root.walk() if n.title == title)
    app._reveal(node)
    app.refresh_view()
    await pilot.pause()
    return node


async def test_open_one_link_at_once(tmp_path, opened):
    app, path = make(tmp_path, LINK_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "сайт")
        await pilot.press("enter")
        assert opened == ["https://www.thecode.media/launchctl/"]
        await pilot.press("g", "x")
        assert len(opened) == 2
        assert path.read_text(encoding="utf-8") == LINK_FILE


async def test_no_links_and_dead_link_messages(tmp_path, opened):
    app, path = make(tmp_path, LINK_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "без ссылок")
        await pilot.press("enter")
        assert "нет ссылок" in app.message
        await goto(pilot, app, "мёртвая")
        await pilot.press("enter")
        assert "не открывает" in app.message
        assert opened == []


async def test_several_links_list_open_and_remove(tmp_path, opened):
    app, path = make(tmp_path, LINK_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "два")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, LinkListDialog)
        await pilot.press("2")                      # цифра открывает сразу
        await pilot.pause()
        assert opened == ["https://b.ru/"]
        assert app.message == "Открыто: b.ru"

        await pilot.press("g", "L")
        await pilot.pause()
        await pilot.press("j", "enter")
        await pilot.pause()
        assert opened[-1] == "https://b.ru/"

        await pilot.press("g", "L")
        await pilot.pause()
        await pilot.press("d")                      # удалена первая, список остаётся открытым
        await pilot.pause()
        assert isinstance(app.screen, LinkListDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert "Ссылка: https://a.ru/" not in path.read_text(encoding="utf-8")
        await pilot.press("u")
        assert path.read_text(encoding="utf-8") == LINK_FILE


async def test_item_link_goes_to_other_tab_and_unfolds(tmp_path, opened):
    app, path = make(tmp_path, LINK_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "ведёт")
        await pilot.press("enter")
        await pilot.pause()
        assert app.tab == 1 and app.sel is app.doc.sheets[1]
        assert opened == []

        # С вкладки «Цель» ссылка с тем же названием ведёт не на неё саму: такого пункта нет.
        await pilot.press("enter")
        await pilot.pause()
        assert "не найден" in app.message

        await pilot.press("g", "l")
        await pilot.pause()
        await typed(pilot, "глуб")                  # достаточно части названия
        await pilot.press("enter")
        await pilot.pause()
        assert "Ссылка на пункт: Глубоко" in app.root.notes
        node = next(n for n in app.root.walk() if n.title == "внутри")
        assert node.collapsed
        await pilot.press("g", "L")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert app.sel.title == "Глубоко"           # свёрнутый родитель раскрылся
        assert not node.collapsed


async def test_link_dialog_keeps_open_on_ambiguous(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- план а\n- план б\n- c\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "c")
        await pilot.press("g", "l")
        await pilot.pause()
        await typed(pilot, "план")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, LinkDialog)   # два совпадения — ждём уточнения
        await pilot.press("escape")
        await pilot.pause()
        assert not links.read(app.sel)


async def test_rename_updates_links_when_title_is_unique(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- цель\n- а\n  Ссылка на пункт: цель\n- б\n  Ссылка на пункт: а\n- а\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "цель")
        await pilot.press("i")
        await pilot.pause()
        app.screen.query_one("Input").value = "задача"
        await pilot.press("enter")
        await pilot.pause()
        text = path.read_text(encoding="utf-8")
        assert "Ссылка на пункт: задача" in text
        await pilot.press("u")
        assert "Ссылка на пункт: цель" in path.read_text(encoding="utf-8")

        await goto(pilot, app, "а")                 # название не единственное — ссылки не трогаем
        await pilot.press("i")
        await pilot.pause()
        app.screen.query_one("Input").value = "новое"
        await pilot.press("enter")
        await pilot.pause()
        assert "Ссылка на пункт: а\n" in path.read_text(encoding="utf-8")


async def test_file_links(tmp_path, opened):
    (tmp_path / "отчёт за год.pdf").write_text("x", encoding="utf-8")
    script = tmp_path / "run.command"
    script.write_text("x", encoding="utf-8")
    text = "# Т\n\n- файл\n  Ссылка: ./отчёт за год.pdf\n- нет\n  Ссылка: ./пропал.pdf\n- скрипт\n  Ссылка: ./run.command\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "файл")
        await pilot.press("enter")
        assert opened == [str((tmp_path / "отчёт за год.pdf").resolve())]

        await goto(pilot, app, "нет")
        await pilot.press("enter")
        assert "Файла нет" in app.message and len(opened) == 1

        await goto(pilot, app, "скрипт")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)  # код без спроса не запускается
        await pilot.press("escape")
        await pilot.pause()
        assert len(opened) == 1
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert opened[-1].endswith("run.command")


async def test_open_failure_is_reported(tmp_path, monkeypatch):
    def broken(_):
        raise OSError("нет open")
    monkeypatch.setattr("mindmap.app.open_url", broken)
    app, path = make(tmp_path, LINK_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(pilot, app, "сайт")
        await pilot.press("enter")
        assert "Не удалось открыть" in app.message


async def test_board_gx_opens_and_enter_still_goes_to_map(tmp_path, opened):
    app, path = make(tmp_path, "# Т\n\n- сайт @2026-11-06\n  Ссылка: https://a.ru/\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("g", "x")
        assert opened == ["https://a.ru/"]
        await pilot.press("enter")
        await pilot.pause()
        assert app.mode == "map" and app.sel.title == "сайт" and len(opened) == 1


NESTED_FILE = """# Т

- Стать заместителем @2026-10..2027-12
  - Получить аттестацию @2026-10..2027-01
    - Закончить переподготовку @2026-10..2027-01
    - Шире родителя @2026-10..2027-06
  - Промежуточный
    - Через одного @2026-11..2026-12
  - Сегодняшняя @2026-11-05
- Сосед @2026-10..2027-01
"""


def board_text(app):
    board = app.query_board()
    return [board.render_line(y).text.rstrip() for y in range(board.size.height)]


async def test_board_draws_card_inside_parent(tmp_path):
    app, path = make(tmp_path, NESTED_FILE)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        titles = [n.title for n in board.cards[1]]
        assert titles[0] == "Сегодняшняя"           # раздел «Сегодня» сверху

        parent = next(n for n in board.cards[1] if n.title == "Стать заместителем")
        inner = next(n for n in board.cards[1] if n.title == "Получить аттестацию")
        deep = next(n for n in board.cards[1] if n.title == "Закончить переподготовку")
        assert inner in board._kids[id(parent)]
        assert deep in board._kids[id(inner)]
        assert not any(n.title == "Сегодняшняя" for n in board._kids[id(parent)])  # другой раздел
        assert titles.index("Стать заместителем") < titles.index("Получить аттестацию") < titles.index("Закончить переподготовку")

        # Вложенные строки на экране сдвинуты внутрь рамки родителя, рамки ровные.
        lines = board_text(app)
        row = next(l for l in lines if "Закончить переподготовку" in l)
        assert row.count("│") >= 3
        for y in range(board.size.height):
            assert board.render_line(y).cell_length == board.size.width

        # j ходит по всем карточкам и останавливается на вложенной.
        while board.current() is not deep:
            await pilot.press("j")
        await pilot.press("enter")
        await pilot.pause()
        assert app.mode == "map" and app.sel is deep


async def test_nested_crumb_is_relative_and_selection_range_is_inside(tmp_path):
    app, path = make(tmp_path, NESTED_FILE)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        cards = board.cards[1]
        rng = dict(zip((n.title for n in cards), board._ranges[1]))
        a, b = rng["Стать заместителем"], rng["Закончить переподготовку"]
        assert a[0] < b[0] and b[1] < a[1]                 # внутри родителя
        lines = board_text(app)
        assert any("Промежуточный" in l for l in lines)    # путь от родителя
        assert not any("Стать заместителем › Получить" in l for l in lines)


async def test_narrow_column_stops_nesting_and_keeps_order(tmp_path):
    text = "# Т\n\n- a @2026\n  - b @2026\n    - c @2026\n      - d @2026\n        - e @2026\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        assert [n.title for n in board.cards[1]] == ["a", "b", "c", "d", "e"]
        tops = [r[0] for r in board._ranges[1]]
        assert tops == sorted(tops) and len(set(tops)) == 5
        for y in range(board.size.height):
            assert board.render_line(y).cell_length == board.size.width


def test_column_titles():
    assert COLUMN_TITLES == ["Запланировано", "На этой неделе"]


def _row_bg(board, text):
    """Фон текста в строке доски, где встречается text."""
    for y in range(board.size.height):
        strip = board.render_line(y)
        if text in strip.text:
            return {seg.style.bgcolor.name for seg in strip if text in seg.text and seg.style and seg.style.bgcolor}
    raise AssertionError(text)


async def test_selected_parent_lights_nested_but_edits_only_itself(tmp_path):
    text = "# Т\n\n- [ ] Родитель @2026\n  - [ ] Ребёнок @2026\n    - [ ] Внук @2026\n- [ ] Сосед @2026\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        parent = next(n for n in board.cards[1] if n.title == "Родитель")
        while board.current() is not parent:
            await pilot.press("j")
        lit = {SELECTED_BG}
        assert _row_bg(board, "Родитель") == lit
        assert _row_bg(board, "Ребёнок") == lit and _row_bg(board, "Внук") == lit
        assert _row_bg(board, "Сосед") == {BACKGROUND}
        assert sum("═" in board.render_line(y).text for y in range(board.size.height)) == 2  # двойная рамка одна

        await pilot.press("space")                  # правка только у выбранного
        assert parent.status == "done"
        assert [n.status for n in parent.children] == ["todo"] and parent.children[0].children[0].status == "todo"
        await pilot.press("u")
        assert path.read_text(encoding="utf-8") == text

        board = app.query_board()
        child = next(n for n in board.cards[1] if n.title == "Ребёнок")
        while board.current() is not child:
            await pilot.press("j" if board.cards[1].index(board.current()) < board.cards[1].index(child) else "k")
        assert _row_bg(board, "Родитель") == {BACKGROUND}  # выбран вложенный — родитель не подсвечен
        assert _row_bg(board, "Ребёнок") == lit and _row_bg(board, "Внук") == lit


# ---------- завершённые за окошком «…» ----------

DONE_FILE = """# Т

- Проект
  - [x] Готово 1
    - [ ] Внутри готового
  - [ ] В работе
  - [x] Готово 2 @2026-11-04
- [x] Старое
"""


def visible_titles(app):
    return [b.node.title for b in app.query_map().plan.boxes]


def kids_of(app, node):
    return [b.node for b in app.query_map().plan.by_node[id(node)].kids]


async def go_to(pilot, app, title):
    """Встать на видимый пункт с таким названием (обход карты по j/l)."""
    app.select(next(b.node for b in app.query_map().plan.boxes if b.node.title == title))
    app.refresh_view()
    await pilot.pause()


async def test_done_items_hide_behind_stub_and_za_shows_them(tmp_path):
    app, path = make(tmp_path, DONE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        root = app.root
        project = root.children[0]
        titles = visible_titles(app)
        assert "Готово 1" not in titles and "Готово 2" not in titles and "Старое" not in titles
        assert "Внутри готового" not in titles               # ветка уходит целиком
        first = kids_of(app, root)[0]
        assert isinstance(first, DoneStub) and first.title == "… завершено: 1✓"
        stub = kids_of(app, project)[0]
        assert isinstance(stub, DoneStub) and stub.title == "… завершено: 2✓"
        assert [n.title for n in kids_of(app, project)[1:]] == ["В работе"]
        assert app.query_map().plan.by_node[id(project)].label == "2/3"   # счётчик прежний

        await pilot.press("l")                       # первый видимый ребёнок — «…»
        assert app.sel is first
        await pilot.press("j", "l")
        assert app.sel is stub
        await pilot.press("z", "a")
        assert [n.title for n in kids_of(app, project)] == ["… завершено: 2✓, показаны", "Готово 1", "В работе", "Готово 2"]
        assert "Внутри готового" in visible_titles(app)
        assert app.sel is stub                       # окошко остаётся первым и выбранным
        await pilot.press("z", "c")
        assert "Готово 1" not in visible_titles(app)
        await pilot.press("z", "o")
        assert "Готово 1" in visible_titles(app)
        assert path.read_text(encoding="utf-8") == DONE_FILE   # раскрытие файл не меняет

        await pilot.press("i")                       # на «…» править нечего
        await pilot.pause()
        assert not isinstance(app.screen, TextDialog)
        assert "za — показать" in app.message
        await pilot.press("space", "d", "d", "1")
        assert path.read_text(encoding="utf-8") == DONE_FILE


async def test_done_item_moves_cursor_to_stub_and_undo_keeps_shown(tmp_path):
    app, path = make(tmp_path, DONE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await go_to(pilot, app, "В работе")
        await pilot.press("space")                   # не завершено → завершено
        assert isinstance(app.sel, DoneStub) and app.sel.title == "… завершено: 3✓"
        await pilot.press("u")
        assert app.sel.title == "В работе" and app.sel.status == "todo"

        await pilot.press("k", "z", "a")             # показать завершённые «Проекта»
        assert "Готово 1" in visible_titles(app)
        await pilot.press("j", "j", "2")             # правка и отмена: показанное остаётся
        await pilot.press("u")
        assert "Готово 1" in visible_titles(app)
        assert path.read_text(encoding="utf-8") == DONE_FILE


async def test_marks_skip_stub_and_drop_when_hidden(tmp_path):
    app, path = make(tmp_path, DONE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await go_to(pilot, app, "В работе")
        await pilot.press("c", "k")                  # курсор на «…», но оно не отмечается
        assert isinstance(app.sel, DoneStub)
        assert [n.title for n in app.marks] == ["В работе"]
        await pilot.press("j", "space")              # отмеченный стал завершённым и спрятался
        assert app.marks is None
        assert isinstance(app.sel, DoneStub)


async def test_swap_and_demote_skip_hidden_done(tmp_path):
    text = "# Т\n\n- a\n- [x] b\n- c\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await go_to(pilot, app, "c")
        await pilot.press("K")                       # меняется с видимым a, а не со спрятанным b
        assert [n.title for n in app.root.children] == ["c", "b", "a"]
        await pilot.press("u")
        await go_to(pilot, app, "c")
        await pilot.press("L")                       # уходит в видимого соседа a
        assert [n.title for n in app.root.children[0].children] == ["c"]


async def test_open_done_card_on_map_shows_it(tmp_path):
    app, path = make(tmp_path, DONE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v", "v", "h")             # график с 04.11: на канбане завершённых нет
        await pilot.pause()
        assert app.query_graph().current().title == "Готово 2"
        await pilot.press("enter")
        await pilot.pause()
        assert app.mode == "map" and app.sel.title == "Готово 2"
        assert "Готово 2" in visible_titles(app)


# ---------- сетевой график ----------

GRAPH_FILE = """# Т

- Неделя @2026-11-05..2026-11-11
  - Сегодня @2026-11-05
  - Два дня @2026-11-06..2026-11-07
- Длинная @2026-11-01..2026-11-20
- Вне окна @2026-11-20
- [x] Сделано @2026-11-05T15:20
"""


def view_text(view):
    return [view.render_line(y).text.rstrip() for y in range(view.size.height)]


async def open_graph(pilot):
    await pilot.press("v", "v")
    await pilot.pause()


async def test_v_cycles_map_board_graph(tmp_path):
    app, path = make(tmp_path, GRAPH_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        seen = []
        for _ in range(3):
            await pilot.press("v")
            await pilot.pause()
            seen.append(app.mode)
        assert seen == ["board", "graph", "map"]


async def test_graph_draws_week_with_spans_and_nesting(tmp_path):
    app, path = make(tmp_path, GRAPH_FILE)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        assert [n.title for n in graph.cards] == ["Длинная", "Неделя", "Сегодня", "Два дня", "Сделано"]
        week = graph.cards[1]
        assert [n.title for n in graph._kids[id(week)]] == ["Сегодня", "Два дня"]

        lines = view_text(graph)
        assert lines[0].startswith(" чт 05.11") and "ср 11.11" in lines[0]
        long = next(l for l in lines if "Длинная" in l)
        assert long.startswith("‹") and long.rstrip().endswith("›")   # срок шире окна с обеих сторон
        frame = next(l for l in lines if "Неделя" in l)
        assert frame.startswith("╭") and "‹" not in frame and "›" not in frame   # рамка родителя
        assert graph.current().title == "Сегодня"          # выбор пришёл с канбана
        row = next(l for l in lines if "Сегодня" in l)
        assert row.startswith("│") and row.index("Сегодня") <= 3 and "━" not in row   # надпись в своём дне, без полосы
        assert any("☑ 15:20 Сделано" in l for l in lines)
        # «Два дня» — полоса со второго дня (пт) по третий (сб) внутри рамки.
        day = graph._day_w
        row = next(l for l in lines if "Два дня" in l)
        assert row.index("╺") == day and row.index("╸") == 3 * day - 1
        assert sum(1 for l in lines if l.strip() and l.strip()[0] in "╺‹╭╰│┊") >= 5   # всё строками, без окошек
        for y in range(graph.size.height):
            assert graph.render_line(y).cell_length == graph.size.width


async def test_graph_scrolls_days_and_returns_today(tmp_path):
    app, path = make(tmp_path, GRAPH_FILE)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        await pilot.press("l")
        assert view_text(graph)[0].startswith(" пт 06.11")
        assert "Сегодня" not in [n.title for n in graph.cards]
        for _ in range(9):
            await pilot.press("l")
        assert "Вне окна" in [n.title for n in graph.cards]
        await pilot.press("0")
        assert graph.start == NOW.date()
        await pilot.press("h")
        assert view_text(graph)[0].startswith(" ср 04.11")


async def test_graph_selection_lights_nested_and_edits_only_selected(tmp_path):
    app, path = make(tmp_path, GRAPH_FILE)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        await pilot.press("g", "g", "j")
        week = graph.current()
        assert week.title == "Неделя"
        assert _row_bg(graph, "Сегодня") == {SELECTED_BG}
        assert _row_bg(graph, "Длинная") == {BACKGROUND}
        await pilot.press("space")
        assert week.status == "todo" and [c.status for c in week.children] == [None, None]
        await pilot.press("j", "j")
        assert graph.current().title == "Два дня"
        await pilot.press("enter")
        await pilot.pause()
        assert app.mode == "map" and app.sel.title == "Два дня"


async def test_graph_narrow_puts_nested_below(tmp_path):
    text = "# Т\n\n- a @2026-11-05\n  - b @2026-11-05\n    - c @2026-11-05\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        assert [n.title for n in graph.cards] == ["a", "b", "c"]
        tops = [r[0] for r in graph._ranges]
        assert tops == sorted(tops) and len(set(tops)) == 3
        for y in range(graph.size.height):
            assert graph.render_line(y).cell_length == graph.size.width


async def test_graph_empty_window_says_so(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- без даты\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        assert "Нет задач на эти дни" in view_text(app.query_graph())[2]


async def test_graph_one_day_child_inside_parent_frame(tmp_path):
    text = ("# Т\n\n- Юбилей @2026-11-01..2026-11-20\n  - плакат @2026-11-05\n"
            "  - сценка @2026-11-01..2026-11-20\n")
    app, path = make(tmp_path, text)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        rng = dict(zip((n.title for n in graph.cards), graph._ranges))
        assert [n.title for n in graph.cards] == ["Юбилей", "сценка", "плакат"]   # как на экране
        for kid in ("сценка", "плакат"):                                          # обе внутри рамки
            assert rng["Юбилей"][0] < rng[kid][0] and rng[kid][1] < rng["Юбилей"][1]
        assert any("плакат" in l for l in view_text(graph))                       # слово целиком
        await pilot.press("j", "j")
        assert graph.current().title == "плакат"
        await pilot.press("space")                    # выбор остаётся на той же задаче
        assert graph.current().title == "плакат" and graph.current().status == "todo"


SCALE_FILE = """# Т

- ▰▰▰▰ Проект @2026-11-02..2026-11-29
  - этап @2026-11-09..2026-11-15
  - мелочь @2026-11-10
- ▰▰▰ Педсовет @2026-11-18
- звонок @2026-11-03
- письмо @2026-11-03
- [x] сдано @2026-11-24
- ▰▰ Сборы @2026-12-07..2026-12-11
"""


async def test_graph_zoom_cycles_scales_and_tab_shows_it(tmp_path):
    from mindmap.graph import SCALE_NAMES
    app, path = make(tmp_path, SCALE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        seen = []
        for _ in range(4):
            await pilot.press("minus")
            seen.append((graph.scale, graph.start, graph.end))
        assert seen == [("month", date(2026, 11, 1), date(2026, 12, 1)),
                        ("quarter", date(2026, 10, 1), date(2027, 1, 1)),
                        ("year", date(2026, 1, 1), date(2027, 1, 1)),
                        ("year", date(2026, 1, 1), date(2027, 1, 1))]   # дальше некуда
        assert "график · год" in app.screen_stack[1].query_one("#tabs").render().plain
        await pilot.press("equals_sign")
        assert graph.scale == "quarter"
        await pilot.press("plus", "plus")
        assert graph.scale == "week" and graph.start == NOW.date()          # сегодня было в окне


async def test_graph_month_hides_one_day_and_counts_them(tmp_path):
    app, path = make(tmp_path, SCALE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        await pilot.press("minus")
        graph = app.query_graph()
        assert [n.title for n in graph.cards] == ["Проект", "этап", "Педсовет"]
        # Столбцы ноября: 01.11 (вс), 02.11, 09.11, 16.11, 23.11, 30.11.
        assert graph._hidden == [0, 2, 1, 0, 1, 0]       # звонок+письмо, мелочь, сдано
        lines = view_text(graph)
        assert " 2 " in lines[1] and " 1 " in lines[1]
        assert "02.11" in lines[0] and "01.11" not in lines[0]           # неполную неделю не подписываем
        assert any("◆ ▰▰▰ Педсовет" in l for l in lines)
        frame = next(l for l in lines if "Проект" in l)
        assert frame.lstrip().startswith("╭") or frame.lstrip().startswith("╔")
        row = next(l for l in lines if "этап" in l)
        assert "━" in row and row.count("│") + row.count("║") == 2       # внутри рамки проекта
        await pilot.press("G")
        assert graph.current().title == "Педсовет"                        # веху можно выбрать
        await pilot.press("space")
        assert "- [ ] ▰▰▰ Педсовет" in path.read_text(encoding="utf-8")
        for y in range(graph.size.height):
            assert graph.render_line(y).cell_length == graph.size.width


async def test_graph_long_scale_shifts_by_column_and_zero_returns(tmp_path):
    app, path = make(tmp_path, SCALE_FILE)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        await pilot.press("minus", "l")
        assert (graph.start, graph.end) == (date(2026, 11, 2), date(2026, 12, 7))
        assert "Сборы" not in [n.title for n in graph.cards]             # с 07.12 — за краем
        await pilot.press("right")
        assert graph.start == date(2026, 11, 9) and "Сборы" in [n.title for n in graph.cards]
        await pilot.press("h", "left", "h")
        assert graph.start == date(2026, 10, 19)
        await pilot.press("0")
        assert (graph.start, graph.end) == (date(2026, 11, 1), date(2026, 12, 1))
        await pilot.press("minus", "minus", "l")
        assert (graph.start, graph.end) == (date(2026, 2, 1), date(2027, 2, 1))
        assert view_text(graph)[0].lstrip().startswith("фев 26")


async def test_graph_bar_name_beside_and_arrows(tmp_path):
    text = "# Т\n\n- Длинное название задачи на квартал @2026-10-20..2027-02-01\n- Короткая @2026-11-16..2026-11-18\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        await pilot.press("minus", "minus")
        graph = app.query_graph()
        lines = view_text(graph)
        long = next(l for l in lines if "Длинное" in l)
        assert long.rstrip().endswith("›") and "╺ Длинное название" in long   # срок дальше окна, имя на полосе
        short = next(l for l in lines if "Короткая" in l)
        bar = short.index("╺")
        assert short.index("Короткая") > short.index("╸") > bar                # имя справа от полосы
        x0, x1 = graph._span(graph.cards[1], 0, graph._width - 1)
        assert x1 - x0 + 1 == short.index("╸") - bar + 1 and x1 - x0 < 12    # три дня — короткая полоса


async def test_graph_week_still_boxes_after_zoom(tmp_path):
    app, path = make(tmp_path, GRAPH_FILE)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause()
        await open_graph(pilot)
        graph = app.query_graph()
        before = view_text(graph)
        await pilot.press("minus", "plus")
        assert graph.scale == "week" and view_text(graph) == before


# ---------- заметки ----------

async def test_note_key_edits_saves_on_escape_and_undoes(tmp_path):
    from mindmap.dialogs import NoteDialog
    from textual.widgets import TextArea
    text = "# Т\n\n- a @2026-11-05\n  Ссылка: https://x.ru/\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "n")
        await pilot.pause()
        assert isinstance(app.screen, NoteDialog)
        await pilot.press(*"купить", "enter", *"молоко")
        assert app.screen.query_one(TextArea).text == "купить\nмолоко"
        await pilot.press("escape")
        await pilot.pause()
        assert path.read_text(encoding="utf-8") == "# Т\n\n- a @2026-11-05\n  купить\n  молоко\n  Ссылка: https://x.ru/\n"
        assert "✎" in app.query_map().render_line(1).text + app.query_map().render_line(0).text
        assert len(app.undo_stack) == 1

        await pilot.press("n")                       # без изменений — шага отмены нет
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "купить\nмолоко"
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.undo_stack) == 1

        await pilot.press("v")                       # на канбане та же клавиша и значок
        await pilot.pause()
        assert any("✎" in l for l in board_text(app))
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, NoteDialog)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("u")
        assert path.read_text(encoding="utf-8") == text


async def test_note_blocked_on_stub(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- a\n  - [x] b\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "l", "n")
        await pilot.pause()
        assert isinstance(app.sel, DoneStub)
        assert "za — показать" in app.message


# ---------- провалено и критерии ----------

async def test_space_cycles_through_failed(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- a\n- b\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "space", "space")          # нет → не завершено → завершено
        assert "- [x] a" in path.read_text(encoding="utf-8")
        assert isinstance(app.sel, DoneStub)
        await pilot.press("z", "a", "j", "space")         # завершено → провалено
        assert "- [-] a" in path.read_text(encoding="utf-8")
        assert app.sel.title == "a" and kids_of(app, app.root)[0].title == "… завершено: 1✗, показаны"
        await pilot.press("space")                        # провалено → не завершено
        assert "- [ ] a" in path.read_text(encoding="utf-8")
        await pilot.press("u")
        assert "- [-] a" in path.read_text(encoding="utf-8")


async def test_finished_not_on_board(tmp_path):
    app, path = make(tmp_path, "# Т\n\n- [-] провал @2026-11-01\n- [x] сделано @2026-11-02\n- [ ] открыто @2026-11-06\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        board = app.query_board()
        assert [[n.title for n in col] for col in board.cards] == [[], ["открыто"]]
        assert not any("сделано" in board.render_line(y).text or "провал" in board.render_line(y).text
                       for y in range(board.size.height))


async def test_board_close_opens_criteria(tmp_path):
    from mindmap.dialogs import CriteriaDialog
    text = "# Т\n\n- [ ] a @2026-11-05\n  Критерий: [ ] всё сдали\n- [ ] b @2026-11-06\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert app.query_board().current().title == "a"
        await pilot.press("space")
        await pilot.pause()
        # Карточка ушла с доски, а окно критериев открыто именно для неё.
        assert isinstance(app.screen, CriteriaDialog)
        assert app.screen.title_text == "a"
        await pilot.press("space", "escape")          # оценить критерий
        await pilot.pause()
        assert "Критерий: [x] всё сдали" in path.read_text(encoding="utf-8")
        assert "- [x] a" in path.read_text(encoding="utf-8")
        assert app.query_board().current().title == "b"


async def test_criteria_dialog_add_rate_review_and_one_undo(tmp_path):
    from mindmap.dialogs import CriteriaDialog, CriterionForm, KindDialog, NoteDialog, ReviewForm
    text = "# Т\n\n- Пробник @2026-11-20\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "g", "k")
        await pilot.pause()
        assert isinstance(app.screen, CriteriaDialog)
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, CriterionForm)
        await pilot.press(*"балл 15", "tab", *"13,4", "enter")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.press(*"все написали", "enter")
        await pilot.pause()
        await pilot.press("space", "space")               # второй: ○ → ✓ → ✗
        await pilot.press("K")                            # второй встаёт первым
        await pilot.press("j", "space")                   # «балл»: ○ → ✓
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, KindDialog)
        await pilot.press("3")
        await pilot.pause()
        assert isinstance(app.screen, ReviewForm)
        await pilot.press(*"субботы", "tab", *"план", "enter")
        await pilot.pause()
        assert isinstance(app.screen, CriteriaDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert path.read_text(encoding="utf-8") == (
            "# Т\n\n- Пробник @2026-11-20\n"
            "  Критерий: [-] все написали\n"
            "  Критерий: [x] балл 15 → 13,4\n"
            "  Разбор: форсаж\n  Причина: субботы\n  Меняем: план\n")
        assert len(app.undo_stack) == 1
        assert "◎" in app.query_map().render_line(0).text

        await pilot.press("g", "k")                       # открыть и закрыть без правок
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.undo_stack) == 1

        await pilot.press("n")                            # заметка критериев не видит
        await pilot.pause()
        assert isinstance(app.screen, NoteDialog)
        from textual.widgets import TextArea
        assert app.screen.query_one(TextArea).text == ""
        await pilot.press(*"текст", "escape")
        await pilot.pause()
        assert "  текст\n  Критерий: [-] все написали\n" in path.read_text(encoding="utf-8")

        await pilot.press("u", "u")
        assert path.read_text(encoding="utf-8") == text


async def test_closing_task_with_unrated_criteria_keeps_it_and_reminds(tmp_path):
    from mindmap.dialogs import CriteriaDialog, KindDialog
    text = "# Т\n\n- [ ] a\n  Критерий: [ ] сделано вовремя\n- b\n"
    app, path = make(tmp_path, text)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "space")                   # не завершено → завершено
        assert app.message == "Оцените критерии и разбор: gk"
        assert app.sel.title == "a"                       # не ушла за «…»
        await pilot.press("space")                        # → провалено
        await pilot.press("g", "k")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, KindDialog) and app.screen.current == "провал"
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert not isinstance(app.screen, (CriteriaDialog, KindDialog))


async def test_criteria_blocked_on_stub_and_available_on_board_and_graph(tmp_path):
    from mindmap.dialogs import CriteriaDialog
    app, path = make(tmp_path, "# Т\n\n- a @2026-11-05\n  - [x] b\n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l", "l", "g", "k")
        await pilot.pause()
        assert isinstance(app.sel, DoneStub) and "za — показать" in app.message
        for _ in range(2):                                # канбан, затем график
            await pilot.press("v")
            await pilot.pause()
            await pilot.press("g", "k")
            await pilot.pause()
            assert isinstance(app.screen, CriteriaDialog)
            await pilot.press("escape")
            await pilot.pause()


async def test_copy_without_clipboard_program_uses_terminal(tmp_path, monkeypatch):
    """Linux без wl-copy/xclip/xsel: копирование идёт через терминал (OSC 52)."""
    def missing(text):
        raise FileNotFoundError("нет программы буфера")
    monkeypatch.setattr("mindmap.app.pbcopy", missing)
    app, path = make(tmp_path, "# Т\n\n- a\n")
    sent = []
    monkeypatch.setattr(app, "copy_to_clipboard", sent.append)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await go_to(pilot, app, "a")
        await pilot.press("y", "y")
        assert sent == ["- a\n"] and app.message.startswith("Скопировано: 1")
