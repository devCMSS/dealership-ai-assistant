"""The Claude provider is tested against a fake client: no network, no API key."""

import json
from types import SimpleNamespace

import pytest

from app.assistant.prompt import build_system_prompt
from app.assistant.providers import AssistantError, ClaudeProvider, DemoProvider
from app.models import AssistantTurn
from app.seed import DEMO_VEHICLES
from app.models import Vehicle

VEHICLES = [Vehicle(id=i + 1, **data) for i, data in enumerate(DEMO_VEHICLES)]


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_client(text="", stop_reason="end_turn", error=None):
    response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
    messages = FakeMessages(response, error)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_prompt_lists_inventory_with_body_types():
    prompt = build_system_prompt("Crestline Motors", VEHICLES)
    assert "#1 | 2022 Toyota Camry SE | [sedan]" in prompt
    assert f"Inventory ({len(VEHICLES)} vehicles" in prompt


def test_claude_provider_parses_structured_turn():
    payload = {"reply": "The RAV4 is a great fit.", "vehicle_ids": [5],
               "lead": {"customer_name": "Ana", "contact": "", "interest": "hybrid SUV"}}
    client, messages = fake_client(json.dumps(payload))
    turn = ClaudeProvider("claude-opus-5-5", client=client).respond("sys", [], "hi", VEHICLES, None)
    assert turn == AssistantTurn.model_validate(payload)
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["messages"][-1] == {"role": "user", "content": "hi"}


def test_claude_provider_handles_refusal():
    client, _ = fake_client("", stop_reason="refusal")
    turn = ClaudeProvider("claude-opus-5-5", client=client).respond("sys", [], "x", VEHICLES, None)
    assert "can't help" in turn.reply and turn.vehicle_ids == []


def test_claude_provider_rejects_malformed_output():
    client, _ = fake_client("not json")
    with pytest.raises(AssistantError):
        ClaudeProvider("claude-opus-5-5", client=client).respond("sys", [], "x", VEHICLES, None)


def test_demo_provider_respects_body_type_and_budget():
    turn = DemoProvider().respond("", [], "Any SUVs under $35k?", VEHICLES, None)
    by_id = {v.id: v for v in VEHICLES}
    assert turn.vehicle_ids
    assert all(by_id[i].body_type == "suv" and by_id[i].price <= 35000 for i in turn.vehicle_ids)


def test_demo_provider_respects_fuel():
    turn = DemoProvider().respond("", [], "Any hybrid SUVs under 35k?", VEHICLES, None)
    by_id = {v.id: v for v in VEHICLES}
    assert turn.vehicle_ids and all(by_id[i].fuel == "hybrid" for i in turn.vehicle_ids)


def test_demo_provider_captures_lead():
    turn = DemoProvider().respond("", [], "My name is Ana, call me at +1 555 010 7788", VEHICLES, VEHICLES[4])
    assert turn.lead.customer_name == "Ana"
    assert turn.lead.contact == "+1 555 010 7788"
