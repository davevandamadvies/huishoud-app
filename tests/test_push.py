import json

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jws
from joserfc.jwk import ECKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import push, users
from app.models import AuditLog, PushSubscription, Role, User
from app.push_pages import device_label
from tests.conftest import HTMX_HEADERS
from tests.factories import make_user
from tests.push_helpers import Browser

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"
)


def _subscribe(
    db: Session, user: User, browser: Browser, endpoint: str = ENDPOINT
) -> PushSubscription:
    return push.subscribe(
        db,
        user,
        endpoint=endpoint,
        p256dh=browser.p256dh,
        auth=browser.auth_b64,
        label="Chrome op Android",
    )


def test_generated_keys_have_the_right_size() -> None:
    public, private = push.generate_keys()
    assert len(push.b64url_decode(public)) == 65
    assert len(push.b64url_decode(private)) == 32


def test_subscribe_stores_and_audits_without_endpoint(db: Session, user: User) -> None:
    subscription = _subscribe(db, user, Browser())
    assert subscription.user_id == user.id
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "push.subscribe"))
    assert entry is not None
    assert "fcm" not in json.dumps(entry.new_value)


def test_subscribe_again_moves_device_to_current_user(db: Session, user: User) -> None:
    browser = Browser()
    _subscribe(db, user, browser)
    other = make_user(db, name="Partner")
    _subscribe(db, other, browser)
    rows = list(db.scalars(select(PushSubscription)))
    assert len(rows) == 1
    assert rows[0].user_id == other.id


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example.com/push",
        "http://fcm.googleapis.com/fcm/send/x",
        "https://fcm.googleapis.com.evil.com/x",
        "https://localhost/push",
        "not a url",
    ],
)
def test_subscribe_rejects_unknown_push_services(
    db: Session, user: User, endpoint: str
) -> None:
    with pytest.raises(push.PushError):
        _subscribe(db, user, Browser(), endpoint)


def test_subscribe_rejects_invalid_keys(db: Session, user: User) -> None:
    with pytest.raises(push.PushError):
        push.subscribe(db, user, endpoint=ENDPOINT, p256dh="abc", auth="abc", label="x")


def test_send_encrypts_and_signs(db: Session, user: User, vapid) -> None:
    public, _ = vapid
    browser = Browser()
    subscription = _subscribe(db, user, browser)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201)

    result = push.send(
        db,
        [subscription],
        {"title": "Hoi", "body": "Één taak", "url": "/"},
        transport=httpx.MockTransport(handler),
    )

    assert result.sent == 1
    assert subscription.last_used_at is not None
    request = requests[0]
    assert str(request.url) == ENDPOINT
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["ttl"] == str(push.DEFAULT_TTL)
    assert browser.decrypt(request.content) == {
        "title": "Hoi",
        "body": "Één taak",
        "url": "/",
    }

    scheme, _, params = request.headers["authorization"].partition(" ")
    assert scheme == "vapid"
    fields = dict(part.split("=", 1) for part in params.split(","))
    assert fields["k"] == public
    x, y = push.b64url_decode(public)[1:33], push.b64url_decode(public)[33:]
    key = ECKey.import_key(
        {
            "kty": "EC",
            "crv": "P-256",
            "x": push.b64url_encode(x),
            "y": push.b64url_encode(y),
        }
    )
    token = jws.deserialize_compact(fields["t"], key, algorithms=["ES256"])
    claims = json.loads(token.payload)
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:test@example.com"


@pytest.mark.parametrize("status", [404, 410])
def test_send_removes_expired_subscriptions(
    db: Session, user: User, vapid, status: int
) -> None:
    subscription = _subscribe(db, user, Browser())
    result = push.send(
        db,
        [subscription],
        {"title": "x"},
        transport=httpx.MockTransport(lambda request: httpx.Response(status)),
    )
    assert result.removed == 1
    assert db.scalar(select(PushSubscription)) is None


