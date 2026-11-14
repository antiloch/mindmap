from datetime import date, datetime
from pathlib import Path

import pytest
from rich.cells import cell_len

from mindmap import links
from mindmap.board import crumb, nest
from mindmap.dates import parse_input, period_from_token
from mindmap.graph import bar_text, collect as graph_collect, days_of
from mindmap.keys import Chord, GRAPH_KEYS, MAP_KEYS, normalize
from mindmap.layout import INNER, box_lines, compute, visible_children
from mindmap.mdformat import dump, parse
from mindmap.model import DONE, TODO, DoneStub, Node, done_hidden
from mindmap import status as st

NOW = datetime(2026, 11, 5, 12, 0)  # четверг; неделя 02–08.11, следующая 09–15.11


def n(token=None, status=TODO):
    return Node("x", status, period_from_token(token) if token else None)


@pytest.mark.parametrize("token,expected", [
    ("2026-11-03", st.RED),
    ("2026-11-05T10:00..2026-11-05T11:00", st.RED),
    ("2025", st.RED),
    ("2026-11-05", st.ORANGE),
    ("2026-11-05T15:00", st.ORANGE),
    ("2026-11-06", st.ORANGE),
    ("2026-11-02..2026-11-20", st.ORANGE),
    ("2026", st.ORANGE),
    ("2026..2027", st.ORANGE),
    ("2026-11", st.ORANGE),
    ("2026-11-07..2026-11-25", st.ORANGE),   # начнётся позже на этой неделе
    ("2026-11-08", st.ORANGE),
    ("2026-11-09", st.GREEN),
    ("2026-11-10", st.GREEN),
    ("2026-11-09..2026-11-15", st.GREEN),    # ровно 7 дней
    ("2026-11-15..2026-11-17", st.GREEN),    # короткий, начало на следующей неделе
    ("2026-11-09..2026-11-16", st.PLAIN),    # 8 дней — зелёным не красим
    ("2026-11-16", st.PLAIN),
    ("2026-11-20", st.PLAIN),
    ("2027", st.PLAIN),
])
def test_colors(token, expected):
    assert st.classify(n(token), NOW) == expected


def test_color_no_date_and_done():
    assert st.classify(n(None), NOW) == st.PLAIN
    assert st.classify(n(None, None), NOW) == st.PLAIN
    assert st.classify(n("2026-11-03", DONE), NOW) == st.GREY
    assert st.classify(n("2027", DONE), NOW) == st.GREY
    assert st.classify(n(None, DONE), NOW) == st.GREY


def test_overdue_without_status_is_red():
    assert st.classify(n("2026-11-03", None), NOW) == st.RED
    assert st.bucket(n("2026-11-03", None), NOW) == st.B_OVERDUE


def test_week_boundary():
    sunday = datetime(2026, 11, 8, 23, 59)
    monday = datetime(2026, 11, 9, 0, 0)
    item = n("2026-11-09")
    assert st.classify(item, sunday) == st.GREEN
    assert st.classify(item, monday) == st.ORANGE
    assert st.classify(n("2026-11-08"), sunday) == st.ORANGE
    assert st.classify(n("2026-11-08"), monday) == st.RED


@pytest.mark.parametrize("token,place", [
    ("2026-11-05", st.B_TODAY),
    ("2026-11-02..2026-11-05", st.B_TODAY),
    ("2026-11-05T15:00..2026-11-05T16:00", st.B_TODAY),
    ("2026-11-03", st.B_OVERDUE),
    ("2026-11-06", st.B_WEEK),
    ("2026-11-02..2026-11-08", st.B_WEEK),
    ("2026-11-07..2026-11-10", st.B_WEEK),
    ("2026", st.B_RUNNING),
    ("2026-11-02..2026-11-20", st.B_RUNNING),
    ("2026-11-10", st.B_PLANNED),
    ("2027", st.B_PLANNED),
])
def test_board_buckets(token, place):
    assert st.bucket(n(token), NOW) == place


def test_board_rules_without_date():
    assert st.bucket(n(None), NOW) is None
    assert st.bucket(n(None, None), NOW) is None
    assert st.bucket(n(None, DONE), NOW) is None
    assert st.bucket(n("2026-11-03", DONE), NOW) == st.B_DONE


