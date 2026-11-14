"""Клавиши в стиле vim: последовательности (dd, gg, za) и русская раскладка."""
from __future__ import annotations

_RU = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
_RU_UP = "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ"
_EN_UP = 'QWERTYUIOP{}ASDFGHJKL:"ZXCVBNM<>~'

# «.» на русской раскладке — это «/», но точка нужна сама по себе, поэтому её не трогаем.
_TABLE = {r: e for r, e in zip(_RU, _EN) if r != "."}
_TABLE.update(zip(_RU_UP, _EN_UP))


def to_latin(text: str) -> str:
    return "".join(_TABLE.get(ch, ch) for ch in text)


def normalize(key: str, character: str | None) -> str:
    """Имя клавиши для таблиц: буква в латинице либо up, space, ctrl+r и т. п."""
    if character and character.isprintable() and character != " ":
        return _TABLE.get(character, character)
    return key


_PRIORITY_KEYS: dict[tuple[str, ...], str] = {
    ("1",): "priority_1", ("2",): "priority_2", ("3",): "priority_3", ("4",): "priority_4",
}

MAP_KEYS: dict[tuple[str, ...], str] = {
    ("h",): "go_left", ("left",): "go_left",
    ("l",): "go_right", ("right",): "go_right",
    ("j",): "go_down", ("down",): "go_down",
    ("k",): "go_up", ("up",): "go_up",
    ("g", "g"): "go_first", ("G",): "go_last",
    ("0",): "go_root",
    ("z", "z"): "center",
    ("o",): "new_below", ("O",): "new_above", ("a",): "new_child",
    ("i",): "rename",
    ("space",): "toggle_status", ("S",): "clear_status",
    ("t",): "edit_date",
    ("d", "d"): "cut", ("y", "y"): "copy", ("p",): "paste",
    ("J",): "move_down", ("K",): "move_up", ("H",): "promote", ("L",): "demote",
    ("z", "a"): "fold_toggle", ("z", "c"): "fold_close", ("z", "o"): "fold_open",
    ("z", "M"): "fold_all", ("z", "R"): "unfold_all",
    ("u",): "undo", ("ctrl+r",): "redo",
    ("g", "t"): "tab_next", ("g", "T"): "tab_prev",
    ("shift+right",): "tab_next", ("shift+left",): "tab_prev",
    ("c",): "mark_start",
    ("v",): "toggle_view",
    ("?",): "help", (":",): "command", ("Z", "Z"): "save_quit",
    **_PRIORITY_KEYS,
    ("enter",): "open_link", ("g", "x"): "open_link",
    ("g", "l"): "add_link", ("g", "L"): "list_links",
    ("n",): "edit_note", ("g", "k"): "criteria",
}

# Режим выделения: движение и команды, которые применяются ко всем отмеченным пунктам.
# Повторного «c» в таблице нет намеренно: зажатая буква повторяется и не должна мешать.
SELECT_KEYS: dict[tuple[str, ...], str] = {
    ("h",): "mark_left", ("left",): "mark_left",
    ("l",): "mark_right", ("right",): "mark_right",
    ("j",): "mark_down", ("down",): "mark_down",
    ("k",): "mark_up", ("up",): "mark_up",
    ("y",): "mark_copy", ("d", "d"): "mark_cut",
    ("space",): "toggle_status", ("S",): "clear_status",
    ("t",): "edit_date",
    ("z", "a"): "fold_toggle", ("z", "c"): "fold_close", ("z", "o"): "fold_open",
    ("g", "l"): "add_link",
    ("u",): "undo",
    **_PRIORITY_KEYS,
}

BOARD_KEYS: dict[tuple[str, ...], str] = {
    ("h",): "col_left", ("left",): "col_left",
    ("l",): "col_right", ("right",): "col_right",
    ("j",): "card_down", ("down",): "card_down",
    ("k",): "card_up", ("up",): "card_up",
    ("g", "g"): "card_first", ("G",): "card_last",
    ("H",): "card_to_left", ("L",): "card_to_right",
    ("space",): "toggle_status", ("S",): "clear_status",
    ("t",): "edit_date", ("i",): "rename",
    ("a",): "board_scope", ("enter",): "open_on_map",
    ("u",): "undo", ("ctrl+r",): "redo",
    ("g", "t"): "tab_next", ("g", "T"): "tab_prev",
    ("shift+right",): "tab_next", ("shift+left",): "tab_prev",
    ("v",): "toggle_view",
    ("?",): "help", (":",): "command", ("Z", "Z"): "save_quit",
    **_PRIORITY_KEYS,
    ("g", "x"): "open_link", ("g", "l"): "add_link", ("g", "L"): "list_links",
    ("n",): "edit_note", ("g", "k"): "criteria",
}


GRAPH_KEYS: dict[tuple[str, ...], str] = {
    ("h",): "days_back", ("left",): "days_back",
    ("l",): "days_forward", ("right",): "days_forward",
    ("0",): "days_today",
    ("-",): "zoom_out", ("+",): "zoom_in", ("=",): "zoom_in",
    ("j",): "task_down", ("down",): "task_down",
    ("k",): "task_up", ("up",): "task_up",
    ("g", "g"): "task_first", ("G",): "task_last",
    ("space",): "toggle_status", ("S",): "clear_status",
    ("t",): "edit_date", ("i",): "rename",
    ("a",): "board_scope", ("enter",): "open_on_map",
    ("u",): "undo", ("ctrl+r",): "redo",
    ("g", "t"): "tab_next", ("g", "T"): "tab_prev",
    ("shift+right",): "tab_next", ("shift+left",): "tab_prev",
    ("v",): "toggle_view",
    ("?",): "help", (":",): "command", ("Z", "Z"): "save_quit",
    **_PRIORITY_KEYS,
    ("g", "x"): "open_link", ("g", "l"): "add_link", ("g", "L"): "list_links",
    ("n",): "edit_note", ("g", "k"): "criteria",
}


class Chord:
    """Накапливает клавиши и отдаёт действие, когда последовательность собрана."""

    def __init__(self) -> None:
        self.buffer: tuple[str, ...] = ()

    def feed(self, key: str, table: dict[tuple[str, ...], str]) -> str | None:
        if key == "escape":
            self.buffer = ()
            return None
        seq = self.buffer + (key,)
        if seq in table:
            self.buffer = ()
            return table[seq]
        if any(k[: len(seq)] == seq for k in table):
            self.buffer = seq
            return None
        self.buffer = ()
        # Последовательность сорвалась: новая клавиша может быть началом другой.
        if len(seq) > 1:
            return self.feed(key, table)
        return None
