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
voor het lokale certificaat van Caddy).

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
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | (uvicorn) IP van de reverse proxy waarvan `X-Forwarded-*` wordt vertrouwd |

Ontbreken `BASE_URL` of `OIDC_*`, dan start de app wel (healthcheck werkt), maar
blijft hij dicht: inloggen toont "Inloggen is nog niet ingesteld".

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
