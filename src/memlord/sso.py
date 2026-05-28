import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from memlord.config import settings
from memlord.dao.user import UserDao
from memlord.db import APISessionDep
from memlord.ui.utils import set_session_cookie

logger = logging.getLogger(__name__)

_azure_oauth = OAuth()

router = APIRouter()


def _rp() -> str:
    return settings.root_path.rstrip("/")


def _is_email_allowed(email: str, allowed_domains: list[str] | None) -> bool:
    if not allowed_domains:
        return True
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in [d.lower() for d in allowed_domains]


def create_azure_router() -> APIRouter | None:
    if not (
        settings.azure_sso_enabled
        and settings.azure_client_id
        and settings.azure_tenant_id
    ):
        return None

    redirect_uri = settings.azure_redirect_uri
    if not redirect_uri:
        redirect_uri = f"{settings.base_url}/auth/azure/callback"

    _azure_oauth.register(
        name="azure",
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
            f"/v2.0/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": settings.azure_scope},
        redirect_uri=redirect_uri,
    )
    return router


@router.get("/auth/azure/login")
async def azure_login(request: Request):
    redirect_uri = settings.azure_redirect_uri
    if not redirect_uri:
        redirect_uri = f"{settings.base_url}/auth/azure/callback"
    return await _azure_oauth.azure.authorize_redirect(request, redirect_uri)


@router.get("/auth/azure/callback")
async def azure_callback(request: Request, s: APISessionDep):
    try:
        token = await _azure_oauth.azure.authorize_access_token(request)
    except Exception:
        logger.warning("Azure SSO: token exchange failed", exc_info=True)
        return RedirectResponse(f"{_rp()}/ui/login?error=azure_failed", status_code=303)

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await _azure_oauth.azure.userinfo(token=token)

    email = userinfo.get("email", "").strip().lower()
    if not email:
        logger.warning("Azure SSO: no email in user info")
        return RedirectResponse(f"{_rp()}/ui/login?error=azure_failed", status_code=303)

    sub = userinfo.get("sub", "")
    name = userinfo.get("name", email)

    if not _is_email_allowed(email, settings.azure_allowed_email_domains):
        return RedirectResponse(f"{_rp()}/ui/login?error=azure_denied", status_code=303)

    user = await UserDao(s).get_or_create_by_email_for_sso(
        email=email,
        display_name=name,
        azure_sub=sub,
        auto_register=settings.azure_auto_register,
    )

    if user is None:
        return RedirectResponse(f"{_rp()}/ui/login?error=azure_no_account", status_code=303)

    response = RedirectResponse(f"{_rp()}/", status_code=303)
    set_session_cookie(response, user.id)
    return response