@pytest.mark.parametrize("text,token", [
    ("2026", "2026"),
    ("2026-2027", "2026..2027"),
    ("2026–2027", "2026..2027"),
    ("с 2026 по 2027", "2026..2027"),
    ("11.2026", "2026-11"),
    ("2026-11", "2026-11"),
    ("11.2026-01.2027", "2026-11..2027-01"),
    ("ноябрь 2026", "2026-11"),
    ("ноябрь", "2026-11"),
    ("ноябрь-декабрь 2026", "2026-11..2026-12"),
    ("05.11", "2026-11-05"),
    ("05.11.2026", "2026-11-05"),
    ("5.11.26", "2026-11-05"),
    ("05-07.11", "2026-11-05..2026-11-07"),
    ("05.11-07.12", "2026-11-05..2026-12-07"),
    ("25.12-10.01", "2026-12-25..2027-01-10"),
    ("25.12-10.01.2027", "2026-12-25..2027-01-10"),
    ("05.11 15:20", "2026-11-05T15:20"),
    ("05.11 15:20-16:00", "2026-11-05T15:20..2026-11-05T16:00"),
    ("05.11.2026 15:20 - 07.11.2026 10:00", "2026-11-05T15:20..2026-11-07T10:00"),
    ("2026-11-05", "2026-11-05"),
    ("2026-11-05 15:20", "2026-11-05T15:20"),
    ("2026-11-05..2026-11-07", "2026-11-05..2026-11-07"),
    ("сегодня", "2026-11-05"),
    ("завтра", "2026-11-06"),
    ("пт", "2026-11-06"),
    ("чт", "2026-11-05"),
    ("ср", "2026-11-11"),
    ("сегодня 15:00-16:00", "2026-11-05T15:00..2026-11-05T16:00"),
    ("сегодня-пт", "2026-11-05..2026-11-06"),
    ("15:00", "2026-11-05T15:00"),
    ("10.01", "2027-01-10"),                 # давно прошло — следующий год
    ("10.10", "2026-10-10"),                 # недавно — этот год
])
def test_date_input(text, token):
    assert parse_input(text, NOW).token() == token


@pytest.mark.parametrize("text", [
    "2027-2026", "07.11-05.11.2026", "32.11.2026", "31.02.2026", "ерунда", "05", "25:00",
    "13.2026", "2026-13", "05.11 25:00",
])
def test_date_input_errors(text):
    with pytest.raises(ValueError):
        parse_input(text, NOW)


def test_date_input_empty_clears():
    assert parse_input("   ", NOW) is None


@pytest.mark.parametrize("token,shown", [
    ("2026", "2026"),
    ("2026..2027", "2026 – 2027"),
    ("2026-11", "11.2026"),
    ("2026-11..2026-12", "11.2026 – 12.2026"),
    ("2026-11..2027-01", "11.2026 – 01.2027"),
    ("2026-11-05", "05.11.2026"),
    ("2026-11-05..2026-11-07", "05.11.2026 – 07.11.2026"),
    ("2026-11-05..2026-12-07", "05.11.2026 – 07.12.2026"),
    ("2026-12-25..2027-01-10", "25.12.2026 – 10.01.2027"),
    ("2026-11-05T15:20", "05.11.2026 15:20"),
    ("2026-11-05T15:20..2026-11-05T16:00", "05.11.2026 15:20 – 05.11.2026 16:00"),
    ("2026-11-05T15:20..2026-11-07T10:00", "05.11.2026 15:20 – 07.11.2026 10:00"),
    ("2026..2026-11-05", "2026 – 05.11.2026"),
])
def test_date_show_and_reinput(token, shown):
    p = period_from_token(token)
    assert p.show() == shown
    assert parse_input(p.show(), NOW).token() == token   # окно ввода читает своё же


@pytest.mark.parametrize("text", ["завтра", "пт", "6.11", "06.11.26", "2026-11-06", "6 . 11".replace(" ", "")])
def test_date_look_does_not_depend_on_input(text):
    assert parse_input(text, NOW).show() == "06.11.2026"


CANON = """# Работа

- Устные зачёты @2026-11-02..2026-11-06
  - [x] Вопросы @2026-11-03
  - [ ] Провести @2026-11-06T15:20..2026-11-06T16:00
    Заметка под пунктом
      с отступом

    и после пустой строки
  - Идея без статуса и даты
- [ ] Цели кафедры @2026..2027 <!--collapsed-->
  - скрытый пункт
- [x] Без даты
- Только дата @2026

# [ ] Личное @2026

Заметка главной темы

- Адрес a@b.ru
- Встреча \\@2026
- \\[x] не статус

# Пустая
"""


def test_roundtrip_exact():
    assert dump(parse(CANON)) == CANON


def test_parse_structure():
    doc = parse(CANON)
    assert [s.title for s in doc.sheets] == ["Работа", "Личное", "Пустая"]
    first = doc.sheets[0].children[0]
    assert first.status is None and first.period.token() == "2026-11-02..2026-11-06"
    assert first.children[0].status == DONE
    assert first.children[1].status == TODO
    assert doc.sheets[0].children[1].collapsed
    assert doc.sheets[1].status == TODO and doc.sheets[1].period.token() == "2026"
    assert doc.sheets[1].children[0].title == "Адрес a@b.ru"
    assert doc.sheets[1].children[1].title == "Встреча @2026"
    assert doc.sheets[1].children[1].period is None
    assert doc.sheets[1].children[2].title == "[x] не статус"
    assert doc.sheets[1].children[2].status is None


