"""Validated data shapes. Client-side validation is UX; these are the rules that count."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .body_type import BODY_TYPES

BodyType = Literal["sedan", "suv", "pickup", "hatchback", "coupe", "minivan"]
Condition = Literal["new", "used", "certified"]
Transmission = Literal["automatic", "manual", "cvt"]
Fuel = Literal["gasoline", "hybrid", "electric", "diesel"]

assert set(BODY_TYPES) == set(BodyType.__args__)  # keep the two lists in sync


class VehicleIn(BaseModel):
    make: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=40)
    trim: str = Field(default="", max_length=40)
    year: int = Field(ge=1990, le=date.today().year + 1)
    body_type: BodyType
    condition: Condition
    price: int = Field(ge=500, le=1_000_000)
    mileage: int = Field(ge=0, le=500_000)
    transmission: Transmission
    fuel: Fuel
    color: str = Field(min_length=1, max_length=30)
    description: str = Field(default="", max_length=2000)
    featured: bool = False

    @field_validator("make", "model", "trim", "color", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class Vehicle(VehicleIn):
    id: int
    photo: str = ""
    active: bool = True

    @property
    def title(self) -> str:
        return f"{self.year} {self.make} {self.model}" + (f" {self.trim}" if self.trim else "")


class VehicleFilters(BaseModel):
    q: str = Field(default="", max_length=60)
    body_type: BodyType | None = None
    make: str = Field(default="", max_length=40)
    max_price: int | None = Field(default=None, ge=0, le=1_000_000)
    sort: Literal["featured", "price_asc", "price_desc", "newest", "mileage"] = "featured"


class ChatRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    message: str = Field(min_length=1, max_length=1000)
    vehicle_id: int | None = None


class LeadUpdate(BaseModel):
    """What the assistant learned about the shopper on this turn ('' = nothing new)."""

    customer_name: str = ""
    contact: str = ""
    interest: str = ""


class AssistantTurn(BaseModel):
    reply: str
    lead: LeadUpdate = LeadUpdate()
    vehicle_ids: list[int] = []
