"""Statistieken: wat er gedaan is, hoe vaak op tijd, door wie en wat het kostte."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Category, Occurrence, OccurrenceStatus, Performer, Task, User
from app.recurrence import MONTH_ABBR, MONTH_NAMES, IntervalUnit, add_interval

MAX_MONTHS = 24
TOP = 5


class Range(StrEnum):
    YEAR = "jaar"
    LAST_12 = "12m"
    ALL = "alles"


RANGE_LABELS = {Range.YEAR: "Dit jaar", Range.LAST_12: "12 maanden", Range.ALL: "Alles"}


@dataclass(frozen=True)
class Bucket:
    """Eén staaf: een maand of (bij een lange periode) een jaar."""

    key: tuple[int, int]
    short: str
    long: str
    value: int


@dataclass(frozen=True)
class Row:
    label: str
    value: int
    color: str | None = None
    detail: str | None = None


@dataclass
class Stats:
    start: date
    end: date
    done: int = 0
    on_time: int = 0
    with_due: int = 0
    per_period: list[Bucket] = field(default_factory=list)
    most_late: list[Row] = field(default_factory=list)
    per_category: list[Row] = field(default_factory=list)
    per_person: list[Row] = field(default_factory=list)
    cost_total: int = 0
    cost_per_period: list[Bucket] = field(default_factory=list)
    cost_per_category: list[Row] = field(default_factory=list)
    cost_top: list[Row] = field(default_factory=list)

    @property
    def on_time_pct(self) -> int | None:
        if not self.with_due:
            return None
        return round(100 * self.on_time / self.with_due)


def bounds(selected: Range, today: date, first: date | None) -> tuple[date, date]:
    if selected == Range.YEAR:
        return date(today.year, 1, 1), today
    if selected == Range.LAST_12:
        start = add_interval(today.replace(day=1), -11, IntervalUnit.MONTHS)
        return start, today
    return (first or today).replace(day=1), today


def _months(start: date, end: date) -> list[tuple[int, int]]:
    months, current = [], start.replace(day=1)
    while current <= end:
        months.append((current.year, current.month))
        current = add_interval(current, 1, IntervalUnit.MONTHS)
    return months


def _buckets(
    start: date, end: date, values: dict[tuple[int, int], int]
) -> list[Bucket]:
    months = _months(start, end)
    if len(months) <= MAX_MONTHS:
        return [
            Bucket(
                (y, m),
                MONTH_ABBR[m - 1],
                f"{MONTH_NAMES[m - 1]} {y}",
                values.get((y, m), 0),
            )
            for y, m in months
        ]
    per_year: Counter[int] = Counter()
    for (y, _m), value in values.items():
        per_year[y] += value
    return [
        Bucket((y, 0), str(y), str(y), per_year.get(y, 0))
        for y in range(start.year, end.year + 1)
    ]


def build(db: Session, selected: Range, today: date) -> Stats:
    first = db.scalar(
        select(func.min(Occurrence.completed_on)).where(
            Occurrence.status == OccurrenceStatus.DONE
        )
    )
    start, end = bounds(selected, today, first)
    stats = Stats(start=start, end=end)
    done = list(
        db.scalars(
            select(Occurrence)
            .where(
                Occurrence.status == OccurrenceStatus.DONE,
                Occurrence.completed_on >= start,
                Occurrence.completed_on <= end,
            )
            .options(joinedload(Occurrence.task).joinedload(Task.category))
        ).unique()
    )
    stats.done = len(done)
    if not done:
        stats.per_period = _buckets(start, end, {})
        return stats

    per_month: Counter[tuple[int, int]] = Counter()
    cost_month: Counter[tuple[int, int]] = Counter()
    late_count: Counter[int] = Counter()
    late_days: defaultdict[int, int] = defaultdict(int)
    per_cat: Counter[int] = Counter()
    cost_cat: Counter[int] = Counter()
    cost_task: Counter[int] = Counter()
    tasks: dict[int, Task] = {}
    categories: dict[int, Category] = {}

    for occurrence in done:
        task = occurrence.task
        tasks[task.id] = task
        categories[task.category_id] = task.category
        key = (occurrence.completed_on.year, occurrence.completed_on.month)
        per_month[key] += 1
        per_cat[task.category_id] += 1
        if occurrence.due_date is not None:
            stats.with_due += 1
            if occurrence.completed_on <= occurrence.due_date:
                stats.on_time += 1
            else:
                late_count[task.id] += 1
                late_days[task.id] += (
                    occurrence.completed_on - occurrence.due_date
                ).days
        if occurrence.cost_cents:
            stats.cost_total += occurrence.cost_cents
            cost_month[key] += occurrence.cost_cents
            cost_cat[task.category_id] += occurrence.cost_cents
            cost_task[task.id] += occurrence.cost_cents

    stats.per_period = _buckets(start, end, per_month)
    stats.most_late = [
        Row(
            tasks[tid].name,
            count,
            detail=f"gemiddeld {round(late_days[tid] / count)} dagen te laat",
        )
        for tid, count in sorted(
            late_count.items(), key=lambda i: (-i[1], tasks[i[0]].name)
        )[:TOP]
    ]
    stats.per_category = [
        Row(categories[cid].name, count, categories[cid].color)
        for cid, count in sorted(
            per_cat.items(), key=lambda i: (-i[1], categories[i[0]].name)
        )
    ]
    people = db.execute(
        select(User.display_name, func.count())
        .join(Performer, Performer.user_id == User.id)
        .join(Occurrence, Occurrence.id == Performer.occurrence_id)
        .where(
            Occurrence.status == OccurrenceStatus.DONE,
            Occurrence.completed_on >= start,
            Occurrence.completed_on <= end,
        )
        .group_by(User.id)
        .order_by(func.count().desc(), User.display_name)
    ).all()
    stats.per_person = [Row(name, count) for name, count in people]
    if stats.cost_total:
        stats.cost_per_period = _buckets(start, end, cost_month)
        stats.cost_per_category = [
            Row(categories[cid].name, cents, categories[cid].color)
            for cid, cents in cost_cat.most_common()
        ]
        stats.cost_top = [
            Row(tasks[tid].name, cents) for tid, cents in cost_task.most_common(TOP)
        ]
    return stats


# ---- Geometrie voor de staafgrafiek (SVG, zonder inline stijl) ----

CHART_HEIGHT = 120
SLOT = 24
BAR = 14
RADIUS = 4


@dataclass(frozen=True)
class Bar:
    x: float
    y: float
    path: str
    label_x: float
    bucket: Bucket
    show_value: bool


def bars(buckets: list[Bucket]) -> tuple[int, list[Bar]]:
    """(breedte, staven) voor een SVG met viewBox 0 0 breedte CHART_HEIGHT+20."""
    top = max((b.value for b in buckets), default=0)
    width = SLOT * len(buckets)
    result = []
    highlight = {len(buckets) - 1}
    if top:
        highlight.add(max(range(len(buckets)), key=lambda i: buckets[i].value))
    for index, bucket in enumerate(buckets):
        x = index * SLOT + (SLOT - BAR) / 2
        height = 0 if not top else max(2.0, CHART_HEIGHT * bucket.value / top)
        y = CHART_HEIGHT - height
        r = min(RADIUS, height / 2, BAR / 2)
        right = x + BAR
        path = (
            f"M{x:.1f},{CHART_HEIGHT} V{y + r:.1f} "
            f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} H{right - r:.1f} "
            f"Q{right:.1f},{y:.1f} {right:.1f},{y + r:.1f} V{CHART_HEIGHT} Z"
            if bucket.value
            else ""
        )
        result.append(
            Bar(
                x,
                y,
                path,
                index * SLOT + SLOT / 2,
                bucket,
                bool(bucket.value) and index in highlight,
            )
        )
    return width, result


def share(value: int, rows: list[Row]) -> float:
    """Breedte (0–100) van een horizontale staaf ten opzichte van de grootste."""
    top = max((r.value for r in rows), default=0)
    return 0.0 if not top else max(1.5, 100 * value / top)
