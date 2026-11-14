"""Срочность пункта и его место на канбан-доске. Текущее время — всегда аргумент."""
from __future__ import annotations

from datetime import datetime, timedelta

from .model import DONE, FAILED

# Вид пункта
GREY = "done"       # завершено: полупрозрачный
DARK_RED = "failed" # провалено: полупрозрачный красный
RED = "overdue"     # не завершено, срок прошёл
ORANGE = "week"     # период задевает текущую неделю
GREEN = "next"      # короткий период начинается на следующей неделе
PLAIN = "plain"     # всё остальное

# Места на доске
B_PLANNED = "planned"
B_TODAY = "today"
B_OVERDUE = "overdue"
B_WEEK = "week"
B_RUNNING = "running"
B_DONE = "done"

LONG_DAYS = 7


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
    if p.first() < next_mon and p.last() >= mon:
        return ORANGE
    if next_mon <= p.first() < after_next and p.days <= LONG_DAYS:
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
    if kind == ORANGE:
        last = node.period.last()
        if last.date() == now.date():
            return B_TODAY
        _, next_mon, _ = week_bounds(now)
        if node.period.days > LONG_DAYS and last >= next_mon:
            return B_RUNNING
        return B_WEEK
    return B_PLANNED