def test_send_keeps_subscription_on_server_error(
    db: Session, user: User, vapid
) -> None:
    subscription = _subscribe(db, user, Browser())
    result = push.send(
        db,
        [subscription],
        {"title": "x"},
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    assert (result.sent, result.failed) == (0, 1)
    assert db.scalar(select(PushSubscription)) is not None


def test_send_handles_network_errors(db: Session, user: User, vapid) -> None:
    subscription = _subscribe(db, user, Browser())

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("geen netwerk")

    result = push.send(
        db, [subscription], {"title": "x"}, transport=httpx.MockTransport(handler)
    )
    assert result.failed == 1


def test_send_without_keys_raises(db: Session, user: User) -> None:
    subscription = _subscribe(db, user, Browser())
    with pytest.raises(push.PushError):
        push.send(db, [subscription], {"title": "x"})


def test_deactivating_user_removes_devices(db: Session, user: User) -> None:
    admin = make_user(db, name="Beheerder", role=Role.ADMIN)
    _subscribe(db, user, Browser())
    users.deactivate(db, admin, user)
    assert db.scalar(select(PushSubscription)) is None


def test_device_label() -> None:
    assert device_label(ANDROID_CHROME) == "Chrome op Android"
    assert device_label("") == "Browser"


def test_cli_prints_env_lines(capsys: pytest.CaptureFixture[str]) -> None:
    assert push.main(["app.push", "sleutels"]) == 0
    output = capsys.readouterr().out
    assert "VAPID_PUBLIC_KEY=" in output
    assert "VAPID_PRIVATE_KEY=" in output
    assert push.main(["app.push"]) == 2


# ---- Scherm ----


def test_page_without_keys_explains(client: TestClient) -> None:
    response = client.get("/meldingen")
    assert response.status_code == 200
    assert "Nog niet ingesteld" in response.text


def test_page_with_keys_exposes_public_key_only(client: TestClient, vapid) -> None:
    public, private = vapid
    response = client.get("/meldingen")
    assert public in response.text
    assert private not in response.text


def test_settings_links_to_notifications(client: TestClient) -> None:
    assert 'href="/meldingen"' in client.get("/meer").text


def test_subscribe_route(client: TestClient, db: Session, user: User, vapid) -> None:
    browser = Browser()
    response = client.post(
        "/meldingen/abonneren",
        data={"endpoint": ENDPOINT, "p256dh": browser.p256dh, "auth": browser.auth_b64},
        headers={**HTMX_HEADERS, "User-Agent": ANDROID_CHROME},
    )
    assert response.status_code == 200
    assert "Chrome op Android" in response.text
    assert db.scalar(select(PushSubscription.user_id)) == user.id


def test_subscribe_route_shows_error(client: TestClient, vapid) -> None:
    response = client.post(
        "/meldingen/abonneren",
        data={"endpoint": "https://evil.example.com", "p256dh": "x", "auth": "y"},
        headers=HTMX_HEADERS,
    )
    assert "Onbekende pushdienst" in response.text


def test_subscribe_route_needs_keys(client: TestClient) -> None:
    response = client.post("/meldingen/abonneren", data={}, headers=HTMX_HEADERS)
    assert response.status_code == 404


def test_subscribe_route_requires_csrf_headers(client: TestClient, vapid) -> None:
    response = client.post("/meldingen/abonneren", data={})
    assert response.status_code == 403


def test_unsubscribe_route(client: TestClient, db: Session, user: User) -> None:
    _subscribe(db, user, Browser())
    response = client.post(
        "/meldingen/afmelden", data={"endpoint": ENDPOINT}, headers=HTMX_HEADERS
    )
    assert response.status_code == 200
    assert db.scalar(select(PushSubscription)) is None


def test_cannot_remove_someone_elses_device(client: TestClient, db: Session) -> None:
    other = make_user(db, name="Partner")
    subscription = _subscribe(db, other, Browser())
    response = client.post(
        f"/meldingen/{subscription.id}/verwijderen", headers=HTMX_HEADERS
    )
    assert response.status_code == 404
    response = client.post(
        "/meldingen/afmelden", data={"endpoint": ENDPOINT}, headers=HTMX_HEADERS
    )
    db.expire_all()
    assert db.scalar(select(PushSubscription)) is not None


def test_remove_own_device(client: TestClient, db: Session, user: User) -> None:
    subscription = _subscribe(db, user, Browser())
    response = client.post(
        f"/meldingen/{subscription.id}/verwijderen", headers=HTMX_HEADERS
    )
    assert "Toestel verwijderd" in response.text
    assert db.scalar(select(PushSubscription)) is None


def test_test_route_without_devices(client: TestClient, vapid) -> None:
    response = client.post("/meldingen/test", headers=HTMX_HEADERS)
    assert "Zet eerst meldingen aan" in response.text


def test_test_route_sends(
    client: TestClient, db: Session, user: User, vapid, monkeypatch
) -> None:
    _subscribe(db, user, Browser())
    sent: list[dict] = []

    def fake_send(db, subscriptions, message, **kwargs):
        sent.append(message)
        return push.SendResult(sent=len(subscriptions))

    monkeypatch.setattr(push, "send", fake_send)
    response = client.post("/meldingen/test", headers=HTMX_HEADERS)
    assert "Testmelding verstuurd" in response.text
    assert sent[0]["title"] == "Testmelding"
