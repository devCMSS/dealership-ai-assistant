"""Data access for vehicles, chat history and leads."""

from __future__ import annotations

import sqlite3

from .db import Database
from .models import LeadUpdate, Vehicle, VehicleFilters, VehicleIn

_SORTS = {
    "featured": "featured DESC, created_at DESC, id DESC",
    "price_asc": "price ASC",
    "price_desc": "price DESC",
    "newest": "year DESC, mileage ASC",
    "mileage": "mileage ASC",
}

_VEHICLE_COLUMNS = ("make", "model", "trim", "year", "body_type", "condition", "price", "mileage",
                    "transmission", "fuel", "color", "description", "featured")


def _row_to_vehicle(row: sqlite3.Row) -> Vehicle:
    data = dict(row)
    data["featured"] = bool(data["featured"])
    data["active"] = bool(data["active"])
    data.pop("created_at", None)
    return Vehicle.model_validate(data)


class VehicleRepository:
    def __init__(self, db: Database):
        self.db = db

    def search(self, filters: VehicleFilters, *, include_inactive: bool = False,
               limit: int = 200) -> list[Vehicle]:
        clauses: list[str] = []
        params: list[object] = []
        if not include_inactive:
            clauses.append("active = 1")
        if filters.body_type:
            clauses.append("body_type = ?")
            params.append(filters.body_type)
        if filters.make:
            clauses.append("make = ? COLLATE NOCASE")
            params.append(filters.make)
        if filters.max_price is not None:
            clauses.append("price <= ?")
            params.append(filters.max_price)
        if filters.q:
            clauses.append("(make || ' ' || model || ' ' || trim || ' ' || color) LIKE ? COLLATE NOCASE")
            params.append(f"%{filters.q}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # ORDER BY comes from a fixed whitelist, never from the request.
        sql = f"SELECT * FROM vehicles {where} ORDER BY {_SORTS[filters.sort]} LIMIT ?"
        params.append(limit)
        with self.db.connect() as conn:
            return [_row_to_vehicle(r) for r in conn.execute(sql, params)]

    def get(self, vehicle_id: int, *, include_inactive: bool = False) -> Vehicle | None:
        sql = "SELECT * FROM vehicles WHERE id = ?" + ("" if include_inactive else " AND active = 1")
        with self.db.connect() as conn:
            row = conn.execute(sql, (vehicle_id,)).fetchone()
        return _row_to_vehicle(row) if row else None

    def makes(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT DISTINCT make FROM vehicles WHERE active = 1 ORDER BY make")
            return [r["make"] for r in rows]

    def create(self, data: VehicleIn, photo: str = "") -> int:
        values = [getattr(data, c) for c in _VEHICLE_COLUMNS] + [photo]
        cols = ", ".join((*_VEHICLE_COLUMNS, "photo"))
        marks = ", ".join("?" for _ in values)
        with self.db.connect() as conn:
            cur = conn.execute(f"INSERT INTO vehicles ({cols}) VALUES ({marks})", values)
            return int(cur.lastrowid)

    def update(self, vehicle_id: int, data: VehicleIn, photo: str | None = None) -> bool:
        cols = list(_VEHICLE_COLUMNS)
        values = [getattr(data, c) for c in cols]
        if photo is not None:
            cols.append("photo")
            values.append(photo)
        assignments = ", ".join(f"{c} = ?" for c in cols)
        with self.db.connect() as conn:
            cur = conn.execute(f"UPDATE vehicles SET {assignments} WHERE id = ?", [*values, vehicle_id])
            return cur.rowcount == 1

    def set_active(self, vehicle_id: int, active: bool) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute("UPDATE vehicles SET active = ? WHERE id = ?", (int(active), vehicle_id))
            return cur.rowcount == 1

    def delete(self, vehicle_id: int) -> str | None:
        """Delete a vehicle; returns its photo filename (if any) so the caller can remove it."""
        with self.db.connect() as conn:
            row = conn.execute("SELECT photo FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            return row["photo"]

    def count(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0])


class ChatRepository:
    def __init__(self, db: Database):
        self.db = db

    def history(self, session_id: str, limit: int) -> list[dict[str, str]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def append(self, session_id: str, role: str, content: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )


class LeadRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, session_id: str, update: LeadUpdate) -> bool:
        """Merge what the assistant learned into the session's lead. Returns True when a lead
        exists for the session after the merge (a lead needs at least a name or a contact)."""
        name, contact, interest = (update.customer_name.strip()[:80], update.contact.strip()[:120],
                                   update.interest.strip()[:200])
        with self.db.connect() as conn:
            existing = conn.execute("SELECT * FROM leads WHERE session_id = ?", (session_id,)).fetchone()
            if existing is None:
                if not (name or contact):
                    return False
                conn.execute(
                    "INSERT INTO leads (session_id, name, contact, interest) VALUES (?, ?, ?, ?)",
                    (session_id, name, contact, interest),
                )
                return True
            if name or contact or interest:
                conn.execute(
                    """UPDATE leads SET
                           name = CASE WHEN ? <> '' THEN ? ELSE name END,
                           contact = CASE WHEN ? <> '' THEN ? ELSE contact END,
                           interest = CASE WHEN ? <> '' THEN ? ELSE interest END,
                           updated_at = datetime('now')
                       WHERE session_id = ?""",
                    (name, name, contact, contact, interest, interest, session_id),
                )
            return True

    def list(self) -> list[dict]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM leads ORDER BY updated_at DESC, id DESC")]

    def set_status(self, lead_id: int, status: str) -> bool:
        if status not in {"new", "contacted"}:
            return False
        with self.db.connect() as conn:
            return conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id)).rowcount == 1

    def count_new(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'").fetchone()[0])
