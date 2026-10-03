"""Schermen voor taken: lijst met zoeken/filter, aanmaken, wijzigen."""

from datetime import date, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import categories, completion, planning, settings_store, tasks
from app import points as app_points
from app.auth import CurrentUser, current_user
from app.dates import due_label, dutch_date, plan_label, today
from app.db import get_db
from app.forms import Form, FormData
from app.models import Occurrence, OccurrenceStatus, Role, Task, User, UserStatus
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
        "dutch_date": dutch_date,
        "plan_label": plan_label,
        "responsible": planning.responsible,
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
        log=completion.history(db, task) if task else [],
        pending=tasks.pending_occurrence(db, task) if task else None,
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


# ---- Afvinken (bottom sheet) ----


def _active_users(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.status == UserStatus.ACTIVE)
            .order_by(User.display_name)
        )
    )


def _sheet(
    request: Request,
    db: Session,
    user: User,
    task: Task,
    *,
    selected: list[int],
    completed_on: date,
    note: str = "",
    after: str = "event",
    error: str | None = None,
    points: int | None = None,
) -> HTMLResponse:
    context = _context(
        db,
        user,
        task=task,
        users=_active_users(db),
        selected=selected,
        completed_on=completed_on,
        note=note,
        after=after,
        error=error,
        preview=completion.preview_next(db, task, completed_on),
        max_days_back=completion.MAX_DAYS_BACK,
        points=points,
    )
    return templates.TemplateResponse(request, "partials/complete_sheet.html", context)


@router.get("/{task_id}/afronden")
def complete_sheet(
    request: Request, task_id: int, user: CurrentUser, db: DB, na: str = "event"
) -> HTMLResponse:
    task = _get(db, task_id)
    pending = tasks.pending_occurrence(db, task)
    owners = [o.user_id for o in pending.owners] if pending else []
    return _sheet(
        request,
        db,
        user,
        task,
        selected=owners or [user.id],
        completed_on=today(),
        points=completion.default_points(db, task),
        after="refresh" if na == "refresh" else "event",
    )


@router.get("/{task_id}/afronden/voorbeeld")
def complete_preview(
    request: Request, task_id: int, user: CurrentUser, db: DB, completed_on: str = ""
) -> HTMLResponse:
    task = _get(db, task_id)
    try:
        day = date.fromisoformat(completed_on)
    except ValueError:
        day = today()
    context = {
        "preview": completion.preview_next(db, task, day),
        "dutch_date": dutch_date,
    }
    return templates.TemplateResponse(request, "partials/next_preview.html", context)


@router.post("/{task_id}/afronden")
def complete(
    request: Request, task_id: int, user: CurrentUser, db: DB, form: Form
) -> Response:
    task = _get(db, task_id)
    performer_ids = [int(v) for v in form.get_all("performer") if v.isdigit()]
    note = form.get_str("note")
    raw_points = form.get_str("points")
    points = int(raw_points) if raw_points.isdigit() else None
    after = "refresh" if form.get_str("after") == "refresh" else "event"
    try:
        completed_on = date.fromisoformat(form.get_str("completed_on"))
    except ValueError:
        completed_on = today()
    try:
        completion.complete(
            db,
            user,
            task,
            performer_ids=performer_ids,
            completed_on=completed_on,
            note=note,
            points=points,
        )
    except completion.CompletionError as exc:
        db.rollback()
        return _sheet(
            request,
            db,
            user,
            task,
            selected=performer_ids,
            completed_on=completed_on,
            note=note,
            after=after,
            error=str(exc),
            points=points,
        )
    return _changed(after)


# ---- Inplannen, verzetten, annuleren (bottom sheet) ----


def _after(value: str) -> str:
    return "refresh" if value == "refresh" else "event"


def _changed(after: str) -> HTMLResponse:
    headers = (
        {"HX-Refresh": "true"}
        if after == "refresh"
        else {"HX-Trigger": "occurrences-changed"}
    )
    # Lege inhoud sluit de sheet.
    return HTMLResponse("", headers=headers)


def _plan_sheet(
    request: Request,
    db: Session,
    user: User,
    task: Task,
    *,
    values: dict,
    after: str,
    error: str | None = None,
) -> HTMLResponse:
    pending = tasks.pending_occurrence(db, task)
    context = _context(
        db,
        user,
        task=task,
        users=_active_users(db),
        values=values,
        after=after,
        error=error,
        planned=pending if pending and pending.planned_date else None,
        min_date=today().isoformat(),
        max_date=(today() + timedelta(days=planning.MAX_DAYS_AHEAD)).isoformat(),
    )
    return templates.TemplateResponse(request, "partials/plan_sheet.html", context)