def test_tricky_titles_survive_save():
    root = Node("Т")
    for title in ["Встреча @2026", "[x] в скобках", "[ ] тоже", "конец @2026-11-05..2026-11-07"]:
        root.add(Node(title))
    root.add(Node("Встреча @2026", TODO, period_from_token("2027")))
    from mindmap.model import Document
    back = parse(dump(Document([root]))).sheets[0]
    assert [c.title for c in back.children] == [c.title for c in root.children]
    assert [c.status for c in back.children] == [c.status for c in root.children]
    assert back.children[-1].period.token() == "2027"


def test_handwritten_file():
    text = "Вступление\n\n# Т\n\n* a\n    + b\n\t\t- c\n1. d\n2) [X] e @2026-13\n- [ ]\n-\n"
    doc = parse(text)
    assert doc.preamble == ["Вступление"]
    root = doc.sheets[0]
    assert [c.title for c in root.children] == ["a", "d", "e @2026-13", "", ""]
    assert root.children[0].children[0].title == "b"
    assert root.children[0].children[0].children[0].title == "c"
    assert root.children[2].status == DONE
    assert root.children[3].status == TODO
    assert root.children[4].status is None
    # Запись приводит к единому виду и дальше не меняется.
    once = dump(doc)
    assert dump(parse(once)) == once


def test_file_without_heading_and_empty():
    doc = parse("- a\n- b\n", "Имя")
    assert doc.sheets[0].title == "Имя" and len(doc.sheets[0].children) == 2
    assert parse("", "Имя").sheets[0].title == "Имя"


def test_code_fence_is_note():
    text = "# Т\n\n- a\n  ```\n  - не пункт\n  # не вкладка\n  ```\n"
    doc = parse(text)
    assert len(doc.sheets) == 1 and not doc.sheets[0].children[0].children
    assert dump(doc) == text


def build_tree():
    root = Node("Главная тема с длинным названием, которое переносится на следующие строки окошка")
    for i in range(6):
        a = root.add(Node(f"Ветка {i}", TODO if i % 2 else None, period_from_token("2026-11-05") if i % 3 else None))
        for j in range(i):
            b = a.add(Node(f"Подветка {i}.{j}", DONE))
            for k in range(j):
                b.add(Node(f"Лист {k} " * 8, TODO, period_from_token("2026-11-05T15:20..2026-11-07T10:00")))
    return root


def test_layout_right_only_no_overlap():
    lay = compute(build_tree())
    boxes = lay.boxes
    assert boxes[0].x == 0
    for box in boxes:
        assert box.x >= 0 and box.y >= 0
        assert box.w == 28  # все блоки одной ширины
        for kid in box.kids:
            assert kid.x >= box.x + box.w  # дети строго правее родителя
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            apart = a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y
            assert apart, (a.node, b.node)


def test_branches_go_right_and_down():
    lay = compute(build_tree())
    assert (lay.boxes[0].x, lay.boxes[0].y) == (0, 0)  # главная тема в левом верхнем углу
    for box in lay.boxes:
        if box.kids:
            assert box.kids[0].y == box.y        # первый ребёнок вровень с родителем
        for upper, lower in zip(box.kids, box.kids[1:]):
            assert lower.y >= upper.y + upper.h  # остальные ниже
    # Столбцы карты ровные: положение зависит только от глубины.
    for box in lay.boxes:
        assert box.x == box.depth * (28 + 4)


def test_connector_shape():
    root = Node("r")
    for name in "abc":
        root.add(Node(name))
    lay = compute(root)
    rows = {y: "".join(t for x, t in sorted(items)) for y, items in lay.lines.items()}
    a, b, c = lay.boxes[1:]
    assert rows[a.anchor] == "─┬──"
    assert rows[b.anchor] == "├──"
    assert rows[c.anchor] == "╰──"
    single = Node("r")
    single.add(Node("a"))
    assert {y: "".join(t for x, t in sorted(i)) for y, i in compute(single).lines.items()} == {1: "────"}


def test_lines_do_not_cross_boxes():
    lay = compute(build_tree())
    for y, items in lay.lines.items():
        for x, text in items:
            for box in lay.boxes:
                inside = box.x <= x < box.x + box.w and box.y <= y < box.y + box.h
                assert not inside, (x, y, text, box.node)


