from datetime import time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import completion, planning, tasks, today_view
from app.dates import today
from app.models import AuditLog, Occurrence, OccurrenceStatus, User, UserStatus
from app.planning import PlanInput
from tests.factories import make_task, make_user


def plan_input(days: int = 2, **kwargs: object) -> PlanInput:
    return PlanInput(planned_date=today() + timedelta(days=days), **kwargs)


def test_plan_open_occurrence_keeps_due_date(db: Session, user: User) -> None:
    due = today() + timedelta(days=5)
    task = make_task(db, due=due, default_points=8)
    partner = make_user(db, name="Partner")
    occ = planning.plan(
        db,
        user,
        task,
        plan_input(2, planned_time=time(10, 0), owner_ids=(partner.id, user.id)),
    )
    assert occ.status == OccurrenceStatus.PLANNED
    assert occ.due_date == due
    assert occ.planned_date == today() + timedelta(days=2)
    assert occ.effective_date == occ.planned_date
    assert occ.planned_time == time(10, 0)
    assert [o.user_id for o in occ.owners] == sorted([user.id, partner.id])
    # Punten standaard van de taak
    assert occ.points == 8
    entry = db.scalars(select(AuditLog)).one()
    assert entry.action == "occurrence.plan"
    assert entry.new_value["planned_time"] == "10:00"


def test_plan_task_without_open_occurrence(db: Session, user: User) -> None:
    task = make_task(db)
    occ = planning.plan(db, user, task, plan_input(1))
    assert occ.due_date is None
    assert tasks.pending_occurrence(db, task).id == occ.id
    assert occ.owners == []


def test_plan_twice_is_refused_and_never_stacks(db: Session, user: User) -> None:
    task = make_task(db, due=today())
    planning.plan(db, user, task, plan_input(1))
    with pytest.raises(planning.PlanningError, match="al ingepland"):
        planning.plan(db, user, task, plan_input(3))
    db.add(Occurrence(task_id=task.id, status=OccurrenceStatus.PLANNED))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (lambda: plan_input(-1), "vanaf vandaag"),
        (lambda: plan_input(367), "een jaar"),
        (lambda: plan_input(1, points=0), "Punten"),
        (lambda: plan_input(1, owner_ids=(999,)), "actieve"),
    ],
)
def test_validation(db: Session, user: User, data, message: str) -> None:  # noqa: ANN001
    with pytest.raises(planning.PlanningError, match=message):
        planning.plan(db, user, make_task(db), data())


def test_deactivated_owner_refused(db: Session, user: User) -> None:
    old = make_user(db, status=UserStatus.DEACTIVATED)
    with pytest.raises(planning.PlanningError):
        planning.plan(db, user, make_task(db), plan_input(1, owner_ids=(old.id,)))


def test_archived_task_refused(db: Session, user: User) -> None:
    task = make_task(db)
    tasks.archive(db, user, task)
    with pytest.raises(planning.PlanningError, match="archief"):
        planning.plan(db, user, task, plan_input(1))


def test_reschedule(db: Session, user: User) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, due=today())
    occ = planning.plan(db, user, task, plan_input(1, owner_ids=(user.id,)))
    planning.reschedule(
        db, user, occ, plan_input(4, planned_time=time(14, 30), owner_ids=(partner.id,))
    )
    assert occ.planned_date == today() + timedelta(days=4)
    assert [o.user_id for o in occ.owners] == [partner.id]
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "occurrence.reschedule")
    ).one()
    assert entry.old_value["owners"] == [user.id]
    assert entry.new_value["planned_time"] == "14:30"


def test_reschedule_past_plan_keeps_date(db: Session, user: User) -> None:
    task = make_task(db, due=today())
    occ = planning.plan(db, user, task, plan_input(1))
    occ.planned_date = today() - timedelta(days=2)  # inmiddels voorbij
    db.commit()
    # Alleen de eigenaar wijzigen mag; de oude datum blijft geldig
    planning.reschedule(
        db, user, occ, PlanInput(occ.planned_date, owner_ids=(user.id,))
    )
    with pytest.raises(planning.PlanningError, match="vanaf vandaag"):
        planning.reschedule(db, user, occ, plan_input(-1))


def test_reschedule_requires_planned(db: Session, user: User) -> None:
    task = make_task(db, due=today())
    with pytest.raises(planning.PlanningError, match="niet ingepland"):
        planning.reschedule(db, user, tasks.pending_occurrence(db, task), plan_input(1))


def test_cancel_returns_to_open_with_due_date(db: Session, user: User) -> None:
    due = today() + timedelta(days=3)
    task = make_task(db, due=due)
    occ = planning.plan(db, user, task, plan_input(1, owner_ids=(user.id,), points=4))
    planning.cancel(db, user, occ)
    assert occ.status == OccurrenceStatus.OPEN
    assert occ.due_date == due
    assert occ.planned_date is None and occ.planned_time is None
    assert occ.owners == [] and occ.points is None
    assert "occurrence.cancel_plan" in db.scalars(select(AuditLog.action)).all()


def test_cancel_without_due_date_removes_occurrence(db: Session, user: User) -> None:
    task = make_task(db)
    occ = planning.plan(db, user, task, plan_input(1))
    planning.cancel(db, user, occ)
    assert tasks.pending_occurrence(db, task) is None


def test_complete_planned_counts_from_completion_not_plan(
    db: Session, user: User
) -> None:
    task = make_task(db, every=7, due=today() - timedelta(days=1))
    planning.plan(db, user, task, plan_input(3))
    result = completion.complete(db, user, task, performer_ids=[user.id])
    assert result.occurrence.status == OccurrenceStatus.DONE
    assert result.next_occurrence.due_date == today() + timedelta(days=7)
    assert result.next_occurrence.status == OccurrenceStatus.OPEN


def test_complete_planned_fixed_date_keeps_rhythm(db: Session, user: User) -> None:
    due = today() + timedelta(days=10)
    task = make_task(db, every=30, recurrence="fixed_date", due=due)
    planning.plan(db, user, task, plan_input(2))
    result = completion.complete(db, user, task, performer_ids=[user.id])
    assert result.next_occurrence.due_date == due + timedelta(days=30)


def test_past_plan_counts_as_late(db: Session, user: User) -> None:
    task = make_task(db, name="Dakgoot", due=today() + timedelta(days=20))
    occ = planning.plan(db, user, task, plan_input(1))
    occ.planned_date = today() - timedelta(days=1)
    db.commit()
    view = today_view.build(db, today())
    assert [o.task.name for o in view.late] == ["Dakgoot"]
