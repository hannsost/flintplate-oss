"""Historical workload estimates with explicit sample dates and a rolling backtest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median


@dataclass(frozen=True)
class Prediction:
    expected: int | None
    low_observed: int | None
    high_observed: int | None
    sample_days: tuple[date, ...]


def weekday_prediction(
    daily: Mapping[date, int], first_observed: date, target: date, as_of: date
) -> Prediction:
    # as_of is the first incomplete day, never part of a historical sample.
    days = tuple(
        day
        for week in range(1, 9)
        if first_observed <= (day := target - timedelta(days=7 * week)) < as_of
    )
    if len(days) < 4:
        return Prediction(None, None, None, days)
    values = [daily.get(day, 0) for day in days]
    return Prediction(round(median(values)), min(values), max(values), days)


@dataclass(frozen=True)
class Backtest:
    evaluated_days: int
    median_mae: float | None
    prior_week_mae: float | None
    from_date: date | None
    through_date: date | None


def rolling_backtest(daily: Mapping[date, int], first_observed: date, as_of: date) -> Backtest:
    start = max(first_observed + timedelta(days=28), as_of - timedelta(days=28))
    median_errors: list[int] = []
    prior_errors: list[int] = []
    evaluated: list[date] = []
    target = start
    while target < as_of:
        prediction = weekday_prediction(daily, first_observed, target, target)
        if prediction.expected is not None:
            observed = daily.get(target, 0)
            median_errors.append(abs(observed - prediction.expected))
            prior_errors.append(abs(observed - daily.get(target - timedelta(days=7), 0)))
            evaluated.append(target)
        target += timedelta(days=1)
    count = len(evaluated)
    return Backtest(
        count,
        round(sum(median_errors) / count, 2) if count else None,
        round(sum(prior_errors) / count, 2) if count else None,
        evaluated[0] if count else None,
        evaluated[-1] if count else None,
    )