def test_collapsed_hides_and_counts():
    root = Node("r")
    a = root.add(Node("a", collapsed=True))
    b = a.add(Node("b"))
    b.add(Node("c"))
    lay = compute(root)
    assert [box.node.title for box in lay.boxes] == ["r", "a"]
    assert lay.by_node[id(a)].hidden == 2


def test_counter():
    from mindmap.layout import counter
    root = Node("r")
    root.add(Node("a", DONE))
    root.add(Node("b", TODO))
    root.add(Node("c"))
    assert counter(root) == "1/2"
    assert counter(root.children[2]) == ""


def test_infinite_nesting():
    depth = 10_000
    root = Node("r")
    cur = root
    for i in range(depth):
        cur = cur.add(Node(f"п{i}", TODO))
    from mindmap.model import Document
    text = dump(Document([root]))
    back = parse(text).sheets[0]
    assert sum(1 for _ in back.walk()) == depth + 1
    assert dump(Document([back])) == text
    assert sum(1 for _ in back.clone().walk()) == depth + 1
    lay = compute(back)
    assert len(lay.boxes) == depth + 1
    assert lay.boxes[-1].x > lay.boxes[-2].x


def test_chords_and_russian_layout():
    c = Chord()
    assert c.feed("d", MAP_KEYS) is None
    assert c.feed("d", MAP_KEYS) == "cut"
    assert normalize("в", "в") == "d"
    assert normalize("Р", "Р") == "H"
    assert normalize("Ж", "Ж") == ":"
    assert normalize("up", None) == "up"
    assert normalize("space", " ") == "space"
    assert c.feed("g", MAP_KEYS) is None
    assert c.feed("t", MAP_KEYS) == "tab_next"
    # Сорвавшаяся последовательность: «d», затем «j» — просто движение вниз.
    assert c.feed("d", MAP_KEYS) is None
    assert c.feed("j", MAP_KEYS) == "go_down"
    # Esc сбрасывает.
    assert c.feed("z", MAP_KEYS) is None
    assert c.feed("escape", MAP_KEYS) is None
    assert c.feed("a", MAP_KEYS) == "new_child"


# ---------- приоритет ----------

@pytest.mark.parametrize("head,priority,title", [
    ("▰▰▰▰ важно", 1, "важно"),
    ("▰▰▰ важно", 2, "важно"),
    ("▰▰ важно", 3, "важно"),
    ("▰ важно", 4, "важно"),
    ("❶ важно", 1, "важно"),
    ("❹ важно", 4, "важно"),
    ("▰▰▰▰▰ пять", None, "▰▰▰▰▰ пять"),   # такого уровня нет
    ("▰важно", None, "▰важно"),            # без пробела это название
    ("важно ▰", None, "важно ▰"),
])
def test_priority_read(head, priority, title):
    node = parse(f"# Т\n\n- {head}\n").sheets[0].children[0]
    assert (node.priority, node.title) == (priority, title)


def test_priority_written_as_bars_next_to_status_and_date():
    text = "# ❷ Вкладка\n\n- [x] ❶ Пункт @2026-11-07 <!--collapsed-->\n  - [ ] ▰ Внук\n"
    doc = parse(text)
    assert doc.sheets[0].priority == 2
    out = dump(doc)
    assert out == "# ▰▰▰ Вкладка\n\n- [x] ▰▰▰▰ Пункт @2026-11-07 <!--collapsed-->\n  - [ ] ▰ Внук\n"
    assert dump(parse(out)) == out


def test_priority_survives_clone():
    node = parse("# Т\n\n- ▰▰ a\n").sheets[0].children[0]
    assert node.clone().priority == 3


def test_priority_in_box_line():
    node = parse("# Т\n\n- ▰▰▰▰ a\n").sheets[0].children[0]
    assert box_lines(node)[0] == "▰▰▰▰ a"


# ---------- ссылки ----------

def _sheets(text):
    return parse(text).sheets


@pytest.mark.parametrize("text,kind,target", [
    ("https://thecode.media/launchctl/", links.WEB, "https://thecode.media/launchctl/"),
    ("  http://a.ru  ", links.WEB, "http://a.ru"),
    ("www.a.ru/x", links.WEB, "https://www.a.ru/x"),
    ("mailto:a@b.ru", links.WEB, "mailto:a@b.ru"),
    ("/Users/a/отчёт.pdf", links.FILE, "/Users/a/отчёт.pdf"),
    ("~/Desktop/a.pdf", links.FILE, "~/Desktop/a.pdf"),
    ("./a.pdf", links.FILE, "./a.pdf"),
    ("../a.pdf", links.FILE, "../a.pdf"),
    ("file:///Users/a/b.pdf", links.FILE, "file:///Users/a/b.pdf"),
    ("/Users/a/My\\ file\\ \\(1\\).pdf ", links.FILE, "/Users/a/My file (1).pdf"),  # перетащили в Terminal
    ("'/Users/a/My file.pdf'", links.FILE, "/Users/a/My file.pdf"),
    ("цел", links.ITEM, "Цель"),
])
def test_link_input(text, kind, target):
    link = links.parse_input(text, _sheets("# Т\n\n- Цель\n- сам\n"))
    assert (link.kind, link.target) == (kind, target)


