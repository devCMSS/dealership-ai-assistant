"""Password hashing, CSRF tokens, rate limiting, safe image uploads and security headers."""

from __future__ import annotations

import hashlib
import hmac
import io
import secrets
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# ── Passwords (scrypt, stdlib only) ───────────────────────────────────────────

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt" or not password:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


# ── CSRF (synchronizer token kept in the signed session) ─────────────────────

def csrf_token(session: dict) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def csrf_valid(session: dict, submitted: str | None) -> bool:
    expected = session.get("csrf")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


# ── Rate limiting (in-memory sliding window, per key) ────────────────────────

class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# ── Image uploads: verified by content, re-encoded (strips EXIF/GPS), random name ──

class UploadError(ValueError):
    pass


_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_vehicle_photo(raw: bytes, uploads_dir: Path, max_bytes: int) -> str:
    if not raw:
        raise UploadError("The file is empty.")
    if len(raw) > max_bytes:
        raise UploadError(f"Photos must be under {max_bytes // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in _ALLOWED_FORMATS:
                raise UploadError("Only JPEG, PNG or WebP photos are accepted.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            img.thumbnail((1600, 1600))
            uploads_dir.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}.webp"
            # Re-encoding writes pixels only: EXIF (including GPS) is not carried over.
            img.save(uploads_dir / name, "WEBP", quality=82, method=4)
            return name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UploadError("That file is not a valid image.") from exc


def remove_photo(uploads_dir: Path, name: str) -> None:
    if not name or "/" in name or "\\" in name or ".." in name:
        return
    path = uploads_dir / name
    if path.is_file():
        path.unlink()


# ── Redirect safety ──────────────────────────────────────────────────────────

def safe_next(target: str | None, default: str = "/admin") -> str:
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


if __name__ == "__main__":  # python -m app.security hash
    if len(sys.argv) == 2 and sys.argv[1] == "hash":
        import getpass

        print(hash_password(getpass.getpass("Admin password: ")))
    else:
        print("usage: python -m app.security hash")
