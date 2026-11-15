"""HTTP API (FastAPI). Thin: parses requests, calls FieldService, returns JSON.

Run:  uvicorn fieldshift.api:app --port 8000   (from backend/)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .app import DATA_DIR, FRONTEND_DIR, get_cache, get_service
from .core.geometry import FieldError, FieldGeometry, field_from_spec

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fieldshift.api")

app = FastAPI(title="Policrop", version="0.0.1")


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
    _warm(f)
    return get_service().field_summary(f)


_WARMING: set[str] = set()


def _warm(f: FieldGeometry) -> None:
    """Start the slow, cacheable fetches (weather, soil, crop history) as soon as a field exists."""
    import threading
    key = f.key()
    if key in _WARMING:
        return
    _WARMING.add(key)
    svc = get_service()

    def run(fn):
        try:
            fn(f)
        except Exception as exc:  # the section reports its own error later
            log.info("warm-up %s failed: %s", getattr(fn, "__name__", fn), exc)

    for fn in (svc.climate, svc.soil, svc.history):
        threading.Thread(target=run, args=(fn,), daemon=True).start()


@app.post("/api/pick")
def pick(body: dict = Body(...)):
    """Trace the field at a tapped point; the farmer confirms it before it becomes their field."""
    try:
        return get_service().pick_field(body.get("lon"), body.get("lat"))
    except FieldError as exc:
        _error(422, str(exc))


@app.get("/api/field/{field_id}")
def field_info(field_id: str):
    return get_service().field_summary(_load_field(field_id))


@app.get("/api/field/{field_id}/history")
def history(field_id: str, corrections: str | None = None):
    return _section(get_service().history, _load_field(field_id), _corrections(corrections))


@app.get("/api/field/{field_id}/soil")
def soil(field_id: str):
    return _section(get_service().soil, _load_field(field_id))


@app.get("/api/field/{field_id}/station")
def station(field_id: str):
    return _section(get_service().station, _load_field(field_id))


@app.get("/api/field/{field_id}/greenness_history")
def greenness_history(field_id: str):
    return _section(get_service().greenness_history, _load_field(field_id))


@app.get("/api/field/{field_id}/slope")
def slope(field_id: str):
    return _section(get_service().slope, _load_field(field_id))


@app.get("/api/field/{field_id}/slope.png")
def slope_png(field_id: str):
    try:
        png, meta = get_service().slope_png(_load_field(field_id))
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("slope map failed")
        _error(502, f"Slope map could not be made: {exc}")
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400",
                                                          "X-Bounds": json.dumps(meta["bounds"])})


@app.get("/api/field/{field_id}/slope_map.json")
def slope_meta(field_id: str):
    return _section(lambda: get_service().slope_png(_load_field(field_id))[1])


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
def strategies(field_id: str, inputs: str | None = None, corrections: str | None = None,
               plan_length: int | None = Query(None, ge=2, le=8)):
    """Options for a field. `inputs` is one JSON object of farmer inputs (brief section 7):
    corrections, priorities, dry_mode, exclude, keep, plan_length, ph, tillage, yields, rain_pct, temp_f."""
    raw: dict = {}
    if inputs:
        try:
            raw = json.loads(inputs)
        except json.JSONDecodeError:
            _error(400, "inputs must be JSON.")
        if not isinstance(raw, dict):
            _error(400, "inputs must be a JSON object.")
    if corrections and "corrections" not in raw:
        raw["corrections"] = _corrections(corrections)
    if plan_length and "plan_length" not in raw:
        raw["plan_length"] = plan_length
    return _section(get_service().strategies, _load_field(field_id), raw)


# ---- the farmer's records (brief 3, part B) ------------------------------------------------
@app.get("/api/field/{field_id}/records_template.xlsx")
def records_template(field_id: str, corrections: str | None = None):
    data = get_service().records_template(_load_field(field_id), _corrections(corrections))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="harvest-records.xlsx"'})


@app.post("/api/field/{field_id}/records/read")
async def records_read(field_id: str, request: Request, name: str = Query("", max_length=200),
                       columns: str | None = None):
    """Read an uploaded .xlsx or .csv for the preview. Values only; the file is discarded after reading."""
    from .core.records import MAX_FILE_BYTES, FileRefused
    f = _load_field(field_id)
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_FILE_BYTES:
            _error(413, f"The file is larger than {MAX_FILE_BYTES // 1000} KB; a harvest table is much smaller.")
    cols = None
    if columns:
        try:
            cols = {k: (int(v) if v not in (None, "") else None) for k, v in json.loads(columns).items()
                    if k in ("year", "crop", "harvest", "unit", "basis")}
        except (ValueError, TypeError, AttributeError):
            _error(400, "columns must be a JSON object of column numbers.")
    try:
        return get_service().read_records(f, name, data, cols)
    except FileRefused as exc:
        _error(422, f"This file was not read: {exc}")


@app.post("/api/field/{field_id}/records/check")
def records_check(field_id: str, body: dict = Body(...)):
    return get_service().check_records(_load_field(field_id), body.get("rows") or [])


@app.get("/api/field/{field_id}/example_records")
def example_records(field_id: str, corrections: str | None = None):
    return _section(get_service().example_records, _load_field(field_id), _corrections(corrections))


# ---- this year so far (brief 3, part D) ------------------------------------------------------
@app.get("/api/field/{field_id}/season")
def season(field_id: str, inputs: str | None = None, date: str | None = None):
    import datetime as _dt
    raw = {}
    if inputs:
        try:
            raw = json.loads(inputs)
        except json.JSONDecodeError:
            _error(400, "inputs must be JSON.")
    as_of = None
    if date:
        try:
            as_of = _dt.date.fromisoformat(date)
        except ValueError:
            _error(400, "date must be YYYY-MM-DD.")
        if as_of >= get_service().today:
            _error(400, "A replay date must be in the past.")
    return _section(get_service().season, _load_field(field_id), raw if isinstance(raw, dict) else {}, as_of)


@app.get("/api/field/{field_id}/season_replay")
def season_replay(field_id: str):
    return _section(get_service().season_replay, _load_field(field_id))


@app.get("/api/field/{field_id}/enso")
def enso(field_id: str):
    return _section(get_service().enso, _load_field(field_id))


@app.get("/api/validation")
def validation():
    p = DATA_DIR / "validation.json"
    if not p.exists():
        _error(404, "The validation has not been run yet (backend/tools/validate.py).")
    return json.loads(p.read_text())


@app.get("/api/region/context")
def region_context():
    return _section(get_service().region_context)


@app.get("/api/region/outlook")
def region_outlook():
    try:
        return get_service().outlook()
    except FileNotFoundError as exc:
        _error(404, str(exc))


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
