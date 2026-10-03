import base64
import json
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from joserfc.jwk import RSAKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import LOGIN_COOKIE, SESSION_COOKIE, safe_next
from app.models import AuditLog, User, UserSession, UserStatus
from app.oidc import OIDCClient, get_oidc_client
from app.settings import get_settings
from tests.conftest import BASE_URL, HTMX_HEADERS, login_as
from tests.factories import make_user
from tests.fake_idp import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeIdP


@pytest.fixture
def idp() -> FakeIdP:
    return FakeIdP()


@pytest.fixture
def oidc(
    db: Session, monkeypatch: pytest.MonkeyPatch, idp: FakeIdP
) -> Iterator[OIDCClient]:
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    get_settings.cache_clear()
    yield OIDCClient(get_settings(), transport=idp.transport())
    get_settings.cache_clear()


@pytest.fixture
def web(oidc: OIDCClient, anon_client: TestClient) -> TestClient:
    overrides = anon_client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_oidc_client] = lambda: oidc
    return anon_client


def start_login(web: TestClient, next_path: str = "/") -> dict[str, str]:
    response = web.get("/auth/login", params={"next": next_path})
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert (
        f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
    )
    params = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert params["response_type"] == "code"
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == f"{BASE_URL}/auth/callback"
    assert params["code_challenge_method"] == "S256"
    assert "openid" in params["scope"]
    assert LOGIN_COOKIE in web.cookies
    return params


def complete_login(
    web: TestClient, idp: FakeIdP, sub: str, next_path: str = "/"
) -> "object":
    params = start_login(web, next_path)
    code = idp.issue_code(params["code_challenge"], sub=sub, nonce=params["nonce"])
    return web.get("/auth/callback", params={"code": code, "state": params["state"]})


def actions(db: Session) -> list[str]:
    db.expire_all()
    return [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]


def test_full_login_flow(web: TestClient, idp: FakeIdP, db: Session) -> None:
    user = make_user(db, sub="sub-dave")
    response = complete_login(web, idp, "sub-dave", next_path="/taken")
    assert response.status_code == 303
    assert response.headers["location"] == "/taken"
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith(SESSION_COOKIE))
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag.lower() in session_cookie.lower()
    assert web.get("/taken").status_code == 200
    assert db.scalar(select(UserSession.user_id)) == user.id
    assert "auth.login" in actions(db)


def test_unknown_account_gets_no_access(
    web: TestClient, idp: FakeIdP, db: Session
) -> None:
    response = complete_login(web, idp, "sub-stranger")
    assert response.status_code == 403
    assert "sub-stranger" in response.text
    assert SESSION_COOKIE not in web.cookies
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "auth.denied")).one()
    assert entry.new_value["reason"] == "unknown_account"
    assert entry.new_value["sub"] == "sub-stranger"


def test_deactivated_account_gets_no_access(
    web: TestClient, idp: FakeIdP, db: Session
) -> None:
    make_user(db, sub="sub-old", status=UserStatus.DEACTIVATED)
    response = complete_login(web, idp, "sub-old")
    assert response.status_code == 403
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "auth.denied")).one()
    assert entry.new_value["reason"] == "deactivated"


def test_state_mismatch_rejected(web: TestClient, idp: FakeIdP, db: Session) -> None:
    make_user(db, sub="s")
    params = start_login(web)
    code = idp.issue_code(params["code_challenge"], sub="s", nonce=params["nonce"])
    response = web.get("/auth/callback", params={"code": code, "state": "anders"})
    assert response.status_code == 400
    assert "auth.failed" in actions(db)


def test_callback_without_login_cookie_rejected(web: TestClient, db: Session) -> None:
    response = web.get("/auth/callback", params={"code": "x", "state": "y"})
    assert response.status_code == 400


def test_wrong_pkce_verifier_rejected(
    web: TestClient, idp: FakeIdP, db: Session
) -> None:
    make_user(db, sub="s")
    params = start_login(web)
    code = idp.issue_code("verkeerde-challenge", sub="s", nonce=params["nonce"])
    response = web.get(
        "/auth/callback", params={"code": code, "state": params["state"]}
    )
    assert response.status_code == 400


def test_idp_error_parameter(web: TestClient, db: Session) -> None:
    start_login(web)
    response = web.get(
        "/auth/callback", params={"error": "access_denied", "state": "x"}
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "https://evil.test"},
        {"aud": "andere-client"},
        {"exp": 1000},
        {"nonce": "verkeerd"},
        {"iat": None},
        {"aud": [CLIENT_ID, "ander"]},  # meerdere audiences zonder azp
    ],
)
def test_invalid_id_token_claims_rejected(
    web: TestClient, idp: FakeIdP, db: Session, override: dict
) -> None:
    make_user(db, sub="s")
    idp.token_overrides = override
    response = complete_login(web, idp, "s")
    assert response.status_code == 400
    assert db.scalar(select(UserSession)) is None


def test_multiple_audiences_with_azp_accepted(
    web: TestClient, idp: FakeIdP, db: Session
) -> None:
    make_user(db, sub="s")
    idp.token_overrides = {"aud": [CLIENT_ID, "ander"], "azp": CLIENT_ID}
    assert complete_login(web, idp, "s").status_code == 303


def test_wrong_signature_rejected(web: TestClient, idp: FakeIdP, db: Session) -> None:
    make_user(db, sub="s")
    idp.sign_key = RSAKey.generate_key(2048, {"kid": "k1"})
    response = complete_login(web, idp, "s")
    assert response.status_code == 400


def test_alg_none_rejected(oidc: OIDCClient) -> None:
    def b64(data: dict) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = f"{b64({'alg': 'none'})}.{b64({'sub': 's', 'iss': ISSUER})}."
    with pytest.raises(Exception, match="ongeldig"):
        oidc.validate_id_token(token, "n")


def test_key_rotation_refreshes_jwks(
    web: TestClient, idp: FakeIdP, db: Session
) -> None:
    make_user(db, sub="s")
    assert complete_login(web, idp, "s").status_code == 303
    idp.key = RSAKey.generate_key(2048, {"kid": "k2"})
    web.cookies.clear()
    assert complete_login(web, idp, "s").status_code == 303
    assert idp.jwks_requests == 2


def test_logout_revokes_session(client: TestClient, db: Session, user: User) -> None:
    assert client.get("/").status_code == 200
    response = client.post("/auth/logout", headers=HTMX_HEADERS)
    assert response.status_code == 204
    assert response.headers["hx-redirect"] == "/auth/uitgelogd"
    session = db.scalars(select(UserSession)).one()
    db.refresh(session)
    assert session.revoked_at is not None
    assert "auth.logout" in actions(db)
    assert client.get("/").status_code == 303


def test_login_when_already_logged_in_redirects(
    web: TestClient, db: Session, user: User
) -> None:
    response = login_as(web, db, user).get("/auth/login", params={"next": "/scores"})
    assert response.status_code == 303
    assert response.headers["location"] == "/scores"


def test_login_without_configuration(anon_client: TestClient) -> None:
    response = anon_client.get("/auth/login")
    assert response.status_code == 503
    assert "niet ingesteld" in response.text


def test_logged_out_page(anon_client: TestClient) -> None:
    response = anon_client.get("/auth/uitgelogd")
    assert response.status_code == 200
    assert 'href="/auth/login"' in response.text


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/taken", "/taken"),
        ("/taken?x=1", "/taken?x=1"),
        ("https://evil.example", "/"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
        ("/auth/login", "/"),
        ("", "/"),
        (None, "/"),
    ],
)
def test_safe_next(target: str | None, expected: str) -> None:
    assert safe_next(target) == expected
