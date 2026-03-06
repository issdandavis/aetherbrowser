"""Tests for the FastAPI server v0.3 (merged Claude + Codex lanes)."""
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from src.aetherbrowser.serve import app, _extract_research_query
from src.aetherbrowser.model_bridge import BridgeResponse
from src.aetherbrowser.browser_bridge import BrowserResearchReport

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "agents" in data

    def test_health_shows_agent_count(self):
        r = client.get("/health")
        data = r.json()
        assert len(data["agents"]) == 6

    def test_health_shows_version_03(self):
        r = client.get("/health")
        data = r.json()
        assert data["version"] == "0.3.0"

    def test_health_shows_providers(self):
        r = client.get("/health")
        data = r.json()
        assert "providers" in data
        assert isinstance(data["providers"], list)

    def test_health_shows_browser_available(self):
        r = client.get("/health")
        data = r.json()
        assert "browser_available" in data
        assert isinstance(data["browser_available"], bool)


class TestResearchQueryExtraction:
    def test_bracket_prefix(self):
        assert _extract_research_query("[Research] quantum ai") == "quantum ai"

    def test_colon_prefix(self):
        assert _extract_research_query("research: deep learning") == "deep learning"

    def test_space_prefix(self):
        assert _extract_research_query("research transformers") == "transformers"

    def test_no_prefix(self):
        assert _extract_research_query("hello world") is None

    def test_empty(self):
        assert _extract_research_query("") is None

    def test_research_only(self):
        assert _extract_research_query("research") is None

    def test_case_insensitive(self):
        assert _extract_research_query("[RESEARCH] safety") == "safety"


class TestWebSocket:
    def test_ws_connect_and_command(self):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "command", "agent": "user", "payload": {"text": "Hello"}})
            response = ws.receive_json()
            assert response["type"] in ("chat", "agent_status", "stream", "error")
            assert "seq" in response

    def test_ws_page_context(self):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "page_context",
                "agent": "user",
                "payload": {
                    "url": "https://github.com/test",
                    "title": "Example",
                    "text": "This is a test page about AI safety and governance.",
                },
            })
            response = ws.receive_json()
            assert response["type"] in ("chat", "agent_status")

    def test_ws_rejects_invalid_type(self):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hacked", "agent": "user", "payload": {}})
            response = ws.receive_json()
            assert response["type"] == "error"

    def test_ws_empty_command_returns_error(self):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "command", "agent": "user", "payload": {"text": ""}})
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "Empty" in response["payload"]["reason"]

    def test_ws_command_gets_streaming_response(self):
        """Command should produce stream chunks when model bridge returns data."""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "command", "agent": "user", "payload": {"text": "Hello world chat"}})
            messages = []
            for _ in range(50):
                try:
                    msg = ws.receive_json()
                    messages.append(msg)
                    if msg["type"] == "agent_status" and msg["agent"] == "KO" and msg["payload"]["state"] == "done":
                        break
                except Exception:
                    break
            types = [m["type"] for m in messages]
            assert "agent_status" in types
            assert any(t in types for t in ("stream", "chat"))

    def test_ws_page_context_green_zone_no_approval(self):
        """GREEN zone URLs should not trigger zone_request."""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "page_context",
                "agent": "user",
                "payload": {
                    "url": "https://github.com/test",
                    "title": "GitHub",
                    "text": "A GitHub page with plenty of content to analyze properly. " * 20,
                },
            })
            messages = []
            for _ in range(20):
                try:
                    msg = ws.receive_json()
                    messages.append(msg)
                    if msg["type"] == "agent_status" and msg["payload"].get("state") == "done":
                        break
                except Exception:
                    break
            types = [m["type"] for m in messages]
            assert "zone_request" not in types

    def test_ws_page_context_includes_metadata(self):
        """Page context should include PollyVision-style metadata."""
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "page_context",
                "agent": "user",
                "payload": {
                    "url": "https://github.com/ai",
                    "title": "AI Example",
                    "text": ("This page discusses governance and model routing. " * 40),
                },
            })
            for _ in range(30):
                msg = ws.receive_json()
                if msg["type"] == "chat" and msg["agent"] == "CA":
                    text = msg["payload"]["text"]
                    # Should have reading time and zone from _build_page_metadata
                    assert "Reading time" in text or "Zone" in text or "Token est" in text
                    break


