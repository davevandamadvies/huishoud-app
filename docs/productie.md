# Productie: app achter een reverse proxy met HTTPS

Inloggen via OIDC en de `Secure`-cookies werken alleen via HTTPS. In productie
staat er daarom een reverse proxy (met certificaat) vóór de app. Authelia draait
als aparte dienst. Dit document beschrijft wat de **app** nodig heeft. De
inrichting van de NAS zelf (proxy, certificaat, Authelia, Tailscale) staat
daarbuiten.

```
browser ──HTTPS──▶ reverse proxy ──HTTP──▶ app (poort 8000, container)
                         │
                         └──HTTPS──▶ Authelia (auth.<domein>)
app ──HTTPS──▶ Authelia (discovery, JWKS, token)
```

## 1. Authelia: OIDC-client voor de app

Maak een client-secret en de bijbehorende hash:

```sh
docker run --rm authelia/authelia:4.39 authelia crypto rand --length 64 --charset alphanumeric
docker run --rm authelia/authelia:4.39 authelia crypto hash generate pbkdf2 --variant sha512 --password '<secret>'
```

Neem de client op in de Authelia-configuratie (de hash, niet het secret):

```yaml
identity_providers:
  oidc:
    clients:
      - client_id: huishoud
        client_name: Huishoud
        client_secret: '$pbkdf2-sha512$...'   # de digest van hierboven
        public: false
        authorization_policy: two_factor       # 2FA, bij voorkeur passkeys
        require_pkce: true
        pkce_challenge_method: S256
        redirect_uris:
          - https://huishoud.<domein>/auth/callback
        scopes: [openid, profile]
        response_types: [code]
        grant_types: [authorization_code]
        token_endpoint_auth_method: client_secret_basic
        id_token_signed_response_alg: RS256
```

De app accepteert alleen RS256-ondertekende ID-tokens en eist PKCE (S256).

## 2. Omgevingsvariabelen van de app (`.env` op de NAS)

| Variabele | Voorbeeld | Toelichting |
|---|---|---|
| `APP_ENV` | `prod` | |
| `BASE_URL` | `https://huishoud.<domein>` | Publieke URL; bepaalt de redirect-URI en de Origin-controle. Moet exact overeenkomen met de URL in de browser. |
| `OIDC_ISSUER` | `https://auth.<domein>` | Moet exact gelijk zijn aan de `issuer` van Authelia. |
| `OIDC_CLIENT_ID` | `huishoud` | |
| `OIDC_CLIENT_SECRET` | *(geheim)* | Het secret zelf (niet de hash). Alleen in `.env`, nooit in git. |
| `INITIAL_ADMIN_SUB` | *(zie stap 4)* | |
| `FORWARDED_ALLOW_IPS` | `172.20.0.10` | IP van de reverse proxy, zodat uvicorn de `X-Forwarded-*`-headers van alleen die proxy vertrouwt. **Nooit `*`.** |

Met `APP_ENV=prod` en een `https://`-`BASE_URL` stuurt de app zelf ook
`Strict-Transport-Security` mee.

De app vertrouwt de proxy-headers niet voor beveiligingsbeslissingen.
Redirect-URI en Origin-controle komen uit `BASE_URL`. `FORWARDED_ALLOW_IPS`
zorgt alleen voor correcte client-IP's en schema in de logs.

De app moet Authelia via `OIDC_ISSUER` kunnen bereiken, met een certificaat dat
de container vertrouwt. Bij een eigen CA: zet `SSL_CERT_FILE` naar het
CA-bestand (gemount, alleen-lezen).

## 3. Reverse proxy

Voorbeeld met Caddy (andere proxies werken net zo):

```
huishoud.<domein> {
	reverse_proxy huishoud:8000
}
```

Een vast IP voor de proxy in het Docker-netwerk maakt `FORWARDED_ALLOW_IPS`
eenvoudig. De app-container zelf hoeft geen poort naar buiten te hebben.

## 4. Eerste beheerder

1. Start de app zonder `INITIAL_ADMIN_SUB` en log in met je Authelia-account.
2. Je ziet "Geen toegang" met je **account-ID** (`sub`).
3. Zet dat ID in `INITIAL_ADMIN_SUB` (en eventueel `INITIAL_ADMIN_NAME`) en
   herstart de app. Je account wordt beheerder, en dat staat in de audit log.
4. Geef je partner daarna toegang via Instellingen → Gebruikers beheren, met
   het account-ID dat op diens "Geen toegang"-pagina staat.

`INITIAL_ADMIN_SUB` doet niets meer zodra er een beheerder bestaat.

## 5. Database en startvulling

```sh
docker compose run --rm huishoud alembic upgrade head
docker compose run --rm huishoud python -m app.seed      # eenmalig, optioneel
```

## Controle na het uitrollen

- `https://huishoud.<domein>/healthz` geeft `{"status":"ok"}`.
- Inloggen leidt naar Authelia en terug. Bij "Inloggen is nog niet ingesteld"
  ontbreken variabelen: de app-log noemt welke.
- In de browser hebben de cookies `__Host-huishoud_session` de vlaggen
  `Secure`, `HttpOnly` en `SameSite=Lax`.