@router.get("/{task_id}/inplannen")
def plan_sheet(
    request: Request,
    task_id: int,
    user: CurrentUser,
    db: DB,
    na: str = "event",
    datum: str = "",
) -> HTMLResponse:
    task = _get(db, task_id)
    pending = tasks.pending_occurrence(db, task)
    if pending is not None and pending.planned_date is not None:
        values = {
            "planned_date": pending.planned_date.isoformat(),
            "planned_time": pending.planned_time.strftime("%H:%M")
            if pending.planned_time
            else "",
            "owners": [o.user_id for o in pending.owners],
            "points": pending.points,
        }
    else:
        try:
            day = date.fromisoformat(datum)
        except ValueError:
            day = today() + timedelta(days=1)
        values = {
            "planned_date": day.isoformat(),
            "planned_time": "",
            "owners": [task.owner_id] if task.owner_id else [],
            "points": task.default_points,
        }
    return _plan_sheet(request, db, user, task, values=values, after=_after(na))


def _parse_plan(form: FormData) -> planning.PlanInput:
    try:
        planned_date = date.fromisoformat(form.get_str("planned_date"))
    except ValueError as exc:
        raise planning.PlanningError("Kies een datum.") from exc
    raw_time = form.get_str("planned_time")
    try:
        planned_time = time.fromisoformat(raw_time) if raw_time else None
    except ValueError as exc:
        raise planning.PlanningError("Vul een geldige tijd in.") from exc
    owners = tuple(int(v) for v in form.get_all("owner") if v.isdigit())
    raw_points = form.get_str("points")
    points = int(raw_points) if raw_points.isdigit() else None
    return planning.PlanInput(planned_date, planned_time, owners, points)


@router.post("/{task_id}/inplannen")
def plan(
    request: Request, task_id: int, user: CurrentUser, db: DB, form: Form
) -> Response:
    task = _get(db, task_id)
    after = _after(form.get_str("after"))
    competition = settings_store.competition_enabled(db)
    try:
        data = _parse_plan(form)
        pending = tasks.pending_occurrence(db, task)
        if not competition and pending is not None:
            # Zonder competitie is er geen puntenveld: punten blijven zoals ze waren.
            data = planning.PlanInput(
                data.planned_date, data.planned_time, data.owner_ids, pending.points
            )
        if pending is not None and pending.status == OccurrenceStatus.PLANNED:
            planning.reschedule(db, user, pending, data)
        else:
            planning.plan(db, user, task, data, use_task_points=not competition)
    except planning.PlanningError as exc:
        db.rollback()
        values = {
            "planned_date": form.get_str("planned_date"),
            "planned_time": form.get_str("planned_time"),
            "owners": [int(v) for v in form.get_all("owner") if v.isdigit()],
            "points": form.get_str("points"),
        }
        return _plan_sheet(
            request, db, user, task, values=values, after=after, error=str(exc)
        )
    return _changed(after)


@router.post("/{task_id}/planning-annuleren")
def cancel_plan(
    request: Request, task_id: int, user: CurrentUser, db: DB, form: Form
) -> Response:
    task = _get(db, task_id)
    after = _after(form.get_str("after"))
    pending = tasks.pending_occurrence(db, task)
    if pending is None:
        raise HTTPException(status_code=404)
    try:
        planning.cancel(db, user, pending)
    except planning.PlanningError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _changed(after)


@router.post("/{task_id}/logboek/{occurrence_id}/punten")
def correct_points(
    task_id: int, occurrence_id: int, user: CurrentUser, db: DB, form: Form
) -> Response:
    occurrence = db.get(Occurrence, occurrence_id)
    if occurrence is None or occurrence.task_id != task_id:
        raise HTTPException(status_code=404)
    if not settings_store.competition_enabled(db):
        raise HTTPException(status_code=409, detail="De competitie staat uit.")
    raw_points = form.get_str("points")
    points = int(raw_points) if raw_points.isdigit() else None
    try:
        app_points.correct(db, user, occurrence, points, form.get_str("reason"))
    except app_points.PointsError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204, headers={"HX-Refresh": "true"})