class TestResearchCommand:
    def test_research_routes_through_browser_bridge(self):
        """Research commands use BrowserBridge when available."""
        fake_report = BrowserResearchReport(
            query="quantum ai",
            extractions=[{"url": "https://example.com", "text": "test content"}],
            urls_discovered=3,
            urls_safe=2,
            urls_blocked=1,
            used_browser=True,
            funnel_receipt={
                "run_id": "r1",
                "local_path": "training/intake/web_research_r1.jsonl",
                "records_written": 1,
                "hf_committed": False,
            },
        )

        async def fake_research(query, max_urls=5, head_id="sidebar"):
            return fake_report

        with patch("src.aetherbrowser.serve.browser_bridge") as mock_bb:
            mock_bb.is_available.return_value = True
            mock_bb.research = fake_research
            mock_bb.persist_extractions = AsyncMock(return_value=None)

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "command", "agent": "user", "payload": {"text": "[Research] quantum ai"}})
                seen_progress_done = False
                seen_summary = False
                for _ in range(30):
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    if msg["type"] == "progress" and msg["payload"].get("current") == 4:
                        seen_progress_done = True
                    if msg["type"] == "chat" and msg["agent"] == "DR":
                        if "Local JSONL" in msg["payload"]["text"]:
                            seen_summary = True
                    if seen_progress_done and seen_summary:
                        break
                assert seen_progress_done is True
                assert seen_summary is True

    def test_research_failure_returns_error(self):
        """Research command errors are reported cleanly."""
        async def failing_research(query, max_urls=5, head_id="sidebar"):
            return BrowserResearchReport(
                query=query,
                error="Playwright not installed",
                used_browser=False,
            )

        with patch("src.aetherbrowser.serve.browser_bridge") as mock_bb:
            mock_bb.is_available.return_value = True
            mock_bb.research = failing_research

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "command", "agent": "user", "payload": {"text": "research deep topic"}})
                # Server sends: chat, progress, agent_status(AV scouting),
                # error, agent_status(AV done) = 5 messages
                messages = [ws.receive_json() for _ in range(5)]
                assert any(
                    m["type"] == "error" and "Research pipeline failed" in m["payload"]["reason"]
                    for m in messages
                )

    def test_research_falls_back_to_llm_when_no_browser(self):
        """Without browser, research commands use normal LLM path."""
        with patch("src.aetherbrowser.serve.browser_bridge") as mock_bb:
            mock_bb.is_available.return_value = False

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "command", "agent": "user", "payload": {"text": "research AI safety"}})
                messages = []
                for _ in range(50):
                    try:
                        msg = ws.receive_json()
                        messages.append(msg)
                        if msg["type"] == "agent_status" and msg["agent"] == "KO" and msg["payload"]["state"] == "done":
                            break
                    except Exception:
                        break
                types = [m["type"] for m in messages]
                # Should fall back to normal LLM streaming
                assert "agent_status" in types
                assert any(t in types for t in ("stream", "chat"))


class TestDisconnectEdgeCases:
    def test_disconnect_reconnect_keeps_server_healthy(self):
        """Server stays healthy after a client disconnects."""
        with client.websocket_connect("/ws") as ws1:
            ws1.send_json({"type": "hacked", "agent": "user", "payload": {}})
            resp = ws1.receive_json()
            assert resp["type"] == "error"

        # New connection should work fine
        with client.websocket_connect("/ws") as ws2:
            ws2.send_json({"type": "command", "agent": "user", "payload": {"text": "hello again"}})
            resp2 = ws2.receive_json()
            assert resp2["type"] in ("agent_status", "chat", "stream", "error")

    def test_multiple_rapid_connections(self):
        """Multiple rapid connect/disconnect cycles don't crash the server."""
        for i in range(5):
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "command", "agent": "user", "payload": {"text": f"msg {i}"}})
                ws.receive_json()  # Just get one response
        # Health check still works
        r = client.get("/health")
        assert r.status_code == 200

    def test_oversized_message_doesnt_crash(self):
        """Sending oversized messages returns an error, doesn't crash."""
        with client.websocket_connect("/ws") as ws:
            big_payload = "x" * 1_100_000
            ws.send_text(big_payload)
            # Should get an error (either from JSON parsing or size guard)
            resp = ws.receive_json()
            assert resp["type"] == "error"


class TestStreamProtocol:
    def test_ws_feed_stream_chunk(self):
        from src.aetherbrowser.ws_feed import WsFeed, MsgType, Agent
        feed = WsFeed()
        msg = feed.stream_chunk(Agent.KO, "hello ", done=False, model="opus")
        assert msg["type"] == MsgType.STREAM.value
        assert msg["payload"]["chunk"] == "hello "
        assert msg["payload"]["done"] is False
        assert msg["model"] == "opus"

    def test_ws_feed_stream_done(self):
        from src.aetherbrowser.ws_feed import WsFeed, Agent
        feed = WsFeed()
        msg = feed.stream_chunk(Agent.KO, "", done=True)
        assert msg["payload"]["done"] is True
        assert msg["payload"]["chunk"] == ""
