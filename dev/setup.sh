#!/usr/bin/env bash
# Maakt de geheimen en testaccounts voor de lokale ontwikkelomgeving aan in
# dev/.secrets (staat in .gitignore). Veilig om opnieuw te draaien: bestaande
# bestanden blijven staan. Met --reset begin je opnieuw.
set -euo pipefail

cd "$(dirname "$0")/.."
SECRETS=dev/.secrets
COMPOSE=(docker compose -f compose.dev.yml)
AUTHELIA_IMAGE=$(sed -n 's/^ *image: \(authelia\/authelia[^ ]*\)$/\1/p' compose.dev.yml)
TEST_PASSWORD=huishoud-dev

if [[ "${1:-}" == "--reset" ]]; then
  "${COMPOSE[@]}" down --volumes
  rm -rf "$SECRETS"
fi

mkdir -p "$SECRETS"
chmod 700 "$SECRETS"

authelia() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/$SECRETS:/out" \
    "$AUTHELIA_IMAGE" authelia "$@"
}

random() {
  authelia crypto rand --length 64 --charset alphanumeric | sed 's/^Random Value: //'
}

new_secret() {
  [[ -s "$SECRETS/$1" ]] || random >"$SECRETS/$1"
}

new_secret jwt_secret
new_secret session_secret
new_secret storage_encryption_key
new_secret oidc_hmac_secret
new_secret oidc_client_secret

if [[ ! -s "$SECRETS/oidc_jwk.pem" ]]; then
  authelia crypto pair rsa generate --bits 2048 --directory /out \
    --file.private-key oidc_jwk.pem --file.public-key oidc_jwk.pub.pem >/dev/null
fi

if [[ ! -s "$SECRETS/oidc_client_secret.digest" ]]; then
  authelia crypto hash generate pbkdf2 --variant sha512 \
    --password "$(cat "$SECRETS/oidc_client_secret")" |
    sed -n 's/^Digest: //p' >"$SECRETS/oidc_client_secret.digest"
fi

if [[ ! -s "$SECRETS/users.yml" ]]; then
  HASH=$(authelia crypto hash generate argon2 --password "$TEST_PASSWORD" | sed -n 's/^Digest: //p')
  cat >"$SECRETS/users.yml" <<USERS
users:
  dave:
    displayname: "Dave (test)"
    password: "$HASH"
    email: dave@example.com
  partner:
    displayname: "Partner (test)"
    password: "$HASH"
    email: partner@example.com
USERS
fi

# Vaste OIDC-subject per testaccount, zodat INITIAL_ADMIN_SUB vooraf bekend is.
for user in dave partner; do
  [[ -s "$SECRETS/sub_$user" ]] || python3 -c 'import uuid; print(uuid.uuid4())' >"$SECRETS/sub_$user"
done

if [[ ! -s "$SECRETS/app.env" ]]; then
  cat >"$SECRETS/app.env" <<APPENV
BASE_URL=https://huishoud.localhost:8443
OIDC_ISSUER=https://auth.huishoud.localhost:8443
OIDC_CLIENT_ID=huishoud-dev
OIDC_CLIENT_SECRET=$(cat "$SECRETS/oidc_client_secret")
INITIAL_ADMIN_SUB=$(cat "$SECRETS/sub_dave")
INITIAL_ADMIN_NAME=Dave
APPENV
fi

# Authelia-database klaarzetten en de subjects registreren.
"${COMPOSE[@]}" run --rm --no-deps authelia authelia storage migrate up >/dev/null
for user in dave partner; do
  "${COMPOSE[@]}" run --rm --no-deps authelia authelia storage user identifiers add \
    "$user" --service openid --identifier "$(cat "$SECRETS/sub_$user")" >/dev/null 2>&1 || true
done

echo "Klaar. Start met: docker compose -f compose.dev.yml up --build"
echo "Testaccounts: dave / partner, wachtwoord: $TEST_PASSWORD"
echo "sub van partner (voor 'Toegang geven'): $(cat "$SECRETS/sub_partner")"
