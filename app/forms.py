"""Formulierdata uit HTMX-verzoeken (application/x-www-form-urlencoded).

Bewust zonder extra afhankelijkheid (python-multipart): HTMX stuurt
standaard urlencoded, en bestandsuploads zijn (nog) niet nodig.
"""

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request

MAX_FORM_BYTES = 64 * 1024


class FormData(dict[str, list[str]]):
    def get_str(self, name: str, default: str = "") -> str:
        values = self.get(name)
        return values[0].strip() if values else default

    def get_all(self, name: str) -> list[str]:
        return [v.strip() for v in self.get(name, [])]


async def read_form(request: Request) -> FormData:
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in ("", "application/x-www-form-urlencoded"):
        raise HTTPException(status_code=415, detail="Alleen formulierdata.")
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="Formulier te groot.")
    try:
        parsed = parse_qs(body.decode(), keep_blank_values=True, max_num_fields=200)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Ongeldig formulier.") from exc
    return FormData(parsed)


Form = Annotated[FormData, Depends(read_form)]
