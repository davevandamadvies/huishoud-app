"""Beginlijst taken (akkoord, 2 okt 2026). Startvulling; alles is aanpasbaar.

Velden die de app nog niet gebruikt (seizoen, winterinterval, kilometers)
staan er al bij, zodat een latere datamigratie ze kan aanvullen.
"""

from dataclasses import dataclass

D, M = "days", "months"


@dataclass(frozen=True)
class SeedTask:
    category: str
    name: str
    every: int | None
    unit: str = D
    points: int | None = None
    recurrence: str = "interval"
    season: tuple[int, ...] | None = None  # actieve maanden (fase 6)
    winter_every: int | None = None  # interval in de winter, nov–feb (fase 6)
    km: int | None = None  # of-kilometers (fase 5)
    notes: str | None = None
    first_reminder_days: int | None = None  # alleen bij een vaste datum


def months(first: int, last: int) -> tuple[int, ...]:
    if first <= last:
        return tuple(range(first, last + 1))
    return tuple(range(first, 13)) + tuple(range(1, last + 1))


S, H, A, T, P, TE = (
    "Schoonmaak",
    "Huis & installaties",
    "Auto",
    "Tuin",
    "Planten",
    "Techniek",
)

TASKS: tuple[SeedTask, ...] = (
    # Schoonmaak
    SeedTask(S, "Stofzuigen hele huis", 7, points=5),
    SeedTask(S, "Vloeren dweilen", 14, points=5),
    SeedTask(S, "Badkamer schoonmaken", 7, points=8),
    SeedTask(S, "Toilet schoonmaken", 7, points=4),
    SeedTask(S, "Keuken grondig (aanrecht, kookplaat, fronten)", 14, points=6),
    SeedTask(S, "Stoffen (kasten, plinten, vensterbanken)", 14, points=4),
    SeedTask(S, "Beddengoed verschonen", 14, points=4),
    SeedTask(S, "Koelkast schoonmaken", 60, points=5),
    SeedTask(S, "Oven schoonmaken", 90, points=8),
    SeedTask(S, "Ramen binnen lappen", 60, points=8),
    SeedTask(S, "Ramen buiten lappen", 90, points=10, season=months(3, 10)),
    # Huis & installaties
    SeedTask(H, "Rookmelders testen", 30, points=2),
    SeedTask(H, "CV-waterdruk controleren", 30, points=1),
    SeedTask(H, "CV-ketel onderhoud (afspraak monteur)", 12, M, points=3),
    SeedTask(H, "Radiatoren ontluchten", 12, M, points=5, season=months(9, 11)),
    SeedTask(H, "Afzuigkapfilter reinigen", 90, points=3),
    SeedTask(H, "Vaatwasserfilter reinigen", 30, points=2),
    SeedTask(H, "Wasmachine reinigen (leegwas 90°)", 30, points=2),
    SeedTask(H, "Waterkoker/koffiezetapparaat ontkalken", 60, points=2),
    SeedTask(H, "Ventilatieroosters/-filters reinigen", 180, points=3),
    SeedTask(H, "Dakgoten schoonmaken", 12, M, points=10, season=months(10, 12)),
    SeedTask(
        H, "Zonnepanelen visueel controleren", 12, M, points=4, season=months(4, 9)
    ),
    # Auto
    SeedTask(
        A, "Oliepeil, koelvloeistof en ruitensproeiervloeistof checken", 30, points=2
    ),
    SeedTask(A, "Bandenspanning controleren", 30, points=2),
    SeedTask(
        A,
        "Olie verversen / onderhoudsbeurt",
        12,
        M,
        points=10,
        km=15000,
        notes="15.000 km of jaarlijks, wat het eerst komt (onderhoudsboekje checken).",
    ),
    SeedTask(
        A,
        "APK",
        12,
        M,
        points=5,
        recurrence="fixed_date",
        notes="Vaste datum; reminder vanaf 2 maanden vooraf.",
        first_reminder_days=60,
    ),
    SeedTask(A, "Auto wassen", 30, points=4),
    SeedTask(A, "Interieur stofzuigen", 30, points=3),
    # Tuin
    SeedTask(T, "Gras maaien", 7, points=6, season=months(3, 10)),
    SeedTask(T, "Onkruid wieden", 14, points=6, season=months(4, 9)),
    SeedTask(T, "Heg snoeien", 90, points=12, season=months(5, 9)),
    SeedTask(T, "Gazon bemesten", 120, points=4, season=months(3, 10)),
    SeedTask(T, "Terras/tegels reinigen", 12, M, points=10, season=months(4, 6)),
    SeedTask(T, "Bladeren ruimen", 14, points=6, season=months(10, 12)),
    SeedTask(
        T, "Tuinmeubels opruimen/afdekken", 12, M, points=6, season=months(10, 11)
    ),
    SeedTask(T, "Buitenkraan aftappen", 12, M, points=2, season=months(11, 11)),
    # Planten
    SeedTask(P, "Kamerplanten water geven", 7, points=1, winter_every=14),
    SeedTask(P, "Kruiden op de vensterbank water geven", 3, points=1, winter_every=5),
    SeedTask(P, "Kamerplanten voeden", 14, points=2, season=months(3, 9)),
    SeedTask(P, "Bladeren afstoffen of besproeien", 30, points=2),
    SeedTask(P, "Controleren op ongedierte", 30, points=1),
    SeedTask(P, "Verpotten (waar nodig)", 12, M, points=6, season=months(3, 4)),
    # Techniek
    SeedTask(TE, "Updates NAS en router controleren/installeren", 30, points=3),
    SeedTask(TE, "Back-up terugzetten testen", 90, points=5),
    SeedTask(TE, "Logging/alerts doorlopen", 30, points=3),
)
