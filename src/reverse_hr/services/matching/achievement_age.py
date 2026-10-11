"""Bonus expires; confirmed historical achievements never disappear."""

from datetime import date


def achievement_points(occurred_on: date | None, today: date) -> int:
    if occurred_on is None:
        return 0
    days = (today - occurred_on).days
    if days < 0 or days >= 730:
        return 0
    return 2 if days < 365 else 1
