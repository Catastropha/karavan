"""Tests for hook app routes — webhook verification, webhook POST, and health check."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.apps.hook.model.output import HealthGetOut, WebhookPostOut
from app.apps.hook.route import health_check, set_agent_registry, trello_webhook, trello_webhook_verify
from app.common.cost import CostTracker
from tests.hook.conftest import sign_payload


# --- Helpers ---


VALID_PAYLOAD = {
    "action": {
        "type": "updateCard",
        "data": {
            "card": {"id": "card_abc", "name": "Fix login bug"},
            "listAfter": {"id": "todo_list_1", "name": "To Do"},
        },
    },
}


def _make_request(body: bytes, agent_name: str = "api", signature: str | None = None) -> MagicMock:
    """Build a mock FastAPI Request with body and headers."""
    request = MagicMock()
    request.body = MagicMock(return_value=body)
    # Make body() awaitable
    async def async_body():
        return body
    request.body = async_body
    callback_url = f"https://test.example.com/webhook/{agent_name}"
    if signature is None:
        signature = sign_payload(body, callback_url)
    request.headers = {"x-trello-webhook": signature}
    return request


# --- trello_webhook_verify ---


class TestTrelloWebhookVerify:
    async def test_returns_200(self):
        response = await trello_webhook_verify("api")
        assert response.status_code == 200

    async def test_any_agent_name(self):
        response = await trello_webhook_verify("some-unknown-agent")
        assert response.status_code == 200


# --- trello_webhook ---


class TestTrelloWebhook:
    async def test_queues_valid_event(self, agent_registry, mock_agent):
        """Valid signed payload with matching agent queues the event."""
        agent_registry.get_agent.return_value = mock_agent
        body = json.dumps(VALID_PAYLOAD).encode()
        request = _make_request(body, agent_name="api")

        result = await trello_webhook("api", request)

        assert result.ok is True
        assert not mock_agent.queue.empty()
        item = mock_agent.queue.get_nowait()
        assert item["card_id"] == "card_abc"
        assert item["card_name"] == "Fix login bug"
        assert item["action_type"] == "updateCard"
        assert item["list_after_id"] == "todo_list_1"

    async def test_returns_ok_on_invalid_signature(self, agent_registry):
        """Invalid signature still returns ok (prevents Trello retries)."""
        body = json.dumps(VALID_PAYLOAD).encode()
        request = _make_request(body, signature="bad_signature")

        result = await trello_webhook("api", request)

        assert result.ok is True
        agent_registry.get_agent.assert_not_called()

    async def test_returns_ok_on_missing_signature(self, agent_registry):
        """Missing signature header still returns ok."""
        body = json.dumps(VALID_PAYLOAD).encode()
        request = MagicMock()
        async def async_body():
            return body
        request.body = async_body
        request.headers = {}

        result = await trello_webhook("api", request)

        assert result.ok is True
        agent_registry.get_agent.assert_not_called()

    async def test_returns_ok_on_empty_signature(self, agent_registry):
        """Empty signature string still returns ok."""
        body = json.dumps(VALID_PAYLOAD).encode()
        request = MagicMock()
        async def async_body():
            return body
        request.body = async_body
        request.headers = {"x-trello-webhook": ""}

        result = await trello_webhook("api", request)

        assert result.ok is True
        agent_registry.get_agent.assert_not_called()

    async def test_returns_ok_on_malformed_json(self, agent_registry):
        """Malformed JSON body returns ok without crashing."""
        body = b"not valid json"
        callback_url = "https://test.example.com/webhook/api"
        sig = sign_payload(body, callback_url)
        request = _make_request(body, agent_name="api", signature=sig)

        result = await trello_webhook("api", request)

        assert result.ok is True

    async def test_returns_ok_when_no_card(self, agent_registry, mock_agent):
        """Payload without card data returns ok without queuing."""
        agent_registry.get_agent.return_value = mock_agent
        payload = {
            "action": {
                "type": "updateCard",
                "data": {"listAfter": {"id": "list1"}},
            },
        }
        body = json.dumps(payload).encode()
        request = _make_request(body, agent_name="api")

        result = await trello_webhook("api", request)

        assert result.ok is True
        assert mock_agent.queue.empty()

    async def test_returns_ok_when_no_list_after(self, agent_registry, mock_agent):
        """Payload without listAfter returns ok without queuing."""
        agent_registry.get_agent.return_value = mock_agent
        payload = {
            "action": {
                "type": "updateCard",
                "data": {"card": {"id": "c1", "name": "Task"}},
            },
        }
        body = json.dumps(payload).encode()
        request = _make_request(body, agent_name="api")

        result = await trello_webhook("api", request)

        assert result.ok is True
        assert mock_agent.queue.empty()

    async def test_returns_ok_when_registry_not_set(self):
        """No registry set returns ok (startup race condition)."""
        set_agent_registry(None)
        body = json.dumps(VALID_PAYLOAD).encode()
        request = _make_request(body, agent_name="api")

        result = await trello_webhook("api", request)

        assert result.ok is True

    async def test_returns_ok_when_agent_not_found(self, agent_registry):
        """Unknown agent name returns ok without crashing."""
        agent_registry.get_agent.return_value = None
        body = json.dumps(VALID_PAYLOAD).encode()
        request = _make_request(body, agent_name="unknown")

        result = await trello_webhook("unknown", request)

        assert result.ok is True

    async def test_skips_when_should_not_process(self, agent_registry, mock_agent):
        """Agent declines event via should_process_webhook — nothing queued."""
        agent_registry.get_agent.return_value = mock_agent
        mock_agent.should_process_webhook.return_value = False
        body = json.dumps(VALID_PAYLOAD).encode()
        request = _make_request(body, agent_name="api")

        result = await trello_webhook("api", request)

        assert result.ok is True
        assert mock_agent.queue.empty()
        mock_agent.should_process_webhook.assert_called_once_with("todo_list_1")

    async def test_calls_get_agent_with_name(self, agent_registry, mock_agent):
        """Verifies the correct agent_name is passed to the registry."""
        agent_registry.get_agent.return_value = mock_agent
        body = json.dumps(VALID_PAYLOAD).encode()
        request = _make_request(body, agent_name="reviewer")

        await trello_webhook("reviewer", request)

        agent_registry.get_agent.assert_called_once_with("reviewer")

    async def test_realistic_trello_payload(self, agent_registry, mock_agent):
        """Parse a full realistic Trello webhook payload with extra fields."""
        agent_registry.get_agent.return_value = mock_agent
        payload = {
            "action": {
                "id": "action123",
                "idMemberCreator": "member1",
                "type": "updateCard",
                "date": "2026-01-15T10:30:00.000Z",
                "data": {
                    "card": {"id": "c1", "name": "Deploy", "idShort": 42, "shortLink": "abc"},
                    "listAfter": {"id": "todo_1", "name": "To Do"},
                    "listBefore": {"id": "doing_1", "name": "Doing"},
                    "board": {"id": "board1", "name": "Project"},
                    "old": {"idList": "doing_1"},
                },
            },
            "model": {"id": "board1"},
        }
        body = json.dumps(payload).encode()
        request = _make_request(body, agent_name="api")

        result = await trello_webhook("api", request)

        assert result.ok is True
        item = mock_agent.queue.get_nowait()
        assert item["card_id"] == "c1"
        assert item["card_name"] == "Deploy"
        assert item["list_after_id"] == "todo_1"
        assert item["action_type"] == "updateCard"


# --- health_check ---


class TestHealthCheck:
    async def test_returns_ok_without_registry(self):
        """Health check works even when registry is not set."""
        set_agent_registry(None)
        result = await health_check()
        assert result.status == "ok"
        assert result.agents == {}

    async def test_returns_agent_statuses(self, agent_registry):
        """Health check includes per-agent status from registry."""
        agent_registry.get_all_status.return_value = {
            "api": {
                "running": True,
                "queue_depth": 2,
                "last_activity_at": 1700000000.0,
                "cards_processed": 10,
            },
        }
        result = await health_check()

        assert result.status == "ok"
        assert "api" in result.agents
        assert result.agents["api"].running is True
        assert result.agents["api"].queue_depth == 2
        assert result.agents["api"].cards_processed == 10

    async def test_includes_cost_data(self, agent_registry):
        """Health check includes cost tracker summaries."""
        tracker = CostTracker()
        tracker.record("api", 0.05, {"input_tokens": 1000, "output_tokens": 500}, "card1")
        tracker.record("api", 0.03, {"input_tokens": 800, "output_tokens": 300}, "card2")

        with patch("app.apps.hook.route.cost_tracker", tracker):
            result = await health_check()

        assert "api" in result.costs_by_agent
        assert result.costs_by_agent["api"]["executions"] == 2
        assert result.costs_by_agent["api"]["total_cost_usd"] == 0.08
        assert result.costs_total["total_executions"] == 2
        assert result.costs_total["total_cost_usd"] == 0.08

    async def test_empty_costs_when_no_executions(self, agent_registry):
        """Health check returns empty cost data when nothing has been tracked."""
        tracker = CostTracker()

        with patch("app.apps.hook.route.cost_tracker", tracker):
            result = await health_check()

        assert result.costs_by_agent == {}
        assert result.costs_total["total_cost_usd"] == 0
        assert result.costs_total["total_executions"] == 0

    async def test_multiple_agents_in_status(self, agent_registry):
        """Health check reports status for all registered agents."""
        agent_registry.get_all_status.return_value = {
            "api": {
                "running": True,
                "queue_depth": 0,
                "last_activity_at": 1700000000.0,
                "cards_processed": 5,
            },
            "reviewer": {
                "running": True,
                "queue_depth": 1,
                "last_activity_at": 1700000100.0,
                "cards_processed": 3,
            },
        }
        result = await health_check()

        assert len(result.agents) == 2
        assert result.agents["api"].cards_processed == 5
        assert result.agents["reviewer"].queue_depth == 1

    async def test_returns_health_get_out_type(self, agent_registry):
        """Health check returns the correct response model type."""
        result = await health_check()
        assert isinstance(result, HealthGetOut)
