import re

import pytest
from fastapi.testclient import TestClient

from app.assistant.providers import DemoProvider
from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(demo_mode=True, secret_key="test-secret", database_path=tmp_path / "test.db",
                    uploads_dir=tmp_path / "uploads", admin_password_hash="", assistant_provider="demo")


@pytest.fixture
def make_client(settings):
    def _make(provider=None):
        app = create_app(settings, provider=provider or DemoProvider())
        return TestClient(app)
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "page has no CSRF token"
    return match.group(1)


@pytest.fixture
def admin(client):
    page = client.get("/admin/login")
    r = client.post("/admin/login", data={"csrf": csrf_from(page.text), "username": "admin",
                                          "password": "crestline-demo", "next": "/admin"},
                    follow_redirects=False)
    assert r.status_code == 303
    return client
