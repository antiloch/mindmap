"""Срочность пункта и его место на канбан-доске. Текущее время — всегда аргумент."""
from __future__ import annotations

from datetime import datetime, timedelta

from .model import DONE, FAILED

# Вид пункта
GREY = "done"       # завершено: полупрозрачный
DARK_RED = "failed" # провалено: полупрозрачный красный
RED = "overdue"     # не завершено, срок прошёл
YELLOW = "running"  # уже идёт: начался и кончается позже этой недели
ORANGE = "week"     # период задевает текущую неделю
GREEN = "next"      # начинается на следующей неделе (любой длины)
PLAIN = "plain"     # всё остальное

# Места на доске
B_NEXT = "next"         # начинается на следующей неделе
B_PLANNED = "planned"
B_TODAY = "today"
B_OVERDUE = "overdue"
B_WEEK = "week"
B_RUNNING = "running"
B_DONE = "done"



def week_bounds(now: datetime) -> tuple[datetime, datetime, datetime]:
    """Понедельник этой недели, следующей и той, что после неё (все — 00:00)."""
    mon = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return mon, mon + timedelta(days=7), mon + timedelta(days=14)


def classify(node, now: datetime) -> str:
    if node.status == FAILED:
        return DARK_RED
    if node.status == DONE:
        return GREY
    p = node.period
    if p is None:
        return PLAIN
    if p.last() < now:
        return RED
    mon, next_mon, after_next = week_bounds(now)
    if p.first() <= now and p.last() >= next_mon:
        return YELLOW
    if p.first() < next_mon and p.last() >= mon:
        return ORANGE
    if next_mon <= p.first() < after_next:
        return GREEN
    return PLAIN


def bucket(node, now: datetime) -> str | None:
    """Раздел доски; None — пункта на доске нет (нет даты)."""
    if node.period is None:
        return None
    kind = classify(node, now)
    if kind in (GREY, DARK_RED):
        return B_DONE
    if kind == RED:
        return B_OVERDUE
    if kind == YELLOW:
        return B_RUNNING
    if kind == ORANGE:
        return B_TODAY if node.period.last().date() == now.date() else B_WEEK
    _, _, after_next = week_bounds(now)
    return B_NEXT if node.period.first() < after_next else B_PLANNED
