import io
import json
from types import SimpleNamespace

from PIL import Image

from app.assistant.providers import ClaudeProvider
from app.security import safe_next
from tests.conftest import csrf_from

SESSION = "test-session-0123456789"


def chat(client, message, session=SESSION, vehicle_id=None):
    return client.post("/api/chat", json={"session_id": session, "message": message, "vehicle_id": vehicle_id})


def vehicle_form(csrf, **overrides):
    data = {"csrf": csrf, "make": "Honda", "model": "Accord", "trim": "Sport", "year": "2022",
            "body_type": "", "condition": "used", "price": "$26,500", "mileage": "21,000",
            "transmission": "cvt", "fuel": "gasoline", "color": "Still Night Pearl", "description": ""}
    data.update(overrides)
    return data


# ── Public site ──────────────────────────────────────────────────────────────

def test_public_pages_render(client):
    for path in ("/", "/inventory", "/inventory?body_type=suv&max_price=35000&sort=price_asc", "/vehicles/1"):
        assert client.get(path).status_code == 200, path
    assert client.get("/vehicles/9999").status_code == 404


def test_security_headers(client):
    headers = client.get("/").headers
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_invalid_filters_fall_back_instead_of_500(client):
    assert client.get("/inventory?body_type=spaceship&sort=evil").status_code == 200
    assert client.get("/api/vehicles?body_type=spaceship").status_code == 422


# ── Chat API ─────────────────────────────────────────────────────────────────

def test_chat_returns_reply_and_real_vehicles(client):
    r = chat(client, "I need a pickup truck")
    assert r.status_code == 200
    body = r.json()
    assert body["vehicles"] and all(v["body_type"] == "pickup" for v in body["vehicles"])


def test_chat_drops_vehicle_ids_the_model_invented(make_client):
    payload = {"reply": "Try #5 or #999.", "vehicle_ids": [5, 999],
               "lead": {"customer_name": "", "contact": "", "interest": ""}}
    response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response)))
    client = make_client(ClaudeProvider("claude-opus-5-5", client=fake))
    ids = [v["id"] for v in chat(client, "suggest something").json()["vehicles"]]
    assert ids == [5]


def test_chat_falls_back_when_provider_fails(make_client):
    import anthropic
    import httpx

    def boom(**kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=boom)))
    client = make_client(ClaudeProvider("claude-opus-5-5", client=fake))
    r = chat(client, "any hybrids?")
    assert r.status_code == 200 and r.json()["assistant"] == "demo-fallback"


def test_chat_validates_input(client):
    assert chat(client, "").status_code == 422
    assert chat(client, "x" * 1001).status_code == 422
    assert chat(client, "hi", session="bad id!").status_code == 422


def test_chat_rate_limit(client):
    statuses = [chat(client, "hello").status_code for _ in range(21)]
    assert statuses[:20] == [200] * 20 and statuses[20] == 429


def test_lead_reaches_admin(admin):
    chat(admin, "I'd like a test drive", vehicle_id=5)
    chat(admin, "My name is Ana, email ana@example.com", vehicle_id=5)
    page = admin.get("/admin/leads").text
    assert "Ana" in page and "ana@example.com" in page


# ── Admin ────────────────────────────────────────────────────────────────────

def test_admin_requires_login(client):
    for path in ("/admin", "/admin/leads", "/admin/vehicles/new", "/admin/vehicles/1/edit"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/admin/login")
    assert client.post("/admin/vehicles/1/delete", follow_redirects=False).status_code == 303


def test_login_rejects_wrong_password_and_missing_csrf(client):
    page = client.get("/admin/login")
    r = client.post("/admin/login", data={"csrf": csrf_from(page.text), "username": "admin", "password": "nope"})
    assert r.status_code == 401
    r = client.post("/admin/login", data={"username": "admin", "password": "crestline-demo"})
    assert r.status_code == 400


def test_post_without_csrf_is_rejected(admin):
    assert admin.post("/admin/vehicles/1/delete").status_code == 400
    assert admin.get("/vehicles/1").status_code == 200


def test_create_vehicle_detects_body_type(admin):
    csrf = csrf_from(admin.get("/admin/vehicles/new").text)
    r = admin.post("/admin/vehicles/new", data=vehicle_form(csrf), follow_redirects=False)
    assert r.status_code == 303
    found = admin.get("/api/vehicles?q=Accord").json()
    assert found and found[0]["body_type"] == "sedan" and found[0]["price"] == 26500


def test_create_vehicle_shows_field_errors_and_keeps_values(admin):
    csrf = csrf_from(admin.get("/admin/vehicles/new").text)
    r = admin.post("/admin/vehicles/new", data=vehicle_form(csrf, year="1850", model="Zzzz Unknown"))
    assert r.status_code == 422
    assert 'id="e-year"' in r.text and "Zzzz Unknown" in r.text


def test_upload_rejects_non_images_and_strips_exif(admin, settings):
    csrf = csrf_from(admin.get("/admin/vehicles/1/edit").text)
    fake = {"photo": ("car.jpg", b"<?php echo 1; ?>", "image/jpeg")}
    r = admin.post("/admin/vehicles/1/edit", data=vehicle_form(csrf), files=fake)
    assert r.status_code == 422 and "not a valid image" in r.text

    img = Image.new("RGB", (64, 48), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # camera make tag
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    r = admin.post("/admin/vehicles/1/edit", data=vehicle_form(csrf),
                   files={"photo": ("car.jpg", buf.getvalue(), "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 303
    (saved,) = settings.uploads_dir.iterdir()
    assert saved.suffix == ".webp"
    with Image.open(saved) as out:
        assert not out.getexif()
    assert admin.get(f"/uploads/{saved.name}").status_code == 200
    assert admin.get("/uploads/..%2Fsecret.db").status_code == 404


def test_toggle_hides_vehicle_from_public(admin):
    csrf = csrf_from(admin.get("/admin").text)
    admin.post("/admin/vehicles/2/toggle", data={"csrf": csrf})
    assert admin.get("/vehicles/2").status_code == 404


def test_safe_next_blocks_open_redirects():
    assert safe_next("/admin/leads") == "/admin/leads"
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example", None, ""):
        assert safe_next(bad) == "/admin"