def test_link_input_empty_and_errors():
    sheets = _sheets("# Т\n\n- план а\n- план б\n- Цель\n")
    assert links.parse_input("   ", sheets) is None
    with pytest.raises(ValueError, match="Нет такого"):
        links.parse_input("нечто", sheets)
    with pytest.raises(ValueError, match="Подходит пунктов: 2"):
        links.parse_input("план", sheets)
    # Точное совпадение важнее части названия.
    assert links.parse_input("план", _sheets("# Т\n\n- план\n- план б\n")).target == "план"
    # Сам пункт не цель.
    sheets = _sheets("# Т\n\n- Цель\n")
    with pytest.raises(ValueError):
        links.parse_input("цель", sheets, sheets[0].children[0])


def test_links_read_add_remove_keep_other_notes():
    node = parse("# Т\n\n- a\n  заметка\n  Ссылка: https://a.ru/\n  Ссылка на пункт: b\n  Ссылка:\n").sheets[0].children[0]
    found = links.read(node)
    assert [(l.kind, l.target) for l in found] == [(links.WEB, "https://a.ru/"), (links.ITEM, "b")]
    assert links.add(node, found[0]) is False
    assert links.add(node, links.Link(links.FILE, "~/a.pdf")) is True
    assert node.notes[-1] == "Ссылка: ~/a.pdf"
    links.remove(node, found[0])
    assert node.notes[0] == "заметка"
    assert "Ссылка: https://a.ru/" not in node.notes
    assert "Ссылка:" in node.notes                 # пустая строка — просто заметка


@pytest.mark.parametrize("note,line", [
    ("Ссылка: https://www.thecode.media/launchctl/", "↗ thecode.media"),
    ("Ссылка: mailto:a@b.ru", "↗ a@b.ru"),
    ("Ссылка: ~/Desktop/отчёт.pdf", "↗ отчёт.pdf"),
    ("Ссылка: ~/Desktop/папка/", "↗ папка"),
    ("Ссылка: xmind:#380b", "↗ xmind:#380b"),
    ("Ссылка на пункт: Цель", "→ Цель"),
])
def test_link_line_in_box(note, line):
    node = parse(f"# Т\n\n- a @2026\n  {note}\n").sheets[0].children[0]
    assert box_lines(node) == ["a", "2026", line]


def test_link_box_line_several_and_long():
    node = parse("# Т\n\n- a\n  Ссылка: https://a.ru/\n  Ссылка: https://b.ru/\n").sheets[0].children[0]
    assert box_lines(node)[-1] == "↗ ссылок: 2"
    node = parse("# Т\n\n- a\n  Ссылка на пункт: " + "очень длинное название пункта карты\n").sheets[0].children[0]
    last = box_lines(node)[-1]
    assert len(box_lines(node)) == 2 and last.endswith("…") and cell_len(last) <= INNER


def test_file_path(tmp_path):
    assert links.file_path(links.Link(links.FILE, "./a b.pdf"), tmp_path) == (tmp_path / "a b.pdf").resolve()
    assert links.file_path(links.Link(links.FILE, "file:///x/%D1%84.pdf"), tmp_path) == Path("/x/ф.pdf")
    assert links.file_path(links.Link(links.FILE, "~/a"), tmp_path) == Path.home() / "a"


def test_is_runnable(tmp_path):
    plain = tmp_path / "a.pdf"
    plain.write_text("x")
    assert not links.is_runnable(plain)
    assert not links.is_runnable(tmp_path)         # папка показывается в Finder
    assert links.is_runnable(tmp_path / "Prog.APP")
    tool = tmp_path / "tool"
    tool.write_text("x")
    tool.chmod(0o755)
    assert links.is_runnable(tool)                 # без расширения, но запускается


# ---------- вложенные карточки ----------

def _dated(text):
    return [n for n in parse(text).sheets[0].walk() if n.period]


def test_nest_by_branch_and_period():
    nodes = _dated("# Т\n\n- a @2026\n  - b @2026-11\n    - c @2026-11-05\n  - шире @2026..2027\n- d @2026-11\n")
    tops, kids = nest(nodes)
    assert [n.title for n in tops] == ["a", "шире", "d"]        # d из другой ветки, шире — не внутри срока
    assert [n.title for n in kids[id(nodes[0])]] == ["b"]
    assert [n.title for n in kids[id(nodes[1])]] == ["c"]


