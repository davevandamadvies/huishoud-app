import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sessions, users
from app.models import AuditLog, Role, User, UserSession, UserStatus
from tests.conftest import HTMX_HEADERS, login_as
from tests.factories import make_user


@pytest.fixture
def admin(db: Session) -> User:
    return make_user(db, name="Beheer", role=Role.ADMIN)


@pytest.fixture
def admin_client(anon_client: TestClient, db: Session, admin: User) -> TestClient:
    return login_as(anon_client, db, admin)


def actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))


# ---- Service-regels ----


def test_grant_access(db: Session, admin: User) -> None:
    user = users.grant_access(
        db, admin, oidc_sub=" abc-123 ", display_name="  Sam  ", role="user"
    )
    assert user.oidc_sub == "abc-123"
    assert user.display_name == "Sam"
    assert user.role == Role.USER and user.is_active
    assert "user.grant_access" in actions(db)


@pytest.mark.parametrize(
    ("sub", "name", "role", "message"),
    [
        ("", "Sam", "user", "account-ID"),
        ("met spatie", "Sam", "user", "account-ID"),
        ("x" * 256, "Sam", "user", "account-ID"),
        ("ok", "", "user", "naam"),
        ("ok", "x" * 51, "user", "50 tekens"),
        ("ok", "Sam", "superuser", "rol"),
    ],
)
def test_grant_access_validation(
    db: Session, admin: User, sub: str, name: str, role: str, message: str
) -> None:
    with pytest.raises(users.UserAdminError, match=message):
        users.grant_access(db, admin, oidc_sub=sub, display_name=name, role=role)


def test_grant_access_duplicate(db: Session, admin: User) -> None:
    with pytest.raises(users.UserAdminError, match="al toegang"):
        users.grant_access(
            db, admin, oidc_sub=admin.oidc_sub, display_name="X", role="user"
        )


def test_last_admin_cannot_be_demoted(db: Session, admin: User) -> None:
    with pytest.raises(users.UserAdminError, match="minimaal één"):
        users.change_role(db, admin, admin, "user")
    with pytest.raises(users.UserAdminError, match="minimaal één"):
        users.deactivate(db, admin, admin)


def test_admin_can_step_down_when_another_exists(db: Session, admin: User) -> None:
    make_user(db, role=Role.ADMIN)
    users.change_role(db, admin, admin, "user")
    assert admin.role == Role.USER


def test_deactivated_admin_does_not_count(db: Session, admin: User) -> None:
    make_user(db, role=Role.ADMIN, status=UserStatus.DEACTIVATED)
    with pytest.raises(users.UserAdminError):
        users.deactivate(db, admin, admin)


def test_deactivate_revokes_sessions_and_keeps_history(
    db: Session, admin: User
) -> None:
    target = make_user(db)
    token = sessions.create_session(db, target)
    db.commit()
    users.deactivate(db, admin, target)
    assert target.status == UserStatus.DEACTIVATED
    assert sessions.get_active_session(db, token) is None
    assert db.get(User, target.id) is not None
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "user.deactivate")
    ).one()
    assert entry.new_value["sessions_revoked"] == 1


def test_activate_and_rename(db: Session, admin: User) -> None:
    target = make_user(db, status=UserStatus.DEACTIVATED)
    users.activate(db, admin, target)
    users.rename(db, admin, target, "Nieuwe   naam")
    assert target.is_active
    assert target.display_name == "Nieuwe naam"
    assert actions(db)[-2:] == ["user.activate", "user.rename"]


# ---- Toegang tot de beheerpagina's ----


def test_regular_user_gets_403(client: TestClient, db: Session) -> None:
    response = client.get("/beheer/gebruikers")
    assert response.status_code == 403
    assert "auth.forbidden" in actions(db)


def test_regular_user_cannot_post(client: TestClient, db: Session) -> None:
    response = client.post(
        "/beheer/gebruikers",
        data={"oidc_sub": "x", "display_name": "X", "role": "admin"},
        headers=HTMX_HEADERS,
    )
    assert response.status_code == 403
    assert db.scalar(select(User).where(User.oidc_sub == "x")) is None


