"""Scherm "Back-up" (alleen beheerders): overzicht en verse kopie downloaden."""

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import audit, backup
from app.auth import AdminUser, require_admin
from app.db import get_db
from app.settings import get_settings
from app.templating import templates

router = APIRouter(
    prefix="/beheer/back-up",
    include_in_schema=False,
    dependencies=[Depends(require_admin)],
)

DB = Annotated[Session, Depends(get_db)]


@router.get("", response_class=HTMLResponse)
def page(request: Request, admin: AdminUser) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "pages/backup.html",
        {
            "user": admin,
            "page_title": "Back-up",
            "active_nav": "more",
            "enabled": backup.enabled(settings),
            "backups": backup.list_backups(settings),
            "keep": settings.backup_keep,
            "human_size": backup.human_size,
        },
    )


@router.get("/download")
def download(admin: AdminUser, db: DB) -> FileResponse:
    if not backup.enabled():
        raise HTTPException(status_code=404)
    folder = Path(tempfile.mkdtemp(prefix="huishoud-backup-"))
    moment = backup.local_now()
    name = f"huishoud-{moment:%Y-%m-%d-%H%M}.db"
    path = backup.copy_to(folder / name)
    audit.record(db, "backup.download", actor=admin, new={"file": name})
    db.commit()

    def cleanup() -> None:
        path.unlink(missing_ok=True)
        folder.rmdir()

    return FileResponse(
        path,
        media_type="application/vnd.sqlite3",
        filename=name,
        background=BackgroundTask(cleanup),
        headers={"Cache-Control": "no-store"},
    )
