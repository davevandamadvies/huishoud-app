"""Schermen voor taken: lijst met zoeken/filter, aanmaken, wijzigen."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import categories, tasks
from app.auth import CurrentUser, current_user
from app.dates import due_label, today
from app.db import get_db
from app.forms import Form
from app.models import Role, Task, User, UserStatus
from app.recurrence import IntervalUnit, RecurrenceType, describe
from app.templating import templates

router = APIRouter(
    prefix="/taken",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]

RECURRENCE_LABELS = {
    RecurrenceType.INTERVAL: "Herhalen na het afvinken",
    RecurrenceType.FIXED_DATE: "Vaste datum (bijv. APK)",
    RecurrenceType.ONCE: "Eenmalig",
}
UNIT_LABELS = {
    IntervalUnit.DAYS: "dagen",
    IntervalUnit.WEEKS: "weken",
    IntervalUnit.MONTHS: "maanden",
}


def _context(db: Session, user: User, **extra: object) -> dict:
    return {
        "user": user,
        "active_nav": "tasks",
        "page_title": "Taken",
        "today": today(),
        "due_label": due_label,
        "describe": describe,
        **extra,
    }


def _list_context(
    db: Session, user: User, q: str, categorie: int | None, archief: bool
) -> dict:
    return _context(
        db,
        user,
        rows=tasks.list_tasks(db, search=q, category_id=categorie, archived=archief),
        categories=categories.list_categories(db),
        q=q,
        selected_category=categorie,
        archived=archief,
        archived_count=tasks.count_archived(db),
    )


@router.get("")
def list_page(
    request: Request,
    user: CurrentUser,
    db: DB,
    q: str = "",
    categorie: int | None = None,
    archief: bool = False,
) -> HTMLResponse:
    context = _list_context(db, user, q.strip(), categorie, archief)
    return templates.TemplateResponse(request, "pages/tasks.html", context)


@router.get("/lijst")
def list_partial(
    request: Request,
    user: CurrentUser,
    db: DB,
    q: str = "",
    categorie: int | None = None,
    archief: bool = False,
) -> HTMLResponse:
    context = _list_context(db, user, q.strip(), categorie, archief)
    return templates.TemplateResponse(request, "partials/task_list.html", context)


def _form_context(
    db: Session,
    user: User,
    *,
    task: Task | None,
    values: dict,
    errors: dict | None = None,
    error: str | None = None,
) -> dict:
    owners = db.scalars(
        select(User)
        .where(User.status == UserStatus.ACTIVE)
        .order_by(User.role != Role.ADMIN, User.display_name)
    ).all()
    return _context(
        db,
        user,
        task=task,
        values=values,
        errors=errors or {},
        error=error,
        categories=categories.list_categories(db),
        owners=owners,
        recurrence_labels=RECURRENCE_LABELS,
        unit_labels=UNIT_LABELS,
        page_title=task.name if task else "Nieuwe taak",
        has_history=tasks.has_history(db, task) if task else False,
    )


def _values_from_task(db: Session, task: Task) -> dict:
    pending = tasks.pending_occurrence(db, task)
    return {
        "name": task.name,
        "category_id": str(task.category_id),
        "recurrence_type": task.recurrence_type.value,
        "interval_every": str(task.interval_every or ""),
        "interval_unit": task.interval_unit.value,
        "owner_id": str(task.owner_id or ""),
        "default_points": str(task.default_points or ""),
        "notes": task.notes or "",
        "next_date": pending.due_date.isoformat()
        if pending and pending.due_date
        else "",
    }


def _get(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404)
    return task


@router.get("/nieuw")
def new_page(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    first_category = next(iter(categories.list_categories(db)), None)
    values = {
        "recurrence_type": RecurrenceType.INTERVAL.value,
        "interval_every": "7",
        "interval_unit": IntervalUnit.DAYS.value,
        "category_id": str(first_category.id) if first_category else "",
    }
    context = _form_context(db, user, task=None, values=values)
    return templates.TemplateResponse(request, "pages/task_form.html", context)


@router.post("")
def create(request: Request, user: CurrentUser, db: DB, form: Form) -> Response:
    try:
        data = tasks.parse_form(db, form)
    except tasks.TaskFormError as exc:
        values = {k: form.get_str(k) for k in form}
        context = _form_context(db, user, task=None, values=values, errors=exc.errors)
        return templates.TemplateResponse(request, "partials/task_form.html", context)
    tasks.create(db, user, data)
    return Response(status_code=204, headers={"HX-Redirect": "/taken"})


@router.get("/{task_id}")
def edit_page(
    request: Request, task_id: int, user: CurrentUser, db: DB
) -> HTMLResponse:
    task = _get(db, task_id)
    context = _form_context(db, user, task=task, values=_values_from_task(db, task))
    return templates.TemplateResponse(request, "pages/task_form.html", context)


@router.post("/{task_id}")
def update(
    request: Request, task_id: int, user: CurrentUser, db: DB, form: Form
) -> Response:
    task = _get(db, task_id)
    try:
        data = tasks.parse_form(db, form)
    except tasks.TaskFormError as exc:
        values = {k: form.get_str(k) for k in form}
        context = _form_context(db, user, task=task, values=values, errors=exc.errors)
        return templates.TemplateResponse(request, "partials/task_form.html", context)
    tasks.update(db, user, task, data)
    return Response(status_code=204, headers={"HX-Redirect": "/taken"})


@router.post("/{task_id}/archiveren")
def archive(task_id: int, user: CurrentUser, db: DB) -> Response:
    tasks.archive(db, user, _get(db, task_id))
    return Response(status_code=204, headers={"HX-Redirect": "/taken"})


@router.post("/{task_id}/herstellen")
def restore(task_id: int, user: CurrentUser, db: DB) -> Response:
    task = _get(db, task_id)
    tasks.restore(db, user, task)
    return Response(status_code=204, headers={"HX-Redirect": f"/taken/{task.id}"})


@router.post("/{task_id}/verwijderen")
def delete(request: Request, task_id: int, user: CurrentUser, db: DB) -> Response:
    task = _get(db, task_id)
    try:
        tasks.delete(db, user, task)
    except tasks.TaskError as exc:
        db.rollback()
        context = _form_context(
            db, user, task=task, values=_values_from_task(db, task), error=str(exc)
        )
        return templates.TemplateResponse(request, "partials/task_form.html", context)
    return Response(status_code=204, headers={"HX-Redirect": "/taken"})