def test_nest_equal_period_and_skips_middle_without_date():
    nodes = _dated("# Т\n\n- a @2026-10..2027-01\n  - без срока\n    - b @2026-10..2027-01\n")
    tops, kids = nest(nodes)
    assert tops == [nodes[0]] and kids[id(nodes[0])] == [nodes[1]]
    assert crumb(nodes[1], False, nodes[0]) == "без срока"
    assert crumb(nodes[1], False) == "a › без срока"


def test_nest_host_must_be_in_same_section():
    nodes = _dated("# Т\n\n- a @2026\n  - b @2026-11\n")
    assert nest([nodes[1]]) == ([nodes[1]], {})


def test_nest_by_window_span():
    """На графике вкладывание считается по дням в окне: ребёнок шире родителя по сроку,
    но в пределах окна внутри — вложен."""
    nodes = _dated("# Т\n\n- a @2026-11-05..2026-11-11\n  - b @2026-11-10..2026-11-20\n")
    start = date(2026, 11, 5)
    assert nest(nodes) == (nodes, {})
    tops, kids = nest(nodes, lambda n: days_of(n, start))
    assert tops == [nodes[0]] and kids[id(nodes[0])] == [nodes[1]]


# ---------- завершённые за «…» ----------

def test_stub_first_and_done_hidden():
    root = parse("# Т\n\n- a\n  - [x] b\n    - c\n  - d\n- [x] e\n").sheets[0]
    a = root.children[0]
    stubs = {}
    kids = visible_children(a, set(), stubs)
    assert isinstance(kids[0], DoneStub) and kids[0].host is a and kids[0].count == 1
    assert [n.title for n in kids[1:]] == ["d"]
    assert visible_children(a, {id(a)}, stubs)[0] is kids[0]       # то же окошко
    assert [n.title for n in visible_children(a, {id(a)}, stubs)[1:]] == ["b", "d"]
    c = a.children[0].children[0]
    assert done_hidden(c, set()) and not done_hidden(c, {id(a)})
    assert not done_hidden(root, set())                            # главная тема не прячется
    plan = compute(root)
    assert sorted(b.node.title for b in plan.boxes) == sorted(["Т", "… завершено: 1✓", "a", "… завершено: 1✓", "d"])
    assert kids[0].path() == a.path() and kids[0] not in a.children
    assert "… завершено" not in dump(parse("# Т\n\n- a\n  - [x] b\n"))


def test_collapsed_has_no_stub():
    root = parse("# Т\n\n- a <!--collapsed-->\n  - [x] b\n").sheets[0]
    assert visible_children(root.children[0], set(), {}) == []


# ---------- сетевой график ----------

def test_graph_collect_and_days():
    root = parse("# Т\n\n- раньше @2026-11-01..2026-11-04\n- задевает @2026-11-04..2026-11-06\n"
                 "- год @2026\n- позже @2026-11-12\n- последний @2026-11-11T23:00\n- ▰ важный @2026-11-09\n").sheets[0]
    start = date(2026, 11, 5)
    got = graph_collect([root], start)
    assert [n.title for n in got] == ["важный", "год", "задевает", "последний"]
    spans = {n.title: days_of(n, start) for n in got}
    assert spans == {"важный": (4, 4), "год": (0, 6), "задевает": (0, 1), "последний": (6, 6)}


def test_graph_bar_text():
    root = parse("# Т\n\n- [x] ▰▰ Сделать @2026-11-05T15:20\n- [ ] Раньше @2026-11-01T09:00..2026-11-06\n").sheets[0]
    start = date(2026, 11, 5)
    assert bar_text(root.children[0], start) == "☑ ▰▰ 15:20 Сделать"
    assert bar_text(root.children[0]) == "☑ ▰▰ Сделать"                    # крупный масштаб — без времени
    assert bar_text(root.children[1], start) == "☐ Раньше"                 # время начала вне окна


def test_graph_scale_bounds_and_columns():
    from mindmap.graph import bounds, columns
    d = date(2026, 11, 13)
    assert bounds("week", d) == (d, date(2026, 11, 20))
    assert bounds("month", d) == (date(2026, 11, 1), date(2026, 12, 1))
    assert bounds("quarter", d) == (date(2026, 10, 1), date(2027, 1, 1))
    assert bounds("year", d) == (date(2026, 1, 1), date(2027, 1, 1))
    assert bounds("month", date(2026, 12, 31)) == (date(2026, 12, 1), date(2027, 1, 1))
    # Ноябрь 2026 начинается в воскресенье: первый столбец — неполная неделя из одного дня.
    cols = columns("month", *bounds("month", d))
    assert cols == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16),
                    date(2026, 11, 23), date(2026, 11, 30)]
    assert len(columns("quarter", *bounds("quarter", d))) == 14
    assert columns("year", *bounds("year", d))[1:3] == [date(2026, 2, 1), date(2026, 3, 1)]
    assert len(columns("week", *bounds("week", d))) == 7


