"""Managed OIDC login for the configured private environment."""
import os
import time
from urllib.parse import urlsplit

from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from .service import close_session, open_session


def install_oidc(app, origin, cookie, issue_cookie):
    issuer = os.environ.get("WORKBENCH_OIDC_ISSUER", "")
    client_id = os.environ.get("WORKBENCH_OIDC_CLIENT_ID")
    secret = os.environ.get("WORKBENCH_OIDC_CLIENT_SECRET")
    session_secret = os.environ.get("WORKBENCH_OIDC_STATE_SECRET", "")
    subjects = set(os.environ.get("WORKBENCH_OIDC_ALLOWED_SUBJECTS", "").split())
    parts = urlsplit(issuer)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.query or parts.fragment
            or not client_id or not secret or len(session_secret) < 32 or not subjects
            or not origin.startswith("https://")):
        raise RuntimeError("Configure HTTPS, managed OIDC credentials, a strong state secret and invited subject IDs.")
    oauth = OAuth()
    client = oauth.register(
        "identity", client_id=client_id, client_secret=secret,
        server_metadata_url=issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid", "code_challenge_method": "S256", "timeout": 15},
    )
    app.add_middleware(SessionMiddleware, secret_key=session_secret, session_cookie="__Host-oidc-state",
                       max_age=300, same_site="lax", https_only=True)
    redirect_uri = origin + "/auth/callback"

    @app.get("/auth/login", include_in_schema=False)
    async def login(request: Request):
        request.session.clear()
        return await client.authorize_redirect(request, redirect_uri, prompt="login", max_age=0)

    @app.get("/auth/callback", include_in_schema=False)
    async def callback(request: Request):
        try:
            token = await client.authorize_access_token(request)
        except (OAuthError, ValueError) as error:
            raise HTTPException(401, "Sign-in could not be verified. Start again.") from error
        finally:
            request.session.clear()
        user = token.get("userinfo")
        if not token.get("id_token") or not user or user.get("iss") != issuer or user.get("sub") not in subjects:
            raise HTTPException(403, "This identity cannot access the private Workbench.")
        authenticated_at = user.get("auth_time")
        now = int(time.time())
        if type(authenticated_at) is not int or not now - 300 <= authenticated_at <= now + 60:
            raise HTTPException(401, "The provider did not confirm a recent interactive sign-in.")
        # The transient provider token is not persisted or sent to the browser.
        def session_token():
            with request.app.state.db.begin() as connection:
                close_session(connection, request.cookies.get(cookie))
                return open_session(connection, (issuer, user["sub"]))[1]

        response = RedirectResponse("/", status_code=303)
        issue_cookie(response, await run_in_threadpool(session_token))
        response.headers["Cache-Control"] = "no-store"
        return response
