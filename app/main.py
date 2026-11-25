"""FastAPI application: public site, chat API and admin back office."""

from __future__ import annotations

import hmac
import logging
import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .assistant.providers import Provider, build_provider
from .assistant.service import ChatService
from .body_type import BODY_TYPES, classify
from .config import DEMO_ADMIN_PASSWORD, Settings, get_settings
from .db import Database
from .models import ChatRequest, Vehicle, VehicleFilters, VehicleIn
from .repository import ChatRepository, LeadRepository, VehicleRepository
from .security import (SECURITY_HEADERS, RateLimiter, UploadError, csrf_token, csrf_valid,
                       remove_photo, safe_next, save_vehicle_photo, verify_password)
from .seed import seed_if_empty

log = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
_UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}\.webp$")

PAINT = {  # vehicle paint colors for the SVG illustrations (data, not UI theme)
    "white": "#e9edf2", "pearl": "#e9edf2", "silver": "#b9c0c9", "platinum": "#d5d9de",
    "gray": "#6b7380", "grey": "#6b7380", "steel": "#7c8794", "carbon": "#4a5260",
    "black": "#22262c", "blue": "#2f5fa7", "aegean": "#2f6f9f", "blueprint": "#3a5a78",
    "red": "#b3262e", "green": "#56633f", "wind": "#d8dde3",
}


def paint_for(color: str) -> str:
    lowered = color.lower()
    for key, value in PAINT.items():
        if key in lowered:
            return value
    return "#8a93a0"