def test_graph_shift_by_one_column():
    from mindmap.graph import bounds, shifted
    d = date(2026, 11, 13)
    assert shifted("week", d, -1) == (date(2026, 11, 12), date(2026, 11, 19))
    start, _ = bounds("month", d)                                   # вс 01.11
    assert shifted("month", start, 1) == (date(2026, 11, 2), date(2026, 12, 7))   # 5 полных недель
    assert shifted("month", start, -1) == (date(2026, 10, 26), date(2026, 11, 30))
    assert shifted("quarter", date(2026, 11, 2), 1) == (date(2026, 11, 9), date(2027, 2, 8))
    assert shifted("year", date(2026, 12, 1), 1) == (date(2027, 1, 1), date(2028, 1, 1))
    assert shifted("year", date(2026, 1, 1), -1) == (date(2025, 12, 1), date(2026, 12, 1))


def test_graph_split_short_keeps_milestones():
    from mindmap.graph import split_short
    root = parse("# Т\n\n- день @2026-11-05\n- ▰▰▰▰ веха @2026-11-06\n- ▰▰▰ веха2 @2026-11-07T10:00\n"
                 "- ▰▰ мелкое @2026-11-08\n- ▰ ещё @2026-11-09\n- [x] сделано @2026-11-10\n"
                 "- два дня @2026-11-05..2026-11-06\n- месяц @2026-11\n").sheets[0]
    kept, hidden = split_short(list(root.children))
    assert [n.title for n in kept] == ["веха", "веха2", "два дня", "месяц"]
    assert hidden == [date(2026, 11, 5), date(2026, 11, 8), date(2026, 11, 9), date(2026, 11, 10)]


def test_graph_keys_share_commands_with_board():
    assert GRAPH_KEYS[("v",)] == "toggle_view"
    assert GRAPH_KEYS[("h",)] == "days_back" and GRAPH_KEYS[("l",)] == "days_forward"
    assert GRAPH_KEYS[("0",)] == "days_today" and GRAPH_KEYS[("enter",)] == "open_on_map"
    assert GRAPH_KEYS[("-",)] == "zoom_out" and GRAPH_KEYS[("+",)] == GRAPH_KEYS[("=",)] == "zoom_in"


# ---------- заметки ----------

def test_note_text_keeps_links_and_escapes_special_lines():
    from mindmap import notes
    from mindmap.layout import frame_label
    doc = parse("# Т\n\n- a\n  Ссылка: https://x.ru/\n- b\n")
    a = doc.sheets[0].children[0]
    assert notes.text(a) == "" and not notes.has(a) and frame_label(a) == ""
    value = "\nпервая\n\n  - похоже на пункт\n# похоже на вкладку\n```\nСсылка: не ссылка\n\\dfrac{1}{2}\n\n"
    a.notes = notes.lines_for(a, value)
    assert a.notes[-1] == "Ссылка: https://x.ru/"                 # ссылка на месте
    assert notes.has(a) and frame_label(a) == "✎"
    again = parse(dump(doc))
    a2 = again.sheets[0].children[0]
    assert [n.title for n in again.sheets[0].children] == ["a", "b"]   # заметка не стала пунктом
    assert notes.text(a2) == value.strip("\n")
    assert [l.target for l in links.read(a2)] == ["https://x.ru/"]
    assert notes.lines_for(a2, notes.text(a2)) == a2.notes           # повторная правка ничего не меняет


def test_frame_label_with_counter_and_root_note():
    from mindmap import notes
    from mindmap.layout import frame_label
    doc = parse("# Т\n\n- a\n  - [x] b\n")
    root, a = doc.sheets[0], doc.sheets[0].children[0]
    a.notes = notes.lines_for(a, "текст")
    assert frame_label(a) == "✎ 1/1" and frame_label(a, with_counter=False) == "✎"
    root.notes = notes.lines_for(root, "- не пункт\n# не вкладка")
    again = parse(dump(doc))
    assert len(again.sheets) == 1 and [n.title for n in again.sheets[0].children] == ["a"]
    assert notes.text(again.sheets[0]) == "- не пункт\n# не вкладка"


# ---------- провалено ----------

