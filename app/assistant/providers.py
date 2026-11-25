"""Assistant back-ends.

- ClaudeProvider: calls the Claude API with structured outputs, so every turn comes back as
  validated JSON (reply + lead fields + vehicle ids).
- DemoProvider: a deterministic, offline stand-in so the project runs with no API key. It is
  intentionally simple; it exists to demo the UI and the lead pipeline, not to compete with
  the model.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from ..body_type import detect_requested
from ..models import AssistantTurn, LeadUpdate, Vehicle

log = logging.getLogger(__name__)


class AssistantError(RuntimeError):
    """The provider could not produce a turn (network, auth, refusal, bad output)."""


class Provider(Protocol):
    name: str

    def respond(self, system: str, history: list[dict[str, str]], message: str,
                vehicles: list[Vehicle], viewing: Vehicle | None) -> AssistantTurn: ...


TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "lead": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "contact": {"type": "string"},
                "interest": {"type": "string"},
            },
            "required": ["customer_name", "contact", "interest"],
            "additionalProperties": False,
        },
        "vehicle_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["reply", "lead", "vehicle_ids"],
    "additionalProperties": False,
}


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str, client=None):
        import anthropic  # imported lazily so the demo runs without the SDK configured

        self._anthropic = anthropic
        self.model = model
        self.client = client or anthropic.Anthropic()

    def respond(self, system, history, message, vehicles, viewing) -> AssistantTurn:
        anthropic = self._anthropic
        messages = [*history, {"role": "user", "content": message}]
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=messages,
                # Chat replies are short and latency-sensitive: low effort is enough.
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": TURN_SCHEMA}},
                # If a safety classifier declines, the API retries on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
        except anthropic.AuthenticationError as exc:
            raise AssistantError("Anthropic credentials are invalid.") from exc
        except anthropic.RateLimitError as exc:
            raise AssistantError("Rate limited by the API.") from exc
        except anthropic.APIStatusError as exc:
            raise AssistantError(f"API error {exc.status_code}.") from exc
        except anthropic.APIConnectionError as exc:
            raise AssistantError("Could not reach the API.") from exc

        if response.stop_reason == "refusal":
            return AssistantTurn(reply="Sorry, I can't help with that. Ask me about our vehicles, "
                                       "test drives or financing.")
        if response.stop_reason == "max_tokens":
            raise AssistantError("Reply was cut off.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return AssistantTurn.model_validate(json.loads(text))
        except (ValueError, TypeError) as exc:
            raise AssistantError("Model returned an unexpected format.") from exc


# ── Offline demo provider ────────────────────────────────────────────────────

_NAME = re.compile(r"\b(?i:my name is|i am|i'm|this is|call me)\s+([A-Z][a-zA-Z'-]{1,30})")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_BUDGET = re.compile(r"(?:under|below|less than|max(?:imum)?|budget(?: is| of)?|up to)\s*\$?\s*"
                     r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?", re.IGNORECASE)
_GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening))\b[\s!.,]*$", re.IGNORECASE)
_FUELS = {
    "hybrid": re.compile(r"\bhybrids?\b", re.IGNORECASE),
    "electric": re.compile(r"\b(?:electric|ev|evs|battery)\b", re.IGNORECASE),
    "diesel": re.compile(r"\bdiesel\b", re.IGNORECASE),
}
_INTEREST = re.compile(r"test drive|financ|trade|appointment|visit|interested|buy|book", re.IGNORECASE)


def _budget(text: str) -> int | None:
    match = _BUDGET.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    if match.group(2) or value < 1000:
        value *= 1000
    return int(value)


class DemoProvider:
    name = "demo"

    def respond(self, system, history, message, vehicles, viewing) -> AssistantTurn:
        text = message.split("\n", 1)[-1] if message.startswith("(Shopper is viewing") else message
        lead = LeadUpdate()
        if m := _NAME.search(text):
            lead.customer_name = m.group(1)
        if m := _EMAIL.search(text) or _PHONE.search(text):
            lead.contact = m.group(0).strip()

        already_asked = any("first name" in h["content"] for h in history if h["role"] == "assistant")
        if lead.customer_name or lead.contact:
            lead.interest = f"interested in #{viewing.id} {viewing.title}" if viewing else ""
            who = f", {lead.customer_name}" if lead.customer_name else ""
            reply = (f"Thanks{who}! A sales advisor will reach out shortly to confirm the details. "
                     "Anything else I can look up for you meanwhile?")
            if not lead.contact:
                reply = (f"Thanks{who}! What's the best phone number or email for our advisor "
                         "to reach you?")
            return AssistantTurn(reply=reply, lead=lead)

        if _GREETING.match(text):
            return AssistantTurn(reply="Hi! I can help you find a car from our current inventory. "
                                       "What are you looking for? A body type, a budget or a make "
                                       "is a great place to start.")

        if viewing and _INTEREST.search(text):
            reply = (f"Great choice, the {viewing.title} is listed at ${viewing.price:,}. "
                     "Could I get your first name and a phone number or email so an advisor can "
                     "set that up with you?")
            return AssistantTurn(reply=reply, vehicle_ids=[viewing.id])

        body = detect_requested(text)
        budget = _budget(text)
        makes = {v.make.lower() for v in vehicles}
        make = next((mk for mk in makes if re.search(rf"\b{re.escape(mk)}\b", text.lower())), None)

        fuel = next((f for f, pattern in _FUELS.items() if pattern.search(text)), None)

        matches = [v for v in vehicles
                   if (body is None or v.body_type == body)
                   and (budget is None or v.price <= budget)
                   and (make is None or v.make.lower() == make)
                   and (fuel is None or v.fuel == fuel)]
        if not (body or budget or make or fuel):
            if viewing:
                return AssistantTurn(
                    reply=(f"The {viewing.title} is a {viewing.condition} {viewing.body_type} with "
                           f"{viewing.mileage:,} miles, {viewing.transmission} transmission, listed at "
                           f"${viewing.price:,}. Want to book a test drive?"),
                    vehicle_ids=[viewing.id])
            return AssistantTurn(reply="Tell me a bit more: are you after a sedan, SUV, pickup or "
                                       "something else? A budget helps too.")

        if not matches:
            closest = sorted((v for v in vehicles if body is None or v.body_type == body),
                             key=lambda v: v.price)[:3]
            what = " ".join(p for p in (fuel, body or (make.title() if make else "vehicle")) if p)
            reply = f"I don't have a {what} that fits that right now."
            if closest:
                reply += " The closest options I do have are below."
            return AssistantTurn(reply=reply, vehicle_ids=[v.id for v in closest])

        top = sorted(matches, key=lambda v: (not v.featured, v.price))[:3]
        reply = f"I found {len(matches)} option{'s' if len(matches) != 1 else ''} for you."
        reply += " Here are the best matches."
        if not already_asked:
            reply += (" If one catches your eye, share your first name and a phone or email and an "
                      "advisor will set up a test drive.")
        return AssistantTurn(reply=reply, vehicle_ids=[v.id for v in top])


def _has_anthropic_credentials() -> bool:
    """The SDK resolves an API key, an auth token or an `ant auth login` profile."""
    import os
    from pathlib import Path

    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()


def build_provider(kind: str, model: str) -> Provider:
    """'claude' forces the API, 'demo' forces offline mode, 'auto' uses Claude when the SDK
    can find credentials and falls back to the demo otherwise."""
    if kind == "demo":
        return DemoProvider()
    if kind == "auto" and not _has_anthropic_credentials():
        log.info("No Anthropic credentials found; using the offline demo assistant.")
        return DemoProvider()
    if kind in {"claude", "auto"}:
        try:
            return ClaudeProvider(model)
        except Exception as exc:  # missing SDK or credentials
            if kind == "claude":
                raise
            log.info("Claude unavailable (%s); using the offline demo assistant.", exc)
    return DemoProvider()
