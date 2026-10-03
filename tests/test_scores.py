from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import completion, scores, settings_store
from app import points as app_points
from app.dates import today, when_label
from app.models import User, UserStatus
from tests.factories import make_category, make_task, make_user


@pytest.fixture
def competition(db: Session, user: User) -> None:
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")


def done(db: Session, actor: User, performers: list[User], points: int, on: date, **kw):  # noqa: ANN003, ANN201
    task = make_task(db, **kw)
    return completion.complete(
        db,
        actor,
        task,
        performer_ids=[u.id for u in performers],
        points=points,
        completed_on=on,
    ).occurrence


def test_bounds() -> None:
    d = date(2026, 12, 31)
    assert scores.bounds(scores.Period.WEEK, d) == (
        date(2026, 12, 28),
        date(2027, 1, 3),
    )
    assert scores.bounds(scores.Period.MONTH, d) == (date(2026, 12, 1), d)
    assert scores.bounds(scores.Period.MONTH, date(2028, 2, 10))[1] == date(2028, 2, 29)
    assert scores.bounds(scores.Period.TOTAL, d) == (None, None)


def test_standings_per_period(db: Session, user: User, competition: None) -> None:
    partner = make_user(db, name="Partner")
    t = today()
    done(db, user, [user], 8, t)
    done(db, user, [user, partner], 5, t)  # ieder 3
    done(db, user, [partner], 4, t - timedelta(days=40))  # buiten week en maand
    week = {
        s.user.display_name: s.points
        for s in scores.build(db, scores.Period.WEEK, t).standings
    }
    assert week == {"Dave": 11, "Partner": 3}
    total = {
        s.user.display_name: s.points
        for s in scores.build(db, scores.Period.TOTAL, t).standings
    }
    assert total == {"Dave": 11, "Partner": 7}


def test_leader_and_tie(db: Session, user: User, competition: None) -> None:
    partner = make_user(db, name="Partner")
    t = today()
    board = scores.build(db, scores.Period.WEEK, t)
    assert board.leader is None  # nog geen punten
    done(db, user, [user, partner], 4, t)
    assert scores.build(db, scores.Period.WEEK, t).leader is None  # gelijk
    done(db, user, [partner], 2, t)
    board = scores.build(db, scores.Period.WEEK, t)
    assert board.leader.user.id == partner.id and board.top == 4


def test_deactivated_hidden_but_history_kept(
    db: Session, user: User, competition: None
) -> None:
    old = make_user(db, name="Oud")
    done(db, user, [old], 6, today())
    old.status = UserStatus.DEACTIVATED
    db.commit()
    board = scores.build(db, scores.Period.WEEK, today())
    assert [s.user.display_name for s in board.standings] == ["Dave"]
    assert board.entries[0].users[0].display_name == "Oud"


def test_category_filter(db: Session, user: User, competition: None) -> None:
    tuin = make_category(db, "Tuin")
    done(db, user, [user], 6, today(), category=tuin, name="Gras")
    done(db, user, [user], 4, today(), name="Stof")
    board = scores.build(db, scores.Period.WEEK, today(), tuin.id)
    assert board.standings[0].points == 6
    assert [e.task.name for e in board.entries] == ["Gras"]


def test_entries_include_point_changes(
    db: Session, user: User, competition: None
) -> None:
    occ = done(db, user, [user], 8, today(), name="Dakgoten")
    app_points.correct(db, user, occ, 10)
    entries = scores.build(db, scores.Period.WEEK, today()).entries
    kinds = [(e.kind, e.task.name) for e in entries]
    assert ("change", "Dakgoten") in kinds and ("done", "Dakgoten") in kinds
    change = next(e for e in entries if e.kind == "change")
    assert (change.old, change.new, change.actor.id) == (8, 10, user.id)


def test_when_label() -> None:
    from datetime import UTC, datetime

    ref = date(2026, 10, 3)
    assert when_label(datetime(2026, 10, 3, 7, 12, tzinfo=UTC), ref) == "vandaag 09:12"
    assert when_label(datetime(2026, 10, 2, 16, 0, tzinfo=UTC), ref) == "gisteren 18:00"
    assert when_label(datetime(2026, 9, 26, 10, 0, tzinfo=UTC), ref) == "za 26 sep"


def test_scores_page(
    client: TestClient, db: Session, user: User, competition: None
) -> None:
    partner = make_user(db, name="Partner")
    done(db, user, [user], 8, today(), name="Badkamer")
    done(db, user, [user, partner], 5, today(), name="Gras maaien")
    html = client.get("/scores").text
    assert "Koploper" in html and "achter" in html
    assert "Badkamer" in html and "samen · 5 p → ieder 3" in html
    assert 'aria-current="true">Week<' in html
    assert 'aria-current="true">Maand<' in client.get("/scores?periode=maand").text


def test_scores_hidden_without_competition(
    client: TestClient, db: Session, user: User
) -> None:
    html = client.get("/scores").text
    assert "competitie staat uit" in html and "Koploper" not in html


def test_today_competition_line(client: TestClient, db: Session, user: User) -> None:
    make_user(db, name="Partner")
    assert "score-line" not in client.get("/").text
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")
    done(db, user, [user], 8, today(), name="Badkamer")
    html = client.get("/").text
    assert "Dave 8 · Partner 0" in html