def create_app(settings: Settings | None = None, provider: Provider | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.database_path)
    db.init()
    vehicles = VehicleRepository(db)
    chats = ChatRepository(db)
    leads = LeadRepository(db)
    if settings.demo_mode:
        seeded = seed_if_empty(vehicles)
        if seeded:
            log.info("Seeded %d demo vehicles.", seeded)

    provider = provider or build_provider(settings.assistant_provider, settings.assistant_model)
    chat_service = ChatService(provider, vehicles, chats, leads, settings.dealership_name,
                               settings.history_limit)
    chat_limiter = RateLimiter(limit=20, window_seconds=60)
    login_limiter = RateLimiter(limit=5, window_seconds=300)

    app = FastAPI(title=f"{settings.dealership_name} API", docs_url="/api/docs", redoc_url=None)
    app.state.settings = settings
    app.state.chat_limiter = chat_limiter
    app.state.login_limiter = login_limiter
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="crestline_session",
                       max_age=8 * 3600, same_site="lax", https_only=settings.https_only)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    templates = Jinja2Templates(directory=APP_DIR / "templates")
    env = templates.env
    env.filters["money"] = lambda v: f"${int(v):,}"
    env.filters["miles"] = lambda v: f"{int(v):,} mi"
    env.globals.update(dealership=settings.dealership_name, demo_mode=settings.demo_mode,
                       body_types=BODY_TYPES, paint_for=paint_for, assistant=provider.name)

    def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
        ctx.setdefault("csrf", csrf_token(request.session))
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def is_admin(request: Request) -> bool:
        return request.session.get("admin") is True

    def require_admin(request: Request) -> None:
        if not is_admin(request):
            target = urlencode({"next": request.url.path})
            raise HTTPException(status_code=303, headers={"Location": f"/admin/login?{target}"})

    async def checked_form(request: Request):
        form = await request.form()
        if not csrf_valid(request.session, form.get("csrf")):
            raise HTTPException(status_code=400, detail="Your session expired. Reload the page and try again.")
        return form

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 303 and exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", status_code=exc.status_code, status=exc.status_code,
                      message=exc.detail if exc.status_code != 404 else "We couldn't find that page.")

    # ── Public site ──────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        featured = [v for v in vehicles.search(VehicleFilters(sort="featured"), limit=6)]
        counts = {b: len(vehicles.search(VehicleFilters(body_type=b))) for b in BODY_TYPES}
        return render(request, "home.html", featured=featured, counts=counts)

    @app.get("/inventory", response_class=HTMLResponse)
    def inventory(request: Request, q: str = "", body_type: str = "", make: str = "",
                  max_price: str = "", sort: str = "featured"):
        try:
            filters = VehicleFilters(q=q[:60], body_type=body_type or None, make=make[:40],
                                     max_price=int(max_price) if max_price.isdigit() else None,
                                     sort=sort if sort else "featured")
        except ValidationError:
            filters = VehicleFilters()
        results = vehicles.search(filters)
        return render(request, "inventory.html", results=results, filters=filters, makes=vehicles.makes())

    @app.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
    def vehicle_detail(request: Request, vehicle_id: int):
        vehicle = vehicles.get(vehicle_id)
        if vehicle is None:
            raise HTTPException(status_code=404)
        similar = [v for v in vehicles.search(VehicleFilters(body_type=vehicle.body_type), limit=4)
                   if v.id != vehicle.id][:3]
        return render(request, "vehicle.html", vehicle=vehicle, similar=similar)

    @app.get("/uploads/{name}")
    def upload(name: str):
        if not _UPLOAD_NAME.match(name):
            raise HTTPException(status_code=404)
        path = settings.uploads_dir / name
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return "User-agent: *\nDisallow: /admin\nDisallow: /api/\n"

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "assistant": provider.name}

    # ── JSON API ─────────────────────────────────────────────────────────────

    def vehicle_json(v: Vehicle) -> dict:
        return {"id": v.id, "title": v.title, "price": v.price, "mileage": v.mileage,
                "condition": v.condition, "body_type": v.body_type, "url": f"/vehicles/{v.id}"}

    @app.get("/api/vehicles")
    def api_vehicles(q: str = "", body_type: str | None = None, make: str = "",
                     max_price: int | None = None, sort: str = "featured"):
        try:
            filters = VehicleFilters(q=q, body_type=body_type, make=make, max_price=max_price, sort=sort)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False))
        return [vehicle_json(v) for v in vehicles.search(filters)]

    @app.post("/api/chat")
    def api_chat(request: Request, body: ChatRequest):
        if not (chat_limiter.allow(f"ip:{client_ip(request)}") and chat_limiter.allow(f"s:{body.session_id}")):
            raise HTTPException(status_code=429, detail="You're sending messages too fast. Wait a minute and try again.")
        result = chat_service.handle(body)
        return {"reply": result.reply, "vehicles": [vehicle_json(v) for v in result.vehicles],
                "lead_saved": result.lead_saved, "assistant": result.provider}

    # ── Admin ────────────────────────────────────────────────────────────────

    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login_page(request: Request, next: str = "/admin"):
        if is_admin(request):
            return RedirectResponse(safe_next(next), status_code=303)
        return render(request, "admin/login.html", next=safe_next(next), error="",
                      demo_password=DEMO_ADMIN_PASSWORD if settings.demo_mode and not settings.admin_password_hash else "")

    @app.post("/admin/login", response_class=HTMLResponse)
    async def admin_login(request: Request):
        form = await checked_form(request)
        target = safe_next(form.get("next"))
        if not login_limiter.allow(client_ip(request)):
            return render(request, "admin/login.html", status_code=429, next=target,
                          error="Too many attempts. Wait a few minutes and try again.", demo_password="")
        username, password = str(form.get("username", "")), str(form.get("password", ""))
        if settings.admin_password_hash:
            ok = verify_password(password, settings.admin_password_hash)
        else:  # demo mode only (config refuses to start otherwise)
            ok = hmac_equal(password, DEMO_ADMIN_PASSWORD)
        ok = ok and hmac_equal(username, settings.admin_user)
        if not ok:
            return render(request, "admin/login.html", status_code=401, next=target,
                          error="Wrong username or password.",
                          demo_password=DEMO_ADMIN_PASSWORD if settings.demo_mode and not settings.admin_password_hash else "")
        request.session.clear()  # new session on login (prevents fixation)
        request.session["admin"] = True
        return RedirectResponse(target, status_code=303)

    @app.post("/admin/logout")
    async def admin_logout(request: Request):
        await checked_form(request)
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request, q: str = ""):
        require_admin(request)
        rows = vehicles.search(VehicleFilters(q=q[:60], sort="newest"), include_inactive=True, limit=500)
        return render(request, "admin/vehicles.html", rows=rows, q=q, new_leads=leads.count_new())

    def vehicle_form_values(form) -> dict:
        fields = ("make", "model", "trim", "year", "body_type", "condition", "price", "mileage",
                  "transmission", "fuel", "color", "description")
        values = {f: str(form.get(f, "")).strip() for f in fields}
        values["featured"] = form.get("featured") == "on"
        for numeric in ("price", "mileage"):
            values[numeric] = values[numeric].replace(",", "").replace("$", "")
        if not values["body_type"]:
            values["body_type"] = classify(values["make"], values["model"], values["trim"]) or ""
        return values

    def field_errors(exc: ValidationError) -> dict[str, str]:
        errors: dict[str, str] = {}
        for err in exc.errors(include_url=False):
            name = str(err["loc"][0]) if err["loc"] else "form"
            errors.setdefault(name, err["msg"].replace("Input should be", "Must be"))
        return errors

    async def save_vehicle(request: Request, vehicle_id: int | None):
        form = await checked_form(request)
        values = vehicle_form_values(form)
        existing = vehicles.get(vehicle_id, include_inactive=True) if vehicle_id else None
        if vehicle_id and existing is None:
            raise HTTPException(status_code=404)
        try:
            data = VehicleIn.model_validate(values)
        except ValidationError as exc:
            return render(request, "admin/vehicle_form.html", status_code=422, vehicle=existing,
                          values=values, errors=field_errors(exc))
        photo_name = None
        upload_file = form.get("photo")
        if upload_file is not None and getattr(upload_file, "filename", ""):
            raw = await upload_file.read(settings.max_upload_bytes + 1)
            try:
                photo_name = save_vehicle_photo(raw, settings.uploads_dir, settings.max_upload_bytes)
            except UploadError as exc:
                return render(request, "admin/vehicle_form.html", status_code=422, vehicle=existing,
                              values=values, errors={"photo": str(exc)})
        if existing:
            vehicles.update(existing.id, data, photo=photo_name)
            if photo_name and existing.photo:
                remove_photo(settings.uploads_dir, existing.photo)
            request.session["flash"] = f"Saved {data.year} {data.make} {data.model}."
        else:
            vehicles.create(data, photo=photo_name or "")
            request.session["flash"] = f"Added {data.year} {data.make} {data.model} to the inventory."
        return RedirectResponse("/admin", status_code=303)

    @app.get("/admin/vehicles/new", response_class=HTMLResponse)
    def admin_new(request: Request):
        require_admin(request)
        return render(request, "admin/vehicle_form.html", vehicle=None, values={}, errors={})

    @app.post("/admin/vehicles/new")
    async def admin_create(request: Request):
        require_admin(request)
        return await save_vehicle(request, None)

    @app.get("/admin/vehicles/{vehicle_id}/edit", response_class=HTMLResponse)
    def admin_edit(request: Request, vehicle_id: int):
        require_admin(request)
        vehicle = vehicles.get(vehicle_id, include_inactive=True)
        if vehicle is None:
            raise HTTPException(status_code=404)
        values = vehicle.model_dump()
        return render(request, "admin/vehicle_form.html", vehicle=vehicle, values=values, errors={})

    @app.post("/admin/vehicles/{vehicle_id}/edit")
    async def admin_update(request: Request, vehicle_id: int):
        require_admin(request)
        return await save_vehicle(request, vehicle_id)

    @app.post("/admin/vehicles/{vehicle_id}/toggle")
    async def admin_toggle(request: Request, vehicle_id: int):
        require_admin(request)
        await checked_form(request)
        vehicle = vehicles.get(vehicle_id, include_inactive=True)
        if vehicle is None:
            raise HTTPException(status_code=404)
        vehicles.set_active(vehicle_id, not vehicle.active)
        request.session["flash"] = f"{vehicle.title} is now {'hidden' if vehicle.active else 'listed'}."
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/vehicles/{vehicle_id}/delete")
    async def admin_delete(request: Request, vehicle_id: int):
        require_admin(request)
        await checked_form(request)
        photo = vehicles.delete(vehicle_id)
        if photo is None:
            raise HTTPException(status_code=404)
        remove_photo(settings.uploads_dir, photo)
        request.session["flash"] = "Vehicle deleted."
        return RedirectResponse("/admin", status_code=303)

    @app.get("/admin/leads", response_class=HTMLResponse)
    def admin_leads(request: Request):
        require_admin(request)
        return render(request, "admin/leads.html", rows=leads.list(), new_leads=leads.count_new())

    @app.post("/admin/leads/{lead_id}/status")
    async def admin_lead_status(request: Request, lead_id: int):
        require_admin(request)
        form = await checked_form(request)
        if not leads.set_status(lead_id, str(form.get("status", ""))):
            raise HTTPException(status_code=404)
        return RedirectResponse("/admin/leads", status_code=303)

    env.globals["pop_flash"] = lambda request: request.session.pop("flash", None)
    return app


def hmac_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
