from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette import status

from memlord.dao.api_key import ApiKeyDao
from memlord.db import APISessionDep
from memlord.schemas.api_key import ApiKeyCreate
from memlord.ui.utils import APIUserDep, templates

router = APIRouter(prefix="/settings", tags=["UI"])


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, user: APIUserDep) -> HTMLResponse:
    return templates.TemplateResponse(request, "settings.html", {"user": user})


@router.get("/api-keys", response_class=JSONResponse)
async def list_keys(user: APIUserDep, s: APISessionDep) -> JSONResponse:
    keys = await ApiKeyDao(s).list_by_user(user.id)
    return JSONResponse([k.model_dump(mode="json") for k in keys])


@router.post("/api-keys", response_class=JSONResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    request: Request, user: APIUserDep, s: APISessionDep
) -> JSONResponse:
    form = await request.form()
    data = ApiKeyCreate(name=str(form.get("name", "")).strip())
    if not data.name:
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        raw_key, key_info = await ApiKeyDao(s).create(user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return JSONResponse(
        {
            "raw_key": raw_key,
            **key_info.model_dump(mode="json"),
        }
    )


@router.delete("/api-keys/{key_id}", response_class=JSONResponse, status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: int, user: APIUserDep, s: APISessionDep
) -> Response:
    deleted = await ApiKeyDao(s).delete(user.id, key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API key not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
