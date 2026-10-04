from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import stats
from app.models import Occurrence, OccurrenceStatus, Performer, User
from tests.factories import make_category, make_task, make_user

TODAY = date(2026, 10, 4)


def done(
    db: Session, task, completed: date, due: date | None = None, cost=None, who=()
):
    occurrence = Occurrence(
        task_id=task.id,
        status=OccurrenceStatus.DONE,
        completed_on=completed,
        due_date=due,
        cost_cents=cost,
    )
    db.add(occurrence)
    db.flush()
    for user in who:
        db.add(Performer(occurrence_id=occurrence.id, user_id=user.id))
    db.commit()
    return occurrence


def test_bounds() -> None:
    assert stats.bounds(stats.Range.YEAR, TODAY, None) == (date(2026, 1, 1), TODAY)
    assert stats.bounds(stats.Range.LAST_12, TODAY, None) == (date(2025, 11, 1), TODAY)
    assert stats.bounds(stats.Range.ALL, TODAY, date(2024, 5, 17)) == (
        date(2024, 5, 1),
        TODAY,
    )


def test_empty(db: Session) -> None:
    s = stats.build(db, stats.Range.YEAR, TODAY)
    assert s.done == 0
    assert s.on_time_pct is None
    assert len(s.per_period) == 10  # jan–okt, allemaal 0


def test_counts_and_on_time(db: Session, user: User) -> None:
    partner = make_user(db, name="Partner")
    garden = make_category(db, name="Tuin", color="green")
    house = make_category(db, name="Huis", color="blue")
    gras = make_task(db, name="Gras", category=garden)
    ramen = make_task(db, name="Ramen", category=house)
    done(db, gras, date(2026, 9, 1), due=date(2026, 9, 1), who=[user])
    done(db, gras, date(2026, 9, 20), due=date(2026, 9, 10), who=[user, partner])
    done(db, ramen, date(2026, 10, 2), due=date(2026, 9, 28), who=[partner])
    done(db, ramen, date(2026, 10, 3), who=[partner])  # zonder vervaldatum
    done(db, ramen, date(2025, 12, 1), due=date(2025, 12, 1))  # vorig jaar

    s = stats.build(db, stats.Range.YEAR, TODAY)
    assert s.done == 4
    assert (s.on_time, s.with_due, s.on_time_pct) == (1, 3, 33)
    by_month = {b.key: b.value for b in s.per_period}
    assert by_month[(2026, 9)] == 2 and by_month[(2026, 10)] == 2
    assert [(r.label, r.value) for r in s.most_late] == [("Gras", 1), ("Ramen", 1)]
    assert s.most_late[0].detail == "gemiddeld 10 dagen te laat"
    assert [(r.label, r.value, r.color) for r in s.per_category] == [
        ("Huis", 2, "blue"),
        ("Tuin", 2, "green"),
    ]
    assert [(r.label, r.value) for r in s.per_person] == [("Partner", 3), ("Dave", 2)]

    last12 = stats.build(db, stats.Range.LAST_12, TODAY)
    assert last12.done == 5


def test_costs(db: Session) -> None:
    category = make_category(db, name="Auto")
    apk = make_task(db, name="APK", category=category)
    wash = make_task(db, name="Wassen", category=category)
    done(db, apk, date(2026, 3, 1), cost=8950)
    done(db, wash, date(2026, 3, 5), cost=1500)
    done(db, wash, date(2026, 4, 5), cost=1500)
    s = stats.build(db, stats.Range.YEAR, TODAY)
    assert s.cost_total == 11950
    assert {b.key: b.value for b in s.cost_per_period}[(2026, 3)] == 10450
    assert [(r.label, r.value) for r in s.cost_top] == [("APK", 8950), ("Wassen", 3000)]
    assert [(r.label, r.value) for r in s.cost_per_category] == [("Auto", 11950)]


def test_long_periods_group_per_year(db: Session) -> None:
    task = make_task(db, name="Ramen")
    done(db, task, date(2023, 2, 1))
    s = stats.build(db, stats.Range.ALL, TODAY)
    assert [b.short for b in s.per_period] == ["2023", "2024", "2025", "2026"]
    assert s.per_period[0].value == 1


def test_bars_geometry() -> None:
    buckets = [
        stats.Bucket((2026, m), "x", "x", v)
        for m, v in ((1, 0), (2, 5), (3, 10), (4, 2))
    ]
    width, bars = stats.bars(buckets)
    assert width == 4 * stats.SLOT
    assert bars[0].path == ""  # geen staaf bij 0
    assert bars[2].y == 0  # hoogste staaf vult de grafiek
    assert [b.show_value for b in bars] == [False, False, True, True]  # max + laatste


def test_share() -> None:
    rows = [stats.Row("a", 10), stats.Row("b", 0), stats.Row("c", 5)]
    assert stats.share(10, rows) == 100
    assert stats.share(5, rows) == 50
    assert stats.share(0, rows) == pytest.approx(1.5)


def test_page(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, name="Ramen")
    from app.dates import today

    done(db, task, today(), due=today(), cost=1250, who=[user])
    response = client.get("/statistieken")
    assert response.status_code == 200
    assert "keer gedaan" in response.text
    assert "100%" in response.text
    assert "€ 12,50" in response.text
    assert "<table>" in response.text  # tabelweergave
    assert 'style="' not in response.text  # CSP: geen inline stijl
    assert client.get("/statistieken?periode=onzin").status_code == 200


def test_page_empty_and_links(client: TestClient) -> None:
    assert "Nog niets gedaan" in client.get("/statistieken?periode=alles").text
    assert 'href="/statistieken"' in client.get("/scores").text
    assert 'href="/statistieken"' in client.get("/meer").text
