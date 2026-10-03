from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_store
from app.models import AuditLog, User
from tests.conftest import HTMX_HEADERS
from tests.factories import make_task


def test_default_off(db: Session) -> None:
    assert settings_store.competition_enabled(db) is False


def test_set_value_with_audit(db: Session, user: User) -> None:
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")  # no-op
    assert settings_store.competition_enabled(db) is True
    entries = db.scalars(select(AuditLog)).all()
    assert [e.action for e in entries] == ["setting.update"]
    assert entries[0].old_value == {"value": "false"}
    assert entries[0].new_value == {"value": "true"}


def test_switch_on_more_page(client: TestClient, db: Session) -> None:
    html = client.get("/meer").text
    assert 'role="switch"' in html and 'aria-checked="false"' in html
    r = client.post("/instellingen/competitie", headers=HTMX_HEADERS)
    assert r.status_code == 200
    assert 'aria-checked="true"' in r.text and 'id="competition-row"' in r.text
    assert settings_store.competition_enabled(db)
    r = client.post("/instellingen/competitie", headers=HTMX_HEADERS)
    assert 'aria-checked="false"' in r.text


def test_switch_requires_csrf_headers(client: TestClient) -> None:
    assert client.post("/instellingen/competitie").status_code == 403


def test_scores_page_explains_when_off(
    client: TestClient, db: Session, user: User
) -> None:
    assert "competitie staat uit" in client.get("/scores").text
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")
    assert "competitie staat uit" not in client.get("/scores").text


def test_points_field_hidden_when_off(
    client: TestClient, db: Session, user: User
) -> None:
    task = make_task(db, default_points=6)
    html = client.get(f"/taken/{task.id}").text
    assert 'id="default_points"' not in html
    # De waarde blijft bewaard bij opslaan
    assert 'type="hidden" name="default_points" value="6"' in html
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")
    html = client.get(f"/taken/{task.id}").text
    assert 'id="default_points"' in html
