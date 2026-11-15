"""HTTP API (FastAPI). Thin: parses requests, calls FieldService, returns JSON.

Run:  uvicorn fieldshift.api:app --port 8000   (from backend/)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .app import DATA_DIR, FRONTEND_DIR, get_cache, get_service
from .core.geometry import FieldError, FieldGeometry, field_from_spec

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fieldshift.api")

app = FastAPI(title="Field Shift v0", version="0.0.1")


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """The front end has no build step or hashed file names; make browsers revalidate it."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _error(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


def _store_field(f: FieldGeometry) -> None:
    get_cache().put("fields", f.key(), f.spec(), ttl=None)


def _load_field(field_id: str) -> FieldGeometry:
    if not field_id.isalnum() or len(field_id) > 64:
        _error(400, "Bad field id.")
    entry = get_cache().get("fields", field_id)
    if not entry:
        _error(404, "Unknown field. Please draw it again.")
    return field_from_spec(entry["value"])


def _corrections(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        _error(400, "Corrections must be JSON.")
    if not isinstance(val, dict):
        _error(400, "Corrections must be an object of year -> crop.")
    return {str(k): str(v) for k, v in val.items() if str(k).isdigit()}


def _section(fn, *args, **kwargs):
    """Run one report section; a data-source failure becomes a readable error, not a crash."""
    try:
        return fn(*args, **kwargs)
    except FieldError as exc:
        _error(422, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("section %s failed", getattr(fn, "__name__", fn))
        return JSONResponse(status_code=502, content={"status": "error", "error": f"{exc}"})


@app.get("/api/config")
def config():
    return _section(get_service().config)


@app.post("/api/field")
def create_field(body: dict = Body(...)):
    try:
        f = get_service().make_field(body.get("field") or body)
    except FieldError as exc:
        _error(422, str(exc))
    _store_field(f)
    return get_service().field_summary(f)


@app.get("/api/field/{field_id}")
def field_info(field_id: str):
    return get_service().field_summary(_load_field(field_id))


@app.get("/api/field/{field_id}/history")
def history(field_id: str, corrections: str | None = None):
    return _section(get_service().history, _load_field(field_id), _corrections(corrections))


@app.get("/api/field/{field_id}/climate")
def climate(field_id: str):
    return _section(get_service().climate, _load_field(field_id))


@app.get("/api/field/{field_id}/vegetation/years")
def vegetation_years(field_id: str):
    _load_field(field_id)
    return _section(lambda: {"years": get_service().vegetation_years()})


@app.get("/api/field/{field_id}/vegetation/year/{year}")
def vegetation_year(field_id: str, year: int):
    svc = get_service()
    if year not in svc.vegetation_years():
        _error(400, "Year out of range.")
    return _section(svc.vegetation_year, _load_field(field_id), year)


@app.get("/api/field/{field_id}/vegetation")
def vegetation(field_id: str):
    return _section(get_service().vegetation, _load_field(field_id))


@app.get("/api/field/{field_id}/strategies")
def strategies(field_id: str, corrections: str | None = None,
               plan_length: int | None = Query(None, ge=2, le=8),
               alternatives: int | None = Query(None, ge=1, le=6)):
    return _section(get_service().strategies, _load_field(field_id), _corrections(corrections),
                    plan_length, alternatives)


@app.get("/api/overlay/years")
def overlay_years():
    ov = get_service().providers.overlay
    if ov is None:
        return {"years": []}
    return _section(lambda: {"years": ov.overlay_years()})


@app.get("/api/overlay/{year}.png")
def overlay_png(year: int):
    ov = get_service().providers.overlay
    if ov is None or year not in ov.overlay_years():
        _error(404, "No overlay for that year.")
    try:
        png, _ = ov.overlay_png(year)
    except Exception as exc:
        log.exception("overlay failed")
        _error(502, f"Crop map could not be loaded: {exc}")
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/overlay/{year}.json")
def overlay_meta(year: int):
    ov = get_service().providers.overlay
    if ov is None or year not in ov.overlay_years():
        _error(404, "No overlay for that year.")
    return _section(lambda: ov.overlay_png(year)[1])


@app.get("/api/demo-fields")
def demo_fields():
    p = DATA_DIR / "demo_fields.geojson"
    if not p.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(p.read_text())


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
