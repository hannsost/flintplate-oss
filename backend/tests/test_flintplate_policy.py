from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.gastro.policy import assess_interval


def test_minor_pause_and_night_are_hard_boundaries():
    start = datetime(2026, 9, 10, 14, tzinfo=ZoneInfo("Europe/Berlin"))
    result = assess_interval(start, start + timedelta(hours=8), 30, date(2009, 1, 1), [])
    assert any("60 Minuten" in reason for reason in result.blockers)
    assert any("06 und 20" in reason for reason in result.blockers)


def test_rest_interval_and_contract_hours_are_distinct():
    start = datetime(2026, 9, 10, 9, tzinfo=ZoneInfo("Europe/Berlin"))
    result = assess_interval(
        start,
        start + timedelta(hours=8),
        30,
        date(1990, 1, 1),
        [(start - timedelta(hours=14), start - timedelta(hours=7))],
        weekly_minutes=1800,
        weekly_target=2000,
    )
    assert any("Ruheabstand" in r for r in result.blockers)
    assert any("Sollzeit" in r for r in result.warnings)


def test_unknown_age_is_not_assumed_adult():
    start = datetime(2026, 9, 10, 9, tzinfo=ZoneInfo("Europe/Berlin"))
    result = assess_interval(start, start + timedelta(hours=6), 30, None, [])
    assert not result.blockers and any("Geburtsdatum fehlt" in r for r in result.warnings)
