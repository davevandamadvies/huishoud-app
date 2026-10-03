import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import categories
from app.models import AuditLog, Category, User
from tests.conftest import HTMX_HEADERS


def make_category(db: Session, name: str = "Tuin", color: str = "green") -> Category:
    category = Category(name=name, color=color, position=1)
    db.add(category)
    db.commit()
    return category


def test_create_and_order(db: Session, user: User) -> None:
    a = categories.create(db, user, name=" Schoonmaak ", color="blue")
    b = categories.create(db, user, name="Tuin", color="green")
    assert a.name == "Schoonmaak"
    assert [c.id for c in categories.list_categories(db)] == [a.id, b.id]
    assert db.scalars(select(AuditLog.action)).all() == ["category.create"] * 2


@pytest.mark.parametrize(
    ("name", "color", "message"),
    [
        ("", "blue", "naam"),
        ("x" * 41, "blue", "40 tekens"),
        ("Iets", "fuchsia", "kleur"),
        ("tuin", "blue", "al een categorie"),
    ],
)
def test_validation(
    db: Session, user: User, name: str, color: str, message: str
) -> None:
    make_category(db, "Tuin")
    with pytest.raises(categories.CategoryError, match=message):
        categories.create(db, user, name=name, color=color)


def test_update_keeps_own_name(db: Session, user: User) -> None:
    category = make_category(db)
    categories.update(db, user, category, name="Tuin", color="olive")
    assert category.color == "olive"
    entry = db.scalars(select(AuditLog)).one()
    assert entry.old_value == {"name": "Tuin", "color": "green"}


def test_delete_blocked_when_tasks_exist(
    db: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    category = make_category(db)
    monkeypatch.setattr(categories, "task_counter", lambda _db, _id: 2)
    with pytest.raises(categories.CategoryError, match="nog taken"):
        categories.delete(db, user, category)
    monkeypatch.setattr(categories, "task_counter", lambda _db, _id: 0)
    categories.delete(db, user, category)
    assert db.scalar(select(Category)) is None


def test_pages(client: TestClient, db: Session) -> None:
    make_category(db, "Planten", "teal")
    html = client.get("/categorieen").text
    assert "Planten" in html
    assert 'class="dot cat-teal"' in html
    assert ">1<" in client.get("/meer").text.replace(" ", "")


def test_create_via_form(client: TestClient, db: Session) -> None:
    r = client.post(
        "/categorieen",
        data={"name": "Huisdieren", "color": "brown"},
        headers=HTMX_HEADERS,
    )
    assert "Huisdieren toegevoegd" in r.text
    assert db.scalar(select(Category.color)) == "brown"


def test_create_error_keeps_input(client: TestClient) -> None:
    r = client.post(
        "/categorieen", data={"name": "Huisdieren", "color": "x"}, headers=HTMX_HEADERS
    )
    assert 'role="alert"' in r.text
    assert 'value="Huisdieren"' in r.text


def test_edit_and_delete_via_form(client: TestClient, db: Session) -> None:
    category = make_category(db)
    assert client.get(f"/categorieen/{category.id}").status_code == 200
    r = client.post(
        f"/categorieen/{category.id}",
        data={"name": "Moestuin", "color": "olive"},
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 204
    assert r.headers["hx-redirect"] == "/categorieen"
    r = client.post(f"/categorieen/{category.id}/verwijderen", headers=HTMX_HEADERS)
    assert r.status_code == 204
    db.expire_all()
    assert db.scalar(select(Category)) is None


def test_requires_login(anon_client: TestClient) -> None:
    assert anon_client.get("/categorieen").status_code == 303
