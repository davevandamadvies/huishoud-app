"""Web Push: abonnementen bijhouden en versleutelde meldingen versturen.

- Versleuteling volgens RFC 8291 (aes128gcm) met http-ece.
- Identiteit van de server volgens RFC 8292 (VAPID) met py-vapid.
- Versturen met httpx; abonnementen die de pushdienst niet meer kent
  (404/410) worden opgeruimd.

Sleutels maken: `python -m app.push sleutels`.
"""

import base64
import json
import logging
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit
from app.db import utcnow
from app.models import PushSubscription, User
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# Alleen bekende pushdiensten als bestemming (voorkomt dat de server naar
# willekeurige adressen gaat posten).
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)
DEFAULT_TTL = 12 * 3600


class PushError(Exception):
    """Ongeldig abonnement of push niet ingesteld."""


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def generate_keys() -> tuple[str, str]:
    """Nieuw VAPID-sleutelpaar: (publiek, privé) als base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url_encode(public_raw), b64url_encode(private_raw)


def _host_allowed(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_PUSH_HOSTS
    )


def subscribe(
    db: Session, user: User, *, endpoint: str, p256dh: str, auth: str, label: str
) -> PushSubscription:
    endpoint, p256dh, auth = endpoint.strip(), p256dh.strip(), auth.strip()
    if len(endpoint) > 1024 or not _host_allowed(endpoint):
        raise PushError("Onbekende pushdienst.")
    try:
        if len(b64url_decode(p256dh)) != 65 or len(b64url_decode(auth)) != 16:
            raise ValueError
    except ValueError as exc:
        raise PushError("Ongeldige sleutels van het toestel.") from exc
    label = " ".join(label.split())[:100] or "Toestel"

    subscription = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint)
        db.add(subscription)
    # Een toestel hoort bij wie er nu op is ingelogd.
    subscription.user_id = user.id
    subscription.p256dh, subscription.auth, subscription.label = p256dh, auth, label
    db.flush()
    audit.record(
        db,
        "push.subscribe",
        actor=user,
        object_type="push_subscription",
        object_id=subscription.id,
        new={"label": label},
    )
    db.commit()
    return subscription


def unsubscribe(db: Session, user: User, subscription: PushSubscription) -> None:
    audit.record(
        db,
        "push.unsubscribe",
        actor=user,
        object_type="push_subscription",
        object_id=subscription.id,
        old={"label": subscription.label},
    )
    db.delete(subscription)
    db.commit()


def remove_all_for_user(db: Session, user: User) -> int:
    """Bij deactiveren: alle abonnementen weg (commit door de aanroeper)."""
    result = db.execute(
        delete(PushSubscription).where(PushSubscription.user_id == user.id)
    )
    return result.rowcount


def subscriptions_for(db: Session, user: User) -> list[PushSubscription]:
    return list(
        db.scalars(
            select(PushSubscription)
            .where(PushSubscription.user_id == user.id)
            .order_by(PushSubscription.created_at)
        )
    )


@dataclass
class SendResult:
    sent: int = 0
    removed: int = 0
    failed: int = 0


def _encrypt(payload: bytes, subscription: PushSubscription) -> bytes:
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    return http_ece.encrypt(
        payload,
        private_key=ephemeral,
        dh=b64url_decode(subscription.p256dh),
        auth_secret=b64url_decode(subscription.auth),
        version="aes128gcm",
    )


def _vapid_headers(settings: Settings, endpoint: str) -> dict[str, str]:
    if settings.vapid_private_key is None:
        raise PushError("VAPID-privésleutel ontbreekt.")
    vapid = Vapid02.from_raw(settings.vapid_private_key.get_secret_value().encode())
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": settings.vapid_subject,
    }
    return vapid.sign(claims)


def send(
    db: Session,
    subscriptions: list[PushSubscription],
    message: dict,
    *,
    ttl: int = DEFAULT_TTL,
    urgency: str = "normal",
    transport: httpx.BaseTransport | None = None,
) -> SendResult:
    """Verstuur een melding ({title, body, url, tag}) naar de abonnementen."""
    settings = get_settings()
    if not settings.push_enabled:
        raise PushError("Meldingen zijn niet ingesteld (VAPID-sleutels ontbreken).")
    payload = json.dumps(message, ensure_ascii=False).encode()
    result = SendResult()
    with httpx.Client(transport=transport, timeout=10.0) as http:
        for subscription in subscriptions:
            headers = {
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
                "Urgency": urgency,
                **_vapid_headers(settings, subscription.endpoint),
            }
            try:
                response = http.post(
                    subscription.endpoint,
                    content=_encrypt(payload, subscription),
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                logger.warning("Push mislukt (abonnement %s): %s", subscription.id, exc)
                result.failed += 1
                continue
            if response.status_code in (404, 410):
                db.delete(subscription)
                result.removed += 1
            elif response.is_success:
                subscription.last_used_at = utcnow()
                result.sent += 1
            else:
                logger.warning(
                    "Push geweigerd (abonnement %s): HTTP %s",
                    subscription.id,
                    response.status_code,
                )
                result.failed += 1
    db.commit()
    return result


def main(argv: list[str]) -> int:
    if argv[1:2] != ["sleutels"]:
        print("Gebruik: python -m app.push sleutels")
        return 2
    public, private = generate_keys()
    print("# Zet deze regels in .env (de privésleutel is geheim):")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print("VAPID_SUBJECT=mailto:jij@example.com")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
