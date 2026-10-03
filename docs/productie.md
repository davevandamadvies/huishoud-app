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
| `VAPID_PUBLIC_KEY` | *(zie stap 6)* | Voor meldingen. |
| `VAPID_PRIVATE_KEY` | *(geheim)* | Voor meldingen. Alleen in `.env`, nooit in git. |
| `VAPID_SUBJECT` | `mailto:jij@<domein>` | Contactadres dat de pushdienst (Google) bij problemen gebruikt. |
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

## 6. Meldingen (Web Push)

Maak eenmalig een sleutelpaar en zet de regels in `.env` (gebruik voor
`huishoud` en `huishoud-test` elk een eigen paar):

```sh
docker compose run --rm huishoud python -m app.push sleutels
```

Herstart daarna de service. Vervang de sleutels niet zonder reden: bestaande
abonnementen werken dan niet meer en iedereen moet meldingen opnieuw aanzetten.

De app stuurt meldingen alleen naar bekende pushdiensten (o.a.
`fcm.googleapis.com` voor Chrome op Android); de container heeft daarvoor
uitgaand HTTPS-verkeer nodig. Meldingen werken alleen via HTTPS met een
certificaat dat de telefoon vertrouwt.

De herinneringen worden binnen de app gepland (elke minuut, tijdzone
Europe/Amsterdam); er is geen cronjob of extra container nodig. De container
moet dus blijven draaien. Na een herstart haalt de app een gemist tijdstip
hooguit 15 minuten later in.

## Controle na het uitrollen

- `https://huishoud.<domein>/healthz` geeft `{"status":"ok"}`.
- Inloggen leidt naar Authelia en terug. Bij "Inloggen is nog niet ingesteld"
  ontbreken variabelen: de app-log noemt welke.
- In de browser hebben de cookies `__Host-huishoud_session` de vlaggen
  `Secure`, `HttpOnly` en `SameSite=Lax`.
- Instellingen → Meldingen → "Meldingen aanzetten" en "Testmelding sturen"
  geeft een melding op de telefoon.
