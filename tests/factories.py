from itertools import count

from sqlalchemy.orm import Session

from app.models import Role, User, UserStatus

_seq = count(1)


def make_user(
    db: Session,
    *,
    name: str | None = None,
    role: Role = Role.USER,
    status: UserStatus = UserStatus.ACTIVE,
    sub: str | None = None,
) -> User:
    n = next(_seq)
    user = User(
        display_name=name or f"Gebruiker {n}",
        oidc_sub=sub or f"sub-{n}",
        role=role,
        status=status,
    )
    db.add(user)
    db.commit()
    return user


def make_category(db: Session, name: str | None = None, color: str = "green"):  # noqa: ANN201
    from app.models import Category

    category = Category(name=name or f"Categorie {next(_seq)}", color=color, position=1)
    db.add(category)
    db.commit()
    return category


def make_task(  # noqa: ANN201
    db: Session,
    *,
    name: str = "Stofzuigen",
    category=None,  # noqa: ANN001
    every: int | None = 7,
    recurrence: str = "interval",
    due=None,  # noqa: ANN001
    **kwargs,  # noqa: ANN003
):
    from app.models import Occurrence, Task
    from app.recurrence import RecurrenceType

    task = Task(
        name=name,
        category=category or make_category(db),
        recurrence_type=RecurrenceType(recurrence),
        interval_every=every,
        **kwargs,
    )
    db.add(task)
    db.flush()
    if due is not None:
        db.add(Occurrence(task_id=task.id, due_date=due))
    db.commit()
    return task
