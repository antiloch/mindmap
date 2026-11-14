"""Сроки: точка любой точности (год … минута) и период из двух точек.

Два представления:
  token() — как в файле: 2026-11-05T15:20..2026-11-05T16:00
  show()  — на карте, на доске и в окне ввода: 05.11.2026 15:20 – 05.11.2026 16:00;
            parse_input() читает его обратно
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_MONTH_STEMS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
_WEEKDAYS = {
    "пн": 0, "понедельник": 0, "вт": 1, "вторник": 1, "ср": 2, "среда": 2, "среду": 2,
    "чт": 3, "четверг": 3, "пт": 4, "пятница": 4, "пятницу": 4,
    "сб": 5, "суббота": 5, "субботу": 5, "вс": 6, "воскресенье": 6,
}
_DAY_WORDS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}


@dataclass(frozen=True)
class Point:
    year: int
    month: int | None = None
    day: int | None = None
    hour: int | None = None
    minute: int | None = None

    def first(self) -> datetime:
        return datetime(self.year, self.month or 1, self.day or 1, self.hour or 0, self.minute or 0)

    def last(self) -> datetime:
        if self.month is None:
            return datetime(self.year, 12, 31, 23, 59, 59)
        if self.day is None:
            return datetime(self.year, self.month, calendar.monthrange(self.year, self.month)[1], 23, 59, 59)
        if self.hour is None:
            return datetime(self.year, self.month, self.day, 23, 59, 59)
        return datetime(self.year, self.month, self.day, self.hour, self.minute or 0, 59)

    @property
    def precision(self) -> int:
        """0 — год, 1 — месяц, 2 — день, 3 — минута."""
        if self.month is None:
            return 0
        if self.day is None:
            return 1
        return 2 if self.hour is None else 3

    def token(self) -> str:
        s = f"{self.year:04d}"
        if self.month is not None:
            s += f"-{self.month:02d}"
        if self.day is not None:
            s += f"-{self.day:02d}"
        if self.hour is not None:
            s += f"T{self.hour:02d}:{self.minute or 0:02d}"
        return s

    def show(self) -> str:
        p = self.precision
        if p == 0:
            return f"{self.year:04d}"
        if p == 1:
            return f"{self.month:02d}.{self.year:04d}"
        s = f"{self.day:02d}.{self.month:02d}.{self.year:04d}"
        return s if p == 2 else f"{s} {self.hour:02d}:{self.minute or 0:02d}"


@dataclass(frozen=True)
class Period:
    start: Point
    end: Point

    def first(self) -> datetime:
        return self.start.first()

    def last(self) -> datetime:
        return self.end.last()

    @property
    def days(self) -> int:
        """Длина в календарных днях, включая оба края."""
        return (self.last().date() - self.first().date()).days + 1

    def token(self) -> str:
        if self.start == self.end:
            return self.start.token()
        return f"{self.start.token()}..{self.end.token()}"

    def show(self) -> str:
        """Один вид везде: оба края полностью, как бы срок ни ввели."""
        if self.start == self.end:
            return self.start.show()
        return f"{self.start.show()} – {self.end.show()}"


# ---------- токен файла ----------

_TOKEN_POINT = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T(\d{2}):(\d{2}))?)?)?")


def _point_from_token(s: str) -> Point:
    m = _TOKEN_POINT.fullmatch(s)
    if not m:
        raise ValueError(s)
    vals = [int(v) if v is not None else None for v in m.groups()]
    p = Point(*vals)
    p.first()  # проверка, что дата существует
    return p


def period_from_token(token: str) -> Period | None:
    """Токен из файла → Period; None, если это не срок (например, @имя)."""
    left, sep, right = token.partition("..")
    try:
        a = _point_from_token(left)
        b = _point_from_token(right) if sep else a
    except ValueError:
        return None
    if b.last() < a.first():
        return None
    return Period(a, b)


# ---------- ввод человека ----------

@dataclass
class _Atom:
    y: int | None = None
    m: int | None = None
    d: int | None = None
    H: int | None = None
    M: int | None = None
    bare: int | None = None  # одно число без точек: день или месяц, зависит от соседа

    @property
    def time_only(self) -> bool:
        return self.H is not None and self.y is None and self.m is None and self.d is None


def _full_year(s: str) -> int:
    y = int(s)
    return y + 2000 if y < 100 else y


def _month_from_word(word: str) -> int | None:
    if not re.fullmatch(r"[а-я]+", word):
        return None
    for stem, month in _MONTH_STEMS.items():
        if word.startswith(stem):
            return month
    return None


def _atom(s: str, now: datetime) -> _Atom:
    s = s.strip()
    a = _Atom()
    tm = re.search(r"(?:^|[\st])(\d{1,2}):(\d{2})$", s)
    if tm:
        a.H, a.M = int(tm[1]), int(tm[2])
        if a.H > 23 or a.M > 59:
            raise ValueError(f"Нет такого времени: {tm[1]}:{tm[2]}")
        s = s[: tm.start()].strip()
    if not s:
        if a.H is None:
            raise ValueError("Пустая дата")
        return a

    if m := re.fullmatch(r"\d{4}", s):
        a.y = int(s)
    elif m := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s):
        a.y, a.m = int(m[1]), int(m[2])
        a.d = int(m[3]) if m[3] else None
    elif re.fullmatch(r"\d{1,2}", s):
        a.bare = int(s)
    elif m := re.fullmatch(r"(\d{1,2})\.(\d{4})", s):
        a.m, a.y = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?", s):
        a.d, a.m = int(m[1]), int(m[2])
        a.y = _full_year(m[3]) if m[3] else None
    elif s in _DAY_WORDS:
        d = now + timedelta(days=_DAY_WORDS[s])
        a.y, a.m, a.d = d.year, d.month, d.day
    elif s in _WEEKDAYS:
        d = now + timedelta(days=(_WEEKDAYS[s] - now.weekday()) % 7)
        a.y, a.m, a.d = d.year, d.month, d.day
    else:
        parts = s.split()
        month = _month_from_word(parts[0])
        if month is None or len(parts) > 2 or (len(parts) == 2 and not re.fullmatch(r"\d{4}", parts[1])):
            raise ValueError(f"Не понимаю: «{s}»")
        a.m = month
        a.y = int(parts[1]) if len(parts) == 2 else None

    if a.H is not None and a.d is None:
        raise ValueError("Время можно указать только вместе с днём")
    return a


def _to_point(a: _Atom) -> Point:
    if a.y is None:
        raise ValueError("Не хватает года")
    p = Point(a.y, a.m, a.d, a.H, a.M)
    try:
        p.first()
        p.last()
    except ValueError:
        raise ValueError(f"Нет такой даты: {p.show()}") from None
    return p


def _default_year(a: _Atom, now: datetime) -> None:
    """Дата без года — этот год; давно прошедшая (полгода и больше) — следующий."""
    a.y = now.year
    try:
        if _to_point(a).last() < now - timedelta(days=183):
            a.y = now.year + 1
    except ValueError:
        a.y = now.year


def _single(a: _Atom, now: datetime) -> Period:
    if a.bare is not None:
        raise ValueError(f"Одно число «{a.bare}» — непонятно, что это; нужен год или дата")
    if a.time_only:
        a.y, a.m, a.d = now.year, now.month, now.day
    if a.y is None:
        _default_year(a, now)
    p = _to_point(a)
    return Period(p, p)


def _pair(left: _Atom, right: _Atom, now: datetime) -> Period:
    if right.bare is not None:
        raise ValueError(f"Одно число «{right.bare}» — непонятно, что это")
    if left.bare is not None:
        if right.d is not None:
            left.d, left.m, left.y = left.bare, right.m, right.y
        elif right.m is not None:
            left.m, left.y = left.bare, right.y
        else:
            raise ValueError(f"Одно число «{left.bare}» — непонятно, что это")
        left.bare = None

    if left.time_only:
        raise ValueError("Сначала укажите день, потом время")
    if right.time_only:
        right.y, right.m, right.d = left.y, left.m, left.d

    # Без года: период переходит через Новый год, только если месяц конца раньше
    # месяца начала (25.12-10.01). Иначе «конец раньше начала» — это опечатка.
    left_free, right_free = left.y is None, right.y is None
    if left_free and right_free:
        _default_year(left, now)
        right.y = left.y
        if right.m < left.m:
            right.y += 1
    elif left_free:
        left.y = right.y
        if right.m < left.m:
            left.y -= 1
    elif right_free:
        right.y = left.y
        if right.m < left.m:
            right.y += 1

    a, b = _to_point(left), _to_point(right)
    if b.last() < a.first():
        raise ValueError("Конец раньше начала")
    return Period(a, b)


def parse_input(text: str, now: datetime) -> Period | None:
    """Строка из окна сроков → Period; пустая строка → None (снять срок).

    Непонятный ввод — ValueError с текстом для показа.
    """
    s = re.sub(r"[–—−]", "-", text.strip().lower().replace("ё", "е")).replace(",", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    if m := re.fullmatch(r"с (.+) по (.+)", s):
        return _pair(_atom(m[1], now), _atom(m[2], now), now)
    if ".." in s:
        l, r = s.split("..", 1)
        return _pair(_atom(l, now), _atom(r, now), now)
    if m := re.fullmatch(r"(.+?) - (.+)", s):
        return _pair(_atom(m[1], now), _atom(m[2], now), now)

    err: ValueError | None = None
    try:
        return _single(_atom(s, now), now)
    except ValueError as e:
        err = e
    for hit in re.finditer("-", s):
        try:
            return _pair(_atom(s[: hit.start()], now), _atom(s[hit.end():], now), now)
        except ValueError as e:
            if str(e).startswith(("Конец", "Нет такой")):
                err = e
    raise err
