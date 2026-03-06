"""
Integration test: full backend message flow.
Tests the complete path from WebSocket command to agent response.
"""
import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.aetherbrowser.serve import app

client = TestClient(app)


def _collect(ws, *, max_msgs: int = 50, done_agent: str = "KO") -> list[dict]:
    """Collect messages until we see *done_agent* status=done or hit max."""
    messages = []
    for _ in range(max_msgs):
        try:
            msg = ws.receive_json()
            messages.append(msg)
            if (msg["type"] == "agent_status"
                    and msg.get("agent") == done_agent
                    and msg["payload"].get("state") == "done"):
                break
        except Exception:
            break
    return messages


class TestFullCommandFlow:
    def test_command_produces_agent_messages(self):
        """A command should produce KO status + streaming/chat + KO done.

        v0.3 flow: decompose -> assign agents -> stream LLM (echo fallback) -> done.
        """
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "command",
                "agent": "user",
                "payload": {"text": "Explain hyperbolic geometry for AI safety"},
            })
            messages = _collect(ws, done_agent="KO")

            types = [m["type"] for m in messages]
            agents = [m.get("agent") for m in messages]

            assert "agent_status" in types
            assert any(t in types for t in ("chat", "stream"))
            assert "KO" in agents

    def test_research_command_falls_back_without_browser(self):
        """Research commands fall back to LLM path when browser unavailable."""
        with patch("src.aetherbrowser.serve.browser_bridge") as mock_bb:
            mock_bb.is_available.return_value = False
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "type": "command",
                    "agent": "user",
                    "payload": {"text": "Research hyperbolic competitors"},
                })
                messages = _collect(ws, done_agent="KO")

                types = [m["type"] for m in messages]
                assert "agent_status" in types
                assert any(t in types for t in ("chat", "stream"))

    def test_page_context_produces_analysis(self):
        """Sending page context should produce CA analysis with metadata.

        v0.3 flow: CA analyzing -> CA chat (metadata + analysis) -> CA done.
        Short text (< 100 words) skips KO enrichment, so CA done is the last msg.
        """
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "page_context",
                "agent": "user",
                "payload": {
                    "url": "https://example.com/ai-safety",
                    "title": "AI Safety Research",
                    "text": "Machine learning security requires governance frameworks. "
                            "Neural networks need adversarial defense mechanisms. "
                            "Hyperbolic geometry provides exponential cost scaling.",
                },
            })
            messages = _collect(ws, done_agent="CA")

            ca_msgs = [m for m in messages if m.get("agent") == "CA"]
            assert len(ca_msgs) >= 1

    def test_health_reflects_squad_state(self):
        """Health endpoint should show all 6 agents."""
        r = client.get("/health")
        data = r.json()
        assert data["status"] == "ok"
        assert len(data["agents"]) == 6


class TestErrorHandling:
    def test_empty_command_returns_error(self):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "command",
                "agent": "user",
                "payload": {"text": ""},
            })
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_malformed_json_handled(self):
        with client.websocket_connect("/ws") as ws:
            ws.send_text("not json at all")
            msg = ws.receive_json()
            assert msg["type"] == "error"
