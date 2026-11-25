"""One chat turn: load history and live inventory, ask the provider, keep only real vehicle
ids, persist the exchange and merge any lead details."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..models import ChatRequest, Vehicle, VehicleFilters
from ..repository import ChatRepository, LeadRepository, VehicleRepository
from .prompt import build_system_prompt, with_page_context
from .providers import AssistantError, DemoProvider, Provider

log = logging.getLogger(__name__)


@dataclass
class ChatResult:
    reply: str
    vehicles: list[Vehicle] = field(default_factory=list)
    lead_saved: bool = False
    provider: str = ""


class ChatService:
    def __init__(self, provider: Provider, vehicles: VehicleRepository, chats: ChatRepository,
                 leads: LeadRepository, dealership_name: str, history_limit: int = 16):
        self.provider = provider
        self.vehicles = vehicles
        self.chats = chats
        self.leads = leads
        self.dealership_name = dealership_name
        self.history_limit = history_limit
        self._fallback = DemoProvider()

    def handle(self, req: ChatRequest) -> ChatResult:
        inventory = self.vehicles.search(VehicleFilters(), limit=200)
        by_id = {v.id: v for v in inventory}
        viewing = by_id.get(req.vehicle_id) if req.vehicle_id else None

        history = self.chats.history(req.session_id, self.history_limit)
        system = build_system_prompt(self.dealership_name, inventory)
        message = with_page_context(req.message.strip(), viewing)

        provider_name = self.provider.name
        try:
            turn = self.provider.respond(system, history, message, inventory, viewing)
        except AssistantError as exc:
            log.warning("Assistant provider failed (%s); answering with the offline fallback.", exc)
            turn = self._fallback.respond(system, history, message, inventory, viewing)
            provider_name = "demo-fallback"

        # The model may only point at vehicles that exist and are on sale right now.
        cards = [by_id[i] for i in dict.fromkeys(turn.vehicle_ids) if i in by_id][:4]

        self.chats.append(req.session_id, "user", message)
        self.chats.append(req.session_id, "assistant", turn.reply)
        lead_saved = self.leads.upsert(req.session_id, turn.lead)
        return ChatResult(reply=turn.reply, vehicles=cards, lead_saved=lead_saved,
                          provider=provider_name)