def test_failed_status_reads_writes_and_escapes():
    from mindmap.model import FAILED
    doc = parse("# Т\n\n- [-] провал @2026-11-01\n- \\[-] просто текст\n")
    a, b = doc.sheets[0].children
    assert a.status == FAILED and b.status is None and b.title == "[-] просто текст"
    assert dump(doc) == "# Т\n\n- [-] провал @2026-11-01\n- \\[-] просто текст\n"


def test_failed_color_bucket_counter_and_stub():
    from mindmap.layout import counter, stub_title, visible_children
    from mindmap.model import FAILED
    now = datetime(2026, 11, 5, 12, 0)
    root = parse("# Т\n\n- p\n  - [x] a\n  - [-] b @2026-11-01\n  - [ ] c\n").sheets[0]
    p = root.children[0]
    b = p.children[1]
    assert st.classify(b, now) == st.DARK_RED                # срок прошёл, но задача закрыта
    assert st.bucket(b, now) == st.B_DONE
    assert counter(p) == "1/3"                                 # провал — в знаменателе
    kids = visible_children(p, set(), {})
    assert kids[0].title == "… завершено: 1✓ 1✗" and kids[0].count == 2
    assert [n.title for n in kids[1:]] == ["c"]
    assert stub_title(0, 2, False) == "… завершено: 2✗"


# ---------- критерии успеха ----------

CRIT_TEXT = """# Т

- [-] Пробник @2026-11-20
  заметка
  Ссылка: https://x.ru/
  Критерий: [x] написали ≥ 90 % → 94 %
  Критерий: [-] средний балл ≥ 15 → 13,4
  Критерий: [ ] разбор с учителями
  Разбор: провал
  Причина: неделя олимпиад
  Меняем: сверять с графиком
"""


def test_criteria_read_write_roundtrip():
    from mindmap import criteria, notes
    from mindmap.layout import frame_label
    doc = parse(CRIT_TEXT)
    node = doc.sheets[0].children[0]
    items = criteria.read(node)
    assert items == [criteria.Criterion("написали ≥ 90 %", "x", "94 %"),
                     criteria.Criterion("средний балл ≥ 15", "-", "13,4"),
                     criteria.Criterion("разбор с учителями")]
    assert criteria.review(node) == criteria.Review("провал", "неделя олимпиад", "сверять с графиком")
    assert criteria.unrated(node)                               # третий не оценён
    assert notes.text(node) == "заметка"                       # заметка их не видит
    assert frame_label(node) == "✎ ◎"
    assert criteria.lines_for(node, items, criteria.review(node)) == node.notes
    assert dump(doc) == CRIT_TEXT

    node.notes = notes.lines_for(node, "новая\nПричина: это просто текст")   # правка заметки
    assert criteria.read(node) == items and len(links.read(node)) == 1
    assert notes.text(node) == "новая\nПричина: это просто текст"
    assert criteria.review(parse(dump(doc)).sheets[0].children[0]).cause == "неделя олимпиад"

    rated = [criteria.Criterion(c.text, "x", c.fact) for c in items]
    node.notes = criteria.lines_for(node, rated, criteria.Review())
    assert criteria.review(node) == criteria.Review() and criteria.unrated(node)   # нет вида разбора
    node.notes = criteria.lines_for(node, [], criteria.Review())
    assert not criteria.has(node) and links.read(node)


def test_criterion_without_mark_and_fact():
    from mindmap import criteria
    node = parse("# Т\n\n- a\n  Критерий: просто текст\n").sheets[0].children[0]
    assert criteria.read(node) == [criteria.Criterion("просто текст")]
    assert criteria.Criterion("x", "-", "3").show() == "✗ x → 3"


# ---------- система: macOS и Linux ----------

def test_linux_clipboard_and_open(monkeypatch):
    from mindmap import system
    monkeypatch.setattr(system, "MAC", False)
    have = {"xclip", "wl-copy", "xdg-open"}
    monkeypatch.setattr(system.shutil, "which", lambda name: name if name in have else None)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert system.copy_command() == ["xclip", "-selection", "clipboard"]          # X11
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert system.copy_command() == ["wl-copy"]                                   # Wayland
    have.clear()
    assert system.copy_command() is None
    with pytest.raises(FileNotFoundError):
        system.copy_text("x")
    calls = []
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    system.open_target("https://example.org")
    assert calls == [["xdg-open", "https://example.org"]]
    assert system.default_file() == Path.home() / "Карта.md"


def test_mac_clipboard_and_open(monkeypatch):
    from mindmap import system
    monkeypatch.setattr(system, "MAC", True)
    assert system.copy_command() == ["pbcopy"]
    calls = []
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    system.open_target("/tmp/a.pdf")
    assert calls == [["open", "/tmp/a.pdf"]]
    assert "Mobile Documents" in str(system.default_file())
