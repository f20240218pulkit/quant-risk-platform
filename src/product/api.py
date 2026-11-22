"""Same-origin API and React shell for the synthetic product checkpoint."""
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from .service import close_session, confirm_import, open_session, owned_report, query, scoped_connection, store_import
from .valuation import FIXTURES, MAX_UPLOAD_BYTES, SAMPLE_CSV, compare_reviews

API = "/api/workbench/v1"


def create_app(*, engine=None, origin=None, static_dir=None, demo_enabled=None):
    origin = origin or os.environ.get("WORKBENCH_ORIGIN", "http://127.0.0.1:8001")
    origin_parts = urlsplit(origin)
    if (origin_parts.scheme not in {"http", "https"} or not origin_parts.hostname
            or origin_parts.path or origin_parts.query or origin_parts.fragment or origin_parts.username
            or (origin_parts.scheme == "http" and origin_parts.hostname not in {"127.0.0.1", "localhost", "::1"})):
        raise RuntimeError("Configure a bare HTTPS origin or a local loopback HTTP origin.")
    if demo_enabled is None:
        demo_enabled = os.environ.get("WORKBENCH_DEMO_MODE") == "1"
    if not demo_enabled:
        raise RuntimeError("This checkpoint requires explicit synthetic mode. Set WORKBENCH_DEMO_MODE=1.")
    secure = origin_parts.scheme == "https"
    cookie = "__Host-workbench" if secure else "workbench"
    dist = Path(static_dir or os.environ.get("WORKBENCH_WEB_DIST")
                or Path(__file__).resolve().parents[2] / "web" / "dist")

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = engine or database_engine()
        yield
        if engine is None:
            app.state.db.dispose()

    app = FastAPI(title="Portfolio Workbench", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def browser_boundary(request, call_next):
        private = request.url.path.startswith(API)
        if private and request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("origin") != origin:
            response = PlainTextResponse("Request origin is not allowed.", status_code=403)
        elif private and request.url.path == f"{API}/imports" and request.method == "POST":
            size = request.headers.get("content-length", "")
            if not size.isdecimal() or len(size) > 10:
                response = PlainTextResponse("A bounded upload length is required.", status_code=411)
            elif int(size) > MAX_UPLOAD_BYTES + 64 * 1024:
                response = PlainTextResponse("Upload exceeds the size limit.", status_code=413)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        if private:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "form-action 'self'; style-src 'self'; img-src 'self' data:"
        )
        return response

    @contextmanager
    def session(request):
        with scoped_connection(request.app.state.db, request.cookies.get(cookie)) as (
            connection, workspace_id,
        ):
            if workspace_id is None:
                raise HTTPException(401, "Start a synthetic workspace first.")
            yield connection, workspace_id

    @app.get("/healthz")
    def readiness(request: Request):
        try:
            with request.app.state.db.connect() as connection:
                query(connection, "SELECT 1 FROM product_jobs LIMIT 1")
        except SQLAlchemyError:
            raise HTTPException(503, "Database or schema unavailable.") from None
        return {"status": "ok", "mode": "synthetic"}

    @app.get(f"{API}/sample")
    def sample():
        return {"csv": SAMPLE_CSV, "dates": list(FIXTURES), "mode": "synthetic"}

    @app.post(f"{API}/session", status_code=201)
    def create_session(request: Request, response: Response):
        with request.app.state.db.begin() as connection:
            close_session(connection, request.cookies.get(cookie))
            workspace_id, token = open_session(connection)
        response.set_cookie(cookie, token, max_age=8 * 3600, httponly=True, secure=secure, samesite="lax")
        return {"workspace_id": workspace_id, "mode": "synthetic"}

    @app.get(f"{API}/session")
    def session_status(request: Request):
        with session(request) as (_, workspace_id):
            return {"workspace_id": workspace_id, "mode": "synthetic"}

    @app.delete(f"{API}/session", status_code=204)
    def logout(request: Request, response: Response):
        with request.app.state.db.begin() as connection:
            close_session(connection, request.cookies.get(cookie))
        response.delete_cookie(cookie, httponly=True, secure=secure, samesite="lax")

    @app.post(f"{API}/imports", status_code=201)
    def upload(request: Request, snapshot_date: date = Form(), file: UploadFile = File()):
        with session(request) as (connection, workspace_id):
            if snapshot_date.isoformat() not in FIXTURES:
                raise HTTPException(422, "Choose one of the synthetic fixture dates.")
            data = file.file.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Upload exceeds 5 MiB.")
            return store_import(connection, workspace_id, snapshot_date, data)

    @app.post(f"{API}/imports/{{import_id}}/confirm", status_code=202)
    def confirm(request: Request, import_id: str):
        with session(request) as (connection, workspace_id):
            result = confirm_import(connection, workspace_id, import_id)
            if result is None:
                raise HTTPException(404, "Import not found.")
            if "issues" in result:
                raise HTTPException(422, "Resolve the import issues before confirming.")
            return result

    @app.get(f"{API}/jobs/{{job_id}}")
    def job(request: Request, job_id: str):
        with session(request) as (connection, workspace_id):
            row = query(connection, """
                SELECT j.state, r.id AS report_id FROM product_jobs j
                LEFT JOIN product_reports r ON r.workspace_id = j.workspace_id AND r.import_id = j.import_id
                WHERE j.id = :id AND j.workspace_id = :workspace
            """, id=job_id, workspace=workspace_id).mappings().one_or_none()
            if row is None:
                raise HTTPException(404, "Job not found.")
            return dict(row)

    @app.get(f"{API}/reviews")
    def reviews(request: Request):
        with session(request) as (connection, workspace_id):
            rows = query(connection, """
                SELECT id, snapshot_date, published_at, evidence->>'status' AS status
                FROM product_reports WHERE workspace_id = :workspace
                ORDER BY snapshot_date DESC, published_at DESC, id LIMIT 100
            """, workspace=workspace_id).mappings()
            return [dict(row) for row in rows]

    @app.get(f"{API}/reviews/{{report_id}}")
    def review(request: Request, report_id: str):
        with session(request) as (connection, workspace_id):
            result = owned_report(connection, workspace_id, report_id)
            if result is None:
                raise HTTPException(404, "Review not found.")
            return result

    @app.get(f"{API}/reviews/{{report_id}}/export")
    def export_review(request: Request, report_id: str):
        result = review(request, report_id)
        filename = f"portfolio-review-{result['snapshot_date']}.json"
        return JSONResponse(jsonable_encoder(result), headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        })

    @app.get(f"{API}/reviews/{{report_id}}/comparison")
    def comparison(request: Request, report_id: str, base: str):
        with session(request) as (connection, workspace_id):
            prior = owned_report(connection, workspace_id, base)
            current = owned_report(connection, workspace_id, report_id)
            if prior is None or current is None:
                raise HTTPException(404, "Review not found.")
            return compare_reviews(prior, current)

    if (dist / "assets").is_dir() and (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def web():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
