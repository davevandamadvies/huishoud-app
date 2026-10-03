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

## Configuratie (omgevingsvariabelen)

| Variabele | Standaard | Betekenis |
|---|---|---|
| `APP_ENV` | `prod` | `dev`, `test` of `prod`; OpenAPI-docs alleen in `dev` |
| `DATABASE_URL` | `sqlite:////data/huishoud.db` | SQLAlchemy-URL van de database |
| `INITIAL_ADMIN_SUB` | – | `sub` van het Authelia-account dat bij de eerste start beheerder wordt (alleen zolang er geen beheerder is) |
| `INITIAL_ADMIN_NAME` | `Beheerder` | Weergavenaam van die eerste beheerder |
| `SESSION_MAX_AGE_DAYS` | `90` | Levensduur van een sessie; schuift mee bij gebruik |

Geheimen krijgen nooit een standaardwaarde en horen in `.env` (niet in git).
Zie `.env.example`.

## Migraties in productie

Migraties draaien niet automatisch. Op de NAS:

```sh
docker compose run --rm <service> alembic upgrade head
```
