# Huishoud-app

Eigen webapp (PWA) om periodieke huishoudtaken te plannen en bij te houden.
Python 3.13 + FastAPI, SQLite + Alembic, HTMX + Jinja2.

## Ontwikkelen

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Database lokaal aanmaken en de app starten:

```sh
export APP_ENV=dev DATABASE_URL=sqlite:///./dev.db INITIAL_ADMIN_SUB=<jouw-sub>
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Bij een wijziging aan het datamodel:

```sh
uv run alembic revision --autogenerate -m "korte omschrijving"
uv run alembic upgrade head && uv run alembic check
```

## Lokaal ontwikkelen met inloggen (Authelia)

Voor het echte inlogproces draait er lokaal een volledige omgeving in Docker:
de app, [Authelia](https://www.authelia.com/) als identity provider (OIDC) en
Caddy voor HTTPS (Authelia werkt alleen via HTTPS).

```sh
./dev/setup.sh                                  # eenmalig: geheimen + testaccounts
docker compose -f compose.dev.yml up --build
```

Open daarna <https://huishoud.localhost:8443> (de browser waarschuwt eenmalig
voor het lokale certificaat van Caddy). De database wordt in deze omgeving bij
het starten automatisch bijgewerkt.

Startvulling (45 taken) laden, terwijl de omgeving draait:

```sh
docker compose -f compose.dev.yml exec app python -m app.seed
```

Meldingen en de app op je beginscherm (PWA) werken alleen als de browser het
certificaat vertrouwt; met alleen een "toch doorgaan"-uitzondering registreert
Chrome geen service worker. Haal het lokale rootcertificaat van Caddy op en
importeer het in je systeem of browser (alleen voor ontwikkeling):

```sh
docker compose -f compose.dev.yml cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

Werkt `huishoud.localhost` niet in je browser (bijv. Safari), voeg dan deze regel
toe aan `/etc/hosts`: `127.0.0.1 huishoud.localhost auth.huishoud.localhost`.

- Testaccounts: `dave` (wordt beheerder) en `partner`, wachtwoord `huishoud-dev`.
- Alle geheimen staan in `dev/.secrets/` (in `.gitignore`); `./dev/setup.sh --reset`
  begint helemaal opnieuw.
- Deze configuratie is alleen voor ontwikkeling: 1-factor, testgeheimen,
  meldingen naar een bestand. Gebruik hem nooit voor productie.
- De automatische tests hebben deze omgeving niet nodig.

## Configuratie (omgevingsvariabelen)

| Variabele | Standaard | Betekenis |
|---|---|---|
| `APP_ENV` | `prod` | `dev`, `test` of `prod`; OpenAPI-docs alleen in `dev` |
| `DATABASE_URL` | `sqlite:////data/huishoud.db` | SQLAlchemy-URL van de database |
| `INITIAL_ADMIN_SUB` | – | `sub` van het Authelia-account dat bij de eerste start beheerder wordt (alleen zolang er geen beheerder is) |
| `INITIAL_ADMIN_NAME` | `Beheerder` | Weergavenaam van die eerste beheerder |
| `SESSION_MAX_AGE_DAYS` | `90` | Levensduur van een sessie; schuift mee bij gebruik |
| `BASE_URL` | – | Publieke URL van de app, bijv. `https://huishoud.example.com` (redirect-URI en Origin-controle) |
| `OIDC_ISSUER` | – | Issuer-URL van Authelia, bijv. `https://auth.example.com` |
| `OIDC_CLIENT_ID` | – | Client-ID van de app in Authelia |
| `OIDC_CLIENT_SECRET` | – | Client-secret (geheim, alleen in `.env`) |
| `OIDC_SCOPES` | `openid profile` | Gevraagde scopes |
| `BACKUP_DIR` | `/data/backups` | Map voor de nachtelijke back-ups (alleen SQLite) |
| `BACKUP_KEEP` | `14` | Aantal nachtelijke back-ups dat bewaard blijft |
| `VAPID_PUBLIC_KEY` | – | Publieke sleutel voor meldingen (Web Push) |
| `VAPID_PRIVATE_KEY` | – | Privésleutel voor meldingen (geheim, alleen in `.env`) |
| `VAPID_SUBJECT` | – | Contactadres voor de pushdienst, bijv. `mailto:jij@example.com` |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | (uvicorn) IP van de reverse proxy waarvan `X-Forwarded-*` wordt vertrouwd |

Ontbreken `BASE_URL` of `OIDC_*`, dan start de app wel (healthcheck werkt), maar
blijft hij dicht: inloggen toont "Inloggen is nog niet ingesteld".

Zonder de drie `VAPID_*`-variabelen staan meldingen uit; de rest van de app
werkt gewoon. Sleutels maak je met `python -m app.push sleutels` (in dev doet
`dev/setup.sh` dat). Iedereen zet meldingen daarna zelf aan via
Instellingen → Meldingen, en kiest onder "Mijn reminders" wanneer en hoe vaak
er een update komt.

De herinneringen verstuurt de app zelf: een achtergrondtaak kijkt elke minuut
(tijdzone Europe/Amsterdam) wat er volgens ieders voorkeuren weg moet. De tabel
`reminder_log` voorkomt dat iets twee keer wordt verstuurd; een tijdstip dat
tijdens een herstart is gemist, gaat hooguit 15 minuten later alsnog weg.

Wie bij Authelia kan inloggen maar niet als gebruiker in de app bekend is, krijgt
"Geen toegang" met zijn account-ID (`sub`). Dat ID gebruik je voor
`INITIAL_ADMIN_SUB` of bij "Toegang geven".

Geheimen krijgen nooit een standaardwaarde en horen in `.env` (niet in git).
Zie `.env.example`.

## Startvulling

De beginlijst met 45 taken (`app/seed_data.py`) laad je met:

```sh
uv run python -m app.seed                                   # lokaal
docker compose run --rm <service> python -m app.seed        # op de NAS
```

Het commando is veilig om opnieuw te draaien: taken die al bestaan (zelfde naam)
worden overgeslagen. De taken krijgen nog geen datum; ze verschijnen onder
Taken als "nog geen datum" tot je ze afvinkt of een "volgende keer" invult.

## Productie

Zie [docs/productie.md](docs/productie.md) voor de inrichting achter een reverse
proxy met HTTPS, de Authelia-client en de eerste beheerder.

## Migraties in productie

Migraties draaien niet automatisch. Op de NAS:

```sh
docker compose run --rm <service> alembic upgrade head
```