def test_more_page_hides_admin_link_for_users(client: TestClient) -> None:
    assert "/beheer/gebruikers" not in client.get("/meer").text


def test_role_change_takes_effect_immediately(
    admin_client: TestClient, db: Session, admin: User
) -> None:
    assert admin_client.get("/beheer/gebruikers").status_code == 200
    make_user(db, role=Role.ADMIN)
    admin.role = Role.USER
    db.commit()
    assert admin_client.get("/beheer/gebruikers").status_code == 403


def test_deactivated_user_is_logged_out(client: TestClient, db: Session) -> None:
    user = db.scalars(select(User)).first()
    assert user is not None
    user.status = UserStatus.DEACTIVATED
    db.commit()
    assert client.get("/").status_code == 303


# ---- Beheerscherm ----


def test_admin_list_page(admin_client: TestClient, db: Session) -> None:
    make_user(db, name="Partner")
    html = admin_client.get("/beheer/gebruikers").text
    assert "Partner" in html
    assert "Toegang geven" in html
    assert "/beheer/gebruikers" in admin_client.get("/meer").text


def test_admin_grants_access(admin_client: TestClient, db: Session) -> None:
    response = admin_client.post(
        "/beheer/gebruikers",
        data={"oidc_sub": "nieuw-sub", "display_name": "Partner", "role": "user"},
        headers=HTMX_HEADERS,
    )
    assert response.status_code == 200
    assert "Partner heeft nu toegang" in response.text
    assert db.scalar(select(User).where(User.oidc_sub == "nieuw-sub")) is not None


def test_admin_grant_error_keeps_input(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/beheer/gebruikers",
        data={"oidc_sub": "abc", "display_name": "", "role": "user"},
        headers=HTMX_HEADERS,
    )
    assert response.status_code == 200
    assert 'role="alert"' in response.text
    assert 'value="abc"' in response.text


def test_admin_detail_actions(
    admin_client: TestClient, db: Session, admin: User
) -> None:
    target = make_user(db, name="Sam")
    sessions.create_session(db, target)
    db.commit()
    base = f"/beheer/gebruikers/{target.id}"
    assert admin_client.get(base).status_code == 200

    r = admin_client.post(f"{base}/rol", data={"role": "admin"}, headers=HTMX_HEADERS)
    assert "Rol opgeslagen" in r.text
    r = admin_client.post(
        f"{base}/naam", data={"display_name": "Samira"}, headers=HTMX_HEADERS
    )
    assert "Naam opgeslagen" in r.text
    r = admin_client.post(f"{base}/deactiveren", headers=HTMX_HEADERS)
    assert "Gedeactiveerd" in r.text
    db.expire_all()
    assert db.get(User, target.id).status == UserStatus.DEACTIVATED
    assert (
        db.scalars(
            select(UserSession).where(
                UserSession.user_id == target.id, UserSession.revoked_at.is_(None)
            )
        ).first()
        is None
    )
    r = admin_client.post(f"{base}/activeren", headers=HTMX_HEADERS)
    assert "Weer actief" in r.text


def test_admin_cannot_deactivate_self_as_last_admin(
    admin_client: TestClient, admin: User
) -> None:
    r = admin_client.post(
        f"/beheer/gebruikers/{admin.id}/deactiveren", headers=HTMX_HEADERS
    )
    assert r.status_code == 200
    assert "minimaal één actieve beheerder" in r.text


def test_unknown_user_404(admin_client: TestClient) -> None:
    assert admin_client.get("/beheer/gebruikers/999").status_code == 404


def test_form_rejects_other_content_types(admin_client: TestClient) -> None:
    r = admin_client.post(
        "/beheer/gebruikers", json={"oidc_sub": "x"}, headers=HTMX_HEADERS
    )
    assert r.status_code == 415
